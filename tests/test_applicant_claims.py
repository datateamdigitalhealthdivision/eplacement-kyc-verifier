from src.extraction.applicant_claims import extract_applicant_claims


def test_extract_applicant_claims_maps_expected_v4_booleans() -> None:
    claims = extract_applicant_claims(
        {
            "marital_status": "BERKAHWIN",
            "spouse_name": "Aisyah",
            "spouse_work_address": "Cyberjaya",
            "personal_health_condition": "Hypertension",
            "children_disability_score": "1",
            "postgraduate_status": "Peperiksaan Kemasukan/MedEX/GCFM",
        }
    )

    assert claims.claimed_marriage is True
    assert claims.claimed_self_illness is True
    assert claims.claimed_family_illness is False
    assert claims.claimed_spouse_location is True
    assert claims.claimed_oku_self_or_family is True
    assert claims.claimed_medex_other_exam is True
    assert claims.signal_map()["medex_or_other_exam"] is True


def test_extract_applicant_claims_marks_unclear_spouse_claims() -> None:
    claims = extract_applicant_claims(
        {
            "marital_status": "",
            "spouse_name": "Aisyah",
            "spouse_work_address": "Cyberjaya",
        }
    )

    assert claims.is_unclear() is True
    assert "marriage" in claims.unclear_claims
    assert "spouse_location" in claims.unclear_claims
