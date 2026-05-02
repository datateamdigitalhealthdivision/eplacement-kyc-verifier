"""Run a verification job directly without Streamlit or FastAPI."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.models import RunJobRequest
from src.services.pipeline_service import PipelineService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a verifier job directly from the command line.")
    parser.add_argument("applicant_path", help="Path to the applicant spreadsheet.")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT), help="Project root directory.")
    parser.add_argument("--pdf-directory", default=None, help="PDF directory override.")
    parser.add_argument("--auto-download", action=argparse.BooleanOptionalAction, default=True, help="Download PDFs when missing locally.")
    parser.add_argument("--job-id-file", default=None, help="Optional file to write the created job id into immediately.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    project_root = Path(args.project_root).resolve()
    service = PipelineService(project_root=project_root)
    pdf_directory = args.pdf_directory or str(service.settings.paths.pdf_dir)
    request = RunJobRequest(
        applicant_path=str(Path(args.applicant_path).resolve()),
        pdf_directory=pdf_directory,
        auto_download=bool(args.auto_download),
    )
    job = service.store.create_job(
        applicant_source=request.applicant_path,
        pdf_directory=request.pdf_directory or str(service.settings.paths.pdf_dir),
        config_snapshot=service.settings.model_dump(mode="json"),
    )
    if args.job_id_file:
        Path(args.job_id_file).write_text(job.job_id, encoding="utf-8")
    print(job.job_id, flush=True)
    service.flow_runner.execute_job(job.job_id, request)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
