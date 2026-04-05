"""Render functions for the Streamlit first-pass UI."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from app.bootstrap import SERVICE, SETTINGS
from app.ui.data_access import (
    decision_dataframe,
    latest_bundle,
    latest_job,
    read_preview_frame,
    save_upload,
    validate_applicant_path,
)
from src.db.models import RunJobRequest



def _decision_column_config() -> dict:
    return {
        "applicant_id": st.column_config.TextColumn("Applicant ID"),
        "marriage": st.column_config.TextColumn("Marriage"),
        "self_illness": st.column_config.TextColumn("Self Illness"),
        "family_illness": st.column_config.TextColumn("Family Illness"),
        "spouse_location": st.column_config.TextColumn("Spouse Location"),
        "oku_self_or_family": st.column_config.TextColumn("OKU Self / Family"),
        "medex_other_exam": st.column_config.TextColumn("MedEX / Other Exam"),
        "check_required": st.column_config.TextColumn("Check?"),
        "open_original_pdf": st.column_config.LinkColumn("Open PDF", help="Open the original PDF URL from the uploaded spreadsheet."),
        "source_pdf_name": st.column_config.TextColumn("File Name"),
    }



def render_upload_section() -> None:
    st.subheader("1. Upload")
    uploaded = st.file_uploader("Applicant CSV/XLSX", type=["csv", "xlsx", "xls"])
    saved_path = save_upload(uploaded)
    if saved_path:
        st.session_state["applicant_path"] = saved_path

    st.text_input("Spreadsheet path", key="applicant_path")
    st.text_input("PDF folder", key="pdf_directory")
    st.checkbox("Auto-download missing PDFs from URL column", key="auto_download")

    applicant_path = Path(str(st.session_state.get("applicant_path", "")))
    if applicant_path.exists() and applicant_path.is_file():
        with st.expander("Preview uploaded spreadsheet", expanded=False):
            try:
                st.dataframe(read_preview_frame(applicant_path), width="stretch", hide_index=True)
            except Exception as exc:  # noqa: BLE001
                st.warning(f"Could not preview spreadsheet: {exc}")



def render_run_section() -> None:
    st.subheader("2. Run")
    if st.button("Run First Pass", width="stretch"):
        applicant_path = str(st.session_state.get("applicant_path", "")).strip()
        pdf_directory = str(st.session_state.get("pdf_directory", SETTINGS.paths.pdf_dir))
        auto_download = bool(st.session_state.get("auto_download", True))
        validation_error = validate_applicant_path(applicant_path)
        if validation_error:
            st.error(validation_error)
        else:
            with st.spinner("Running first-pass verification..."):
                try:
                    job = SERVICE.run_job(
                        RunJobRequest(applicant_path=applicant_path, pdf_directory=pdf_directory, auto_download=auto_download),
                        background=False,
                    )
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Verification failed: {exc}")
                else:
                    st.session_state["last_job_id"] = job.job_id if job else ""
                    st.success(f"Finished job {job.job_id}")

    job = latest_job()
    if job:
        st.caption(f"Latest job: {job.job_id} | {job.progress_completed}/{job.progress_total} processed")



def render_check_section() -> None:
    st.subheader("3. Check")
    current_job = latest_job()
    job_id = st.session_state.get("last_job_id") or (current_job.job_id if current_job else None)
    bundle = latest_bundle(job_id)
    queue_df = decision_dataframe(bundle)
    if queue_df is None or queue_df.empty:
        st.info("Run the first pass to see the applicant queue.")
        return

    check_counts = queue_df["check_required"].value_counts()
    metric_cols = st.columns(3)
    metric_cols[0].metric("Applicants", len(queue_df))
    metric_cols[1].metric("Check", int(check_counts.get("check", 0)))
    metric_cols[2].metric("No Check", int(check_counts.get("no_check", 0)))

    download_cols = st.columns(2)
    if bundle and bundle.decision_csv and Path(bundle.decision_csv).exists():
        download_cols[0].download_button(
            "Download CSV",
            data=Path(bundle.decision_csv).read_bytes(),
            file_name=Path(bundle.decision_csv).name,
        )
    if bundle and bundle.decision_xlsx and Path(bundle.decision_xlsx).exists():
        download_cols[1].download_button(
            "Download XLSX",
            data=Path(bundle.decision_xlsx).read_bytes(),
            file_name=Path(bundle.decision_xlsx).name,
        )

    only_check = st.checkbox("Show only rows that need checking", value=False)
    visible_df = queue_df[queue_df["check_required"] == "check"] if only_check else queue_df
    st.dataframe(visible_df, width="stretch", hide_index=True, column_config=_decision_column_config())
