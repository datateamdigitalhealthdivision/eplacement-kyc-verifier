"""Helpers for validating local model JSON responses."""

from __future__ import annotations

import json
import re
from typing import Any, TypeVar

from pydantic import BaseModel


ModelT = TypeVar("ModelT", bound=BaseModel)
FIRST_PASS_STATUS_KEYS = {
    "marriage",
    "self_illness",
    "family_illness",
    "spouse_location",
    "oku_self_or_family",
    "medex_or_other_exam",
}
FIRST_PASS_BUCKET_ALIASES = {
    "marriage": "marriage",
    "marriage certificate": "marriage",
    "self illness": "self_illness",
    "family illness": "family_illness",
    "spouse location": "spouse_location",
    "oku self or family": "oku_self_or_family",
    "oku": "oku_self_or_family",
    "medex or other exam": "medex_or_other_exam",
    "medex": "medex_or_other_exam",
    "exam": "medex_or_other_exam",
}
SUBJECT_ROLE_ALIASES = {
    "applicant": "applicant",
    "self": "applicant",
    "candidate": "applicant",
    "spouse": "spouse",
    "husband": "spouse",
    "wife": "spouse",
    "family": "family",
    "parent": "family",
    "child": "family",
    "other person": "other_person",
    "other_person": "other_person",
    "unknown": "unknown",
}


def extract_json_fragment(text: str) -> str:
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("No JSON object found in model response.")
    return text[start : end + 1]


def _coerce_confidence(value: Any) -> float:
    if value is None:
        return 0.0
    if isinstance(value, (int, float)):
        return max(0.0, min(1.0, float(value)))
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if not normalized:
            return 0.0
        label_map = {
            "very high": 0.98,
            "high": 0.9,
            "medium": 0.65,
            "moderate": 0.65,
            "low": 0.35,
            "very low": 0.1,
        }
        if normalized in label_map:
            return label_map[normalized]
        match = re.search(r"\d+(?:\.\d+)?", normalized)
        if match:
            numeric = float(match.group(0))
            if numeric > 1.0:
                numeric = numeric / 100.0 if numeric <= 100.0 else 1.0
            return max(0.0, min(1.0, numeric))
    return 0.0


def _coerce_page_refs(value: Any) -> list[int]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    refs: list[int] = []
    for item in items:
        if isinstance(item, int):
            refs.append(item)
        elif isinstance(item, float):
            refs.append(int(item))
        elif isinstance(item, str):
            refs.extend(int(match) for match in re.findall(r"\d+", item))
    deduped: list[int] = []
    for ref in refs:
        if ref > 0 and ref not in deduped:
            deduped.append(ref)
    return deduped


def _coerce_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    items = value if isinstance(value, list) else [value]
    cleaned = [str(item).strip() for item in items if str(item).strip()]
    return cleaned


def _coerce_presence_status(value: Any) -> str:
    if isinstance(value, bool):
        return "present" if value else "not_present"
    normalized = str(value or "").strip().casefold()
    if not normalized:
        return "not_present"
    if normalized in {"present", "yes", "y", "true", "found", "detected"}:
        return "present"
    if normalized in {"manual_check", "manual", "unclear", "ambiguous", "uncertain", "possible", "maybe"}:
        return "manual_check"
    if normalized in {"not_present", "no", "n", "false", "not found", "absent", "none"}:
        return "not_present"
    return "manual_check"


def _coerce_first_pass_bucket(value: Any) -> str | None:
    normalized = str(value or "").strip().casefold().replace("-", "_")
    if not normalized:
        return None
    normalized = re.sub(r"\s+", " ", normalized.replace("_", " ")).strip()
    return FIRST_PASS_BUCKET_ALIASES.get(normalized)


def _coerce_subject_role(value: Any) -> str:
    normalized = str(value or "").strip().casefold().replace("-", "_")
    if not normalized:
        return "unknown"
    normalized = re.sub(r"\s+", " ", normalized.replace("_", " ")).strip()
    return SUBJECT_ROLE_ALIASES.get(normalized, "unknown")


def _normalize_payload(payload: dict[str, Any], overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    normalized = dict(payload)
    if "confidence" in normalized:
        normalized["confidence"] = _coerce_confidence(normalized.get("confidence"))
    if "extraction_confidence" in normalized:
        normalized["extraction_confidence"] = _coerce_confidence(normalized.get("extraction_confidence"))
    if "best_fit_confidence" in normalized:
        normalized["best_fit_confidence"] = _coerce_confidence(normalized.get("best_fit_confidence"))
    if "subject_role_confidence" in normalized:
        normalized["subject_role_confidence"] = _coerce_confidence(normalized.get("subject_role_confidence"))
    for key in list(normalized):
        if key.endswith("_confidence") and key not in {"confidence", "extraction_confidence", "best_fit_confidence", "subject_role_confidence"}:
            normalized[key] = _coerce_confidence(normalized.get(key))
    if "page_refs" in normalized:
        normalized["page_refs"] = _coerce_page_refs(normalized.get("page_refs"))
    if "reasons" in normalized:
        normalized["reasons"] = _coerce_string_list(normalized.get("reasons"))
    if "key_supporting_snippets" in normalized:
        normalized["key_supporting_snippets"] = _coerce_string_list(normalized.get("key_supporting_snippets"))
    for key, value in list(normalized.items()):
        if key in FIRST_PASS_STATUS_KEYS:
            normalized[key] = _coerce_presence_status(value)
            continue
        if key == "best_fit_bucket":
            normalized[key] = _coerce_first_pass_bucket(value)
            continue
        if key == "subject_role":
            normalized[key] = _coerce_subject_role(value)
            continue
        if isinstance(value, str):
            stripped = value.strip()
            normalized[key] = stripped or None
    if overrides:
        normalized.update(overrides)
    return normalized


def parse_model_response(text: str, schema: type[ModelT], overrides: dict[str, Any] | None = None) -> ModelT:
    fragment = extract_json_fragment(text)
    payload = _normalize_payload(json.loads(fragment), overrides=overrides)
    return schema.model_validate(payload)
