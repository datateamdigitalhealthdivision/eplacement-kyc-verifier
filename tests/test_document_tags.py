from types import SimpleNamespace

from src.rules.document_tags import derive_document_tags


def test_primary_marriage_document_does_not_infer_cross_domain_tags() -> None:
    classification = SimpleNamespace(primary_type="marriage_certificate")
    evidence = SimpleNamespace(
        doc_type="marriage_certificate",
        key_supporting_snippets=["SURAT PERAKUAN NIKAH"],
        raw_payload={"note": "OKU MEDEX"},
    )
    document = SimpleNamespace(combined_text="SURAT PERAKUAN NIKAH")

    tags = derive_document_tags(classification, evidence, document)

    assert tags["marriage_certificate"] is True
    assert tags["marriage_related_document"] is True
    assert tags["medex_exam_document"] is False
    assert tags["oku_document"] is False
    assert tags["medical_document"] is False
    assert tags["marriage_evidence_detected"] is True
    assert tags["medex_evidence_detected"] is False
    assert tags["oku_evidence_detected"] is False


def test_other_supporting_document_can_surface_oku_signal() -> None:
    classification = SimpleNamespace(primary_type="other_supporting_document")
    evidence = SimpleNamespace(
        doc_type="other_supporting_document",
        key_supporting_snippets=["JABATAN KEBAJIKAN MASYARAKAT"],
        raw_payload={},
    )
    document = SimpleNamespace(combined_text="PENDAFTARAN ORANG KURANG UPAYA")

    tags = derive_document_tags(classification, evidence, document)

    assert tags["other_supporting_document"] is True
    assert tags["oku_document"] is True
    assert tags["oku_evidence_detected"] is True
