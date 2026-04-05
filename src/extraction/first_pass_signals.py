"""Broad first-pass evidence scan across all pages of an applicant PDF."""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.extraction.evidence_models import FirstPassEvidenceSignals, OCRDocument
from src.llm.ollama_client import OllamaClient
from src.llm.parser import parse_model_response
from src.llm.prompts import first_pass_signals_prompt
from src.llm.schemas import FirstPassSignalsSchema
from src.settings import AppConfig


CACHE_VERSION = "v5"
STATUS_PRIORITY = {"not_present": 0, "manual_check": 1, "present": 2}
SIGNAL_KEYS = [
    "marriage",
    "self_illness",
    "family_illness",
    "spouse_location",
    "oku_self_or_family",
    "medex_or_other_exam",
]
MEDICAL_PATTERNS = [
    r"HOSPITAL",
    r"KLINIK",
    r"DIAGNOSIS",
    r"PATIENT",
    r"FOLLOW\s*UP",
    r"MEDICATION",
    r"BLOOD\s+INVESTIGATION",
    r"IMPRESSION",
    r"RAWATAN",
    r"THERAPY",
    r"AUTISM",
    r"LYMPHOMA",
    r"HYPERTENSION",
    r"DIABETES|DM\b",
]
FAMILY_PATTERNS = [
    r"SUAMI",
    r"ISTERI",
    r"PASANGAN",
    r"SPOUSE",
    r"ANAK",
    r"CHILD",
    r"BAPA",
    r"FATHER",
    r"IBU",
    r"MOTHER",
    r"KELUARGA",
    r"FAMILY",
    r"BIRTH\s+CERTIFICATE",
    r"SIJIL\s+KELAHIRAN",
    r"KANAK-KANAK",
]
HEURISTIC_PATTERNS: dict[str, list[str]] = {
    "marriage": [
        r"SURAT\s+PERAKUAN\s+NIKAH",
        r"SIJIL\s+NIKAH",
        r"MARRIAGE\s+CERTIFICATE",
        r"TARIKH\s+NIKAH",
        r"NOMBOR\s+DAFTAR",
    ],
    "spouse_location": [
        r"PENEMPATAN",
        r"PLACEMENT",
        r"LAPOR\s+DIRI",
        r"PEJABAT\s+KESIHATAN\s+KAWASAN",
        r"TEMPAT\s+TUGAS",
        r"BERTUGAS",
        r"KOTA\s+KINABALU",
        r"DAERAH",
        r"PERTUKARAN",
        r"PEGAWAI\s+PERUBATAN",
        r"JAWATAN",
        r"PEGAWAI\s+KESIHATAN",
    ],
    "oku_self_or_family": [
        r"\bOKU\b",
        r"ORANG\s+KURANG\s+UPAYA",
        r"JABATAN\s+KEBAJIKAN\s+MASYARAKAT",
        r"KAD\s+OKU",
        r"DISABILITY",
    ],
    "medex_or_other_exam": [
        r"\bMEDEX\b",
        r"\bGCFM\b",
        r"MEDICAL\s+SPECIALIST\s+PRE-ENTRANCE",
        r"PRE-ENTRANCE\s+EXAM",
        r"EXAM\s+RESULT",
        r"KEPUTUSAN\s+PEPERIKSAAN",
        r"PEPERIKSAAN\s+KEMASUKAN",
        r"PEPERIKSAAN\s+MASUK",
        r"POSTGRADUATE",
        r"SLIP\s+KEPUTUSAN",
        r"SIJIL\s+KEPUTUSAN",
    ],
}
EXAM_POSITIVE_PATTERNS = HEURISTIC_PATTERNS["medex_or_other_exam"]
EXAM_NEGATIVE_PATTERNS = [
    r"PHYSICAL\s+EXAMINATION",
    r"MEDICAL\s+EXAMINATION\s+RECORD",
    r"MEDICAL\s+EXAMINATION\s+REPORT",
    r"MEDICAL\s+RECORD",
    r"FOLLOW\s*UP",
    r"THERAPY",
    r"HOSPITAL",
    r"KLINIK",
    r"TREATMENT",
    r"DISCHARGE",
]


class FirstPassEvidenceScanner:
    def __init__(self, settings: AppConfig, llm_client: OllamaClient | None = None) -> None:
        self.settings = settings
        self.llm_client = llm_client

    def _cache_path(self, processing_hash: str, mode: str, model_name: str | None = None) -> Path:
        suffix = f"_{OllamaClient.cache_slug(model_name)}" if model_name else ""
        return self.settings.paths.llm_json_dir / f"{processing_hash}_first_pass_{CACHE_VERSION}_{mode}{suffix}.json"

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

    @staticmethod
    def _page_text(document: OCRDocument, start: int, stop: int) -> str:
        if not document.pages:
            return document.combined_text
        parts = []
        for page in document.pages[start:stop]:
            parts.append(f"[Page {page.page_number}]\n{page.extracted_text}")
        return "\n\n".join(parts)

    @staticmethod
    def _page_range(document: OCRDocument, start: int, stop: int) -> str | None:
        page_numbers = [page.page_number for page in document.pages[start:stop]]
        if not page_numbers:
            return None
        if len(page_numbers) == 1:
            return str(page_numbers[0])
        return f"{page_numbers[0]}-{page_numbers[-1]}"

    @staticmethod
    def _merge_signals(base: FirstPassEvidenceSignals, incoming: FirstPassEvidenceSignals) -> FirstPassEvidenceSignals:
        payload = base.model_dump(mode="json")
        for key in SIGNAL_KEYS:
            current = payload.get(key, "not_present")
            candidate = getattr(incoming, key)
            if STATUS_PRIORITY[candidate] > STATUS_PRIORITY[current]:
                payload[key] = candidate
        payload["reasons"] = list(dict.fromkeys([*base.reasons, *incoming.reasons]))
        payload["raw_payload"] = dict(base.raw_payload)
        return FirstPassEvidenceSignals.model_validate(payload)

    @staticmethod
    def _aggregate_chunk_results(chunk_results: list[FirstPassEvidenceSignals]) -> FirstPassEvidenceSignals:
        payload = FirstPassEvidenceSignals().model_dump(mode="json")
        reasons: list[str] = []
        for key in SIGNAL_KEYS:
            present_count = sum(1 for result in chunk_results if getattr(result, key) == "present")
            manual_count = sum(1 for result in chunk_results if getattr(result, key) == "manual_check")
            if present_count >= 1:
                payload[key] = "present"
            elif manual_count >= 2:
                payload[key] = "manual_check"
            else:
                payload[key] = "not_present"
        for result in chunk_results:
            reasons.extend(result.reasons)
        payload["reasons"] = list(dict.fromkeys(reasons))
        return FirstPassEvidenceSignals.model_validate(payload)

    @staticmethod
    def _present_only(result: FirstPassEvidenceSignals) -> FirstPassEvidenceSignals:
        payload = result.model_dump(mode="json")
        for key in SIGNAL_KEYS:
            if payload.get(key) != "present":
                payload[key] = "not_present"
        return FirstPassEvidenceSignals.model_validate(payload)

    @staticmethod
    def _empty_result() -> FirstPassEvidenceSignals:
        return FirstPassEvidenceSignals()

    @staticmethod
    def _matches(text: str, patterns: list[str]) -> bool:
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)

    @staticmethod
    def _normalized_digits(value: str | None) -> str:
        return re.sub(r"\D+", "", str(value or ""))

    @staticmethod
    def _contains_identifier(text: str, value: str | None) -> bool:
        digits = FirstPassEvidenceScanner._normalized_digits(value)
        text_digits = FirstPassEvidenceScanner._normalized_digits(text)
        return bool(digits and digits in text_digits)

    @staticmethod
    def _contains_name(text: str, value: str | None) -> bool:
        normalized = str(value or "").strip().casefold()
        if not normalized or len(normalized) < 5:
            return False
        return normalized in text.casefold()

    @staticmethod
    def _chunk_reason_text(chunk_payloads: list[dict[str, object]], signal: str) -> str:
        pieces: list[str] = []
        for chunk in chunk_payloads:
            if chunk.get(signal) == "not_present":
                continue
            reasons = chunk.get("reasons", [])
            if isinstance(reasons, list):
                pieces.extend(str(reason) for reason in reasons)
        return " ".join(pieces)

    def _post_process_result(
        self,
        result: FirstPassEvidenceSignals,
        document: OCRDocument,
        chunk_payloads: list[dict[str, object]],
    ) -> FirstPassEvidenceSignals:
        payload = result.model_dump(mode="json")
        exam_text = f"{document.combined_text}\n{self._chunk_reason_text(chunk_payloads, 'medex_or_other_exam')}"
        has_positive_exam_signal = self._matches(exam_text, EXAM_POSITIVE_PATTERNS)
        has_negative_exam_signal = self._matches(exam_text, EXAM_NEGATIVE_PATTERNS)
        if payload.get("medex_or_other_exam") == "present" and has_negative_exam_signal and not has_positive_exam_signal:
            payload["medex_or_other_exam"] = "not_present"
            payload["reasons"] = list(dict.fromkeys([*result.reasons, "Routine medical examination pages were excluded from MedEX or other exam."]))
        return FirstPassEvidenceSignals.model_validate(payload)

    def _heuristic_scan(self, document: OCRDocument, applicant_context: dict[str, str] | None = None) -> FirstPassEvidenceSignals:
        text = document.combined_text or ""
        context = applicant_context or {}
        medical = self._matches(text, MEDICAL_PATTERNS)
        family_terms = self._matches(text, FAMILY_PATTERNS)
        applicant_match = self._contains_identifier(text, context.get("applicant_id")) or self._contains_name(text, context.get("applicant_name"))
        spouse_match = self._contains_identifier(text, context.get("spouse_id")) or self._contains_name(text, context.get("spouse_name"))
        statuses = {
            "marriage": "present" if self._matches(text, HEURISTIC_PATTERNS["marriage"]) else "not_present",
            "self_illness": "present" if medical and applicant_match else "not_present",
            "family_illness": "present" if medical and (spouse_match or family_terms) else "not_present",
            "spouse_location": "present" if self._matches(text, HEURISTIC_PATTERNS["spouse_location"]) and (spouse_match or family_terms or self._matches(text, HEURISTIC_PATTERNS["marriage"])) else "not_present",
            "oku_self_or_family": "present" if self._matches(text, HEURISTIC_PATTERNS["oku_self_or_family"]) else "not_present",
            "medex_or_other_exam": "present" if self._matches(text, HEURISTIC_PATTERNS["medex_or_other_exam"]) else "not_present",
        }
        reasons = [f"Heuristic matched {key.replace('_', ' ')} evidence." for key, value in statuses.items() if value == "present"]
        return FirstPassEvidenceSignals(**statuses, reasons=reasons, raw_payload={"_method": "heuristic", "_cache_version": CACHE_VERSION})

    def _overview_scan(self, chunk_payloads: list[dict[str, object]], applicant_context: dict[str, str] | None = None) -> FirstPassEvidenceSignals:
        if not (self.llm_client and self.llm_client.is_enabled() and chunk_payloads):
            return self._empty_result()
        overview_text = "\n".join(
            f"Pages {chunk.get('pages')}: {json.dumps(chunk, ensure_ascii=True)}" for chunk in chunk_payloads
        )
        try:
            response = self.llm_client.generate(first_pass_signals_prompt(overview_text, applicant_context=applicant_context))
            payload = parse_model_response(response, FirstPassSignalsSchema)
            result = FirstPassEvidenceSignals(**payload.model_dump())
            result.raw_payload = {"_method": "ollama_text_overview", "_cache_version": CACHE_VERSION, **payload.model_dump(mode="json")}
            return self._present_only(result)
        except Exception:  # noqa: BLE001
            return self._empty_result()

    def scan(self, document: OCRDocument, applicant_context: dict[str, str] | None = None) -> FirstPassEvidenceSignals:
        desired_mode, model_name = self._desired_mode(document)
        cache_path = self._cache_path(document.processing_hash, desired_mode, model_name)
        if cache_path.exists():
            return FirstPassEvidenceSignals.model_validate(json.loads(cache_path.read_text(encoding="utf-8")))

        heuristic = self._heuristic_scan(document, applicant_context)
        result = heuristic
        images = self._document_images(document)

        if desired_mode == "ollama_vision":
            chunk_size = 1
            chunk_results: list[FirstPassEvidenceSignals] = []
            chunk_payloads: list[dict[str, object]] = []
            for start in range(0, len(images), chunk_size):
                stop = start + chunk_size
                chunk_images = images[start:stop]
                if not chunk_images:
                    continue
                try:
                    response = self.llm_client.generate_vision(
                        first_pass_signals_prompt(
                            self._page_text(document, start, stop),
                            applicant_context=applicant_context,
                            include_images=True,
                            page_range=self._page_range(document, start, stop),
                        ),
                        image_paths=chunk_images,
                    )
                    payload = parse_model_response(response, FirstPassSignalsSchema)
                    chunk_result = FirstPassEvidenceSignals(**payload.model_dump())
                    chunk_results.append(chunk_result)
                    chunk_payloads.append(
                        {
                            "pages": self._page_range(document, start, stop),
                            **payload.model_dump(mode="json"),
                        }
                    )
                except Exception:  # noqa: BLE001
                    continue
            if chunk_payloads:
                llm_result = self._aggregate_chunk_results(chunk_results)
                overview_result = self._overview_scan(chunk_payloads, applicant_context=applicant_context)
                llm_result = self._merge_signals(llm_result, overview_result)
                result = self._merge_signals(heuristic, llm_result)
                result = self._post_process_result(result, document, chunk_payloads)
                result.raw_payload = {
                    "_method": desired_mode,
                    "_model": model_name,
                    "_cache_version": CACHE_VERSION,
                    "chunks": chunk_payloads,
                    "overview": overview_result.raw_payload,
                }
        elif desired_mode == "ollama_text":
            try:
                response = self.llm_client.generate(first_pass_signals_prompt(document.combined_text, applicant_context=applicant_context))
                payload = parse_model_response(response, FirstPassSignalsSchema)
                llm_result = FirstPassEvidenceSignals(**payload.model_dump())
                result = self._merge_signals(heuristic, llm_result)
                result.raw_payload = {
                    "_method": desired_mode,
                    "_model": model_name,
                    "_cache_version": CACHE_VERSION,
                    **payload.model_dump(mode="json"),
                }
            except Exception:  # noqa: BLE001
                pass

        if desired_mode == "heuristic" or result.raw_payload.get("_method") == desired_mode:
            cache_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return result
