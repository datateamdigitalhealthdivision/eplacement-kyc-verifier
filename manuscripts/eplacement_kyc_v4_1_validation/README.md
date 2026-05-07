# ePlacement KYC verifier v4.1 manuscript

This folder contains the manuscript draft for the final validation of the eplacement-kyc-verifier v4.1 algorithm.

## Contents

- `MANUSCRIPT.md`: source manuscript in Markdown.
- `build_manuscript.py`: local builder that extracts validation summary tables and generates a DOCX manuscript.
- `figures/`: generated manuscript figures showing the problem frame, evidence taxonomy, workflow, AI harness, method shift, validation performance, and review funnel.
- `editable_figures_1_4.pptx`: editable PowerPoint version of Figures 1-4, built with native PPT shapes and text.
- `validation_summary.json`: generated validation metrics extracted from the final validation workbook.
- `tables/`: generated CSV copies of key validation tables.
- `eplacement_kyc_verifier_v4_1_validation_manuscript.docx`: generated Word manuscript.

## Source Files Used

- `C:/Users/vivek/Downloads/eplacement_kyc_validation_analysis_v4_1.xlsx`
- `C:/Users/vivek/Downloads/Landscape Review for eplacement-kyc-verifier.docx`
- `C:/codex/ascertainment_c19_2026/soul.md`

Raw applicant PDFs, downloaded evidence files, OCR caches, and working databases are intentionally not copied into this folder.
Applicant-level error exports with IC-like identifiers are also intentionally excluded from the committed manuscript artifacts.

## Rebuild

From the repository root:

```powershell
.\.venv\Scripts\python.exe -m pip install -r .\manuscripts\eplacement_kyc_v4_1_validation\requirements.txt
.\.venv\Scripts\python.exe .\manuscripts\eplacement_kyc_v4_1_validation\build_manuscript.py
.\.venv\Scripts\python.exe .\manuscripts\eplacement_kyc_v4_1_validation\build_editable_figures_pptx.py
```
