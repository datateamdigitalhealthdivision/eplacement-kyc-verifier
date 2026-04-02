"""Route each PDF page through direct extraction, Tesseract, or PaddleOCR."""

from __future__ import annotations

from pathlib import Path

from src.extraction.evidence_models import OCRDocument, OCRPage
from src.ocr.ocr_cache import OCRCache
from src.ocr.ocrmypdf_runner import OCRMyPDFRunner
from src.ocr.paddleocr_runner import PaddleOCRRunner
from src.ocr.pdf_text_extract import DirectTextExtractor
from src.ocr.pdf_to_images import PDFToImagesRenderer
from src.settings import AppConfig
from src.utils.hashing import sha256_file, stable_json_hash
from src.utils.language_guess import guess_script, is_jawi_like


class OCRRouter:
    def __init__(self, settings: AppConfig) -> None:
        self.settings = settings
        self.direct_extractor = DirectTextExtractor(
            min_chars=settings.ocr.direct_text_min_chars,
            min_alpha_ratio=settings.ocr.direct_text_min_alpha_ratio,
        )
        self.renderer = PDFToImagesRenderer(dpi=settings.ocr.dpi)
        self.ocr_runner = OCRMyPDFRunner(
            languages=settings.ocr.tesseract_languages,
            low_confidence_threshold=settings.ocr.low_confidence_threshold,
        )
        self.paddle_runner = PaddleOCRRunner(low_confidence_threshold=settings.ocr.low_confidence_threshold)
        self.cache = OCRCache(settings.paths.ocr_json_dir)

    def _processing_hash(self, document_hash: str) -> str:
        return stable_json_hash(
            {
                "document_hash": document_hash,
                "dpi": self.settings.ocr.dpi,
                "languages": self.settings.ocr.tesseract_languages,
                "paddle": self.settings.ocr.use_paddle_fallback,
            }
        )

    @staticmethod
    def _store_rendered_images(document: OCRDocument, rendered_images: list[Path]) -> OCRDocument:
        document.page_image_paths = [str(path) for path in rendered_images]
        document.metadata["page_image_paths"] = list(document.page_image_paths)
        document.metadata["page_count"] = max(len(document.pages), len(document.page_image_paths))
        return document

    def process_document(self, applicant_id: str, pdf_path: str | Path) -> OCRDocument:
        pdf_path = Path(pdf_path)
        document_hash = sha256_file(pdf_path)
        processing_hash = self._processing_hash(document_hash)
        image_dir = self.settings.paths.page_images_dir / document_hash
        cached = self.cache.load(processing_hash)
        if cached is not None:
            if not cached.page_image_paths or any(not Path(path).exists() for path in cached.page_image_paths):
                rendered_images = self.renderer.render(pdf_path, image_dir)
                cached = self._store_rendered_images(cached, rendered_images)
                self.cache.save(cached)
            return cached

        direct_pages = self.direct_extractor.extract(pdf_path)
        rendered_images = self.renderer.render(pdf_path, image_dir)
        pages: list[OCRPage] = []
        warnings: list[str] = []

        for direct_page, image_path in zip(direct_pages, rendered_images):
            if direct_page.adequate:
                pages.append(
                    OCRPage(
                        page_number=direct_page.page_number,
                        extracted_text=direct_page.text,
                        engine_used="direct_text",
                        confidence=1.0,
                        language_guess=guess_script(direct_page.text),
                        low_confidence=False,
                    )
                )
                continue

            prefer_paddle = self.settings.ocr.use_paddle_fallback and (
                is_jawi_like(direct_page.text) or direct_page.alpha_ratio < 0.05
            )
            selected = (
                self.paddle_runner.run_page(image_path, direct_page.page_number)
                if prefer_paddle
                else self.ocr_runner.run_page(image_path, direct_page.page_number)
            )
            if (
                selected.low_confidence
                and self.settings.ocr.use_paddle_fallback
                and not prefer_paddle
                and self.paddle_runner.is_available()
            ):
                paddle_candidate = self.paddle_runner.run_page(image_path, direct_page.page_number)
                if (paddle_candidate.confidence or 0.0) > (selected.confidence or 0.0):
                    selected = paddle_candidate
            if not selected.extracted_text:
                warnings.append(f"No text extracted for page {direct_page.page_number}.")
            pages.append(selected)

        combined_text = "\n\n".join(f"[Page {page.page_number}]\n{page.extracted_text}" for page in pages).strip()
        if not combined_text:
            warnings.append("OCR pipeline produced empty text.")
        document = OCRDocument(
            applicant_id=applicant_id,
            document_path=str(pdf_path),
            document_hash=document_hash,
            processing_hash=processing_hash,
            pages=pages,
            page_image_paths=[str(path) for path in rendered_images],
            combined_text=combined_text,
            warnings=warnings,
            metadata={
                "page_count": len(pages),
                "engines": list(dict.fromkeys(page.engine_used for page in pages)),
                "page_image_paths": [str(path) for path in rendered_images],
            },
        )
        self.cache.save(document)
        return document
