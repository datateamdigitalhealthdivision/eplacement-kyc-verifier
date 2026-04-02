#!/usr/bin/env bash
set -euo pipefail

source .venv/bin/activate
if [[ "${UVICORN_RELOAD:-0}" == "1" ]]; then
  .venv/bin/python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000 --reload
else
  .venv/bin/python -m uvicorn src.api.main:app --host 127.0.0.1 --port 8000
fi
