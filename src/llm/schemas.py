"""JSON response schemas expected from the local model."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ClassificationSchema(BaseModel):
    doc_type: Literal[
        "marriage_certificate",
        "medex_or_exam_document",
        "other_supporting_document",
        "unknown",
    ]
    confidence: float = 0.0
    reasons: list[str] = Field(default_factory=list)


class MarriageExtractionSchema(BaseModel):
    doc_type: Literal["marriage_certificate"]
    applicant_name_from_doc: str | None = None
    applicant_ic_from_doc: str | None = None
    spouse_name_from_doc: str | None = None
    spouse_ic_from_doc: str | None = None
    marriage_registration_no: str | None = None
    marriage_date: str | None = None
    issuing_authority: str | None = None
    document_language: str | None = None
    key_supporting_snippets: list[str] = Field(default_factory=list)
    page_refs: list[int] = Field(default_factory=list)
    extraction_confidence: float = 0.0


class MedexExtractionSchema(BaseModel):
    doc_type: Literal["medex_or_exam_document"]
    candidate_name_from_doc: str | None = None
    candidate_ic_from_doc: str | None = None
    exam_name: str | None = None
    exam_status_or_result: str | None = None
    exam_date: str | None = None
    issuing_body: str | None = None
    document_language: str | None = None
    key_supporting_snippets: list[str] = Field(default_factory=list)
    page_refs: list[int] = Field(default_factory=list)
    extraction_confidence: float = 0.0


class GenericExtractionSchema(BaseModel):
    doc_type: Literal["other_supporting_document", "unknown"]
    possible_subject_name: str | None = None
    possible_subject_ic: str | None = None
    document_title: str | None = None
    document_date: str | None = None
    issuing_body: str | None = None
    key_supporting_snippets: list[str] = Field(default_factory=list)
    page_refs: list[int] = Field(default_factory=list)
    extraction_confidence: float = 0.0


class FirstPassSignalsSchema(BaseModel):
    marriage: Literal["present", "not_present", "manual_check"] = "not_present"
    self_illness: Literal["present", "not_present", "manual_check"] = "not_present"
    family_illness: Literal["present", "not_present", "manual_check"] = "not_present"
    spouse_location: Literal["present", "not_present", "manual_check"] = "not_present"
    oku_self_or_family: Literal["present", "not_present", "manual_check"] = "not_present"
    medex_or_other_exam: Literal["present", "not_present", "manual_check"] = "not_present"
    reasons: list[str] = Field(default_factory=list)
