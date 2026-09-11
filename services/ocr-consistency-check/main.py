"""OCR & Consistency Check Microservice (Module 1 - Operation PRAMAAN).

Entry point for SIH26188 Module 1.
Handles document ingestion (PDF/Images), PaddleOCR text extraction,
MRZ ICAO 9303 validation, watchlist screening, registry candidate matching,
and weighted Score A calculation.
"""

from __future__ import annotations
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from candidate_search import CandidateSearchEngine
from cross_document import cross_check_documents
from db import DatabaseManager
from decision_matrix import DecisionOutcome, evaluate_decision_matrix
from field_extractor import ParsedDocumentData, extract_document_fields
from ingestion import IngestedDocument, ingest_file
from matcher import MatchOutcome, match_against_candidate
from multilingual_service import router as multilingual_router
from ocr_engine import OCREngine
from script_detector import COUNTRY_TO_LANG

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ocr_service")


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


@app.post("/api/v1/extract-only", tags=["Extraction"])
async def extract_only(
    file: UploadFile = File(...),
    expected_country: Optional[str] = Form(None),
    expected_language: Optional[str] = Form(None),
) -> Dict[str, Any]:
    """Step 1 Endpoint: Extract raw OCR text and parsed fields without running DB matching."""
    try:
        content = await file.read()
        ingested = ingest_file(content, file.filename or "")
        ocr_engine = OCREngine.get_instance()

        ocr_lang = None
        if expected_country and expected_country.upper() in COUNTRY_TO_LANG:
            ocr_lang = COUNTRY_TO_LANG[expected_country.upper()][2]
        elif expected_language:
            ocr_lang = f"eng+{expected_language}" if expected_language != "eng" else "eng"

        ocr_res = ocr_engine.extract_text(ingested.images[0], lang=ocr_lang)
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
        ingested = ingest_file(content, file.filename or "")
    except Exception as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"File ingestion error: {err}")

    # 1. OCR Text Extraction (with regional language override if indicated)
    ocr_lang = None
    if expected_country and expected_country.upper() in COUNTRY_TO_LANG:
        ocr_lang = COUNTRY_TO_LANG[expected_country.upper()][2]
    elif expected_language:
        ocr_lang = f"eng+{expected_language}" if expected_language != "eng" else "eng"

    ocr_engine = OCREngine.get_instance()
    ocr_res = ocr_engine.extract_text(ingested.images[0], lang=ocr_lang)

    # 2. Field Extraction & MRZ Verification with Multilingual / Calendar Normalization
    parsed = extract_document_fields(ocr_res, expected_country=expected_country, expected_language=expected_language)

    # 3. Watchlist Screening & Candidate Document Search
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

    # 4. Strict & Fuzzy Matching
    match_outcome = match_against_candidate(parsed, selected_candidate)

    # 5. Weighted Decision Matrix & Reason Codes
    decision = evaluate_decision_matrix(parsed, match_outcome, watchlist_hits)

    # 6. Database Persistence
    _persist_screening_session(s_id, d_id, ingested, ocr_res, parsed, decision, watchlist_hits)

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

    ocr_engine = OCREngine.get_instance()
    parsed_docs: List[ParsedDocumentData] = []
    for f in files:
        try:
            content = await f.read()
            ingested = ingest_file(content, f.filename or "")
            ocr_res = ocr_engine.extract_text(ingested.images[0])
            parsed_docs.append(extract_document_fields(ocr_res))
        except Exception as err:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to process '{f.filename}': {err}")

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

