#!/usr/bin/env bash
set -euo pipefail

python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt

echo "Install system prerequisites separately: Tesseract OCR, Ghostscript, and OCRmyPDF dependencies."
