from datetime import UTC, datetime

from src.db.sqlite_store import SQLiteStore
from src.extraction.evidence_models import EvidenceResult
from src.services.review_queue import ReviewQueueService


def test_review_queue_includes_claim_cross_check_rows(tmp_path) -> None:
    store = SQLiteStore(tmp_path / 'kyc.sqlite3')
    service = ReviewQueueService(store)
    result = EvidenceResult(
        job_id='job-1',
        applicant_id='950101145678',
        row_index=0,
        document_type='marriage_certificate',
        evidence_type='marriage',
        final_status='NOT_EVIDENCED_OR_INCONSISTENT',
        final_reason="Uploaded document was tagged as 'other supporting document', not 'marriage certificate'.",
        manual_review_flag=False,
        audit_payload={
            'result_kind': 'claim_cross_check',
            'decision': {
                'expected_document_type': 'marriage_certificate',
                'observed_document_type': 'other_supporting_document',
            },
        },
        created_at=datetime.now(UTC),
    )
    store.save_evidence_result(result)

    records = service.list_records(job_id='job-1')

    assert len(records) == 1
    assert records[0].review_category == 'wrong_document_type_uploaded'
    assert records[0].expected_document_type == 'marriage_certificate'
    assert records[0].observed_document_type == 'other_supporting_document'
    assert records[0].result_kind == 'claim_cross_check'


def test_review_queue_job_filter_does_not_leak_other_jobs(tmp_path) -> None:
    store = SQLiteStore(tmp_path / 'kyc.sqlite3')
    service = ReviewQueueService(store)
    first = EvidenceResult(
        job_id='job-1',
        applicant_id='111',
        row_index=0,
        document_type='marriage_certificate',
        evidence_type='marriage',
        final_status='MANUAL_REVIEW_REQUIRED',
        final_reason='Marriage certificate supports part of the claim but needs manual review.',
        manual_review_flag=True,
        audit_payload={'result_kind': 'observed_document'},
        created_at=datetime.now(UTC),
    )
    second = EvidenceResult(
        job_id='job-2',
        applicant_id='222',
        row_index=0,
        document_type='medex_or_exam_document',
        evidence_type='medex',
        final_status='MANUAL_REVIEW_REQUIRED',
        final_reason='Exam evidence is partially supported but requires manual review.',
        manual_review_flag=True,
        audit_payload={'result_kind': 'observed_document'},
        created_at=datetime.now(UTC),
    )
    store.save_evidence_result(first)
    store.save_evidence_result(second)

    records = service.list_records(job_id='job-1')

    assert len(records) == 1
    assert records[0].job_id == 'job-1'
    assert records[0].applicant_id == '111'


def test_review_queue_labels_identity_mismatch_rows(tmp_path) -> None:
    store = SQLiteStore(tmp_path / 'kyc.sqlite3')
    service = ReviewQueueService(store)
    result = EvidenceResult(
        job_id='job-2',
        applicant_id='960713145778',
        row_index=0,
        document_type='marriage_certificate',
        evidence_type='marriage',
        final_status='NOT_EVIDENCED_OR_INCONSISTENT',
        final_reason='Applicant IC on the document conflicts with the spreadsheet row. | Spouse name on the document does not align with the spreadsheet row.',
        manual_review_flag=True,
        audit_payload={'result_kind': 'observed_document'},
        created_at=datetime.now(UTC),
    )
    store.save_evidence_result(result)

    records = service.list_records(job_id='job-2')

    assert len(records) == 1
    assert records[0].review_category == 'document_belongs_to_other_person'
    assert records[0].observed_document_type == 'marriage_certificate'
    assert records[0].triage_note == 'Observed marriage certificate, but extracted identity does not match the spreadsheet.'
