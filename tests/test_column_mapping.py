from pathlib import Path

from src.io.spreadsheet_loader import SpreadsheetLoader


def test_column_mapping_resolution(tmp_path: Path) -> None:
    csv_path = tmp_path / "applicants.csv"
    csv_path.write_text(
        "NO KP,MARITAL_STATUS,Sheet1.NamaFail\n950101145678,BERKAHWIN,950101145678.pdf\n",
        encoding="utf-8",
    )
    loader = SpreadsheetLoader(project_root=Path(__file__).resolve().parents[1])
    bundle = loader.load(csv_path)
    assert bundle.resolved_columns["applicant_id"] == "NO KP"
    assert bundle.records[0].applicant_id == "950101145678"


def test_column_mapping_recovers_lossy_scientific_applicant_id_from_pdf_filename(tmp_path: Path) -> None:
    csv_path = tmp_path / "applicants.csv"
    csv_path.write_text(
        "NO KP,NoKPPasangan,Sheet1.NamaFail\n9.6043E+11,9.51216E+11,960430045398.pdf\n",
        encoding="utf-8",
    )
    loader = SpreadsheetLoader(project_root=Path(__file__).resolve().parents[1])
    bundle = loader.load(csv_path)
    assert bundle.records[0].applicant_id == "960430045398"
    assert any("Recovered applicant_id from PDF filename" in warning for warning in bundle.warnings)
