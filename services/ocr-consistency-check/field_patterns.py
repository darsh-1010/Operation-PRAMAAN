"""Field patterns, constants, and data structures for document parsing."""

from __future__ import annotations
from dataclasses import dataclass, field
import re
from typing import Dict, List, Optional
from mrz_verifier import MRZCheckResult


@dataclass
class ExtractedField:
    """Individual extracted field for database persistence."""
    field_key: str
    field_value: Optional[str]
    source: str  # 'MRZ' or 'BARCODE'
    confidence: float
    bbox: Optional[Dict[str, float]] = None


@dataclass
class ParsedDocumentData:
    """Consolidated document fields ready for consistency verification."""
    doc_type: str  # 'PASSPORT', 'NATIONAL_ID', 'DRIVING_LICENSE', etc.
    document_number: Optional[str] = None
    claimed_name: Optional[str] = None
    claimed_dob: Optional[str] = None
    claimed_expiry: Optional[str] = None
    claimed_gender: Optional[str] = None
    issuing_country: Optional[str] = "IND"
    fields: List[ExtractedField] = field(default_factory=list)
    mrz_result: Optional[MRZCheckResult] = None
    viz_mrz_consistent: bool = True
    inconsistencies: List[str] = field(default_factory=list)
    detected_language: str = "English"
    detected_script: str = "Latin"
    claimed_dob_bs: Optional[str] = None
    calendar_system: str = "GREGORIAN"


def detect_document_type(full_text: str) -> str:
    """Infer document type from text tokens across English and regional scripts."""
    upper = full_text.upper()
    if (
        "PASSPORT" in upper
        or "राहदानी" in full_text
        or ("REPUBLIC OF INDIA" in upper and "PASSPORT" in upper)
        or bool(re.search(r"\b[A-PR-WY][0-9O]{7,8}\b", upper))
        or bool(re.search(r"P[<C][A-Z]{3}", upper))
    ):
        return "PASSPORT"
    if "DRIVING" in upper or "LICENCE" in upper or "LICENSE" in upper or "चालक अनुमतिपत्र" in full_text or "सवारी चालक" in full_text:
        return "DRIVING_LICENSE"
    if (
        "AADHAAR" in upper
        or "UNIQUE IDENTIFICATION" in upper
        or "PAN CARD" in upper
        or "नागरिकता" in full_text
        or "CITIZENSHIP" in upper
    ):
        return "NATIONAL_ID"
    if "VISA" in upper or "भिसा" in full_text:
        return "VISA"
    return "NATIONAL_ID"
