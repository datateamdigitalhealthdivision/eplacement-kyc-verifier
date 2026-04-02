"""Job management endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from src.api.service import get_service
from src.db.models import JobEvent, JobRecord, RetryFailedRequest, RunJobRequest
from src.services.pipeline_service import PipelineService


router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/run", response_model=JobRecord)
def run_job(
    request: RunJobRequest,
    background: bool = Query(default=False),
    service: PipelineService = Depends(get_service),
) -> JobRecord:
    job = service.run_job(request, background=background)
    if job is None:
        raise HTTPException(status_code=500, detail="Failed to start job.")
    return job


@router.post("/retry-failed", response_model=JobRecord)
def retry_failed(
    request: RetryFailedRequest,
    background: bool = Query(default=False),
    service: PipelineService = Depends(get_service),
) -> JobRecord:
    try:
        job = service.retry_failed(request, background=background)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if job is None:
        raise HTTPException(status_code=500, detail="Failed to retry job.")
    return job


@router.get("/{job_id}", response_model=JobRecord)
def get_job(job_id: str, service: PipelineService = Depends(get_service)) -> JobRecord:
    job = service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found.")
    return job


@router.get("/{job_id}/logs", response_model=list[JobEvent])
def get_job_logs(job_id: str, service: PipelineService = Depends(get_service)) -> list[JobEvent]:
    return service.get_logs(job_id)
