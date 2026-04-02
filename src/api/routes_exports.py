"""Export listing endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from src.api.service import get_service
from src.db.models import ExportBundle
from src.services.pipeline_service import PipelineService


router = APIRouter(prefix="/exports", tags=["exports"])


@router.get("/latest", response_model=ExportBundle)
def latest_exports(job_id: str | None = None, service: PipelineService = Depends(get_service)) -> ExportBundle:
    bundle = service.latest_exports(job_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail="No exports available.")
    return bundle
