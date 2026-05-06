"""Build manuscript artifacts for the ePlacement KYC verifier v4.1 validation."""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

import pandas as pd
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt


HERE = Path(__file__).resolve().parent
WORKBOOK = Path(r"C:\Users\vivek\Downloads\eplacement_kyc_validation_analysis_v4_1.xlsx")
MANUSCRIPT_MD = HERE / "MANUSCRIPT.md"
OUTPUT_DOCX = HERE / "eplacement_kyc_verifier_v4_1_validation_manuscript.docx"
TABLES_DIR = HERE / "tables"
SUMMARY_JSON = HERE / "validation_summary.json"


def wilson_interval(successes: int, total: int, z: float = 1.96) -> dict[str, float]:
    if total <= 0:
        return {"estimate": 0.0, "lower": 0.0, "upper": 0.0}
    p = successes / total
    denom = 1 + z**2 / total
    center = (p + z**2 / (2 * total)) / denom
    half_width = z * math.sqrt((p * (1 - p) + z**2 / (4 * total)) / total) / denom
    return {"estimate": p, "lower": center - half_width, "upper": center + half_width}


def clean_key(value: object) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value).strip().casefold()).strip("_")


def extract_validation_tables() -> None:
    """Extract small, de-identified validation summaries from the final workbook."""

    if not WORKBOOK.exists():
        raise FileNotFoundError(f"Validation workbook not found: {WORKBOOK}")

    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    by_evidence = pd.read_excel(WORKBOOK, sheet_name="By evidence")
    comparison = pd.read_excel(WORKBOOK, sheet_name="v4 comparison")
    review_flag = pd.read_excel(WORKBOOK, sheet_name="Review flag")
    summary_raw = pd.read_excel(WORKBOOK, sheet_name="Summary", header=None)

    by_evidence.to_csv(TABLES_DIR / "by_evidence.csv", index=False)
    comparison.to_csv(TABLES_DIR / "v4_comparison.csv", index=False)
    review_flag.to_csv(TABLES_DIR / "review_flag.csv", index=False)

    summary_lookup: dict[str, object] = {}
    for _, row in summary_raw.iterrows():
        key = row.iloc[0]
        value = row.iloc[1] if len(row) > 1 else None
        if pd.notna(key) and pd.notna(value):
            summary_lookup[clean_key(key)] = value.item() if hasattr(value, "item") else value

    total_decisions = int(summary_lookup.get("binary_decisions", 0))
    tp = int(summary_lookup.get("tp", 0))
    fp = int(summary_lookup.get("fp", 0))
    tn = int(summary_lookup.get("tn", 0))
    fn = int(summary_lookup.get("fn", 0))
    applicants = int(summary_lookup.get("applicants_matched", 0))
    exact_matches = int(summary_lookup.get("exact_applicant_matches", 0))
    review_flagged = int(summary_lookup.get("review_flagged_applicants", 0))

    validation_summary = {
        "source_workbook": str(WORKBOOK),
        "model_evaluated": summary_lookup.get("model_evaluated"),
        "validation_set": summary_lookup.get("validation_set"),
        "applicants_matched": applicants,
        "binary_decisions": total_decisions,
        "confusion_matrix": {"tp": tp, "fp": fp, "tn": tn, "fn": fn},
        "metrics": {
            "accuracy": summary_lookup.get("accuracy"),
            "sensitivity_recall": summary_lookup.get("sensitivity_recall"),
            "specificity": summary_lookup.get("specificity"),
            "ppv_precision": summary_lookup.get("ppv_precision"),
            "npv": summary_lookup.get("npv"),
            "f1_score": summary_lookup.get("f1_score"),
            "exact_applicant_match_rate": summary_lookup.get("exact_applicant_match"),
            "review_rate": summary_lookup.get("review_rate"),
        },
        "descriptive_wilson_intervals": {
            "accuracy": wilson_interval(tp + tn, total_decisions),
            "sensitivity_recall": wilson_interval(tp, tp + fn),
            "specificity": wilson_interval(tn, tn + fp),
            "ppv_precision": wilson_interval(tp, tp + fp),
            "npv": wilson_interval(tn, tn + fn),
            "exact_applicant_match_rate": wilson_interval(exact_matches, applicants),
            "manual_review_rate": wilson_interval(review_flagged, applicants),
        },
        "conclusion": summary_lookup.get("conclusion"),
    }
    SUMMARY_JSON.write_text(json.dumps(validation_summary, indent=2), encoding="utf-8")


def split_table_row(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def is_table_separator(line: str) -> bool:
    cells = split_table_row(line)
    return bool(cells) and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells)


def add_markdown_table(document: Document, lines: list[str]) -> None:
    rows = [split_table_row(line) for line in lines if not is_table_separator(line)]
    if not rows:
        return
    width = max(len(row) for row in rows)
    table = document.add_table(rows=len(rows), cols=width)
    table.style = "Table Grid"
    for row_idx, row in enumerate(rows):
        for col_idx in range(width):
            cell_text = row[col_idx] if col_idx < len(row) else ""
            paragraph = table.cell(row_idx, col_idx).paragraphs[0]
            run = paragraph.add_run(cell_text)
            if row_idx == 0:
                run.bold = True
            if col_idx > 0:
                paragraph.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    document.add_paragraph()


def add_paragraph_with_basic_formatting(document: Document, text: str, style: str | None = None) -> None:
    paragraph = document.add_paragraph(style=style)
    cursor = 0
    for match in re.finditer(r"\*\*(.+?)\*\*", text):
        if match.start() > cursor:
            paragraph.add_run(text[cursor : match.start()])
        bold_run = paragraph.add_run(match.group(1))
        bold_run.bold = True
        cursor = match.end()
    if cursor < len(text):
        paragraph.add_run(text[cursor:])


def build_docx() -> None:
    document = Document()
    section = document.sections[0]
    section.top_margin = Inches(0.7)
    section.bottom_margin = Inches(0.7)
    section.left_margin = Inches(0.75)
    section.right_margin = Inches(0.75)

    styles = document.styles
    styles["Normal"].font.name = "Aptos"
    styles["Normal"].font.size = Pt(10)
    for style_name, size in [("Heading 1", 16), ("Heading 2", 13), ("Heading 3", 11)]:
        styles[style_name].font.name = "Aptos"
        styles[style_name].font.size = Pt(size)

    lines = MANUSCRIPT_MD.read_text(encoding="utf-8").splitlines()
    table_buffer: list[str] = []

    def flush_table() -> None:
        nonlocal table_buffer
        if table_buffer:
            add_markdown_table(document, table_buffer)
            table_buffer = []

    for raw_line in lines:
        line = raw_line.rstrip()
        if line.startswith("|"):
            table_buffer.append(line)
            continue
        flush_table()
        if not line.strip():
            continue
        if line.startswith("# "):
            document.add_heading(line[2:].strip(), level=0)
        elif line.startswith("## "):
            document.add_heading(line[3:].strip(), level=1)
        elif line.startswith("### "):
            document.add_heading(line[4:].strip(), level=2)
        elif line.startswith("- "):
            add_paragraph_with_basic_formatting(document, line[2:].strip(), style="List Bullet")
        elif re.match(r"^\d+\.\s+", line):
            add_paragraph_with_basic_formatting(document, re.sub(r"^\d+\.\s+", "", line), style="List Number")
        else:
            add_paragraph_with_basic_formatting(document, line)
    flush_table()

    document.save(OUTPUT_DOCX)


def main() -> None:
    extract_validation_tables()
    build_docx()
    print(f"Wrote {OUTPUT_DOCX}")
    print(f"Wrote {SUMMARY_JSON}")
    print(f"Wrote CSV tables to {TABLES_DIR}")


if __name__ == "__main__":
    main()
