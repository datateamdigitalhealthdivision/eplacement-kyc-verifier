"""Download helper for locally caching applicant PDF bundles."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from urllib.parse import urlparse

import requests
from requests.exceptions import SSLError

from src.utils.hashing import sha256_file
from src.utils.paths import safe_filename


@dataclass(slots=True)
class DownloadResult:
    status: str
    path: Path | None = None
    file_hash: str | None = None
    error: str | None = None
    downloaded: bool = False


class Downloader:
    def __init__(self, timeout_seconds: int = 60) -> None:
        self.timeout_seconds = timeout_seconds
        self.session = requests.Session()

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(f"Invalid download URL: {url}")

    @staticmethod
    def _should_try_windows_fallback(url: str, exc: Exception) -> bool:
        if os.name != "nt" or not url.lower().startswith("https://"):
            return False
        if isinstance(exc, SSLError):
            return True
        message = str(exc).lower()
        return any(
            marker in message
            for marker in (
                "certificate verify failed",
                "ssl",
                "tls",
                "revocation",
            )
        )

    def _download_with_requests(self, url: str, target: Path) -> DownloadResult:
        response = self.session.get(url, timeout=self.timeout_seconds, stream=True)
        response.raise_for_status()
        with target.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    handle.write(chunk)
        return DownloadResult(status="DOWNLOADED", path=target, file_hash=sha256_file(target), downloaded=True)

    def _download_with_windows_curl(self, url: str, target: Path) -> DownloadResult:
        command = [
            "curl.exe",
            "--silent",
            "--show-error",
            "--fail",
            "--location",
            "--ssl-no-revoke",
            "--connect-timeout",
            str(min(self.timeout_seconds, 30)),
            "--max-time",
            str(self.timeout_seconds),
            "--output",
            str(target),
            url,
        ]
        result = subprocess.run(command, capture_output=True, text=True, timeout=self.timeout_seconds + 5, check=False)
        if result.returncode != 0:
            message = result.stderr.strip() or result.stdout.strip() or f"curl.exe exited with code {result.returncode}"
            raise RuntimeError(message)
        return DownloadResult(status="DOWNLOADED", path=target, file_hash=sha256_file(target), downloaded=True)

    def download(self, url: str, destination_dir: str | Path, file_name: str | None = None) -> DownloadResult:
        self._validate_url(url)
        destination = Path(destination_dir)
        destination.mkdir(parents=True, exist_ok=True)
        candidate_name = safe_filename(file_name or Path(urlparse(url).path).name or "document.pdf")
        target = destination / candidate_name
        if target.exists():
            return DownloadResult(status="CACHED", path=target, file_hash=sha256_file(target), downloaded=False)
        try:
            return self._download_with_requests(url, target)
        except Exception as exc:  # noqa: BLE001
            if target.exists():
                target.unlink(missing_ok=True)
            if self._should_try_windows_fallback(url, exc):
                try:
                    return self._download_with_windows_curl(url, target)
                except Exception as fallback_exc:  # noqa: BLE001
                    if target.exists():
                        target.unlink(missing_ok=True)
                    combined_error = f"{exc} | Windows fallback failed: {fallback_exc}"
                    return DownloadResult(status="DOWNLOAD_FAILED", error=combined_error)
            return DownloadResult(status="DOWNLOAD_FAILED", error=str(exc))
