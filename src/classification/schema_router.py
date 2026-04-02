"""Route document types to extraction schemas and rule modules."""

from __future__ import annotations

from pathlib import Path

from src.settings import load_yaml_config


class SchemaRouter:
    def __init__(self, project_root: str | Path | None = None) -> None:
        self.config = load_yaml_config("document_schemas.yaml", project_root=project_root)

    def schema_name(self, doc_type: str) -> str:
        spec = self.config.get("document_types", {}).get(doc_type, {})
        return spec.get("extraction_schema", "generic_evidence")

    def rule_name(self, doc_type: str) -> str:
        spec = self.config.get("document_types", {}).get(doc_type, {})
        return spec.get("validation_rule", "generic")
