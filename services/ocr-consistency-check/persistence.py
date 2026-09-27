"""Audit log and screening session persistence helpers."""

from __future__ import annotations
import logging
from typing import Any, List, Optional
import uuid

from db import DatabaseManager
from decision_models import DecisionOutcome
from field_patterns import ParsedDocumentData
from ingestion import IngestedDocument

logger = logging.getLogger("persistence")


def ensure_uuid(val: Optional[str]) -> str:
    """Ensure a string is a valid UUID, or deterministically generate one."""
    if not val:
        return str(uuid.uuid4())
    try:
        uuid.UUID(str(val))
        return str(val)
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, str(val)))


def persist_document_extraction(
    db: DatabaseManager, session_id: str, document_id: str, ingested: IngestedDocument,
    ocr_res: Any, parsed: ParsedDocumentData, decision: DecisionOutcome, watchlist_hits: List[Any],
) -> str:
    """Persist one document's extraction artifacts and return the extraction_id."""
    s_uuid = ensure_uuid(session_id)
    d_uuid = ensure_uuid(document_id)
    extraction_uuid = str(uuid.uuid4())

    db.insert_document(
        document_id=d_uuid, session_id=s_uuid, doc_type=parsed.doc_type,
        document_number=parsed.document_number, claimed_name=parsed.claimed_name,
        claimed_dob=parsed.claimed_dob, claimed_expiry=parsed.claimed_expiry,
        claimed_gender=parsed.claimed_gender, issuing_country=parsed.issuing_country or "IND",
    )

    storage_ext = ingested.mime_type.split("/")[-1] if "/" in ingested.mime_type else "png"
    storage_uri = f"uploads/{d_uuid}.{storage_ext}"
    db.insert_capture(
        session_id=s_uuid, document_id=d_uuid, kind="DOCUMENT_PHOTO", storage_uri=storage_uri,
        sha256=ingested.sha256, mime_type=ingested.mime_type, width_px=ingested.width_px, height_px=ingested.height_px,
    )

    mrz_raw_text = "\n".join(parsed.mrz_result.raw_lines) if (parsed.mrz_result and parsed.mrz_result.raw_lines) else None
    db.insert_ocr_extraction(
        extraction_id=extraction_uuid, document_id=d_uuid, engine=getattr(ocr_res, "engine", "paddleocr-3.7"),
        model_version=getattr(ocr_res, "model_version", "PP-OCRv6"), mrz_raw=mrz_raw_text,
        overall_confidence=getattr(ocr_res, "average_confidence", 0.90),
    )

    for f in parsed.fields:
        db.insert_extracted_field(
            extraction_id=extraction_uuid, document_id=d_uuid, field_key=f.field_key,
            field_value=f.field_value, source=f.source, confidence=f.confidence, bbox=f.bbox,
        )

    for c in decision.validation_checks:
        db.insert_validation_check(
            document_id=d_uuid, module="MODULE_1", check_type=c.check_type, field_key=c.field_key,
            status=c.status, is_hard_fail=c.is_hard_fail, expected_value=c.expected_value,
            observed_value=c.observed_value, detail=c.detail,
        )

    for h in watchlist_hits:
        db.insert_watchlist_hit(
            session_id=s_uuid, document_id=d_uuid, entry_id=h.entry_id,
            match_basis=h.match_basis, match_score=h.match_score, is_hard_fail=h.is_hard_fail,
        )

    db.insert_audit_log(
        session_id=s_uuid, action="OCR_DOCUMENT_EXTRACTED", entity_type="DOCUMENT", entity_id=d_uuid,
        payload={"extraction_id": extraction_uuid, "score": decision.score, "canonical_score": decision.canonical_score, "status": decision.status, "hard_fail": decision.hard_fail},
    )
    return extraction_uuid


def persist_screening_session(
    session_id: str, document_id: str, ingested: IngestedDocument,
    ocr_res: Any, parsed: ParsedDocumentData, decision: DecisionOutcome, watchlist_hits: List[Any],
) -> None:
    """Persist a single-document screening session lifecycle and scores."""
    db = DatabaseManager.get_instance()
    try:
        s_uuid = ensure_uuid(session_id)
        sess_status = "COMPLETED" if not decision.hard_fail else "FAILED"
        db.upsert_screening_session(session_id=s_uuid, pipeline_version="v1.0.0", status=sess_status)
        persist_document_extraction(db, s_uuid, document_id, ingested, ocr_res, parsed, decision, watchlist_hits)
        db.upsert_module_score(session_id=s_uuid, score_kind="A", value=decision.canonical_score, detail=decision.sub_scores)
        logger.info("Screening session %s audit and extractions successfully persisted to database.", s_uuid)
    except Exception as err:
        logger.error("Audit persistence failure: %s", err, exc_info=True)
