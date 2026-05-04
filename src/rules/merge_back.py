"""Merge applicant-level claim-guided results back onto the spreadsheet."""

from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd

from src.extraction.applicant_claims import ApplicantClaims, extract_applicant_claims
from src.extraction.evidence_models import EvidenceResult


SIGNAL_KEYS = [
    "marriage",
    "self_illness",
    "family_illness",
    "spouse_location",
    "oku_self_or_family",
    "medex_or_other_exam",
]
SIGNAL_EXPORT_KEYS = {
    "marriage": "marriage",
    "self_illness": "self_illness",
    "family_illness": "family_illness",
    "spouse_location": "spouse_location",
    "oku_self_or_family": "oku_self_or_family",
    "medex_or_other_exam": "medex_other_exam",
}
SIGNAL_LABELS = {
    "marriage": "marriage",
    "self_illness": "self illness",
    "family_illness": "family illness",
    "spouse_location": "spouse location",
    "oku_self_or_family": "OKU self/family",
    "medex_or_other_exam": "MedEX/other exam",
}
FIRST_PASS_STATUS_COLUMNS = {
    "marriage": "KYC_FIRSTPASS_MARRIAGE",
    "self_illness": "KYC_FIRSTPASS_SELF_ILLNESS",
    "family_illness": "KYC_FIRSTPASS_FAMILY_ILLNESS",
    "spouse_location": "KYC_FIRSTPASS_SPOUSE_LOCATION",
    "oku_self_or_family": "KYC_FIRSTPASS_OKU_SELF_OR_FAMILY",
    "medex_or_other_exam": "KYC_FIRSTPASS_MEDEX_OR_OTHER_EXAM",
}
TAG_COLUMNS = {
    "marriage_certificate": "KYC_DETECTED_MARRIAGE_CERTIFICATE",
    "marriage_related_document": "KYC_DETECTED_MARRIAGE_RELATED_DOCUMENT",
    "medex_exam_document": "KYC_DETECTED_MEDEX_EXAM_DOCUMENT",
    "oku_document": "KYC_DETECTED_OKU_DOCUMENT",
    "medical_document": "KYC_DETECTED_MEDICAL_DOCUMENT",
    "other_supporting_document": "KYC_DETECTED_OTHER_SUPPORTING_DOCUMENT",
}
EVIDENCE_COLUMNS = {
    "marriage_evidence_detected": "KYC_DETECTED_MARRIAGE_EVIDENCE",
    "medex_evidence_detected": "KYC_DETECTED_MEDEX_EVIDENCE",
    "oku_evidence_detected": "KYC_DETECTED_OKU_EVIDENCE",
}


def _text(value) -> str:
    return str(value or "").strip()


def _as_bool(value) -> bool:
    if isinstance(value, bool):
        return value
    return _text(value).casefold() in {"1", "true", "yes", "y"}


def _join_pages(pages: list[int]) -> str:
    return ", ".join(str(page) for page in pages if str(page).strip())


def _default_signal_detail(signal: str, claimed: bool, status: str) -> dict[str, object]:
    label = SIGNAL_LABELS[signal]
    if not claimed:
        summary = "Not claimed; skipped."
    elif status == "present":
        summary = f"Supporting {label} evidence was found."
    elif status == "manual_check":
        summary = f"Potential {label} evidence was found but remains ambiguous."
    else:
        summary = f"No supporting {label} evidence was found."
    return {
        "claimed": claimed,
        "status": status if claimed else "not_present",
        "proof_found": claimed and status == "present",
        "verified": claimed and status == "present",
        "missing_proof": claimed and status != "present",
        "ambiguous": claimed and status == "manual_check",
        "low_confidence": False,
        "proof_strength": 2 if claimed and status == "present" else 1 if claimed and status == "manual_check" else 0,
        "supporting_pages": [],
        "document_type": "",
        "person_named": "",
        "person_role": "unknown",
        "relationship_to_applicant": "unknown",
        "evidence_summary": summary,
        "confidence": 1.0 if claimed and status == "present" else 0.5 if claimed and status == "manual_check" else 0.0,
    }


def _preferred_record(records: list[EvidenceResult]) -> EvidenceResult | None:
    if not records:
        return None
    for result_kind in ["candidate_assessment", "observed_document"]:
        for record in records:
            if record.audit_payload.get("result_kind") == result_kind:
                return record
    return records[0]


def _normalize_signal_details(record: EvidenceResult | None, claims: ApplicantClaims) -> dict[str, dict[str, object]]:
    if record is None:
        return {signal: _default_signal_detail(signal, claims.signal_map().get(signal, False), "not_present") for signal in SIGNAL_KEYS}

    payload = record.audit_payload or {}
    raw_details = dict(payload.get("signal_details") or {})
    raw_statuses = dict(payload.get("final_signal_statuses") or payload.get("first_pass_signals") or {})
    claim_map = claims.signal_map()
    normalized: dict[str, dict[str, object]] = {}

    for signal in SIGNAL_KEYS:
        detail = dict(raw_details.get(signal) or {})
        raw_status = _text(detail.get("status") or raw_statuses.get(signal) or "not_present").casefold() or "not_present"
        if not detail:
            detail = _default_signal_detail(signal, claim_map.get(signal, False), raw_status)
        claimed = bool(detail.get("claimed", claim_map.get(signal, False)))
        status = raw_status
        proof_found = bool(detail.get("proof_found", claimed and status == "present"))
        ambiguous = bool(detail.get("ambiguous", claimed and status == "manual_check"))
        low_confidence = bool(detail.get("low_confidence", False))
        supporting_pages = [int(page) for page in detail.get("supporting_pages", []) if str(page).strip()]
        evidence_summary = _text(detail.get("evidence_summary"))
        if not evidence_summary:
            if not claimed and status != "not_present":
                evidence_summary = f"Legacy broad scan detected {SIGNAL_LABELS[signal]} evidence even though the category was not claimed."
            else:
                evidence_summary = _default_signal_detail(signal, claimed, status)["evidence_summary"]
        confidence = float(detail.get("confidence") or (1.0 if proof_found else 0.5 if ambiguous else 0.0))
        normalized[signal] = {
            "claimed": claimed,
            "status": status,
            "proof_found": proof_found,
            "verified": bool(detail.get("verified", proof_found)),
            "missing_proof": bool(detail.get("missing_proof", claimed and not proof_found)),
            "ambiguous": ambiguous,
            "low_confidence": low_confidence,
            "proof_strength": int(detail.get("proof_strength", 2 if proof_found else 1 if ambiguous else 0) or 0),
            "supporting_pages": supporting_pages,
            "document_type": _text(detail.get("document_type")),
            "person_named": _text(detail.get("person_named")),
            "person_role": _text(detail.get("person_role") or "unknown"),
            "relationship_to_applicant": _text(detail.get("relationship_to_applicant") or "unknown"),
            "evidence_summary": evidence_summary,
            "confidence": confidence,
        }
    return normalized


def _signal_tags(signal_details: dict[str, dict[str, object]], has_document: bool) -> dict[str, bool]:
    marriage = signal_details["marriage"]["status"] != "not_present"
    medex = signal_details["medex_or_other_exam"]["status"] != "not_present"
    oku = signal_details["oku_self_or_family"]["status"] != "not_present"
    medical = any(signal_details[key]["status"] != "not_present" for key in ["self_illness", "family_illness", "medex_or_other_exam"])
    any_detected = any(detail["status"] != "not_present" for detail in signal_details.values())
    return {
        "marriage_certificate": marriage,
        "marriage_related_document": marriage or signal_details["spouse_location"]["status"] != "not_present",
        "medex_exam_document": medex,
        "oku_document": oku,
        "medical_document": medical,
        "other_supporting_document": has_document and not any_detected,
        "marriage_evidence_detected": marriage,
        "medex_evidence_detected": medex,
        "oku_evidence_detected": oku,
    }


def _claim_status(detail: dict[str, object], label: str) -> tuple[str, str, bool]:
    if not detail["claimed"]:
        return "", "", False
    if detail["verified"]:
        return "CONFIRMED", f"Detected {label}.", False
    if detail["ambiguous"] or detail["low_confidence"]:
        return "MANUAL_REVIEW_REQUIRED", f"{label.capitalize()} is still ambiguous after the claim-guided second pass.", True
    return "MANUAL_REVIEW_REQUIRED", f"{label.capitalize()} is still missing after the claim-guided second pass.", True


def merge_results_back(source_df: pd.DataFrame, canonical_df: pd.DataFrame, evidence_results: list[EvidenceResult]) -> pd.DataFrame:
    bucketed: dict[str, list[EvidenceResult]] = {}
    for result in evidence_results:
        bucketed.setdefault(result.applicant_id, []).append(result)

    merged = source_df.copy()
    now = datetime.now(UTC).isoformat()

    kyc_columns: dict[str, list[object]] = {
        "KYC_APPLICANT_ID_NORMALIZED": [],
        "KYC_UPLOADED_DOC_TYPE": [],
        "KYC_UPLOADED_DOC_STATUS": [],
        "KYC_UPLOADED_DOC_REASON": [],
        "KYC_UPLOADED_DOC_REVIEW_REQUIRED": [],
        "KYC_DETECTED_PRIMARY_DOC": [],
        "KYC_DETECTED_DOC_TAGS": [],
        "KYC_CLAIM_MARRIED": [],
        "KYC_CLAIM_MEDEX": [],
        "KYC_CLAIM_OKU": [],
        "KYC_MARRIAGE_STATUS": [],
        "KYC_MARRIAGE_REASON": [],
        "KYC_MARRIAGE_REVIEW_REQUIRED": [],
        "KYC_MEDEX_STATUS": [],
        "KYC_MEDEX_REASON": [],
        "KYC_MEDEX_REVIEW_REQUIRED": [],
        "KYC_OKU_STATUS": [],
        "KYC_OKU_REASON": [],
        "KYC_OKU_REVIEW_REQUIRED": [],
        "KYC_OVERALL_STATUS": [],
        "KYC_OVERALL_REASON": [],
        "KYC_OVERALL_REVIEW_REQUIRED": [],
        "KYC_NEEDS_MANUAL_REVIEW": [],
        "KYC_SUPPORTING_DOC_PRESENT": [],
        "KYC_LAST_RUN_AT": [],
    }
    for column in [*TAG_COLUMNS.values(), *EVIDENCE_COLUMNS.values(), *FIRST_PASS_STATUS_COLUMNS.values()]:
        kyc_columns[column] = []
    for signal in SIGNAL_KEYS:
        suffix = SIGNAL_EXPORT_KEYS[signal]
        for prefix in [
            "claimed",
            "proof_found",
            "proof_strength",
            "verified",
            "missing_proof",
            "supporting_page",
            "document_type",
            "person_named",
            "person_role",
            "relationship_to_applicant",
            "evidence_summary",
            "confidence",
        ]:
            kyc_columns[f"{prefix}_{suffix}"] = []

    for _, canonical_row in canonical_df.iterrows():
        canonical_dict = dict(canonical_row)
        applicant_id = _text(canonical_dict.get("applicant_id"))
        claims = extract_applicant_claims(canonical_dict)
        record = _preferred_record(bucketed.get(applicant_id, []))
        signal_details = _normalize_signal_details(record, claims)
        has_document = bool(record and (record.source_pdf_path or record.source_pdf_name or record.download_url))
        tags = _signal_tags(signal_details, has_document)
        detected_primary = ""
        if record:
            detected_primary = _text(record.audit_payload.get("detected_primary_signal") or record.document_type)
        if not detected_primary and has_document:
            for signal in ["marriage", "spouse_location", "medex_or_other_exam", "oku_self_or_family", "self_illness", "family_illness"]:
                if signal_details[signal]["status"] == "present":
                    detected_primary = signal
                    break

        positive_tags = [tag for tag, value in tags.items() if value]
        positive_tags.extend(f"{signal}:{detail['status']}" for signal, detail in signal_details.items() if detail["status"] != "not_present")

        marriage_status, marriage_reason, marriage_review = _claim_status(signal_details["marriage"], "marriage evidence")
        medex_status, medex_reason, medex_review = _claim_status(signal_details["medex_or_other_exam"], "MedEX/other exam evidence")
        oku_status, oku_reason, oku_review = _claim_status(signal_details["oku_self_or_family"], "OKU evidence")

        missing_or_ambiguous = any(detail["claimed"] and int(detail.get("proof_strength") or 0) <= 1 for detail in signal_details.values())
        overall_review = bool(record.manual_review_flag) if record else False
        overall_review = overall_review or missing_or_ambiguous or claims.is_unclear()
        overall_status = record.effective_status() if record else ("MANUAL_REVIEW_REQUIRED" if overall_review else "CONFIRMED")
        overall_reason_parts: list[str] = []
        if record and _text(record.final_reason):
            overall_reason_parts.append(_text(record.final_reason))
        if claims.is_unclear():
            unclear = ", ".join(SIGNAL_LABELS.get(signal, signal.replace("_", " ")) for signal in claims.unclear_claims)
            overall_reason_parts.append(f"Claim extraction unclear for: {unclear}.")
        for signal in SIGNAL_KEYS:
            detail = signal_details[signal]
            if detail["claimed"] and int(detail.get("proof_strength") or 0) <= 1:
                overall_reason_parts.append(_text(detail["evidence_summary"]))
        overall_reason = " | ".join(dict.fromkeys(part for part in overall_reason_parts if part))

        kyc_columns["KYC_APPLICANT_ID_NORMALIZED"].append(applicant_id)
        kyc_columns["KYC_UPLOADED_DOC_TYPE"].append(detected_primary or _text(record.document_type if record else ""))
        kyc_columns["KYC_UPLOADED_DOC_STATUS"].append(overall_status)
        kyc_columns["KYC_UPLOADED_DOC_REASON"].append(overall_reason)
        kyc_columns["KYC_UPLOADED_DOC_REVIEW_REQUIRED"].append(overall_review)
        kyc_columns["KYC_DETECTED_PRIMARY_DOC"].append(detected_primary)
        kyc_columns["KYC_DETECTED_DOC_TAGS"].append(" | ".join(positive_tags))
        kyc_columns["KYC_CLAIM_MARRIED"].append(claims.claimed_marriage)
        kyc_columns["KYC_CLAIM_MEDEX"].append(claims.claimed_medex_other_exam)
        kyc_columns["KYC_CLAIM_OKU"].append(claims.claimed_oku_self_or_family)
        kyc_columns["KYC_MARRIAGE_STATUS"].append(marriage_status)
        kyc_columns["KYC_MARRIAGE_REASON"].append(marriage_reason)
        kyc_columns["KYC_MARRIAGE_REVIEW_REQUIRED"].append(marriage_review)
        kyc_columns["KYC_MEDEX_STATUS"].append(medex_status)
        kyc_columns["KYC_MEDEX_REASON"].append(medex_reason)
        kyc_columns["KYC_MEDEX_REVIEW_REQUIRED"].append(medex_review)
        kyc_columns["KYC_OKU_STATUS"].append(oku_status)
        kyc_columns["KYC_OKU_REASON"].append(oku_reason)
        kyc_columns["KYC_OKU_REVIEW_REQUIRED"].append(oku_review)
        kyc_columns["KYC_OVERALL_STATUS"].append(overall_status)
        kyc_columns["KYC_OVERALL_REASON"].append(overall_reason)
        kyc_columns["KYC_OVERALL_REVIEW_REQUIRED"].append(overall_review)
        kyc_columns["KYC_NEEDS_MANUAL_REVIEW"].append(overall_review)
        kyc_columns["KYC_SUPPORTING_DOC_PRESENT"].append(has_document)
        kyc_columns["KYC_LAST_RUN_AT"].append(now)

        for tag, column in TAG_COLUMNS.items():
            kyc_columns[column].append(bool(tags.get(tag, False)))
        for tag, column in EVIDENCE_COLUMNS.items():
            kyc_columns[column].append(bool(tags.get(tag, False)))
        for signal, column in FIRST_PASS_STATUS_COLUMNS.items():
            kyc_columns[column].append(signal_details[signal]["status"])
        for signal in SIGNAL_KEYS:
            suffix = SIGNAL_EXPORT_KEYS[signal]
            detail = signal_details[signal]
            kyc_columns[f"claimed_{suffix}"].append(bool(detail["claimed"]))
            kyc_columns[f"proof_found_{suffix}"].append(bool(detail["proof_found"]))
            kyc_columns[f"proof_strength_{suffix}"].append(int(detail.get("proof_strength") or 0))
            kyc_columns[f"verified_{suffix}"].append(bool(detail["verified"]))
            kyc_columns[f"missing_proof_{suffix}"].append(bool(detail["missing_proof"]))
            kyc_columns[f"supporting_page_{suffix}"].append(_join_pages(detail["supporting_pages"]))
            kyc_columns[f"document_type_{suffix}"].append(_text(detail.get("document_type")))
            kyc_columns[f"person_named_{suffix}"].append(_text(detail.get("person_named")))
            kyc_columns[f"person_role_{suffix}"].append(_text(detail.get("person_role")))
            kyc_columns[f"relationship_to_applicant_{suffix}"].append(_text(detail.get("relationship_to_applicant")))
            kyc_columns[f"evidence_summary_{suffix}"].append(_text(detail["evidence_summary"]))
            kyc_columns[f"confidence_{suffix}"].append(float(detail["confidence"]))

    for column, values in kyc_columns.items():
        merged[column] = values
    return merged
