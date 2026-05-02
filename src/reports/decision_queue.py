"""Build a simplified applicant-level decision queue for operators."""

from __future__ import annotations

import re
from pathlib import PurePosixPath
from urllib.parse import quote

import pandas as pd

from src.extraction.evidence_models import EvidenceResult
from src.rules.validators import row_claim_is_married, row_has_oku_claim, row_has_postgraduate_claim


DEFAULT_PDF_BASE_URL = "https://eplacement-2.s3.ap-southeast-5.amazonaws.com/"
VALID_STATUSES = {"present", "not_present", "manual_check"}
NEGATIVE_TEXT_VALUES = {
    "",
    "0",
    "tiada",
    "tidak",
    "tidak berkenaan",
    "none",
    "n/a",
    "na",
    "null",
}
TICK = "\u2713"


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and pd.isna(value):
        return ""
    return str(value).strip()


def _normalize_identifier(value) -> str:
    text = _text(value)
    if re.fullmatch(r"\d+\.0+", text):
        return text.split(".", 1)[0]
    return text


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    text = _text(value).casefold()
    return text in {"1", "true", "yes", "y"}


def _has_meaningful_text(value) -> bool:
    text = _text(value).casefold()
    return bool(text) and text not in NEGATIVE_TEXT_VALUES


def _numeric_positive(value) -> bool:
    text = _text(value)
    if not text:
        return False
    try:
        return float(text) > 0
    except ValueError:
        return False


def _source_info_map(evidence_rows: list[EvidenceResult]) -> dict[str, dict[str, str]]:
    mapping: dict[str, dict[str, str]] = {}
    for row in evidence_rows:
        applicant_id = _normalize_identifier(row.applicant_id)
        if not applicant_id:
            continue
        info = mapping.setdefault(applicant_id, {"source_pdf_name": "", "original_pdf_url": ""})
        if row.source_pdf_name and not info["source_pdf_name"]:
            info["source_pdf_name"] = row.source_pdf_name
        if row.download_url and not info["original_pdf_url"]:
            info["original_pdf_url"] = row.download_url
    return mapping


def _build_original_pdf_url(original_pdf_url: str, source_pdf_name: str) -> str:
    url = _text(original_pdf_url)
    if url.lower().startswith(("http://", "https://")):
        return url
    filename = _text(source_pdf_name)
    if not filename:
        return ""
    return f"{DEFAULT_PDF_BASE_URL}{quote(filename)}"


def _row_source_pdf_name(row: pd.Series, applicant_source: dict[str, str], applicant_id: str) -> str:
    source_pdf_name = _text(applicant_source.get("source_pdf_name", ""))
    if source_pdf_name:
        return source_pdf_name
    for column in ["Sheet1.NamaFail", "NamaFail", "pdf_filename", "source_pdf_name"]:
        value = _text(row.get(column))
        if value:
            return value
    url = _text(row.get("ATTACHMENT") or row.get("Sheet1.DownloadURL") or row.get("DownloadURL") or row.get("pdf_url"))
    if url.lower().startswith(("http://", "https://")):
        filename = PurePosixPath(url.split("?", 1)[0]).name
        if filename:
            return filename
    return f"{applicant_id}.pdf" if applicant_id else ""


def _row_original_pdf_url(row: pd.Series, applicant_source: dict[str, str], source_pdf_name: str) -> str:
    for value in [
        applicant_source.get("original_pdf_url", ""),
        row.get("ATTACHMENT"),
        row.get("Sheet1.DownloadURL"),
        row.get("DownloadURL"),
        row.get("pdf_url"),
    ]:
        url = _text(value)
        if url.lower().startswith(("http://", "https://")):
            return url
    return _build_original_pdf_url("", source_pdf_name)


def _doc_status(row: pd.Series, *, primary_type: str, exact_flag: str, signal_flag: str) -> str:
    detected_primary = _text(row.get("KYC_DETECTED_PRIMARY_DOC"))
    has_exact = _as_bool(row.get(exact_flag))
    has_signal = _as_bool(row.get(signal_flag))
    if detected_primary == primary_type or has_exact:
        return "present"
    if has_signal:
        return "manual_check"
    return "not_present"


def _oku_status(row: pd.Series) -> str:
    if _as_bool(row.get("KYC_DETECTED_OKU_DOCUMENT")) or _as_bool(row.get("KYC_DETECTED_OKU_EVIDENCE")):
        return "present"
    return "not_present"


def _first_pass_status(row: pd.Series, column: str, fallback: str) -> str:
    status = _text(row.get(column)).casefold()
    if status in VALID_STATUSES:
        return status
    return fallback


def _summary_line(label: str, status: str) -> str:
    if status == "present":
        return f"{label} present."
    if status == "manual_check":
        return f"{label} unclear."
    return ""


def _display_tick(status: str) -> str:
    return TICK if status == "present" else ""


def _claim_self_illness(row: pd.Series) -> bool:
    return _has_meaningful_text(row.get("PERSONAL_HEALTH_CONDITION")) or _has_meaningful_text(row.get("Keterangan Kesihatan"))


def _claim_family_illness(row: pd.Series) -> bool:
    return any(
        [
            _has_meaningful_text(row.get("SPOUSE_HEALTH_CONDITION")),
            _has_meaningful_text(row.get("Keterangan Masalah Kesihatan Pasanga")),
            _numeric_positive(row.get("CHILDREN_HEALTH_ISSUE_SCORE")),
            _numeric_positive(row.get("PARENT_HEALTH_ISSUE_SCORE")),
        ]
    )


def _claim_spouse_location(row: pd.Series) -> bool:
    if not row_claim_is_married(_text(row.get("MARITAL_STATUS"))):
        return False
    return any(
        [
            _has_meaningful_text(row.get("Alamat Bekerja Pasangan")),
            _has_meaningful_text(row.get("NegeriBekerjaPasangan")),
            _has_meaningful_text(row.get("Pekerjaan Pasangan")),
            _has_meaningful_text(row.get("SPOUSE_EMPLOYMENT_STATUS")),
        ]
    )


def _claim_oku_self_or_family(row: pd.Series) -> bool:
    return any(
        [
            row_has_oku_claim(_text(row.get("StatusOKU"))),
            row_has_oku_claim(_text(row.get("SPOUSE_STATUS_OKU"))),
            _numeric_positive(row.get("CHILDREN_DISABILITY_SCORE")),
            _numeric_positive(row.get("PARENT_DISABILITY_SCORE")),
        ]
    )


def _claim_flags(row: pd.Series) -> dict[str, bool]:
    return {
        "marriage": row_claim_is_married(_text(row.get("MARITAL_STATUS"))),
        "self_illness": _claim_self_illness(row),
        "family_illness": _claim_family_illness(row),
        "spouse_location": _claim_spouse_location(row),
        "oku_self_or_family": _claim_oku_self_or_family(row),
        "medex_other_exam": row_has_postgraduate_claim(_text(row.get("POSTGRADUATE_PAPER_STATUS"))),
    }


def _has_supporting_document(row: pd.Series, original_pdf_url: str, source_pdf_name: str) -> bool:
    if _as_bool(row.get("KYC_SUPPORTING_DOC_PRESENT")):
        return True
    if _text(original_pdf_url):
        return True
    if _text(source_pdf_name):
        return True
    return False


def _gross_mismatch_reasons(
    statuses: dict[str, str],
    claims: dict[str, bool],
    *,
    has_supporting_document: bool,
) -> list[str]:
    labels = {
        "marriage": "marriage",
        "self_illness": "self illness",
        "family_illness": "family illness",
        "spouse_location": "spouse location",
        "oku_self_or_family": "OKU self/family",
        "medex_other_exam": "MedEX/other exam",
    }
    claimed_signals = [signal for signal, claimed in claims.items() if claimed]
    present_claims = [signal for signal in claimed_signals if statuses.get(signal) == "present"]
    ambiguous_claims = [signal for signal in claimed_signals if statuses.get(signal) == "manual_check"]
    missing_claims = [signal for signal in claimed_signals if statuses.get(signal) == "not_present"]
    reasons: list[str] = []

    if claimed_signals and not has_supporting_document:
        reasons.append("Claimed evidence exists in the spreadsheet but no supporting document was available.")

    if missing_claims:
        missing = ", ".join(labels[signal] for signal in missing_claims)
        if present_claims:
            detected = ", ".join(labels[signal] for signal in present_claims)
            reasons.append(f"Detected {detected}, but missing claimed {missing}.")
        else:
            reasons.append(f"Missing claimed {missing} after the second pass.")

    if ambiguous_claims:
        ambiguous = ", ".join(labels[signal] for signal in ambiguous_claims)
        reasons.append(f"Claimed {ambiguous} is still ambiguous after the second pass.")

    return list(dict.fromkeys(reasons))


def build_decision_queue(merged_df: pd.DataFrame, evidence_rows: list[EvidenceResult]) -> pd.DataFrame:
    source_info = _source_info_map(evidence_rows)
    rows: list[dict[str, object]] = []

    for _, row in merged_df.iterrows():
        applicant_id = _normalize_identifier(row.get("KYC_APPLICANT_ID_NORMALIZED") or row.get("applicant_id") or row.get("NO KP"))
        if not applicant_id:
            continue
        applicant_source = source_info.get(applicant_id, {"source_pdf_name": "", "original_pdf_url": ""})

        marriage = _first_pass_status(
            row,
            "KYC_FIRSTPASS_MARRIAGE",
            _doc_status(
                row,
                primary_type="marriage_certificate",
                exact_flag="KYC_DETECTED_MARRIAGE_CERTIFICATE",
                signal_flag="KYC_DETECTED_MARRIAGE_EVIDENCE",
            ),
        )
        self_illness = _first_pass_status(row, "KYC_FIRSTPASS_SELF_ILLNESS", "not_present")
        family_illness = _first_pass_status(row, "KYC_FIRSTPASS_FAMILY_ILLNESS", "not_present")
        spouse_location = _first_pass_status(row, "KYC_FIRSTPASS_SPOUSE_LOCATION", "not_present")
        oku_self_or_family = _first_pass_status(row, "KYC_FIRSTPASS_OKU_SELF_OR_FAMILY", _oku_status(row))
        medex_other_exam = _first_pass_status(
            row,
            "KYC_FIRSTPASS_MEDEX_OR_OTHER_EXAM",
            _doc_status(
                row,
                primary_type="medex_or_exam_document",
                exact_flag="KYC_DETECTED_MEDEX_EXAM_DOCUMENT",
                signal_flag="KYC_DETECTED_MEDEX_EVIDENCE",
            ),
        )

        statuses = {
            "marriage": marriage,
            "self_illness": self_illness,
            "family_illness": family_illness,
            "spouse_location": spouse_location,
            "oku_self_or_family": oku_self_or_family,
            "medex_other_exam": medex_other_exam,
        }
        claims = _claim_flags(row)

        summary_parts = [
            _summary_line("Marriage", marriage),
            _summary_line("Self illness", self_illness),
            _summary_line("Family illness", family_illness),
            _summary_line("Spouse location", spouse_location),
            _summary_line("OKU", oku_self_or_family),
            _summary_line("MedEX/exam", medex_other_exam),
        ]

        source_pdf_name = _row_source_pdf_name(row, applicant_source, applicant_id)
        original_pdf_url = _row_original_pdf_url(row, applicant_source, source_pdf_name)
        has_supporting_document = _has_supporting_document(row, original_pdf_url, source_pdf_name)
        check_reasons = _gross_mismatch_reasons(statuses, claims, has_supporting_document=has_supporting_document)
        check_required = "check" if check_reasons else "no_check"
        summary = " | ".join(part for part in [*summary_parts, *check_reasons] if part) or "No target evidence detected."

        rows.append(
            {
                "applicant_id": applicant_id,
                "marriage": _display_tick(marriage),
                "self_illness": _display_tick(self_illness),
                "family_illness": _display_tick(family_illness),
                "spouse_location": _display_tick(spouse_location),
                "oku_self_or_family": _display_tick(oku_self_or_family),
                "medex_other_exam": _display_tick(medex_other_exam),
                "marriage_status": marriage,
                "self_illness_status": self_illness,
                "family_illness_status": family_illness,
                "spouse_location_status": spouse_location,
                "oku_self_or_family_status": oku_self_or_family,
                "medex_other_exam_status": medex_other_exam,
                "check_required": check_required,
                "summary": summary,
                "original_pdf_url": original_pdf_url,
                "open_original_pdf": original_pdf_url,
                "source_pdf_name": source_pdf_name,
                "_check_sort": 0 if check_required == "check" else 1,
            }
        )

    decision_df = pd.DataFrame(rows)
    if decision_df.empty:
        return decision_df
    decision_df = decision_df.sort_values(by=["_check_sort", "applicant_id"], ascending=[True, True], kind="stable")
    return decision_df.drop(columns=["_check_sort"])
