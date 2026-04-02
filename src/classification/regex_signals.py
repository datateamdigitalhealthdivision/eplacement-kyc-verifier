"""Deterministic regex signals for supported evidence types."""

from __future__ import annotations

import re


SIGNAL_PATTERNS: dict[str, list[str]] = {
    "marriage_certificate": [
        r"SURAT\s+PERAKUAN\s+NIKAH",
        r"SIJIL\s+NIKAH",
        r"MARRIAGE\s+CERTIFICATE",
        r"NOMBOR\s+DAFTAR",
        r"TARIKH\s+NIKAH",
    ],
    "medex_or_exam_document": [
        r"\bMEDEX\b",
        r"PEPERIKSAAN\s+KEMASUKAN",
        r"\bGCFM\b",
        r"(?:KEPUTUSAN|RESULT)\s+(?:MEDEX|PEPERIKSAAN|EXAM|GCFM)",
        r"MALAYSIAN\s+MEDICAL\s+COUNCIL",
        r"MAJLIS\s+PERUBATAN\s+MALAYSIA",
    ],
    "other_supporting_document": [
        r"SUPPORTING\s+DOCUMENT",
        r"LETTER",
        r"CERTIFICATION",
    ],
}


def score_signals(text: str) -> dict[str, list[str]]:
    signals: dict[str, list[str]] = {}
    for doc_type, patterns in SIGNAL_PATTERNS.items():
        matched = [pattern for pattern in patterns if re.search(pattern, text, flags=re.IGNORECASE)]
        if matched:
            signals[doc_type] = matched
    return signals
