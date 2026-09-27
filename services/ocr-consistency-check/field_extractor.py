"""MRZ Field Extraction and Document Parser.

Extracts identity credentials exclusively from Machine Readable Zones (MRZ: TD1, TD3, MRV).
Visual Inspection Zone (VIZ) label and field extraction has been removed from this module.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional

from field_patterns import ExtractedField, ParsedDocumentData, detect_document_type
from mrz_verifier import MRZCheckResult, extract_and_verify_mrz
from ocr_engine import OCRResult
from script_detector import detect_script_and_language


def extract_document_fields(
    ocr_result: OCRResult, expected_country: Optional[str] = None, expected_language: Optional[str] = None
) -> ParsedDocumentData:
    """Orchestrate document parsing using MRZ extraction (no VIZ component)."""
    lines, full_text = ocr_result.lines, ocr_result.full_text
    fields_list: List[ExtractedField] = []
    lang_info = detect_script_and_language(full_text, expected_country, expected_language)

    mrz = extract_and_verify_mrz(lines)

    if mrz and mrz.valid_format:
        doc_type = mrz.doc_type or "PASSPORT"
        final_id = mrz.document_number
        final_name = mrz.full_name
        final_dob = mrz.dob
        final_exp = mrz.expiry
        final_gen = mrz.gender
        issuing_country = mrz.issuing_country or expected_country or "IND"

        conf = 0.99 if not mrz.has_checksum_failure else 0.70
        for k, v in [
            ("NAME", mrz.full_name),
            ("DOB", mrz.dob),
            ("EXPIRY", mrz.expiry),
            ("GENDER", mrz.gender),
            ("DOCUMENT_NUMBER", mrz.document_number),
        ]:
            if v:
                fields_list.append(ExtractedField(k, v, "MRZ", conf))
    else:
        doc_type = detect_document_type(full_text)
        final_id = None
        final_name = None
        final_dob = None
        final_exp = None
        final_gen = None
        issuing_country = expected_country or "IND"

    claimed_dob_bs = None
    calendar_system = "GREGORIAN"
    if (issuing_country == "NPL" or expected_country == "NPL") and final_dob:
        from nepali_calendar import convert_gregorian_to_bs
        claimed_dob_bs = convert_gregorian_to_bs(final_dob)
        calendar_system = "BIKRAM_SAMBAT"

    return ParsedDocumentData(
        doc_type=doc_type,
        document_number=final_id,
        claimed_name=final_name,
        claimed_dob=final_dob,
        claimed_expiry=final_exp,
        claimed_gender=final_gen,
        issuing_country=issuing_country,
        fields=fields_list,
        mrz_result=mrz,
        viz_mrz_consistent=True,
        inconsistencies=[],
        detected_language=lang_info.language_name,
        detected_script=lang_info.detected_script,
        claimed_dob_bs=claimed_dob_bs,
        calendar_system=calendar_system,
    )
