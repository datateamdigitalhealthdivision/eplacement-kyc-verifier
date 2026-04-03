"""Langflow component for document classification."""

from __future__ import annotations

from pathlib import Path

from src.classification.doc_classifier import HybridDocClassifier
from src.extraction.evidence_models import DocumentClassification, OCRDocument
from src.langflow_components._base import Component
from src.llm.ollama_client import OllamaClient
from src.settings import AppConfig, load_app_config


class DocClassifierComponent(Component):
    display_name = "Doc Classifier"
    description = "Classify OCR text and page images into supported evidence types."
    name = "DocClassifierComponent"

    def __init__(self, settings: AppConfig | None = None, llm_client: OllamaClient | None = None, project_root: Path | None = None, **kwargs):
        super().__init__(**kwargs)
        root = project_root or Path(__file__).resolve().parents[2]
        self.settings = settings or load_app_config(project_root=root)
        self.llm_client = llm_client or OllamaClient(self.settings)
        self.classifier = HybridDocClassifier(self.llm_client)

    def can_use_vision(self, document: OCRDocument) -> bool:
        return self.classifier.can_use_vision(document.page_image_paths)

    def classify_document(self, document: OCRDocument) -> DocumentClassification:
        return self.classifier.classify(document.combined_text, document.page_image_paths)

    def run_model(self, ocr_document: dict) -> dict:
        document = OCRDocument.model_validate(ocr_document)
        return self.classify_document(document).model_dump(mode="json")
