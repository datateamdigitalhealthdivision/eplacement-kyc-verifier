"""Langflow component for OCR routing."""

from __future__ import annotations

from pathlib import Path

from src.extraction.evidence_models import OCRDocument
from src.langflow_components._base import Component
from src.ocr.ocr_router import OCRRouter
from src.settings import AppConfig, load_app_config


class OCRRouterComponent(Component):
    display_name = "OCR Router"
    description = "Run direct text extraction, OCR, and fallback routing for a PDF bundle."
    name = "OCRRouterComponent"

    def __init__(self, settings: AppConfig | None = None, project_root: Path | None = None, **kwargs):
        super().__init__(**kwargs)
        root = project_root or Path(__file__).resolve().parents[2]
        self.settings = settings or load_app_config(project_root=root)
        self.router = OCRRouter(self.settings)

    def process_document(self, applicant_id: str, pdf_path: str) -> OCRDocument:
        return self.router.process_document(applicant_id, pdf_path)

    def run_model(self, applicant_id: str, pdf_path: str) -> dict:
        return self.process_document(applicant_id, pdf_path).model_dump(mode="json")
