"""Data access helpers for the Streamlit first-pass UI."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

from app.bootstrap import SERVICE, SETTINGS, SUPPORTED_SPREADSHEET_SUFFIXES
from src.reports.decision_queue import build_decision_queue
from src.reports.scoring_sheet import build_scoring_sheet, write_scoring_sheet_xlsx


TICK_COLUMNS = [
    "marriage",
    "self_illness",
    "family_illness",
    "spouse_location",
    "oku_self_or_family",
    "medex_other_exam",
]
STATUS_VALUES = {"present", "not_present", "manual_check"}


def candidate_applicant_paths() -> list[Path]:
    applicants_dir = SETTINGS.paths.applicants_dir
    if not applicants_dir.exists():
        return []
    candidates = [
        path
        for path in applicants_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_SPREADSHEET_SUFFIXES
    ]
    return sorted(candidates, key=lambda path: path.stat().st_mtime, reverse=True)


def initialize_session_state() -> None:
    if not str(st.session_state.get("applicant_path", "")).strip():
        candidates = candidate_applicant_paths()
        st.session_state["applicant_path"] = str(candidates[0]) if candidates else ""
    st.session_state.setdefault("pdf_directory", str(SETTINGS.paths.pdf_dir))
    st.session_state.setdefault("auto_download", True)
    st.session_state.setdefault("last_job_id", "")


def save_upload(uploaded_file) -> str | None:
    if uploaded_file is None:
        return None
    filename = Path(uploaded_file.name or "uploaded_applicants.csv").name
    if not Path(filename).suffix:
        filename = f"{filename}.csv"
    target = SETTINGS.paths.applicants_dir / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(uploaded_file.getbuffer())
    return str(target)


def validate_applicant_path(applicant_path: str) -> str | None:
    normalized = applicant_path.strip()
    if not normalized:
        return "Upload a CSV/XLSX file or enter a spreadsheet path before running verification."
    path = Path(normalized)
    if not path.exists():
        return f"Applicant spreadsheet not found: {path}"
    if path.is_dir():
        return f"Applicant spreadsheet path points to a folder, not a file: {path}"
    return None


def read_preview_frame(path: Path, limit: int = 8) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path, nrows=limit)
    if suffix in {".xlsx", ".xls"}:
        return pd.read_excel(path, nrows=limit)
    return pd.read_csv(path, nrows=limit)


def latest_job():
    return SERVICE.store.latest_job()


def latest_bundle(job_id: str | None = None):
    return SERVICE.latest_exports(job_id)


def _refresh_bundle_exports(bundle: Any) -> None:
    if bundle is None or not getattr(bundle, "merged_csv", None):
        return
    merged_path = Path(bundle.merged_csv)
    if not merged_path.exists():
        return
    merged_df = pd.read_csv(merged_path, dtype=str, keep_default_na=False)
    decision_df = build_decision_queue(merged_df, [])
    if bundle.decision_csv:
        Path(bundle.decision_csv).parent.mkdir(parents=True, exist_ok=True)
        decision_df.to_csv(bundle.decision_csv, index=False)
    if bundle.decision_xlsx:
        decision_df.to_excel(bundle.decision_xlsx, index=False)
    scoring_df = build_scoring_sheet(decision_df, SETTINGS, bundle.job_id)
    if bundle.scoring_csv:
        scoring_df.to_csv(bundle.scoring_csv, index=False)
    if bundle.scoring_xlsx:
        write_scoring_sheet_xlsx(scoring_df, bundle.scoring_xlsx)


def decision_dataframe(bundle: Any) -> pd.DataFrame | None:
    if bundle is None or not bundle.decision_csv:
        return None
    _refresh_bundle_exports(bundle)
    path = Path(bundle.decision_csv)
    if not path.exists():
        return None
    df = pd.read_csv(path, dtype=str, keep_default_na=False)
    columns = [
        column
        for column in [
            "applicant_id",
            "marriage",
            "self_illness",
            "family_illness",
            "spouse_location",
            "oku_self_or_family",
            "medex_other_exam",
            "check_required",
            "open_original_pdf",
            "source_pdf_name",
        ]
        if column in df.columns
    ]
    return df[columns]
