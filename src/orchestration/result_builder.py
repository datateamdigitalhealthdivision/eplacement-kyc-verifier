"""Shared helpers for building evidence results from the orchestration flow."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from src.extraction.applicant_claims import ApplicantClaims, extract_applicant_claims
from src.extraction.evidence_models import EvidenceResult
from src.io.spreadsheet_loader import ApplicantRecord
from src.rules.document_tags import derive_document_tags
from src.rules.validators import (
    aggregate_reason_text,
    document_ocr_confidence,
    row_claim_is_married,
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
SIGNAL_EXPORT_KEYS = {
    "marriage": "marriage",
    "self_illness": "self_illness",
    "family_illness": "family_illness",
    "spouse_location": "spouse_location",
    "oku_self_or_family": "oku_self_or_family",
    "medex_or_other_exam": "medex_other_exam",
}
SIGNAL_LABELS = {
    "marriage": "marriage",
    "self_illness": "self illness",
    "family_illness": "family illness",
    "spouse_location": "spouse location",
    "oku_self_or_family": "OKU self/family",
    "medex_or_other_exam": "MedEX/other exam",
}
PRIMARY_SIGNAL_ORDER = [
    "marriage",
    "spouse_location",
    "medex_or_other_exam",
    "oku_self_or_family",
    "self_illness",
    "family_illness",
]


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
    return extract_applicant_claims(row).signal_map()


def _default_signal_detail(signal: str, claimed: bool, status: str) -> dict[str, object]:
    label = SIGNAL_LABELS[signal]
    if not claimed:
        summary = "Not claimed; skipped."
    elif status == "present":
        summary = f"Supporting {label} evidence was found."
    elif status == "manual_check":
        summary = f"Potential {label} evidence was found but remains ambiguous."
    else:
        summary = f"No supporting {label} evidence was found."
    return {
        "claimed": claimed,
        "status": status if claimed else "not_present",
        "proof_found": claimed and status == "present",
        "verified": claimed and status == "present",
        "missing_proof": claimed and status != "present",
        "ambiguous": claimed and status == "manual_check",
        "low_confidence": False,
        "proof_strength": 2 if claimed and status == "present" else 1 if claimed and status == "manual_check" else 0,
        "supporting_pages": [],
        "document_type": "",
        "person_named": "",
        "person_role": "unknown",
        "relationship_to_applicant": "unknown",
        "evidence_summary": summary,
        "confidence": 1.0 if claimed and status == "present" else 0.5 if claimed and status == "manual_check" else 0.0,
    }


def _normalize_signal_details(first_pass_signals, claims: ApplicantClaims) -> dict[str, dict[str, object]]:
    raw_details = dict(first_pass_signals.raw_payload.get("signal_details", {}))
    claim_map = claims.signal_map()
    normalized: dict[str, dict[str, object]] = {}
    for signal in SIGNAL_KEYS:
        detail = dict(raw_details.get(signal) or {})
        if not detail:
            detail = _default_signal_detail(signal, claim_map.get(signal, False), getattr(first_pass_signals, signal))
        detail["claimed"] = bool(detail.get("claimed", claim_map.get(signal, False)))
        detail["status"] = str(detail.get("status") or getattr(first_pass_signals, signal) or "not_present")
        detail["proof_found"] = bool(detail.get("proof_found", detail["claimed"] and detail["status"] == "present"))
        detail["verified"] = bool(detail.get("verified", detail["proof_found"]))
        detail["missing_proof"] = bool(detail.get("missing_proof", detail["claimed"] and not detail["proof_found"]))
        detail["ambiguous"] = bool(detail.get("ambiguous", detail["claimed"] and detail["status"] == "manual_check"))
        detail["low_confidence"] = bool(detail.get("low_confidence", False))
        detail["proof_strength"] = int(detail.get("proof_strength", 2 if detail["proof_found"] else 1 if detail["ambiguous"] else 0) or 0)
        detail["supporting_pages"] = [int(page) for page in detail.get("supporting_pages", []) if str(page).strip()]
        detail["document_type"] = str(detail.get("document_type") or "")
        detail["person_named"] = str(detail.get("person_named") or "")
        detail["person_role"] = str(detail.get("person_role") or "unknown")
        detail["relationship_to_applicant"] = str(detail.get("relationship_to_applicant") or "unknown")
        detail["evidence_summary"] = str(detail.get("evidence_summary") or _default_signal_detail(signal, detail["claimed"], detail["status"])["evidence_summary"])
        detail["confidence"] = float(detail.get("confidence") or 0.0)
        normalized[signal] = detail
    return normalized


def primary_signal(signal_statuses: dict[str, str], fallback: str | None = None) -> str:
    for key in PRIMARY_SIGNAL_ORDER:
        if signal_statuses.get(key) == "present":
            return key
    for key in PRIMARY_SIGNAL_ORDER:
        if signal_statuses.get(key) == "manual_check":
            return key
    return fallback or ""


def candidate_outcome(
    signal_details: dict[str, dict[str, object]],
    claims: ApplicantClaims,
    has_supporting_document: bool,
) -> tuple[str, str, bool, list[str], list[str], list[str]]:
    claimed_signals = [signal for signal, claimed in claims.signal_map().items() if claimed]
    present_claims = [signal for signal in claimed_signals if bool(signal_details.get(signal, {}).get("verified"))]
    ambiguous_claims = [
        signal
        for signal in claimed_signals
        if bool(signal_details.get(signal, {}).get("ambiguous")) or bool(signal_details.get(signal, {}).get("low_confidence"))
    ]
    missing_claims = [
        signal
        for signal in claimed_signals
        if bool(signal_details.get(signal, {}).get("missing_proof")) and signal not in ambiguous_claims
    ]
    reasons: list[str] = []

    if claims.is_unclear():
        unclear = ", ".join(SIGNAL_LABELS.get(signal, signal.replace("_", " ")) for signal in claims.unclear_claims)
        reasons.append(f"Claim extraction from the spreadsheet is unclear for: {unclear}.")

    if claimed_signals and not has_supporting_document:
        reasons.append("Claimed evidence exists in the spreadsheet but no supporting PDF was available.")

    if ambiguous_claims:
        reasons.append(
            "Claimed evidence is still ambiguous or low confidence after the second pass: "
            + ", ".join(SIGNAL_LABELS[key] for key in ambiguous_claims)
            + "."
        )
    if missing_claims:
        reasons.append(
            "Claimed evidence is still missing after the second pass: "
            + ", ".join(SIGNAL_LABELS[key] for key in missing_claims)
            + "."
        )

    if reasons:
        final_status = "DOCUMENT_MISSING" if claimed_signals and not has_supporting_document else "MANUAL_REVIEW_REQUIRED"
        return final_status, " | ".join(reasons), True, present_claims, ambiguous_claims, missing_claims

    if not claimed_signals:
        return "CONFIRMED", "No claimed evidence categories required verification.", False, [], [], []

    return "CONFIRMED", "All claimed evidence categories were supported by the uploaded PDF.", False, present_claims, [], []


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
    claims: ApplicantClaims | None = None,
) -> EvidenceResult:
    claim_model = claims or extract_applicant_claims(record.canonical)
    claims_map = claim_model.signal_map()
    signal_statuses = {key: getattr(first_pass_signals, key) for key in SIGNAL_KEYS}
    signal_details = _normalize_signal_details(first_pass_signals, claim_model)
    has_supporting_document = True
    final_status, final_reason, manual_review, present_claims, ambiguous_claims, missing_claims = candidate_outcome(
        signal_details,
        claim_model,
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
        llm_confidence=max((float(detail.get("confidence") or 0.0) for detail in signal_details.values()), default=0.0),
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
        snippets=[str(detail.get("evidence_summary")) for detail in signal_details.values() if detail.get("claimed")][:6],
        llm_json={"first_pass_signals": first_pass_signals.model_dump(mode="json")},
        audit_payload={
            "result_kind": "candidate_assessment",
            "verifier_mode": first_pass_signals.raw_payload.get("_verifier_mode", "broad_classifier"),
            "claims": claims_map,
            "claim_columns": claim_model.export_claim_columns(),
            "claim_extraction_unclear": list(claim_model.unclear_claims),
            "claim_extraction_notes": list(claim_model.notes),
            "first_pass_signals": first_pass_signals.model_dump(mode="json"),
            "final_signal_statuses": signal_statuses,
            "signal_details": signal_details,
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
