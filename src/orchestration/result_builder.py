"""Shared helpers for building evidence results from the orchestration flow."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from src.extraction.evidence_models import EvidenceResult
from src.io.spreadsheet_loader import ApplicantRecord
from src.rules.document_tags import derive_document_tags
from src.rules.validators import (
    aggregate_reason_text,
    document_ocr_confidence,
    row_claim_is_married,
    row_has_oku_claim,
    row_has_postgraduate_claim,
)
from src.utils.download_url import normalize_download_url


TARGET_LABELS = {
    "marriage_certificate": "marriage certificate",
    "medex_or_exam_document": "MedEX or postgraduate document",
    "other_supporting_document": "other supporting document",
    "unknown": "unidentified supporting document",
}

SIGNAL_KEYS = [
    "marriage",
    "self_illness",
    "family_illness",
    "spouse_location",
    "oku_self_or_family",
    "medex_or_other_exam",
]
PRIMARY_SIGNAL_ORDER = [
    "marriage",
    "spouse_location",
    "medex_or_other_exam",
    "oku_self_or_family",
    "self_illness",
    "family_illness",
]


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


def expected_targets(row: dict) -> list[str]:
    targets: list[str] = []
    if row_claim_is_married(row.get("marital_status")):
        targets.append("marriage_certificate")
    if row_has_postgraduate_claim(row.get("postgraduate_status")):
        targets.append("medex_or_exam_document")
    return targets

def applicant_context(record: ApplicantRecord) -> dict[str, str]:
    keys = [
        "applicant_id",
        "applicant_name",
        "marital_status",
        "personal_health_condition",
        "personal_health_details",
        "applicant_oku_status",
        "spouse_name",
        "spouse_id",
        "spouse_employment_status",
        "spouse_job_title",
        "spouse_work_address",
        "spouse_work_state",
        "spouse_oku_status",
        "spouse_health_condition",
        "spouse_health_details",
        "children_health_issue_score",
        "parent_health_issue_score",
        "children_disability_score",
        "parent_disability_score",
        "postgraduate_status",
        "current_headquarters",
        "current_placement",
        "pdf_filename",
        "pdf_url",
    ]
    return {key: str(record.canonical.get(key, "") or "") for key in keys}


def candidate_claims(row: dict) -> dict[str, bool]:
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


def primary_signal(signal_statuses: dict[str, str], fallback: str | None = None) -> str:
    for key in PRIMARY_SIGNAL_ORDER:
        if signal_statuses.get(key) == "present":
            return key
    for key in PRIMARY_SIGNAL_ORDER:
        if signal_statuses.get(key) == "manual_check":
            return key
    return fallback or ""


def candidate_outcome(signal_statuses: dict[str, str], claims: dict[str, bool], has_supporting_document: bool) -> tuple[str, str, bool, list[str], list[str], list[str]]:
    claimed_signals = [key for key, claimed in claims.items() if claimed]
    present_claims = [key for key in claimed_signals if signal_statuses.get(key) == "present"]
    ambiguous_claims = [key for key in claimed_signals if signal_statuses.get(key) == "manual_check"]
    missing_claims = [key for key in claimed_signals if signal_statuses.get(key) == "not_present"]
    label_map = {
        "marriage": "marriage",
        "self_illness": "self illness",
        "family_illness": "family illness",
        "spouse_location": "spouse location",
        "oku_self_or_family": "OKU self/family",
        "medex_or_other_exam": "MedEX/other exam",
    }
    reasons: list[str] = []

    if claimed_signals and not has_supporting_document:
        return "DOCUMENT_MISSING", "Claimed evidence exists in the spreadsheet but no supporting PDF was available.", True, present_claims, ambiguous_claims, missing_claims

    if ambiguous_claims:
        reasons.append("Claimed evidence is still ambiguous after the second pass: " + ", ".join(label_map[key] for key in ambiguous_claims) + ".")
    if missing_claims:
        reasons.append("Claimed evidence is still missing after the second pass: " + ", ".join(label_map[key] for key in missing_claims) + ".")

    if reasons:
        return "MANUAL_REVIEW_REQUIRED", " | ".join(reasons), True, present_claims, ambiguous_claims, missing_claims

    return "CONFIRMED", "All claimed evidence matched the final signal set.", False, present_claims, ambiguous_claims, missing_claims


def target_label(target: str) -> str:
    return TARGET_LABELS.get(target, target.replace("_", " "))


def evidence_type(target: str) -> str:
    return {
        "marriage_certificate": "marriage",
        "medex_or_exam_document": "medex",
    }.get(target, "generic")


def observed_target(classification) -> str:
    for target in [classification.primary_type, *classification.candidate_types]:
        if target in {"marriage_certificate", "medex_or_exam_document", "other_supporting_document"}:
            return target
    return "other_supporting_document"


def evidence_name_fields(evidence) -> list[str]:
    fields: list[str] = []
    for attribute in [
        "applicant_name_from_doc",
        "spouse_name_from_doc",
        "candidate_name_from_doc",
        "possible_subject_name",
    ]:
        value = getattr(evidence, attribute, None)
        if value:
            fields.append(value)
    return fields


def evidence_identifiers(evidence) -> tuple[str | None, str | None]:
    applicant_identifier = (
        getattr(evidence, "applicant_ic_from_doc", None)
        or getattr(evidence, "candidate_ic_from_doc", None)
        or getattr(evidence, "possible_subject_ic", None)
    )
    spouse_identifier = getattr(evidence, "spouse_ic_from_doc", None)
    return applicant_identifier, spouse_identifier


def result_llm_json(classification, evidence=None) -> dict[str, object | None]:
    return {
        "classification": classification.llm_payload,
        "extraction": evidence.raw_payload if evidence is not None else None,
    }


def missing_result(
    *,
    job_id: str,
    record: ApplicantRecord,
    target: str,
    status: str,
    reason: str,
    download_url: str | None,
) -> EvidenceResult:
    manual_review = status in {
        "MANUAL_REVIEW_REQUIRED",
        "DOCUMENT_MISSING",
        "DOWNLOAD_FAILED",
        "OCR_FAILED",
        "UNSUPPORTED_DOCUMENT_TYPE",
        "NOT_EVIDENCED_OR_INCONSISTENT",
    }
    return EvidenceResult(
        job_id=job_id,
        applicant_id=record.applicant_id,
        applicant_name=str(record.canonical.get("applicant_name") or "") or None,
        row_index=record.row_index,
        source_pdf_name=str(record.canonical.get("pdf_filename") or "") or None,
        source_pdf_path=None,
        download_url=download_url,
        document_type=target,
        evidence_type=evidence_type(target),
        final_status=status,
        final_reason=reason,
        manual_review_flag=manual_review,
        audit_payload={"reason": reason, "result_kind": "missing_document"},
    )


def build_result(
    *,
    job_id: str,
    record: ApplicantRecord,
    classification,
    evidence,
    decision,
    pdf_path: Path,
    ocr_document,
    processing_time_seconds: float,
) -> EvidenceResult:
    applicant_identifier, spouse_identifier = evidence_identifiers(evidence)
    llm_json = result_llm_json(classification, evidence)
    document_tags = derive_document_tags(classification, evidence, ocr_document)
    manual_review = decision.manual_review_required or decision.final_status in {
        "MANUAL_REVIEW_REQUIRED",
        "DOCUMENT_MISSING",
        "DOWNLOAD_FAILED",
        "OCR_FAILED",
        "UNSUPPORTED_DOCUMENT_TYPE",
        "NOT_EVIDENCED_OR_INCONSISTENT",
    }
    return EvidenceResult(
        job_id=job_id,
        applicant_id=record.applicant_id,
        applicant_name=str(record.canonical.get("applicant_name") or "") or None,
        row_index=record.row_index,
        source_pdf_name=pdf_path.name,
        source_pdf_path=str(pdf_path),
        download_url=normalize_download_url(record.canonical.get("pdf_url")),
        document_type=evidence.doc_type,
        evidence_type=decision.evidence_type,
        ocr_engine=",".join(ocr_document.metadata.get("engines", [])),
        ocr_confidence=document_ocr_confidence(ocr_document),
        llm_confidence=evidence.extraction_confidence,
        extracted_applicant_ic=applicant_identifier,
        extracted_spouse_ic=spouse_identifier,
        extracted_name_fields=evidence_name_fields(evidence),
        page_refs=evidence.page_refs,
        final_status=decision.final_status,
        final_reason=aggregate_reason_text(decision.reasons),
        manual_review_flag=manual_review,
        processing_time_seconds=round(processing_time_seconds, 3),
        document_hash=ocr_document.document_hash,
        processing_hash=ocr_document.processing_hash,
        matched_fields=decision.matched_fields,
        mismatched_fields=decision.mismatched_fields,
        snippets=evidence.key_supporting_snippets,
        llm_json=llm_json,
        audit_payload={
            "result_kind": "observed_document",
            "classification": classification.model_dump(mode="json"),
            "evidence": evidence.model_dump(mode="json"),
            "decision": decision.model_dump(mode="json"),
            "document_tags": document_tags,
            "ocr_warnings": ocr_document.warnings,
        },
    )


def claim_mismatch_result(
    *,
    job_id: str,
    record: ApplicantRecord,
    expected_target: str,
    observed_target_name: str,
    classification,
    observed_evidence,
    pdf_path: Path,
    ocr_document,
    processing_time_seconds: float,
) -> EvidenceResult:
    observed_label = target_label(observed_target_name)
    expected_label = target_label(expected_target)
    if classification.primary_type == "unknown":
        reason = f"Uploaded document could not be confidently tagged as '{expected_label}'; manual review required."
    else:
        reason = f"Uploaded document was tagged as '{observed_label}', not '{expected_label}'; manual review required."
    applicant_identifier, spouse_identifier = evidence_identifiers(observed_evidence)
    document_tags = derive_document_tags(classification, observed_evidence, ocr_document)
    return EvidenceResult(
        job_id=job_id,
        applicant_id=record.applicant_id,
        applicant_name=str(record.canonical.get("applicant_name") or "") or None,
        row_index=record.row_index,
        source_pdf_name=pdf_path.name,
        source_pdf_path=str(pdf_path),
        download_url=normalize_download_url(record.canonical.get("pdf_url")),
        document_type=expected_target,
        evidence_type=evidence_type(expected_target),
        ocr_engine=",".join(ocr_document.metadata.get("engines", [])),
        ocr_confidence=document_ocr_confidence(ocr_document),
        llm_confidence=observed_evidence.extraction_confidence,
        extracted_applicant_ic=applicant_identifier,
        extracted_spouse_ic=spouse_identifier,
        extracted_name_fields=evidence_name_fields(observed_evidence),
        page_refs=observed_evidence.page_refs,
        final_status="MANUAL_REVIEW_REQUIRED",
        final_reason=reason,
        manual_review_flag=True,
        processing_time_seconds=round(processing_time_seconds, 3),
        document_hash=ocr_document.document_hash,
        processing_hash=ocr_document.processing_hash,
        matched_fields=[],
        mismatched_fields=["document_type"],
        snippets=observed_evidence.key_supporting_snippets,
        llm_json=result_llm_json(classification, observed_evidence),
        audit_payload={
            "result_kind": "claim_cross_check",
            "classification": classification.model_dump(mode="json"),
            "evidence": observed_evidence.model_dump(mode="json"),
            "decision": {
                "expected_document_type": expected_target,
                "observed_document_type": observed_target_name,
                "reason": reason,
            },
            "document_tags": document_tags,
            "ocr_warnings": ocr_document.warnings,
        },
    )


def candidate_failure_result(
    *,
    job_id: str,
    record: ApplicantRecord,
    status: str,
    reason: str,
    download_url: str | None,
) -> EvidenceResult:
    return EvidenceResult(
        job_id=job_id,
        applicant_id=record.applicant_id,
        applicant_name=str(record.canonical.get("applicant_name") or "") or None,
        row_index=record.row_index,
        source_pdf_name=str(record.canonical.get("pdf_filename") or "") or None,
        source_pdf_path=None,
        download_url=download_url,
        document_type="supporting_bundle",
        evidence_type="bundle",
        final_status=status,
        final_reason=reason,
        manual_review_flag=status in {"MANUAL_REVIEW_REQUIRED", "DOCUMENT_MISSING", "OCR_FAILED", "DOWNLOAD_FAILED"},
        audit_payload={"reason": reason, "result_kind": "candidate_assessment"},
    )


def candidate_result(
    *,
    job_id: str,
    record: ApplicantRecord,
    pdf_path: Path,
    ocr_document,
    first_pass_signals,
    processing_time_seconds: float,
) -> EvidenceResult:
    claims = candidate_claims(record.canonical)
    signal_statuses = {key: getattr(first_pass_signals, key) for key in SIGNAL_KEYS}
    has_supporting_document = True
    final_status, final_reason, manual_review, present_claims, ambiguous_claims, missing_claims = candidate_outcome(
        signal_statuses,
        claims,
        has_supporting_document,
    )
    detected_primary_signal = primary_signal(
        signal_statuses,
        fallback=str(first_pass_signals.raw_payload.get("best_fit_bucket") or ""),
    )
    page_labels = list(first_pass_signals.raw_payload.get("page_labels", []))
    models_used = list(
        dict.fromkeys(
            [
                str(first_pass_signals.raw_payload.get("_model") or ""),
                str(first_pass_signals.raw_payload.get("_secondary_model") or ""),
                *[
                    str(model_name)
                    for payload in page_labels
                    for model_name in payload.get("models_used", [])
                ],
            ]
        )
    )
    models_used = [model_name for model_name in models_used if model_name]
    return EvidenceResult(
        job_id=job_id,
        applicant_id=record.applicant_id,
        applicant_name=str(record.canonical.get("applicant_name") or "") or None,
        row_index=record.row_index,
        source_pdf_name=pdf_path.name,
        source_pdf_path=str(pdf_path),
        download_url=normalize_download_url(record.canonical.get("pdf_url")),
        document_type=detected_primary_signal or "supporting_bundle",
        evidence_type="bundle",
        ocr_engine=",".join(ocr_document.metadata.get("engines", [])),
        ocr_confidence=document_ocr_confidence(ocr_document),
        llm_confidence=float(first_pass_signals.raw_payload.get("best_fit_confidence") or 0.0),
        extracted_applicant_ic=None,
        extracted_spouse_ic=None,
        extracted_name_fields=[],
        page_refs=[page.page_number for page in ocr_document.pages],
        final_status=final_status,
        final_reason=final_reason,
        manual_review_flag=manual_review,
        processing_time_seconds=round(processing_time_seconds, 3),
        document_hash=ocr_document.document_hash,
        processing_hash=ocr_document.processing_hash,
        matched_fields=present_claims,
        mismatched_fields=missing_claims + ambiguous_claims,
        snippets=first_pass_signals.reasons[:6],
        llm_json={"first_pass_signals": first_pass_signals.model_dump(mode="json")},
        audit_payload={
            "result_kind": "candidate_assessment",
            "claims": claims,
            "first_pass_signals": first_pass_signals.model_dump(mode="json"),
            "final_signal_statuses": signal_statuses,
            "detected_primary_signal": detected_primary_signal,
            "present_claims": present_claims,
            "ambiguous_claims": ambiguous_claims,
            "missing_claims": missing_claims,
            "models_used": models_used,
            "ocr_warnings": ocr_document.warnings,
        },
    )


def summary(bundle, evidence_results: list[EvidenceResult], downloaded_count: int, ocr_docs: int, direct_text_docs: int) -> list[dict]:
    by_applicant: dict[str, EvidenceResult] = {}
    for result in evidence_results:
        by_applicant[result.applicant_id] = result
    applicant_results = list(by_applicant.values())
    status_counts = Counter(result.effective_status() for result in applicant_results)
    doc_counts = Counter(result.document_type for result in applicant_results)
    reason_counts = Counter(result.final_reason for result in applicant_results if result.final_reason)
    pdf_paths = {result.source_pdf_path for result in applicant_results if result.source_pdf_path}
    return [
        {
            "total_applicants": len(bundle.records),
            "total_pdfs_found": len(pdf_paths),
            "total_downloaded": downloaded_count,
            "total_ocred": ocr_docs,
            "total_direct_text_extracted": direct_text_docs,
            "counts_by_document_type": dict(doc_counts),
            "counts_by_status": dict(status_counts),
            "counts_requiring_manual_review": sum(1 for result in applicant_results if result.manual_review_flag),
            "counts_by_failure_reason": dict(reason_counts),
        }
    ]
