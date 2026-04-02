"""Optional PaddleOCR fallback for difficult layouts or Arabic-script pages."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from src.extraction.evidence_models import OCRPage
from src.utils.confidence import average_confidence, flag_low_confidence
from src.utils.language_guess import guess_script


@lru_cache(maxsize=1)
def _load_paddleocr() -> object | None:
    try:
        from paddleocr import PaddleOCR  # type: ignore
    except Exception:  # noqa: BLE001
        return None
    return PaddleOCR(use_angle_cls=True, lang="en")


class PaddleOCRRunner:
    def __init__(self, low_confidence_threshold: float = 0.7) -> None:
        self.low_confidence_threshold = low_confidence_threshold

    def is_available(self) -> bool:
        return _load_paddleocr() is not None

    def run_page(self, image_path: str | Path, page_number: int) -> OCRPage:
        engine = _load_paddleocr()
        if engine is None:
            return OCRPage(
                page_number=page_number,
                extracted_text="",
                engine_used="paddleocr_unavailable",
                confidence=0.0,
                language_guess="unknown",
                low_confidence=True,
            )
        result = engine.ocr(str(image_path), cls=True) or []
        lines: list[str] = []
        boxes: list[list[int | float]] = []
        confidences: list[float] = []
        for page_result in result:
            for line in page_result:
                box, (text, confidence) = line
                if text.strip():
                    lines.append(text.strip())
                confidences.append(float(confidence))
                flattened = [coordinate for point in box for coordinate in point]
                boxes.append(flattened)
        text = " ".join(lines).strip()
        confidence = average_confidence(confidences, default=0.0)
        return OCRPage(
            page_number=page_number,
            extracted_text=text,
            engine_used="paddleocr",
            confidence=confidence,
            language_guess=guess_script(text),
            low_confidence=flag_low_confidence(confidence, self.low_confidence_threshold),
            bounding_boxes=boxes,
        )
