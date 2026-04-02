"""Langflow component for OCR routing."""

from __future__ import annotations

from pathlib import Path

from src.langflow_components._base import Component
from src.ocr.ocr_router import OCRRouter
from src.settings import load_app_config


class OCRRouterComponent(Component):
    display_name = "OCR Router"
    description = "Run direct text extraction, OCR, and fallback routing for a PDF bundle."
    name = "OCRRouterComponent"

    def run_model(self, applicant_id: str, pdf_path: str) -> dict:
        settings = load_app_config(project_root=Path(__file__).resolve().parents[2])
        router = OCRRouter(settings)
        document = router.process_document(applicant_id, pdf_path)
        return document.model_dump(mode="json")
