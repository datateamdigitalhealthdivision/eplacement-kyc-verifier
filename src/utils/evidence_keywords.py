"""Shared keyword heuristics for OCR page metadata."""

from __future__ import annotations

import re


SIGNAL_PATTERNS: dict[str, list[str]] = {
    "marriage": [
        r"SURAT\s+PERAKUAN\s+NIKAH",
        r"SIJIL\s+NIKAH",
        r"SIJIL\s+PERKAHWINAN",
        r"MARRIAGE\s+CERTIFICATE",
        r"TARIKH\s+NIKAH",
        r"NOMBOR\s+DAFTAR",
    ],
    "self_illness": [
        r"HOSPITAL",
        r"KLINIK",
        r"DIAGNOSIS",
        r"PATIENT",
        r"FOLLOW\s*UP",
        r"MEDICATION",
        r"IMPRESSION",
        r"RAWATAN",
        r"THERAPY",
    ],
    "family_illness": [
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
    ],
    "spouse_location": [
        r"PENEMPATAN",
        r"PLACEMENT",
        r"LAPOR\s+DIRI",
        r"TEMPAT\s+TUGAS",
        r"BERTUGAS",
        r"PERTUKARAN",
        r"JAWATAN",
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
        r"POSTGRADUATE",
        r"PRE-ENTRANCE\s+EXAM",
        r"EXAM\s+RESULT",
        r"PEPERIKSAAN",
        r"KEPUTUSAN\s+PEPERIKSAAN",
        r"SIJIL\s+KEPUTUSAN",
    ],
}


def matching_keywords(text: str) -> dict[str, list[str]]:
    text = str(text or "")
    matches: dict[str, list[str]] = {}
    for signal, patterns in SIGNAL_PATTERNS.items():
        values: list[str] = []
        for pattern in patterns:
            for match in re.finditer(pattern, text, flags=re.IGNORECASE):
                value = match.group(0).strip()
                if value and value not in values:
                    values.append(value)
        matches[signal] = values
    return matches


def candidate_signals(text: str) -> tuple[list[str], dict[str, list[str]]]:
    matches = matching_keywords(text)
    signals = [signal for signal, values in matches.items() if values]
    return signals, matches
