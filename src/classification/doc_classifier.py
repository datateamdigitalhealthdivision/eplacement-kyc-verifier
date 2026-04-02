"""Hybrid regex-first, LLM-second document classification."""

from __future__ import annotations

from src.classification.regex_signals import score_signals
from src.extraction.evidence_models import DocumentClassification
from src.llm.ollama_client import OllamaClient
from src.llm.parser import parse_model_response
from src.llm.prompts import classification_prompt
from src.llm.schemas import ClassificationSchema


class HybridDocClassifier:
    def __init__(self, llm_client: OllamaClient | None = None) -> None:
        self.llm_client = llm_client

    def can_use_vision(self, image_paths: list[str] | None = None) -> bool:
        return bool(self.llm_client and self.llm_client.is_vision_enabled() and image_paths)

    def classify(self, text: str, image_paths: list[str] | None = None) -> DocumentClassification:
        signals = score_signals(text)
        if signals:
            primary_type, matched = max(signals.items(), key=lambda item: len(item[1]))
            confidence = min(0.99, 0.45 + 0.15 * len(matched))
            return DocumentClassification(
                primary_type=primary_type,  # type: ignore[arg-type]
                candidate_types=list(signals.keys()),  # type: ignore[arg-type]
                confidence=confidence,
                method="regex",
                matched_signals=matched,
            )
        if self.can_use_vision(image_paths):
            try:
                response = self.llm_client.generate_vision(
                    classification_prompt(text, include_images=True),
                    image_paths=image_paths or [],
                )
                payload = parse_model_response(response, ClassificationSchema)
                return DocumentClassification(
                    primary_type=payload.doc_type,
                    candidate_types=[payload.doc_type],
                    confidence=payload.confidence,
                    method="ollama_vision",
                    matched_signals=payload.reasons,
                    llm_payload={
                        **payload.model_dump(mode="json"),
                        "_method": "ollama_vision",
                        "_model": self.llm_client.vision_model_name(),
                    },
                )
            except Exception:
                pass
        if self.llm_client and self.llm_client.is_enabled() and text:
            try:
                response = self.llm_client.generate(classification_prompt(text))
                payload = parse_model_response(response, ClassificationSchema)
                return DocumentClassification(
                    primary_type=payload.doc_type,
                    candidate_types=[payload.doc_type],
                    confidence=payload.confidence,
                    method="ollama_text",
                    matched_signals=payload.reasons,
                    llm_payload={
                        **payload.model_dump(mode="json"),
                        "_method": "ollama_text",
                        "_model": self.llm_client.text_model_name(),
                    },
                )
            except Exception:
                pass
        return DocumentClassification(primary_type="unknown", candidate_types=["unknown"], confidence=0.0, method="fallback")
