"""Langflow component that loads applicant rows from a spreadsheet."""

from __future__ import annotations

from pathlib import Path

from src.io.spreadsheet_loader import SpreadsheetLoader
from src.langflow_components._base import Component


class ApplicantLoaderComponent(Component):
    display_name = "Applicant Loader"
    description = "Load and normalize applicant spreadsheet rows."
    name = "ApplicantLoaderComponent"

    def run_model(self, applicant_path: str) -> dict:
        bundle = SpreadsheetLoader(project_root=Path(__file__).resolve().parents[2]).load(applicant_path)
        return {
            "source_path": str(bundle.source_path),
            "records": [record.canonical for record in bundle.records],
            "resolved_columns": bundle.resolved_columns,
            "warnings": bundle.warnings,
        }
