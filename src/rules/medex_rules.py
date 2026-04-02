"""Transparent validation rules for MedEX or postgraduate evidence."""

from __future__ import annotations

from pathlib import Path

from src.extraction.evidence_models import MedexEvidence, OCRDocument, ValidationDecision
from src.rules.validators import (
    aggregate_reason_text,
    any_arabic_script,
    document_ocr_confidence,
    identifier_match,
    name_similarity,
    row_has_postgraduate_claim,
    rule_config,
)
from src.utils.text_cleaning import normalize_identifier, normalize_name


MIN_TRUSTWORTHY_IDENTIFIER_DIGITS = 10


def validate_medex(
    row: dict,
    evidence: MedexEvidence,
    document: OCRDocument,
    project_root: str | Path | None = None,
) -> ValidationDecision:
    config = rule_config(project_root)
    thresholds = config.get("thresholds", {})
    fuzzy_threshold = float(thresholds.get("fuzzy_name_threshold", 0.85))
    min_ocr = float(thresholds.get("minimum_ocr_confidence", 0.70))
    min_extraction = float(thresholds.get("minimum_extraction_confidence", 0.65))

    reasons: list[str] = []
    matched: list[str] = []
    mismatched: list[str] = []
    flags: list[str] = []

    ocr_conf = document_ocr_confidence(document)
    if ocr_conf < min_ocr:
        flags.append("low_ocr_confidence")
    if evidence.extraction_confidence < min_extraction:
        flags.append("low_extraction_confidence")
    if any_arabic_script(document):
        flags.append("arabic_script_page")

    row_has_claim = row_has_postgraduate_claim(row.get("postgraduate_status"), config)
    applicant_reference = normalize_identifier(row.get("applicant_id"))
    applicant_reference_available = len(applicant_reference) >= MIN_TRUSTWORTHY_IDENTIFIER_DIGITS
    applicant_name_reference = normalize_name(row.get("applicant_name") or "")
    id_match = applicant_reference_available and identifier_match(row.get("applicant_id"), evidence.candidate_ic_from_doc)
    name_score = name_similarity(row.get("applicant_name"), evidence.candidate_name_from_doc) if applicant_name_reference else 0.0
    exam_supported = bool(evidence.exam_name or evidence.exam_status_or_result)

    if id_match:
        matched.append("applicant_id")
    elif applicant_reference_available and evidence.candidate_ic_from_doc:
        mismatched.append("applicant_id")
        reasons.append("Candidate IC on the document conflicts with the spreadsheet row.")
    elif not evidence.candidate_ic_from_doc:
        reasons.append("Candidate IC could not be extracted from the document.")

    if applicant_name_reference and name_score >= fuzzy_threshold:
        matched.append("candidate_name")
    elif applicant_name_reference and evidence.candidate_name_from_doc:
        reasons.append("Candidate name only partially matches the spreadsheet row.")
        flags.append("partial_candidate_name_match")

    if id_match and exam_supported and evidence.key_supporting_snippets and not flags and row_has_claim:
        return ValidationDecision(
            final_status="CONFIRMED",
            evidence_type="medex",
            reasons=["Exam or postgraduate evidence supports the applicant claim."],
            matched_fields=matched,
            mismatched_fields=mismatched,
            manual_review_required=False,
            low_confidence_flags=flags,
            final_confidence=min(evidence.extraction_confidence, ocr_conf),
        )

    if not row_has_claim and exam_supported:
        reasons.append("Postgraduate or exam evidence was found even though the row does not claim it.")
    if not applicant_reference_available and exam_supported:
        reasons.append("Spreadsheet applicant ID is not reliable enough for exact automated comparison.")
    if applicant_reference_available and evidence.candidate_ic_from_doc and not id_match and "Candidate IC on the document conflicts with the spreadsheet row." not in reasons:
        reasons.append("Candidate IC on the document conflicts with the spreadsheet row.")

    if exam_supported:
        reasons.append("Exam or postgraduate evidence requires manual review before a final decision.")
        return ValidationDecision(
            final_status="MANUAL_REVIEW_REQUIRED",
            evidence_type="medex",
            reasons=[aggregate_reason_text(reasons)],
            matched_fields=matched,
            mismatched_fields=mismatched,
            manual_review_required=True,
            low_confidence_flags=flags,
            final_confidence=min(evidence.extraction_confidence, ocr_conf),
        )

    return ValidationDecision(
        final_status="MANUAL_REVIEW_REQUIRED",
        evidence_type="medex",
        reasons=[aggregate_reason_text(reasons) or "Postgraduate or exam claim was not adequately evidenced."],
        matched_fields=matched,
        mismatched_fields=mismatched,
        manual_review_required=True,
        low_confidence_flags=flags,
        final_confidence=min(evidence.extraction_confidence, ocr_conf),
    )
