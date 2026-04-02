"""Langflow component for evidence extraction."""

from __future__ import annotations

from pathlib import Path

from src.extraction.generic_extractor import GenericExtractor
from src.extraction.marriage_extractor import MarriageExtractor
from src.extraction.medex_extractor import MedexExtractor
from src.extraction.evidence_models import OCRDocument
from src.langflow_components._base import Component
from src.llm.ollama_client import OllamaClient
from src.settings import load_app_config


class EvidenceExtractorComponent(Component):
    display_name = "Evidence Extractor"
    description = "Extract evidence fields for the chosen document type."
    name = "EvidenceExtractorComponent"

    def run_model(self, ocr_document: dict, applicant_context: dict, target_type: str) -> dict:
        settings = load_app_config(project_root=Path(__file__).resolve().parents[2])
        llm_client = OllamaClient(settings)
        document = OCRDocument.model_validate(ocr_document)
        if target_type == "marriage_certificate":
            return MarriageExtractor(settings, llm_client).extract(document, applicant_context).model_dump(mode="json")
        if target_type == "medex_or_exam_document":
            return MedexExtractor(settings, llm_client).extract(document, applicant_context).model_dump(mode="json")
        return GenericExtractor(settings, llm_client).extract(document, applicant_context).model_dump(mode="json")
