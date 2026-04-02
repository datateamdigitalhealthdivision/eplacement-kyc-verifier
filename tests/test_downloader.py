from pathlib import Path

from src.io.downloader import Downloader


class DummyResponse:
    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int = 65536):
        yield self.payload


def test_downloader_downloads_and_caches(tmp_path: Path, monkeypatch) -> None:
    downloader = Downloader(timeout_seconds=5)
    monkeypatch.setattr(downloader.session, "get", lambda *args, **kwargs: DummyResponse(b"pdf"))
    result = downloader.download("https://example.com/test.pdf", tmp_path, "sample.pdf")
    assert result.status == "DOWNLOADED"
    assert result.path is not None and result.path.exists()

    cached = downloader.download("https://example.com/test.pdf", tmp_path, "sample.pdf")
    assert cached.status == "CACHED"
