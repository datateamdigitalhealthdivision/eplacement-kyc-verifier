# Scripts

These scripts are intentionally thin wrappers. The real logic lives in `src/` and `app/`.

## Setup

- `setup_env.ps1`
- `setup_env.sh`

Creates the virtual environment and installs dependencies.

## Runtime

- `run_backend.ps1`
- `run_backend.sh`

Starts the FastAPI backend.

- `run_streamlit.ps1`
- `run_streamlit.sh`

Starts the single-page Streamlit operator UI.

## Models

- `pull_models.ps1`
- `pull_models.sh`

Pulls the local Ollama models defined for the repo.

## Operations

- `reprocess_failed.py`

Re-runs the pipeline for applicants that failed in the latest job.

## Design rule

If you want to change behavior, change the Python modules under `src/` or `app/` first. These scripts should stay simple launch helpers.
