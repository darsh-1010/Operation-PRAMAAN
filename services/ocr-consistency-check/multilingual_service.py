"""Dedicated Multilingual & Regional Consistency Microservice."""

from __future__ import annotations
import logging
import uuid
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, FastAPI, File, Form, HTTPException, Request, UploadFile, status

from ingestion import ingest_file
from multilingual_consistency import evaluate_multilingual_consistency
from multilingual_ocr import MultilingualOCREngine
from multilingual_schemas import (
    CalendarConvertRequest,
    CalendarConvertResponse,
    LanguageDetectRequest,
    LanguageDetectResponse,
    MultilingualScreenResponse,
)
from nepali_calendar import convert_bikram_sambat
from script_detector import detect_script_and_language

logger = logging.getLogger("multilingual_service")
router = APIRouter(prefix="/api/v1/multilingual", tags=["Multilingual Screening"])


@router.post("/detect-language", response_model=LanguageDetectResponse)
async def detect_language_endpoint(request: Request) -> LanguageDetectResponse:
    content_type = request.headers.get("content-type", "")
    text_to_check = None
    expected_country = None

    if "application/json" in content_type:
        body = await request.json()
        req = LanguageDetectRequest(**body)
        text_to_check, expected_country = req.text, req.expected_country
    elif "multipart/form-data" in content_type:
        form = await request.form()
        expected_country = form.get("expected_country")
        if "file" in form and hasattr(form["file"], "read"):
            f = form["file"]
            content = await f.read()
            ingested = ingest_file(content, getattr(f, "filename", ""))
            ocr = MultilingualOCREngine.get_instance()
            res = ocr.extract_text(ingested.images[0], lang="eng+nep")
            text_to_check = res.full_text

    if not text_to_check:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Provide 'text' in JSON or an image 'file'.")

    lang_info = detect_script_and_language(text_to_check, expected_country=expected_country)
    return LanguageDetectResponse(
        detected_script=lang_info.detected_script, language_code=lang_info.language_code,
        language_name=lang_info.language_name, confidence=lang_info.confidence,
        is_english=lang_info.is_english, tesseract_lang=lang_info.tesseract_lang,
        script_distribution=lang_info.script_distribution,
    )


@router.post("/convert-calendar", response_model=CalendarConvertResponse)
async def convert_calendar_endpoint(req: CalendarConvertRequest) -> CalendarConvertResponse:
    res = convert_bikram_sambat(req.date_or_year)
    return CalendarConvertResponse(
        raw_input=res.raw_input, bs_year=res.bs_year, bs_month=res.bs_month,
        bs_day=res.bs_day, bs_month_name=res.bs_month_name, gregorian_date=res.gregorian_date,
        gregorian_primary_year=res.gregorian_primary_year, gregorian_year_span=res.gregorian_year_span,
        is_valid=res.is_valid, detail=res.detail,
    )


@router.post("/extract-text")
async def extract_multilingual_text(file: UploadFile = File(...), lang: str = Form("eng+nep")) -> Dict[str, Any]:
    content = await file.read()
    ingested = ingest_file(content, file.filename or "")
    ocr = MultilingualOCREngine.get_instance()
    ocr_res = ocr.extract_text(ingested.images[0], lang=lang)
    return {
        "engine": ocr_res.engine, "average_confidence": ocr_res.average_confidence,
        "full_text": ocr_res.full_text, "lines": ocr_res.lines,
        "blocks": [{"text": b.text, "confidence": b.confidence, "bbox": b.bbox} for b in ocr_res.blocks],
    }


@router.post("/screen", response_model=MultilingualScreenResponse)
async def multilingual_screen_endpoint(
    file: UploadFile = File(...), expected_country: Optional[str] = Form("NPL"), expected_ad_dob: Optional[str] = Form(None),
) -> MultilingualScreenResponse:
    content = await file.read()
    ingested = ingest_file(content, file.filename or "")
    ocr = MultilingualOCREngine.get_instance()
    ocr_res = ocr.extract_text(ingested.images[0], lang="eng+nep" if expected_country == "NPL" else "eng")

    lang_info = detect_script_and_language(ocr_res.full_text, expected_country=expected_country)
    from field_extractor import extract_document_fields
    parsed = extract_document_fields(ocr_res, expected_country=expected_country)

    consistency = evaluate_multilingual_consistency(
        document_number=parsed.document_number, claimed_name=parsed.claimed_name,
        claimed_bs_date=parsed.claimed_dob, expected_ad_date=expected_ad_dob,
        issuing_country=expected_country or parsed.issuing_country or "NPL",
    )

    score = 90.0 if consistency.is_consistent else (0.0 if consistency.hard_fail else 60.0)
    status_label = "VERIFIED" if consistency.is_consistent else ("NOT VERIFIED" if consistency.hard_fail else "NEEDS REVIEW")
    cal = consistency.calendar_conversion
    cal_dict = {
        "bs_year": cal.bs_year, "bs_month": cal.bs_month, "bs_month_name": cal.bs_month_name,
        "gregorian_date": cal.gregorian_date, "gregorian_year_span": cal.gregorian_year_span, "detail": cal.detail,
    } if cal and cal.is_valid else None

    return MultilingualScreenResponse(
        session_id=str(uuid.uuid4()), document_id=str(uuid.uuid4()), status=status_label, score=score,
        hard_fail=consistency.hard_fail, detected_language=lang_info.language_name,
        detected_script=lang_info.detected_script, issuing_country=expected_country or parsed.issuing_country or "NPL",
        document_number=parsed.document_number, claimed_name=parsed.claimed_name,
        claimed_dob_bs=parsed.claimed_dob, claimed_dob_gregorian=cal_dict.get("gregorian_date") if cal_dict else parsed.claimed_dob,
        raw_text=ocr_res.full_text, calendar_conversion=cal_dict,
        validation_checks=[{"check_name": c.check_name, "status": c.status, "is_hard_fail": c.is_hard_fail, "detail": c.detail} for c in consistency.checks],
        reason_codes=[{"code": f"MULTILINGUAL_{c.check_name}", "message": c.detail, "severity": "HIGH" if c.is_hard_fail else "MEDIUM"} for c in consistency.checks if c.status != "PASS"],
    )


app = FastAPI(title="Operation PRAMAAN — Multilingual & Regional Consistency Microservice", version="1.0.0")
app.include_router(router)
