"""Run the verification job through the Langflow component chain."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import Iterable

from src.db.models import ExportBundle, RunJobRequest
from src.db.sqlite_store import SQLiteStore
from src.extraction.evidence_models import EvidenceResult
from src.langflow_components.applicant_loader import ApplicantLoaderComponent
from src.langflow_components.export_component import ExportWriterComponent
from src.langflow_components.first_pass_signals_component import FirstPassSignalsComponent
from src.langflow_components.ocr_component import OCRRouterComponent
from src.langflow_components.pdf_fetch_component import PDFFetchComponent
from src.llm.ollama_client import OllamaClient
from src.orchestration.result_builder import (
    applicant_context,
    candidate_claims,
    candidate_failure_result,
    candidate_result,
    summary,
)
from src.services.review_queue import ReviewQueueService
from src.settings import AppConfig


class LangflowFirstPassRunner:
    flow_name = "ePlacement Evidence Verification"
    node_order = [
        "Applicant Loader",
        "PDF Fetch",
        "OCR Router",
        "Evidence Signals",
        "Export Writer",
    ]

    def __init__(self, settings: AppConfig, store: SQLiteStore, llm_client: OllamaClient) -> None:
        self.settings = settings
        self.store = store
        self.loader_node = ApplicantLoaderComponent(project_root=Path(__file__).resolve().parents[2])
        self.fetch_node = PDFFetchComponent(settings)
        self.ocr_node = OCRRouterComponent(settings)
        self.signals_node = FirstPassSignalsComponent(settings, llm_client)
        self.export_node = ExportWriterComponent(settings, project_root=Path(__file__).resolve().parents[2])
        self.review_queue = ReviewQueueService(store)

    def execute_job(
        self,
        job_id: str,
        request: RunJobRequest,
        include_applicant_ids: Iterable[str] | None = None,
    ) -> ExportBundle | None:
        bundle = self.loader_node.load_bundle(request.applicant_path)
        selected_ids = set(include_applicant_ids or [])
        records = [record for record in bundle.records if not selected_ids or record.applicant_id in selected_ids]
        counters: Counter = Counter()
        evidence_results: list[EvidenceResult] = []
        downloaded_count = 0
        ocr_docs = 0
        direct_text_docs = 0

        self.store.update_job(job_id, status="RUNNING", progress_total=len(records), progress_completed=0, counters={})
        self.store.log_event(job_id, "INFO", "Running Langflow-first orchestration", {"flow_name": self.flow_name, "node_order": self.node_order})
        for warning in bundle.warnings:
            self.store.log_event(job_id, "WARNING", warning)
        if bundle.missing_required:
            message = f"Cannot process spreadsheet because required columns are missing: {', '.join(bundle.missing_required)}"
            self.store.update_job(job_id, status="FAILED", latest_error=message)
            self.store.log_event(job_id, "ERROR", message)
            return None

        pdf_directory = request.pdf_directory or str(self.settings.paths.pdf_dir)

        for completed, record in enumerate(records, start=1):
            started = perf_counter()
            try:
                context = applicant_context(record)
                claims = candidate_claims(record.canonical)
                fetch_result = self.fetch_node.fetch_pdf(record.canonical, pdf_directory, request.auto_download)
                pdf_path = Path(fetch_result["path"]) if fetch_result.get("path") else None
                if pdf_path is not None:
                    downloaded_count += int(bool(fetch_result.get("downloaded", False)))
                if pdf_path is None:
                    has_claims = any(claims.values())
                    failure_status = "DOWNLOAD_FAILED" if has_claims and fetch_result.get("error") else "DOCUMENT_MISSING" if has_claims else "CONFIRMED"
                    failure_reason = (
                        fetch_result.get("error")
                        or fetch_result.get("message")
                        or ("Supporting document not found." if has_claims else "No claimed evidence and no supporting PDF was required.")
                    )
                    result = candidate_failure_result(
                        job_id=job_id,
                        record=record,
                        status=failure_status,
                        reason=failure_reason,
                        download_url=fetch_result.get("url"),
                    )
                    evidence_results.append(result)
                    self.store.save_evidence_result(result)
                    counters[result.final_status] += 1
                    self.store.log_event(job_id, "INFO", f"No PDF available for applicant {record.applicant_id}")
                    self.store.update_job(job_id, progress_completed=completed, counters=dict(counters))
                    continue

                ocr_document = self.ocr_node.process_document(record.applicant_id, str(pdf_path))
                first_pass_signals = self.signals_node.scan_document(ocr_document, context)
                engines = set(ocr_document.metadata.get("engines", []))
                if engines == {"direct_text"}:
                    direct_text_docs += 1
                else:
                    ocr_docs += 1

                if not ocr_document.combined_text and not ocr_document.page_image_paths:
                    has_claims = any(claims.values())
                    result = candidate_failure_result(
                        job_id=job_id,
                        record=record,
                        status="OCR_FAILED" if has_claims else "CONFIRMED",
                        reason="OCR pipeline did not extract usable text or page images from the PDF." if has_claims else "No claimed evidence and OCR output was not needed for this row.",
                        download_url=fetch_result.get("url"),
                    )
                    result.source_pdf_name = pdf_path.name
                    result.source_pdf_path = str(pdf_path)
                    result.audit_payload["first_pass_signals"] = first_pass_signals.model_dump(mode="json")
                    evidence_results.append(result)
                    self.store.save_evidence_result(result)
                    counters[result.final_status] += 1
                    self.store.log_event(job_id, "WARNING", f"OCR failed for applicant {record.applicant_id}")
                    self.store.update_job(job_id, progress_completed=completed, counters=dict(counters))
                    continue

                assessment_result = candidate_result(
                    job_id=job_id,
                    record=record,
                    pdf_path=pdf_path,
                    ocr_document=ocr_document,
                    first_pass_signals=first_pass_signals,
                    processing_time_seconds=perf_counter() - started,
                )
                evidence_results.append(assessment_result)
                self.store.save_evidence_result(assessment_result)
                counters[assessment_result.final_status] += 1

                self.store.log_event(
                    job_id,
                    "INFO",
                    f"Processed applicant {record.applicant_id} through first-pass candidate flow",
                    {
                        "download_status": fetch_result.get("status"),
                        "pdf_path": str(pdf_path),
                        "detected_primary_signal": assessment_result.audit_payload.get("detected_primary_signal"),
                        "claims": assessment_result.audit_payload.get("claims"),
                        "first_pass_signals": first_pass_signals.model_dump(mode="json"),
                    },
                )
            except Exception as exc:  # noqa: BLE001
                result = candidate_failure_result(
                    job_id=job_id,
                    record=record,
                    status="OCR_FAILED",
                    reason=str(exc),
                    download_url=record.canonical.get("pdf_url"),
                )
                evidence_results.append(result)
                self.store.save_evidence_result(result)
                counters[result.final_status] += 1
                self.store.log_event(job_id, "ERROR", f"Langflow chain failed for applicant {record.applicant_id}", {"error": str(exc)})
            finally:
                self.store.update_job(job_id, progress_completed=completed, counters=dict(counters))

        summary_rows = summary(bundle, evidence_results, downloaded_count, ocr_docs, direct_text_docs)
        review_rows = self.review_queue.list_records(job_id=job_id)
        export_bundle = self.export_node.write_exports(job_id, request.applicant_path, evidence_results, review_rows, summary_rows)
        self.store.save_exports(export_bundle)
        self.store.update_job(job_id, status="COMPLETED", counters=dict(counters))
        self.store.log_event(job_id, "INFO", "Langflow-first job completed", {"exports": export_bundle.model_dump(mode="json")})
        return export_bundle
