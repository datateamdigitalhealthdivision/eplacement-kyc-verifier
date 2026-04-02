#!/usr/bin/env bash
set -euo pipefail

source .venv/bin/activate
export PYTHONPATH="$(pwd):${PYTHONPATH:-}"
export STREAMLIT_SERVER_FILE_WATCHER_TYPE="none"
export STREAMLIT_SERVER_RUN_ON_SAVE="false"
.venv/bin/python -m streamlit run app/streamlit_app.py
