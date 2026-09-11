"""Dedicated Multilingual & Regional Consistency Microservice.

Provides independent and mounted API endpoints for:
- Language & script detection from document images or extracted text
- Bikram Sambat (B.S.) Nepali calendar conversion to Gregorian (A.D.)
- Regional Tesseract OCR extraction using local engine
- End-to-end multilingual document screening and consistency checks
"""

from __future__ import annotations
import logging
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Request, UploadFile, status
from pydantic import BaseModel, Field

from ingestion import ingest_file
from multilingual_consistency import evaluate_multilingual_consistency
from multilingual_ocr import MultilingualOCREngine
from nepali_calendar import convert_bikram_sambat
from script_detector import detect_script_and_language

logger = logging.getLogger("multilingual_service")

router = APIRouter(prefix="/api/v1/multilingual", tags=["Multilingual Screening"])


# -------------------------------------------------------------
# Request & Response Schemas
# -------------------------------------------------------------
class LanguageDetectRequest(BaseModel):
    text: Optional[str] = Field(None, description="Raw text snippet to detect language from")
    expected_country: Optional[str] = Field(None, description="ISO-3 country hint (e.g. NPL, BGD, PAK)")


class LanguageDetectResponse(BaseModel):
    detected_script: str
    language_code: str
    language_name: str
    confidence: float
    is_english: bool
    tesseract_lang: str
    script_distribution: Dict[str, float]


class CalendarConvertRequest(BaseModel):
    date_or_year: str = Field(..., description="Nepali date or year e.g. '2082-04-25', '15 Baishakh 2080', '2080 BS', '२०८०/०१/१५'")


class CalendarConvertResponse(BaseModel):
    raw_input: str
    bs_year: int
    bs_month: Optional[int]
    bs_day: Optional[int]
    bs_month_name: Optional[str]
    gregorian_date: Optional[str]
    gregorian_primary_year: int
    gregorian_year_span: str
    is_valid: bool
    detail: str


class MultilingualScreenResponse(BaseModel):
    session_id: str
    document_id: str
    status: str
    score: float
    hard_fail: bool
    detected_language: str
    detected_script: str
    issuing_country: str
    document_number: Optional[str]
    claimed_name: Optional[str]
    claimed_dob_bs: Optional[str]
    claimed_dob_gregorian: Optional[str]
    raw_text: str
    calendar_conversion: Optional[Dict[str, Any]]
    validation_checks: List[Dict[str, Any]]
    reason_codes: List[Dict[str, Any]]


# -------------------------------------------------------------
# Endpoints
# -------------------------------------------------------------
@router.post("/detect-language", response_model=LanguageDetectResponse)
async def detect_language_endpoint(request: Request) -> LanguageDetectResponse:
    """Detect dominant language and script from text or an uploaded image."""
    content_type = request.headers.get("content-type", "")
    text_to_check = None
    hint_country = None

    if "application/json" in content_type:
        body = await request.json()
        text_to_check = body.get("text")
        hint_country = body.get("expected_country")
    else:
        form = await request.form()
        text_to_check = form.get("text")
        hint_country = form.get("expected_country")
        uploaded = form.get("file")
        if uploaded and hasattr(uploaded, "read"):
            content = await uploaded.read()
            ingested = ingest_file(content, getattr(uploaded, "filename", "doc.png"))
            ocr = MultilingualOCREngine.get_instance()
            ocr_res = ocr.extract_text(ingested.images[0], lang="eng+nep")
            text_to_check = ocr_res.full_text

    result = detect_script_and_language(text_to_check, expected_country=hint_country)
    return LanguageDetectResponse(
        detected_script=result.detected_script,
        language_code=result.language_code,
        language_name=result.language_name,
        confidence=result.confidence,
        is_english=result.is_english,
        tesseract_lang=result.tesseract_lang,
        script_distribution=result.script_distribution,
    )


@router.post("/convert-calendar", response_model=CalendarConvertResponse)
def convert_calendar_endpoint(req: CalendarConvertRequest) -> CalendarConvertResponse:
    """Convert Nepali Bikram Sambat (B.S.) date or year to Gregorian (A.D.)."""
    cal_res = convert_bikram_sambat(req.date_or_year)
    return CalendarConvertResponse(
        raw_input=cal_res.raw_input,
        bs_year=cal_res.bs_year,
        bs_month=cal_res.bs_month,
        bs_day=cal_res.bs_day,
        bs_month_name=cal_res.bs_month_name,
        gregorian_date=cal_res.gregorian_date,
        gregorian_primary_year=cal_res.gregorian_primary_year,
        gregorian_year_span=cal_res.gregorian_year_span,
        is_valid=cal_res.is_valid,
        detail=cal_res.detail,
    )


@router.post("/ocr")
async def multilingual_ocr_endpoint(
    file: UploadFile = File(...),
    lang: Optional[str] = Form("eng+nep"),
) -> Dict[str, Any]:
    """Execute local Tesseract OCR with specified regional language pack."""
    content = await file.read()
    ingested = ingest_file(content, file.filename or "")
    ocr = MultilingualOCREngine.get_instance()
    ocr_res = ocr.extract_text(ingested.images[0], lang=lang or "eng+nep")

    return {
        "engine": ocr_res.engine,
        "average_confidence": ocr_res.average_confidence,
        "full_text": ocr_res.full_text,
        "lines": ocr_res.lines,
        "blocks": [
            {"text": b.text, "confidence": b.confidence, "bbox": b.bbox}
            for b in ocr_res.blocks
        ],
    }


@router.post("/screen", response_model=MultilingualScreenResponse)
async def multilingual_screen_endpoint(
    file: UploadFile = File(...),
    expected_country: Optional[str] = Form("NPL"),
    expected_ad_dob: Optional[str] = Form(None),
) -> MultilingualScreenResponse:
    """Full Multilingual Screening: Language Detection -> Tesseract OCR -> Calendar Conversion -> Consistency."""
    content = await file.read()
    ingested = ingest_file(content, file.filename or "")

    # 1. OCR with regional language pack
    ocr = MultilingualOCREngine.get_instance()
    lang_to_use = "eng+nep" if expected_country == "NPL" else "eng"
    ocr_res = ocr.extract_text(ingested.images[0], lang=lang_to_use)

    # 2. Detect language from extracted text
    lang_info = detect_script_and_language(ocr_res.full_text, expected_country=expected_country)

    # 3. Field parsing with regional vocabulary
    from field_extractor import extract_document_fields
    parsed = extract_document_fields(ocr_res, expected_country=expected_country)

    # 4. Multilingual & Calendar consistency
    consistency = evaluate_multilingual_consistency(
        document_number=parsed.document_number,
        claimed_name=parsed.claimed_name,
        claimed_bs_date=parsed.claimed_dob,
        expected_ad_date=expected_ad_dob,
        issuing_country=expected_country or parsed.issuing_country or "NPL",
    )

    score = 90.0 if consistency.is_consistent else (0.0 if consistency.hard_fail else 60.0)
    status_label = "VERIFIED" if consistency.is_consistent else ("NOT VERIFIED" if consistency.hard_fail else "NEEDS REVIEW")

    cal_dict = None
    if consistency.calendar_conversion and consistency.calendar_conversion.is_valid:
        cal = consistency.calendar_conversion
        cal_dict = {
            "bs_year": cal.bs_year,
            "bs_month": cal.bs_month,
            "bs_month_name": cal.bs_month_name,
            "gregorian_date": cal.gregorian_date,
            "gregorian_year_span": cal.gregorian_year_span,
            "detail": cal.detail,
        }

    return MultilingualScreenResponse(
        session_id=str(uuid.uuid4()),
        document_id=str(uuid.uuid4()),
        status=status_label,
        score=score,
        hard_fail=consistency.hard_fail,
        detected_language=lang_info.language_name,
        detected_script=lang_info.detected_script,
        issuing_country=expected_country or parsed.issuing_country or "NPL",
        document_number=parsed.document_number,
        claimed_name=parsed.claimed_name,
        claimed_dob_bs=parsed.claimed_dob,
        claimed_dob_gregorian=cal_dict.get("gregorian_date") if cal_dict else parsed.claimed_dob,
        raw_text=ocr_res.full_text,
        calendar_conversion=cal_dict,
        validation_checks=[
            {
                "check_name": c.check_name,
                "status": c.status,
                "is_hard_fail": c.is_hard_fail,
                "detail": c.detail,
            }
            for c in consistency.checks
        ],
        reason_codes=[
            {"code": f"MULTILINGUAL_{c.check_name}", "message": c.detail, "severity": "HIGH" if c.is_hard_fail else "MEDIUM"}
            for c in consistency.checks if c.status != "PASS"
        ],
    )


# Standalone FastAPI application instance for independent microservice execution
app = FastAPI(
    title="Operation PRAMAAN — Multilingual & Regional Consistency Microservice",
    description="Microservice for language detection, regional Tesseract OCR, and Bikram Sambat calendar conversion.",
    version="1.0.0",
)
app.include_router(router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8005)
