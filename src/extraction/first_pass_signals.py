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
from src.rules.validators import row_claim_is_married, row_has_oku_claim, row_has_postgraduate_claim
from src.settings import AppConfig


CACHE_VERSION = "v8"
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
FORCED_GUESS_PRESENT_THRESHOLD = 0.7
FORCED_GUESS_MANUAL_THRESHOLD = 0.45
DOCUMENT_GUESS_PRESENT_THRESHOLD = 0.6
TARGETED_PRESENT_THRESHOLD = 0.55
TARGETED_MANUAL_THRESHOLD = 0.35
NEGATIVE_TEXT_VALUES = {"", "0", "tiada", "tidak", "tidak berkenaan", "none", "n/a", "na", "null"}


class FirstPassEvidenceScanner:
    def __init__(self, settings: AppConfig, llm_client: OllamaClient | None = None) -> None:
        self.settings = settings
        self.llm_client = llm_client

    def _secondary_model_name(self) -> str | None:
        if not self.llm_client or not hasattr(self.llm_client, "secondary_vision_model_name"):
            return None
        return self.llm_client.secondary_vision_model_name()

    def _cache_path(self, processing_hash: str, mode: str, model_name: str | None = None) -> Path:
        suffix = f"_{OllamaClient.cache_slug(model_name)}" if model_name else ""
        return self.settings.paths.llm_json_dir / f"{processing_hash}_first_pass_{CACHE_VERSION}_{mode}{suffix}.json"

    @staticmethod
    def _document_images(document: OCRDocument) -> list[str]:
        return document.page_image_paths or list(document.metadata.get("page_image_paths", []))

    def _desired_mode(self, document: OCRDocument) -> tuple[str, str | None]:
        image_paths = self._document_images(document)
        if self.llm_client and self.llm_client.is_vision_enabled() and image_paths:
            model_names = [self.llm_client.vision_model_name()]
            if self._secondary_model_name():
                model_names.append(self._secondary_model_name())
            return "ollama_vision", "+".join(model_names)
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
            elif manual_count >= 1:
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
    def _all_not_present(result: FirstPassEvidenceSignals) -> bool:
        return all(getattr(result, key) == "not_present" for key in SIGNAL_KEYS)

    @staticmethod
    def _forced_guess_status(confidence: float) -> str:
        if confidence >= FORCED_GUESS_PRESENT_THRESHOLD:
            return "present"
        if confidence >= FORCED_GUESS_MANUAL_THRESHOLD:
            return "manual_check"
        return "not_present"

    @staticmethod
    def _meaningful_context_text(value: str | None) -> bool:
        normalized = str(value or "").strip().casefold()
        return bool(normalized) and normalized not in NEGATIVE_TEXT_VALUES

    @classmethod
    def _context_claims(cls, applicant_context: dict[str, str] | None) -> dict[str, bool]:
        context = applicant_context or {}
        return {
            "marriage": row_claim_is_married(context.get("marital_status")),
            "self_illness": cls._meaningful_context_text(context.get("personal_health_condition")) or cls._meaningful_context_text(context.get("personal_health_details")),
            "family_illness": any(
                [
                    cls._meaningful_context_text(context.get("spouse_health_condition")),
                    cls._meaningful_context_text(context.get("spouse_health_details")),
                    cls._meaningful_context_text(context.get("children_health_issue_score")),
                    cls._meaningful_context_text(context.get("parent_health_issue_score")),
                ]
            ),
            "spouse_location": row_claim_is_married(context.get("marital_status"))
            and any(
                [
                    cls._meaningful_context_text(context.get("spouse_employment_status")),
                    cls._meaningful_context_text(context.get("spouse_job_title")),
                    cls._meaningful_context_text(context.get("spouse_work_address")),
                    cls._meaningful_context_text(context.get("spouse_work_state")),
                ]
            ),
            "oku_self_or_family": any(
                [
                    row_has_oku_claim(context.get("applicant_oku_status")),
                    row_has_oku_claim(context.get("spouse_oku_status")),
                    cls._meaningful_context_text(context.get("children_disability_score")),
                    cls._meaningful_context_text(context.get("parent_disability_score")),
                ]
            ),
            "medex_or_other_exam": row_has_postgraduate_claim(context.get("postgraduate_status")),
        }

    @staticmethod
    def _page_label_payload(page_number: int, payload: FirstPassSignalsSchema) -> dict[str, object]:
        result = {
            "page": page_number,
            "best_fit_bucket": payload.best_fit_bucket,
            "best_fit_confidence": payload.best_fit_confidence,
            "subject_role": payload.subject_role,
            "subject_role_confidence": payload.subject_role_confidence,
        }
        for key in SIGNAL_KEYS:
            result[key] = getattr(payload, key)
        result["reasons"] = list(payload.reasons)
        return result

    @staticmethod
    def _page_roles_for_signal(signal: str) -> set[str]:
        if signal == "self_illness":
            return {"applicant", "unknown"}
        if signal == "family_illness":
            return {"spouse", "family", "unknown"}
        if signal == "spouse_location":
            return {"spouse", "unknown"}
        if signal == "medex_or_other_exam":
            return {"applicant", "unknown"}
        return {"applicant", "spouse", "family", "other_person", "unknown"}

    @staticmethod
    def _candidate_pages_for_signal(signal: str, chunk_payloads: list[dict[str, object]]) -> list[int]:
        candidates: list[int] = []
        allowed_roles = FirstPassEvidenceScanner._page_roles_for_signal(signal)
        for index, chunk in enumerate(chunk_payloads):
            best_fit_bucket = chunk.get("best_fit_bucket")
            best_fit_confidence = float(chunk.get("best_fit_confidence") or 0.0)
            signal_status = str(chunk.get(signal) or "not_present")
            subject_role = str(chunk.get("subject_role") or "unknown")
            if subject_role not in allowed_roles and signal not in {"marriage", "oku_self_or_family"}:
                continue
            if signal_status in {"present", "manual_check"} or (best_fit_bucket == signal and best_fit_confidence >= TARGETED_MANUAL_THRESHOLD):
                candidates.append(index)
        return candidates

    @staticmethod
    def _promote_targeted_signal(signal: str, page_payloads: list[dict[str, object]]) -> tuple[str, list[str]]:
        if not page_payloads:
            return "not_present", []
        present_count = sum(1 for payload in page_payloads if str(payload.get(signal)) == "present")
        manual_count = sum(1 for payload in page_payloads if str(payload.get(signal)) == "manual_check")
        best_fit_matches = [
            float(payload.get("best_fit_confidence") or 0.0)
            for payload in page_payloads
            if payload.get("best_fit_bucket") == signal
        ]
        reasons: list[str] = []
        if present_count >= 1:
            reasons.append(f"Claim-aware second pass found {signal.replace('_', ' ')} on at least one page.")
            return "present", reasons
        if len(best_fit_matches) >= 2 and sum(best_fit_matches) / len(best_fit_matches) >= TARGETED_PRESENT_THRESHOLD:
            reasons.append(f"Claim-aware second pass found repeated page labels for {signal.replace('_', ' ')}.")
            return "present", reasons
        if manual_count >= 1 or best_fit_matches:
            reasons.append(f"Claim-aware second pass found a plausible {signal.replace('_', ' ')} page but not a clear confirmation.")
            return "manual_check", reasons
        return "not_present", reasons

    @classmethod
    def _apply_chunk_guess_fallback(
        cls,
        chunk_result: FirstPassEvidenceSignals,
        payload: FirstPassSignalsSchema,
    ) -> FirstPassEvidenceSignals:
        if not cls._all_not_present(chunk_result):
            return chunk_result
        bucket = payload.best_fit_bucket
        status = cls._forced_guess_status(payload.best_fit_confidence)
        if not bucket or status == "not_present":
            return chunk_result
        promoted = chunk_result.model_dump(mode="json")
        promoted[bucket] = status
        promoted["reasons"] = list(
            dict.fromkeys(
                [
                    *chunk_result.reasons,
                    f"Forced best-fit page guess promoted {bucket.replace('_', ' ')} to {status}.",
                ]
            )
        )
        return FirstPassEvidenceSignals.model_validate(promoted)

    @classmethod
    def _apply_document_guess_fallback(
        cls,
        result: FirstPassEvidenceSignals,
        chunk_payloads: list[dict[str, object]],
    ) -> FirstPassEvidenceSignals:
        payload = result.model_dump(mode="json")
        guess_counts = {key: 0 for key in SIGNAL_KEYS}
        guess_confidence = {key: 0.0 for key in SIGNAL_KEYS}
        total_chunks = len(chunk_payloads)
        for chunk in chunk_payloads:
            bucket = chunk.get("best_fit_bucket")
            confidence = float(chunk.get("best_fit_confidence") or 0.0)
            if bucket not in SIGNAL_KEYS:
                continue
            guess_counts[bucket] += 1
            guess_confidence[bucket] += confidence
        if not total_chunks:
            return result
        required_count = max(2, (total_chunks + 1) // 2)
        for key in SIGNAL_KEYS:
            if payload.get(key) != "not_present":
                continue
            count = guess_counts[key]
            if count < required_count and not (total_chunks == 1 and count == 1):
                continue
            average_confidence = guess_confidence[key] / max(count, 1)
            if total_chunks > 1:
                promoted_status = "present" if average_confidence >= DOCUMENT_GUESS_PRESENT_THRESHOLD else "manual_check"
            else:
                promoted_status = cls._forced_guess_status(average_confidence)
            if promoted_status == "not_present":
                continue
            payload[key] = promoted_status
            payload["reasons"] = list(
                dict.fromkeys(
                    [
                        *payload.get("reasons", []),
                        (
                            f"Repeated best-fit page guesses promoted {key.replace('_', ' ')} to "
                            f"{promoted_status}."
                        ),
                    ]
                )
            )
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

    @staticmethod
    def _all_statuses_not_present(payload: FirstPassSignalsSchema) -> bool:
        return all(getattr(payload, key) == "not_present" for key in SIGNAL_KEYS)

    @staticmethod
    def _merge_page_payloads(primary: FirstPassSignalsSchema, secondary: FirstPassSignalsSchema | None = None) -> FirstPassSignalsSchema:
        if secondary is None:
            return primary
        payload = primary.model_dump(mode="json")
        secondary_payload = secondary.model_dump(mode="json")
        for key in SIGNAL_KEYS:
            current = payload.get(key, "not_present")
            candidate = secondary_payload.get(key, "not_present")
            if STATUS_PRIORITY[candidate] > STATUS_PRIORITY[current]:
                payload[key] = candidate
        primary_bucket_confidence = float(payload.get("best_fit_confidence") or 0.0)
        secondary_bucket_confidence = float(secondary_payload.get("best_fit_confidence") or 0.0)
        if secondary_bucket_confidence > primary_bucket_confidence:
            payload["best_fit_bucket"] = secondary_payload.get("best_fit_bucket")
            payload["best_fit_confidence"] = secondary_bucket_confidence
        primary_role_confidence = float(payload.get("subject_role_confidence") or 0.0)
        secondary_role_confidence = float(secondary_payload.get("subject_role_confidence") or 0.0)
        if payload.get("subject_role") == "unknown" and secondary_payload.get("subject_role") != "unknown":
            payload["subject_role"] = secondary_payload.get("subject_role")
            payload["subject_role_confidence"] = secondary_role_confidence
        elif secondary_role_confidence > primary_role_confidence:
            payload["subject_role"] = secondary_payload.get("subject_role")
            payload["subject_role_confidence"] = secondary_role_confidence
        payload["reasons"] = list(dict.fromkeys([*primary.reasons, *secondary.reasons]))
        return FirstPassSignalsSchema.model_validate(payload)

    def _scan_page_with_models(
        self,
        prompt: str,
        image_paths: list[str],
        *,
        run_secondary_on_weak_primary: bool = True,
    ) -> tuple[FirstPassSignalsSchema, list[str]]:
        if not (self.llm_client and self.llm_client.is_vision_enabled()):
            raise ValueError("Vision model is not available.")

        primary_model = self.llm_client.vision_model_name()
        secondary_model = self._secondary_model_name()
        try:
            primary_payload = parse_model_response(
                self.llm_client.generate_vision(prompt, image_paths=image_paths, model=primary_model),
                FirstPassSignalsSchema,
            )
            models_used = [primary_model]
        except Exception:  # noqa: BLE001
            if not secondary_model:
                raise
            secondary_payload = parse_model_response(
                self.llm_client.generate_vision(prompt, image_paths=image_paths, model=secondary_model),
                FirstPassSignalsSchema,
            )
            return secondary_payload, [secondary_model]

        should_try_secondary = (
            secondary_model
            and run_secondary_on_weak_primary
            and (
                self._all_statuses_not_present(primary_payload)
                or float(primary_payload.best_fit_confidence or 0.0) < FORCED_GUESS_MANUAL_THRESHOLD
            )
        )
        if not should_try_secondary:
            return primary_payload, models_used

        try:
            secondary_payload = parse_model_response(
                self.llm_client.generate_vision(prompt, image_paths=image_paths, model=secondary_model),
                FirstPassSignalsSchema,
            )
        except Exception:  # noqa: BLE001
            return primary_payload, models_used

        models_used.append(secondary_model)
        return self._merge_page_payloads(primary_payload, secondary_payload), models_used

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

    def _claim_recovery_scan(
        self,
        document: OCRDocument,
        applicant_context: dict[str, str] | None,
        images: list[str],
        chunk_payloads: list[dict[str, object]],
        current_result: FirstPassEvidenceSignals,
    ) -> tuple[FirstPassEvidenceSignals, dict[str, dict[str, object]]]:
        if not (self.llm_client and self.llm_client.is_vision_enabled() and images):
            return current_result, {}
        claims = self._context_claims(applicant_context)
        recovery_payload: dict[str, dict[str, object]] = {}
        updated_payload = current_result.model_dump(mode="json")

        for signal, claimed in claims.items():
            if not claimed or updated_payload.get(signal) == "present":
                continue
            candidate_indexes = self._candidate_pages_for_signal(signal, chunk_payloads)
            if not candidate_indexes:
                candidate_indexes = list(range(len(images)))
            page_payloads: list[dict[str, object]] = []
            for page_index in candidate_indexes:
                page_number = page_index + 1
                try:
                    payload, models_used = self._scan_page_with_models(
                        first_pass_signals_prompt(
                            self._page_text(document, page_index, page_index + 1),
                            applicant_context=applicant_context,
                            include_images=True,
                            page_range=self._page_range(document, page_index, page_index + 1),
                            focus_signal=signal,
                        ),
                        image_paths=[images[page_index]],
                    )
                    page_payload = self._page_label_payload(page_number, payload)
                    page_payload["models_used"] = models_used
                    page_payloads.append(page_payload)
                except Exception:  # noqa: BLE001
                    continue
            recovered_status, reasons = self._promote_targeted_signal(signal, page_payloads)
            if STATUS_PRIORITY[recovered_status] > STATUS_PRIORITY.get(updated_payload.get(signal, "not_present"), 0):
                updated_payload[signal] = recovered_status
            if reasons:
                updated_payload["reasons"] = list(dict.fromkeys([*updated_payload.get("reasons", []), *reasons]))
            recovery_payload[signal] = {
                "claimed": claimed,
                "candidate_pages": [index + 1 for index in candidate_indexes],
                "page_labels": page_payloads,
                "final_status": recovered_status,
                "reasons": reasons,
            }

        return FirstPassEvidenceSignals.model_validate(updated_payload), recovery_payload

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
            page_labels: list[dict[str, object]] = []
            for start in range(0, len(images), chunk_size):
                stop = start + chunk_size
                chunk_images = images[start:stop]
                if not chunk_images:
                    continue
                try:
                    payload, models_used = self._scan_page_with_models(
                        first_pass_signals_prompt(
                            self._page_text(document, start, stop),
                            applicant_context=applicant_context,
                            include_images=True,
                            page_range=self._page_range(document, start, stop),
                        ),
                        image_paths=chunk_images,
                    )
                    chunk_result = FirstPassEvidenceSignals(**payload.model_dump())
                    chunk_result = self._apply_chunk_guess_fallback(chunk_result, payload)
                    chunk_results.append(chunk_result)
                    page_label = self._page_label_payload(start + 1, payload)
                    page_label["models_used"] = models_used
                    page_labels.append(page_label)
                    chunk_payloads.append(
                        {
                            "pages": self._page_range(document, start, stop),
                            "models_used": models_used,
                            **payload.model_dump(mode="json"),
                        }
                    )
                except Exception:  # noqa: BLE001
                    continue
            if chunk_payloads:
                llm_result = self._aggregate_chunk_results(chunk_results)
                llm_result = self._apply_document_guess_fallback(llm_result, chunk_payloads)
                overview_result = self._overview_scan(chunk_payloads, applicant_context=applicant_context)
                llm_result = self._merge_signals(llm_result, overview_result)
                result = self._merge_signals(heuristic, llm_result)
                result = self._post_process_result(result, document, chunk_payloads)
                result, recovery_payload = self._claim_recovery_scan(document, applicant_context, images, chunk_payloads, result)
                result.raw_payload = {
                    "_method": desired_mode,
                    "_model": self.llm_client.vision_model_name(),
                    "_secondary_model": self._secondary_model_name(),
                    "_cache_models": model_name,
                    "_cache_version": CACHE_VERSION,
                    "chunks": chunk_payloads,
                    "page_labels": page_labels,
                    "claims": self._context_claims(applicant_context),
                    "claim_recovery": recovery_payload,
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
