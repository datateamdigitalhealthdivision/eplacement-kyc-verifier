"""File-system OCR cache keyed by processing hash."""

from __future__ import annotations

import json
from pathlib import Path

from src.extraction.evidence_models import OCRDocument
from src.utils.file_locking import file_lock


class OCRCache:
    def __init__(self, cache_dir: str | Path) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, processing_hash: str) -> Path:
        return self.cache_dir / f"{processing_hash}.json"

    def load(self, processing_hash: str) -> OCRDocument | None:
        path = self.path_for(processing_hash)
        if not path.exists():
            return None
        return OCRDocument.model_validate(json.loads(path.read_text(encoding="utf-8")))

    def save(self, document: OCRDocument) -> None:
        path = self.path_for(document.processing_hash)
        lock_path = path.with_suffix(path.suffix + ".lock")
        with file_lock(lock_path):
            path.write_text(document.model_dump_json(indent=2) + "\n", encoding="utf-8")
