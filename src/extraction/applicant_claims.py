"""Helpers for turning applicant spreadsheet rows into claim booleans."""

from __future__ import annotations

from pydantic import BaseModel, Field

from src.rules.validators import row_claim_is_married, row_has_oku_claim, row_has_postgraduate_claim


SIGNAL_KEYS = [
    "marriage",
    "self_illness",
    "family_illness",
    "spouse_location",
    "oku_self_or_family",
    "medex_or_other_exam",
]
NEGATIVE_TEXT_VALUES = {"", "0", "tiada", "tidak", "tidak berkenaan", "none", "n/a", "na", "null"}
SPOUSE_FIELDS = [
    "spouse_name",
    "spouse_id",
    "spouse_employment_status",
    "spouse_job_title",
    "spouse_work_address",
    "spouse_work_state",
    "spouse_oku_status",
    "spouse_health_condition",
    "spouse_health_details",
]


def _text(value) -> str:
    return str(value or "").strip()


def _has_meaningful_text(value) -> bool:
    return _text(value).casefold() not in NEGATIVE_TEXT_VALUES


def _numeric_positive(value) -> bool:
    text = _text(value)
    if not text:
        return False
    try:
        return float(text) > 0
    except ValueError:
        return False


class ApplicantClaims(BaseModel):
    claimed_marriage: bool = False
    claimed_self_illness: bool = False
    claimed_family_illness: bool = False
    claimed_spouse_location: bool = False
    claimed_oku_self_or_family: bool = False
    claimed_medex_other_exam: bool = False
    unclear_claims: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

    def signal_map(self) -> dict[str, bool]:
        return {
            "marriage": self.claimed_marriage,
            "self_illness": self.claimed_self_illness,
            "family_illness": self.claimed_family_illness,
            "spouse_location": self.claimed_spouse_location,
            "oku_self_or_family": self.claimed_oku_self_or_family,
            "medex_or_other_exam": self.claimed_medex_other_exam,
        }

    def active_signals(self) -> list[str]:
        return [signal for signal, claimed in self.signal_map().items() if claimed]

    def is_unclear(self) -> bool:
        return bool(self.unclear_claims)

    def export_claim_columns(self) -> dict[str, bool]:
        return {
            "claimed_marriage": self.claimed_marriage,
            "claimed_self_illness": self.claimed_self_illness,
            "claimed_family_illness": self.claimed_family_illness,
            "claimed_spouse_location": self.claimed_spouse_location,
            "claimed_oku_self_or_family": self.claimed_oku_self_or_family,
            "claimed_medex_other_exam": self.claimed_medex_other_exam,
        }


def extract_applicant_claims(row: dict) -> ApplicantClaims:
    row = row or {}
    marital_status = row.get("marital_status")
    spouse_fields_present = any(_has_meaningful_text(row.get(field)) for field in SPOUSE_FIELDS)
    claimed_marriage = row_claim_is_married(marital_status)
    claimed_self_illness = _has_meaningful_text(row.get("personal_health_condition")) or _has_meaningful_text(row.get("personal_health_details"))
    claimed_family_illness = any(
        [
            _has_meaningful_text(row.get("spouse_health_condition")),
            _has_meaningful_text(row.get("spouse_health_details")),
            _numeric_positive(row.get("children_health_issue_score")),
            _numeric_positive(row.get("parent_health_issue_score")),
        ]
    )
    claimed_spouse_location = claimed_marriage and any(
        [
            _has_meaningful_text(row.get("spouse_employment_status")),
            _has_meaningful_text(row.get("spouse_job_title")),
            _has_meaningful_text(row.get("spouse_work_address")),
            _has_meaningful_text(row.get("spouse_work_state")),
        ]
    )
    claimed_oku_self_or_family = any(
        [
            row_has_oku_claim(row.get("applicant_oku_status")),
            row_has_oku_claim(row.get("spouse_oku_status")),
            _numeric_positive(row.get("children_disability_score")),
            _numeric_positive(row.get("parent_disability_score")),
        ]
    )
    claimed_medex_other_exam = row_has_postgraduate_claim(row.get("postgraduate_status"))

    unclear_claims: list[str] = []
    notes: list[str] = []

    if not _has_meaningful_text(marital_status) and spouse_fields_present:
        unclear_claims.extend(["marriage", "spouse_location"])
        if _has_meaningful_text(row.get("spouse_health_condition")) or _has_meaningful_text(row.get("spouse_health_details")):
            unclear_claims.append("family_illness")
        notes.append("Spouse-related fields are populated but marital status is blank or unclear.")

    postgraduate_status = row.get("postgraduate_status")
    if _has_meaningful_text(postgraduate_status) and not claimed_medex_other_exam and "exam" in _text(postgraduate_status).casefold():
        unclear_claims.append("medex_or_other_exam")
        notes.append("Postgraduate or exam text is present but could not be confidently converted into a MedEX/exam claim.")

    for value in [row.get("applicant_oku_status"), row.get("spouse_oku_status")]:
        if _has_meaningful_text(value) and not row_has_oku_claim(value):
            unclear_claims.append("oku_self_or_family")
            notes.append("OKU-related text is present but could not be confidently converted into a claim.")
            break

    claims = ApplicantClaims(
        claimed_marriage=claimed_marriage,
        claimed_self_illness=claimed_self_illness,
        claimed_family_illness=claimed_family_illness,
        claimed_spouse_location=claimed_spouse_location,
        claimed_oku_self_or_family=claimed_oku_self_or_family,
        claimed_medex_other_exam=claimed_medex_other_exam,
        unclear_claims=list(dict.fromkeys(unclear_claims)),
        notes=list(dict.fromkeys(notes)),
    )
    return claims
