"""Langflow component that writes evidence, merged, review, and summary outputs."""

from __future__ import annotations

from pathlib import Path

from src.db.models import ExportBundle
from src.extraction.evidence_models import EvidenceResult
from src.io.exporters import ExportWriter
from src.io.spreadsheet_loader import SpreadsheetLoader
from src.langflow_components._base import Component
from src.rules.merge_back import merge_results_back
from src.settings import load_app_config


class ExportWriterComponent(Component):
    display_name = "Export Writer"
    description = "Write validation, merged, review, and summary output files."
    name = "ExportWriterComponent"

    def run_model(self, job_id: str, applicant_path: str, evidence_rows: list[dict], review_rows: list[dict], summary_rows: list[dict]) -> dict:
        project_root = Path(__file__).resolve().parents[2]
        settings = load_app_config(project_root=project_root)
        bundle = SpreadsheetLoader(project_root=project_root).load(applicant_path)
        results = [EvidenceResult.model_validate(row) for row in evidence_rows]
        merged = merge_results_back(bundle.original_df, bundle.canonical_df, results)
        exports: ExportBundle = ExportWriter(settings).write_outputs(job_id, results, merged, review_rows, summary_rows)
        return exports.model_dump(mode="json")
