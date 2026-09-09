"""Field Extraction and Document Parser.

Extracts structured fields (Name, DOB, ID number, Expiry, Gender, Country)
from OCR text blocks using regex patterns, label anchoring, and MRZ cross-checking.
"""

from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from mrz_verifier import MRZCheckResult, extract_and_verify_mrz
from normalizer import normalize_date, normalize_gender, normalize_id_number, normalize_name
from ocr_engine import OCRResult, TextBlock


@dataclass
class ExtractedField:
    """Individual extracted field for database persistence."""
    field_key: str
    field_value: Optional[str]
    source: str  # 'VIZ', 'MRZ', or 'BARCODE'
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


def detect_document_type(full_text: str) -> str:
    """Infer document type from text tokens."""
    upper = full_text.upper()
    if "PASSPORT" in upper or "REPUBLIC OF INDIA" in upper and "PASSPORT" in upper:
        return "PASSPORT"
    if "DRIVING" in upper or "LICENCE" in upper or "LICENSE" in upper:
        return "DRIVING_LICENSE"
    if "AADHAAR" in upper or "UNIQUE IDENTIFICATION" in upper or "PAN CARD" in upper:
        return "NATIONAL_ID"
    if "VISA" in upper:
        return "VISA"
    return "NATIONAL_ID"


def extract_labeled_field(lines: List[str], label_pattern: str, max_lookahead: int = 2) -> Optional[str]:
    """Find a value adjacent to or on the line following a field label."""
    for idx, line in enumerate(lines):
        match = re.search(label_pattern, line, re.IGNORECASE)
        if match:
            # Check if value is on the same line after a colon or space
            remainder = line[match.end():].strip().lstrip(":").strip()
            if len(remainder) >= 2 and not re.search(r"^(OF|AND|THE|NO)\b", remainder, re.I):
                return remainder
            # Look at next line(s)
            for offset in range(1, max_lookahead + 1):
                if idx + offset < len(lines):
                    candidate = lines[idx + offset].strip()
                    if candidate and not re.search(r"(NAME|DOB|DATE|SEX|PASSPORT|NUMBER|EXPIRY)", candidate, re.I):
                        return candidate
    return None


def extract_regex_value(full_text: str, pattern: str) -> Optional[str]:
    """Search for first match of a regex pattern across full text."""
    match = re.search(pattern, full_text, re.MULTILINE | re.IGNORECASE)
    return match.group(1).strip() if match else None


def extract_document_fields(ocr_result: OCRResult) -> ParsedDocumentData:
    """Orchestrate extraction across MRZ and Visual Inspection Zone (VIZ)."""
    lines = ocr_result.lines
    full_text = ocr_result.full_text
    fields_list: List[ExtractedField] = []

    # Step 1: Detect and verify MRZ if present
    mrz = extract_and_verify_mrz(lines)
    doc_type = mrz.doc_type if (mrz and mrz.valid_format) else detect_document_type(full_text)

    # Step 2: Extract VIZ fields
    viz_name_raw = extract_labeled_field(lines, r"\b(GIVEN\s*NAME[S]?|NAME|SURNAME|FULL\s*NAME)\b")
    viz_dob_raw = extract_labeled_field(lines, r"\b(DATE\s*OF\s*BIRTH|DOB|D\.O\.B|BIRTH\s*DATE)\b")
    viz_exp_raw = extract_labeled_field(lines, r"\b(DATE\s*OF\s*EXPIRY|EXPIRY\s*DATE|VALID\s*UNTIL|EXP)\b")
    viz_sex_raw = extract_labeled_field(lines, r"\b(SEX|GENDER)\b")

    # Document number regexes based on type
    doc_num_raw: Optional[str] = None
    if doc_type == "PASSPORT":
        doc_num_raw = extract_regex_value(full_text, r"\b([A-PR-WY][0-9]{7,8})\b")
    elif doc_type == "DRIVING_LICENSE":
        doc_num_raw = extract_regex_value(full_text, r"\b([A-Z]{2}[-\s]?[0-9]{2}[-\s]?[0-9]{7,11})\b")
    elif doc_type == "NATIONAL_ID":
        doc_num_raw = extract_regex_value(full_text, r"\b([0-9]{4}\s?[0-9]{4}\s?[0-9]{4})\b")

    if not doc_num_raw:
        doc_num_raw = extract_labeled_field(lines, r"\b(PASSPORT\s*NO|DOC\s*NO|ID\s*NO|NUMBER)\b")

    # Step 3: Normalize VIZ fields
    norm_name = normalize_name(viz_name_raw)
    norm_dob = normalize_date(viz_dob_raw)
    norm_exp = normalize_date(viz_exp_raw)
    norm_sex = normalize_gender(viz_sex_raw)
    norm_doc_num = normalize_id_number(doc_num_raw)

    # Step 4: Reconcile with MRZ (MRZ takes precedence for travel docs, but cross-checks VIZ)
    inconsistencies: List[str] = []
    final_name = norm_name
    final_dob = norm_dob
    final_exp = norm_exp
    final_sex = norm_sex
    final_doc_num = norm_doc_num
    country = "IND"

    if mrz and mrz.valid_format:
        country = mrz.issuing_country or "IND"
        if mrz.document_number:
            if norm_doc_num and norm_doc_num != mrz.document_number:
                inconsistencies.append(f"Doc number mismatch: VIZ '{norm_doc_num}' vs MRZ '{mrz.document_number}'")
            final_doc_num = mrz.document_number
            fields_list.append(ExtractedField("document_number", mrz.document_number, "MRZ", 0.99))

        if mrz.full_name:
            if norm_name and norm_name != mrz.full_name:
                inconsistencies.append(f"Name mismatch: VIZ '{norm_name}' vs MRZ '{mrz.full_name}'")
            final_name = mrz.full_name if not norm_name else norm_name
            fields_list.append(ExtractedField("name", mrz.full_name, "MRZ", 0.98))

        if mrz.dob:
            if norm_dob and norm_dob != mrz.dob:
                inconsistencies.append(f"DOB mismatch: VIZ '{norm_dob}' vs MRZ '{mrz.dob}'")
            final_dob = mrz.dob
            fields_list.append(ExtractedField("dob", mrz.dob, "MRZ", 0.99))

        if mrz.expiry:
            final_exp = mrz.expiry
            fields_list.append(ExtractedField("expiry", mrz.expiry, "MRZ", 0.99))

        if mrz.gender:
            final_sex = mrz.gender
            fields_list.append(ExtractedField("gender", mrz.gender, "MRZ", 0.99))

    # Add VIZ fields to fields list
    if norm_name:
        fields_list.append(ExtractedField("name", norm_name, "VIZ", 0.90))
    if norm_dob:
        fields_list.append(ExtractedField("dob", norm_dob, "VIZ", 0.90))
    if norm_exp:
        fields_list.append(ExtractedField("expiry", norm_exp, "VIZ", 0.90))
    if norm_doc_num:
        fields_list.append(ExtractedField("document_number", norm_doc_num, "VIZ", 0.92))
    if norm_sex:
        fields_list.append(ExtractedField("gender", norm_sex, "VIZ", 0.90))

    return ParsedDocumentData(
        doc_type=doc_type,
        document_number=final_doc_num,
        claimed_name=final_name,
        claimed_dob=final_dob,
        claimed_expiry=final_exp,
        claimed_gender=final_sex,
        issuing_country=country,
        fields=fields_list,
        mrz_result=mrz,
        viz_mrz_consistent=(len(inconsistencies) == 0),
        inconsistencies=inconsistencies,
    )

