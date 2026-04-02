"""Configuration loading utilities for the KYC verifier."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any
import os

import yaml
from pydantic import BaseModel, Field

from src.utils.paths import ensure_directories, project_root_from


class AppSection(BaseModel):
    name: str = "eplacement-kyc-verifier"
    timezone: str = "Asia/Kuala_Lumpur"
    debug: bool = False


class PathsSection(BaseModel):
    applicants_dir: Path
    pdf_dir: Path
    sample_dir: Path
    downloads_dir: Path
    extracted_text_dir: Path
    page_images_dir: Path
    ocr_json_dir: Path
    llm_json_dir: Path
    cache_dir: Path
    db_path: Path
    reports_dir: Path
    merged_dir: Path
    review_dir: Path
    logs_dir: Path


class OllamaSection(BaseModel):
    host: str = "http://localhost:11434"
    model: str = "qwen2.5:7b-instruct"
    image_model: str = "qwen2.5vl:7b"
    vision_enabled: bool = True
    vision_max_images: int = 3
    timeout_seconds: int = 120
    enabled: bool = True


class LangflowSection(BaseModel):
    base_url: str = "http://localhost:7860"
    enabled: bool = True


class BatchSection(BaseModel):
    concurrency: int = 2
    retry_count: int = 2
    auto_download: bool = True
    chunk_size: int = 25


class OCRSection(BaseModel):
    dpi: int = 225
    direct_text_min_chars: int = 40
    direct_text_min_alpha_ratio: float = 0.18
    low_confidence_threshold: float = 0.7
    tesseract_languages: str = "eng+msa+ara"
    language_hints: list[str] = Field(default_factory=lambda: ["eng", "msa", "ara"])
    use_paddle_fallback: bool = True
    retain_raw_text: bool = True


class PrivacySection(BaseModel):
    redact_logs: bool = True
    retain_raw_ocr_text: bool = True


class LoggingSection(BaseModel):
    level: str = "INFO"


class AppConfig(BaseModel):
    app: AppSection
    paths: PathsSection
    ollama: OllamaSection
    langflow: LangflowSection
    batch: BatchSection
    ocr: OCRSection
    privacy: PrivacySection
    logging: LoggingSection

    def materialize_paths(self, root_dir: Path) -> "AppConfig":
        resolved: dict[str, Path] = {}
        for key, value in self.paths.model_dump().items():
            path_value = Path(value)
            resolved[key] = path_value if path_value.is_absolute() else root_dir / path_value
        self.paths = PathsSection(**resolved)
        ensure_directories(
            [
                self.paths.applicants_dir,
                self.paths.pdf_dir,
                self.paths.sample_dir,
                self.paths.downloads_dir,
                self.paths.extracted_text_dir,
                self.paths.page_images_dir,
                self.paths.ocr_json_dir,
                self.paths.llm_json_dir,
                self.paths.cache_dir,
                self.paths.db_path.parent,
                self.paths.reports_dir,
                self.paths.merged_dir,
                self.paths.review_dir,
                self.paths.logs_dir,
            ]
        )
        return self


def _load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def _merge_env_overrides(config: dict[str, Any]) -> dict[str, Any]:
    if host := os.getenv("EPKYC_OLLAMA_HOST"):
        config.setdefault("ollama", {})["host"] = host
    if model := os.getenv("EPKYC_OLLAMA_MODEL"):
        config.setdefault("ollama", {})["model"] = model
    if image_model := os.getenv("EPKYC_OLLAMA_IMAGE_MODEL"):
        config.setdefault("ollama", {})["image_model"] = image_model
    if vision_enabled := os.getenv("EPKYC_OLLAMA_VISION_ENABLED"):
        config.setdefault("ollama", {})["vision_enabled"] = vision_enabled.casefold() in {"1", "true", "yes", "on"}
    if vision_max_images := os.getenv("EPKYC_OLLAMA_VISION_MAX_IMAGES"):
        try:
            config.setdefault("ollama", {})["vision_max_images"] = int(vision_max_images)
        except ValueError:
            pass
    if base_url := os.getenv("EPKYC_LANGFLOW_BASE_URL"):
        config.setdefault("langflow", {})["base_url"] = base_url
    if level := os.getenv("EPKYC_LOG_LEVEL"):
        config.setdefault("logging", {})["level"] = level
    return config


@lru_cache(maxsize=4)
def load_app_config(config_dir: str | Path | None = None, project_root: str | Path | None = None) -> AppConfig:
    root_dir = project_root_from(Path(project_root) if project_root else Path.cwd())
    config_path = root_dir / (Path(config_dir) if config_dir else Path("config")) / "app_config.yaml"
    merged = _merge_env_overrides(_load_yaml(config_path))
    return AppConfig.model_validate(merged).materialize_paths(root_dir)


@lru_cache(maxsize=8)
def load_yaml_config(name: str, config_dir: str | Path | None = None, project_root: str | Path | None = None) -> dict[str, Any]:
    root_dir = project_root_from(Path(project_root) if project_root else Path.cwd())
    directory = root_dir / (Path(config_dir) if config_dir else Path("config"))
    return _load_yaml(directory / name)
