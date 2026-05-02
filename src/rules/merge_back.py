"""Merge applicant-level first-pass results back onto the spreadsheet."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from src.extraction.evidence_models import EvidenceResult
from src.rules.validators import row_claim_is_married, row_has_oku_claim, row_has_postgraduate_claim


FIRST_PASS_STATUS_COLUMNS = {
    "marriage": "KYC_FIRSTPASS_MARRIAGE",
    "self_illness": "KYC_FIRSTPASS_SELF_ILLNESS",
    "family_illness": "KYC_FIRSTPASS_FAMILY_ILLNESS",
    "spouse_location": "KYC_FIRSTPASS_SPOUSE_LOCATION",
    "oku_self_or_family": "KYC_FIRSTPASS_OKU_SELF_OR_FAMILY",
    "medex_or_other_exam": "KYC_FIRSTPASS_MEDEX_OR_OTHER_EXAM",
}
SIGNAL_ORDER = {"present": 0, "manual_check": 1, "not_present": 2, "": 3}
TAG_COLUMNS = {
    "marriage_certificate": "KYC_DETECTED_MARRIAGE_CERTIFICATE",
    "marriage_related_document": "KYC_DETECTED_MARRIAGE_RELATED_DOCUMENT",
    "medex_exam_document": "KYC_DETECTED_MEDEX_EXAM_DOCUMENT",
    "oku_document": "KYC_DETECTED_OKU_DOCUMENT",
    "medical_document": "KYC_DETECTED_MEDICAL_DOCUMENT",
    "other_supporting_document": "KYC_DETECTED_OTHER_SUPPORTING_DOCUMENT",
}
EVIDENCE_COLUMNS = {
    "marriage_evidence_detected": "KYC_DETECTED_MARRIAGE_EVIDENCE",
    "medex_evidence_detected": "KYC_DETECTED_MEDEX_EVIDENCE",
    "oku_evidence_detected": "KYC_DETECTED_OKU_EVIDENCE",
}


def _text(value) -> str:
    return str(value or "").strip()


def _has_meaningful_text(value) -> bool:
    return _text(value).casefold() not in {"", "0", "tiada", "tidak", "tidak berkenaan", "none", "n/a", "na", "null"}


def _numeric_positive(value) -> bool:
    text = _text(value)
    if not text:
        return False
    try:
        return float(text) > 0
    except ValueError:
        return False


def _candidate_claims(row: dict) -> dict[str, bool]:
    return {
        "marriage": row_claim_is_married(row.get("marital_status")),
        "self_illness": _has_meaningful_text(row.get("personal_health_condition")) or _has_meaningful_text(row.get("personal_health_details")),
        "family_illness": any(
            [
                _has_meaningful_text(row.get("spouse_health_condition")),
                _has_meaningful_text(row.get("spouse_health_details")),
                _numeric_positive(row.get("children_health_issue_score")),
                _numeric_positive(row.get("parent_health_issue_score")),
            ]
        ),
        "spouse_location": row_claim_is_married(row.get("marital_status"))
        and any(
            [
                _has_meaningful_text(row.get("spouse_employment_status")),
                _has_meaningful_text(row.get("spouse_job_title")),
                _has_meaningful_text(row.get("spouse_work_address")),
                _has_meaningful_text(row.get("spouse_work_state")),
            ]
        ),
        "oku_self_or_family": any(
            [
                row_has_oku_claim(row.get("applicant_oku_status")),
                row_has_oku_claim(row.get("spouse_oku_status")),
                _numeric_positive(row.get("children_disability_score")),
                _numeric_positive(row.get("parent_disability_score")),
            ]
        ),
        "medex_or_other_exam": row_has_postgraduate_claim(row.get("postgraduate_status")),
    }


def _normalize_signal_status(value: object) -> str:
    normalized = str(value or "").strip().casefold()
    if normalized in {"present", "yes", "true", "found", "detected"}:
        return "present"
    if normalized in {"manual_check", "manual", "unclear", "ambiguous", "possible", "maybe"}:
        return "manual_check"
    return "not_present"


def _extract_signal_statuses(record: EvidenceResult | None) -> tuple[dict[str, str], list[str]]:
    statuses = {key: "not_present" for key in FIRST_PASS_STATUS_COLUMNS}
    reasons: list[str] = []
    if record is None:
        return statuses, reasons
    payload = record.audit_payload or {}
    first_pass = payload.get("final_signal_statuses") or payload.get("first_pass_signals") or {}
    for key in statuses:
        incoming = _normalize_signal_status(first_pass.get(key))
        if SIGNAL_ORDER[incoming] < SIGNAL_ORDER[statuses[key]]:
            statuses[key] = incoming
    reasons.extend(str(reason) for reason in first_pass.get("reasons", []) if str(reason).strip())
    return statuses, list(dict.fromkeys(reasons))


def _signal_tags(statuses: dict[str, str]) -> dict[str, bool]:
    marriage = statuses["marriage"] != "not_present"
    medex = statuses["medex_or_other_exam"] != "not_present"
    oku = statuses["oku_self_or_family"] != "not_present"
    medical = any(statuses[key] != "not_present" for key in ["self_illness", "family_illness", "medex_or_other_exam"])
    other = not any(status == "present" for status in statuses.values())
    return {
        "marriage_certificate": marriage,
        "marriage_related_document": marriage or statuses["spouse_location"] != "not_present",
        "medex_exam_document": medex,
        "oku_document": oku,
        "medical_document": medical,
        "other_supporting_document": other,
        "marriage_evidence_detected": marriage,
        "medex_evidence_detected": medex,
        "oku_evidence_detected": oku,
    }


def _claim_status(claimed: bool, signal_status: str, label: str) -> tuple[str, str, bool]:
    if not claimed:
        return "", "", False
    if signal_status == "present":
        return "CONFIRMED", f"Detected {label}.", False
    if signal_status == "manual_check":
        return "MANUAL_REVIEW_REQUIRED", f"{label.capitalize()} is still ambiguous after the second pass.", True
    return "MANUAL_REVIEW_REQUIRED", f"{label.capitalize()} is still missing after the second pass.", True


def _preferred_record(records: list[EvidenceResult]) -> EvidenceResult | None:
    if not records:
        return None
    for result_kind in ["candidate_assessment", "observed_document"]:
        for record in records:
            if record.audit_payload.get("result_kind") == result_kind:
                return record
    return records[0]


def merge_results_back(source_df: pd.DataFrame, canonical_df: pd.DataFrame, evidence_results: list[EvidenceResult]) -> pd.DataFrame:
    bucketed: dict[str, list[EvidenceResult]] = {}
    for result in evidence_results:
        bucketed.setdefault(result.applicant_id, []).append(result)
    merged = source_df.copy()
    now = datetime.now(UTC).isoformat()
    kyc_columns = {
        "KYC_APPLICANT_ID_NORMALIZED": [],
        "KYC_UPLOADED_DOC_TYPE": [],
        "KYC_UPLOADED_DOC_STATUS": [],
        "KYC_UPLOADED_DOC_REASON": [],
        "KYC_UPLOADED_DOC_REVIEW_REQUIRED": [],
        "KYC_DETECTED_PRIMARY_DOC": [],
        "KYC_DETECTED_DOC_TAGS": [],
        "KYC_CLAIM_MARRIED": [],
        "KYC_CLAIM_MEDEX": [],
        "KYC_CLAIM_OKU": [],
        "KYC_MARRIAGE_STATUS": [],
        "KYC_MARRIAGE_REASON": [],
        "KYC_MARRIAGE_REVIEW_REQUIRED": [],
        "KYC_MEDEX_STATUS": [],
        "KYC_MEDEX_REASON": [],
        "KYC_MEDEX_REVIEW_REQUIRED": [],
        "KYC_OKU_STATUS": [],
        "KYC_OKU_REASON": [],
        "KYC_OKU_REVIEW_REQUIRED": [],
        "KYC_OVERALL_STATUS": [],
        "KYC_OVERALL_REASON": [],
        "KYC_OVERALL_REVIEW_REQUIRED": [],
        "KYC_NEEDS_MANUAL_REVIEW": [],
        "KYC_SUPPORTING_DOC_PRESENT": [],
        "KYC_LAST_RUN_AT": [],
    }
    for column in [*TAG_COLUMNS.values(), *EVIDENCE_COLUMNS.values(), *FIRST_PASS_STATUS_COLUMNS.values()]:
        kyc_columns[column] = []

    for _, canonical_row in canonical_df.iterrows():
        applicant_id = str(canonical_row.get("applicant_id", ""))
        record = _preferred_record(bucketed.get(applicant_id, []))
        statuses, first_pass_reasons = _extract_signal_statuses(record)
        claims = _candidate_claims(dict(canonical_row))
        tags = _signal_tags(statuses)
        has_document = bool(record and (record.source_pdf_path or record.source_pdf_name or record.download_url))
        detected_primary = ""
        if record:
            detected_primary = str(record.audit_payload.get("detected_primary_signal") or record.document_type or "")
        positive_tags = [key for key, value in tags.items() if value]
        positive_tags.extend(f"{key}:{value}" for key, value in statuses.items() if value != "not_present")

        marriage_status, marriage_reason, marriage_review = _claim_status(claims["marriage"], statuses["marriage"], "marriage evidence")
        medex_status, medex_reason, medex_review = _claim_status(claims["medex_or_other_exam"], statuses["medex_or_other_exam"], "MedEX/other exam evidence")
        oku_claim = row_has_oku_claim(canonical_row.get("applicant_oku_status")) or claims["oku_self_or_family"]
        oku_status, oku_reason, oku_review = _claim_status(oku_claim, statuses["oku_self_or_family"], "OKU evidence")

        overall_status = record.effective_status() if record else ""
        overall_reason = record.final_reason if record else ""
        overall_review = bool(record.manual_review_flag) if record else False
        if first_pass_reasons:
            overall_reason = " | ".join(dict.fromkeys([part for part in [overall_reason, *first_pass_reasons] if part]))

        kyc_columns["KYC_APPLICANT_ID_NORMALIZED"].append(applicant_id)
        kyc_columns["KYC_UPLOADED_DOC_TYPE"].append(detected_primary)
        kyc_columns["KYC_UPLOADED_DOC_STATUS"].append(overall_status)
        kyc_columns["KYC_UPLOADED_DOC_REASON"].append(overall_reason)
        kyc_columns["KYC_UPLOADED_DOC_REVIEW_REQUIRED"].append(overall_review)
        kyc_columns["KYC_DETECTED_PRIMARY_DOC"].append(detected_primary)
        kyc_columns["KYC_DETECTED_DOC_TAGS"].append(" | ".join(positive_tags))
        kyc_columns["KYC_CLAIM_MARRIED"].append(claims["marriage"])
        kyc_columns["KYC_CLAIM_MEDEX"].append(claims["medex_or_other_exam"])
        kyc_columns["KYC_CLAIM_OKU"].append(oku_claim)
        kyc_columns["KYC_MARRIAGE_STATUS"].append(marriage_status)
        kyc_columns["KYC_MARRIAGE_REASON"].append(marriage_reason)
        kyc_columns["KYC_MARRIAGE_REVIEW_REQUIRED"].append(marriage_review)
        kyc_columns["KYC_MEDEX_STATUS"].append(medex_status)
        kyc_columns["KYC_MEDEX_REASON"].append(medex_reason)
        kyc_columns["KYC_MEDEX_REVIEW_REQUIRED"].append(medex_review)
        kyc_columns["KYC_OKU_STATUS"].append(oku_status)
        kyc_columns["KYC_OKU_REASON"].append(oku_reason)
        kyc_columns["KYC_OKU_REVIEW_REQUIRED"].append(oku_review)
        kyc_columns["KYC_OVERALL_STATUS"].append(overall_status)
        kyc_columns["KYC_OVERALL_REASON"].append(overall_reason)
        kyc_columns["KYC_OVERALL_REVIEW_REQUIRED"].append(overall_review)
        kyc_columns["KYC_NEEDS_MANUAL_REVIEW"].append(overall_review)
        kyc_columns["KYC_SUPPORTING_DOC_PRESENT"].append(has_document)
        kyc_columns["KYC_LAST_RUN_AT"].append(now)
        for tag, column in TAG_COLUMNS.items():
            kyc_columns[column].append(bool(tags.get(tag, False)))
        for tag, column in EVIDENCE_COLUMNS.items():
            kyc_columns[column].append(bool(tags.get(tag, False)))
        for signal, column in FIRST_PASS_STATUS_COLUMNS.items():
            kyc_columns[column].append(statuses[signal])

    for column, values in kyc_columns.items():
        merged[column] = values
    return merged
