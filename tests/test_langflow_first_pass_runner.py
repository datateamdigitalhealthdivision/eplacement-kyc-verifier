from pathlib import Path

import pandas as pd

from src.db.models import RunJobRequest
from src.db.sqlite_store import SQLiteStore
from src.llm.ollama_client import OllamaClient
from src.orchestration.langflow_first_pass import LangflowFirstPassRunner
from tests.helpers import make_test_settings, write_pdf


def test_langflow_first_pass_runner_smoke_run(tmp_path: Path) -> None:
    settings = make_test_settings(tmp_path)
    pdf_dir = settings.paths.pdf_dir
    pdf_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = pdf_dir / "950101145678.pdf"
    write_pdf(
        pdf_path,
        [
            "SURAT PERAKUAN NIKAH",
            "NAMA SUAMI: NURUL HANANI",
            "NO KP SUAMI: 950101145678",
            "NAMA ISTERI: NOOR AIN BINTI AHMAD",
            "NO KP ISTERI: 900202085432",
            "NOMBOR DAFTAR: ABC123",
        ],
    )
    applicant_csv = settings.paths.applicants_dir / "applicants.csv"
    applicant_csv.write_text(
        "NO KP,applicant_name,MARITAL_STATUS,Nama Pasangan,NoKPPasangan,POSTGRADUATE_PAPER_STATUS,Sheet1.NamaFail\n"
        "950101145678,NURUL HANANI,BERKAHWIN,NOOR AIN BINTI AHMAD,900202085432,Tidak Berkenaan,950101145678.pdf\n",
        encoding="utf-8",
    )

    store = SQLiteStore(settings.paths.db_path)
    runner = LangflowFirstPassRunner(settings, store, OllamaClient(settings))
    job = store.create_job(str(applicant_csv), str(pdf_dir), settings.model_dump(mode="json"))
    exports = runner.execute_job(
        job.job_id,
        RunJobRequest(applicant_path=str(applicant_csv), pdf_directory=str(pdf_dir), auto_download=False),
    )

    assert exports is not None
    validation_df = pd.read_csv(exports.validation_csv)
    assert "CONFIRMED" in set(validation_df["final_status"])
    merged_df = pd.read_csv(exports.merged_csv)
    assert merged_df.loc[0, "KYC_UPLOADED_DOC_TYPE"] == "marriage_certificate"
    assert merged_df.loc[0, "KYC_UPLOADED_DOC_STATUS"] == "CONFIRMED"
    assert merged_df.loc[0, "KYC_MARRIAGE_STATUS"] == "CONFIRMED"
