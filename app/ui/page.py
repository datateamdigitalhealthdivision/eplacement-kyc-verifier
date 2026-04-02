"""Page composition for the Streamlit first-pass UI."""

from __future__ import annotations

import streamlit as st

from app.ui.data_access import initialize_session_state
from app.ui.sections import render_check_section, render_run_section, render_upload_section


def render_page() -> None:
    st.set_page_config(page_title="ePlacement KYC First Pass", layout="wide", initial_sidebar_state="collapsed")
    initialize_session_state()

    st.title("ePlacement KYC First Pass")
    st.caption("Upload the applicant file, run the first-pass document detector, and review one simple table of results.")
    render_upload_section()
    st.divider()
    render_run_section()
    st.divider()
    render_check_section()
