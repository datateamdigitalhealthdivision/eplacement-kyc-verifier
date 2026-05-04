"""Broad first-pass evidence scan across all pages of an applicant PDF."""

from __future__ import annotations

import json
import re
from pathlib import Path

from src.extraction.applicant_claims import ApplicantClaims, extract_applicant_claims
from src.extraction.evidence_models import FirstPassEvidenceSignals, OCRDocument, OCRPage
from src.llm.ollama_client import OllamaClient
from src.llm.parser import parse_model_response
from src.llm.prompts import first_pass_signals_prompt
from src.llm.schemas import FirstPassSignalsSchema
from src.rules.validators import row_claim_is_married, row_has_oku_claim, row_has_postgraduate_claim
from src.settings import AppConfig


CACHE_VERSION = "v12"
STATUS_PRIORITY = {"not_present": 0, "manual_check": 1, "present": 2}
CLAIM_GUIDED_MODES = {"claim_guided_verifier", "claim_guided_verifier_v5"}
NO_FORCED_GUESS_MODES = {"claim_guided_verifier_v5"}
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
CLAIM_GUIDED_INITIAL_PAGE_LIMIT = 2
V5_SHORTLIST_FALLBACK_LIMIT = 2
NEGATIVE_TEXT_VALUES = {"", "0", "tiada", "tidak", "tidak berkenaan", "none", "n/a", "na", "null"}
SIGNAL_CONFIDENCE_KEYS = {signal: f"{signal}_confidence" for signal in SIGNAL_KEYS}


class FirstPassEvidenceScanner:
    def __init__(self, settings: AppConfig, llm_client: OllamaClient | None = None) -> None:
        self.settings = settings
        self.llm_client = llm_client

    def _secondary_model_name(self) -> str | None:
        if not self.llm_client or not hasattr(self.llm_client, "secondary_vision_model_name"):
            return None
        return self.llm_client.secondary_vision_model_name()

    def _cache_path(
        self,
        processing_hash: str,
        mode: str,
        model_name: str | None = None,
        claim_key: str | None = None,
    ) -> Path:
        suffix = f"_{OllamaClient.cache_slug(model_name)}" if model_name else ""
        claim_suffix = f"_{claim_key}" if claim_key else ""
        return self.settings.paths.llm_json_dir / f"{processing_hash}_first_pass_{CACHE_VERSION}_{mode}{claim_suffix}{suffix}.json"

    @staticmethod
    def _is_claim_guided_mode(verifier_mode: str) -> bool:
        return verifier_mode in CLAIM_GUIDED_MODES

    @staticmethod
    def _is_v5_mode(verifier_mode: str) -> bool:
        return verifier_mode == "claim_guided_verifier_v5"

    @staticmethod
    def _active_signals(claims: ApplicantClaims | None, verifier_mode: str) -> list[str]:
        if verifier_mode in CLAIM_GUIDED_MODES:
            return claims.active_signals() if claims else []
        return list(SIGNAL_KEYS)

    @staticmethod
    def _status_for_unclaimed_signal(signal: str, active_signals: list[str], payload: FirstPassSignalsSchema) -> str:
        if signal in active_signals:
            return getattr(payload, signal)
        return "not_present"

    @staticmethod
    def _confidence_for_signal(signal: str, active_signals: list[str], payload: FirstPassSignalsSchema) -> float:
        confidence_key = SIGNAL_CONFIDENCE_KEYS[signal]
        if signal not in active_signals:
            return 0.0
        confidence = float(getattr(payload, confidence_key, 0.0) or 0.0)
        if confidence <= 0 and getattr(payload, signal) != "not_present" and payload.best_fit_bucket == signal:
            return float(payload.best_fit_confidence or 0.0)
        return confidence

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
    def _aggregate_chunk_results(chunk_results: list[FirstPassEvidenceSignals], active_signals: list[str]) -> FirstPassEvidenceSignals:
        payload = FirstPassEvidenceSignals().model_dump(mode="json")
        reasons: list[str] = []
        for key in SIGNAL_KEYS:
            if key not in active_signals:
                payload[key] = "not_present"
                continue
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
    def _page_label_payload(page: OCRPage, payload: FirstPassSignalsSchema, active_signals: list[str]) -> dict[str, object]:
        result = {
            "page": page.page_number,
            "ocr_text": page.ocr_text or page.extracted_text,
            "ocr_confidence": float(page.ocr_confidence or page.confidence or 0.0),
            "script_guess": page.script_guess or page.language_guess or "unknown",
            "image_path": page.image_path or "",
            "candidate_signals": list(page.candidate_signals),
            "matching_keywords": list(page.matching_keywords),
            "name_or_ic_match": bool(page.name_or_ic_match),
            "best_fit_bucket": payload.best_fit_bucket,
            "best_fit_confidence": payload.best_fit_confidence,
            "subject_role": payload.subject_role,
            "subject_role_confidence": payload.subject_role_confidence,
        }
        for key in SIGNAL_KEYS:
            result[key] = FirstPassEvidenceScanner._status_for_unclaimed_signal(key, active_signals, payload)
            result[SIGNAL_CONFIDENCE_KEYS[key]] = FirstPassEvidenceScanner._confidence_for_signal(key, active_signals, payload)
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
    def _page_name_or_ic_match(page: OCRPage, applicant_context: dict[str, str] | None, signal: str) -> bool:
        text = (page.ocr_text or page.extracted_text or "").casefold()
        if not text:
            return bool(page.name_or_ic_match)
        context = applicant_context or {}
        if signal in {"marriage", "self_illness", "medex_or_other_exam", "oku_self_or_family"}:
            if FirstPassEvidenceScanner._contains_identifier(text, context.get("applicant_id")):
                return True
            if FirstPassEvidenceScanner._contains_name(text, context.get("applicant_name")):
                return True
        if signal in {"marriage", "family_illness", "spouse_location", "oku_self_or_family"}:
            if FirstPassEvidenceScanner._contains_identifier(text, context.get("spouse_id")):
                return True
            if FirstPassEvidenceScanner._contains_name(text, context.get("spouse_name")):
                return True
        return bool(page.name_or_ic_match)

    @staticmethod
    def _family_context_match(page: OCRPage, applicant_context: dict[str, str] | None) -> bool:
        text = (page.ocr_text or page.extracted_text or "").casefold()
        if not text:
            return False
        return FirstPassEvidenceScanner._matches(text, FAMILY_PATTERNS)

    def _shortlist_pages_for_signal_v5(
        self,
        signal: str,
        document: OCRDocument,
        applicant_context: dict[str, str] | None,
    ) -> list[int]:
        ranked: list[tuple[int, int]] = []
        for index, page in enumerate(document.pages):
            score = 0
            if signal in page.candidate_signals:
                score += 4
            if self._page_name_or_ic_match(page, applicant_context, signal):
                score += 3
            if signal == "family_illness" and self._family_context_match(page, applicant_context):
                score += 2
            if signal == "marriage" and page.script_guess == "arabic_script_or_jawi":
                score += 2
            if signal == "marriage" and page.low_confidence and page.image_path:
                score += 1
            if signal == "spouse_location" and self._matches(page.ocr_text or page.extracted_text, HEURISTIC_PATTERNS["spouse_location"]):
                score += 2
            if signal == "oku_self_or_family" and self._matches(page.ocr_text or page.extracted_text, HEURISTIC_PATTERNS["oku_self_or_family"]):
                score += 2
            if signal == "medex_or_other_exam" and self._matches(page.ocr_text or page.extracted_text, HEURISTIC_PATTERNS["medex_or_other_exam"]):
                score += 2
            if signal in {"self_illness", "family_illness"} and self._matches(page.ocr_text or page.extracted_text, MEDICAL_PATTERNS):
                score += 2
            if float(page.ocr_confidence or page.confidence or 0.0) >= 0.8:
                score += 1
            if score > 0:
                ranked.append((index, score))
        ranked.sort(key=lambda item: (-item[1], item[0]))
        shortlisted = [index for index, _ in ranked[: self.settings.ocr.shortlist_max_pages_per_signal]]
        if shortlisted:
            return shortlisted
        return list(range(min(len(document.pages), V5_SHORTLIST_FALLBACK_LIMIT)))

    def _claim_shortlists_v5(
        self,
        document: OCRDocument,
        applicant_context: dict[str, str] | None,
        active_signals: list[str],
    ) -> dict[str, list[int]]:
        return {
            signal: self._shortlist_pages_for_signal_v5(signal, document, applicant_context)
            for signal in active_signals
        }

    @staticmethod
    def _union_shortlisted_pages(shortlists: dict[str, list[int]]) -> list[int]:
        page_scores: dict[int, int] = {}
        for pages in shortlists.values():
            for rank, page_index in enumerate(pages):
                page_scores[page_index] = page_scores.get(page_index, 0) + max(1, 5 - rank)
        return [page for page, _ in sorted(page_scores.items(), key=lambda item: (-item[1], item[0]))]

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
        active_signals: list[str],
    ) -> FirstPassEvidenceSignals:
        if not cls._all_not_present(chunk_result):
            return chunk_result
        bucket = payload.best_fit_bucket
        status = cls._forced_guess_status(payload.best_fit_confidence)
        if not bucket or status == "not_present" or bucket not in active_signals:
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
        active_signals: list[str],
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
            if key not in active_signals:
                continue
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

    def _heuristic_scan(
        self,
        document: OCRDocument,
        applicant_context: dict[str, str] | None = None,
        active_signals: list[str] | None = None,
    ) -> FirstPassEvidenceSignals:
        text = document.combined_text or ""
        context = applicant_context or {}
        active = set(active_signals or SIGNAL_KEYS)
        medical = self._matches(text, MEDICAL_PATTERNS)
        family_terms = self._matches(text, FAMILY_PATTERNS)
        applicant_match = self._contains_identifier(text, context.get("applicant_id")) or self._contains_name(text, context.get("applicant_name"))
        spouse_match = self._contains_identifier(text, context.get("spouse_id")) or self._contains_name(text, context.get("spouse_name"))
        statuses = {
            "marriage": "present" if "marriage" in active and self._matches(text, HEURISTIC_PATTERNS["marriage"]) else "not_present",
            "self_illness": "present" if "self_illness" in active and medical and applicant_match else "not_present",
            "family_illness": "present" if "family_illness" in active and medical and (spouse_match or family_terms) else "not_present",
            "spouse_location": "present" if "spouse_location" in active and self._matches(text, HEURISTIC_PATTERNS["spouse_location"]) and (spouse_match or family_terms or self._matches(text, HEURISTIC_PATTERNS["marriage"])) else "not_present",
            "oku_self_or_family": "present" if "oku_self_or_family" in active and self._matches(text, HEURISTIC_PATTERNS["oku_self_or_family"]) else "not_present",
            "medex_or_other_exam": "present" if "medex_or_other_exam" in active and self._matches(text, HEURISTIC_PATTERNS["medex_or_other_exam"]) else "not_present",
        }
        reasons = [f"Heuristic matched {key.replace('_', ' ')} evidence." for key, value in statuses.items() if value == "present"]
        return FirstPassEvidenceSignals(**statuses, reasons=reasons, raw_payload={"_method": "heuristic", "_cache_version": CACHE_VERSION})

    def _overview_scan(
        self,
        chunk_payloads: list[dict[str, object]],
        applicant_context: dict[str, str] | None = None,
        *,
        verifier_mode: str,
        active_signals: list[str],
    ) -> FirstPassEvidenceSignals:
        if not (self.llm_client and self.llm_client.is_enabled() and chunk_payloads):
            return self._empty_result()
        if verifier_mode in CLAIM_GUIDED_MODES:
            return self._empty_result()
        overview_text = "\n".join(
            f"Pages {chunk.get('pages')}: {json.dumps(chunk, ensure_ascii=True)}" for chunk in chunk_payloads
        )
        try:
            response = self.llm_client.generate(
                first_pass_signals_prompt(
                    overview_text,
                    applicant_context=applicant_context,
                    verifier_mode=verifier_mode,
                    claimed_signals=active_signals,
                )
            )
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
        *,
        claims: ApplicantClaims | None,
        verifier_mode: str,
        active_signals: list[str],
        shortlists: dict[str, list[int]] | None = None,
        scanned_indexes: set[int] | None = None,
    ) -> tuple[FirstPassEvidenceSignals, dict[str, dict[str, object]]]:
        if not (self.llm_client and self.llm_client.is_vision_enabled() and images):
            return current_result, {}
        claims_map = claims.signal_map() if claims else self._context_claims(applicant_context)
        recovery_payload: dict[str, dict[str, object]] = {}
        updated_payload = current_result.model_dump(mode="json")

        for signal, claimed in claims_map.items():
            if signal not in active_signals:
                continue
            if not claimed or updated_payload.get(signal) == "present":
                continue
            candidate_indexes = list((shortlists or {}).get(signal, []))
            if not candidate_indexes:
                candidate_indexes = self._candidate_pages_for_signal(signal, chunk_payloads)
            if not candidate_indexes:
                candidate_indexes = list(range(len(images)))
            if self._is_v5_mode(verifier_mode):
                extras = [
                    index
                    for index in range(len(images))
                    if index not in candidate_indexes and index not in (scanned_indexes or set())
                ]
                candidate_indexes.extend(extras[:V5_SHORTLIST_FALLBACK_LIMIT])
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
                            verifier_mode=verifier_mode,
                            claimed_signals=active_signals,
                        ),
                        image_paths=[images[page_index]],
                        run_secondary_on_weak_primary=self._is_v5_mode(verifier_mode),
                    )
                    page_payload = self._page_label_payload(document.pages[page_index], payload, active_signals)
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

    def _signal_page_payloads(
        self,
        signal: str,
        page_labels: list[dict[str, object]],
        recovery_payload: dict[str, dict[str, object]],
    ) -> list[dict[str, object]]:
        payloads: list[dict[str, object]] = []
        for payload in page_labels:
            if payload.get(signal) != "not_present" or payload.get("best_fit_bucket") == signal:
                payloads.append(payload)
        for payload in recovery_payload.get(signal, {}).get("page_labels", []):
            if payload.get(signal) != "not_present" or payload.get("best_fit_bucket") == signal:
                payloads.append(payload)
        return payloads

    def _signal_supporting_pages(
        self,
        signal: str,
        page_labels: list[dict[str, object]],
        recovery_payload: dict[str, dict[str, object]],
    ) -> list[int]:
        pages: list[int] = []
        for payload in self._signal_page_payloads(signal, page_labels, recovery_payload):
            page = payload.get("page")
            if isinstance(page, int) and page not in pages:
                pages.append(page)
        return pages

    def _signal_confidence(
        self,
        signal: str,
        status: str,
        *,
        page_labels: list[dict[str, object]],
        recovery_payload: dict[str, dict[str, object]],
        fallback_payload: dict[str, object] | None = None,
    ) -> float:
        confidences: list[float] = []
        for payload in self._signal_page_payloads(signal, page_labels, recovery_payload):
            confidence = float(payload.get(SIGNAL_CONFIDENCE_KEYS[signal]) or 0.0)
            if confidence <= 0 and payload.get("best_fit_bucket") == signal and payload.get(signal) != "not_present":
                confidence = float(payload.get("best_fit_confidence") or 0.0)
            if confidence > 0:
                confidences.append(confidence)
        if fallback_payload:
            fallback_confidence = float(fallback_payload.get(SIGNAL_CONFIDENCE_KEYS[signal]) or 0.0)
            if fallback_confidence <= 0 and fallback_payload.get("best_fit_bucket") == signal and status != "not_present":
                fallback_confidence = float(fallback_payload.get("best_fit_confidence") or 0.0)
            if fallback_confidence > 0:
                confidences.append(fallback_confidence)
        if status == "present" and not confidences:
            return 1.0
        if status == "manual_check" and not confidences:
            return 0.5
        return max(confidences, default=0.0)

    def _best_support_payload(
        self,
        signal: str,
        page_labels: list[dict[str, object]],
        recovery_payload: dict[str, dict[str, object]],
    ) -> dict[str, object]:
        payloads = self._signal_page_payloads(signal, page_labels, recovery_payload)
        if not payloads:
            return {}
        return max(
            payloads,
            key=lambda payload: (
                STATUS_PRIORITY.get(str(payload.get(signal) or "not_present"), 0),
                float(payload.get(SIGNAL_CONFIDENCE_KEYS[signal]) or 0.0),
                float(payload.get("best_fit_confidence") or 0.0),
            ),
        )

    def _signal_document_type(self, signal: str, best_payload: dict[str, object]) -> str:
        if not best_payload:
            return ""
        if signal == "marriage":
            return "marriage_certificate"
        if signal in {"self_illness", "family_illness"}:
            return "medical_document"
        if signal == "spouse_location":
            return "spouse_location_document"
        if signal == "oku_self_or_family":
            return "oku_document"
        if signal == "medex_or_other_exam":
            return "exam_document"
        return "supporting_document"

    def _signal_person_role(self, signal: str, best_payload: dict[str, object]) -> str:
        if not best_payload:
            return "unknown"
        subject_role = str(best_payload.get("subject_role") or "unknown")
        if signal == "self_illness" and subject_role == "family":
            return "family"
        return subject_role

    def _signal_person_named(self, signal: str, best_payload: dict[str, object], applicant_context: dict[str, str] | None) -> str:
        if not best_payload:
            return ""
        role = self._signal_person_role(signal, best_payload)
        context = applicant_context or {}
        if role == "applicant":
            return str(context.get("applicant_name") or context.get("applicant_id") or "")
        if role == "spouse":
            return str(context.get("spouse_name") or context.get("spouse_id") or "")
        if role == "family":
            return "family_member"
        if role == "other_person":
            return "other_person"
        return ""

    @staticmethod
    def _relationship_to_applicant(role: str) -> str:
        return {
            "applicant": "self",
            "spouse": "spouse",
            "family": "family",
            "other_person": "other_person",
            "unknown": "unknown",
        }.get(role, "unknown")

    def _proof_strength(
        self,
        signal: str,
        *,
        claimed: bool,
        status: str,
        confidence: float,
        best_payload: dict[str, object],
    ) -> int:
        if not claimed:
            return 0
        if status == "not_present":
            return 0
        if status == "manual_check":
            return 1
        subject_role = str(best_payload.get("subject_role") or "unknown")
        signal_candidates = {str(value) for value in best_payload.get("candidate_signals", [])}
        keyword_text = " ".join(str(value) for value in best_payload.get("matching_keywords", []))
        base = 2 if confidence >= float(self.settings.verifier.present_confidence_threshold) else 1
        if signal == "marriage" and best_payload.get("script_guess") == "arabic_script_or_jawi":
            return max(base, 2)
        if signal == "self_illness" and subject_role not in {"applicant", "unknown"}:
            return min(base, 1)
        if signal == "family_illness" and subject_role not in {"spouse", "family", "unknown"}:
            return min(base, 1)
        if signal == "spouse_location" and signal not in signal_candidates and not keyword_text:
            return min(base, 1)
        if signal == "oku_self_or_family" and signal not in signal_candidates:
            return min(base, 1)
        if signal == "medex_or_other_exam" and signal not in signal_candidates and not keyword_text:
            return min(base, 1)
        if signal in {"oku_self_or_family", "medex_or_other_exam"} and confidence >= 0.85:
            return 3
        if signal in {"marriage", "spouse_location"} and confidence >= 0.9:
            return 3
        if signal in {"self_illness", "family_illness"} and confidence >= 0.8:
            return 2
        return base

    def _signal_summary(
        self,
        signal: str,
        *,
        claimed: bool,
        status: str,
        page_labels: list[dict[str, object]],
        recovery_payload: dict[str, dict[str, object]],
    ) -> str:
        label = signal.replace("_", " ")
        if not claimed:
            return "Not claimed; skipped."
        reasons: list[str] = []
        for payload in self._signal_page_payloads(signal, page_labels, recovery_payload):
            for reason in payload.get("reasons", []):
                text = str(reason).strip()
                if text and text not in reasons:
                    reasons.append(text)
        for reason in recovery_payload.get(signal, {}).get("reasons", []):
            text = str(reason).strip()
            if text and text not in reasons:
                reasons.append(text)
        if reasons:
            return " | ".join(reasons)
        if status == "present":
            return f"Supporting {label} evidence was found."
        if status == "manual_check":
            return f"Potential {label} evidence was found but remains ambiguous."
        return f"No supporting {label} evidence was found."

    def _build_signal_details(
        self,
        result: FirstPassEvidenceSignals,
        *,
        claims: ApplicantClaims | None,
        verifier_mode: str,
        page_labels: list[dict[str, object]],
        recovery_payload: dict[str, dict[str, object]],
        fallback_payload: dict[str, object] | None = None,
        applicant_context: dict[str, str] | None = None,
    ) -> dict[str, dict[str, object]]:
        claim_map = claims.signal_map() if claims else {signal: verifier_mode not in CLAIM_GUIDED_MODES for signal in SIGNAL_KEYS}
        details: dict[str, dict[str, object]] = {}
        for signal in SIGNAL_KEYS:
            status = getattr(result, signal)
            claimed = bool(claim_map.get(signal, False))
            supporting_pages = self._signal_supporting_pages(signal, page_labels, recovery_payload) if claimed else []
            confidence = self._signal_confidence(
                signal,
                status,
                page_labels=page_labels,
                recovery_payload=recovery_payload,
                fallback_payload=fallback_payload,
            ) if claimed else 0.0
            best_payload = self._best_support_payload(signal, page_labels, recovery_payload) if claimed else {}
            proof_strength = self._proof_strength(
                signal,
                claimed=claimed,
                status=status,
                confidence=confidence,
                best_payload=best_payload,
            )
            proof_found = claimed and proof_strength >= 2
            ambiguous = claimed and proof_strength == 1
            low_confidence = claimed and status == "present" and proof_strength < 2
            person_role = self._signal_person_role(signal, best_payload)
            details[signal] = {
                "claimed": claimed,
                "status": status if claimed else "not_present",
                "proof_found": proof_found,
                "verified": proof_found,
                "missing_proof": claimed and proof_strength == 0,
                "ambiguous": ambiguous,
                "low_confidence": low_confidence,
                "proof_strength": proof_strength,
                "supporting_pages": supporting_pages,
                "document_type": self._signal_document_type(signal, best_payload) if claimed else "",
                "person_named": self._signal_person_named(signal, best_payload, applicant_context) if claimed else "",
                "person_role": person_role if claimed else "unknown",
                "relationship_to_applicant": self._relationship_to_applicant(person_role) if claimed else "unknown",
                "evidence_summary": self._signal_summary(
                    signal,
                    claimed=claimed,
                    status=status,
                    page_labels=page_labels,
                    recovery_payload=recovery_payload,
                ),
                "confidence": round(confidence, 3),
            }
        return details

    def _all_active_signals_verified(self, signal_details: dict[str, dict[str, object]], active_signals: list[str]) -> bool:
        if not active_signals:
            return True
        threshold = float(self.settings.verifier.early_stop_confidence_threshold)
        for signal in active_signals:
            detail = signal_details.get(signal, {})
            if not detail.get("claimed"):
                continue
            if not detail.get("proof_found"):
                return False
            if float(detail.get("confidence") or 0.0) < threshold:
                return False
        return True

    def scan(
        self,
        document: OCRDocument,
        applicant_context: dict[str, str] | None = None,
        claims: ApplicantClaims | None = None,
        verifier_mode: str = "broad_classifier",
    ) -> FirstPassEvidenceSignals:
        claims = claims or (extract_applicant_claims(applicant_context or {}) if applicant_context else None)
        active_signals = self._active_signals(claims, verifier_mode)
        claim_key = "all" if verifier_mode not in CLAIM_GUIDED_MODES else "-".join(active_signals) if active_signals else "none"
        desired_mode, model_name = self._desired_mode(document)
        cache_path = self._cache_path(document.processing_hash, desired_mode, model_name, claim_key=claim_key)
        if cache_path.exists():
            return FirstPassEvidenceSignals.model_validate(json.loads(cache_path.read_text(encoding="utf-8")))

        if verifier_mode in CLAIM_GUIDED_MODES and not active_signals:
            skipped = self._empty_result()
            skipped.raw_payload = {
                "_method": "claim_guided_skip",
                "_cache_version": CACHE_VERSION,
                "_verifier_mode": verifier_mode,
                "claims": claims.signal_map() if claims else {},
                "claim_extraction": {
                    "unclear_claims": list(claims.unclear_claims) if claims else [],
                    "notes": list(claims.notes) if claims else [],
                },
            }
            skipped.raw_payload["signal_details"] = self._build_signal_details(
                skipped,
                claims=claims,
                verifier_mode=verifier_mode,
                page_labels=[],
                recovery_payload={},
                applicant_context=applicant_context,
            )
            cache_path.write_text(skipped.model_dump_json(indent=2) + "\n", encoding="utf-8")
            return skipped

        heuristic = self._heuristic_scan(document, applicant_context, active_signals=active_signals)
        result = heuristic
        images = self._document_images(document)

        if desired_mode == "ollama_vision":
            chunk_size = 1
            chunk_results: list[FirstPassEvidenceSignals] = []
            chunk_payloads: list[dict[str, object]] = []
            page_labels: list[dict[str, object]] = []
            recovery_payload: dict[str, dict[str, object]] = {}
            scanned_indexes: set[int] = set()
            shortlists = self._claim_shortlists_v5(document, applicant_context, active_signals) if self._is_v5_mode(verifier_mode) else {}
            if self._is_v5_mode(verifier_mode):
                page_indexes = self._union_shortlisted_pages(shortlists)
            else:
                initial_image_count = len(images)
                if verifier_mode == "claim_guided_verifier":
                    initial_image_count = min(len(images), CLAIM_GUIDED_INITIAL_PAGE_LIMIT)
                page_indexes = list(range(initial_image_count))
            for page_index in page_indexes:
                start = page_index
                stop = page_index + chunk_size
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
                            verifier_mode=verifier_mode,
                            claimed_signals=active_signals,
                        ),
                        image_paths=chunk_images,
                        run_secondary_on_weak_primary=self._is_v5_mode(verifier_mode) or verifier_mode != "claim_guided_verifier",
                    )
                    chunk_result = FirstPassEvidenceSignals(**payload.model_dump())
                    if verifier_mode not in NO_FORCED_GUESS_MODES:
                        chunk_result = self._apply_chunk_guess_fallback(chunk_result, payload, active_signals)
                    chunk_results.append(chunk_result)
                    page_label = self._page_label_payload(document.pages[page_index], payload, active_signals)
                    page_label["models_used"] = models_used
                    page_labels.append(page_label)
                    chunk_payloads.append(
                        {
                            "pages": self._page_range(document, start, stop),
                            "models_used": models_used,
                            **payload.model_dump(mode="json"),
                        }
                    )
                    scanned_indexes.add(page_index)
                except Exception:  # noqa: BLE001
                    continue
                if verifier_mode in CLAIM_GUIDED_MODES:
                    interim = self._aggregate_chunk_results(chunk_results, active_signals)
                    if verifier_mode not in NO_FORCED_GUESS_MODES:
                        interim = self._apply_document_guess_fallback(interim, chunk_payloads, active_signals)
                    interim_details = self._build_signal_details(
                        interim,
                        claims=claims,
                        verifier_mode=verifier_mode,
                        page_labels=page_labels,
                        recovery_payload={},
                        applicant_context=applicant_context,
                    )
                    if self._all_active_signals_verified(interim_details, active_signals):
                        break
            if chunk_payloads:
                llm_result = self._aggregate_chunk_results(chunk_results, active_signals)
                if verifier_mode not in NO_FORCED_GUESS_MODES:
                    llm_result = self._apply_document_guess_fallback(llm_result, chunk_payloads, active_signals)
                overview_result = self._overview_scan(
                    chunk_payloads,
                    applicant_context=applicant_context,
                    verifier_mode=verifier_mode,
                    active_signals=active_signals,
                )
                llm_result = self._merge_signals(llm_result, overview_result)
                result = self._merge_signals(heuristic, llm_result)
                result = self._post_process_result(result, document, chunk_payloads)
                result, recovery_payload = self._claim_recovery_scan(
                    document,
                    applicant_context,
                    images,
                    chunk_payloads,
                    result,
                    claims=claims,
                    verifier_mode=verifier_mode,
                    active_signals=active_signals,
                    shortlists=shortlists,
                    scanned_indexes=scanned_indexes,
                )
                signal_details = self._build_signal_details(
                    result,
                    claims=claims,
                    verifier_mode=verifier_mode,
                    page_labels=page_labels,
                    recovery_payload=recovery_payload,
                    applicant_context=applicant_context,
                )
                result.raw_payload = {
                    "_method": desired_mode,
                    "_model": self.llm_client.vision_model_name(),
                    "_secondary_model": self._secondary_model_name(),
                    "_cache_models": model_name,
                    "_cache_version": CACHE_VERSION,
                    "_verifier_mode": verifier_mode,
                    "chunks": chunk_payloads,
                    "page_labels": page_labels,
                    "claims": claims.signal_map() if claims else self._context_claims(applicant_context),
                    "claim_extraction": {
                        "unclear_claims": list(claims.unclear_claims) if claims else [],
                        "notes": list(claims.notes) if claims else [],
                    },
                    "active_signals": active_signals,
                    "signal_details": signal_details,
                    "claim_recovery": recovery_payload,
                    "claim_shortlists": {signal: [index + 1 for index in indexes] for signal, indexes in shortlists.items()},
                    "overview": overview_result.raw_payload,
                }
        elif desired_mode == "ollama_text":
            try:
                response = self.llm_client.generate(
                    first_pass_signals_prompt(
                        document.combined_text,
                        applicant_context=applicant_context,
                        verifier_mode=verifier_mode,
                        claimed_signals=active_signals,
                    )
                )
                payload = parse_model_response(response, FirstPassSignalsSchema)
                llm_result = FirstPassEvidenceSignals(**payload.model_dump())
                result = self._merge_signals(heuristic, llm_result)
                signal_details = self._build_signal_details(
                    result,
                    claims=claims,
                    verifier_mode=verifier_mode,
                    page_labels=[],
                    recovery_payload={},
                    fallback_payload=payload.model_dump(mode="json"),
                    applicant_context=applicant_context,
                )
                result.raw_payload = {
                    "_method": desired_mode,
                    "_model": model_name,
                    "_cache_version": CACHE_VERSION,
                    "_verifier_mode": verifier_mode,
                    "claims": claims.signal_map() if claims else self._context_claims(applicant_context),
                    "claim_extraction": {
                        "unclear_claims": list(claims.unclear_claims) if claims else [],
                        "notes": list(claims.notes) if claims else [],
                    },
                    "active_signals": active_signals,
                    "signal_details": signal_details,
                    **payload.model_dump(mode="json"),
                }
            except Exception:  # noqa: BLE001
                pass

        if desired_mode == "heuristic" and not result.raw_payload:
            result.raw_payload = {
                "_method": "heuristic",
                "_cache_version": CACHE_VERSION,
                "_verifier_mode": verifier_mode,
                "claims": claims.signal_map() if claims else self._context_claims(applicant_context),
                "claim_extraction": {
                    "unclear_claims": list(claims.unclear_claims) if claims else [],
                    "notes": list(claims.notes) if claims else [],
                },
                "active_signals": active_signals,
            }
        if "signal_details" not in result.raw_payload:
            result.raw_payload["signal_details"] = self._build_signal_details(
                result,
                claims=claims,
                verifier_mode=verifier_mode,
                page_labels=list(result.raw_payload.get("page_labels", [])),
                recovery_payload=dict(result.raw_payload.get("claim_recovery", {})),
                fallback_payload=result.raw_payload,
                applicant_context=applicant_context,
            )
        if desired_mode == "heuristic" or result.raw_payload.get("_method") in {desired_mode, "claim_guided_skip"}:
            cache_path.write_text(result.model_dump_json(indent=2) + "\n", encoding="utf-8")
        return result
