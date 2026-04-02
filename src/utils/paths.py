"""Path resolution helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


def ensure_directories(paths: Iterable[Path]) -> None:
    for path in paths:
        path.mkdir(parents=True, exist_ok=True)


def project_root_from(start: Path) -> Path:
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    return current


def safe_filename(name: str, default: str = "document.pdf") -> str:
    cleaned = "".join(character if character.isalnum() or character in "._-" else "_" for character in name.strip())
    cleaned = cleaned.strip("._")
    return cleaned or default
