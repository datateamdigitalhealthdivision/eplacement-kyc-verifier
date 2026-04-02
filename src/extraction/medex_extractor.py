"""MedEX/postgraduate document extraction with heuristic and Ollama fallback."""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.extraction.evidence_models import MedexEvidence, OCRDocument
from src.llm.ollama_client import OllamaClient
from src.llm.parser import parse_model_response
from src.llm.prompts import extraction_prompt
from src.llm.schemas import MedexExtractionSchema
from src.settings import AppConfig
from src.utils.language_guess import guess_script
from src.utils.text_cleaning import normalize_whitespace


class MedexExtractor:
    def __init__(self, settings: AppConfig, llm_client: OllamaClient | None = None) -> None:
        self.settings = settings
        self.llm_client = llm_client

    def _cache_path(self, processing_hash: str, mode: str, model_name: str | None = None) -> Path:
        suffix = f"_{OllamaClient.cache_slug(model_name)}" if model_name else ""
        return self.settings.paths.llm_json_dir / f"{processing_hash}_medex_{mode}{suffix}.json"

    @staticmethod
    def _first_match(patterns: list[str], text: str) -> str | None:
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                return normalize_whitespace(match.group(1))
        return None

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

    def _page_refs(self, document: OCRDocument, terms: list[str]) -> list[int]:
        refs = []
        for page in document.pages:
            page_text_upper = page.extracted_text.upper()
            if any(term.upper() in page_text_upper for term in terms if term):
                refs.append(page.page_number)
        return refs

    def _heuristic_extract(self, document: OCRDocument) -> MedexEvidence:
        text = document.combined_text
        candidate_name = self._first_match(
            [
                r"(?:NAMA\s+CALON|CANDIDATE\s+NAME|NAMA\s+PESERTA)\s*[:\-]\s*([^\n]+)",
            ],
            text,
        )
        candidate_ic = self._first_match(
            [
                r"(?:NO\.?\s*KP|NO\.?\s*PENGENALAN\s+DIRI|IDENTITY\s+CARD|CANDIDATE\s+IC)\s*[:\-]\s*([0-9\- ]{8,20})",
            ],
            text,
        )
        exam_name = self._first_match(
            [
                r"(?:NAMA\s+PEPERIKSAAN|EXAM(?:INATION)?\s+NAME)\s*[:\-]\s*([^\n]+)",
                r"\b(MEDEX|GCFM|PEPERIKSAAN\s+KEMASUKAN)\b",
            ],
            text,
        )
        exam_result = self._first_match(
            [r"(?:KEPUTUSAN|RESULT|STATUS)\s*[:\-]\s*([^\n]+)"],
            text,
        )
        exam_date = self._first_match(
            [r"(?:TARIKH|DATE)\s*[:\-]\s*([^\n]+)"],
            text,
        )
        authority_match = re.search(
            r"(?:MALAYSIAN\s+MEDICAL\s+COUNCIL[^\n]*|MAJLIS\s+PERUBATAN\s+MALAYSIA[^\n]*|ISSUING\s+BODY\s*[:\-]\s*[^\n]+)",
            text,
            flags=re.IGNORECASE,
        )
        issuing_body = normalize_whitespace(authority_match.group(0)) if authority_match else None
        snippets = [
            line.strip()
            for line in text.splitlines()
            if any(keyword in line.upper() for keyword in ["MEDEX", "KEPUTUSAN", "EXAM", "GCFM"])
        ][:5]
        refs = self._page_refs(document, [candidate_name or "", exam_name or "MEDEX", exam_result or "KEPUTUSAN"])
        found_fields = [candidate_name, candidate_ic, exam_name, exam_result, exam_date, issuing_body]
        confidence = round(sum(1 for value in found_fields if value) / 6, 2)
        language = "arabic_script" if guess_script(text) == "arabic_script" else "english_malay"
        return MedexEvidence(
            candidate_name_from_doc=candidate_name,
            candidate_ic_from_doc=candidate_ic,
            exam_name=exam_name,
            exam_status_or_result=exam_result,
            exam_date=exam_date,
            issuing_body=issuing_body,
            document_language=language,
            key_supporting_snippets=snippets,
            page_refs=refs,
            extraction_confidence=confidence,
            raw_payload={"_method": "heuristic"},
        )

    def extract(self, document: OCRDocument, applicant_context: dict[str, str]) -> MedexEvidence:
        desired_mode, model_name = self._desired_mode(document)
        cache_path = self._cache_path(document.processing_hash, desired_mode, model_name)
        if cache_path.exists():
            return MedexEvidence.model_validate(json.loads(cache_path.read_text(encoding="utf-8")))

        result = self._heuristic_extract(document)
        images = self._document_images(document)
        if desired_mode == "ollama_vision":
            try:
                response = self.llm_client.generate_vision(
                    extraction_prompt("medex_or_exam_document", document.combined_text, applicant_context, include_images=True),
                    image_paths=images,
                )
                payload = parse_model_response(response, MedexExtractionSchema, overrides={'doc_type': 'medex_or_exam_document'})
                result = MedexEvidence(
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
                    extraction_prompt("medex_or_exam_document", document.combined_text, applicant_context)
                )
                payload = parse_model_response(response, MedexExtractionSchema, overrides={'doc_type': 'medex_or_exam_document'})
                result = MedexEvidence(
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

