"""Build a claim-guided applicant decision queue for operators."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import quote

import pandas as pd

from src.extraction.evidence_models import EvidenceResult
from src.rules.validators import row_claim_is_married, row_has_oku_claim, row_has_postgraduate_claim


DEFAULT_PDF_BASE_URL = "https://eplacement-2.s3.ap-southeast-5.amazonaws.com/"
TICK = "\u2713"
SIGNAL_EXPORT_KEYS = [
    "marriage",
    "self_illness",
    "family_illness",
    "spouse_location",
    "oku_self_or_family",
    "medex_other_exam",
]


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
    return _text(value).casefold() in {"1", "true", "yes", "y"}


def _as_float(value) -> float:
    text = _text(value)
    if not text:
        return 0.0


def _has_meaningful_text(value) -> bool:
    return bool(_text(value)) and _text(value).casefold() not in {"0", "tiada", "tidak", "tidak berkenaan", "none", "n/a", "na", "null"}


def _numeric_positive(value) -> bool:
    text = _text(value)
    if not text:
        return False
    try:
        return float(text) > 0
    except ValueError:
        return False
    try:
        return float(text)
    except ValueError:
        return 0.0


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


def _row_source_pdf_name(row: pd.Series, applicant_source: dict[str, str], applicant_id: str) -> str:
    source_pdf_name = _text(applicant_source.get("source_pdf_name", ""))
    if source_pdf_name:
        return source_pdf_name
    for column in ["Sheet1.NamaFail", "NamaFail", "pdf_filename", "source_pdf_name"]:
        value = _text(row.get(column))
        if value:
            return value
    url = _text(row.get("ATTACHMENT") or row.get("Sheet1.DownloadURL") or row.get("DownloadURL") or row.get("pdf_url"))
    if url.lower().startswith(("http://", "https://")):
        filename = PurePosixPath(url.split("?", 1)[0]).name
        if filename:
            return filename
    return f"{applicant_id}.pdf" if applicant_id else ""


def _row_original_pdf_url(row: pd.Series, applicant_source: dict[str, str], source_pdf_name: str) -> str:
    for value in [
        applicant_source.get("original_pdf_url", ""),
        row.get("ATTACHMENT"),
        row.get("Sheet1.DownloadURL"),
        row.get("DownloadURL"),
        row.get("pdf_url"),
    ]:
        url = _text(value)
        if url.lower().startswith(("http://", "https://")):
            return url
    return _build_original_pdf_url("", source_pdf_name)


def _supporting_document_present(row: pd.Series, original_pdf_url: str, source_pdf_name: str) -> bool:
    if _as_bool(row.get("KYC_SUPPORTING_DOC_PRESENT")):
        return True
    return bool(_text(original_pdf_url) or _text(source_pdf_name))


def _fallback_claim_flags(row: pd.Series) -> dict[str, bool]:
    return {
        "marriage": row_claim_is_married(_text(row.get("MARITAL_STATUS") or row.get("marital_status"))),
        "self_illness": _has_meaningful_text(row.get("PERSONAL_HEALTH_CONDITION") or row.get("personal_health_condition"))
        or _has_meaningful_text(row.get("Keterangan Kesihatan") or row.get("personal_health_details")),
        "family_illness": any(
            [
                _has_meaningful_text(row.get("SPOUSE_HEALTH_CONDITION") or row.get("spouse_health_condition")),
                _has_meaningful_text(row.get("Keterangan Masalah Kesihatan Pasanga") or row.get("spouse_health_details")),
                _numeric_positive(row.get("CHILDREN_HEALTH_ISSUE_SCORE") or row.get("children_health_issue_score")),
                _numeric_positive(row.get("PARENT_HEALTH_ISSUE_SCORE") or row.get("parent_health_issue_score")),
            ]
        ),
        "spouse_location": row_claim_is_married(_text(row.get("MARITAL_STATUS") or row.get("marital_status")))
        and any(
            [
                _has_meaningful_text(row.get("Alamat Bekerja Pasangan") or row.get("spouse_work_address")),
                _has_meaningful_text(row.get("NegeriBekerjaPasangan") or row.get("spouse_work_state")),
                _has_meaningful_text(row.get("Pekerjaan Pasangan") or row.get("spouse_job_title")),
                _has_meaningful_text(row.get("SPOUSE_EMPLOYMENT_STATUS") or row.get("spouse_employment_status")),
            ]
        ),
        "oku_self_or_family": any(
            [
                row_has_oku_claim(_text(row.get("StatusOKU") or row.get("applicant_oku_status"))),
                row_has_oku_claim(_text(row.get("SPOUSE_STATUS_OKU") or row.get("spouse_oku_status"))),
                _numeric_positive(row.get("CHILDREN_DISABILITY_SCORE") or row.get("children_disability_score")),
                _numeric_positive(row.get("PARENT_DISABILITY_SCORE") or row.get("parent_disability_score")),
            ]
        ),
        "medex_other_exam": row_has_postgraduate_claim(_text(row.get("POSTGRADUATE_PAPER_STATUS") or row.get("postgraduate_status"))),
    }


def _signal_status(row: pd.Series, suffix: str) -> str:
    if f"claimed_{suffix}" not in row.index:
        legacy_column = {
            "marriage": "KYC_FIRSTPASS_MARRIAGE",
            "self_illness": "KYC_FIRSTPASS_SELF_ILLNESS",
            "family_illness": "KYC_FIRSTPASS_FAMILY_ILLNESS",
            "spouse_location": "KYC_FIRSTPASS_SPOUSE_LOCATION",
            "oku_self_or_family": "KYC_FIRSTPASS_OKU_SELF_OR_FAMILY",
            "medex_other_exam": "KYC_FIRSTPASS_MEDEX_OR_OTHER_EXAM",
        }[suffix]
        legacy_status = _text(row.get(legacy_column)).casefold()
        return legacy_status if legacy_status in {"present", "manual_check", "not_present"} else "not_present"
    claimed = _as_bool(row.get(f"claimed_{suffix}"))
    proof_found = _as_bool(row.get(f"proof_found_{suffix}"))
    missing_proof = _as_bool(row.get(f"missing_proof_{suffix}"))
    confidence = _as_float(row.get(f"confidence_{suffix}"))
    if not claimed:
        return "not_claimed"
    if proof_found:
        return "present"
    if confidence > 0 or missing_proof:
        return "manual_check"
    return "not_present"


def _summary(row: pd.Series) -> str:
    if "claimed_marriage" not in row.index:
        parts: list[str] = []
        for suffix, legacy_column in {
            "marriage": "KYC_FIRSTPASS_MARRIAGE",
            "self_illness": "KYC_FIRSTPASS_SELF_ILLNESS",
            "family_illness": "KYC_FIRSTPASS_FAMILY_ILLNESS",
            "spouse_location": "KYC_FIRSTPASS_SPOUSE_LOCATION",
            "oku_self_or_family": "KYC_FIRSTPASS_OKU_SELF_OR_FAMILY",
            "medex_other_exam": "KYC_FIRSTPASS_MEDEX_OR_OTHER_EXAM",
        }.items():
            status = _text(row.get(legacy_column)).casefold()
            if status == "present":
                parts.append(f"{suffix.replace('_', ' ').capitalize()} present.")
            elif status == "manual_check":
                parts.append(f"{suffix.replace('_', ' ').capitalize()} unclear.")
        return " | ".join(parts) or "No target evidence detected."
    parts: list[str] = []
    for suffix in SIGNAL_EXPORT_KEYS:
        claimed = _as_bool(row.get(f"claimed_{suffix}"))
        if not claimed:
            continue
        summary = _text(row.get(f"evidence_summary_{suffix}"))
        if summary:
            parts.append(summary)
    if _as_bool(row.get("KYC_NEEDS_MANUAL_REVIEW")) and _text(row.get("KYC_OVERALL_REASON")):
        parts.append(_text(row.get("KYC_OVERALL_REASON")))
    return " | ".join(dict.fromkeys(part for part in parts if part)) or "No claimed evidence categories required verification."


def _legacy_check_reasons(claimed_flags: dict[str, bool], signal_statuses: dict[str, str]) -> list[str]:
    label_map = {
        "marriage": "marriage",
        "self_illness": "self illness",
        "family_illness": "family illness",
        "spouse_location": "spouse location",
        "oku_self_or_family": "OKU self/family",
        "medex_other_exam": "MedEX/other exam",
    }
    present_claims = [suffix for suffix, claimed in claimed_flags.items() if claimed and signal_statuses[suffix] == "present"]
    missing_claims = [suffix for suffix, claimed in claimed_flags.items() if claimed and signal_statuses[suffix] == "not_present"]
    ambiguous_claims = [suffix for suffix, claimed in claimed_flags.items() if claimed and signal_statuses[suffix] == "manual_check"]
    reasons: list[str] = []
    if missing_claims:
        missing = ", ".join(label_map[suffix] for suffix in missing_claims)
        if present_claims:
            detected = ", ".join(label_map[suffix] for suffix in present_claims)
            reasons.append(f"Detected {detected}, but missing claimed {missing}.")
        else:
            reasons.append(f"Missing claimed {missing} after the second pass.")
    if ambiguous_claims:
        ambiguous = ", ".join(label_map[suffix] for suffix in ambiguous_claims)
        reasons.append(f"Claimed {ambiguous} is still ambiguous after the second pass.")
    return reasons


def build_decision_queue(merged_df: pd.DataFrame, evidence_rows: list[EvidenceResult]) -> pd.DataFrame:
    source_info = _source_info_map(evidence_rows)
    rows: list[dict[str, object]] = []

    for _, row in merged_df.iterrows():
        applicant_id = _normalize_identifier(row.get("KYC_APPLICANT_ID_NORMALIZED") or row.get("applicant_id") or row.get("NO KP"))
        if not applicant_id:
            continue

        applicant_source = source_info.get(applicant_id, {"source_pdf_name": "", "original_pdf_url": ""})
        source_pdf_name = _row_source_pdf_name(row, applicant_source, applicant_id)
        original_pdf_url = _row_original_pdf_url(row, applicant_source, source_pdf_name)
        has_document = _supporting_document_present(row, original_pdf_url, source_pdf_name)

        signal_statuses = {suffix: _signal_status(row, suffix) for suffix in SIGNAL_EXPORT_KEYS}
        if "claimed_marriage" in row.index:
            claimed_flags = {suffix: _as_bool(row.get(f"claimed_{suffix}")) for suffix in SIGNAL_EXPORT_KEYS}
            check_required = "check" if _as_bool(row.get("KYC_NEEDS_MANUAL_REVIEW")) else "no_check"
            summary = _summary(row)
        else:
            claimed_flags = _fallback_claim_flags(row)
            missing_claims = [suffix for suffix, claimed in claimed_flags.items() if claimed and signal_statuses[suffix] == "not_present"]
            ambiguous_claims = [suffix for suffix, claimed in claimed_flags.items() if claimed and signal_statuses[suffix] == "manual_check"]
            check_required = "check" if (missing_claims or ambiguous_claims) else "no_check"
            summary_parts = [_summary(row), *_legacy_check_reasons(claimed_flags, signal_statuses)]
            summary = " | ".join(part for part in summary_parts if part) or "No target evidence detected."

        queue_row: dict[str, object] = {
            "applicant_id": applicant_id,
            "check_required": check_required,
            "summary": summary,
            "original_pdf_url": original_pdf_url,
            "open_original_pdf": original_pdf_url,
            "source_pdf_name": source_pdf_name,
            "supporting_document_present": has_document,
            "_check_sort": 0 if check_required == "check" else 1,
        }

        for suffix, status in signal_statuses.items():
            queue_row[suffix] = TICK if status == "present" else ""
            queue_row[f"{suffix}_status"] = status
            queue_row[f"claimed_{suffix}"] = claimed_flags[suffix]
            queue_row[f"proof_found_{suffix}"] = _as_bool(row.get(f"proof_found_{suffix}")) if f"proof_found_{suffix}" in row.index else status == "present"
            queue_row[f"verified_{suffix}"] = _as_bool(row.get(f"verified_{suffix}")) if f"verified_{suffix}" in row.index else (claimed_flags[suffix] and status == "present")
            queue_row[f"missing_proof_{suffix}"] = _as_bool(row.get(f"missing_proof_{suffix}")) if f"missing_proof_{suffix}" in row.index else (claimed_flags[suffix] and status != "present")
            queue_row[f"supporting_page_{suffix}"] = _text(row.get(f"supporting_page_{suffix}"))
            queue_row[f"evidence_summary_{suffix}"] = _text(row.get(f"evidence_summary_{suffix}"))
            queue_row[f"confidence_{suffix}"] = _as_float(row.get(f"confidence_{suffix}"))

        rows.append(queue_row)

    decision_df = pd.DataFrame(rows)
    if decision_df.empty:
        return decision_df
    decision_df = decision_df.sort_values(by=["_check_sort", "applicant_id"], ascending=[True, True], kind="stable")
    return decision_df.drop(columns=["_check_sort"])
