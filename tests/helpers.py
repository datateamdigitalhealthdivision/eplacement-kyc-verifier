"""Test helpers for temporary settings and synthetic PDFs."""

from __future__ import annotations

from pathlib import Path

import fitz

from src.settings import load_app_config
from src.utils.paths import ensure_directories


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def make_test_settings(tmp_path: Path):
    settings = load_app_config(project_root=PROJECT_ROOT).model_copy(deep=True)
    settings.ollama.enabled = False
    settings.langflow.enabled = False
    settings.paths.applicants_dir = tmp_path / "input" / "applicants"
    settings.paths.pdf_dir = tmp_path / "input" / "pdfs"
    settings.paths.sample_dir = tmp_path / "input" / "samples"
    settings.paths.downloads_dir = tmp_path / "working" / "downloads"
    settings.paths.extracted_text_dir = tmp_path / "working" / "extracted_text"
    settings.paths.page_images_dir = tmp_path / "working" / "page_images"
    settings.paths.ocr_json_dir = tmp_path / "working" / "ocr_json"
    settings.paths.llm_json_dir = tmp_path / "working" / "llm_json"
    settings.paths.cache_dir = tmp_path / "working" / "cache"
    settings.paths.db_path = tmp_path / "working" / "db" / "test.sqlite3"
    settings.paths.reports_dir = tmp_path / "output" / "reports"
    settings.paths.merged_dir = tmp_path / "output" / "merged"
    settings.paths.review_dir = tmp_path / "output" / "review"
    settings.paths.logs_dir = tmp_path / "output" / "logs"
    ensure_directories(
        [
            settings.paths.applicants_dir,
            settings.paths.pdf_dir,
            settings.paths.sample_dir,
            settings.paths.downloads_dir,
            settings.paths.extracted_text_dir,
            settings.paths.page_images_dir,
            settings.paths.ocr_json_dir,
            settings.paths.llm_json_dir,
            settings.paths.cache_dir,
            settings.paths.db_path.parent,
            settings.paths.reports_dir,
            settings.paths.merged_dir,
            settings.paths.review_dir,
            settings.paths.logs_dir,
        ]
    )
    return settings


def write_pdf(path: Path, lines: list[str]) -> None:
    document = fitz.open()
    page = document.new_page()
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=12)
        y += 18
    document.save(path)
    document.close()
