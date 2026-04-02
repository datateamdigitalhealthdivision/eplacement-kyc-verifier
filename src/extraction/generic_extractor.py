"""Generic extractor for unsupported or ambiguous documents."""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.extraction.evidence_models import GenericEvidence, OCRDocument
from src.llm.ollama_client import OllamaClient
from src.llm.parser import parse_model_response
from src.llm.prompts import extraction_prompt
from src.llm.schemas import GenericExtractionSchema
from src.settings import AppConfig
from src.utils.language_guess import guess_script
from src.utils.text_cleaning import normalize_whitespace


class GenericExtractor:
    def __init__(self, settings: AppConfig, llm_client: OllamaClient | None = None) -> None:
        self.settings = settings
        self.llm_client = llm_client

    def _cache_path(self, processing_hash: str, mode: str, model_name: str | None = None) -> Path:
        suffix = f"_{OllamaClient.cache_slug(model_name)}" if model_name else ""
        return self.settings.paths.llm_json_dir / f"{processing_hash}_generic_{mode}{suffix}.json"

    @staticmethod
    def _document_images(document: OCRDocument) -> list[str]:
        return document.page_image_paths or list(document.metadata.get("page_image_paths", []))

    def _desired_mode(self, document: OCRDocument) -> tuple[str, str | None]:
        image_paths = self._document_images(document)
        if self.llm_client and self.llm_client.is_vision_enabled() and image_paths:
            return "ollama_vision", self.llm_client.vision_model_name()
        if self.llm_client and self.llm_client.is_enabled() and document.combined_text:
            return "ollama_text", self.llm_client.text_model_name()
        return "heuristic", None

    def _heuristic_extract(self, document: OCRDocument) -> GenericEvidence:
        lines = [normalize_whitespace(line) for line in document.combined_text.splitlines() if normalize_whitespace(line)]
        title = lines[0] if lines else None
        date_match = re.search(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", document.combined_text)
        ic_match = re.search(r"\b\d{6}[- ]?\d{2}[- ]?\d{4}\b|\b\d{12}\b", document.combined_text)
        name_match = re.search(r"(?:NAMA|NAME)\s*[:\-]\s*([^\n]+)", document.combined_text, flags=re.IGNORECASE)
        snippets = lines[:3]
        refs = [page.page_number for page in document.pages if snippets and snippets[0] in page.extracted_text][:1]
        confidence = 0.5 if lines else 0.0
        return GenericEvidence(
            doc_type="other_supporting_document",
            possible_subject_name=normalize_whitespace(name_match.group(1)) if name_match else None,
            possible_subject_ic=ic_match.group(0) if ic_match else None,
            document_title=title,
            document_date=date_match.group(0) if date_match else None,
            issuing_body=None,
            document_language="arabic_script" if guess_script(document.combined_text) == "arabic_script" else "english_malay",
            key_supporting_snippets=snippets,
            page_refs=refs,
            extraction_confidence=confidence,
            raw_payload={"_method": "heuristic"},
        )

    def extract(self, document: OCRDocument, applicant_context: dict[str, str]) -> GenericEvidence:
        desired_mode, model_name = self._desired_mode(document)
        cache_path = self._cache_path(document.processing_hash, desired_mode, model_name)
        if cache_path.exists():
            return GenericEvidence.model_validate(json.loads(cache_path.read_text(encoding="utf-8")))

        result = self._heuristic_extract(document)
        images = self._document_images(document)
        if desired_mode == "ollama_vision":
            try:
                response = self.llm_client.generate_vision(
                    extraction_prompt("other_supporting_document", document.combined_text, applicant_context, include_images=True),
                    image_paths=images,
                )
                payload = parse_model_response(response, GenericExtractionSchema, overrides={'doc_type': 'other_supporting_document'})
                result = GenericEvidence(
                    **payload.model_dump(),
                    raw_payload={
                        **payload.model_dump(mode="json"),
                        "_method": desired_mode,
                        "_model": model_name,
                    },
                )
            except Exception:  # noqa: BLE001
                pass
        elif desired_mode == "ollama_text":
            try:
                response = self.llm_client.generate(
                    extraction_prompt("other_supporting_document", document.combined_text, applicant_context)
                )
                payload = parse_model_response(response, GenericExtractionSchema, overrides={'doc_type': 'other_supporting_document'})
                result = GenericEvidence(
                    **payload.model_dump(),
                    raw_payload={
                        **payload.model_dump(mode="json"),
                        "_method": desired_mode,
                        "_model": model_name,
                    },
                )
            except Exception:  # noqa: BLE001
                pass

        if desired_mode == "heuristic" or result.raw_payload.get("_method") == desired_mode:
            cache_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return result

