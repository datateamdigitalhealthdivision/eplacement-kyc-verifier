"""Langflow component that locates or downloads a PDF for an applicant."""

from __future__ import annotations

from pathlib import Path

from src.io.downloader import Downloader
from src.io.pdf_locator import PDFLocator
from src.io.spreadsheet_loader import ApplicantRecord
from src.langflow_components._base import Component
from src.settings import AppConfig, load_app_config


class PDFFetchComponent(Component):
    display_name = "PDF Fetch"
    description = "Find an applicant PDF locally or download it from a URL column."
    name = "PDFFetchComponent"

    def __init__(self, settings: AppConfig | None = None, project_root: Path | None = None, **kwargs):
        super().__init__(**kwargs)
        root = project_root or Path(__file__).resolve().parents[2]
        self.settings = settings or load_app_config(project_root=root)
        self.downloader = Downloader(timeout_seconds=self.settings.ollama.timeout_seconds)

    def fetch_pdf(self, applicant_row: dict, pdf_directory: str, auto_download: bool = True) -> dict:
        record = ApplicantRecord(row_index=0, applicant_id=str(applicant_row.get("applicant_id", "")), canonical=applicant_row, raw=applicant_row)
        locator = PDFLocator([pdf_directory, self.settings.paths.pdf_dir, self.settings.paths.downloads_dir])
        located = locator.locate(record)
        if located.path is not None:
            return {
                "path": str(located.path),
                "status": located.status,
                "source": located.source,
                "downloaded": False,
            }
        if auto_download and str(applicant_row.get("pdf_url") or ""):
            download = self.downloader.download(
                str(applicant_row.get("pdf_url")),
                self.settings.paths.downloads_dir,
                str(applicant_row.get("pdf_filename") or f"{record.applicant_id}.pdf"),
            )
            return {
                "path": str(download.path) if download.path else None,
                "status": download.status,
                "error": download.error,
                "downloaded": download.downloaded,
            }
        return {
            "path": None,
            "status": "MISSING",
            "attempted_names": located.attempted_names,
            "message": located.message,
            "downloaded": False,
        }

    def run_model(self, applicant_row: dict, pdf_directory: str, auto_download: bool = True) -> dict:
        return self.fetch_pdf(applicant_row, pdf_directory, auto_download)
