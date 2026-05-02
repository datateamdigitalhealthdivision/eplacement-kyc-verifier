"""Langflow component for broad first-pass evidence scan."""

from __future__ import annotations

from pathlib import Path

from src.extraction.applicant_claims import ApplicantClaims
from src.extraction.evidence_models import FirstPassEvidenceSignals, OCRDocument
from src.extraction.first_pass_signals import FirstPassEvidenceScanner
from src.langflow_components._base import Component
from src.llm.ollama_client import OllamaClient
from src.settings import AppConfig, load_app_config


class FirstPassSignalsComponent(Component):
    display_name = "Evidence Signals"
    description = "Verify applicant evidence claims from the PDF bundle."
    name = "FirstPassSignalsComponent"

    def __init__(self, settings: AppConfig | None = None, llm_client: OllamaClient | None = None, project_root: Path | None = None, **kwargs):
        super().__init__(**kwargs)
        root = project_root or Path(__file__).resolve().parents[2]
        self.settings = settings or load_app_config(project_root=root)
        self.llm_client = llm_client or OllamaClient(self.settings)
        self.scanner = FirstPassEvidenceScanner(self.settings, self.llm_client)

    def scan_document(
        self,
        document: OCRDocument,
        applicant_context: dict[str, str] | None = None,
        claims: ApplicantClaims | None = None,
        verifier_mode: str | None = None,
    ) -> FirstPassEvidenceSignals:
        mode = verifier_mode or self.settings.verifier.mode
        return self.scanner.scan(document, applicant_context=applicant_context, claims=claims, verifier_mode=mode)

    def run_model(self, ocr_document: dict, applicant_context: dict | None = None, claims: dict | None = None, verifier_mode: str | None = None) -> dict:
        document = OCRDocument.model_validate(ocr_document)
        context = {str(key): str(value or "") for key, value in (applicant_context or {}).items()}
        claim_model = ApplicantClaims.model_validate(claims or {}) if claims is not None else None
        return self.scan_document(document, context, claims=claim_model, verifier_mode=verifier_mode).model_dump(mode="json")
