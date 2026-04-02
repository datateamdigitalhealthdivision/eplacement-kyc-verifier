"""Spreadsheet loader with configurable column resolution."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from src.settings import load_yaml_config
from src.utils.text_cleaning import extract_pdf_stem_identifier, looks_like_scientific_notation, normalize_identifier, normalize_whitespace


@dataclass(slots=True)
class ApplicantRecord:
    row_index: int
    applicant_id: str
    canonical: dict[str, Any]
    raw: dict[str, Any]


@dataclass(slots=True)
class SpreadsheetBundle:
    source_path: Path
    original_df: pd.DataFrame
    canonical_df: pd.DataFrame
    records: list[ApplicantRecord]
    resolved_columns: dict[str, str | None]
    missing_required: list[str]
    warnings: list[str]


class SpreadsheetLoader:
    def __init__(self, project_root: str | Path | None = None) -> None:
        self.mapping = load_yaml_config("column_mapping.yaml", project_root=project_root)

    @staticmethod
    def _normalize_header(header: str) -> str:
        return normalize_whitespace(str(header)).casefold()

    def resolve_columns(self, columns: list[str]) -> tuple[dict[str, str | None], list[str]]:
        normalized_headers = {self._normalize_header(column): column for column in columns}
        resolved: dict[str, str | None] = {}
        missing_required: list[str] = []
        for canonical, spec in self.mapping.get("columns", {}).items():
            aliases = spec.get("aliases", [])
            selected = None
            for alias in aliases:
                if self._normalize_header(alias) in normalized_headers:
                    selected = normalized_headers[self._normalize_header(alias)]
                    break
            resolved[canonical] = selected
            if spec.get("required") and selected is None:
                missing_required.append(canonical)
        return resolved, missing_required

    @staticmethod
    def _read_csv(path: Path) -> pd.DataFrame:
        return pd.read_csv(path, dtype=str, keep_default_na=False, na_filter=False)

    @staticmethod
    def _read_excel(path: Path) -> pd.DataFrame:
        return pd.read_excel(path, dtype=str).fillna("")

    @classmethod
    def _load_frame(cls, path: Path) -> pd.DataFrame:
        if not path.exists():
            raise FileNotFoundError(f"Spreadsheet not found: {path}")
        if path.is_dir():
            raise ValueError(f"Spreadsheet path points to a directory, not a file: {path}")

        suffix = path.suffix.lower()
        if suffix == ".csv":
            return cls._read_csv(path)
        if suffix in {".xlsx", ".xls"}:
            return cls._read_excel(path)

        for reader in (cls._read_csv, cls._read_excel):
            try:
                return reader(path)
            except Exception:  # noqa: BLE001
                continue

        normalized_suffix = path.suffix or "<no extension>"
        raise ValueError(f"Unsupported spreadsheet format: {normalized_suffix}")

    @staticmethod
    def _normalize_applicant_identifier(raw_value: str, pdf_filename: str) -> tuple[str, bool]:
        normalized_raw = normalize_whitespace(raw_value)
        pdf_identifier = extract_pdf_stem_identifier(pdf_filename)
        if looks_like_scientific_notation(normalized_raw) and pdf_identifier:
            return pdf_identifier, True
        return normalize_identifier(normalized_raw), False

    def load(self, path: str | Path) -> SpreadsheetBundle:
        source_path = Path(path)
        df = self._load_frame(source_path)
        resolved, missing_required = self.resolve_columns(list(df.columns))
        canonical_df = df.copy()
        warnings: list[str] = []

        for canonical, source in resolved.items():
            canonical_df[canonical] = canonical_df[source] if source else ""
            canonical_df[canonical] = canonical_df[canonical].astype(str).fillna("").map(normalize_whitespace)

        recovered_applicant_ids = 0
        if "applicant_id" in canonical_df.columns:
            normalized_ids: list[str] = []
            for _, row in canonical_df.iterrows():
                normalized_id, recovered = self._normalize_applicant_identifier(
                    str(row.get("applicant_id", "") or ""),
                    str(row.get("pdf_filename", "") or ""),
                )
                recovered_applicant_ids += int(recovered)
                normalized_ids.append(normalized_id)
            canonical_df["applicant_id"] = normalized_ids

        if "spouse_id" in canonical_df.columns:
            canonical_df["spouse_id"] = canonical_df["spouse_id"].map(normalize_identifier)

        if recovered_applicant_ids:
            warnings.append(
                f"Recovered applicant_id from PDF filename for {recovered_applicant_ids} rows with lossy scientific notation."
            )

        if canonical_df["applicant_id"].duplicated().any():
            warnings.append("Duplicate applicant_id values detected in master spreadsheet.")

        records = [
            ApplicantRecord(
                row_index=index,
                applicant_id=str(row.get("applicant_id", "")),
                canonical=row.to_dict(),
                raw=df.iloc[index].to_dict(),
            )
            for index, (_, row) in enumerate(canonical_df.iterrows())
            if str(row.get("applicant_id", "")).strip()
        ]
        if missing_required:
            warnings.append(f"Missing required canonical columns: {', '.join(missing_required)}")
        return SpreadsheetBundle(
            source_path=source_path,
            original_df=df,
            canonical_df=canonical_df,
            records=records,
            resolved_columns=resolved,
            missing_required=missing_required,
            warnings=warnings,
        )
