"""Prompt builders for local text and vision Ollama calls."""

from __future__ import annotations

import json


CLASSIFICATION_GUIDANCE = (
    "Document type definitions:\n"
    "- marriage_certificate: an issued marriage or nikah certificate that evidences a completed marriage and usually shows the applicant and spouse names or identifiers.\n"
    "- medex_or_exam_document: only an applicant-specific MedEX, GCFM, postgraduate paper, entrance examination, or official exam result/certificate. Do not use this label for general medical records, hospital notes, disability or OKU approvals, death records, referral letters, or unrelated health documents.\n"
    "- other_supporting_document: any other supporting evidence, including request letters, administrative notices, hospital records, OKU documents, death-related documents, marriage appointment slips, and documents related to marriage that are not the actual certificate.\n"
    "- unknown: use only when the document cannot be classified with reasonable confidence.\n"
)


def classification_prompt(text: str, include_images: bool = False) -> str:
    vision_hint = (
        "You are also given document page images. Use visual cues such as headers, seals, tables, stamps, "
        "signatures, and layout together with the OCR text.\n"
        if include_images
        else ""
    )
    return (
        "You are classifying a KYC supporting document.\n"
        f"{vision_hint}"
        f"{CLASSIFICATION_GUIDANCE}"
        "Classify the document into exactly one of: marriage_certificate, medex_or_exam_document, "
        "other_supporting_document, unknown. Confidence must be a numeric value between 0 and 1. "
        "Return JSON only with keys doc_type, confidence, reasons.\n\n"
        "OCR_TEXT:\n"
        f"{text[:12000]}"
    )


def extraction_prompt(
    doc_type: str,
    text: str,
    applicant_context: dict[str, str],
    include_images: bool = False,
) -> str:
    context = json.dumps(applicant_context, ensure_ascii=True)
    vision_hint = (
        "You are also given document page images from the same PDF. Use visual cues, form structure, titles, "
        "seals, and non-text evidence together with the OCR text.\n"
        if include_images
        else ""
    )
    schema_hint = {
        "marriage_certificate": "applicant_name_from_doc, applicant_ic_from_doc, spouse_name_from_doc, spouse_ic_from_doc, marriage_registration_no, marriage_date, issuing_authority, document_language, key_supporting_snippets, page_refs, extraction_confidence",
        "medex_or_exam_document": "candidate_name_from_doc, candidate_ic_from_doc, exam_name, exam_status_or_result, exam_date, issuing_body, document_language, key_supporting_snippets, page_refs, extraction_confidence",
        "other_supporting_document": "possible_subject_name, possible_subject_ic, document_title, document_date, issuing_body, key_supporting_snippets, page_refs, extraction_confidence",
        "unknown": "possible_subject_name, possible_subject_ic, document_title, document_date, issuing_body, key_supporting_snippets, page_refs, extraction_confidence",
    }[doc_type]
    return (
        f"{vision_hint}"
        f"Extract fields for {doc_type}. The doc_type field in your JSON must be exactly \"{doc_type}\". "
        "The applicant row context is for cross-checking only. Never copy values from applicant context into extracted "
        "document fields unless they are explicitly visible in the OCR text or page images. If a field is not directly "
        "visible, return null. page_refs must be integer page numbers. extraction_confidence must be a numeric value "
        f"between 0 and 1. Return strict JSON only with keys: doc_type, {schema_hint}. Use page numbers from the "
        f"[Page N] markers when possible. OCR text may be partial or noisy. Applicant row context: {context}.\n\n"
        f"OCR_TEXT:\n{text[:16000]}"
    )
