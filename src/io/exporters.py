"""Export pipeline outputs to CSV, XLSX, and JSON artifacts."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from src.db.models import ExportBundle
from src.extraction.evidence_models import EvidenceResult
from src.reports.decision_queue import build_decision_queue
from src.settings import AppConfig


class ExportWriter:
    def __init__(self, settings: AppConfig) -> None:
        self.settings = settings

    def _table(self, records: list[Any]) -> pd.DataFrame:
        rows = [record.model_dump(mode="json") if hasattr(record, "model_dump") else record for record in records]
        return pd.DataFrame(rows)

    def write_outputs(
        self,
        job_id: str,
        evidence_rows: list[EvidenceResult],
        merged_df: pd.DataFrame,
        review_rows: list[Any],
        summary: list[dict[str, Any]],
    ) -> ExportBundle:
        reports_dir = self.settings.paths.reports_dir
        merged_dir = self.settings.paths.merged_dir
        review_dir = self.settings.paths.review_dir

        validation_df = self._table(evidence_rows)
        review_df = self._table(review_rows)
        summary_df = pd.DataFrame(summary)
        decision_df = build_decision_queue(merged_df, evidence_rows)

        validation_csv = reports_dir / f"validation_{job_id}.csv"
        validation_xlsx = reports_dir / f"validation_{job_id}.xlsx"
        merged_csv = merged_dir / f"merged_{job_id}.csv"
        merged_xlsx = merged_dir / f"merged_{job_id}.xlsx"
        review_csv = review_dir / f"review_queue_{job_id}.csv"
        review_xlsx = review_dir / f"review_queue_{job_id}.xlsx"
        decision_csv = review_dir / f"decision_queue_{job_id}.csv"
        decision_xlsx = review_dir / f"decision_queue_{job_id}.xlsx"
        summary_csv = reports_dir / f"summary_{job_id}.csv"
        summary_json = reports_dir / f"summary_{job_id}.json"

        validation_df.to_csv(validation_csv, index=False)
        validation_df.to_excel(validation_xlsx, index=False)
        merged_df.to_csv(merged_csv, index=False)
        merged_df.to_excel(merged_xlsx, index=False)
        review_df.to_csv(review_csv, index=False)
        review_df.to_excel(review_xlsx, index=False)
        decision_df.to_csv(decision_csv, index=False)
        decision_df.to_excel(decision_xlsx, index=False)
        summary_df.to_csv(summary_csv, index=False)
        summary_json.write_text(json.dumps(summary, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")

        return ExportBundle(
            job_id=job_id,
            validation_csv=str(validation_csv),
            validation_xlsx=str(validation_xlsx),
            merged_csv=str(merged_csv),
            merged_xlsx=str(merged_xlsx),
            review_csv=str(review_csv),
            review_xlsx=str(review_xlsx),
            summary_csv=str(summary_csv),
            summary_json=str(summary_json),
            decision_csv=str(decision_csv),
            decision_xlsx=str(decision_xlsx),
        )

    def write(
        self,
        job_id: str,
        evidence_rows: list[EvidenceResult],
        merged_df: pd.DataFrame,
        review_rows: list[Any],
        summary: list[dict[str, Any]],
    ) -> ExportBundle:
        return self.write_outputs(job_id, evidence_rows, merged_df, review_rows, summary)
