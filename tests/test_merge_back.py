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
            "result_kind": "candidate_assessment",
            "detected_primary_signal": "marriage_certificate",
            "first_pass_signals": {
                "marriage": "present",
                "self_illness": "not_present",
                "family_illness": "manual_check",
                "spouse_location": "not_present",
                "oku_self_or_family": "not_present",
                "medex_or_other_exam": "not_present",
                "reasons": ["Marriage certificate visible", "Possible family illness evidence"],
            },
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
    assert merged.loc[0, "KYC_FIRSTPASS_MARRIAGE"] == "present"
    assert merged.loc[0, "KYC_FIRSTPASS_FAMILY_ILLNESS"] == "manual_check"
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
    assessment = EvidenceResult(
        job_id="job-1",
        applicant_id="950101145678",
        row_index=0,
        document_type="marriage",
        evidence_type="bundle",
        final_status="MANUAL_REVIEW_REQUIRED",
        final_reason="Detected marriage evidence, but MedEX/other exam is still ambiguous after the second pass.",
        manual_review_flag=True,
        audit_payload={
            "result_kind": "candidate_assessment",
            "detected_primary_signal": "marriage",
            "first_pass_signals": {
                "marriage": "present",
                "self_illness": "not_present",
                "family_illness": "not_present",
                "spouse_location": "present",
                "oku_self_or_family": "not_present",
                "medex_or_other_exam": "manual_check",
                "reasons": ["Marriage certificate visible", "Placement letter visible", "Possible exam evidence"],
            },
            "final_signal_statuses": {
                "marriage": "present",
                "self_illness": "not_present",
                "family_illness": "not_present",
                "spouse_location": "present",
                "oku_self_or_family": "not_present",
                "medex_or_other_exam": "manual_check",
            },
        },
        created_at=datetime.utcnow(),
    )

    merged = merge_results_back(source, canonical, [assessment])

    assert merged.loc[0, "KYC_UPLOADED_DOC_TYPE"] == "marriage"
    assert merged.loc[0, "KYC_MARRIAGE_STATUS"] == "CONFIRMED"
    assert bool(merged.loc[0, "KYC_DETECTED_MARRIAGE_EVIDENCE"]) is True
    assert bool(merged.loc[0, "KYC_DETECTED_MEDEX_EVIDENCE"]) is True
    assert merged.loc[0, "KYC_FIRSTPASS_SPOUSE_LOCATION"] == "present"
    assert merged.loc[0, "KYC_FIRSTPASS_MEDEX_OR_OTHER_EXAM"] == "manual_check"
    assert merged.loc[0, "KYC_MEDEX_STATUS"] == "MANUAL_REVIEW_REQUIRED"
    assert bool(merged.loc[0, "KYC_MEDEX_REVIEW_REQUIRED"]) is True
    assert merged.loc[0, "KYC_OVERALL_STATUS"] == "MANUAL_REVIEW_REQUIRED"
    assert bool(merged.loc[0, "KYC_OVERALL_REVIEW_REQUIRED"]) is True
    assert bool(merged.loc[0, "KYC_NEEDS_MANUAL_REVIEW"]) is True
