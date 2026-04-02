from pathlib import Path

from src.ocr.ocr_router import OCRRouter
from tests.helpers import make_test_settings, write_pdf


def test_ocr_router_uses_direct_text_for_digital_pdf(tmp_path: Path) -> None:
    settings = make_test_settings(tmp_path)
    pdf_path = tmp_path / "input" / "pdfs" / "direct.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    write_pdf(pdf_path, ["SURAT PERAKUAN NIKAH", "NAMA SUAMI: AHMAD", "NAMA ISTERI: ALIA"])
    document = OCRRouter(settings).process_document("950101145678", pdf_path)
    assert "SURAT PERAKUAN NIKAH" in document.combined_text
    assert all(page.engine_used == "direct_text" for page in document.pages)
    assert len(document.page_image_paths) == len(document.pages)
    assert all(Path(path).exists() for path in document.page_image_paths)
