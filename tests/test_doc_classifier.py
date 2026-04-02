from src.classification.doc_classifier import HybridDocClassifier


class FakeVisionClient:
    def is_enabled(self) -> bool:
        return True

    def is_vision_enabled(self) -> bool:
        return True

    def text_model_name(self) -> str:
        return "qwen2.5:7b-instruct"

    def vision_model_name(self) -> str:
        return "qwen2.5vl:7b"

    def generate_vision(self, prompt: str, image_paths: list[str]) -> str:
        assert "OCR_TEXT" in prompt
        assert image_paths == ["page_0001.png"]
        return '{"doc_type": "other_supporting_document", "confidence": 0.88, "reasons": ["official form layout"]}'


def test_doc_classifier_regex_marriage() -> None:
    classifier = HybridDocClassifier(llm_client=None)
    result = classifier.classify("SURAT PERAKUAN NIKAH Nombor Daftar Tarikh Nikah")
    assert result.primary_type == "marriage_certificate"


def test_doc_classifier_regex_medex() -> None:
    classifier = HybridDocClassifier(llm_client=None)
    result = classifier.classify("MedEX Keputusan Candidate Examination Result")
    assert result.primary_type == "medex_or_exam_document"


def test_doc_classifier_uses_vision_when_images_are_available() -> None:
    classifier = HybridDocClassifier(llm_client=FakeVisionClient())
    result = classifier.classify("", image_paths=["page_0001.png"])
    assert result.primary_type == "other_supporting_document"
    assert result.method == "ollama_vision"
