"""Langflow component for rules validation."""

from __future__ import annotations

from src.extraction.evidence_models import GenericEvidence, MarriageEvidence, MedexEvidence, OCRDocument, ValidationDecision
from src.langflow_components._base import Component
from src.rules.marriage_rules import validate_marriage
from src.rules.medex_rules import validate_medex
from src.rules.validators import generic_document_decision


class RulesValidatorComponent(Component):
    display_name = "Rules Validator"
    description = "Apply transparent Python rules to extracted evidence."
    name = "RulesValidatorComponent"

    def validate_document(self, applicant_row: dict, ocr_document: OCRDocument, extracted_evidence: MarriageEvidence | MedexEvidence | GenericEvidence, target_type: str) -> ValidationDecision:
        if target_type == "marriage_certificate":
            evidence = MarriageEvidence.model_validate(extracted_evidence)
            return validate_marriage(applicant_row, evidence, ocr_document)
        if target_type == "medex_or_exam_document":
            evidence = MedexEvidence.model_validate(extracted_evidence)
            return validate_medex(applicant_row, evidence, ocr_document)
        evidence = GenericEvidence.model_validate(extracted_evidence)
        return generic_document_decision(evidence, ocr_document)

    def run_model(self, applicant_row: dict, ocr_document: dict, extracted_evidence: dict, target_type: str) -> dict:
        document = OCRDocument.model_validate(ocr_document)
        if target_type == "marriage_certificate":
            evidence = MarriageEvidence.model_validate(extracted_evidence)
        elif target_type == "medex_or_exam_document":
            evidence = MedexEvidence.model_validate(extracted_evidence)
        else:
            evidence = GenericEvidence.model_validate(extracted_evidence)
        return self.validate_document(applicant_row, document, evidence, target_type).model_dump(mode="json")
