"""Local-only Ollama HTTP client."""

from __future__ import annotations

import base64
import re
from pathlib import Path
from typing import Any

import requests

from src.settings import AppConfig


class OllamaClient:
    def __init__(self, settings: AppConfig) -> None:
        self.settings = settings
        self.session = requests.Session()

    def is_enabled(self) -> bool:
        return self.settings.ollama.enabled

    def is_vision_enabled(self) -> bool:
        return self.is_enabled() and self.settings.ollama.vision_enabled and bool(self.settings.ollama.image_model)

    def text_model_name(self) -> str:
        return self.settings.ollama.model

    def vision_model_name(self) -> str:
        return self.settings.ollama.image_model

    @staticmethod
    def cache_slug(model_name: str) -> str:
        return re.sub(r"[^a-z0-9]+", "_", model_name.casefold()).strip("_") or "default"

    def health(self) -> dict[str, Any]:
        if not self.is_enabled():
            return {"ok": False, "detail": "Ollama disabled in config."}
        try:
            response = self.session.get(
                f"{self.settings.ollama.host.rstrip('/')}/api/tags",
                timeout=min(self.settings.ollama.timeout_seconds, 15),
            )
            response.raise_for_status()
            return {"ok": True, "detail": response.json()}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": str(exc)}

    def generate(self, prompt: str, model: str | None = None) -> str:
        response = self.session.post(
            f"{self.settings.ollama.host.rstrip('/')}/api/generate",
            json={
                "model": model or self.settings.ollama.model,
                "prompt": prompt,
                "format": "json",
                "stream": False,
                "options": {"temperature": 0},
            },
            timeout=self.settings.ollama.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        return str(payload.get("response", ""))

    def _select_image_paths(self, image_paths: list[str | Path]) -> list[Path]:
        existing = [Path(path) for path in image_paths if Path(path).exists()]
        limit = max(1, self.settings.ollama.vision_max_images)
        if len(existing) <= limit:
            return existing
        if limit == 1:
            return [existing[0]]
        if limit == 2:
            return [existing[0], existing[-1]]
        selected = existing[: limit - 1]
        selected.append(existing[-1])
        return selected

    @staticmethod
    def _encode_image(path: Path) -> str:
        return base64.b64encode(path.read_bytes()).decode("ascii")

    def generate_vision(self, prompt: str, image_paths: list[str | Path], model: str | None = None) -> str:
        selected_paths = self._select_image_paths(image_paths)
        if not selected_paths:
            raise ValueError("No page images available for multimodal Ollama call.")
        response = self.session.post(
            f"{self.settings.ollama.host.rstrip('/')}/api/chat",
            json={
                "model": model or self.settings.ollama.image_model,
                "format": "json",
                "messages": [
                    {
                        "role": "user",
                        "content": prompt,
                        "images": [self._encode_image(path) for path in selected_paths],
                    }
                ],
                "stream": False,
                "options": {"temperature": 0},
            },
            timeout=self.settings.ollama.timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        return str(payload.get("message", {}).get("content", ""))
