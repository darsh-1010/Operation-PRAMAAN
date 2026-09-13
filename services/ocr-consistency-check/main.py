"""OCR & Consistency Check Microservice (Module 1 - Operation PRAMAAN).

Entry point for SIH26188 Module 1.
Handles document ingestion (PDF/Images), PaddleOCR text extraction,
MRZ ICAO 9303 validation, watchlist screening, registry candidate matching,
and weighted Score A calculation.
"""

from __future__ import annotations
import json
import logging
import os
import uuid
from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from candidate_search import CandidateSearchEngine
from db import DatabaseManager
from decision_matrix import DecisionOutcome, evaluate_decision_matrix
from field_extractor import ParsedDocumentData, extract_document_fields
from ingestion import IngestedDocument, ingest_file
from cross_document import cross_check_documents
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


def _resolve_ocr_lang(expected_country: Optional[str], expected_language: Optional[str]) -> Optional[str]:
    """Map a country/language hint to the Tesseract language pack to use for regional
    scripts. Returns None for English/unspecified, so callers fall back to the default
    PaddleOCR/English-Tesseract path in OCREngine.extract_text()."""
    if expected_country and expected_country.upper() in COUNTRY_TO_LANG:
        return COUNTRY_TO_LANG[expected_country.upper()][2]
    if expected_language:
        return f"eng+{expected_language}" if expected_language != "eng" else "eng"
    return None


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
        ocr_lang = _resolve_ocr_lang(expected_country, expected_language)
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


@app.post("/api/v1/cross-verify", tags=["Cross-Document"])
async def cross_verify_documents(files: List[UploadFile] = File(...)) -> Dict[str, Any]:
    """Verify consistency across multiple uploaded documents."""
    if len(files) < 2:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="At least two documents are required for cross-verification.",
        )

    parsed_docs: List[ParsedDocumentData] = []
    ocr_engine = OCREngine.get_instance()

    for f in files:
        content = await f.read()
        ingested = ingest_file(content, f.filename or "")
        ocr_res = ocr_engine.extract_text(ingested.images[0])
        parsed = extract_document_fields(ocr_res)
        parsed_docs.append(parsed)

    outcome = cross_check_documents(parsed_docs)

    return {
        "consistent": outcome.consistent,
        "documents": [
            {
                "doc_type": d.doc_type,
                "document_number": d.document_number,
                "claimed_name": d.claimed_name,
                "claimed_dob": d.claimed_dob,
                "claimed_gender": d.claimed_gender,
            }
            for d in parsed_docs
        ],
        "field_results": [
            {
                "field_key": r.field_key,
                "consistent": r.consistent,
                "values": r.values,
                "detail": r.detail,
            }
            for r in outcome.field_results
        ],
    }


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

    ocr_engine = OCREngine.get_instance()
    ocr_lang = _resolve_ocr_lang(expected_country, expected_language)
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
        ingested, ocr_res, parsed, match_outcome, decision, watchlist_hits, selected_candidate = _run_screening_pipeline(
            content, file.filename or "", expected_country, expected_language
        )
    except HTTPException:
        raise
    except Exception as err:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"File ingestion error: {err}")

    # Database Persistence
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
async def screen(
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

    reason_codes: List[str] = []
    scores: List[float] = []
    hard_fail = False
    parsed_docs: List[ParsedDocumentData] = []

    for key, file in uploaded:
        content = await file.read()
        try:
            _, _, parsed, _, decision, _, _ = _run_screening_pipeline(content, file.filename or key)
        except Exception as err:
            logger.error("Screening failed for %s: %s", key, err)
            raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=f"{key}: {err}")
        parsed_docs.append(parsed)
        scores.append(decision.score)
        hard_fail = hard_fail or decision.hard_fail
        reason_codes.extend(r.code for r in decision.reason_codes)

    if len(parsed_docs) > 1:
        cross = cross_check_documents(parsed_docs)
        if not cross.consistent:
            hard_fail = True
            reason_codes.append("cross_document_mismatch")

    return {"score": min(scores) if scores else 0, "hard_fail": hard_fail, "reason_codes": reason_codes}


def _ensure_uuid(val: Optional[str]) -> str:
    """Ensure a string is a valid UUID, or deterministically generate one."""
    if not val:
        return str(uuid.uuid4())
    try:
        uuid.UUID(str(val))
        return str(val)
    except ValueError:
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, str(val)))


def _persist_screening_session(
    session_id: str,
    document_id: str,
    ingested: IngestedDocument,
    ocr_res: Any,
    parsed: ParsedDocumentData,
    decision: DecisionOutcome,
    watchlist_hits: List[Any],
) -> None:
    """Save screening audit artifacts into relational schema according to DB plan."""
    db = DatabaseManager.get_instance()
    try:
        s_uuid = _ensure_uuid(session_id)
        d_uuid = _ensure_uuid(document_id)
        extraction_uuid = str(uuid.uuid4())

        # 1. Screening session lifecycle (PROCESSING -> COMPLETED/FAILED)
        sess_status = "COMPLETED" if not decision.hard_fail else "FAILED"
        db.upsert_screening_session(session_id=s_uuid, pipeline_version="v1.0.0", status=sess_status)

        # 2. Document claim record
        db.insert_document(
            document_id=d_uuid,
            session_id=s_uuid,
            doc_type=parsed.doc_type,
            document_number=parsed.document_number,
            claimed_name=parsed.claimed_name,
            claimed_dob=parsed.claimed_dob,
            claimed_expiry=parsed.claimed_expiry,
            claimed_gender=parsed.claimed_gender,
            issuing_country=parsed.issuing_country or "IND",
        )

        # 3. Capture metadata
        storage_ext = ingested.mime_type.split("/")[-1] if "/" in ingested.mime_type else "png"
        storage_uri = f"uploads/{d_uuid}.{storage_ext}"
        db.insert_capture(
            session_id=s_uuid,
            document_id=d_uuid,
            kind="DOCUMENT_PHOTO",
            storage_uri=storage_uri,
            sha256=ingested.sha256,
            mime_type=ingested.mime_type,
            width_px=ingested.width_px,
            height_px=ingested.height_px,
        )

        # 4. OCR Extraction run metadata
        mrz_raw_text = "\n".join(parsed.mrz_result.raw_lines) if (parsed.mrz_result and parsed.mrz_result.raw_lines) else None
        db.insert_ocr_extraction(
            extraction_id=extraction_uuid,
            document_id=d_uuid,
            engine=getattr(ocr_res, "engine", "tesseract-5"),
            model_version=getattr(ocr_res, "model_version", "standard"),
            mrz_raw=mrz_raw_text,
            overall_confidence=getattr(ocr_res, "average_confidence", 0.90),
        )

        # 5. Extracted key-value fields with confidence and bounding boxes
        for f in parsed.fields:
            db.insert_extracted_field(
                extraction_id=extraction_uuid,
                document_id=d_uuid,
                field_key=f.field_key,
                field_value=f.field_value,
                source=f.source,
                confidence=f.confidence,
                bbox=f.bbox,
            )

        # 6. Validation checks
        for c in decision.validation_checks:
            db.insert_validation_check(
                document_id=d_uuid,
                module="MODULE_1",
                check_type=c.check_type,
                field_key=c.field_key,
                status=c.status,
                is_hard_fail=c.is_hard_fail,
                expected_value=c.expected_value,
                observed_value=c.observed_value,
                detail=c.detail,
            )

        # 7. Watchlist hits (if any positive hits found)
        for h in watchlist_hits:
            db.insert_watchlist_hit(
                session_id=s_uuid,
                document_id=d_uuid,
                entry_id=h.entry_id,
                match_basis=h.match_basis,
                match_score=h.match_score,
                is_hard_fail=h.is_hard_fail,
            )

        # 8. Module score A
        db.upsert_module_score(
            session_id=s_uuid,
            score_kind="A",
            value=decision.canonical_score,
            detail=decision.sub_scores,
        )

        # 9. Immutable audit trail entry
        db.insert_audit_log(
            session_id=s_uuid,
            action="OCR_SCREENING_COMPLETED",
            entity_type="DOCUMENT",
            entity_id=d_uuid,
            payload={
                "extraction_id": extraction_uuid,
                "score": decision.score,
                "canonical_score": decision.canonical_score,
                "status": decision.status,
                "hard_fail": decision.hard_fail,
            },
        )
        logger.info("Screening session %s audit and extractions successfully persisted to database.", s_uuid)
    except Exception as err:
        logger.error("Audit persistence failure: %s", err, exc_info=True)


