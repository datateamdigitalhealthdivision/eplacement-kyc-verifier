"""Very lightweight script and language hints for routing."""

from __future__ import annotations

import re

from src.utils.text_cleaning import normalize_whitespace


ARABIC_SCRIPT_RE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]")
TAMIL_RE = re.compile(r"[\u0B80-\u0BFF]")
CHINESE_RE = re.compile(r"[\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF]")
LATIN_RE = re.compile(r"[A-Za-z]")


def guess_script(text: str) -> str:
    compact = normalize_whitespace(text)
    if not compact:
        return "unknown"
    counts = {
        "arabic_script_or_jawi": len(ARABIC_SCRIPT_RE.findall(compact)),
        "tamil": len(TAMIL_RE.findall(compact)),
        "chinese": len(CHINESE_RE.findall(compact)),
        "latin": len(LATIN_RE.findall(compact)),
    }
    script, count = max(counts.items(), key=lambda item: item[1])
    if count > 0:
        return script
    return "unknown"


def is_jawi_like(text: str) -> bool:
    compact = normalize_whitespace(text).casefold()
    return guess_script(compact) == "arabic_script_or_jawi" or "jawi" in compact
