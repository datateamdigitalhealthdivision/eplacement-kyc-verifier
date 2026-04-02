"""SQLite persistence for jobs, events, evidence rows, and export pointers."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from src.db.models import ExportBundle, JobEvent, JobRecord, ReviewRecord
from src.extraction.evidence_models import EvidenceResult


class SQLiteStore:
    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    applicant_source TEXT NOT NULL,
                    pdf_directory TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    progress_total INTEGER NOT NULL DEFAULT 0,
                    progress_completed INTEGER NOT NULL DEFAULT 0,
                    counters_json TEXT NOT NULL,
                    config_snapshot_json TEXT NOT NULL,
                    latest_error TEXT
                );

                CREATE TABLE IF NOT EXISTS job_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    level TEXT NOT NULL,
                    message TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evidence_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    applicant_id TEXT NOT NULL,
                    document_type TEXT NOT NULL,
                    evidence_type TEXT NOT NULL,
                    final_status TEXT NOT NULL,
                    manual_review_flag INTEGER NOT NULL,
                    source_pdf_path TEXT,
                    final_reason TEXT NOT NULL,
                    override_status TEXT,
                    override_note TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS exports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

    def create_job(self, applicant_source: str, pdf_directory: str, config_snapshot: dict) -> JobRecord:
        now = datetime.utcnow().isoformat()
        job = JobRecord(
            job_id=str(uuid4()),
            status="QUEUED",
            applicant_source=applicant_source,
            pdf_directory=pdf_directory,
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
            progress_total=0,
            progress_completed=0,
            counters={},
            config_snapshot=config_snapshot,
            latest_error=None,
        )
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO jobs (
                    job_id, status, applicant_source, pdf_directory, created_at, updated_at,
                    progress_total, progress_completed, counters_json, config_snapshot_json, latest_error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job.job_id,
                    job.status,
                    job.applicant_source,
                    job.pdf_directory,
                    now,
                    now,
                    0,
                    0,
                    json.dumps(job.counters),
                    json.dumps(job.config_snapshot),
                    job.latest_error,
                ),
            )
        return job

    def update_job(
        self,
        job_id: str,
        *,
        status: str | None = None,
        progress_total: int | None = None,
        progress_completed: int | None = None,
        counters: dict | None = None,
        latest_error: str | None = None,
    ) -> None:
        current = self.get_job(job_id)
        if current is None:
            return
        payload = {
            "status": status or current.status,
            "progress_total": current.progress_total if progress_total is None else progress_total,
            "progress_completed": current.progress_completed if progress_completed is None else progress_completed,
            "counters_json": json.dumps(current.counters if counters is None else counters),
            "latest_error": latest_error if latest_error is not None else current.latest_error,
            "updated_at": datetime.utcnow().isoformat(),
        }
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE jobs
                SET status = ?, progress_total = ?, progress_completed = ?, counters_json = ?, latest_error = ?, updated_at = ?
                WHERE job_id = ?
                """,
                (
                    payload["status"],
                    payload["progress_total"],
                    payload["progress_completed"],
                    payload["counters_json"],
                    payload["latest_error"],
                    payload["updated_at"],
                    job_id,
                ),
            )

    def get_job(self, job_id: str) -> JobRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        if row is None:
            return None
        return JobRecord(
            job_id=row["job_id"],
            status=row["status"],
            applicant_source=row["applicant_source"],
            pdf_directory=row["pdf_directory"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            progress_total=row["progress_total"],
            progress_completed=row["progress_completed"],
            counters=json.loads(row["counters_json"]),
            config_snapshot=json.loads(row["config_snapshot_json"]),
            latest_error=row["latest_error"],
        )

    def latest_job(self) -> JobRecord | None:
        with self._connect() as connection:
            row = connection.execute("SELECT job_id FROM jobs ORDER BY created_at DESC LIMIT 1").fetchone()
        return self.get_job(row["job_id"]) if row else None

    def log_event(self, job_id: str, level: str, message: str, payload: dict | None = None) -> None:
        event = JobEvent(job_id=job_id, level=level, message=message, payload=payload or {})
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO job_events (job_id, level, message, payload_json, created_at) VALUES (?, ?, ?, ?, ?)",
                (job_id, level, message, json.dumps(event.payload), event.created_at.isoformat()),
            )

    def get_logs(self, job_id: str) -> list[JobEvent]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT job_id, level, message, payload_json, created_at FROM job_events WHERE job_id = ? ORDER BY id ASC",
                (job_id,),
            ).fetchall()
        return [
            JobEvent(
                job_id=row["job_id"],
                level=row["level"],
                message=row["message"],
                payload=json.loads(row["payload_json"]),
                created_at=datetime.fromisoformat(row["created_at"]),
            )
            for row in rows
        ]

    def save_evidence_result(self, result: EvidenceResult) -> int:
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO evidence_results (
                    job_id, applicant_id, document_type, evidence_type, final_status, manual_review_flag,
                    source_pdf_path, final_reason, override_status, override_note, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.job_id,
                    result.applicant_id,
                    result.document_type,
                    result.evidence_type,
                    result.final_status,
                    int(result.manual_review_flag),
                    result.source_pdf_path,
                    result.final_reason,
                    result.override_status,
                    result.override_note,
                    result.model_dump_json(),
                    result.created_at.isoformat(),
                ),
            )
            return int(cursor.lastrowid)

    def list_evidence_results(self, job_id: str | None = None) -> list[EvidenceResult]:
        query = "SELECT payload_json FROM evidence_results"
        params: tuple = ()
        if job_id:
            query += " WHERE job_id = ?"
            params = (job_id,)
        query += " ORDER BY id ASC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [EvidenceResult.model_validate_json(row["payload_json"]) for row in rows]

    def list_review_records(self, job_id: str | None = None) -> list[ReviewRecord]:
        query = (
            "SELECT id, job_id, final_status, manual_review_flag, final_reason, source_pdf_path, payload_json, override_status, override_note "
            "FROM evidence_results WHERE (manual_review_flag = 1 OR final_status IN "
            "('MANUAL_REVIEW_REQUIRED', 'DOCUMENT_MISSING', 'OCR_FAILED', 'DOWNLOAD_FAILED', 'UNSUPPORTED_DOCUMENT_TYPE', 'NOT_EVIDENCED_OR_INCONSISTENT'))"
        )
        params: tuple = ()
        if job_id:
            query += " AND job_id = ?"
            params = (job_id,)
        query += " ORDER BY id ASC"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        review_rows: list[ReviewRecord] = []
        for row in rows:
            payload = EvidenceResult.model_validate_json(row["payload_json"])
            review_rows.append(
                ReviewRecord(
                    record_id=row["id"],
                    job_id=row["job_id"],
                    applicant_id=payload.applicant_id,
                    document_type=payload.document_type,
                    final_status=row["override_status"] or row["final_status"],
                    manual_review_flag=bool(row["manual_review_flag"]),
                    reason=row["final_reason"],
                    result_kind=payload.audit_payload.get("result_kind"),
                    source_pdf_path=row["source_pdf_path"],
                    extracted_json=payload.audit_payload.get("evidence", {}),
                    audit_json=payload.audit_payload,
                    ocr_text_preview="\n".join(payload.snippets[:3]),
                    override_status=row["override_status"],
                    override_note=row["override_note"],
                )
            )
        return review_rows

    def apply_override(self, record_id: int, override_status: str, reviewer_note: str | None = None) -> ReviewRecord | None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE evidence_results SET override_status = ?, override_note = ? WHERE id = ?",
                (override_status, reviewer_note, record_id),
            )
            row = connection.execute(
                "SELECT job_id FROM evidence_results WHERE id = ?",
                (record_id,),
            ).fetchone()
        if row is None:
            return None
        reviews = self.list_review_records(row["job_id"])
        return next((record for record in reviews if record.record_id == record_id), None)

    def save_exports(self, bundle: ExportBundle) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO exports (job_id, payload_json, created_at) VALUES (?, ?, ?)",
                (bundle.job_id, bundle.model_dump_json(), datetime.utcnow().isoformat()),
            )

    def latest_exports(self, job_id: str | None = None) -> ExportBundle | None:
        query = "SELECT payload_json FROM exports"
        params: tuple = ()
        if job_id:
            query += " WHERE job_id = ?"
            params = (job_id,)
        query += " ORDER BY id DESC LIMIT 1"
        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        return ExportBundle.model_validate_json(row["payload_json"]) if row else None

    def failed_applicant_ids_for_latest_job(self) -> tuple[JobRecord | None, set[str]]:
        latest = self.latest_job()
        if latest is None:
            return None, set()
        failed_statuses = {
            "MANUAL_REVIEW_REQUIRED",
            "DOCUMENT_MISSING",
            "OCR_FAILED",
            "DOWNLOAD_FAILED",
            "UNSUPPORTED_DOCUMENT_TYPE",
            "NOT_EVIDENCED_OR_INCONSISTENT",
        }
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT applicant_id FROM evidence_results WHERE job_id = ? AND final_status IN (?, ?, ?, ?, ?, ?)",
                (latest.job_id, *failed_statuses),
            ).fetchall()
        return latest, {row["applicant_id"] for row in rows}


