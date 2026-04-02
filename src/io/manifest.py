"""JSON manifest for downloaded files and cache lookups."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.utils.file_locking import file_lock


class ManifestStore:
    def __init__(self, manifest_path: str | Path) -> None:
        self.manifest_path = Path(manifest_path)
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.manifest_path.exists():
            self.manifest_path.write_text("{}\n", encoding="utf-8")

    def _read(self) -> dict[str, Any]:
        return json.loads(self.manifest_path.read_text(encoding="utf-8"))

    def get(self, key: str, default: Any = None) -> Any:
        return self._read().get(key, default)

    def upsert(self, key: str, value: dict[str, Any]) -> None:
        lock_path = self.manifest_path.with_suffix(self.manifest_path.suffix + ".lock")
        with file_lock(lock_path):
            payload = self._read()
            payload[key] = value
            self.manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")
