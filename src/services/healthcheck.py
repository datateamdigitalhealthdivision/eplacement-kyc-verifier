"""Local health checks for the backend, Langflow, Ollama, and disk usage."""

from __future__ import annotations

import shutil

import requests

from src.db.sqlite_store import SQLiteStore
from src.llm.ollama_client import OllamaClient
from src.settings import AppConfig


class HealthcheckService:
    def __init__(self, settings: AppConfig, store: SQLiteStore, llm_client: OllamaClient) -> None:
        self.settings = settings
        self.store = store
        self.llm_client = llm_client

    def run(self) -> dict:
        ollama = self.llm_client.health()
        langflow = {"ok": False, "detail": "Langflow disabled in config."}
        if self.settings.langflow.enabled:
            try:
                response = requests.get(self.settings.langflow.base_url, timeout=5)
                langflow = {"ok": response.ok, "detail": response.status_code}
            except Exception as exc:  # noqa: BLE001
                langflow = {"ok": False, "detail": str(exc)}
        disk = shutil.disk_usage(self.settings.paths.cache_dir)
        latest_job = self.store.latest_job()
        return {
            "ollama": ollama,
            "langflow": langflow,
            "disk": {
                "total_bytes": disk.total,
                "used_bytes": disk.used,
                "free_bytes": disk.free,
            },
            "database_path": str(self.settings.paths.db_path),
            "latest_job": latest_job.model_dump(mode="json") if latest_job else None,
        }
