# Input Table Template

Use [applicant_input_template.csv](/C:/codex/eplacement_fraud-detector-v1/eplacement-kyc-verifier/data/input/samples/applicant_input_template.csv) as the easiest starting point.

## Minimum required

Only one column is strictly required:

| Column | Meaning |
| --- | --- |
| `NO KP` | Applicant NRIC / ID |

## Recommended columns

These materially improve first-pass accuracy:

| Column | Why it helps |
| --- | --- |
| `NAMA` | Helps match the document subject to the applicant |
| `MARITAL_STATUS` | Tells the flow whether marriage evidence is expected |
| `Nama Pasangan` | Helps spouse-location and family-illness detection |
| `NoKPPasangan` | Stronger spouse matching when visible in the PDF |
| `POSTGRADUATE_PAPER_STATUS` | Tells the flow whether MedEX / exam evidence is expected |
| `PERSONAL_HEALTH_CONDITION` | Gives applicant health context |
| `Keterangan Kesihatan` | More detail for applicant health context |
| `StatusOKU` | Helps interpret OKU evidence |
| `SPOUSE_EMPLOYMENT_STATUS` | Helps spouse-location reasoning |
| `Pekerjaan Pasangan` | Helps spouse-location reasoning |
| `Alamat Bekerja Pasangan` | Helps spouse-location reasoning |
| `NegeriBekerjaPasangan` | Helps spouse-location reasoning |
| `SPOUSE_STATUS_OKU` | Helps spouse/family OKU reasoning |
| `SPOUSE_HEALTH_CONDITION` | Helps family-illness reasoning |
| `Keterangan Masalah Kesihatan Pasanga` | More detail for spouse/family illness reasoning |
| `Sheet1.NamaFail` | Lets the app find the PDF by filename |
| `Sheet1.DownloadURL` | Lets the app download the PDF if it is missing locally |

## Good defaults

- Use `BERKAHWIN` or `BUJANG` for `MARITAL_STATUS`
- Use `Ada` or `Tiada` for health / OKU style flags where possible
- Use `Bekerja` for employed spouse rows where relevant
- Use `Tidak Berkenaan` when postgraduate / MedEX does not apply
- Put the actual PDF filename in `Sheet1.NamaFail`, for example `930620115062.pdf`
- Put the original source link in `Sheet1.DownloadURL` whenever possible

## Notes

- The app accepts aliases, but using the exact column names in the template is safest.
- Blank cells are fine for fields that do not apply.
- If `NO KP` is stored in Excel, format that column as text to avoid scientific notation.
