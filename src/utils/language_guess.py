"""Very lightweight script and language hints for routing."""

from __future__ import annotations

import re

from src.utils.text_cleaning import normalize_whitespace


ARABIC_SCRIPT_RE = re.compile(r"[؀-ۿ]")
LATIN_RE = re.compile(r"[A-Za-z]")


def guess_script(text: str) -> str:
    compact = normalize_whitespace(text)
    if not compact:
        return "unknown"
    if ARABIC_SCRIPT_RE.search(compact):
        return "arabic_script"
    if LATIN_RE.search(compact):
        return "latin"
    return "unknown"


def is_jawi_like(text: str) -> bool:
    script = guess_script(text)
    lowered = text.lower()
    return script == "arabic_script" or "jawi" in lowered
