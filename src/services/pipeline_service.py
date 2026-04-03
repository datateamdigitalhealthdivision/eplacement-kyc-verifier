"""Facade service used by FastAPI, Streamlit, and scripts."""

from __future__ import annotations

import threading
from pathlib import Path

from src.db.models import OverrideRequest, RetryFailedRequest, RunJobRequest
from src.db.sqlite_store import SQLiteStore
from src.llm.ollama_client import OllamaClient
from src.orchestration.langflow_first_pass import LangflowFirstPassRunner
from src.services.healthcheck import HealthcheckService
from src.services.review_queue import ReviewQueueService
from src.settings import load_app_config


class PipelineService:
    def __init__(self, project_root: str | Path | None = None) -> None:
        root = Path(project_root) if project_root else Path.cwd()
        self.settings = load_app_config(project_root=root)
        self.store = SQLiteStore(self.settings.paths.db_path)
        self.llm_client = OllamaClient(self.settings)
        self.flow_runner = LangflowFirstPassRunner(self.settings, self.store, self.llm_client)
        self.review_queue = ReviewQueueService(self.store)
        self.healthcheck = HealthcheckService(self.settings, self.store, self.llm_client)
        self._threads: dict[str, threading.Thread] = {}

    def _record_job_failure(self, job_id: str, exc: Exception) -> str:
        message = str(exc) or exc.__class__.__name__
        self.store.update_job(job_id, status="FAILED", latest_error=message)
        self.store.log_event(job_id, "ERROR", message)
        return message

    def _run_job_background(
        self,
        job_id: str,
        request: RunJobRequest,
        include_applicant_ids: set[str] | None = None,
    ) -> None:
        try:
            self.flow_runner.execute_job(job_id, request, include_applicant_ids)
        except Exception as exc:  # noqa: BLE001
            self._record_job_failure(job_id, exc)

    def run_job(self, request: RunJobRequest, background: bool = False):
        pdf_directory = request.pdf_directory or str(self.settings.paths.pdf_dir)
        job = self.store.create_job(
            applicant_source=request.applicant_path,
            pdf_directory=pdf_directory,
            config_snapshot=self.settings.model_dump(mode="json"),
        )
        if background:
            thread = threading.Thread(target=self._run_job_background, args=(job.job_id, request), daemon=True)
            thread.start()
            self._threads[job.job_id] = thread
            return self.store.get_job(job.job_id)
        try:
            self.flow_runner.execute_job(job.job_id, request)
        except Exception as exc:  # noqa: BLE001
            self._record_job_failure(job.job_id, exc)
            raise
        return self.store.get_job(job.job_id)

    def retry_failed(self, request: RetryFailedRequest | None = None, background: bool = False):
        latest, failed_ids = self.store.failed_applicant_ids_for_latest_job()
        if latest is None:
            raise ValueError("No previous job available to retry.")
        applicant_path = request.applicant_path if request and request.applicant_path else latest.applicant_source
        pdf_directory = request.pdf_directory if request and request.pdf_directory else latest.pdf_directory
        job = self.store.create_job(
            applicant_source=applicant_path,
            pdf_directory=pdf_directory,
            config_snapshot=self.settings.model_dump(mode="json"),
        )
        run_request = RunJobRequest(applicant_path=applicant_path, pdf_directory=pdf_directory, auto_download=True, retry_failed_only=True)
        if background:
            thread = threading.Thread(
                target=self._run_job_background,
                args=(job.job_id, run_request, failed_ids),
                daemon=True,
            )
            thread.start()
            self._threads[job.job_id] = thread
            return self.store.get_job(job.job_id)
        try:
            self.flow_runner.execute_job(job.job_id, run_request, failed_ids)
        except Exception as exc:  # noqa: BLE001
            self._record_job_failure(job.job_id, exc)
            raise
        return self.store.get_job(job.job_id)

    def get_job(self, job_id: str):
        return self.store.get_job(job_id)

    def get_logs(self, job_id: str):
        return self.store.get_logs(job_id)

    def list_review_records(self, job_id: str | None = None, status: str | None = None, document_type: str | None = None, reason_contains: str | None = None):
        return self.review_queue.list_records(job_id=job_id, status=status, document_type=document_type, reason_contains=reason_contains)

    def override_review(self, record_id: int, override: OverrideRequest):
        return self.store.apply_override(record_id, override.override_status, override.reviewer_note)

    def latest_exports(self, job_id: str | None = None):
        return self.store.latest_exports(job_id)

    def health(self):
        return self.healthcheck.run()
