"""Health endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from src.api.service import get_service
from src.services.pipeline_service import PipelineService


router = APIRouter(tags=["health"])


@router.get("/health")
def health(service: PipelineService = Depends(get_service)) -> dict:
    return service.health()
