"""Merge evidence-level validation results back onto the applicant spreadsheet."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from typing import Iterable

import pandas as pd

from src.extraction.evidence_models import EvidenceResult
from src.rules.validators import row_claim_is_married, row_has_oku_claim, row_has_postgraduate_claim


STATUS_ORDER = {
    "CONFIRMED": 0,
    "MANUAL_REVIEW_REQUIRED": 1,
    "DOCUMENT_MISSING": 2,
    "": 3,
}


MANUAL_REVIEW_SOURCE_STATUSES = {
    "MANUAL_REVIEW_REQUIRED",
    "NOT_EVIDENCED_OR_INCONSISTENT",
    "OCR_FAILED",
    "DOWNLOAD_FAILED",
    "UNSUPPORTED_DOCUMENT_TYPE",
}


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


def _normalized_status(status: str) -> str:
    if status == "DOCUMENT_MISSING":
        return status
    if status in MANUAL_REVIEW_SOURCE_STATUSES:
        return "MANUAL_REVIEW_REQUIRED"
    return status


def _effective_status(record: EvidenceResult | dict) -> str:
    if isinstance(record, EvidenceResult):
        return _normalized_status(record.effective_status())
    raw_status = str(record.get("override_status") or record.get("final_status") or "")
    return _normalized_status(raw_status)


def _aggregate(records: Iterable[EvidenceResult | dict]) -> tuple[str, str, bool]:
    rows = list(records)
    if not rows:
        return "", "", False
    ordered = sorted(rows, key=lambda row: STATUS_ORDER.get(_effective_status(row), 99))
    status = _effective_status(ordered[0])
    reasons: list[str] = []
    manual_review = status == "MANUAL_REVIEW_REQUIRED"
    for row in rows:
        reason = row.final_reason if isinstance(row, EvidenceResult) else str(row.get("final_reason", ""))
        if reason and reason not in reasons:
            reasons.append(reason)
        manual_review = manual_review or bool(
            row.manual_review_flag if isinstance(row, EvidenceResult) else row.get("manual_review_flag", False)
        )
    return status, " | ".join(reasons), manual_review


def _document_present(records: list[EvidenceResult], observed_records: list[EvidenceResult]) -> bool:
    if observed_records:
        return True
    return any(record.source_pdf_path or _normalized_status(record.final_status) != "" for record in records)


def _observed_tags(observed_records: list[EvidenceResult]) -> dict[str, bool]:
    tags = {tag: False for tag in TAG_COLUMNS}
    evidence_flags = {flag: False for flag in EVIDENCE_COLUMNS}
    for record in observed_records:
        payload = record.audit_payload.get("document_tags", {})
        for tag in tags:
            tags[tag] = tags[tag] or bool(payload.get(tag, False))
        for flag in evidence_flags:
            evidence_flags[flag] = evidence_flags[flag] or bool(payload.get(flag, False))
        if record.document_type == "other_supporting_document":
            tags["other_supporting_document"] = True
        if record.document_type == "marriage_certificate":
            tags["marriage_certificate"] = True
            tags["marriage_related_document"] = True
            evidence_flags["marriage_evidence_detected"] = True
        if record.document_type == "medex_or_exam_document":
            tags["medex_exam_document"] = True
            tags["medical_document"] = True
            evidence_flags["medex_evidence_detected"] = True
    return {**tags, **evidence_flags}


def _positive_tag_list(tags: dict[str, bool]) -> list[str]:
    return [tag for tag in [*TAG_COLUMNS.keys(), *EVIDENCE_COLUMNS.keys()] if tags.get(tag)]


def merge_results_back(source_df: pd.DataFrame, canonical_df: pd.DataFrame, evidence_results: list[EvidenceResult]) -> pd.DataFrame:
    grouped: dict[str, list[EvidenceResult]] = defaultdict(list)
    for result in evidence_results:
        grouped[result.applicant_id].append(result)

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
    for column in TAG_COLUMNS.values():
        kyc_columns[column] = []
    for column in EVIDENCE_COLUMNS.values():
        kyc_columns[column] = []

    for _, canonical_row in canonical_df.iterrows():
        applicant_id = str(canonical_row.get("applicant_id", ""))
        records = grouped.get(applicant_id, [])
        observed_records = [record for record in records if record.audit_payload.get("result_kind") == "observed_document"]
        marriage_records = [record for record in records if record.evidence_type == "marriage"]
        medex_records = [record for record in records if record.evidence_type == "medex"]

        uploaded_status, uploaded_reason, uploaded_review = _aggregate(observed_records)
        uploaded_doc_types = list(dict.fromkeys(record.document_type for record in observed_records if record.document_type))
        uploaded_doc_type = " | ".join(uploaded_doc_types)
        detected_primary_doc = uploaded_doc_types[0] if uploaded_doc_types else ""

        marriage_status, marriage_reason, marriage_review = _aggregate(marriage_records)
        medex_status, medex_reason, medex_review = _aggregate(medex_records)
        has_document = _document_present(records, observed_records)
        tags = _observed_tags(observed_records)
        positive_tags = _positive_tag_list(tags)

        married_claim = row_claim_is_married(canonical_row.get("marital_status"))
        medex_claim = row_has_postgraduate_claim(canonical_row.get("postgraduate_status"))
        oku_claim = row_has_oku_claim(canonical_row.get("applicant_oku_status"))

        detected_marriage_evidence = bool(tags.get("marriage_evidence_detected", False))
        detected_medex_evidence = bool(tags.get("medex_evidence_detected", False))
        detected_oku_evidence = bool(tags.get("oku_evidence_detected", False))

        if oku_claim and not has_document:
            oku_status = "DOCUMENT_MISSING"
            oku_reason = "Applicant row claims OKU support but no uploaded document was found."
            oku_review = True
        elif oku_claim and detected_oku_evidence:
            oku_status = "MANUAL_REVIEW_REQUIRED"
            oku_reason = "Uploaded document appears OKU-related; verify it supports the applicant claim."
            oku_review = True
        elif oku_claim:
            oku_status = "MANUAL_REVIEW_REQUIRED"
            oku_reason = "Applicant row claims OKU support, but the uploaded document was not clearly tagged as an OKU document."
            oku_review = True
        elif detected_oku_evidence:
            oku_status = "MANUAL_REVIEW_REQUIRED"
            oku_reason = "Uploaded document appears OKU-related even though the spreadsheet does not claim OKU support."
            oku_review = True
        else:
            oku_status = ""
            oku_reason = ""
            oku_review = False

        if married_claim and not has_document:
            marriage_status = "DOCUMENT_MISSING"
            marriage_review = True
            if not marriage_reason:
                marriage_reason = "Applicant row claims marriage support but no uploaded document was found."
        elif married_claim and marriage_status != "CONFIRMED":
            marriage_status = "MANUAL_REVIEW_REQUIRED"
            marriage_review = True
        elif not married_claim and marriage_status and marriage_status != "CONFIRMED":
            marriage_status = "MANUAL_REVIEW_REQUIRED"
            marriage_review = True
        elif not married_claim and any(record.evidence_type == "marriage" for record in records):
            marriage_status = "MANUAL_REVIEW_REQUIRED"
            marriage_reason = marriage_reason or "Marriage-related evidence was detected even though the spreadsheet does not claim it."
            marriage_review = True

        if medex_claim and not has_document:
            medex_status = "DOCUMENT_MISSING"
            medex_review = True
            if not medex_reason:
                medex_reason = "Applicant row claims MedEX/postgraduate support but no uploaded document was found."
        elif medex_claim and medex_status != "CONFIRMED":
            medex_status = "MANUAL_REVIEW_REQUIRED"
            medex_review = True
        elif not medex_claim and medex_status and medex_status != "CONFIRMED":
            medex_status = "MANUAL_REVIEW_REQUIRED"
            medex_review = True
        elif not medex_claim and any(record.evidence_type == "medex" for record in records):
            medex_status = "MANUAL_REVIEW_REQUIRED"
            medex_reason = medex_reason or "MedEX or exam evidence was detected even though the spreadsheet does not claim it."
            medex_review = True

        overall_reasons = [reason for reason in [uploaded_reason, marriage_reason, medex_reason, oku_reason] if reason]
        overall_review = uploaded_review or marriage_review or medex_review or oku_review
        if not has_document and (married_claim or medex_claim or oku_claim):
            overall_status = "DOCUMENT_MISSING"
            overall_review = True
        elif overall_review:
            overall_status = "MANUAL_REVIEW_REQUIRED"
        else:
            overall_status = "CONFIRMED"

        kyc_columns["KYC_APPLICANT_ID_NORMALIZED"].append(applicant_id)
        kyc_columns["KYC_UPLOADED_DOC_TYPE"].append(uploaded_doc_type)
        kyc_columns["KYC_UPLOADED_DOC_STATUS"].append(uploaded_status)
        kyc_columns["KYC_UPLOADED_DOC_REASON"].append(uploaded_reason)
        kyc_columns["KYC_UPLOADED_DOC_REVIEW_REQUIRED"].append(uploaded_review)
        kyc_columns["KYC_DETECTED_PRIMARY_DOC"].append(detected_primary_doc)
        kyc_columns["KYC_DETECTED_DOC_TAGS"].append(" | ".join(positive_tags))
        kyc_columns["KYC_CLAIM_MARRIED"].append(married_claim)
        kyc_columns["KYC_CLAIM_MEDEX"].append(medex_claim)
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
        kyc_columns["KYC_OVERALL_REASON"].append(" | ".join(dict.fromkeys(overall_reasons)))
        kyc_columns["KYC_OVERALL_REVIEW_REQUIRED"].append(overall_review)
        kyc_columns["KYC_NEEDS_MANUAL_REVIEW"].append(overall_review)
        kyc_columns["KYC_SUPPORTING_DOC_PRESENT"].append(has_document)
        kyc_columns["KYC_LAST_RUN_AT"].append(now)
        for tag, column in TAG_COLUMNS.items():
            kyc_columns[column].append(bool(tags.get(tag, False)))
        for flag, column in EVIDENCE_COLUMNS.items():
            kyc_columns[column].append(bool(tags.get(flag, False)))

    for column, values in kyc_columns.items():
        merged[column] = values
    return merged
