"""Run a single verification job from the command line."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.models import RunJobRequest
from src.services.pipeline_service import PipelineService


def main() -> int:
    parser = argparse.ArgumentParser(description="Run one ePlacement KYC verification batch.")
    parser.add_argument("applicant_path", help="Path to the applicant spreadsheet.")
    parser.add_argument("--pdf-directory", default="", help="Optional PDF directory override.")
    parser.add_argument("--no-auto-download", action="store_true", help="Disable URL-based PDF downloading.")
    args = parser.parse_args()

    service = PipelineService(project_root=PROJECT_ROOT)
    request = RunJobRequest(
        applicant_path=str(Path(args.applicant_path).resolve()),
        pdf_directory=args.pdf_directory or str(service.settings.paths.pdf_dir),
        auto_download=not args.no_auto_download,
    )
    job = service.run_job(request, background=False)
    print("JOB_ID", job.job_id, flush=True)
    print("STATUS", job.status, flush=True)
    exports = service.latest_exports(job.job_id)
    if exports is not None:
        print("DECISION_CSV", exports.decision_csv, flush=True)
        print("DECISION_XLSX", exports.decision_xlsx, flush=True)
        print("SCORING_CSV", exports.scoring_csv, flush=True)
        print("SCORING_XLSX", exports.scoring_xlsx, flush=True)
        print("MERGED_CSV", exports.merged_csv, flush=True)
        print("SUMMARY_JSON", exports.summary_json, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
