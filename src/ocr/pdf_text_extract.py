"""Direct PDF text extraction before OCR fallback."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz


@dataclass(slots=True)
class DirectTextPage:
    page_number: int
    text: str
    char_count: int
    alpha_ratio: float
    adequate: bool


class DirectTextExtractor:
    def __init__(self, min_chars: int = 40, min_alpha_ratio: float = 0.18) -> None:
        self.min_chars = min_chars
        self.min_alpha_ratio = min_alpha_ratio

    @staticmethod
    def _alpha_ratio(text: str) -> float:
        if not text:
            return 0.0
        letters = sum(1 for character in text if character.isalpha())
        return letters / max(len(text), 1)

    def extract(self, pdf_path: str | Path) -> list[DirectTextPage]:
        document = fitz.open(pdf_path)
        pages: list[DirectTextPage] = []
        for index, page in enumerate(document):
            text = page.get_text("text").strip()
            char_count = len(text)
            alpha_ratio = self._alpha_ratio(text)
            adequate = char_count >= self.min_chars and alpha_ratio >= self.min_alpha_ratio
            pages.append(
                DirectTextPage(
                    page_number=index + 1,
                    text=text,
                    char_count=char_count,
                    alpha_ratio=round(alpha_ratio, 4),
                    adequate=adequate,
                )
            )
        return pages
