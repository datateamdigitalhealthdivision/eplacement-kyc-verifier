"""Build a simplified applicant-level decision queue for operators."""

from __future__ import annotations

import re
from urllib.parse import quote

import pandas as pd

from src.extraction.evidence_models import EvidenceResult


DEFAULT_PDF_BASE_URL = "https://eplacement-2.s3.ap-southeast-5.amazonaws.com/"


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _normalize_identifier(value) -> str:
    text = _text(value)
    if re.fullmatch(r"\d+\.0+", text):
        return text.split(".", 1)[0]
    return text


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    text = _text(value).casefold()
    return text in {"1", "true", "yes", "y"}


def _source_info_map(evidence_rows: list[EvidenceResult]) -> dict[str, dict[str, str]]:
    mapping: dict[str, dict[str, str]] = {}
    for row in evidence_rows:
        applicant_id = _normalize_identifier(row.applicant_id)
        if not applicant_id:
            continue
        info = mapping.setdefault(applicant_id, {"source_pdf_name": "", "original_pdf_url": ""})
        if row.source_pdf_name and not info["source_pdf_name"]:
            info["source_pdf_name"] = row.source_pdf_name
        if row.download_url and not info["original_pdf_url"]:
            info["original_pdf_url"] = row.download_url
    return mapping


def _build_original_pdf_url(original_pdf_url: str, source_pdf_name: str) -> str:
    url = _text(original_pdf_url)
    if url.lower().startswith(("http://", "https://")):
        return url
    filename = _text(source_pdf_name)
    if not filename:
        return ""
    return f"{DEFAULT_PDF_BASE_URL}{quote(filename)}"


def _doc_status(row: pd.Series, *, primary_type: str, exact_flag: str, signal_flag: str) -> str:
    detected_primary = _text(row.get("KYC_DETECTED_PRIMARY_DOC"))
    has_exact = _as_bool(row.get(exact_flag))
    has_signal = _as_bool(row.get(signal_flag))
    if detected_primary == primary_type or has_exact:
        return "present"
    if has_signal:
        return "manual_check"
    return "not_present"


def _oku_status(row: pd.Series) -> str:
    if _as_bool(row.get("KYC_DETECTED_OKU_DOCUMENT")) or _as_bool(row.get("KYC_DETECTED_OKU_EVIDENCE")):
        return "present"
    return "not_present"


def _doc_summary(label: str, doc_status: str) -> str:
    if doc_status == "present":
        return f"{label} present."
    if doc_status == "not_present":
        return f"{label} not present."
    return f"{label} unclear; manual check needed."


def build_decision_queue(merged_df: pd.DataFrame, evidence_rows: list[EvidenceResult]) -> pd.DataFrame:
    source_info = _source_info_map(evidence_rows)
    rows: list[dict[str, object]] = []

    for _, row in merged_df.iterrows():
        applicant_id = _normalize_identifier(row.get("KYC_APPLICANT_ID_NORMALIZED") or row.get("applicant_id") or row.get("NO KP"))
        if not applicant_id:
            continue
        applicant_source = source_info.get(applicant_id, {"source_pdf_name": "", "original_pdf_url": ""})

        marriage_doc = _doc_status(
            row,
            primary_type="marriage_certificate",
            exact_flag="KYC_DETECTED_MARRIAGE_CERTIFICATE",
            signal_flag="KYC_DETECTED_MARRIAGE_EVIDENCE",
        )
        medex_doc = _doc_status(
            row,
            primary_type="medex_or_exam_document",
            exact_flag="KYC_DETECTED_MEDEX_EXAM_DOCUMENT",
            signal_flag="KYC_DETECTED_MEDEX_EVIDENCE",
        )
        oku_doc = _oku_status(row)

        summary = " | ".join(
            [
                _doc_summary("Marriage certificate", marriage_doc),
                _doc_summary("MedEX/exam document", medex_doc),
                _doc_summary("OKU evidence", oku_doc),
            ]
        )

        source_pdf_name = applicant_source.get("source_pdf_name", "")
        original_pdf_url = _build_original_pdf_url(applicant_source.get("original_pdf_url", ""), source_pdf_name)
        check_required = "check" if "manual_check" in {marriage_doc, medex_doc, oku_doc} else "no_check"

        rows.append(
            {
                "applicant_id": applicant_id,
                "marriage_doc": marriage_doc,
                "medex_exam_doc": medex_doc,
                "oku_doc": oku_doc,
                "check_required": check_required,
                "summary": summary,
                "original_pdf_url": original_pdf_url,
                "open_original_pdf": original_pdf_url,
                "source_pdf_name": source_pdf_name,
                "_check_sort": 0 if check_required == "check" else 1,
            }
        )

    decision_df = pd.DataFrame(rows)
    if decision_df.empty:
        return decision_df
    decision_df = decision_df.sort_values(by=["_check_sort", "applicant_id"], ascending=[True, True], kind="stable")
    return decision_df.drop(columns=["_check_sort"])
