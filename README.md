# eplacement-kyc-verifier

`eplacement-kyc-verifier` is a local-first KYC document triage tool for ePlacement. It takes an applicant spreadsheet, finds or downloads the supporting PDF for each applicant, runs OCR plus multimodal document detection, and returns a simple first-pass queue showing which document types appear to be present.

## What this repo contains

- A single-page Streamlit operator UI for `Upload -> Run -> Check`
- A FastAPI backend for jobs, health, review records, and exports
- A reusable Python pipeline under `src/`
- Optional Langflow components and an importable flow JSON for visual orchestration
- Local SQLite audit storage and CSV/XLSX/JSON exports

## Start here

- Project architecture: [docs/architecture.md](docs/architecture.md)
- Langflow walkthrough: [docs/langflow.md](docs/langflow.md)
- Script catalog: [scripts/README.md](scripts/README.md)
- Flow notes: [flows/README.md](flows/README.md)

## Quick start

### 1. Create the environment

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/setup_env.ps1
```

Unix shell:

```bash
bash scripts/setup_env.sh
```

### 2. Start the backend

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_backend.ps1
```

Unix shell:

```bash
bash scripts/run_backend.sh
```

### 3. Start the operator UI

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/run_streamlit.ps1
```

Unix shell:

```bash
bash scripts/run_streamlit.sh
```

### 4. Optional: use Langflow

Import `flows/evidence_verification_flow.json` after reading [docs/langflow.md](docs/langflow.md).

## Repository layout

```text
app/                    Streamlit entrypoint and UI modules
config/                 App config and column mapping
data/input/samples/     Safe demo assets
docs/                   Project documentation
flows/                  Langflow flow definition
scripts/                Setup and launch helpers
src/                    Reusable pipeline code
tests/                  Unit and smoke tests
```

## Runtime notes

- The Streamlit app is single-page and intentionally simple.
- Langflow is optional and is kept thin on purpose.
- Real applicant data, generated outputs, caches, and logs should stay out of git.
- The root `.gitignore` is set up for a repo-first workflow.

## Testing

```bash
pytest
```


