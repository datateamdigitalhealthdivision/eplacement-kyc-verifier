from datetime import UTC, datetime

from src.extraction.evidence_models import MedexEvidence, OCRDocument, OCRPage
from src.rules.medex_rules import validate_medex


def _document() -> OCRDocument:
    return OCRDocument(
        applicant_id="950101145678",
        document_path="medex.pdf",
        document_hash="hash",
        processing_hash="proc",
        pages=[OCRPage(page_number=1, extracted_text="MedEX Keputusan", engine_used="direct_text", confidence=0.98)],
        combined_text="MedEX Keputusan",
        extracted_at=datetime.now(UTC),
    )


def test_medex_rules_confirmed() -> None:
    row = {
        "applicant_id": "950101145678",
        "applicant_name": "NURUL HANANI",
        "postgraduate_status": "Peperiksaan Kemasukan/MedEX/GCFM",
    }
    evidence = MedexEvidence(
        candidate_name_from_doc="Nurul Hanani",
        candidate_ic_from_doc="950101145678",
        exam_name="MedEX",
        exam_status_or_result="Lulus",
        key_supporting_snippets=["MedEX Keputusan"],
        page_refs=[1],
        extraction_confidence=0.92,
    )
    decision = validate_medex(row, evidence, _document())
    assert decision.final_status == "CONFIRMED"


def test_medex_rules_does_not_penalize_missing_applicant_name() -> None:
    row = {
        "applicant_id": "950101145678",
        "applicant_name": "",
        "postgraduate_status": "Peperiksaan Kemasukan/MedEX/GCFM",
    }
    evidence = MedexEvidence(
        candidate_name_from_doc="Completely Different Name",
        candidate_ic_from_doc="950101145678",
        exam_name="MedEX",
        exam_status_or_result="Lulus",
        key_supporting_snippets=["MedEX Keputusan"],
        page_refs=[1],
        extraction_confidence=0.92,
    )
    decision = validate_medex(row, evidence, _document())
    assert decision.final_status == "CONFIRMED"
