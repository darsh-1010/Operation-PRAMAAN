"""API Route handlers for OCR & Consistency Check Microservice."""

from __future__ import annotations
import asyncio, logging, uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from candidate_search import CandidateSearchEngine
from cross_document import cross_check_documents
from db import DatabaseManager
from decision_matrix import evaluate_decision_matrix
from field_extractor import ParsedDocumentData, extract_document_fields
from ingestion import ingest_file
from matcher import match_against_candidate
from ocr_engine import OCREngine
from persistence import persist_screening_session
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
