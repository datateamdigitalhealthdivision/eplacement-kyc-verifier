from pathlib import Path

from src.extraction.evidence_models import OCRDocument, OCRPage
from src.extraction.first_pass_signals import FirstPassEvidenceScanner
from tests.helpers import make_test_settings


PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\x0b\xb5\x1d\x00\x00\x00\x00IEND\xaeB`\x82"
)


class FakeVisionClient:
    def __init__(self, vision_responses: list[str], text_response: str) -> None:
        self.vision_responses = vision_responses
        self.text_response = text_response
        self.vision_calls = 0
        self.text_calls = 0

    def is_vision_enabled(self) -> bool:
        return True

    def vision_model_name(self) -> str:
        return "fake-vision"

    def is_enabled(self) -> bool:
        return True

    def text_model_name(self) -> str:
        return "fake-text"

    def generate_vision(self, prompt: str, image_paths: list[str | Path], model: str | None = None) -> str:
        response = self.vision_responses[self.vision_calls]
        self.vision_calls += 1
        return response

    def generate(self, prompt: str, model: str | None = None) -> str:
        self.text_calls += 1
        return self.text_response


def test_first_pass_scanner_aggregates_across_image_chunks(tmp_path: Path) -> None:
    settings = make_test_settings(tmp_path)
    settings.ollama.vision_max_images = 1

    image_paths = []
    for index in range(2):
        image_path = tmp_path / f"page_{index + 1}.png"
        image_path.write_bytes(PNG_BYTES)
        image_paths.append(str(image_path))

    document = OCRDocument(
        applicant_id="930620115062",
        document_path=str(tmp_path / "930620115062.pdf"),
        document_hash="doc-hash",
        processing_hash="proc-hash",
        pages=[
            OCRPage(page_number=1, extracted_text="", engine_used="vision"),
            OCRPage(page_number=2, extracted_text="", engine_used="vision"),
        ],
        page_image_paths=image_paths,
        combined_text="",
        warnings=[],
        metadata={},
    )

    client = FakeVisionClient(
        [
            '{"marriage":"present","self_illness":"present","family_illness":"not_present","spouse_location":"not_present","oku_self_or_family":"not_present","medex_or_other_exam":"not_present","reasons":["Marriage certificate visible","Medical follow-up visible"]}',
            '{"marriage":"not_present","self_illness":"not_present","family_illness":"manual_check","spouse_location":"present","oku_self_or_family":"not_present","medex_or_other_exam":"not_present","reasons":["Possible family illness","Placement letter visible"]}',
        ],
        '{"marriage":"present","self_illness":"present","family_illness":"manual_check","spouse_location":"present","oku_self_or_family":"not_present","medex_or_other_exam":"not_present","reasons":["Bundle summary confirms the signals"]}',
    )

    scanner = FirstPassEvidenceScanner(settings, client)
    result = scanner.scan(document)

    assert result.marriage == "present"
    assert result.self_illness == "present"
    assert result.family_illness == "not_present"
    assert result.spouse_location == "present"
    assert result.oku_self_or_family == "not_present"
    assert result.medex_or_other_exam == "not_present"
    assert result.raw_payload["_method"] == "ollama_vision"
    assert len(result.raw_payload["chunks"]) == 2
    assert result.raw_payload["overview"]["_method"] == "ollama_text_overview"
    assert client.text_calls == 1


def test_first_pass_scanner_requires_repeated_manual_signals(tmp_path: Path) -> None:
    settings = make_test_settings(tmp_path)
    settings.ollama.vision_max_images = 1

    image_paths = []
    for index in range(2):
        image_path = tmp_path / f"manual_page_{index + 1}.png"
        image_path.write_bytes(PNG_BYTES)
        image_paths.append(str(image_path))

    document = OCRDocument(
        applicant_id="950213146361",
        document_path=str(tmp_path / "950213146361.pdf"),
        document_hash="manual-doc-hash",
        processing_hash="manual-proc-hash",
        pages=[
            OCRPage(page_number=1, extracted_text="", engine_used="vision"),
            OCRPage(page_number=2, extracted_text="", engine_used="vision"),
        ],
        page_image_paths=image_paths,
        combined_text="",
        warnings=[],
        metadata={},
    )

    client = FakeVisionClient(
        [
            '{"marriage":"not_present","self_illness":"not_present","family_illness":"manual_check","spouse_location":"not_present","oku_self_or_family":"not_present","medex_or_other_exam":"not_present","reasons":["Possible family illness"]}',
            '{"marriage":"not_present","self_illness":"not_present","family_illness":"not_present","spouse_location":"not_present","oku_self_or_family":"not_present","medex_or_other_exam":"not_present","reasons":["Generic page"]}',
        ],
        '{"marriage":"not_present","self_illness":"not_present","family_illness":"not_present","spouse_location":"not_present","oku_self_or_family":"not_present","medex_or_other_exam":"not_present","reasons":[]}',
    )

    scanner = FirstPassEvidenceScanner(settings, client)
    result = scanner.scan(document)

    assert result.family_illness == "not_present"


def test_first_pass_scanner_filters_routine_physical_exam_from_medex(tmp_path: Path) -> None:
    settings = make_test_settings(tmp_path)
    settings.ollama.vision_max_images = 1

    image_path = tmp_path / "exam_page_1.png"
    image_path.write_bytes(PNG_BYTES)

    document = OCRDocument(
        applicant_id="930620115062",
        document_path=str(tmp_path / "930620115062.pdf"),
        document_hash="exam-doc-hash",
        processing_hash="exam-proc-hash",
        pages=[OCRPage(page_number=1, extracted_text="", engine_used="vision")],
        page_image_paths=[str(image_path)],
        combined_text="",
        warnings=[],
        metadata={},
    )

    client = FakeVisionClient(
        [
            '{"marriage":"not_present","self_illness":"not_present","family_illness":"not_present","spouse_location":"not_present","oku_self_or_family":"not_present","medex_or_other_exam":"present","reasons":["The document is a physical examination report with vital signs."]}',
        ],
        '{"marriage":"not_present","self_illness":"not_present","family_illness":"not_present","spouse_location":"not_present","oku_self_or_family":"not_present","medex_or_other_exam":"not_present","reasons":[]}',
    )

    scanner = FirstPassEvidenceScanner(settings, client)
    result = scanner.scan(document)

    assert result.medex_or_other_exam == "not_present"
