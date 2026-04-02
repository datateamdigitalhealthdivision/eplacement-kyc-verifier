"""Langflow component for document classification."""

from __future__ import annotations

from pathlib import Path

from src.classification.doc_classifier import HybridDocClassifier
from src.extraction.evidence_models import OCRDocument
from src.langflow_components._base import Component
from src.llm.ollama_client import OllamaClient
from src.settings import load_app_config


class DocClassifierComponent(Component):
    display_name = "Doc Classifier"
    description = "Classify OCR text and page images into supported evidence types."
    name = "DocClassifierComponent"

    def run_model(self, ocr_document: dict) -> dict:
        settings = load_app_config(project_root=Path(__file__).resolve().parents[2])
        classifier = HybridDocClassifier(OllamaClient(settings))
        document = OCRDocument.model_validate(ocr_document)
        return classifier.classify(document.combined_text, document.page_image_paths).model_dump(mode="json")
