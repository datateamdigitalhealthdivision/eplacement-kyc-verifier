"""Shared validation helpers and generic unsupported-document logic."""

from __future__ import annotations

from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

from src.extraction.evidence_models import GenericEvidence, OCRDocument, ValidationDecision
from src.settings import load_yaml_config
from src.utils.confidence import average_confidence
from src.utils.text_cleaning import normalize_identifier, normalize_name, normalize_whitespace


def rule_config(project_root: str | Path | None = None) -> dict:
    return load_yaml_config("rules.yaml", project_root=project_root)


def identifier_match(expected: str | None, observed: str | None) -> bool:
    expected_clean = normalize_identifier(expected)
    observed_clean = normalize_identifier(observed)
    return bool(expected_clean and observed_clean and expected_clean == observed_clean)


def name_similarity(expected: str | None, observed: str | None) -> float:
    expected_clean = normalize_name(expected or "")
    observed_clean = normalize_name(observed or "")
    if not expected_clean or not observed_clean:
        return 0.0
    return SequenceMatcher(None, expected_clean, observed_clean).ratio()


def row_claim_is_married(value: str | None, config: dict | None = None) -> bool:
    cfg = config or rule_config()
    married_values = {normalize_whitespace(item).upper() for item in cfg.get("logic", {}).get("married_values", [])}
    return normalize_whitespace(value or "").upper() in married_values


def row_has_postgraduate_claim(value: str | None, config: dict | None = None) -> bool:
    cfg = config or rule_config()
    no_values = {normalize_whitespace(item).upper() for item in cfg.get("logic", {}).get("no_postgraduate_values", [])}
    normalized = normalize_whitespace(value or "").upper()
    return bool(normalized) and normalized not in no_values


def row_has_oku_claim(value: str | None, config: dict | None = None) -> bool:
    cfg = config or rule_config()
    no_values = {normalize_whitespace(item).upper() for item in cfg.get("logic", {}).get("no_oku_values", [])}
    normalized = normalize_whitespace(value or "").upper()
    return bool(normalized) and normalized not in no_values


def document_ocr_confidence(document: OCRDocument) -> float:
    return average_confidence([page.confidence for page in document.pages], default=0.0)


def any_arabic_script(document: OCRDocument) -> bool:
    return any(page.language_guess == "arabic_script" for page in document.pages)


def aggregate_reason_text(reasons: Iterable[str]) -> str:
    unique = [reason for reason in dict.fromkeys(reason.strip() for reason in reasons if reason and reason.strip())]
    return " | ".join(unique)


def generic_document_decision(evidence: GenericEvidence, document: OCRDocument) -> ValidationDecision:
    ocr_conf = document_ocr_confidence(document)
    if not document.combined_text:
        return ValidationDecision(
            final_status="OCR_FAILED",
            evidence_type="generic",
            reasons=["No OCR or direct text could be extracted from the document."],
            manual_review_required=True,
            final_confidence=0.0,
        )
    reason = (
        "Document classified as other supporting document; manual review required."
        if evidence.doc_type == "other_supporting_document"
        else "Document type is ambiguous and requires human review."
    )
    return ValidationDecision(
        final_status="MANUAL_REVIEW_REQUIRED",
        evidence_type="generic",
        reasons=[reason],
        manual_review_required=True,
        low_confidence_flags=[
            flag
            for flag in [
                "arabic_script_detected" if any_arabic_script(document) else "",
                "low_ocr_confidence" if ocr_conf < 0.7 else "",
            ]
            if flag
        ],
        final_confidence=min(evidence.extraction_confidence, ocr_conf),
    )
