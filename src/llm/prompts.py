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


def first_pass_signals_prompt(
    text: str,
    applicant_context: dict[str, str] | None = None,
    include_images: bool = False,
    page_range: str | None = None,
) -> str:
    vision_hint = (
        "You are also given page images from a PDF bundle. A single PDF may contain multiple different documents. "
        "Use what you can see in the images together with any OCR text.\n"
        if include_images
        else ""
    )
    page_hint = f"The supplied content is from pages {page_range}.\n" if page_range else ""
    context_payload = {
        key: value
        for key, value in (applicant_context or {}).items()
        if key
        in {
            "applicant_id",
            "applicant_name",
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
            "postgraduate_status",
            "current_headquarters",
            "current_placement",
        }
        and str(value or "").strip()
    }
    context_hint = (
        "Spreadsheet context for relationship disambiguation only. Use it only to decide who the document is about. "
        "Do not invent evidence that is not visible in the document.\n"
        f"APPLICANT_CONTEXT: {json.dumps(context_payload, ensure_ascii=True)}\n"
        if context_payload
        else ""
    )
    return (
        "You are doing a first-pass evidence scan for KYC review.\n"
        f"{vision_hint}"
        f"{page_hint}"
        f"{context_hint}"
        "Do not force the whole PDF into one main document type. Instead, decide whether each evidence bucket is present, not_present, or manual_check based on anything visible in the supplied pages.\n"
        "Use present when the evidence is clearly visible. Use not_present when there is no sign of it. Use manual_check only when there is a possible signal but it is too ambiguous to call present.\n"
        "Use manual_check sparingly. If the page is generic, weak, or not clearly about the target evidence, prefer not_present.\n"
        "Evidence buckets:\n"
        "- marriage: actual marriage certificate or clear marriage evidence such as surat perakuan nikah or sijil nikah.\n"
        "- self_illness: evidence the applicant has illness, treatment, follow-up care, diagnosis, admission, medication, or ongoing medical issues. Use applicant context to decide whether the medical subject is the applicant. Do not mark self_illness just because a family member has a medical document.\n"
        "- family_illness: evidence that a spouse, child, parent, or other family member has illness, treatment, follow-up care, diagnosis, admission, medication, or ongoing medical issues. If a medical document is clearly about someone other than the applicant, prefer family_illness over self_illness.\n"
        "- spouse_location: evidence of spouse working location or placement. This includes appointment letters, placement letters, posting letters, transfer letters, report-to-duty letters, office assignment letters, or clear place-of-work or location evidence for the spouse. Use spouse name, spouse ID, spouse job title, or spouse workplace context when visible. If the letter is clearly for someone other than the applicant and that person matches the spouse context, mark spouse_location present.\n"
        "- oku_self_or_family: evidence of official OKU or disability registration, approval, card, or status for the applicant or a family member. Do not use this just because there is illness.\n"
        "- medex_or_other_exam: only official MedEX, GCFM, exam attendance, exam result, exam certificate, or postgraduate or entrance examination evidence. Do not count ordinary clinic visits, hospital notes, routine physical examination sheets, treatment summaries, therapy notes, medical memos, discharge letters, or general medical reports as medex_or_other_exam. The word peperiksaan or examination by itself is not enough.\n"
        "Relationship rules:\n"
        "- If the bundle clearly shows both applicant illness and family illness on different pages, both can be present.\n"
        "- If the medical pages point to only one person and that person is the spouse or family member, do not also mark self_illness.\n"
        "- If marriage evidence exists elsewhere in the bundle, that can help confirm spouse context for spouse_location, but it is not required.\n"
        "Return JSON only with keys marriage, self_illness, family_illness, spouse_location, oku_self_or_family, medex_or_other_exam, reasons.\n\n"
        "OCR_TEXT:\n"
        f"{text[:12000]}"
    )
