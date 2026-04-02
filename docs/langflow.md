# Langflow Guide

Langflow is optional in this repo. The FastAPI and Streamlit paths call the same underlying services directly, while Langflow gives you a visual way to inspect or prototype the pipeline.

## Files that matter

- `flows/evidence_verification_flow.json`: importable Langflow flow
- `src/langflow_components/`: custom component implementations
- `src/langflow_components/registry.py`: component catalog used as the source of truth for what the flow exposes

## Current component chain

1. `ApplicantLoaderComponent`
   - loads the spreadsheet with the same `SpreadsheetLoader` used by the app
2. `PDFFetchComponent`
   - finds a local PDF or downloads it from the spreadsheet URL
3. `OCRRouterComponent`
   - produces OCR text, page images, hashes, and OCR metadata
4. `DocClassifierComponent`
   - classifies using OCR text plus page images, so the visual path stays aligned with the live app
5. `EvidenceExtractorComponent`
   - runs the document-specific extractor
6. `RulesValidatorComponent`
   - applies deterministic Python rules for the final rule outcome
7. `ExportWriterComponent`
   - writes the same merged and review artifacts used elsewhere in the repo

## Why this matters

The Langflow layer is intentionally thin. It should not contain separate business logic. Each component wraps the same Python modules that FastAPI and Streamlit use, which keeps visual experimentation and production behavior aligned.

## Local startup notes

Recommended environment for Langflow is Python 3.11 to 3.13. This repository can run parts of the pipeline on Python 3.14, but Langflow and some watcher behavior are more stable on 3.11 to 3.13.

Typical launch flow:

1. Create and activate the virtual environment.
2. Install dependencies.
3. Set `PYTHONPATH` to the repository root.
4. Start Langflow from the repository root.
5. Import `flows/evidence_verification_flow.json`.

## Reading the flow in code

If you want to understand what a node does, open the matching file in `src/langflow_components/`. The component names in Langflow match the class names listed in `src/langflow_components/registry.py`.
