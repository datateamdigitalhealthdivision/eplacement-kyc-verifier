"""Shared pydantic models for OCR, extraction, and validation."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


StatusLiteral = Literal[
    "CONFIRMED",
    "NOT_EVIDENCED_OR_INCONSISTENT",
    "MANUAL_REVIEW_REQUIRED",
    "DOCUMENT_MISSING",
    "OCR_FAILED",
    "DOWNLOAD_FAILED",
    "UNSUPPORTED_DOCUMENT_TYPE",
]
DocTypeLiteral = Literal[
    "marriage_certificate",
    "medex_or_exam_document",
    "other_supporting_document",
    "unknown",
]
SignalStatusLiteral = Literal["present", "not_present", "manual_check"]


class OCRPage(BaseModel):
    page_number: int
    extracted_text: str = ""
    engine_used: str
    confidence: float | None = None
    language_guess: str = "unknown"
    low_confidence: bool = False
    bounding_boxes: list[list[int | float]] = Field(default_factory=list)
    source_hash: str | None = None


class OCRDocument(BaseModel):
    applicant_id: str
    document_path: str
    document_hash: str
    processing_hash: str
    pages: list[OCRPage] = Field(default_factory=list)
    page_image_paths: list[str] = Field(default_factory=list)
    combined_text: str = ""
    extracted_at: datetime = Field(default_factory=datetime.utcnow)
    warnings: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentClassification(BaseModel):
    primary_type: DocTypeLiteral = "unknown"
    candidate_types: list[DocTypeLiteral] = Field(default_factory=list)
    confidence: float = 0.0
    method: str = "regex"
    matched_signals: list[str] = Field(default_factory=list)
    llm_payload: dict[str, Any] | None = None


class BaseEvidence(BaseModel):
    doc_type: DocTypeLiteral
    document_language: str | None = None
    key_supporting_snippets: list[str] = Field(default_factory=list)
    page_refs: list[int] = Field(default_factory=list)
    extraction_confidence: float = 0.0
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class MarriageEvidence(BaseEvidence):
    doc_type: DocTypeLiteral = "marriage_certificate"
    applicant_name_from_doc: str | None = None
    applicant_ic_from_doc: str | None = None
    spouse_name_from_doc: str | None = None
    spouse_ic_from_doc: str | None = None
    marriage_registration_no: str | None = None
    marriage_date: str | None = None
    issuing_authority: str | None = None


class MedexEvidence(BaseEvidence):
    doc_type: DocTypeLiteral = "medex_or_exam_document"
    candidate_name_from_doc: str | None = None
    candidate_ic_from_doc: str | None = None
    exam_name: str | None = None
    exam_status_or_result: str | None = None
    exam_date: str | None = None
    issuing_body: str | None = None


class GenericEvidence(BaseEvidence):
    doc_type: DocTypeLiteral = "other_supporting_document"
    possible_subject_name: str | None = None
    possible_subject_ic: str | None = None
    document_title: str | None = None
    document_date: str | None = None
    issuing_body: str | None = None


class ValidationDecision(BaseModel):
    final_status: StatusLiteral
    evidence_type: str
    reasons: list[str] = Field(default_factory=list)
    matched_fields: list[str] = Field(default_factory=list)
    mismatched_fields: list[str] = Field(default_factory=list)
    manual_review_required: bool = False
    low_confidence_flags: list[str] = Field(default_factory=list)
    recommended_action: str | None = None
    final_confidence: float = 0.0


class FirstPassEvidenceSignals(BaseModel):
    marriage: SignalStatusLiteral = "not_present"
    self_illness: SignalStatusLiteral = "not_present"
    family_illness: SignalStatusLiteral = "not_present"
    spouse_location: SignalStatusLiteral = "not_present"
    oku_self_or_family: SignalStatusLiteral = "not_present"
    medex_or_other_exam: SignalStatusLiteral = "not_present"
    reasons: list[str] = Field(default_factory=list)
    raw_payload: dict[str, Any] = Field(default_factory=dict)


class EvidenceResult(BaseModel):
    job_id: str
    applicant_id: str
    applicant_name: str | None = None
    row_index: int
    source_pdf_name: str | None = None
    source_pdf_path: str | None = None
    download_url: str | None = None
    document_type: str
    evidence_type: str
    ocr_engine: str | None = None
    ocr_confidence: float | None = None
    llm_confidence: float | None = None
    extracted_applicant_ic: str | None = None
    extracted_spouse_ic: str | None = None
    extracted_name_fields: list[str] = Field(default_factory=list)
    page_refs: list[int] = Field(default_factory=list)
    final_status: StatusLiteral
    final_reason: str
    manual_review_flag: bool = False
    processing_time_seconds: float = 0.0
    document_hash: str | None = None
    processing_hash: str | None = None
    matched_fields: list[str] = Field(default_factory=list)
    mismatched_fields: list[str] = Field(default_factory=list)
    snippets: list[str] = Field(default_factory=list)
    llm_json: dict[str, Any] | None = None
    audit_payload: dict[str, Any] = Field(default_factory=dict)
    override_status: str | None = None
    override_note: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)

    def effective_status(self) -> str:
        return self.override_status or self.final_status
