"""Derived document tags used for claim cross-checking and operator review."""

from __future__ import annotations

import re
from typing import Any


TAG_PATTERNS: dict[str, list[str]] = {
    "marriage_certificate": [
        r"SURAT\s+PERAKUAN\s+NIKAH",
        r"SIJIL\s+NIKAH",
        r"MARRIAGE\s+CERTIFICATE",
        r"TARIKH\s+NIKAH",
        r"NOMBOR\s+DAFTAR",
    ],
    "marriage_related_document": [
        r"NIKAH",
        r"PERKAHWINAN",
        r"MARRIAGE",
        r"TA[' ]?LIQ",
        r"PENDAFTARAN\s+NIKAH",
        r"REGISTER(?:ING)?\s+FOR\s+MARRIAGE",
    ],
    "medex_exam_document": [
        r"\bMEDEX\b",
        r"PEPERIKSAAN\s+KEMASUKAN",
        r"\bGCFM\b",
        r"KEPUTUSAN\s+(?:PEPERIKSAAN|EXAM|MEDEX)",
        r"EXAM\s+RESULT",
    ],
    "oku_document": [
        r"\bOKU\b",
        r"ORANG\s+KURANG\s+UPAYA",
        r"JABATAN\s+KEBAJIKAN\s+MASYARAKAT",
        r"PENDAFTARAN\s+ORANG\s+KURANG\s+UPAYA",
        r"DISABILITY",
    ],
    "medical_document": [
        r"HOSPITAL",
        r"KLINIK",
        r"DIAGNOSIS",
        r"PATIENT",
        r"VITAL\s+SIGNS",
        r"PEJABAT\s+KESIHATAN",
        r"MEDICAL",
        r"SEBAB\s+KEMATIAN",
    ],
}


DOC_TYPE_TAGS = {
    "marriage_certificate": ["marriage_certificate", "marriage_related_document"],
    "medex_or_exam_document": ["medex_exam_document", "medical_document"],
    "other_supporting_document": ["other_supporting_document"],
    "unknown": [],
}


TEXT_INFERENCE_DOC_TYPES = {"other_supporting_document", "unknown"}


def _flatten_text(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        parts: list[str] = []
        for item in value.values():
            parts.extend(_flatten_text(item))
        return parts
    if isinstance(value, (list, tuple, set)):
        parts: list[str] = []
        for item in value:
            parts.extend(_flatten_text(item))
        return parts
    return [str(value)]


def _combined_text(evidence: Any, document: Any) -> str:
    return "\n".join(
        part
        for part in [
            getattr(document, "combined_text", ""),
            *getattr(evidence, "key_supporting_snippets", []),
            *_flatten_text(getattr(evidence, "raw_payload", {})),
        ]
        if part
    )


def _pattern_matches(text: str) -> dict[str, bool]:
    if not text:
        return {tag: False for tag in TAG_PATTERNS}
    return {
        tag: any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)
        for tag, patterns in TAG_PATTERNS.items()
    }


def derive_document_tags(classification, evidence, document) -> dict[str, Any]:
    tags = {
        "marriage_certificate": False,
        "marriage_related_document": False,
        "medex_exam_document": False,
        "oku_document": False,
        "medical_document": False,
        "other_supporting_document": False,
    }
    primary_doc_type = getattr(evidence, "doc_type", None) or getattr(classification, "primary_type", "unknown")
    for tag in DOC_TYPE_TAGS.get(primary_doc_type, []):
        tags[tag] = True

    text_matches = _pattern_matches(_combined_text(evidence, document))
    if primary_doc_type in TEXT_INFERENCE_DOC_TYPES:
        for tag, matched in text_matches.items():
            tags[tag] = tags[tag] or matched

    if tags["marriage_certificate"]:
        tags["marriage_related_document"] = True
    if tags["medex_exam_document"]:
        tags["medical_document"] = True

    positive_tags = [tag for tag, enabled in tags.items() if enabled]
    return {
        "primary_document_type": primary_doc_type,
        "positive_tags": positive_tags,
        "marriage_evidence_detected": tags["marriage_certificate"] or tags["marriage_related_document"],
        "medex_evidence_detected": tags["medex_exam_document"],
        "oku_evidence_detected": tags["oku_document"],
        **tags,
    }
