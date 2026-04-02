"""FastAPI application entrypoint."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
import uvicorn

from src.api.routes_exports import router as exports_router
from src.api.routes_health import router as health_router
from src.api.routes_jobs import router as jobs_router
from src.api.routes_review import router as review_router
from src.settings import load_app_config


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS = load_app_config(project_root=PROJECT_ROOT)
ALLOWED_FILE_ROOTS = [
    SETTINGS.paths.pdf_dir,
    SETTINGS.paths.downloads_dir,
]


app = FastAPI(title="ePlacement KYC Verifier", version="0.1.0")
app.include_router(jobs_router)
app.include_router(review_router)
app.include_router(exports_router)
app.include_router(health_router)


@app.get("/")
def root() -> dict:
    return {"service": "eplacement-kyc-verifier", "status": "ok"}


@app.get("/files/open")
def open_local_file(path: str = Query(..., description="Absolute path to a local file inside the configured PDF roots.")):
    try:
        resolved = Path(path).expanduser().resolve(strict=True)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File not found.") from exc
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found.")
    if not any(root.exists() and resolved.is_relative_to(root.resolve()) for root in ALLOWED_FILE_ROOTS):
        raise HTTPException(status_code=403, detail="File path is outside the allowed document folders.")
    return FileResponse(resolved)


def run() -> None:
    uvicorn.run("src.api.main:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    run()
