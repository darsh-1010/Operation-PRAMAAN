"""ICAO Doc 9303 Machine Readable Zone (MRZ) Verifier and Parser."""

from __future__ import annotations
import re
from typing import Dict, List, Optional, Tuple

from mrz_checksums import (
    ICAO_WEIGHTS,
    MRZCheckResult,
    calculate_mrz_checksum,
    clean_mrz_line,
    icao_char_value,
    parse_mrz_date,
    verify_check_digit,
)


def parse_td3_mrz(lines: List[str]) -> MRZCheckResult:
    """Parse and verify a 2-line x 44-character TD3 Passport MRZ."""
    l1, l2 = lines[0], lines[1]
    if l2.startswith(("P<", "P", "V<", "V")) and not l1.startswith(("P<", "P", "V<", "V")):
        l1, l2 = l2, l1

    if len(l1) != 44 or len(l2) != 44:
        return MRZCheckResult(valid_format=False, failure_details=["TD3 line length must be 44 chars."])

    is_visa = l1.startswith("V")
    doc_type = "VISA" if is_visa else "PASSPORT"
    format_type = "MRV-A" if is_visa else "TD3"
    issuing_country = l1[2:5].replace("<", "")
    name_field = l1[5:]
    name_parts = name_field.split("<<")
    surname = name_parts[0].replace("<", " ").strip()
    given_names = name_parts[1].replace("<", " ").strip() if len(name_parts) > 1 else ""
    full_name = f"{surname} {given_names}".strip() if surname and given_names else (surname or given_names)

    doc_num_raw = l2[0:9]
    doc_num = doc_num_raw.replace("<", "")
    doc_num_check = l2[9]
    nationality = l2[10:13].replace("<", "")
    dob_raw = l2[13:19]
    dob_check = l2[19]
    gender = l2[20] if l2[20] in ("M", "F") else None
    expiry_raw = l2[21:27]
    expiry_check = l2[27]
    composite_data = l2[0:10] + l2[13:20] + l2[21:43]
    composite_check = l2[43]

    checksums = {}
    failures = []

    p_doc, c_doc = verify_check_digit(doc_num_raw, doc_num_check, "document_number")
    checksums["document_number"] = c_doc
    if not p_doc:
        failures.append("Document number checksum mismatch")

    p_dob, c_dob = verify_check_digit(dob_raw, dob_check, "dob")
    checksums["dob"] = c_dob
    if not p_dob:
        failures.append("DOB checksum mismatch")

    p_exp, c_exp = verify_check_digit(expiry_raw, expiry_check, "expiry")
    checksums["expiry"] = c_exp
    if not p_exp:
        failures.append("Expiry checksum mismatch")

    if not is_visa:
        p_comp, c_comp = verify_check_digit(composite_data, composite_check, "composite")
        checksums["composite"] = c_comp
        if not p_comp:
            failures.append("Composite checksum mismatch")

    return MRZCheckResult(
        valid_format=True, format_type=format_type, doc_type=doc_type,
        document_number=doc_num, dob=parse_mrz_date(dob_raw, is_dob=True),
        expiry=parse_mrz_date(expiry_raw, is_dob=False), gender=gender,
        issuing_country=issuing_country, nationality=nationality, full_name=full_name,
        raw_lines=[l1, l2], checksums=checksums,
        has_checksum_failure=(len(failures) > 0), failure_details=failures,
    )


def parse_td1_mrz(lines: List[str]) -> MRZCheckResult:
    """Parse and verify a 3-line x 30-character TD1 ID Card MRZ."""
    if len(lines) != 3 or any(len(l) != 30 for l in lines):
        return MRZCheckResult(valid_format=False, failure_details=["TD1 requires exactly 3 lines of 30 characters."])

    l1, l2, l3 = lines[0], lines[1], lines[2]
    issuing_country = l1[2:5].replace("<", "")
    doc_num_raw = l1[5:14]
    doc_num = doc_num_raw.replace("<", "")
    doc_num_check = l1[14]

    dob_raw, dob_check = l2[0:6], l2[6]
    gender = l2[7] if l2[7] in ("M", "F") else None
    expiry_raw, expiry_check = l2[8:14], l2[14]
    nationality = l2[15:18].replace("<", "")
    composite_data = l1[5:30] + l2[0:7] + l2[8:15] + l2[18:29]
    composite_check = l2[29]

    name_field = l3
    name_parts = name_field.split("<<")
    surname = name_parts[0].replace("<", " ").strip()
    given_names = name_parts[1].replace("<", " ").strip() if len(name_parts) > 1 else ""
    full_name = f"{surname} {given_names}".strip() if surname and given_names else (surname or given_names)

    checksums = {}
    failures = []
    for label, raw_val, chk in [("document_number", doc_num_raw, doc_num_check), ("dob", dob_raw, dob_check), ("expiry", expiry_raw, expiry_check), ("composite", composite_data, composite_check)]:
        p, c = verify_check_digit(raw_val, chk, label)
        checksums[label] = c
        if not p:
            failures.append(f"{label} checksum mismatch")

    return MRZCheckResult(
        valid_format=True, format_type="TD1", doc_type="NATIONAL_ID",
        document_number=doc_num, dob=parse_mrz_date(dob_raw, is_dob=True),
        expiry=parse_mrz_date(expiry_raw, is_dob=False), gender=gender,
        issuing_country=issuing_country, nationality=nationality, full_name=full_name,
        raw_lines=[l1, l2, l3], checksums=checksums,
        has_checksum_failure=(len(failures) > 0), failure_details=failures,
    )


def extract_and_verify_mrz(ocr_lines: List[str]) -> Optional[MRZCheckResult]:
    """Find, clean, and verify MRZ blocks from raw OCR text lines."""
    candidate_lines = []
    for raw in ocr_lines:
        cleaned = clean_mrz_line(raw)
        if len(cleaned) >= 20 and ("<" in cleaned or cleaned.startswith(("P", "V", "I", "A"))):
            candidate_lines.append(cleaned)

    # Pass 1: TD3 44-character lines with candidate ranking
    td3_candidates = [c for c in candidate_lines if len(c) == 44]
    best_td3: Optional[MRZCheckResult] = None
    min_failures = 999

    for i in range(len(td3_candidates) - 1):
        c1, c2 = td3_candidates[i], td3_candidates[i + 1]
        for pair in [(c1, c2), (c2, c1)]:
            top, bottom = pair
            if not (top.startswith(("P<", "P", "V<", "V")) or "<" in top):
                continue
            res = parse_td3_mrz([top, bottom])
            if res.valid_format:
                num_fails = len(res.failure_details)
                if num_fails < min_failures:
                    min_failures = num_fails
                    best_td3 = res
                if num_fails == 0:
                    return res

    # Pass 2: Fuzzy reconstruction of 44-character lines
    if not best_td3:
        fuzzy_44 = []
        for c in candidate_lines:
            if 40 <= len(c) < 44:
                fuzzy_44.append(c + "<" * (44 - len(c)))
            elif len(c) == 44:
                fuzzy_44.append(c)
        for i in range(len(fuzzy_44) - 1):
            res = parse_td3_mrz([fuzzy_44[i], fuzzy_44[i + 1]])
            if res.valid_format and not res.has_checksum_failure:
                return res

    # Pass 3: TD1 30-character lines (3 lines)
    for i in range(len(candidate_lines) - 2):
        l1, l2, l3 = candidate_lines[i], candidate_lines[i + 1], candidate_lines[i + 2]
        if len(l1) == 30 and len(l2) == 30 and len(l3) == 30 and l1.startswith(("I", "A")):
            return parse_td1_mrz([l1, l2, l3])

    return best_td3
