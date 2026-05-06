# Validation of a local-first claim-guided document evidence verifier for Malaysian ePlacement applications: a retrospective diagnostic accuracy study

Draft author: Vivek Jason Jayaraj and collaborators  
Draft date: 2026-05-06  
Repository branch: feature/manuscript-v4-1-validation  
Algorithm version evaluated: eplacement-kyc-verifier v4.1

## Structured Abstract

### Background

Administrative placement systems often require applicants to upload documentary evidence for family, health, disability, marital, spouse-location, and professional examination claims. In practice, these checks are document-heavy, multilingual, and difficult to standardise. Commercial electronic know-your-customer (e-KYC) systems increasingly automate identity proofing, but they are usually built around identity documents, biometrics, liveness checks, and vendor-controlled infrastructure. Less is known about local-first evidence verification systems designed for public-sector administrative workflows where the objective is not full identity proofing, but rapid, auditable triage of whether claimed evidence is supported by uploaded documents.

### Objective

We aimed to validate a local-first, claim-guided document evidence verifier for Malaysian ePlacement applications, focusing on whether the system could identify uploaded proof for six applicant-claimed evidence categories while reducing manual review workload.

### Methods

We conducted a retrospective validation study using a manually adjudicated reference set of 238 applicants. Each applicant contributed six evidence-level binary decisions: marriage, self illness, family illness, spouse location, OKU self or family, and MedEX or other examination evidence, yielding 1,428 binary decisions. The evaluated system ingested applicant spreadsheet data, extracted claimed evidence categories, retrieved and rendered supporting PDFs, routed text extraction through direct PDF text and optical character recognition (OCR), and applied a claim-guided evidence verification workflow using deterministic rules and local language/vision model support. We assessed sensitivity, specificity, positive predictive value (PPV), negative predictive value (NPV), F1 score, exact applicant-level agreement, and manual review burden.

### Results

Across 1,428 evidence-level decisions, the verifier produced 415 true positives, 103 false positives, 856 true negatives, and 54 false negatives. Overall accuracy was 89.0%, sensitivity was 88.5%, specificity was 89.3%, PPV was 80.1%, NPV was 94.1%, and F1 score was 84.1%. Exact applicant-level agreement, defined as all six evidence classes matching the manual reference standard for a given applicant, was 118/238 (49.6%). The system flagged 64/238 applicants for manual review, corresponding to a manual review rate of 26.9% and a potential first-pass clearance rate of 73.1%. Performance varied by evidence type: marriage evidence had high precision and F1 score, while family illness and spouse-location evidence accounted for most false-positive burden. Version 4.1 produced the same predictions and check-required flags as version 4, but added proof-strength and audit fields for downstream review.

### Conclusion

The validated system showed substantial improvement over early broad-classification versions and achieved decision-level performance consistent with a useful first-pass triage tool. However, residual applicant-level disagreement and incomplete capture of residual errors by the review flag mean it should not be deployed as an autonomous adjudication system. The appropriate near-term use case is AI-assisted evidence triage with structured audit, targeted manual review, and ongoing recalibration.

Keywords: document AI; e-KYC; administrative evidence verification; OCR; multimodal language models; human-in-the-loop review; Malaysia; digital epidemiology

## Introduction

Administrative placement decisions increasingly depend on structured applicant-declared information and unstructured supporting documents. In the Malaysian ePlacement context, applicants may submit evidence relating to marriage, spouse location, personal illness, family illness, OKU or disability status, and postgraduate or MedEX-related examination obligations. These domains are consequential because they influence placement prioritisation and require trust in both applicant declarations and uploaded evidence. However, the operational reality is difficult: supporting documents are heterogeneous, often multilingual, variably scanned, and frequently bundled into multi-page PDFs containing unrelated or partially related evidence.

Manual review remains the default control for these workflows. It is interpretable and flexible, but it is also slow, repetitive, vulnerable to fatigue, and hard to scale consistently. A naive automation approach can perform poorly for two reasons. First, a broad document classifier may label any plausible evidence type it sees, even when the applicant did not claim that category. Second, a language or vision model may appear confident while missing visually obvious but OCR-poor documents, such as scanned marriage certificates or documents using non-Latin scripts. These failure modes are especially relevant in public-sector settings where documents may include Bahasa Malaysia, English, Jawi or Arabic-script text, and other regional language content.

The term e-KYC is often used broadly, but the task evaluated here is narrower than full remote identity proofing. Full e-KYC systems typically include identity document authenticity checks, biometric face matching, liveness or presentation attack detection, sanctions or watchlist screening, device intelligence, and risk scoring. The eplacement-kyc-verifier system is better understood as a local-first administrative evidence verification tool with e-KYC relevance. Its immediate purpose is to help operators determine whether applicant-claimed evidence appears to be supported by uploaded PDFs, while preserving a human-review pathway and audit trail.

We aimed to evaluate the final v4.1 validation of this verifier against a manually adjudicated reference set. The primary scientific question was whether a claim-guided approach could provide useful evidence-level classification performance while reducing the number of applicants requiring manual review. The secondary question was whether the system's review flag was sufficiently conservative to identify uncertain or problematic cases for human adjudication.

## Objectives

The objectives were:

- To estimate evidence-level sensitivity, specificity, PPV, NPV, accuracy, and F1 score for the v4.1 verifier across six evidence categories.
- To estimate applicant-level exact agreement across the full six-category evidence vector.
- To quantify the manual review burden generated by the system.
- To characterise performance by evidence type and identify residual failure modes relevant to operational deployment.
- To frame the system honestly within the broader digital identity and document AI landscape, distinguishing administrative evidence triage from full-stack e-KYC.

## Methods

### Study Design

We conducted a retrospective validation study of the eplacement-kyc-verifier v4.1 algorithm. The unit of primary analysis was the evidence-level binary decision. Each applicant could contribute one binary decision for each of six evidence categories, resulting in six decisions per applicant. Applicant-level agreement was assessed separately because an applicant could be correct for some evidence categories and incorrect for others.

### Setting and Workflow Context

The workflow was designed for Malaysian ePlacement document review. Applicant data were provided as a structured spreadsheet, and supporting documents were provided as uploaded PDF links or local PDF paths. The operational goal was first-pass triage: identify applicants whose claimed evidence appeared sufficiently supported by uploaded documents, and route uncertain or unsupported cases to manual review.

### Evidence Categories

The six evidence categories were:

- Marriage: clear evidence of marriage or spouse relationship, including marriage or nikah certificates.
- Self illness: medical or health evidence relating to the applicant.
- Family illness: medical or health evidence relating to a spouse, child, parent, dependent, or other relevant family member.
- Spouse location: evidence of spouse workplace, posting, residence, or location relevant to placement.
- OKU self or family: official OKU or disability evidence for the applicant or relevant family member.
- MedEX or other examination: evidence of MedEX, postgraduate examination, specialist training examination, entrance examination, examination attendance, result, certificate, or official registration. Routine physical examination, general medical check-up, and generic medical reports were not treated as MedEX evidence.

### Index System

The evaluated system is a local-first verifier implemented as a Python application with a Streamlit operator interface, Langflow-shaped orchestration, local file-based inputs and outputs, and local model execution through Ollama. The relevant v4.1 workflow used a claim-guided design. It first parsed the applicant spreadsheet row into claimed evidence booleans, then verified only categories claimed by the applicant. Unclaimed categories were not treated as positive evidence targets.

The core processing path was:

1. Applicant spreadsheet ingestion and column normalisation.
2. Claim extraction from structured applicant fields.
3. Supporting PDF acquisition from the uploaded document link or local path.
4. PDF text extraction and page rendering.
5. OCR routing using direct PDF text where possible, with OCR fallback for scanned or low-text pages.
6. Claim-guided evidence signal generation using deterministic rules, OCR-derived signals, and local language/vision model support.
7. Export of decision queues, scoring sheets, final tick sheets, merged outputs, and audit fields.

Version 4.1 added proof-strength and page-level audit fields while preserving the v4 prediction labels and check-required flags. The validation workbook confirmed that v4.1 output was identical to v4 for predictions and check-required flags.

### Reference Standard

The reference standard was a manually validated dataset supplied as the final validation workbook. Manual validation classified each applicant-evidence category as present or absent. The analysis compared the algorithmic output against this manual reference standard across six evidence categories for each matched applicant.

### Outcomes

The primary outcomes were evidence-level true positives, false positives, true negatives, and false negatives. From these counts, we calculated accuracy, sensitivity, specificity, PPV, NPV, and F1 score. Secondary outcomes included exact applicant-level match, defined as all six evidence-category predictions matching the manual reference standard for an applicant, and the proportion of applicants flagged for manual review.

### Statistical Analysis

We calculated decision-level performance metrics using standard 2 x 2 classification definitions. Because each applicant contributed six evidence-level observations, evidence-level metrics should be interpreted as clustered descriptive summaries rather than independent observations. Where confidence intervals are reported, they use approximate Wilson intervals and should be interpreted as descriptive. Future submission-ready analysis should use applicant-clustered bootstrap intervals.

### Governance and Privacy

This manuscript draft is based on derived validation metrics and does not include raw applicant PDFs or identifiable applicant documents. The repository should continue to exclude raw applicant data, downloaded PDFs, OCR caches, local databases, and generated working files from version control. Formal ethics, data protection, and information governance statements should be added before external submission or operational deployment.

## Results

### Validation Set

The validation set included 238 matched applicants. Since each applicant was evaluated across six evidence categories, the total number of evidence-level binary decisions was 1,428.

### Overall Evidence-Level Performance

The verifier produced 415 true positives, 103 false positives, 856 true negatives, and 54 false negatives. Overall decision-level accuracy was 89.0%. Sensitivity was 88.5%, indicating that most manually confirmed evidence-positive categories were detected by the system. Specificity was 89.3%, indicating good discrimination among evidence-negative categories. PPV was 80.1%, NPV was 94.1%, and F1 score was 84.1%.

| Metric | Result |
| --- | ---: |
| Applicants matched | 238 |
| Evidence-level binary decisions | 1,428 |
| True positives | 415 |
| False positives | 103 |
| True negatives | 856 |
| False negatives | 54 |
| Accuracy | 89.0% |
| Sensitivity / recall | 88.5% |
| Specificity | 89.3% |
| PPV / precision | 80.1% |
| NPV | 94.1% |
| F1 score | 84.1% |
| Exact applicant-level matches | 118 / 238 (49.6%) |
| Applicants flagged for manual review | 64 / 238 (26.9%) |
| Applicants not flagged for manual review | 174 / 238 (73.1%) |

### Performance by Evidence Type

Performance varied materially by evidence type. Marriage evidence performed strongly, with sensitivity of 88.8%, specificity of 98.9%, PPV of 99.2%, and F1 score of 93.7%. MedEX or other examination evidence also performed well, with sensitivity of 91.4%, specificity of 87.9%, PPV of 79.6%, and F1 score of 85.1%.

The most difficult categories were family illness and spouse location. Family illness achieved sensitivity of 83.9% but specificity of 69.5%, with 46 false positives. Spouse location achieved very high sensitivity of 98.1%, but specificity was 75.4%, with 32 false positives. This pattern suggests that the system was tuned toward recall for relational evidence, but at the cost of over-calling some family or spouse-location documents.

| Evidence type | Manual positives | AI positives | TP | FP | TN | FN |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Marriage | 143 | 128 | 127 | 1 | 94 | 16 |
| Self illness | 35 | 28 | 24 | 4 | 199 | 11 |
| Family illness | 87 | 119 | 73 | 46 | 105 | 14 |
| Spouse location | 108 | 138 | 106 | 32 | 98 | 2 |
| OKU self or family | 15 | 12 | 11 | 1 | 222 | 4 |
| MedEX or other exam | 81 | 93 | 74 | 19 | 138 | 7 |

| Evidence type | Accuracy | Sensitivity | Specificity | PPV | NPV | F1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Marriage | 92.9% | 88.8% | 98.9% | 99.2% | 85.5% | 93.7% |
| Self illness | 93.7% | 68.6% | 98.0% | 85.7% | 94.8% | 76.2% |
| Family illness | 74.8% | 83.9% | 69.5% | 61.3% | 88.2% | 70.9% |
| Spouse location | 85.7% | 98.1% | 75.4% | 76.8% | 98.0% | 86.2% |
| OKU self or family | 97.9% | 73.3% | 99.6% | 91.7% | 98.2% | 81.5% |
| MedEX or other exam | 89.1% | 91.4% | 87.9% | 79.6% | 95.2% | 85.1% |

### Applicant-Level Agreement and Review Burden

Exact applicant-level agreement was 118/238 (49.6%). This is a stricter outcome than evidence-level accuracy because all six evidence categories had to match the manual reference standard for a given applicant. In operational terms, the system flagged 64/238 applicants for manual review, leaving 174/238 applicants not flagged. This corresponds to a potential 73.1% reduction in first-pass manual review workload if the system were used as an initial triage layer.

However, the review flag was not a complete detector of residual classification error. Among 120 applicants with at least one evidence-level error, 34 were flagged for review. Among 48 applicants with at least one false negative, 25 were flagged. These findings mean that "no_check" should not be interpreted as a guarantee of perfect classification. Rather, it reflects the system's current operational threshold for uncertainty or missing proof.

| Error or review group | Total | Flagged for review | Percentage flagged |
| --- | ---: | ---: | ---: |
| False-positive evidence decisions | 103 | 19 | 18.4% |
| False-negative evidence decisions | 54 | 29 | 53.7% |
| Applicants with at least one false positive | 92 | 18 | 19.6% |
| Applicants with at least one false negative | 48 | 25 | 52.1% |
| Applicants with any evidence-level error | 120 | 34 | 28.3% |
| All applicants | 238 | 64 | 26.9% |

### Comparison With Version 4

The final validation workbook reported no prediction-label differences between v4 and v4.1, and no check-required differences. Thus, v4.1 should be interpreted as an auditability and reporting extension of v4 rather than a new predictive model. The practical value of v4.1 is the addition of proof-strength and supporting audit fields that make manual review more structured.

## Discussion

### Principal Findings

This validation showed that a local-first, claim-guided evidence verifier can achieve useful decision-level performance in a difficult administrative document setting. Across 1,428 evidence-level decisions, the system achieved sensitivity of 88.5%, specificity of 89.3%, NPV of 94.1%, and F1 score of 84.1%. It also reduced the first-pass manual review queue to 26.9% of applicants. These findings are consistent with a viable AI-assisted triage role.

The results also show why the system should not be treated as autonomous adjudication. Exact applicant-level agreement was 49.6%, and the manual review flag captured only a subset of applicants with residual evidence-level errors. This is not unusual for multi-label document evidence systems, where each applicant contributes several opportunities for disagreement. However, it matters operationally because a low review rate can hide residual errors if thresholds are not calibrated to the governance objective.

### Interpretation

The strongest categories were marriage and MedEX or other examination evidence. Marriage evidence benefited from relatively distinctive document structure and vocabulary, while MedEX and examination evidence became easier after earlier prompt and rule changes that separated official examination evidence from generic medical records. In contrast, family illness and spouse location were more ambiguous. Both categories depend on relational context: the document must not only be a medical or location document, but must also relate to the applicant, spouse, parent, child, or other relevant family member. This creates more room for over-calling when documents contain names, official letters, workplace references, or medical terms without a clearly adjudicable relationship.

The findings support a systems interpretation rather than a model-centric one. The improvement appears to come from the workflow design: using the applicant's declared claims, skipping unclaimed categories, combining OCR with vision-capable local model support, and exporting audit fields for review. The model is only one part of the system. The surrounding data model, column mapping, document acquisition, OCR routing, and decision queue design are equally important.

### Operational Implications

For an ePlacement workflow, the most defensible near-term deployment is human-in-the-loop triage. A 26.9% review queue could materially reduce routine document review if no-check applicants are handled through an auditable first-pass process. However, production use should include safeguards:

- Review all applicants flagged as check or missing proof.
- Apply targeted review or sampling to no-check applicants, especially for family illness and spouse-location claims.
- Monitor false positives and false negatives by evidence type after each batch.
- Preserve original PDF links, supporting pages, proof-strength fields, and evidence summaries for audit.
- Recalibrate the check threshold based on operational tolerance for missed evidence versus manual workload.
- Avoid using the system as the sole basis for adverse decisions until external validation and governance review are complete.

The system's local-first architecture is important in the Malaysian public-sector context. Running OCR, document processing, and model inference locally can support data minimisation, lower external dependency, and clearer auditability. This is especially relevant when raw PDFs may contain health, disability, family, marital, and employment information.

### Relationship to the Broader e-KYC Landscape

This system should not be positioned as a complete e-KYC product. It does not currently perform identity document authenticity checks, face matching, liveness detection, NFC or eMRTD chip verification, sanctions screening, device-risk assessment, or financial crime risk scoring. Instead, it addresses a narrower but underexplored problem: evidence verification for administrative claims using local documents and a human-review workflow.

The broader literature and industry landscape suggest useful extension paths. Public identity-document datasets such as MIDV-500 and MIDV-2020 support document recognition and OCR benchmarking. Document AI models such as TrOCR, LayoutLMv3, Donut, and GeoLayoutLM provide candidate baselines for OCR-dependent and OCR-free document understanding. Document recapture and authenticity datasets such as DLC-2021, and broader identity-verification work on selfie-to-ID matching and presentation attack detection, are relevant if the system evolves toward full e-KYC. For the current manuscript, however, the honest contribution is an evaluated local-first evidence triage system, not a comprehensive identity proofing stack.

### Strengths

This validation has several strengths. First, it used a manually adjudicated validation set rather than relying only on synthetic examples or internal unit tests. Second, it evaluated six evidence categories that reflect the real administrative burden of ePlacement review. Third, it reported both evidence-level metrics and applicant-level exact agreement, which prevents overinterpretation of aggregate accuracy. Fourth, the system exported structured scoring and audit outputs, making future validation, error review, and recalibration feasible.

### Limitations

The validation has important limitations. The dataset included 238 applicants from a single workflow and may not represent future application cycles, different document submission behaviours, or different scanner and language distributions. The reference standard depends on manual adjudication and may contain reviewer error. Evidence-level metrics treat six decisions per applicant as separate observations; future analysis should use applicant-clustered confidence intervals or bootstrap methods. The system does not verify document authenticity, liveness, or applicant identity. The review flag is not yet calibrated as a safety net for all residual errors. Finally, v4.1 did not improve prediction labels over v4; its contribution was auditability, proof-strength reporting, and more interpretable outputs.

### Future Work

The next development phase should focus on calibration and evidence-type-specific error reduction rather than broad model replacement. High-yield improvements include:

- Recalibrating review thresholds to improve capture of false negatives while keeping manual review workload acceptable.
- Adding active-learning loops from the manual scoring sheet into prompt, rule, and threshold updates.
- Performing targeted error review for family illness and spouse-location false positives.
- Adding applicant-clustered bootstrap confidence intervals and batch-level monitoring dashboards.
- Benchmarking OCR and vision pathways against OCR-free document understanding baselines.
- Testing robustness across language scripts, document quality, scanned image resolution, and multi-document PDF bundles.
- Adding formal model cards, data protection impact assessment notes, and deployment governance documentation.

## Conclusion

The eplacement-kyc-verifier v4.1 system achieved strong evidence-level validation performance and reduced the first-pass manual review queue to 26.9% of applicants in a 238-applicant validation set. Its most appropriate role is AI-assisted administrative evidence triage, not autonomous KYC adjudication. The findings support continued development of local-first, auditable document evidence systems for public-sector workflows, provided that deployment includes structured manual review, residual error monitoring, and clear governance boundaries.

## Figure 1. System Schematic

Applicant spreadsheet -> claim extraction -> PDF acquisition -> direct text extraction and OCR routing -> claim-guided evidence verification -> decision queue, scoring sheet, final tick sheet, and audit exports.

## Manuscript-Ready Table Captions

Table 1. Overall validation performance of the eplacement-kyc-verifier v4.1 algorithm across 1,428 evidence-level binary decisions from 238 applicants.

Table 2a. Evidence-type-specific validation counts across six administrative evidence categories.

Table 2b. Evidence-type-specific validation performance across six administrative evidence categories.

Table 3. Manual review flag behaviour among false-positive decisions, false-negative decisions, applicants with residual errors, and all applicants.

## Data Availability

This draft uses derived validation metrics from `C:/Users/vivek/Downloads/eplacement_kyc_validation_analysis_v4_1.xlsx`. Raw applicant PDFs and identifiable applicant-level source data should not be committed to the repository. A de-identified validation summary and manuscript source are stored in this manuscript folder.

## Ethics and Governance Statement

This is a draft statement only. The final manuscript should specify whether the work was conducted as service evaluation, quality improvement, operational validation, or research requiring ethics review. It should also document data minimisation, access controls, retention policy, and whether any identifiable data were processed during algorithm development or validation.

## Competing Interests

To be completed before submission.

## Funding

To be completed before submission.

## References for Draft Development

1. Financial Action Task Force. Guidance on Digital Identity.
2. National Institute of Standards and Technology. Digital Identity Guidelines, SP 800-63 series.
3. International Civil Aviation Organization. Doc 9303 Machine Readable Travel Documents.
4. Arlazarov V, et al. MIDV-500: a dataset for identity document analysis and recognition on mobile devices in video stream.
5. Bulatov K, et al. MIDV-2020: a comprehensive benchmark dataset for identity document analysis.
6. Li M, et al. TrOCR: Transformer-based optical character recognition.
7. Huang Y, et al. LayoutLMv3: pre-training for document AI with unified text and image masking.
8. Kim G, et al. Donut: document understanding transformer without OCR.
9. Luo C, et al. GeoLayoutLM: geometric pre-training for visual information extraction.
10. Shi Y, et al. DocFace: matching ID document photos to selfies.
11. Document liveness and recapture evaluation resources, including DLC-2021 and related identity-document authenticity work.
