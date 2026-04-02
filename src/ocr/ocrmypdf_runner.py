"""OCRmyPDF/Tesseract-backed OCR fallback helpers."""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytesseract
from PIL import Image
from pytesseract import Output

from src.extraction.evidence_models import OCRPage
from src.utils.confidence import average_confidence, flag_low_confidence
from src.utils.language_guess import guess_script


class OCRMyPDFRunner:
    def __init__(
        self,
        languages: str = "eng+msa+ara",
        low_confidence_threshold: float = 0.7,
        tesseract_cmd: str | Path | None = None,
        tessdata_dir: str | Path | None = None,
    ) -> None:
        self.languages = languages
        self.low_confidence_threshold = low_confidence_threshold
        self.tesseract_cmd = Path(tesseract_cmd) if tesseract_cmd else self._detect_tesseract_cmd()
        self.tessdata_dir = Path(tessdata_dir) if tessdata_dir else self._detect_tessdata_dir()
        if self.tesseract_cmd is not None:
            pytesseract.pytesseract.tesseract_cmd = str(self.tesseract_cmd)

    @staticmethod
    def _detect_tesseract_cmd() -> Path | None:
        env_value = os.getenv("EPKYC_TESSERACT_CMD")
        candidates = [
            Path(env_value) if env_value else None,
            Path(shutil.which("tesseract")) if shutil.which("tesseract") else None,
            Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
            Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
        ]
        for candidate in candidates:
            if candidate and candidate.exists():
                return candidate
        return None

    @staticmethod
    def _detect_tessdata_dir() -> Path | None:
        env_value = os.getenv("EPKYC_TESSDATA_DIR")
        repo_tools = Path(__file__).resolve().parents[2] / ".tools" / "tessdata"
        candidates = [
            Path(env_value) if env_value else None,
            repo_tools,
            Path(r"C:\Program Files\Tesseract-OCR\tessdata"),
            Path(r"C:\Program Files (x86)\Tesseract-OCR\tessdata"),
        ]
        for candidate in candidates:
            if candidate and candidate.exists() and any(candidate.glob("*.traineddata")):
                return candidate
        return None

    def available_cli(self) -> bool:
        return self.tesseract_cmd is not None and self.tesseract_cmd.exists()

    def _tesseract_config(self) -> str:
        if self.tessdata_dir is None:
            return ""
        return f'--tessdata-dir "{self.tessdata_dir}"'

    def run_page(self, image_path: str | Path, page_number: int) -> OCRPage:
        if self.tesseract_cmd is None:
            return OCRPage(
                page_number=page_number,
                extracted_text="",
                engine_used="tesseract_unavailable",
                confidence=0.0,
                language_guess="unknown",
                low_confidence=True,
            )
        image = Image.open(image_path)
        try:
            data = pytesseract.image_to_data(
                image,
                lang=self.languages,
                output_type=Output.DICT,
                config=self._tesseract_config(),
            )
        except Exception:
            return OCRPage(
                page_number=page_number,
                extracted_text="",
                engine_used="tesseract_error",
                confidence=0.0,
                language_guess="unknown",
                low_confidence=True,
            )
        tokens = [token for token in data.get("text", []) if str(token).strip()]
        text = " ".join(tokens).strip()
        confidences = []
        for raw_confidence in data.get("conf", []):
            try:
                confidence_value = float(raw_confidence)
            except (TypeError, ValueError):
                continue
            if confidence_value >= 0:
                confidences.append(confidence_value / 100)
        confidence = average_confidence(confidences, default=0.0)
        boxes = []
        for left, top, width, height in zip(
            data.get("left", []),
            data.get("top", []),
            data.get("width", []),
            data.get("height", []),
        ):
            try:
                boxes.append([int(left), int(top), int(width), int(height)])
            except (TypeError, ValueError):
                continue
        return OCRPage(
            page_number=page_number,
            extracted_text=text,
            engine_used="tesseract",
            confidence=confidence,
            language_guess=guess_script(text),
            low_confidence=flag_low_confidence(confidence, self.low_confidence_threshold),
            bounding_boxes=boxes,
        )
