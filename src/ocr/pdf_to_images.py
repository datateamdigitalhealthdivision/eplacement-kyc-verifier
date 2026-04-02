"""Render PDF pages to images for OCR fallback."""

from __future__ import annotations

from pathlib import Path

import fitz


class PDFToImagesRenderer:
    def __init__(self, dpi: int = 225) -> None:
        self.dpi = dpi

    def render(self, pdf_path: str | Path, output_dir: str | Path) -> list[Path]:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        matrix = fitz.Matrix(self.dpi / 72, self.dpi / 72)
        document = fitz.open(pdf_path)
        rendered: list[Path] = []
        for index, page in enumerate(document):
            pixmap = page.get_pixmap(matrix=matrix, alpha=False)
            target = output / f"page_{index + 1:04d}.png"
            pixmap.save(target)
            rendered.append(target)
        return rendered
