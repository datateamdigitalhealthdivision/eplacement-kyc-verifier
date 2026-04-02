"""Marriage certificate extraction with heuristic and Ollama fallback."""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.extraction.evidence_models import MarriageEvidence, OCRDocument
from src.llm.ollama_client import OllamaClient
from src.llm.parser import parse_model_response
from src.llm.prompts import extraction_prompt
from src.llm.schemas import MarriageExtractionSchema
from src.settings import AppConfig
from src.utils.language_guess import guess_script
from src.utils.text_cleaning import normalize_whitespace


class MarriageExtractor:
    def __init__(self, settings: AppConfig, llm_client: OllamaClient | None = None) -> None:
        self.settings = settings
        self.llm_client = llm_client

    def _cache_path(self, processing_hash: str, mode: str, model_name: str | None = None) -> Path:
        suffix = f"_{OllamaClient.cache_slug(model_name)}" if model_name else ""
        return self.settings.paths.llm_json_dir / f"{processing_hash}_marriage_{mode}{suffix}.json"

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

    def _heuristic_extract(self, document: OCRDocument) -> MarriageEvidence:
        text = document.combined_text
        applicant_name = self._first_match(
            [
                r"(?:NAMA\s+(?:PEMOHON|SUAMI|PENGANTIN\s+LELAKI)|HUSBAND\s+NAME|NAMA\s+SUAMI)\s*[:\-]\s*([^\n]+)",
                r"APPLICANT\s+NAME\s*[:\-]\s*([^\n]+)",
            ],
            text,
        )
        spouse_name = self._first_match(
            [
                r"(?:NAMA\s+(?:ISTERI|PASANGAN|PENGANTIN\s+PEREMPUAN)|WIFE\s+NAME|SPOUSE\s+NAME)\s*[:\-]\s*([^\n]+)",
            ],
            text,
        )
        applicant_ic = self._first_match(
            [
                r"(?:NO\.?\s*KP\s+SUAMI|NO\.?\s*KAD\s+PENGENALAN\s+SUAMI|APPLICANT\s+IC)\s*[:\-]\s*([0-9\- ]{8,20})",
                r"(?:NO\.?\s*KP\s+PEMOHON)\s*[:\-]\s*([0-9\- ]{8,20})",
            ],
            text,
        )
        spouse_ic = self._first_match(
            [
                r"(?:NO\.?\s*KP\s+ISTERI|NO\.?\s*KAD\s+PENGENALAN\s+ISTERI|SPOUSE\s+IC)\s*[:\-]\s*([0-9\- ]{8,20})",
            ],
            text,
        )
        registration_no = self._first_match(
            [r"(?:NOMBOR|NO\.?|NO)\s*DAFTAR\s*[:\-]\s*([^\n]+)"],
            text,
        )
        marriage_date = self._first_match(
            [r"(?:TARIKH\s+NIKAH|DATE\s+OF\s+MARRIAGE)\s*[:\-]\s*([^\n]+)"],
            text,
        )
        authority_match = re.search(
            r"(?:JABATAN\s+AGAMA[^\n]*|PEJABAT\s+AGAMA[^\n]*|ISSUING\s+AUTHORITY\s*[:\-]\s*[^\n]+)",
            text,
            flags=re.IGNORECASE,
        )
        issuing_authority = normalize_whitespace(authority_match.group(0)) if authority_match else None
        snippets = [
            line.strip()
            for line in text.splitlines()
            if any(keyword in line.upper() for keyword in ["NIKAH", "MARRIAGE", "DAFTAR"])
        ][:5]
        refs = self._page_refs(document, [applicant_name or "", spouse_name or "", registration_no or "NIKAH"])
        found_fields = [applicant_name, spouse_name, applicant_ic, spouse_ic, registration_no, marriage_date]
        confidence = round(sum(1 for value in found_fields if value) / 6, 2)
        script = guess_script(text)
        language = "arabic_script" if script == "arabic_script" else "english_malay"
        return MarriageEvidence(
            applicant_name_from_doc=applicant_name,
            applicant_ic_from_doc=applicant_ic,
            spouse_name_from_doc=spouse_name,
            spouse_ic_from_doc=spouse_ic,
            marriage_registration_no=registration_no,
            marriage_date=marriage_date,
            issuing_authority=issuing_authority,
            document_language=language,
            key_supporting_snippets=snippets,
            page_refs=refs,
            extraction_confidence=confidence,
            raw_payload={"_method": "heuristic"},
        )

    def extract(self, document: OCRDocument, applicant_context: dict[str, str]) -> MarriageEvidence:
        desired_mode, model_name = self._desired_mode(document)
        cache_path = self._cache_path(document.processing_hash, desired_mode, model_name)
        if cache_path.exists():
            return MarriageEvidence.model_validate(json.loads(cache_path.read_text(encoding="utf-8")))

        result = self._heuristic_extract(document)
        images = self._document_images(document)
        if desired_mode == "ollama_vision":
            try:
                response = self.llm_client.generate_vision(
                    extraction_prompt("marriage_certificate", document.combined_text, applicant_context, include_images=True),
                    image_paths=images,
                )
                payload = parse_model_response(response, MarriageExtractionSchema, overrides={'doc_type': 'marriage_certificate'})
                result = MarriageEvidence(
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
                    extraction_prompt("marriage_certificate", document.combined_text, applicant_context)
                )
                payload = parse_model_response(response, MarriageExtractionSchema, overrides={'doc_type': 'marriage_certificate'})
                result = MarriageEvidence(
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

