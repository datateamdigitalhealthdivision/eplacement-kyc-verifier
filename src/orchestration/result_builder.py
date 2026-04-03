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
    row_has_postgraduate_claim,
)


TARGET_LABELS = {
    "marriage_certificate": "marriage certificate",
    "medex_or_exam_document": "MedEX or postgraduate document",
    "other_supporting_document": "other supporting document",
    "unknown": "unidentified supporting document",
}


def expected_targets(row: dict) -> list[str]:
    targets: list[str] = []
    if row_claim_is_married(row.get("marital_status")):
        targets.append("marriage_certificate")
    if row_has_postgraduate_claim(row.get("postgraduate_status")):
        targets.append("medex_or_exam_document")
    return targets


def normalize_download_url(value: str | None) -> str | None:
    normalized = str(value or "").strip()
    if not normalized:
        return None
    if normalized.casefold() in {"tiada maklumat", "nan", "none", "null", "n/a", "na", "-"}:
        return None
    if normalized.lower().startswith(("http://", "https://")):
        return normalized
    return None


def applicant_context(record: ApplicantRecord) -> dict[str, str]:
    keys = [
        "applicant_id",
        "applicant_name",
        "marital_status",
        "spouse_name",
        "spouse_id",
        "postgraduate_status",
        "pdf_filename",
        "pdf_url",
    ]
    return {key: str(record.canonical.get(key, "") or "") for key in keys}


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


def summary(bundle, evidence_results: list[EvidenceResult], downloaded_count: int, ocr_docs: int, direct_text_docs: int) -> list[dict]:
    status_counts = Counter(result.effective_status() for result in evidence_results)
    doc_counts = Counter(result.document_type for result in evidence_results)
    reason_counts = Counter(result.final_reason for result in evidence_results if result.final_reason)
    pdf_paths = {result.source_pdf_path for result in evidence_results if result.source_pdf_path}
    return [
        {
            "total_applicants": len(bundle.records),
            "total_pdfs_found": len(pdf_paths),
            "total_downloaded": downloaded_count,
            "total_ocred": ocr_docs,
            "total_direct_text_extracted": direct_text_docs,
            "counts_by_document_type": dict(doc_counts),
            "counts_by_status": dict(status_counts),
            "counts_requiring_manual_review": sum(1 for result in evidence_results if result.manual_review_flag),
            "counts_by_failure_reason": dict(reason_counts),
        }
    ]
