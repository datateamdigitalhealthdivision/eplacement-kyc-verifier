# Repository Guide

This repository is organized around three entry points:

- `app/`: the Streamlit operator UI
- `src/`: the reusable pipeline, OCR, rules, exports, API, and Langflow components
- `scripts/`: thin launch/setup helpers for common local tasks

## How a run moves through the codebase

1. `app/streamlit_app.py` is the Streamlit entrypoint.
2. `app/bootstrap.py` builds the shared `PipelineService` used by the UI.
3. `app/ui/sections.py` renders the three visible parts of the operator flow: Upload, Run, and Check.
4. `app/ui/data_access.py` handles spreadsheet discovery, upload persistence, preview reads, and decision-queue loading.
5. `src/services/pipeline_service.py` is the facade used by Streamlit and FastAPI.
6. `src/services/batch_processor.py` orchestrates the full run:
   - spreadsheet load
   - PDF locate / download
   - OCR
   - multimodal classification
   - extraction
   - deterministic validation
   - merge + export
7. `src/io/`, `src/ocr/`, `src/classification/`, `src/extraction/`, and `src/rules/` hold the implementation details for each stage.
8. `src/reports/decision_queue.py` builds the first-pass operator queue.
9. `src/io/exporters.py` writes the CSV/XLSX/JSON outputs.

## Where Ollama and Qwen run

- Model names live in `config/app_config.yaml`.
- `src/settings.py` loads them into the runtime config.
- `src/llm/ollama_client.py` is the only place that talks to the Ollama HTTP API.
- `src/ocr/ocr_router.py` renders page images and stores them on the OCR document.
- `src/classification/doc_classifier.py` uses `qwen2.5vl:7b` when page images are available.
- `src/extraction/marriage_extractor.py`, `src/extraction/medex_extractor.py`, and `src/extraction/generic_extractor.py` use the same vision path for field extraction.
- If vision is unavailable, the code falls back to the text model `qwen2.5:7b-instruct`, and then to heuristics.

## Where to look when changing behavior

- Change uploaded-file handling or the first-pass table: `app/ui/`
- Change OCR behavior or image generation: `src/ocr/`
- Change document typing: `src/classification/`
- Change extracted fields: `src/extraction/`
- Change truth-check logic: `src/rules/`
- Change exported queue shape: `src/reports/decision_queue.py`
- Change orchestration: `src/services/batch_processor.py`

## Project layout

```text
app/                    Streamlit UI entrypoint and UI modules
config/                 YAML configuration and column mapping
data/                   Inputs, working files, and exported outputs
docs/                   Human-facing project and architecture documentation
flows/                  Langflow flow JSON and thin flow-specific notes
scripts/                Setup and run helpers
src/                    Reusable backend and pipeline code
tests/                  Unit and smoke tests
```

## Repo hygiene notes

- Working files and generated outputs should not be committed.
- Real applicant spreadsheets and downloaded PDFs should stay out of git.
- The sample assets under `data/input/samples/` are the only intended checked-in demo inputs.
- The root `.gitignore` is set up for that workflow.


