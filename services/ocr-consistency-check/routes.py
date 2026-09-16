"""API Route handlers for OCR & Consistency Check Microservice."""

from __future__ import annotations
import asyncio, json, logging, time, uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from candidate_search import CandidateSearchEngine
from cross_document import cross_check_documents
from db import DatabaseManager
from decision_matrix import evaluate_decision_matrix
from decision_models import ValidationCheckRecord
from field_extractor import ParsedDocumentData, extract_document_fields
from ingestion import ingest_file
from matcher import match_against_candidate
from ocr_engine import OCREngine
from persistence import ensure_uuid, persist_document_extraction, persist_screening_session
from schemas import ScreenResponse, VerifyTextRequest
from screening_pipeline import resolve_ocr_lang, run_screening_pipeline

logger = logging.getLogger("ocr_routes")
router = APIRouter()


@router.get("/api/v1/health", tags=["Monitoring"])
def health_check() -> Dict[str, Any]:
    db = DatabaseManager.get_instance()
    engine = OCREngine.get_instance()
    return {
        "status": "healthy", "service": "ocr-consistency-check", "version": "1.0.0",
        "database": "postgresql" if db.is_postgres else "sqlite_fallback", "ocr_engine": engine._engine_name,
    }


@router.post("/api/v1/extract-only", tags=["Extraction"])
async def extract_only(
    file: UploadFile = File(...), expected_country: Optional[str] = Form(None), expected_language: Optional[str] = Form(None),
) -> Dict[str, Any]:
    try:
        content = await file.read()
        ingested = ingest_file(content, file.filename or "")
        ocr_res = OCREngine.get_instance().extract_text(ingested.images[0], lang=resolve_ocr_lang(expected_country, expected_language))
        parsed = extract_document_fields(ocr_res, expected_country=expected_country, expected_language=expected_language)
        return {
            "doc_type": parsed.doc_type, "document_number": parsed.document_number, "claimed_name": parsed.claimed_name,
            "claimed_dob": parsed.claimed_dob, "claimed_expiry": parsed.claimed_expiry, "claimed_gender": parsed.claimed_gender,
            "mrz_valid": parsed.mrz_result.valid_format if parsed.mrz_result else False, "raw_text": ocr_res.full_text,
            "fields": [{"key": f.field_key, "value": f.field_value, "source": f.source, "confidence": f.confidence, "bbox": f.bbox} for f in parsed.fields],
        }
    except Exception as err:
        logger.error("Extraction failed: %s", err)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))


@router.post("/api/v1/cross-verify", tags=["Cross-Document"])
async def cross_verify_documents(files: List[UploadFile] = File(...)) -> Dict[str, Any]:
    if len(files) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="At least two documents are required for cross-verification.")

    async def _process_f(f: UploadFile):
        img = ingest_file(await f.read(), f.filename or "").images[0]
        return await asyncio.to_thread(lambda: extract_document_fields(OCREngine.get_instance().extract_text(img)))

    parsed_docs = await asyncio.gather(*[_process_f(f) for f in files])
    outcome = cross_check_documents(parsed_docs)
    return {
        "consistent": outcome.consistent,
        "documents": [{"doc_type": d.doc_type, "document_number": d.document_number, "claimed_name": d.claimed_name, "claimed_dob": d.claimed_dob, "claimed_gender": d.claimed_gender} for d in parsed_docs],
        "field_results": [{"field_key": r.field_key, "consistent": r.consistent, "values": r.values, "detail": r.detail} for r in outcome.field_results],
    }


@router.post("/api/v1/screen", response_model=ScreenResponse, tags=["Screening"])
async def screen_document(
    file: UploadFile = File(...), session_id: Optional[str] = Form(None), document_id: Optional[str] = Form(None),
    expected_country: Optional[str] = Form(None), expected_language: Optional[str] = Form(None),
) -> ScreenResponse:
    s_id, d_id = session_id or str(uuid.uuid4()), document_id or str(uuid.uuid4())
    content = await file.read()
    try:
        ingested, ocr_res, parsed, match_outcome, decision, watchlist_hits, selected_candidate = await asyncio.to_thread(
            run_screening_pipeline, content, file.filename or "", expected_country, expected_language
        )
    except Exception as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"File ingestion error: {err}")

    persist_screening_session(s_id, d_id, ingested, ocr_res, parsed, decision, watchlist_hits)
    cand_dict = {"record_id": selected_candidate.record_id, "id_number": selected_candidate.id_number, "full_name": selected_candidate.full_name, "dob": selected_candidate.dob, "status": selected_candidate.status, "expiry_date": selected_candidate.expiry_date} if selected_candidate else None

    return ScreenResponse(
        session_id=s_id, document_id=d_id, status=decision.status, score=decision.score,
        canonical_score=decision.canonical_score, hard_fail=decision.hard_fail, doc_type=parsed.doc_type,
        document_number=parsed.document_number, claimed_name=parsed.claimed_name, claimed_dob=parsed.claimed_dob,
        claimed_expiry=parsed.claimed_expiry, claimed_gender=parsed.claimed_gender,
        issuing_country=parsed.issuing_country or "IND", detected_language=parsed.detected_language,
        detected_script=parsed.detected_script, claimed_dob_bs=parsed.claimed_dob_bs, calendar_system=parsed.calendar_system,
        reason_codes=[{"code": r.code, "message": r.message, "severity": r.severity, "contribution": r.contribution} for r in decision.reason_codes],
        validation_checks=[{"check_type": c.check_type, "field_key": c.field_key, "status": c.status, "is_hard_fail": c.is_hard_fail, "expected": c.expected_value, "observed": c.observed_value, "detail": c.detail} for c in decision.validation_checks],
        candidate_matched=match_outcome.has_candidate, candidate_details=cand_dict, mrz_valid=parsed.mrz_result.valid_format if parsed.mrz_result else None,
        extracted_fields=[{"field_key": f.field_key, "field_value": f.field_value, "source": f.source, "confidence": f.confidence} for f in parsed.fields],
    )


@router.post("/api/v1/verify-text", tags=["Verification"])
def verify_text_only(req: VerifyTextRequest) -> Dict[str, Any]:
    s_id = req.session_id or str(uuid.uuid4())
    search = CandidateSearchEngine()
    watchlist_hits = search.screen_watchlist(document_number=req.document_number, full_name=req.full_name, dob=req.dob)
    candidates = search.find_candidate_documents(doc_type=req.doc_type, id_number=req.document_number, dob=req.dob)
    cand = candidates[0] if candidates else None
    dummy = ParsedDocumentData(doc_type=req.doc_type, document_number=req.document_number, claimed_name=req.full_name, claimed_dob=req.dob)
    match_outcome = match_against_candidate(dummy, cand)
    decision = evaluate_decision_matrix(dummy, match_outcome, watchlist_hits)
    return {
        "session_id": s_id, "status": decision.status, "score": decision.score, "canonical_score": decision.canonical_score,
        "hard_fail": decision.hard_fail, "reason_codes": [{"code": r.code, "message": r.message, "severity": r.severity} for r in decision.reason_codes],
        "candidate_matched": match_outcome.has_candidate, "differences": match_outcome.differences,
    }


@router.post("/screen", tags=["Screening"])
async def screen(
    uuid: str = Form(...), documents_present: str = Form(...), passport: Optional[UploadFile] = File(None),
    visa: Optional[UploadFile] = File(None), nationalId: Optional[UploadFile] = File(None),
    drivingLicence: Optional[UploadFile] = File(None), permit: Optional[UploadFile] = File(None),
    selfie: Optional[UploadFile] = File(None),
) -> Dict[str, Any]:
    try:
        present: Dict[str, bool] = json.loads(documents_present)
    except json.JSONDecodeError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "documents_present must be valid JSON")

    documents = {"passport": passport, "visa": visa, "nationalId": nationalId, "drivingLicence": drivingLicence, "permit": permit}
    uploaded = [(k, f) for k, f in documents.items() if f is not None]
    missing = [k for k in documents if present.get(k) and documents[k] is None]
    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"documents_present says '{missing[0]}' is present but no file was sent")
    if not uploaded:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No documents uploaded")

    s_uuid, db = ensure_uuid(uuid), DatabaseManager.get_instance()
    try:
        db.upsert_screening_session(session_id=s_uuid, pipeline_version="v1.0.0", status="PROCESSING")
    except Exception as err:
        logger.error("Failed to open session %s: %s", s_uuid, err)

    start_t = time.perf_counter()
    file_payloads = [(k, f.filename or k, await f.read()) for k, f in uploaded]

    async def _screen_one(key: str, filename: str, content: bytes):
        return (key, await asyncio.to_thread(run_screening_pipeline, content, filename))

    pipeline_results = await asyncio.gather(*[_screen_one(k, fn, c) for k, fn, c in file_payloads])

    reason_codes, scores, canonical_scores = [], [], []
    hard_fail = False
    parsed_docs, all_checks = [], []

    for key, (ingested, ocr_res, parsed, _, decision, watchlist_hits, _) in pipeline_results:
        parsed_docs.append(parsed)
        scores.append(decision.score)
        canonical_scores.append(decision.canonical_score)
        hard_fail = hard_fail or decision.hard_fail
        reason_codes.extend(r.code for r in decision.reason_codes)
        all_checks.extend(decision.validation_checks)
        try:
            persist_document_extraction(db, s_uuid, ensure_uuid(None), ingested, ocr_res, parsed, decision, watchlist_hits)
        except Exception as err:
            logger.error("Failed to persist document '%s': %s", key, err)

    if len(parsed_docs) > 1:
        cross = cross_check_documents(parsed_docs)
        if not cross.consistent:
            hard_fail = True
            reason_codes.append("cross_document_mismatch")
            incon_msg = "; ".join(fr.detail for fr in cross.field_results if not fr.consistent) or "Identity fields differ across documents."
            all_checks.append(ValidationCheckRecord(check_type="CROSS_DOCUMENT_CONSISTENCY", field_key="cross_document", status="FAIL", is_hard_fail=True, expected_value="CONSISTENT", observed_value="INCONSISTENT", detail=incon_msg))

    final_canonical_score = 0.0 if hard_fail else round(sum(canonical_scores) / len(canonical_scores), 4)
    final_score = round(final_canonical_score * 100.0, 2)
    elapsed_ms = round((time.perf_counter() - start_t) * 1000.0, 2)

    try:
        db.upsert_screening_session(session_id=s_uuid, pipeline_version="v1.0.0", status="FAILED" if hard_fail else "COMPLETED")
        db.upsert_module_score(session_id=s_uuid, score_kind="A", value=final_canonical_score, detail={"latency_ms": elapsed_ms})
        db.insert_audit_log(session_id=s_uuid, action="OCR_MODULE_SCREENING_COMPLETED", entity_type="SESSION", entity_id=s_uuid, payload={"score": final_score, "canonical_score": final_canonical_score, "hard_fail": hard_fail, "latency_ms": elapsed_ms})
    except Exception as err:
        logger.error("Failed to persist final score for %s: %s", s_uuid, err)

    primary = parsed_docs[0] if parsed_docs else None
    return {
        "score": final_score, "hard_fail": hard_fail, "reason_codes": reason_codes, "latency_ms": elapsed_ms,
        "details": {
            "claimed_name": primary.claimed_name if primary else None, "document_number": primary.document_number if primary else None,
            "doc_type": primary.doc_type if primary else None, "mrz_valid": primary.mrz_result.valid_format if (primary and primary.mrz_result) else False,
            "extracted_fields": [{"field_key": f.field_key, "field_value": f.field_value, "source": f.source, "confidence": f.confidence} for d in parsed_docs for f in d.fields],
            "validation_checks": [{"check_type": c.check_type, "status": c.status, "detail": c.detail, "field_key": c.field_key} for c in all_checks],
        },
    }
