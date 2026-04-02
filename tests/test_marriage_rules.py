from datetime import UTC, datetime

from src.extraction.evidence_models import MarriageEvidence, OCRDocument, OCRPage
from src.rules.marriage_rules import validate_marriage


def _document() -> OCRDocument:
    return OCRDocument(
        applicant_id="950101145678",
        document_path="sample.pdf",
        document_hash="hash",
        processing_hash="proc",
        pages=[OCRPage(page_number=1, extracted_text="Marriage certificate text", engine_used="direct_text", confidence=0.95)],
        combined_text="Marriage certificate text",
        extracted_at=datetime.now(UTC),
    )


def test_marriage_rules_exact_match() -> None:
    row = {
        "applicant_id": "950101145678",
        "applicant_name": "NURUL HANANI",
        "marital_status": "BERKAHWIN",
        "spouse_name": "NOOR AIN BINTI AHMAD",
        "spouse_id": "900202085432",
    }
    evidence = MarriageEvidence(
        applicant_name_from_doc="Nurul Hanani",
        applicant_ic_from_doc="950101145678",
        spouse_name_from_doc="Noor Ain Binti Ahmad",
        spouse_ic_from_doc="900202085432",
        key_supporting_snippets=["SURAT PERAKUAN NIKAH"],
        page_refs=[1],
        extraction_confidence=0.95,
    )
    decision = validate_marriage(row, evidence, _document())
    assert decision.final_status == "CONFIRMED"


def test_marriage_rules_ambiguous_match() -> None:
    row = {
        "applicant_id": "950101145678",
        "applicant_name": "NURUL HANANI",
        "marital_status": "BERKAHWIN",
        "spouse_name": "NOOR AIN BINTI AHMAD",
        "spouse_id": "900202085432",
    }
    evidence = MarriageEvidence(
        applicant_name_from_doc="Nurul Hanani",
        spouse_name_from_doc="Noor Ain",
        key_supporting_snippets=["SURAT PERAKUAN NIKAH"],
        page_refs=[1],
        extraction_confidence=0.7,
    )
    document = _document()
    document.pages[0].confidence = 0.65
    decision = validate_marriage(row, evidence, document)
    assert decision.final_status == "MANUAL_REVIEW_REQUIRED"


def test_marriage_rules_ignores_lossy_spouse_identifier_when_name_matches() -> None:
    row = {
        "applicant_id": "950101145678",
        "applicant_name": "NURUL HANANI",
        "marital_status": "BERKAHWIN",
        "spouse_name": "NOOR AIN BINTI AHMAD",
        "spouse_id": "9.00202E+11",
    }
    evidence = MarriageEvidence(
        applicant_name_from_doc="Nurul Hanani",
        applicant_ic_from_doc="950101145678",
        spouse_name_from_doc="Noor Ain Binti Ahmad",
        spouse_ic_from_doc="900202085432",
        key_supporting_snippets=["SURAT PERAKUAN NIKAH"],
        page_refs=[1],
        extraction_confidence=0.95,
    )
    decision = validate_marriage(row, evidence, _document())
    assert decision.final_status == "CONFIRMED"
