"""Langflow component that loads applicant rows from a spreadsheet."""

from __future__ import annotations

from pathlib import Path

from src.io.spreadsheet_loader import SpreadsheetBundle, SpreadsheetLoader
from src.langflow_components._base import Component


class ApplicantLoaderComponent(Component):
    display_name = "Applicant Loader"
    description = "Load and normalize applicant spreadsheet rows."
    name = "ApplicantLoaderComponent"

    def __init__(self, project_root: Path | None = None, **kwargs):
        super().__init__(**kwargs)
        root = project_root or Path(__file__).resolve().parents[2]
        self.loader = SpreadsheetLoader(project_root=root)

    def load_bundle(self, applicant_path: str) -> SpreadsheetBundle:
        return self.loader.load(applicant_path)

    def run_model(self, applicant_path: str) -> dict:
        bundle = self.load_bundle(applicant_path)
        return {
            "source_path": str(bundle.source_path),
            "records": [record.canonical for record in bundle.records],
            "resolved_columns": bundle.resolved_columns,
            "missing_required": bundle.missing_required,
            "warnings": bundle.warnings,
        }
