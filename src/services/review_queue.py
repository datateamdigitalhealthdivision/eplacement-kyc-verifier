"""Helper for filtering and shaping manual review queue output."""

from __future__ import annotations

from src.db.models import ReviewRecord
from src.db.sqlite_store import SQLiteStore


DOC_TYPE_LABELS = {
    "marriage_certificate": "marriage certificate",
    "medex_or_exam_document": "MedEX or postgraduate document",
    "other_supporting_document": "other supporting document",
    "unknown": "unidentified document",
}


class ReviewQueueService:
    def __init__(self, store: SQLiteStore) -> None:
        self.store = store

    @staticmethod
    def _doc_type_label(doc_type: str | None) -> str:
        if not doc_type:
            return "unavailable document type"
        return DOC_TYPE_LABELS.get(doc_type, doc_type.replace("_", " "))

    @classmethod
    def _annotate_record(cls, record: ReviewRecord) -> ReviewRecord:
        audit = record.audit_json or {}
        result_kind = record.result_kind or audit.get("result_kind")
        decision = audit.get("decision") if isinstance(audit.get("decision"), dict) else {}
        expected = None
        observed = None
        category = None
        triage_note = record.reason

        if result_kind == "claim_cross_check":
            expected = str(decision.get("expected_document_type") or record.document_type or "") or None
            observed = str(decision.get("observed_document_type") or "") or None
            category = "wrong_document_type_uploaded"
            triage_note = f"Observed {cls._doc_type_label(observed)}; expected {cls._doc_type_label(expected)}."
        elif result_kind == "missing_document":
            expected = record.document_type or None
            category = "missing_document"
            triage_note = f"No document found for expected {cls._doc_type_label(expected)}."
        else:
            observed = record.document_type or None
            if record.final_status in {"DOWNLOAD_FAILED", "OCR_FAILED"}:
                category = "processing_issue"
            elif "Document classified as other supporting document" in record.reason:
                category = "unsupported_supporting_document"
                triage_note = f"Observed {cls._doc_type_label(observed)}; route for manual review."
            elif "Spreadsheet applicant ID is not reliable enough" in record.reason:
                category = "spreadsheet_data_issue"
                triage_note = "Spreadsheet identity data is unreliable; compare the document manually."
            elif "even though the row does not claim it" in record.reason:
                category = "unexpected_evidence_uploaded"
                triage_note = f"Observed {cls._doc_type_label(observed)} even though the spreadsheet does not claim it."
            elif "conflicts with the spreadsheet row" in record.reason or "does not align with the spreadsheet row" in record.reason:
                category = "document_belongs_to_other_person"
                triage_note = f"Observed {cls._doc_type_label(observed)}, but extracted identity does not match the spreadsheet."
            elif "partially matches" in record.reason or "supports part of the claim" in record.reason or "requires manual review before a final decision" in record.reason:
                category = "partial_match_needs_review"
                triage_note = f"Observed {cls._doc_type_label(observed)} with partial support; manual verification needed."
            elif record.final_status == "DOCUMENT_MISSING":
                category = "missing_document"
                triage_note = f"No document found for expected {cls._doc_type_label(record.document_type)}."
            else:
                category = "manual_review_other"

        return record.model_copy(
            update={
                "result_kind": result_kind,
                "review_category": category,
                "triage_note": triage_note,
                "expected_document_type": expected,
                "observed_document_type": observed,
            }
        )

    def list_records(
        self,
        job_id: str | None = None,
        status: str | None = None,
        document_type: str | None = None,
        reason_contains: str | None = None,
    ) -> list[ReviewRecord]:
        records = [self._annotate_record(record) for record in self.store.list_review_records(job_id=job_id)]
        if status:
            records = [record for record in records if record.final_status == status]
        if document_type:
            records = [record for record in records if record.document_type == document_type]
        if reason_contains:
            needle = reason_contains.casefold()
            records = [record for record in records if needle in record.reason.casefold()]
        return records
