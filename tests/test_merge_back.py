from datetime import datetime

import pandas as pd

from src.extraction.evidence_models import EvidenceResult
from src.rules.merge_back import merge_results_back


def test_merge_back_adds_uploaded_document_columns() -> None:
    source = pd.DataFrame(
        [
            {
                "applicant_id": "950101145678",
                "marital_status": "BERKAHWIN",
                "postgraduate_status": "Tidak Berkenaan",
            }
        ]
    )
    canonical = source.copy()
    result = EvidenceResult(
        job_id="job-1",
        applicant_id="950101145678",
        row_index=0,
        document_type="marriage_certificate",
        evidence_type="marriage",
        final_status="CONFIRMED",
        final_reason="Marriage certificate supports applicant and spouse details.",
        manual_review_flag=False,
        audit_payload={
            "result_kind": "observed_document",
            "document_tags": {
                "primary_document_type": "marriage_certificate",
                "positive_tags": [
                    "marriage_certificate",
                    "marriage_related_document",
                    "marriage_evidence_detected",
                ],
                "marriage_certificate": True,
                "marriage_related_document": True,
                "medex_exam_document": False,
                "oku_document": False,
                "medical_document": False,
                "other_supporting_document": False,
                "marriage_evidence_detected": True,
                "medex_evidence_detected": False,
                "oku_evidence_detected": False,
            },
        },
        created_at=datetime.utcnow(),
    )

    merged = merge_results_back(source, canonical, [result])

    assert merged.loc[0, "KYC_APPLICANT_ID_NORMALIZED"] == "950101145678"
    assert merged.loc[0, "KYC_UPLOADED_DOC_TYPE"] == "marriage_certificate"
    assert merged.loc[0, "KYC_UPLOADED_DOC_STATUS"] == "CONFIRMED"
    assert bool(merged.loc[0, "KYC_DETECTED_MARRIAGE_CERTIFICATE"]) is True
    assert bool(merged.loc[0, "KYC_DETECTED_MARRIAGE_EVIDENCE"]) is True
    assert merged.loc[0, "KYC_MARRIAGE_STATUS"] == "CONFIRMED"
    assert merged.loc[0, "KYC_OVERALL_STATUS"] == "CONFIRMED"


def test_merge_back_marks_claim_mismatch_as_manual_review() -> None:
    source = pd.DataFrame(
        [
            {
                "applicant_id": "950101145678",
                "marital_status": "BERKAHWIN",
                "postgraduate_status": "Ya",
            }
        ]
    )
    canonical = source.copy()
    observed = EvidenceResult(
        job_id="job-1",
        applicant_id="950101145678",
        row_index=0,
        document_type="marriage_certificate",
        evidence_type="marriage",
        final_status="CONFIRMED",
        final_reason="Marriage certificate supports applicant and spouse details.",
        manual_review_flag=False,
        audit_payload={
            "result_kind": "observed_document",
            "document_tags": {
                "primary_document_type": "marriage_certificate",
                "positive_tags": [
                    "marriage_certificate",
                    "marriage_related_document",
                    "marriage_evidence_detected",
                ],
                "marriage_certificate": True,
                "marriage_related_document": True,
                "medex_exam_document": False,
                "oku_document": False,
                "medical_document": False,
                "other_supporting_document": False,
                "marriage_evidence_detected": True,
                "medex_evidence_detected": False,
                "oku_evidence_detected": False,
            },
        },
        created_at=datetime.utcnow(),
    )
    mismatch = EvidenceResult(
        job_id="job-1",
        applicant_id="950101145678",
        row_index=0,
        document_type="medex_or_exam_document",
        evidence_type="medex",
        final_status="NOT_EVIDENCED_OR_INCONSISTENT",
        final_reason="Uploaded document was tagged as a marriage certificate, not a MedEX or postgraduate document.",
        manual_review_flag=False,
        mismatched_fields=["document_type"],
        audit_payload={"result_kind": "claim_cross_check"},
        created_at=datetime.utcnow(),
    )

    merged = merge_results_back(source, canonical, [observed, mismatch])

    assert merged.loc[0, "KYC_UPLOADED_DOC_TYPE"] == "marriage_certificate"
    assert merged.loc[0, "KYC_MARRIAGE_STATUS"] == "CONFIRMED"
    assert bool(merged.loc[0, "KYC_DETECTED_MARRIAGE_EVIDENCE"]) is True
    assert bool(merged.loc[0, "KYC_DETECTED_MEDEX_EVIDENCE"]) is False
    assert merged.loc[0, "KYC_MEDEX_STATUS"] == "MANUAL_REVIEW_REQUIRED"
    assert bool(merged.loc[0, "KYC_MEDEX_REVIEW_REQUIRED"]) is True
    assert merged.loc[0, "KYC_OVERALL_STATUS"] == "MANUAL_REVIEW_REQUIRED"
    assert bool(merged.loc[0, "KYC_OVERALL_REVIEW_REQUIRED"]) is True
    assert bool(merged.loc[0, "KYC_NEEDS_MANUAL_REVIEW"]) is True

