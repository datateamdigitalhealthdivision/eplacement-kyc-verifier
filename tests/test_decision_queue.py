from datetime import datetime

import pandas as pd

from src.extraction.evidence_models import EvidenceResult
from src.reports.decision_queue import build_decision_queue


TICK = "\u2713"


def test_decision_queue_prefers_original_source_url() -> None:
    merged = pd.DataFrame(
        [
            {
                "KYC_APPLICANT_ID_NORMALIZED": "950101145678",
                "KYC_FIRSTPASS_MARRIAGE": "present",
                "KYC_FIRSTPASS_SELF_ILLNESS": "not_present",
                "KYC_FIRSTPASS_FAMILY_ILLNESS": "not_present",
                "KYC_FIRSTPASS_SPOUSE_LOCATION": "not_present",
                "KYC_FIRSTPASS_OKU_SELF_OR_FAMILY": "not_present",
                "KYC_FIRSTPASS_MEDEX_OR_OTHER_EXAM": "present",
            }
        ]
    )
    evidence_rows = [
        EvidenceResult(
            job_id="job-1",
            applicant_id="950101145678",
            row_index=0,
            document_type="medex_or_exam_document",
            evidence_type="medex",
            final_status="CONFIRMED",
            final_reason="ok",
            source_pdf_name="950101145678.pdf",
            download_url="https://example.com/950101145678.pdf",
            audit_payload={"result_kind": "observed_document"},
            created_at=datetime.utcnow(),
        )
    ]

    decision_df = build_decision_queue(merged, evidence_rows)

    assert decision_df.loc[0, "medex_other_exam"] == TICK
    assert decision_df.loc[0, "marriage"] == TICK
    assert decision_df.loc[0, "marriage_status"] == "present"
    assert decision_df.loc[0, "check_required"] == "no_check"
    assert decision_df.loc[0, "original_pdf_url"] == "https://example.com/950101145678.pdf"
    assert decision_df.loc[0, "open_original_pdf"] == "https://example.com/950101145678.pdf"
    assert decision_df.loc[0, "source_pdf_name"] == "950101145678.pdf"


def test_decision_queue_builds_s3_url_from_filename_when_missing() -> None:
    merged = pd.DataFrame(
        [
            {
                "KYC_APPLICANT_ID_NORMALIZED": "950510055140",
                "KYC_FIRSTPASS_MARRIAGE": "present",
                "KYC_FIRSTPASS_SELF_ILLNESS": "not_present",
                "KYC_FIRSTPASS_FAMILY_ILLNESS": "not_present",
                "KYC_FIRSTPASS_SPOUSE_LOCATION": "not_present",
                "KYC_FIRSTPASS_OKU_SELF_OR_FAMILY": "not_present",
                "KYC_FIRSTPASS_MEDEX_OR_OTHER_EXAM": "not_present",
            }
        ]
    )
    evidence_rows = [
        EvidenceResult(
            job_id="job-1",
            applicant_id="950510055140",
            row_index=0,
            document_type="marriage_certificate",
            evidence_type="marriage",
            final_status="MANUAL_REVIEW_REQUIRED",
            final_reason="Applicant IC on the document conflicts with the spreadsheet row.",
            source_pdf_name="950510055140.pdf",
            download_url="",
            audit_payload={"result_kind": "observed_document"},
            created_at=datetime.utcnow(),
        )
    ]

    decision_df = build_decision_queue(merged, evidence_rows)

    assert decision_df.loc[0, "marriage"] == TICK
    assert decision_df.loc[0, "check_required"] == "no_check"
    assert decision_df.loc[0, "original_pdf_url"] == "https://eplacement-2.s3.ap-southeast-5.amazonaws.com/950510055140.pdf"


def test_decision_queue_uses_manual_check_only_for_ambiguous_signal() -> None:
    merged = pd.DataFrame(
        [
            {
                "KYC_APPLICANT_ID_NORMALIZED": "960102135327",
                "KYC_FIRSTPASS_MARRIAGE": "present",
                "KYC_FIRSTPASS_SELF_ILLNESS": "manual_check",
                "KYC_FIRSTPASS_FAMILY_ILLNESS": "not_present",
                "KYC_FIRSTPASS_SPOUSE_LOCATION": "not_present",
                "KYC_FIRSTPASS_OKU_SELF_OR_FAMILY": "not_present",
                "KYC_FIRSTPASS_MEDEX_OR_OTHER_EXAM": "not_present",
            }
        ]
    )
    evidence_rows = [
        EvidenceResult(
            job_id="job-1",
            applicant_id="960102135327",
            row_index=0,
            document_type="other_supporting_document",
            evidence_type="generic",
            final_status="MANUAL_REVIEW_REQUIRED",
            final_reason="Mixed bundle.",
            source_pdf_name="960102135327.pdf",
            download_url="",
            audit_payload={"result_kind": "observed_document"},
            created_at=datetime.utcnow(),
        )
    ]

    decision_df = build_decision_queue(merged, evidence_rows)

    assert decision_df.loc[0, "self_illness"] == ""
    assert decision_df.loc[0, "self_illness_status"] == "manual_check"
    assert decision_df.loc[0, "check_required"] == "no_check"
    assert decision_df.loc[0, "original_pdf_url"] == "https://eplacement-2.s3.ap-southeast-5.amazonaws.com/960102135327.pdf"


def test_decision_queue_checks_when_claimed_signals_remain_missing_after_second_pass() -> None:
    merged = pd.DataFrame(
        [
            {
                "KYC_APPLICANT_ID_NORMALIZED": "960831106534",
                "MARITAL_STATUS": "BERKAHWIN",
                "POSTGRADUATE_PAPER_STATUS": "Peperiksaan Kemasukan/MedEX/GCFM",
                "Alamat Bekerja Pasangan": "Cyberjaya",
                "KYC_FIRSTPASS_MARRIAGE": "not_present",
                "KYC_FIRSTPASS_SELF_ILLNESS": "not_present",
                "KYC_FIRSTPASS_FAMILY_ILLNESS": "not_present",
                "KYC_FIRSTPASS_SPOUSE_LOCATION": "not_present",
                "KYC_FIRSTPASS_OKU_SELF_OR_FAMILY": "not_present",
                "KYC_FIRSTPASS_MEDEX_OR_OTHER_EXAM": "not_present",
                "ATTACHMENT": "https://d3j85m1nd79zoa.cloudfront.net/960831106534.pdf",
            }
        ]
    )

    decision_df = build_decision_queue(merged, [])

    assert decision_df.loc[0, "check_required"] == "check"
    assert decision_df.loc[0, "original_pdf_url"] == "https://d3j85m1nd79zoa.cloudfront.net/960831106534.pdf"


def test_decision_queue_keeps_no_check_for_blank_non_claim_row() -> None:
    merged = pd.DataFrame(
        [
            {
                "KYC_APPLICANT_ID_NORMALIZED": "950331075322",
                "MARITAL_STATUS": "BUJANG",
                "POSTGRADUATE_PAPER_STATUS": "Tidak Berkenaan",
                "PERSONAL_HEALTH_CONDITION": "Tiada",
                "StatusOKU": "Tiada",
                "KYC_FIRSTPASS_MARRIAGE": "not_present",
                "KYC_FIRSTPASS_SELF_ILLNESS": "not_present",
                "KYC_FIRSTPASS_FAMILY_ILLNESS": "not_present",
                "KYC_FIRSTPASS_SPOUSE_LOCATION": "not_present",
                "KYC_FIRSTPASS_OKU_SELF_OR_FAMILY": "not_present",
                "KYC_FIRSTPASS_MEDEX_OR_OTHER_EXAM": "not_present",
            }
        ]
    )

    decision_df = build_decision_queue(merged, [])

    assert decision_df.loc[0, "check_required"] == "no_check"
    assert decision_df.loc[0, "summary"] == "No target evidence detected."


def test_decision_queue_checks_gross_partial_mismatch() -> None:
    merged = pd.DataFrame(
        [
            {
                "KYC_APPLICANT_ID_NORMALIZED": "950213146361",
                "MARITAL_STATUS": "BERKAHWIN",
                "POSTGRADUATE_PAPER_STATUS": "Peperiksaan Kemasukan/MedEX/GCFM",
                "Alamat Bekerja Pasangan": "Kota Kinabalu",
                "KYC_FIRSTPASS_MARRIAGE": "present",
                "KYC_FIRSTPASS_SELF_ILLNESS": "not_present",
                "KYC_FIRSTPASS_FAMILY_ILLNESS": "not_present",
                "KYC_FIRSTPASS_SPOUSE_LOCATION": "present",
                "KYC_FIRSTPASS_OKU_SELF_OR_FAMILY": "not_present",
                "KYC_FIRSTPASS_MEDEX_OR_OTHER_EXAM": "not_present",
                "ATTACHMENT": "https://d3j85m1nd79zoa.cloudfront.net/950213146361.pdf",
            }
        ]
    )

    decision_df = build_decision_queue(merged, [])

    assert decision_df.loc[0, "check_required"] == "check"
    assert "Detected marriage, spouse location, but missing claimed MedEX/other exam." in decision_df.loc[0, "summary"]
