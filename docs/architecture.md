# Repository Guide

This repository is now organized around one main runtime idea: the app and API run the job through the same Langflow-shaped chain that is defined in the flow JSON and custom components.

## How a run moves through the codebase

1. `app/streamlit_app.py` is the Streamlit entrypoint.
2. `app/bootstrap.py` builds the shared `PipelineService` used by the UI.
3. `app/ui/sections.py` renders the three visible parts of the operator flow: Upload, Run, and Check.
4. `app/ui/data_access.py` handles spreadsheet discovery, upload persistence, preview reads, and decision-queue loading.
5. `src/services/pipeline_service.py` is the facade used by Streamlit and FastAPI.
6. `src/orchestration/langflow_first_pass.py` is the live orchestration runner.
7. `src/langflow_components/` holds the step-by-step component chain used by that runner:
   - Applicant Loader
   - PDF Fetch
   - OCR Router
   - Doc Classifier
   - Evidence Extractor
   - Rules Validator
   - Export Writer
8. `src/orchestration/result_builder.py` assembles shared result rows and summaries for the flow.
9. `src/io/`, `src/ocr/`, `src/classification/`, `src/extraction/`, and `src/rules/` hold the lower-level implementation details for each step.
10. `src/reports/decision_queue.py` builds the first-pass operator queue.
11. `src/io/exporters.py` writes the CSV/XLSX/JSON outputs.

## Live orchestration vs legacy path

- `src/orchestration/langflow_first_pass.py` is the primary runtime path used by the app and API.
- `flows/evidence_verification_flow.json` is the visual version of that same chain.
- `src/services/batch_processor.py` is still in the repo as a direct Python orchestration path for regression testing, comparison, and emergency fallback work. It is no longer the main story of the repo.

## Where Ollama and Qwen run

- Model names live in `config/app_config.yaml`.
- `src/settings.py` loads them into runtime config.
- `src/llm/ollama_client.py` is the only place that talks to the Ollama HTTP API.
- `src/ocr/ocr_router.py` renders page images and stores them on the OCR document.
- `src/classification/doc_classifier.py` uses `qwen2.5vl:7b` when page images are available.
- `src/extraction/marriage_extractor.py`, `src/extraction/medex_extractor.py`, and `src/extraction/generic_extractor.py` use the same vision path for field extraction.
- If vision is unavailable, the code falls back to the text model `qwen2.5:7b-instruct`, and then to heuristics.

## Where to look when changing behavior

- Change uploaded-file handling or the first-pass table: `app/ui/`
- Change flow sequencing or shared run assembly: `src/orchestration/`
- Change Langflow node contracts: `src/langflow_components/`
- Change OCR behavior or image generation: `src/ocr/`
- Change document typing: `src/classification/`
- Change extracted fields: `src/extraction/`
- Change truth-check logic: `src/rules/`
- Change exported queue shape: `src/reports/decision_queue.py`
- Change the legacy direct runner: `src/services/batch_processor.py`

## Project layout

```text
app/                    Streamlit UI entrypoint and UI modules
config/                 YAML configuration and column mapping
data/                   Inputs, working files, and exported outputs
docs/                   Human-facing project and architecture documentation
flows/                  Langflow flow JSON and thin flow-specific notes
scripts/                Setup and run helpers
src/                    Reusable backend, orchestration, and pipeline code
tests/                  Unit and smoke tests
```

## Repo hygiene notes

- Working files and generated outputs should not be committed.
- Real applicant spreadsheets and downloaded PDFs should stay out of git.
- The sample assets under `data/input/samples/` are the only intended checked-in demo inputs.
- The root `.gitignore` is set up for that workflow.
