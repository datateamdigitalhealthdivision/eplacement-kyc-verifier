"""Shared API dependencies."""

from __future__ import annotations

from pathlib import Path

from src.services.pipeline_service import PipelineService


SERVICE = PipelineService(project_root=Path(__file__).resolve().parents[2])


def get_service() -> PipelineService:
    return SERVICE
