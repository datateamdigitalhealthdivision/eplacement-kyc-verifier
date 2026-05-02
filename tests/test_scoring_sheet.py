from pathlib import Path

import pandas as pd
from openpyxl import load_workbook

from src.reports.scoring_sheet import build_scoring_sheet, write_scoring_sheet_xlsx
from tests.helpers import make_test_settings


def test_build_scoring_sheet_includes_predicted_and_manual_columns(tmp_path: Path) -> None:
    settings = make_test_settings(tmp_path)
    decision_df = pd.DataFrame(
        [
            {
                "applicant_id": "930620115062",
                "source_pdf_name": "930620115062.pdf",
                "original_pdf_url": "https://example.com/930620115062.pdf",
                "open_original_pdf": "https://example.com/930620115062.pdf",
                "marriage_status": "present",
                "self_illness_status": "present",
                "family_illness_status": "not_present",
                "spouse_location_status": "manual_check",
                "oku_self_or_family_status": "not_present",
                "medex_other_exam_status": "not_present",
                "check_required": "check",
                "summary": "Marriage present. | Spouse location unclear.",
            }
        ]
    )

    scoring_df = build_scoring_sheet(decision_df, settings, "job-123")

    assert "pred_marriage" in scoring_df.columns
    assert "pred_medex_other_exam" in scoring_df.columns
    assert "claimed_marriage" in scoring_df.columns
    assert "proof_found_marriage" in scoring_df.columns
    assert "verified_marriage" in scoring_df.columns
    assert "missing_proof_marriage" in scoring_df.columns
    assert "supporting_page_marriage" in scoring_df.columns
    assert "evidence_summary_marriage" in scoring_df.columns
    assert "confidence_marriage" in scoring_df.columns
    assert "manual_marriage" in scoring_df.columns
    assert "manual_check_required" in scoring_df.columns
    assert "reviewer_notes" in scoring_df.columns
    assert scoring_df.iloc[0]["pred_marriage"] == "present"
    assert scoring_df.iloc[0]["pred_spouse_location"] == "manual_check"
    assert bool(scoring_df.iloc[0]["claimed_marriage"]) is False
    assert scoring_df.iloc[0]["manual_marriage"] == ""
    assert scoring_df.iloc[0]["manual_check_required"] == ""


def test_write_scoring_sheet_xlsx_adds_hyperlink_and_keeps_headers(tmp_path: Path) -> None:
    scoring_df = pd.DataFrame(
        [
            {
                "job_id": "job-123",
                "vision_model": "qwen2.5vl:7b",
                "secondary_vision_model": "gemma3:12b",
                "text_model": "qwen2.5:7b-instruct",
                "applicant_id": "930620115062",
                "source_pdf_name": "930620115062.pdf",
                "original_pdf_url": "https://example.com/930620115062.pdf",
                "open_original_pdf": "https://example.com/930620115062.pdf",
                "pred_marriage": "present",
                "pred_self_illness": "present",
                "pred_family_illness": "not_present",
                "pred_spouse_location": "present",
                "pred_oku_self_or_family": "not_present",
                "pred_medex_other_exam": "not_present",
                "pred_check_required": "no_check",
                "pred_summary": "Marriage present.",
                "manual_marriage": "",
                "manual_self_illness": "",
                "manual_family_illness": "",
                "manual_spouse_location": "",
                "manual_oku_self_or_family": "",
                "manual_medex_other_exam": "",
                "manual_check_required": "",
                "reviewer_notes": "",
            }
        ]
    )
    target = tmp_path / "scoring_sheet.xlsx"

    write_scoring_sheet_xlsx(scoring_df, target)

    workbook = load_workbook(target)
    sheet = workbook.active
    headers = [cell.value for cell in sheet[1]]
    assert "manual_check_required" in headers
    hyperlink_cell = sheet["H2"]
    assert hyperlink_cell.value == "Open PDF"
    assert hyperlink_cell.hyperlink.target == "https://example.com/930620115062.pdf"
