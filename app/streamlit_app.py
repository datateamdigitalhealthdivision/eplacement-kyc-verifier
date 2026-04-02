"""Streamlit entrypoint for the first-pass operator UI."""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.ui.data_access import initialize_session_state
from app.ui.sections import render_check_section, render_run_section, render_upload_section


st.set_page_config(page_title="ePlacement KYC First Pass", layout="wide", initial_sidebar_state="collapsed")
initialize_session_state()

st.title("ePlacement KYC First Pass")
st.caption("Upload the applicant file, run the first-pass document detector, and review one simple table of results.")
render_upload_section()
st.divider()
render_run_section()
st.divider()
render_check_section()
