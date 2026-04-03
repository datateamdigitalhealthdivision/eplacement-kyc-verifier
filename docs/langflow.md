# Langflow Guide

Langflow is the primary orchestration model in this repo.

The Streamlit app and FastAPI backend do not bypass the flow anymore. They call `src/orchestration/langflow_first_pass.py`, which runs the same node sequence defined in `flows/evidence_verification_flow.json` and implemented in `src/langflow_components/`.

## Files that matter

- `flows/evidence_verification_flow.json`: the visual flow definition
- `src/langflow_components/`: custom node implementations used by both the flow and the live runner
- `src/orchestration/langflow_first_pass.py`: the runtime runner that executes the Langflow-shaped chain
- `src/orchestration/result_builder.py`: shared helpers for building evidence rows and summaries from the flow
- `src/langflow_components/registry.py`: component catalog for the flow

## Current component chain

1. `ApplicantLoaderComponent`
   - loads and canonicalizes the spreadsheet
2. `PDFFetchComponent`
   - finds a local PDF or downloads it from the spreadsheet URL
3. `OCRRouterComponent`
   - produces OCR text, page images, hashes, and OCR metadata
4. `DocClassifierComponent`
   - classifies using OCR text plus page images
5. `EvidenceExtractorComponent`
   - runs the document-specific extractor
6. `RulesValidatorComponent`
   - applies deterministic Python rules for the final outcome
7. `ExportWriterComponent`
   - writes the same merged and review artifacts used by the app

## How to think about the architecture

- Langflow owns orchestration.
- The Python modules under `src/ocr/`, `src/classification/`, `src/extraction/`, and `src/rules/` are the step implementations.
- The runner in `src/orchestration/langflow_first_pass.py` is there so the app can execute the same Langflow-shaped chain without requiring a Langflow server to be running.
- `src/services/batch_processor.py` is now a legacy direct runner kept for regression comparison and troubleshooting, not the main runtime path.

## Where Qwen/Ollama fits in the flow

- `src/llm/ollama_client.py` sends text requests to `qwen2.5:7b-instruct` and vision requests to `qwen2.5vl:7b`.
- `OCRRouterComponent` gives the document both OCR text and page image paths.
- `DocClassifierComponent` sends page images to Qwen vision when available.
- `EvidenceExtractorComponent` uses the same page images for document-specific field extraction.

So the actual multimodal path is:

`PDF -> OCR Router -> page images + OCR text -> Doc Classifier / Evidence Extractor -> Rules Validator`

## Local startup notes

Recommended environment for Langflow is Python 3.11 to 3.13. This repository can run parts of the pipeline on Python 3.14, but Langflow and some watcher behavior are more stable on 3.11 to 3.13.

Typical launch flow:

1. Create and activate the virtual environment.
2. Install dependencies.
3. Set `PYTHONPATH` to the repository root.
4. Start Langflow from the repository root.
5. Import `flows/evidence_verification_flow.json`.

## When you want to change the flow

- Change the node implementation: edit the matching file in `src/langflow_components/`.
- Change the live app/API behavior: keep `src/orchestration/langflow_first_pass.py` aligned with the component chain.
- Change the visual flow: update `flows/evidence_verification_flow.json` so the diagram still matches the runtime.
