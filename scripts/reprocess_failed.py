"""Retry failed applicants from the latest recorded job."""

from __future__ import annotations

import argparse
from pathlib import Path

from src.db.models import RetryFailedRequest
from src.services.pipeline_service import PipelineService


def main() -> None:
    parser = argparse.ArgumentParser(description="Retry failed applicants from the latest job.")
    parser.add_argument("--applicant-path", default=None)
    parser.add_argument("--pdf-directory", default=None)
    args = parser.parse_args()

    service = PipelineService(project_root=Path(__file__).resolve().parents[1])
    job = service.retry_failed(
        RetryFailedRequest(applicant_path=args.applicant_path, pdf_directory=args.pdf_directory),
        background=False,
    )
    print(f"Retried failed applicants in job {job.job_id}")
    exports = service.latest_exports(job.job_id)
    if exports:
        print(exports.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
