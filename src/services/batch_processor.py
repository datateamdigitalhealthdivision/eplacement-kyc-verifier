"""Batch orchestration for spreadsheet, PDF, OCR, extraction, rules, and exports."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from time import perf_counter
from typing import Iterable

from src.classification.doc_classifier import HybridDocClassifier
from src.db.models import ExportBundle, RunJobRequest
from src.db.sqlite_store import SQLiteStore
from src.extraction.evidence_models import EvidenceResult
from src.extraction.generic_extractor import GenericExtractor
from src.extraction.marriage_extractor import MarriageExtractor
from src.extraction.medex_extractor import MedexExtractor
from src.io.downloader import Downloader
from src.io.exporters import ExportWriter
from src.io.pdf_locator import PDFLocator
from src.io.spreadsheet_loader import ApplicantRecord, SpreadsheetLoader
from src.llm.ollama_client import OllamaClient
from src.ocr.ocr_router import OCRRouter
from src.rules.marriage_rules import validate_marriage
from src.rules.medex_rules import validate_medex
from src.rules.document_tags import derive_document_tags
from src.rules.merge_back import merge_results_back
from src.rules.validators import aggregate_reason_text, document_ocr_confidence, generic_document_decision, row_claim_is_married, row_has_postgraduate_claim
from src.services.review_queue import ReviewQueueService
from src.settings import AppConfig


SUPPORTED_TARGETS = {"marriage_certificate", "medex_or_exam_document"}
TARGET_LABELS = {
    "marriage_certificate": "marriage certificate",
    "medex_or_exam_document": "MedEX or postgraduate document",
    "other_supporting_document": "other supporting document",
    "unknown": "unidentified supporting document",
}


class BatchProcessor:
    def __init__(self, settings: AppConfig, store: SQLiteStore, llm_client: OllamaClient) -> None:
        self.settings = settings
        self.store = store
        self.loader = SpreadsheetLoader(project_root=Path(__file__).resolve().parents[2])
        self.downloader = Downloader(timeout_seconds=self.settings.ollama.timeout_seconds)
        self.ocr_router = OCRRouter(settings)
        self.classifier = HybridDocClassifier(llm_client)
        self.marriage_extractor = MarriageExtractor(settings, llm_client)
        self.medex_extractor = MedexExtractor(settings, llm_client)
        self.generic_extractor = GenericExtractor(settings, llm_client)
        self.exporter = ExportWriter(settings)
        self.review_queue = ReviewQueueService(store)

    @staticmethod
    def _expected_targets(row: dict) -> list[str]:
        targets: list[str] = []
        if row_claim_is_married(row.get("marital_status")):
            targets.append("marriage_certificate")
        if row_has_postgraduate_claim(row.get("postgraduate_status")):
            targets.append("medex_or_exam_document")
        return targets

    @staticmethod
    def _normalize_download_url(value: str | None) -> str | None:
        normalized = str(value or "").strip()
        if not normalized:
            return None
        if normalized.casefold() in {"tiada maklumat", "nan", "none", "null", "n/a", "na", "-"}:
            return None
        if normalized.lower().startswith(("http://", "https://")):
            return normalized
        return None

    @staticmethod
    def _applicant_context(record: ApplicantRecord) -> dict[str, str]:
        keys = [
            "applicant_id",
            "applicant_name",
            "marital_status",
            "spouse_name",
            "spouse_id",
            "postgraduate_status",
            "pdf_filename",
            "pdf_url",
        ]
        return {key: str(record.canonical.get(key, "") or "") for key in keys}

    @staticmethod
    def _target_label(target: str) -> str:
        return TARGET_LABELS.get(target, target.replace("_", " "))

    @staticmethod
    def _evidence_type(target: str) -> str:
        return {
            "marriage_certificate": "marriage",
            "medex_or_exam_document": "medex",
        }.get(target, "generic")

    @staticmethod
    def _observed_target(classification) -> str:
        for target in [classification.primary_type, *classification.candidate_types]:
            if target in {"marriage_certificate", "medex_or_exam_document", "other_supporting_document"}:
                return target
        return "other_supporting_document"

    @staticmethod
    def _evidence_name_fields(evidence) -> list[str]:
        fields: list[str] = []
        for attribute in [
            "applicant_name_from_doc",
            "spouse_name_from_doc",
            "candidate_name_from_doc",
            "possible_subject_name",
        ]:
            value = getattr(evidence, attribute, None)
            if value:
                fields.append(value)
        return fields

    @staticmethod
    def _evidence_identifiers(evidence) -> tuple[str | None, str | None]:
        applicant_identifier = (
            getattr(evidence, "applicant_ic_from_doc", None)
            or getattr(evidence, "candidate_ic_from_doc", None)
            or getattr(evidence, "possible_subject_ic", None)
        )
        spouse_identifier = getattr(evidence, "spouse_ic_from_doc", None)
        return applicant_identifier, spouse_identifier

    @staticmethod
    def _result_llm_json(classification, evidence=None) -> dict[str, object | None]:
        return {
            "classification": classification.llm_payload,
            "extraction": evidence.raw_payload if evidence is not None else None,
        }

    def _missing_result(
        self,
        job_id: str,
        record: ApplicantRecord,
        target: str,
        status: str,
        reason: str,
        download_url: str | None,
    ) -> EvidenceResult:
        manual_review = status in {
            "MANUAL_REVIEW_REQUIRED",
            "DOCUMENT_MISSING",
            "DOWNLOAD_FAILED",
            "OCR_FAILED",
            "UNSUPPORTED_DOCUMENT_TYPE",
            "NOT_EVIDENCED_OR_INCONSISTENT",
        }
        return EvidenceResult(
            job_id=job_id,
            applicant_id=record.applicant_id,
            applicant_name=str(record.canonical.get("applicant_name") or "") or None,
            row_index=record.row_index,
            source_pdf_name=str(record.canonical.get("pdf_filename") or "") or None,
            source_pdf_path=None,
            download_url=download_url,
            document_type=target,
            evidence_type=self._evidence_type(target),
            final_status=status,
            final_reason=reason,
            manual_review_flag=manual_review,
            audit_payload={"reason": reason, "result_kind": "missing_document"},
        )

    def _build_result(
        self,
        *,
        job_id: str,
        record: ApplicantRecord,
        classification,
        evidence,
        decision,
        pdf_path: Path,
        ocr_document,
        processing_time_seconds: float,
    ) -> EvidenceResult:
        applicant_identifier, spouse_identifier = self._evidence_identifiers(evidence)
        llm_json = self._result_llm_json(classification, evidence)
        document_tags = derive_document_tags(classification, evidence, ocr_document)
        manual_review = decision.manual_review_required or decision.final_status in {
            "MANUAL_REVIEW_REQUIRED",
            "DOCUMENT_MISSING",
            "DOWNLOAD_FAILED",
            "OCR_FAILED",
            "UNSUPPORTED_DOCUMENT_TYPE",
            "NOT_EVIDENCED_OR_INCONSISTENT",
        }
        return EvidenceResult(
            job_id=job_id,
            applicant_id=record.applicant_id,
            applicant_name=str(record.canonical.get("applicant_name") or "") or None,
            row_index=record.row_index,
            source_pdf_name=pdf_path.name,
            source_pdf_path=str(pdf_path),
            download_url=self._normalize_download_url(record.canonical.get("pdf_url")),
            document_type=evidence.doc_type,
            evidence_type=decision.evidence_type,
            ocr_engine=",".join(ocr_document.metadata.get("engines", [])),
            ocr_confidence=document_ocr_confidence(ocr_document),
            llm_confidence=evidence.extraction_confidence,
            extracted_applicant_ic=applicant_identifier,
            extracted_spouse_ic=spouse_identifier,
            extracted_name_fields=self._evidence_name_fields(evidence),
            page_refs=evidence.page_refs,
            final_status=decision.final_status,
            final_reason=aggregate_reason_text(decision.reasons),
            manual_review_flag=manual_review,
            processing_time_seconds=round(processing_time_seconds, 3),
            document_hash=ocr_document.document_hash,
            processing_hash=ocr_document.processing_hash,
            matched_fields=decision.matched_fields,
            mismatched_fields=decision.mismatched_fields,
            snippets=evidence.key_supporting_snippets,
            llm_json=llm_json,
            audit_payload={
                "result_kind": "observed_document",
                "classification": classification.model_dump(mode="json"),
                "evidence": evidence.model_dump(mode="json"),
                "decision": decision.model_dump(mode="json"),
                "document_tags": document_tags,
                "ocr_warnings": ocr_document.warnings,
            },
        )

    def _claim_mismatch_result(
        self,
        *,
        job_id: str,
        record: ApplicantRecord,
        expected_target: str,
        observed_target: str,
        classification,
        observed_evidence,
        pdf_path: Path,
        ocr_document,
        processing_time_seconds: float,
    ) -> EvidenceResult:
        observed_label = self._target_label(observed_target)
        expected_label = self._target_label(expected_target)
        if classification.primary_type == "unknown":
            status = "MANUAL_REVIEW_REQUIRED"
            reason = f"Uploaded document could not be confidently tagged as '{expected_label}'; manual review required."
        else:
            status = "MANUAL_REVIEW_REQUIRED"
            reason = f"Uploaded document was tagged as '{observed_label}', not '{expected_label}'; manual review required."
        applicant_identifier, spouse_identifier = self._evidence_identifiers(observed_evidence)
        document_tags = derive_document_tags(classification, observed_evidence, ocr_document)
        return EvidenceResult(
            job_id=job_id,
            applicant_id=record.applicant_id,
            applicant_name=str(record.canonical.get("applicant_name") or "") or None,
            row_index=record.row_index,
            source_pdf_name=pdf_path.name,
            source_pdf_path=str(pdf_path),
            download_url=self._normalize_download_url(record.canonical.get("pdf_url")),
            document_type=expected_target,
            evidence_type=self._evidence_type(expected_target),
            ocr_engine=",".join(ocr_document.metadata.get("engines", [])),
            ocr_confidence=document_ocr_confidence(ocr_document),
            llm_confidence=observed_evidence.extraction_confidence,
            extracted_applicant_ic=applicant_identifier,
            extracted_spouse_ic=spouse_identifier,
            extracted_name_fields=self._evidence_name_fields(observed_evidence),
            page_refs=observed_evidence.page_refs,
            final_status=status,
            final_reason=reason,
            manual_review_flag=True,
            processing_time_seconds=round(processing_time_seconds, 3),
            document_hash=ocr_document.document_hash,
            processing_hash=ocr_document.processing_hash,
            matched_fields=[],
            mismatched_fields=["document_type"],
            snippets=observed_evidence.key_supporting_snippets,
            llm_json=self._result_llm_json(classification, observed_evidence),
            audit_payload={
                "result_kind": "claim_cross_check",
                "classification": classification.model_dump(mode="json"),
                "evidence": observed_evidence.model_dump(mode="json"),
                "decision": {
                    "expected_document_type": expected_target,
                    "observed_document_type": observed_target,
                    "reason": reason,
                },
                "document_tags": document_tags,
                "ocr_warnings": ocr_document.warnings,
            },
        )

    def _extract_observed_document(self, target: str, document, applicant_context: dict[str, str], row: dict):
        if target == "marriage_certificate":
            evidence = self.marriage_extractor.extract(document, applicant_context)
            decision = validate_marriage(row, evidence, document)
        elif target == "medex_or_exam_document":
            evidence = self.medex_extractor.extract(document, applicant_context)
            decision = validate_medex(row, evidence, document)
        else:
            evidence = self.generic_extractor.extract(document, applicant_context)
            decision = generic_document_decision(evidence, document)
        return evidence, decision

    @staticmethod
    def _summary(bundle, evidence_results: list[EvidenceResult], downloaded_count: int, ocr_docs: int, direct_text_docs: int) -> list[dict]:
        status_counts = Counter(result.effective_status() for result in evidence_results)
        doc_counts = Counter(result.document_type for result in evidence_results)
        reason_counts = Counter(result.final_reason for result in evidence_results if result.final_reason)
        pdf_paths = {result.source_pdf_path for result in evidence_results if result.source_pdf_path}
        return [
            {
                "total_applicants": len(bundle.records),
                "total_pdfs_found": len(pdf_paths),
                "total_downloaded": downloaded_count,
                "total_ocred": ocr_docs,
                "total_direct_text_extracted": direct_text_docs,
                "counts_by_document_type": dict(doc_counts),
                "counts_by_status": dict(status_counts),
                "counts_requiring_manual_review": sum(1 for result in evidence_results if result.manual_review_flag),
                "counts_by_failure_reason": dict(reason_counts),
            }
        ]

    def execute_job(
        self,
        job_id: str,
        request: RunJobRequest,
        include_applicant_ids: Iterable[str] | None = None,
    ) -> ExportBundle | None:
        bundle = self.loader.load(request.applicant_path)
        selected_ids = set(include_applicant_ids or [])
        records = [record for record in bundle.records if not selected_ids or record.applicant_id in selected_ids]
        counters: Counter = Counter()
        evidence_results: list[EvidenceResult] = []
        downloaded_count = 0
        ocr_docs = 0
        direct_text_docs = 0
        self.store.update_job(job_id, status="RUNNING", progress_total=len(records), progress_completed=0, counters={})
        for warning in bundle.warnings:
            self.store.log_event(job_id, "WARNING", warning)
        if bundle.missing_required:
            message = f"Cannot process spreadsheet because required columns are missing: {', '.join(bundle.missing_required)}"
            self.store.update_job(job_id, status="FAILED", latest_error=message)
            self.store.log_event(job_id, "ERROR", message)
            return None

        pdf_directory = request.pdf_directory or str(self.settings.paths.pdf_dir)
        locator = PDFLocator([pdf_directory, self.settings.paths.pdf_dir, self.settings.paths.downloads_dir])

        for completed, record in enumerate(records, start=1):
            started = perf_counter()
            try:
                expected_targets = self._expected_targets(record.canonical)
                located = locator.locate(record)
                pdf_path = located.path
                download_status = None
                download_error = None
                download_url = self._normalize_download_url(record.canonical.get("pdf_url"))
                if pdf_path is None and request.auto_download and download_url:
                    download_result = self.downloader.download(
                        download_url,
                        self.settings.paths.downloads_dir,
                        str(record.canonical.get("pdf_filename") or f"{record.applicant_id}.pdf"),
                    )
                    download_status = download_result.status
                    if download_result.path is not None:
                        pdf_path = download_result.path
                        downloaded_count += int(download_result.downloaded)
                    else:
                        download_error = download_result.error or download_result.status
                if pdf_path is None:
                    failure_status = "DOWNLOAD_FAILED" if download_error else "DOCUMENT_MISSING"
                    failure_reason = download_error or located.message or "Supporting document not found."
                    targets = expected_targets or ["other_supporting_document"]
                    for target in targets:
                        result = self._missing_result(
                            job_id,
                            record,
                            target,
                            failure_status,
                            failure_reason,
                            download_url,
                        )
                        evidence_results.append(result)
                        self.store.save_evidence_result(result)
                        counters[result.final_status] += 1
                    self.store.log_event(job_id, "INFO", f"No PDF available for applicant {record.applicant_id}")
                    self.store.update_job(job_id, progress_completed=completed, counters=dict(counters))
                    continue

                ocr_document = self.ocr_router.process_document(record.applicant_id, pdf_path)
                engines = set(ocr_document.metadata.get("engines", []))
                if engines == {"direct_text"}:
                    direct_text_docs += 1
                else:
                    ocr_docs += 1

                if not ocr_document.combined_text and not self.classifier.can_use_vision(ocr_document.page_image_paths):
                    targets = expected_targets or ["other_supporting_document"]
                    for target in targets:
                        result = self._missing_result(
                            job_id,
                            record,
                            target,
                            "OCR_FAILED",
                            "OCR pipeline did not extract usable text from the PDF.",
                            download_url,
                        )
                        result.source_pdf_name = pdf_path.name
                        result.source_pdf_path = str(pdf_path)
                        evidence_results.append(result)
                        self.store.save_evidence_result(result)
                        counters[result.final_status] += 1
                    self.store.log_event(job_id, "WARNING", f"OCR failed for applicant {record.applicant_id}")
                    self.store.update_job(job_id, progress_completed=completed, counters=dict(counters))
                    continue

                classification = self.classifier.classify(ocr_document.combined_text, ocr_document.page_image_paths)
                observed_target = self._observed_target(classification)
                context = self._applicant_context(record)
                observed_evidence, observed_decision = self._extract_observed_document(
                    observed_target,
                    ocr_document,
                    context,
                    record.canonical,
                )
                observed_result = self._build_result(
                    job_id=job_id,
                    record=record,
                    classification=classification,
                    evidence=observed_evidence,
                    decision=observed_decision,
                    pdf_path=pdf_path,
                    ocr_document=ocr_document,
                    processing_time_seconds=perf_counter() - started,
                )
                evidence_results.append(observed_result)
                self.store.save_evidence_result(observed_result)
                counters[observed_result.final_status] += 1

                for target in expected_targets:
                    if target == observed_target:
                        continue
                    mismatch_result = self._claim_mismatch_result(
                        job_id=job_id,
                        record=record,
                        expected_target=target,
                        observed_target=observed_target,
                        classification=classification,
                        observed_evidence=observed_evidence,
                        pdf_path=pdf_path,
                        ocr_document=ocr_document,
                        processing_time_seconds=perf_counter() - started,
                    )
                    evidence_results.append(mismatch_result)
                    self.store.save_evidence_result(mismatch_result)
                    counters[mismatch_result.final_status] += 1

                self.store.log_event(
                    job_id,
                    "INFO",
                    f"Processed applicant {record.applicant_id}",
                    {
                        "download_status": download_status,
                        "pdf_path": str(pdf_path),
                        "observed_document_type": observed_target,
                        "expected_targets": expected_targets,
                    },
                )
            except Exception as exc:  # noqa: BLE001
                result = self._missing_result(
                    job_id,
                    record,
                    "other_supporting_document",
                    "OCR_FAILED",
                    str(exc),
                    self._normalize_download_url(record.canonical.get("pdf_url")),
                )
                evidence_results.append(result)
                self.store.save_evidence_result(result)
                counters[result.final_status] += 1
                self.store.log_event(job_id, "ERROR", f"Processing failed for applicant {record.applicant_id}", {"error": str(exc)})
            finally:
                self.store.update_job(job_id, progress_completed=completed, counters=dict(counters))

        merged_df = merge_results_back(bundle.original_df, bundle.canonical_df, evidence_results)
        summary_rows = self._summary(bundle, evidence_results, downloaded_count, ocr_docs, direct_text_docs)
        review_rows = self.review_queue.list_records(job_id=job_id)
        export_bundle = self.exporter.write_outputs(job_id, evidence_results, merged_df, review_rows, summary_rows)
        self.store.save_exports(export_bundle)
        self.store.update_job(job_id, status="COMPLETED", counters=dict(counters))
        self.store.log_event(job_id, "INFO", "Job completed", {"exports": export_bundle.model_dump(mode="json")})
        return export_bundle




