"""Review queue endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.service import get_service
from src.db.models import OverrideRequest, ReviewRecord
from src.services.pipeline_service import PipelineService


router = APIRouter(tags=["review"])


@router.get("/review", response_model=list[ReviewRecord])
def list_review_records(
    job_id: str | None = None,
    status: str | None = Query(default=None),
    document_type: str | None = Query(default=None),
    reason_contains: str | None = Query(default=None),
    service: PipelineService = Depends(get_service),
) -> list[ReviewRecord]:
    return service.list_review_records(job_id=job_id, status=status, document_type=document_type, reason_contains=reason_contains)


@router.post("/review/{record_id}/override", response_model=ReviewRecord)
def override_review(
    record_id: int,
    override: OverrideRequest,
    service: PipelineService = Depends(get_service),
) -> ReviewRecord:
    record = service.override_review(record_id, override)
    if record is None:
        raise HTTPException(status_code=404, detail="Review record not found.")
    return record
