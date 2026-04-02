"""Transparent validation rules for marriage certificate evidence."""

from __future__ import annotations

from pathlib import Path

from src.extraction.evidence_models import MarriageEvidence, OCRDocument, ValidationDecision
from src.rules.validators import (
    aggregate_reason_text,
    any_arabic_script,
    document_ocr_confidence,
    identifier_match,
    name_similarity,
    row_claim_is_married,
    rule_config,
)
from src.utils.text_cleaning import normalize_identifier, normalize_name


MIN_TRUSTWORTHY_IDENTIFIER_DIGITS = 10


def validate_marriage(
    row: dict,
    evidence: MarriageEvidence,
    document: OCRDocument,
    project_root: str | Path | None = None,
) -> ValidationDecision:
    config = rule_config(project_root)
    thresholds = config.get("thresholds", {})
    fuzzy_threshold = float(thresholds.get("fuzzy_name_threshold", 0.85))
    partial_threshold = float(thresholds.get("partial_name_threshold", 0.70))
    min_ocr = float(thresholds.get("minimum_ocr_confidence", 0.70))
    min_extraction = float(thresholds.get("minimum_extraction_confidence", 0.65))
    jawi_threshold = float(thresholds.get("jawi_manual_review_threshold", 0.80))

    reasons: list[str] = []
    matched: list[str] = []
    mismatched: list[str] = []
    flags: list[str] = []

    ocr_conf = document_ocr_confidence(document)
    if ocr_conf < min_ocr:
        flags.append("low_ocr_confidence")
    if evidence.extraction_confidence < min_extraction:
        flags.append("low_extraction_confidence")
    if any_arabic_script(document) and ocr_conf < jawi_threshold:
        flags.append("jawi_or_arabic_script_page")

    row_married = row_claim_is_married(row.get("marital_status"), config)
    applicant_reference = normalize_identifier(row.get("applicant_id"))
    spouse_reference = normalize_identifier(row.get("spouse_id"))
    applicant_reference_available = len(applicant_reference) >= MIN_TRUSTWORTHY_IDENTIFIER_DIGITS
    spouse_reference_available = len(spouse_reference) >= MIN_TRUSTWORTHY_IDENTIFIER_DIGITS
    applicant_name_reference = normalize_name(row.get("applicant_name") or "")
    spouse_name_reference = normalize_name(row.get("spouse_name") or "")

    applicant_ic_match = applicant_reference_available and identifier_match(row.get("applicant_id"), evidence.applicant_ic_from_doc)
    spouse_ic_match = spouse_reference_available and identifier_match(row.get("spouse_id"), evidence.spouse_ic_from_doc)
    spouse_name_score = name_similarity(row.get("spouse_name"), evidence.spouse_name_from_doc) if spouse_name_reference else 0.0
    applicant_name_score = name_similarity(row.get("applicant_name"), evidence.applicant_name_from_doc) if applicant_name_reference else 0.0

    if applicant_ic_match:
        matched.append("applicant_id")
    elif applicant_reference_available and evidence.applicant_ic_from_doc:
        mismatched.append("applicant_id")
        reasons.append("Applicant IC on the document conflicts with the spreadsheet row.")
    elif not evidence.applicant_ic_from_doc:
        reasons.append("Applicant IC could not be extracted from the document.")

    if spouse_ic_match:
        matched.append("spouse_id")
    elif spouse_reference_available and evidence.spouse_ic_from_doc:
        mismatched.append("spouse_id")
        reasons.append("Spouse IC does not match the spreadsheet row.")

    if spouse_name_reference and spouse_name_score >= fuzzy_threshold:
        matched.append("spouse_name")
    elif spouse_name_reference and spouse_name_score >= partial_threshold:
        reasons.append("Spouse name partially matches but needs manual confirmation.")
        flags.append("partial_spouse_name_match")
    elif spouse_name_reference and evidence.spouse_name_from_doc:
        mismatched.append("spouse_name")
        reasons.append("Spouse name on the document does not align with the spreadsheet row.")

    if applicant_name_reference and applicant_name_score >= partial_threshold:
        matched.append("applicant_name")

    if applicant_ic_match and (spouse_ic_match or spouse_name_score >= fuzzy_threshold) and not flags and evidence.key_supporting_snippets and row_married:
        return ValidationDecision(
            final_status="CONFIRMED",
            evidence_type="marriage",
            reasons=["Marriage certificate supports applicant and spouse details."],
            matched_fields=matched,
            mismatched_fields=mismatched,
            manual_review_required=False,
            low_confidence_flags=flags,
            final_confidence=min(evidence.extraction_confidence, ocr_conf),
        )

    if not row_married and evidence.key_supporting_snippets:
        reasons.append("Applicant row is not marked married but marriage certificate-like evidence was found.")
    if not applicant_reference_available and evidence.key_supporting_snippets:
        reasons.append("Spreadsheet applicant ID is not reliable enough for exact automated comparison.")
    if applicant_reference_available and evidence.applicant_ic_from_doc and not applicant_ic_match and "Applicant IC on the document conflicts with the spreadsheet row." not in reasons:
        reasons.append("Applicant IC on the document conflicts with the spreadsheet row.")

    if evidence.key_supporting_snippets:
        reasons.append("Marriage certificate requires manual review before a final decision.")
        return ValidationDecision(
            final_status="MANUAL_REVIEW_REQUIRED",
            evidence_type="marriage",
            reasons=[aggregate_reason_text(reasons)],
            matched_fields=matched,
            mismatched_fields=mismatched,
            manual_review_required=True,
            low_confidence_flags=flags,
            final_confidence=min(evidence.extraction_confidence, ocr_conf),
        )

    return ValidationDecision(
        final_status="MANUAL_REVIEW_REQUIRED",
        evidence_type="marriage",
        reasons=[aggregate_reason_text(reasons) or "Marriage claim was not adequately evidenced by the uploaded document."],
        matched_fields=matched,
        mismatched_fields=mismatched,
        manual_review_required=True,
        low_confidence_flags=flags,
        final_confidence=min(evidence.extraction_confidence, ocr_conf),
    )
