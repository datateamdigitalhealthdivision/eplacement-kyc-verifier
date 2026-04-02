"""Text normalization and redaction helpers."""

from __future__ import annotations

import re
from pathlib import Path


WHITESPACE_RE = re.compile(r"\s+")
IC_RE = re.compile(r"\b\d{6}[- ]?\d{2}[- ]?\d{4}\b|\b\d{12}\b")
SCIENTIFIC_NOTATION_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?[Ee][+-]?\d+$")


def normalize_whitespace(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text or "").strip()


def normalize_name(text: str) -> str:
    normalized = normalize_whitespace(text).upper()
    normalized = re.sub(r"[^A-Z0-9 ]", "", normalized)
    return normalized


def normalize_identifier(value: str | None) -> str:
    return re.sub(r"\D", "", value or "")


def looks_like_scientific_notation(value: str | None) -> bool:
    return bool(SCIENTIFIC_NOTATION_RE.fullmatch(normalize_whitespace(value or "")))


def extract_pdf_stem_identifier(filename: str | None) -> str:
    stem = Path(normalize_whitespace(filename or "")).stem
    digits = normalize_identifier(stem)
    return digits if len(digits) == 12 else ""


def redact_sensitive(value: str, keep_last: int = 4) -> str:
    normalized = normalize_identifier(value)
    if not normalized:
        return value
    masked = "*" * max(len(normalized) - keep_last, 0) + normalized[-keep_last:]
    return masked


def redact_text(text: str) -> str:
    return IC_RE.sub(lambda match: redact_sensitive(match.group(0)), text or "")
