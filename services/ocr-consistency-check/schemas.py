"""Pydantic schemas for Module 1 OCR Consistency Check API."""

from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


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
