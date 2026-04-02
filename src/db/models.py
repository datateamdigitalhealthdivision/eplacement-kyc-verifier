"""Database and API-facing record models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class JobRecord(BaseModel):
    job_id: str
    status: str
    applicant_source: str
    pdf_directory: str
    created_at: datetime
    updated_at: datetime
    progress_total: int = 0
    progress_completed: int = 0
    counters: dict[str, int] = Field(default_factory=dict)
    config_snapshot: dict[str, Any] = Field(default_factory=dict)
    latest_error: str | None = None


class JobEvent(BaseModel):
    job_id: str
    level: str
    message: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    payload: dict[str, Any] = Field(default_factory=dict)


class ReviewRecord(BaseModel):
    record_id: int
    job_id: str
    applicant_id: str
    document_type: str
    final_status: str
    manual_review_flag: bool
    reason: str
    result_kind: str | None = None
    review_category: str | None = None
    triage_note: str | None = None
    expected_document_type: str | None = None
    observed_document_type: str | None = None
    source_pdf_path: str | None = None
    extracted_json: dict[str, Any] = Field(default_factory=dict)
    audit_json: dict[str, Any] = Field(default_factory=dict)
    ocr_text_preview: str = ""
    override_status: str | None = None
    override_note: str | None = None


class ExportBundle(BaseModel):
    job_id: str
    validation_csv: str
    validation_xlsx: str
    merged_csv: str
    merged_xlsx: str
    review_csv: str
    review_xlsx: str
    summary_csv: str
    summary_json: str
    decision_csv: str | None = None
    decision_xlsx: str | None = None


class RunJobRequest(BaseModel):
    applicant_path: str
    pdf_directory: str | None = None
    auto_download: bool = True
    retry_failed_only: bool = False


class OverrideRequest(BaseModel):
    override_status: str
    reviewer_note: str | None = None


class RetryFailedRequest(BaseModel):
    applicant_path: str | None = None
    pdf_directory: str | None = None
