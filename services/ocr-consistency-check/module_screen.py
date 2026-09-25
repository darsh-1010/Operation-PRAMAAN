"""POST /screen — this module's API_CONTRACT.md entry point: OCR every uploaded document, run the
identity-document checks (Aadhaar Secure QR, Voter ID, Nepali citizenship — id_verification.py),
keep encrypted evidence (evidence.py), and push the result to risk-scoring-engine.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid as _uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, status

import aadhaar_qr
import evidence
from cross_document import cross_check_documents
from db import DatabaseManager
from decision_models import ValidationCheckRecord
from id_verification import verify_identity_document
from persistence import ensure_uuid, persist_document_extraction
from rate_limit import SCREEN_RATE_LIMIT, limiter
from risk_client import notify_risk_engine
from screening_pipeline import run_screening_pipeline

logger = logging.getLogger("module_screen")
router = APIRouter()

MAX_DOCUMENT_BYTES = 15 * 1024 * 1024
SLOTS = ("passport", "visa", "nationalId", "drivingLicence", "permit", "voterId", "citizenship")
# OCR language hint per slot: Nepali citizenship certificates are Devanagari (Tesseract eng+nep).
SLOT_COUNTRY = {"citizenship": "NPL"}
UIDAI_KEYS = aadhaar_qr.load_uidai_keys()


def _screen_document(key: str, filename: str, content: bytes) -> tuple:
    """Blocking: generic OCR pipeline + identity-document checks for one uploaded file."""
    ingested, ocr_res, parsed, _, decision, watchlist_hits, _ = run_screening_pipeline(content, filename, SLOT_COUNTRY.get(key))
    idv = verify_identity_document(key, ingested.images[0], ocr_res.full_text, parsed, UIDAI_KEYS)
    decision.validation_checks.extend(idv.checks)
    decision.reason_codes.extend(idv.reasons)
    if idv.hard_fail:
        decision.hard_fail, decision.score, decision.canonical_score = True, 0.0, 0.0
    return ingested, ocr_res, parsed, decision, watchlist_hits, idv


def _keep_evidence(session: str, uploads: list) -> tuple[list[str], list[str]]:
    """(evidence refs for the ledger, problems). The refs are sent even if storage fails — the
    hash of what was screened is still worth sealing — but a failure is surfaced, not hidden."""
    refs, problems = [], []
    for key, _, content in uploads:
        try:
            refs.append(evidence.store(session, key, content))
        except evidence.EvidenceError as err:
            refs.append(evidence.evidence_ref(key, content))
            problems.append(f"{key}: {err}")
    return refs, problems


@router.post("/screen", tags=["Screening"])
@limiter.limit(SCREEN_RATE_LIMIT)
async def screen(
    request: Request, uuid: str = Form(...), documents_present: str = Form(...),
    passport: Optional[UploadFile] = File(None), visa: Optional[UploadFile] = File(None),
    nationalId: Optional[UploadFile] = File(None), drivingLicence: Optional[UploadFile] = File(None),
    permit: Optional[UploadFile] = File(None), voterId: Optional[UploadFile] = File(None),
    citizenship: Optional[UploadFile] = File(None), selfie: Optional[UploadFile] = File(None),
) -> Dict[str, Any]:
    try:
        session = str(_uuid.UUID(uuid))
        present: Dict[str, bool] = json.loads(documents_present)
    except (ValueError, json.JSONDecodeError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "uuid must be a UUID and documents_present valid JSON")

    files = dict(zip(SLOTS, (passport, visa, nationalId, drivingLicence, permit, voterId, citizenship)))
    missing = [k for k in SLOTS if present.get(k) and files[k] is None]
    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"documents_present says '{missing[0]}' is present but no file was sent")
    uploads = [(k, f.filename or k, await f.read()) for k, f in files.items() if f is not None]
    if not uploads:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No documents uploaded")
    for key, _, content in uploads:
        if not content or len(content) > MAX_DOCUMENT_BYTES:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{key}: empty or larger than 15MB")

    db = DatabaseManager.get_instance()
    try:
        db.upsert_screening_session(session_id=session, pipeline_version="v1.1.0", status="PROCESSING")
    except Exception as err:
        logger.error("Failed to open session %s: %s", session, err)

    start_t = time.perf_counter()
    evidence_refs, evidence_problems = _keep_evidence(session, uploads)
    try:
        results = await asyncio.gather(*[asyncio.to_thread(_screen_document, k, fn, c) for k, fn, c in uploads])
    except ValueError as err:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"File ingestion error: {err}")

    return await _finish(session, db, uploads, results, evidence_refs, evidence_problems, start_t)


async def _finish(session: str, db, uploads: list, results: list, evidence_refs: list, evidence_problems: list,
                  start_t: float) -> Dict[str, Any]:
    reason_codes: List[str] = []
    all_checks: List[ValidationCheckRecord] = []
    canonical_scores, parsed_docs, id_docs = [], [], []
    hard_fail = review_required = False
    for (key, _, _), (ingested, ocr_res, parsed, decision, watchlist_hits, idv) in zip(uploads, results):
        parsed_docs.append(parsed)
        canonical_scores.append(decision.canonical_score)
        hard_fail |= decision.hard_fail
        review_required |= idv.review_required
        reason_codes.extend(r.code for r in decision.reason_codes)
        all_checks.extend(decision.validation_checks)
        id_docs.append({"slot": key, "detected_type": idv.subtype, "review_required": idv.review_required})
        try:
            persist_document_extraction(db, session, ensure_uuid(None), ingested, ocr_res, parsed, decision, watchlist_hits)
        except Exception as err:
            logger.error("Failed to persist document '%s': %s", key, err)

    if len(parsed_docs) > 1:
        cross = cross_check_documents(parsed_docs)
        if not cross.consistent:
            hard_fail = True
            reason_codes.append("cross_document_mismatch")
            detail = "; ".join(fr.detail for fr in cross.field_results if not fr.consistent) or "Identity fields differ across documents."
            all_checks.append(ValidationCheckRecord("CROSS_DOCUMENT_CONSISTENCY", "cross_document", "FAIL", True, "CONSISTENT", "INCONSISTENT", detail))
    if evidence_problems:
        review_required = True
        reason_codes.append("EVIDENCE_NOT_RETAINED")
        logger.error("uuid=%s evidence not retained: %s", session, evidence_problems)

    canonical = 0.0 if hard_fail else round(sum(canonical_scores) / len(canonical_scores), 4)
    final_score = round(canonical * 100.0, 2)
    elapsed_ms = round((time.perf_counter() - start_t) * 1000.0, 2)
    try:
        db.upsert_screening_session(session_id=session, pipeline_version="v1.1.0", status="FAILED" if hard_fail else "COMPLETED")
        db.upsert_module_score(session_id=session, score_kind="A", value=canonical, detail={"latency_ms": elapsed_ms})
        db.insert_audit_log(session_id=session, action="OCR_MODULE_SCREENING_COMPLETED", entity_type="SESSION", entity_id=session,
                            payload={"score": final_score, "hard_fail": hard_fail, "review_required": review_required, "evidence": evidence_refs})
    except Exception as err:
        logger.error("Failed to persist final score for %s: %s", session, err)

    await notify_risk_engine(session, hard_fail, final_score, reason_codes, evidence_refs, review_required)

    primary = parsed_docs[0]
    return {
        "score": final_score, "hard_fail": hard_fail, "reason_codes": reason_codes, "latency_ms": elapsed_ms,
        "review_required": review_required,
        "details": {
            "claimed_name": primary.claimed_name, "document_number": primary.document_number, "doc_type": primary.doc_type,
            "mrz_valid": primary.mrz_result.valid_format if primary.mrz_result else False, "identity_documents": id_docs,
            "extracted_fields": [{"field_key": f.field_key, "field_value": f.field_value, "source": f.source, "confidence": f.confidence} for d in parsed_docs for f in d.fields],
            "validation_checks": [{"check_type": c.check_type, "status": c.status, "detail": c.detail, "field_key": c.field_key} for c in all_checks],
        },
    }
