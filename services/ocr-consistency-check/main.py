"""OCR & Consistency Check Microservice (Module 1 - Operation PRAMAAN).

Entry point for SIH26188 Module 1.
Handles document ingestion (PDF/Images), PaddleOCR text extraction,
MRZ ICAO 9303 validation, watchlist screening, registry candidate matching,
and weighted Score A calculation.
"""

from __future__ import annotations
import asyncio
import json
import logging
import os
import uuid
import uuid as py_uuid  # alias for use inside /screen, whose own `uuid` param shadows the module
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Optional

import httpx
from aiobreaker import CircuitBreakerError
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, status
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from pydantic import BaseModel, Field
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from candidate_search import CandidateSearchEngine
from cross_document import cross_check_documents
from db import DatabaseManager
from decision_matrix import DecisionOutcome, evaluate_decision_matrix
from field_extractor import ParsedDocumentData, extract_document_fields
from inference_pool import InferenceCrashed, run_isolated
from ingestion import IngestedDocument, ingest_file
from matcher import MatchOutcome, match_against_candidate
from multilingual_service import router as multilingual_router
from ocr_engine import OCREngine
from rate_limit import SCREEN_RATE_LIMIT, limiter
from result_cache import ResultCache
from risk_engine_breaker import RISK_ENGINE_BREAKER
from script_detector import COUNTRY_TO_LANG

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ocr_service")

RISK_ENGINE_URL = os.environ.get("RISK_ENGINE_URL", "http://localhost:8004").rstrip("/")
_cache = ResultCache(namespace="ocr")


@RISK_ENGINE_BREAKER
async def _push_to_risk_engine(session_id: str, hard_fail: bool, score: float, reasons: List[str]) -> None:
    async with httpx.AsyncClient(timeout=5.0) as client:
        await client.post(
            f"{RISK_ENGINE_URL}/flag-check",
            json={"uuid": session_id, "module": "ocr", "flag": hard_fail, "reasons": reasons},
        )
        # If that flag was true, the risk engine already rejected and cleared this uuid —
        # this second call still fires (simpler than branching), but lands on the
        # already-finalized guard on the other end rather than a live wait.
        await client.post(
            f"{RISK_ENGINE_URL}/submit-score",
            json={"uuid": session_id, "module": "ocr", "ocr": {"score": score, "reasons": reasons}},
        )
    logger.info("uuid=%s pushed to risk-scoring-engine (flag=%s, score=%s)", session_id, hard_fail, score)


async def _notify_risk_engine(session_id: str, hard_fail: bool, score: float, reasons: List[str]) -> None:
    """Push this module's flag + score to risk-scoring-engine (see
    ../../services/risk-scoring-engine/README.md for the two-stage contract). Best-effort:
    the risk engine being down must never break this service's own /screen response to the
    frontend, so failures are logged and swallowed rather than raised. Circuit-breaker-backed
    (see risk_engine_breaker.py) so a down risk-scoring-engine fails fast instead of costing
    a full httpx timeout on every single request."""
    try:
        await _push_to_risk_engine(session_id, hard_fail, score, reasons)
    except CircuitBreakerError:
        logger.warning("uuid=%s risk-scoring-engine circuit open, skipping push", session_id)
    except httpx.HTTPError as exc:
        logger.warning("uuid=%s risk-scoring-engine unreachable, skipping push: %s", session_id, exc)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Pre-warm models and initialize connections at service startup."""
    logger.info("Initializing OCR & Consistency Check Service...")
    db = DatabaseManager.get_instance()
    logger.info("Database backend initialized (PostgreSQL: %s).", db.is_postgres)
    engine = OCREngine.get_instance()
    logger.info("OCR Engine initialized: %s.", engine._engine_name)
    yield
    logger.info("Shutting down OCR & Consistency Check Service...")


app = FastAPI(
    title="Operation PRAMAAN — Module 1 (OCR & Consistency Check)",
    description="FastAPI service for document text extraction, MRZ checksum verification, and registry matching.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Exposes /metrics (request count/latency/in-flight, per route+status) for Prometheus to
# scrape — see docker-compose.yml's prometheus service and monitoring/prometheus.yml.
Instrumentator().instrument(app).expose(app)

app.include_router(multilingual_router)


# -------------------------------------------------------------
# Request & Response Models
# -------------------------------------------------------------
class VerifyTextRequest(BaseModel):
    doc_type: str = Field(default="PASSPORT", description="Type of document (e.g. PASSPORT, NATIONAL_ID)")
    document_number: str = Field(..., description="Document ID number")
    full_name: Optional[str] = Field(None, description="Name as printed on document")
    dob: Optional[str] = Field(None, description="Date of birth in YYYY-MM-DD or common formats")
    session_id: Optional[str] = None


class ScreenResponse(BaseModel):
    session_id: str
    document_id: str
    status: str  # 'VERIFIED', 'NEEDS REVIEW', 'NOT VERIFIED'
    score: float  # 0..100 for display
    canonical_score: float  # 0..1 for database
    hard_fail: bool
    doc_type: str
    document_number: Optional[str]
    claimed_name: Optional[str]
    claimed_dob: Optional[str]
    claimed_expiry: Optional[str]
    claimed_gender: Optional[str]
    issuing_country: str
    detected_language: str = "English"
    detected_script: str = "Latin"
    claimed_dob_bs: Optional[str] = None
    calendar_system: str = "GREGORIAN"
    reason_codes: List[Dict[str, Any]]
    validation_checks: List[Dict[str, Any]]
    candidate_matched: bool
    candidate_details: Optional[Dict[str, Any]] = None
    mrz_valid: Optional[bool] = None
    extracted_fields: List[Dict[str, Any]]


# -------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------
@app.get("/api/v1/health", tags=["Monitoring"])
def health_check() -> Dict[str, Any]:
    """Health check endpoint providing runtime and engine status."""
    db = DatabaseManager.get_instance()
    engine = OCREngine.get_instance()
    return {
        "status": "healthy",
        "service": "ocr-consistency-check",
        "version": "1.0.0",
        "database": "postgresql" if db.is_postgres else "sqlite_fallback",
        "ocr_engine": engine._engine_name,
    }


def _extract_text_isolated(image, lang: Optional[str]):
    """Runs in an isolated worker process (see inference_pool.py) — this is the actual
    PaddleOCR/Tesseract call, the one part of the pipeline that can segfault natively."""
    return OCREngine.get_instance().extract_text(image, lang=lang)


@app.post("/api/v1/extract-only", tags=["Extraction"])
async def extract_only(
    file: UploadFile = File(...),
    expected_country: Optional[str] = Form(None),
    expected_language: Optional[str] = Form(None),
) -> Dict[str, Any]:
    """Step 1 Endpoint: Extract raw OCR text and parsed fields without running DB matching."""
    try:
        content = await file.read()
        ingested = await run_in_threadpool(ingest_file, content, file.filename or "")

        ocr_lang = None
        if expected_country and expected_country.upper() in COUNTRY_TO_LANG:
            ocr_lang = COUNTRY_TO_LANG[expected_country.upper()][2]
        elif expected_language:
            ocr_lang = f"eng+{expected_language}" if expected_language != "eng" else "eng"

        try:
            ocr_res = await run_isolated(_extract_text_isolated, ingested.images[0], ocr_lang)
        except InferenceCrashed as err:
            raise HTTPException(status_code=503, detail=f"OCR engine crashed: {err}")
        parsed = extract_document_fields(ocr_res, expected_country=expected_country, expected_language=expected_language)

        return {
            "doc_type": parsed.doc_type,
            "document_number": parsed.document_number,
            "claimed_name": parsed.claimed_name,
            "claimed_dob": parsed.claimed_dob,
            "claimed_dob_bs": parsed.claimed_dob_bs,
            "calendar_system": parsed.calendar_system,
            "detected_language": parsed.detected_language,
            "detected_script": parsed.detected_script,
            "claimed_expiry": parsed.claimed_expiry,
            "claimed_gender": parsed.claimed_gender,
            "issuing_country": parsed.issuing_country,
            "mrz_detected": parsed.mrz_result is not None,
            "mrz_valid": parsed.mrz_result.valid_format if parsed.mrz_result else False,
            "raw_text": ocr_res.full_text,
            "fields": [
                {
                    "key": f.field_key,
                    "value": f.field_value,
                    "source": f.source,
                    "confidence": f.confidence,
                    "bbox": f.bbox,
                }
                for f in parsed.fields
            ],
        }
    except Exception as err:
        logger.error("Extraction failed: %s", err)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(err))


def _run_screening_pipeline(
    content: bytes,
    filename: str,
    expected_country: Optional[str] = None,
    expected_language: Optional[str] = None,
):
    """Steps 1-5 of the screening pipeline: ingest -> OCR -> field/MRZ extraction ->
    watchlist/candidate search -> matching -> decision. Shared by /api/v1/screen (single
    document, full response) and /screen (the frontend-facing multi-document contract)."""
    ingested = ingest_file(content, filename or "")

    ocr_lang = None
    if expected_country and expected_country.upper() in COUNTRY_TO_LANG:
        ocr_lang = COUNTRY_TO_LANG[expected_country.upper()][2]
    elif expected_language:
        ocr_lang = f"eng+{expected_language}" if expected_language != "eng" else "eng"

    ocr_engine = OCREngine.get_instance()
    ocr_res = ocr_engine.extract_text(ingested.images[0], lang=ocr_lang)
    parsed = extract_document_fields(ocr_res, expected_country=expected_country, expected_language=expected_language)

    search_engine = CandidateSearchEngine()
    watchlist_hits = search_engine.screen_watchlist(
        document_number=parsed.document_number,
        full_name=parsed.claimed_name,
        dob=parsed.claimed_dob,
    )
    candidates = search_engine.find_candidate_documents(
        doc_type=parsed.doc_type,
        id_number=parsed.document_number,
        dob=parsed.claimed_dob,
    )
    selected_candidate = candidates[0] if candidates else None
    match_outcome = match_against_candidate(parsed, selected_candidate)
    decision = evaluate_decision_matrix(parsed, match_outcome, watchlist_hits)
    return ingested, ocr_res, parsed, match_outcome, decision, watchlist_hits, selected_candidate


@app.post("/api/v1/screen", response_model=ScreenResponse, tags=["Screening"])
async def screen_document(
    file: UploadFile = File(...),
    session_id: Optional[str] = Form(None),
    document_id: Optional[str] = Form(None),
    expected_country: Optional[str] = Form(None),
    expected_language: Optional[str] = Form(None),
) -> ScreenResponse:
    """Full Screening Pipeline: Ingestion -> OCR -> MRZ Verification -> DB Candidate Search -> Decision."""
    s_id = session_id or str(uuid.uuid4())
    d_id = document_id or str(uuid.uuid4())

    try:
        content = await file.read()
        ingested, ocr_res, parsed, match_outcome, decision, watchlist_hits, selected_candidate = await run_isolated(
            _run_screening_pipeline, content, file.filename or "", expected_country, expected_language
        )
    except InferenceCrashed as err:
        raise HTTPException(status_code=503, detail=f"OCR pipeline crashed: {err}")
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"File ingestion error: {err}")

    # Database Persistence
    await run_in_threadpool(_persist_screening_session, s_id, d_id, ingested, ocr_res, parsed, decision, watchlist_hits)

    cand_dict = None
    if selected_candidate:
        cand_dict = {
            "record_id": selected_candidate.record_id,
            "id_number": selected_candidate.id_number,
            "full_name": selected_candidate.full_name,
            "dob": selected_candidate.dob,
            "status": selected_candidate.status,
            "expiry_date": selected_candidate.expiry_date,
        }

    return ScreenResponse(
        session_id=s_id,
        document_id=d_id,
        status=decision.status,
        score=decision.score,
        canonical_score=decision.canonical_score,
        hard_fail=decision.hard_fail,
        doc_type=parsed.doc_type,
        document_number=parsed.document_number,
        claimed_name=parsed.claimed_name,
        claimed_dob=parsed.claimed_dob,
        claimed_expiry=parsed.claimed_expiry,
        claimed_gender=parsed.claimed_gender,
        issuing_country=parsed.issuing_country or "IND",
        detected_language=parsed.detected_language,
        detected_script=parsed.detected_script,
        claimed_dob_bs=parsed.claimed_dob_bs,
        calendar_system=parsed.calendar_system,
        reason_codes=[
            {"code": r.code, "message": r.message, "severity": r.severity, "contribution": r.contribution}
            for r in decision.reason_codes
        ],
        validation_checks=[
            {
                "check_type": c.check_type,
                "field_key": c.field_key,
                "status": c.status,
                "is_hard_fail": c.is_hard_fail,
                "expected": c.expected_value,
                "observed": c.observed_value,
                "detail": c.detail,
            }
            for c in decision.validation_checks
        ],
        candidate_matched=match_outcome.has_candidate,
        candidate_details=cand_dict,
        mrz_valid=parsed.mrz_result.valid_format if parsed.mrz_result else None,
        extracted_fields=[
            {"field_key": f.field_key, "field_value": f.field_value, "source": f.source, "confidence": f.confidence}
            for f in parsed.fields
        ],
    )


@app.post("/api/v1/cross-verify", tags=["Cross-Document"])
async def cross_verify_documents(files: List[UploadFile] = File(...)) -> Dict[str, Any]:
    """Cross-check name/DOB/gender consistency across 2+ documents for the same person
    (e.g. passport + driving licence + visa). Independent of /screen; does not touch DB."""
    if len(files) < 2:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Upload at least 2 documents to cross-verify.")

    async def _parse(f: UploadFile) -> ParsedDocumentData:
        try:
            content = await f.read()
            ingested = await run_in_threadpool(ingest_file, content, f.filename or "")
            ocr_res = await run_isolated(_extract_text_isolated, ingested.images[0], None)
            return await run_in_threadpool(extract_document_fields, ocr_res)
        except InferenceCrashed as err:
            raise HTTPException(status_code=503, detail=f"OCR engine crashed processing '{f.filename}': {err}")
        except Exception as err:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to process '{f.filename}': {err}")

    parsed_docs: List[ParsedDocumentData] = await asyncio.gather(*(_parse(f) for f in files))

    outcome = cross_check_documents(parsed_docs)
    return {
        "consistent": outcome.consistent,
        "documents": [
            {
                "filename": f.filename,
                "doc_type": d.doc_type,
                "document_number": d.document_number,
                "claimed_name": d.claimed_name,
                "claimed_dob": d.claimed_dob,
                "claimed_gender": d.claimed_gender,
                "mrz_valid": d.mrz_result.valid_format and not d.mrz_result.has_checksum_failure if d.mrz_result else None,
            }
            for f, d in zip(files, parsed_docs)
        ],
        "field_results": [
            {"field": r.field_key, "consistent": r.consistent, "values": r.values, "detail": r.detail}
            for r in outcome.field_results
        ],
    }


@app.post("/api/v1/verify-text", tags=["Verification"])
def verify_text_only(req: VerifyTextRequest) -> Dict[str, Any]:
    """Verify document credentials directly against registry without image processing."""
    s_id = req.session_id or str(uuid.uuid4())
    search_engine = CandidateSearchEngine()

    watchlist_hits = search_engine.screen_watchlist(
        document_number=req.document_number,
        full_name=req.full_name,
        dob=req.dob,
    )
    candidates = search_engine.find_candidate_documents(
        doc_type=req.doc_type,
        id_number=req.document_number,
        dob=req.dob,
    )
    selected_candidate = candidates[0] if candidates else None

    dummy_parsed = ParsedDocumentData(
        doc_type=req.doc_type,
        document_number=req.document_number,
        claimed_name=req.full_name,
        claimed_dob=req.dob,
    )
    match_outcome = match_against_candidate(dummy_parsed, selected_candidate)
    decision = evaluate_decision_matrix(dummy_parsed, match_outcome, watchlist_hits)

    return {
        "session_id": s_id,
        "status": decision.status,
        "score": decision.score,
        "canonical_score": decision.canonical_score,
        "hard_fail": decision.hard_fail,
        "reason_codes": [
            {"code": r.code, "message": r.message, "severity": r.severity}
            for r in decision.reason_codes
        ],
        "candidate_matched": match_outcome.has_candidate,
        "differences": match_outcome.differences,
    }


@app.post("/screen", tags=["Screening"])
@limiter.limit(SCREEN_RATE_LIMIT)
async def screen(
    request: Request,
    uuid: str = Form(...),
    documents_present: str = Form(...),
    passport: Optional[UploadFile] = File(None),
    visa: Optional[UploadFile] = File(None),
    nationalId: Optional[UploadFile] = File(None),
    drivingLicence: Optional[UploadFile] = File(None),
    permit: Optional[UploadFile] = File(None),
    selfie: Optional[UploadFile] = File(None),
) -> Dict[str, Any]:
    """Frontend-facing contract endpoint (see ../../API_CONTRACT.md). Adapts the per-document
    screening pipeline above to the shared {score, hard_fail, reason_codes} module response,
    across every document present in one submission. selfie is excluded: it belongs to the
    biometric-matching module, not OCR."""
    try:
        present: Dict[str, bool] = json.loads(documents_present)
    except json.JSONDecodeError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "documents_present must be valid JSON")

    documents = {"passport": passport, "visa": visa, "nationalId": nationalId, "drivingLicence": drivingLicence, "permit": permit}
    uploaded: List[tuple] = []
    for key, file in documents.items():
        if present.get(key) and file is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"documents_present says '{key}' is present but no file was sent")
        if file is not None:
            uploaded.append((key, file))

    if not uploaded:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No documents uploaded")

    logger.info("uuid=%s /screen received: docs=%s", uuid, [k for k, _ in uploaded])

    contents = [(key, file, await file.read()) for key, file in uploaded]

    # Same exact set of document bytes re-submitted (retry, refresh, duplicate kiosk scan)?
    # Skip the OCR/watchlist pipeline entirely and reuse last time's result — it's
    # deterministic for identical input. The risk-scoring-engine push still happens below
    # with this call's own uuid, so per-submission coordination is unaffected.
    fingerprint = ResultCache.fingerprint(*(c for _, _, c in contents))
    cached = _cache.get(fingerprint)
    if cached is not None:
        logger.info("uuid=%s /screen cache hit (fingerprint=%s)", uuid, fingerprint[:12])
        await _notify_risk_engine(uuid, cached["hard_fail"], cached["score"], cached["reason_codes"])
        return cached

    # Each document's OCR + matching + decision pipeline is independent until the
    # cross-document check below, and each one is CPU-bound (blocks a thread, not the
    # event loop) — run them off the event loop and concurrently rather than one at a time,
    # each in its own isolated worker process (see inference_pool.py) so a native OCR crash
    # only fails this one document instead of the whole service.
    async def _screen_one(key: str, file: UploadFile, content: bytes):
        try:
            return key, await run_isolated(_run_screening_pipeline, content, file.filename or key)
        except InferenceCrashed as err:
            # Don't call _notify_risk_engine here — risk-scoring-engine's own timeout sweeper
            # is explicitly designed for "one module crashed, or just never called back"
            # (see its docstring) and will auto-escalate this uuid to MANUAL_REVIEW.
            logger.error("uuid=%s OCR pipeline crashed for %s: %s", uuid, key, err)
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"{key}: OCR pipeline crashed")
        except Exception as err:
            logger.error("Screening failed for %s: %s", key, err)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"{key}: {err}")

    results = await asyncio.gather(*(_screen_one(key, file, content) for key, file, content in contents))

    reason_codes: List[str] = []
    scores: List[float] = []
    hard_fail = False
    parsed_docs: List[ParsedDocumentData] = []

    for key, (ingested, ocr_res, parsed, _, decision, watchlist_hits, _) in results:
        parsed_docs.append(parsed)
        scores.append(decision.score)
        hard_fail = hard_fail or decision.hard_fail
        reason_codes.extend(r.code for r in decision.reason_codes)
        # session_id = the frontend's submission uuid (shared across all documents in this
        # call); document_id is per-document since each upload is its own audit row.
        await run_in_threadpool(
            _persist_screening_session, uuid, str(py_uuid.uuid4()), ingested, ocr_res, parsed, decision, watchlist_hits
        )

    if len(parsed_docs) > 1:
        cross = cross_check_documents(parsed_docs)
        if not cross.consistent:
            hard_fail = True
            reason_codes.append("cross_document_mismatch")

    final_score = min(scores) if scores else 0
    logger.info("uuid=%s /screen result: score=%s hard_fail=%s reasons=%s", uuid, final_score, hard_fail, reason_codes)
    result = {"score": final_score, "hard_fail": hard_fail, "reason_codes": reason_codes}
    _cache.set(fingerprint, result)
    await _notify_risk_engine(uuid, hard_fail, final_score, reason_codes)
    return result


def _persist_screening_session(
    session_id: str,
    document_id: str,
    ingested: IngestedDocument,
    ocr_res: Any,
    parsed: ParsedDocumentData,
    decision: DecisionOutcome,
    watchlist_hits: List[Any],
) -> None:
    """Save screening audit artifacts into relational schema."""
    db = DatabaseManager.get_instance()
    try:
        # 1. Log module score A
        db.execute(
            """
            INSERT INTO module_scores (score_id, session_id, score_kind, value, detail)
            VALUES (%s, %s, %s, %s, %s);
            """,
            (str(uuid.uuid4()), session_id, "A", decision.canonical_score, str(decision.sub_scores)),
        )

        # 2. Log validation checks
        for c in decision.validation_checks:
            db.execute(
                """
                INSERT INTO validation_checks 
                    (check_id, document_id, module, check_type, field_key, status, is_hard_fail, expected_value, observed_value, detail)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
                """,
                (str(uuid.uuid4()), document_id, "MODULE_1", c.check_type, c.field_key or "", c.status, 1 if c.is_hard_fail else 0, c.expected_value or "", c.observed_value or "", c.detail),
            )

        # 3. Log watchlist hits
        for h in watchlist_hits:
            db.execute(
                """
                INSERT INTO watchlist_hits (hit_id, session_id, document_id, entry_id, match_basis, match_score, is_hard_fail)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
                """,
                (str(uuid.uuid4()), session_id, document_id, h.entry_id, h.match_basis, h.match_score, 1 if h.is_hard_fail else 0),
            )
    except Exception as err:
        logger.warning("Audit persistence notice: %s", err)

