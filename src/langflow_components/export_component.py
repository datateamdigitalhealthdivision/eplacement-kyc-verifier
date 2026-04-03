"""Langflow component that writes evidence, merged, review, and summary outputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.db.models import ExportBundle
from src.extraction.evidence_models import EvidenceResult
from src.io.exporters import ExportWriter
from src.io.spreadsheet_loader import SpreadsheetLoader
from src.langflow_components._base import Component
from src.rules.merge_back import merge_results_back
from src.settings import AppConfig, load_app_config


class ExportWriterComponent(Component):
    display_name = "Export Writer"
    description = "Write validation, merged, review, and summary output files."
    name = "ExportWriterComponent"

    def __init__(self, settings: AppConfig | None = None, project_root: Path | None = None, **kwargs):
        super().__init__(**kwargs)
        root = project_root or Path(__file__).resolve().parents[2]
        self.project_root = root
        self.settings = settings or load_app_config(project_root=root)
        self.loader = SpreadsheetLoader(project_root=root)
        self.writer = ExportWriter(self.settings)

    def write_exports(self, job_id: str, applicant_path: str, evidence_rows: list[EvidenceResult | dict], review_rows: list[Any], summary_rows: list[dict]) -> ExportBundle:
        bundle = self.loader.load(applicant_path)
        results = [row if isinstance(row, EvidenceResult) else EvidenceResult.model_validate(row) for row in evidence_rows]
        merged = merge_results_back(bundle.original_df, bundle.canonical_df, results)
        return self.writer.write_outputs(job_id, results, merged, review_rows, summary_rows)

    def run_model(self, job_id: str, applicant_path: str, evidence_rows: list[dict], review_rows: list[dict], summary_rows: list[dict]) -> dict:
        exports = self.write_exports(job_id, applicant_path, evidence_rows, review_rows, summary_rows)
        return exports.model_dump(mode="json")
