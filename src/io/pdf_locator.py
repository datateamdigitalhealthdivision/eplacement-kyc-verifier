"""Find PDFs for an applicant row based on mapping and default naming."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from src.io.spreadsheet_loader import ApplicantRecord
from src.utils.paths import safe_filename


@dataclass(slots=True)
class LocatedPDF:
    path: Path | None
    source: str
    status: str
    attempted_names: list[str]
    message: str = ""


class PDFLocator:
    def __init__(self, pdf_directories: Iterable[str | Path]) -> None:
        self.pdf_directories = [Path(directory) for directory in pdf_directories if directory]

    @staticmethod
    def _is_blank(value: str | None) -> bool:
        if value is None:
            return True
        lowered = value.strip().casefold()
        return lowered in {"", "tiada maklumat", "nan", "none"}

    def candidate_names(self, record: ApplicantRecord) -> list[str]:
        explicit_name = str(record.canonical.get("pdf_filename", "") or "").strip()
        candidates: list[str] = []
        if not self._is_blank(explicit_name):
            candidates.append(safe_filename(explicit_name))
        applicant_id = str(record.applicant_id).strip()
        if applicant_id:
            candidates.append(f"{applicant_id}.pdf")
        return list(dict.fromkeys(candidates))

    def locate(self, record: ApplicantRecord) -> LocatedPDF:
        attempts = self.candidate_names(record)
        for directory in self.pdf_directories:
            for candidate in attempts:
                path = directory / candidate
                if path.exists():
                    return LocatedPDF(path=path, source=str(directory), status="FOUND", attempted_names=attempts)
        return LocatedPDF(path=None, source="", status="MISSING", attempted_names=attempts, message="No matching PDF found.")
