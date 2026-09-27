"""Pydantic schemas for the multilingual screening API."""

from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


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
    date_or_year: str = Field(..., description="Nepali date or year e.g. '2082-04-25', '15 Baishakh 2080', '2080 BS'")


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
