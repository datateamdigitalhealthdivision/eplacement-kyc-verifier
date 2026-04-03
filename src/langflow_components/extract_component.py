"""Langflow component for evidence extraction."""

from __future__ import annotations

from pathlib import Path

from src.extraction.evidence_models import GenericEvidence, MarriageEvidence, MedexEvidence, OCRDocument
from src.extraction.generic_extractor import GenericExtractor
from src.extraction.marriage_extractor import MarriageExtractor
from src.extraction.medex_extractor import MedexExtractor
from src.langflow_components._base import Component
from src.llm.ollama_client import OllamaClient
from src.settings import AppConfig, load_app_config


class EvidenceExtractorComponent(Component):
    display_name = "Evidence Extractor"
    description = "Extract evidence fields for the chosen document type."
    name = "EvidenceExtractorComponent"

    def __init__(self, settings: AppConfig | None = None, llm_client: OllamaClient | None = None, project_root: Path | None = None, **kwargs):
        super().__init__(**kwargs)
        root = project_root or Path(__file__).resolve().parents[2]
        self.settings = settings or load_app_config(project_root=root)
        self.llm_client = llm_client or OllamaClient(self.settings)
        self.marriage_extractor = MarriageExtractor(self.settings, self.llm_client)
        self.medex_extractor = MedexExtractor(self.settings, self.llm_client)
        self.generic_extractor = GenericExtractor(self.settings, self.llm_client)

    def extract_document(self, ocr_document: OCRDocument, applicant_context: dict, target_type: str) -> MarriageEvidence | MedexEvidence | GenericEvidence:
        if target_type == "marriage_certificate":
            return self.marriage_extractor.extract(ocr_document, applicant_context)
        if target_type == "medex_or_exam_document":
            return self.medex_extractor.extract(ocr_document, applicant_context)
        return self.generic_extractor.extract(ocr_document, applicant_context)

    def run_model(self, ocr_document: dict, applicant_context: dict, target_type: str) -> dict:
        document = OCRDocument.model_validate(ocr_document)
        return self.extract_document(document, applicant_context, target_type).model_dump(mode="json")
