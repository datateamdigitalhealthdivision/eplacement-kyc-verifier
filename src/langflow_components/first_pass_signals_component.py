"""Langflow component for broad first-pass evidence scan."""

from __future__ import annotations

from pathlib import Path

from src.extraction.evidence_models import FirstPassEvidenceSignals, OCRDocument
from src.extraction.first_pass_signals import FirstPassEvidenceScanner
from src.langflow_components._base import Component
from src.llm.ollama_client import OllamaClient
from src.settings import AppConfig, load_app_config


class FirstPassSignalsComponent(Component):
    display_name = "Evidence Signals"
    description = "Scan the whole PDF for broad first-pass evidence categories."
    name = "FirstPassSignalsComponent"

    def __init__(self, settings: AppConfig | None = None, llm_client: OllamaClient | None = None, project_root: Path | None = None, **kwargs):
        super().__init__(**kwargs)
        root = project_root or Path(__file__).resolve().parents[2]
        self.settings = settings or load_app_config(project_root=root)
        self.llm_client = llm_client or OllamaClient(self.settings)
        self.scanner = FirstPassEvidenceScanner(self.settings, self.llm_client)

    def scan_document(self, document: OCRDocument, applicant_context: dict[str, str] | None = None) -> FirstPassEvidenceSignals:
        return self.scanner.scan(document, applicant_context=applicant_context)

    def run_model(self, ocr_document: dict, applicant_context: dict | None = None) -> dict:
        document = OCRDocument.model_validate(ocr_document)
        context = {str(key): str(value or "") for key, value in (applicant_context or {}).items()}
        return self.scan_document(document, context).model_dump(mode="json")
