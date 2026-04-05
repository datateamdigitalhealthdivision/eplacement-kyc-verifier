"""Catalog of custom Langflow components shipped with the repository."""

from __future__ import annotations


COMPONENT_CATALOG: list[dict[str, str]] = [
    {
        "display_name": "Applicant Loader",
        "class_name": "ApplicantLoaderComponent",
        "module_path": "src.langflow_components.applicant_loader",
        "purpose": "Loads the spreadsheet and emits normalized applicant rows.",
    },
    {
        "display_name": "PDF Fetch",
        "class_name": "PDFFetchComponent",
        "module_path": "src.langflow_components.pdf_fetch_component",
        "purpose": "Finds or downloads the applicant PDF before OCR starts.",
    },
    {
        "display_name": "OCR Router",
        "class_name": "OCRRouterComponent",
        "module_path": "src.langflow_components.ocr_component",
        "purpose": "Builds the OCR document object, including page images for vision models.",
    },
    {
        "display_name": "Evidence Signals",
        "class_name": "FirstPassSignalsComponent",
        "module_path": "src.langflow_components.first_pass_signals_component",
        "purpose": "Scans the full PDF bundle for broad first-pass evidence categories.",
    },
    {
        "display_name": "Doc Classifier",
        "class_name": "DocClassifierComponent",
        "module_path": "src.langflow_components.classify_component",
        "purpose": "Tags the observed document type from OCR text plus page images.",
    },
    {
        "display_name": "Evidence Extractor",
        "class_name": "EvidenceExtractorComponent",
        "module_path": "src.langflow_components.extract_component",
        "purpose": "Extracts document-specific fields once the type is known.",
    },
    {
        "display_name": "Rules Validator",
        "class_name": "RulesValidatorComponent",
        "module_path": "src.langflow_components.validate_component",
        "purpose": "Applies deterministic Python rules to the extracted evidence.",
    },
    {
        "display_name": "Export Writer",
        "class_name": "ExportWriterComponent",
        "module_path": "src.langflow_components.export_component",
        "purpose": "Writes validation, merged, review, and decision queue exports.",
    },
]


def component_catalog() -> list[dict[str, str]]:
    return [item.copy() for item in COMPONENT_CATALOG]
