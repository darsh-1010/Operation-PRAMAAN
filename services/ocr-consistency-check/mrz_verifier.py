"""ICAO Doc 9303 Machine Readable Zone (MRZ) Verifier and Parser.

Implements international standards for travel document MRZ validation,
supporting TD3 (2x44 Passports) and TD1 (3x30 ID Cards).
Calculates modulo-10 weighted check digits (weights: 7, 3, 1) and validates
integrity to detect document tampering or fraudulent alterations.
"""

from __future__ import annotations
import datetime
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("mrz_verifier")

ICAO_WEIGHTS = [7, 3, 1]


def icao_char_value(c: str) -> int:
    """Convert an MRZ character to its ICAO 9303 numeric value."""
    if c == "<":
        return 0
    if "0" <= c <= "9":
        return int(c)
    if "A" <= c <= "Z":
        return ord(c) - ord("A") + 10
    return 0


def calculate_mrz_checksum(data: str) -> int:
    """Calculate ICAO Doc 9303 check digit using repeating weights 7, 3, 1."""
    total = 0
    for idx, char in enumerate(data):
        weight = ICAO_WEIGHTS[idx % len(ICAO_WEIGHTS)]
        total += icao_char_value(char) * weight
    return total % 10


def parse_mrz_date(yymmdd: str, is_dob: bool = False) -> Optional[str]:
    """Parse a 6-digit MRZ date into ISO standard YYYY-MM-DD."""
    if len(yymmdd) != 6 or not yymmdd.isdigit():
        return None
    yy, mm, dd = int(yymmdd[0:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        return None

    current_year = datetime.date.today().year
    current_yy = current_year % 100

    if is_dob:
        # DOB cutoff: if YY is greater than current year YY, person was born in 1900s
        century = 1900 if yy > current_yy else 2000
    else:
        # Expiry cutoff: travel docs are typically valid up to 10-20 years into the future
        century = 2000 if yy <= current_yy + 25 else 1900

    full_year = century + yy
    try:
        dt = datetime.date(full_year, mm, dd)
        return dt.isoformat()
    except ValueError:
        return None


def clean_mrz_line(line: str) -> str:
    """Clean and normalize a detected MRZ line string."""
    line = line.strip().upper()
    line = re.sub(r"[^A-Z0-9<]", "", line)
    return line


@dataclass
class MRZCheckResult:
    """Detailed verification outcome of an MRZ block."""
    valid_format: bool
    format_type: Optional[str] = None  # TD1 or TD3
    doc_type: Optional[str] = None     # PASSPORT or NATIONAL_ID
    document_number: Optional[str] = None
    dob: Optional[str] = None
    expiry: Optional[str] = None
    gender: Optional[str] = None
    issuing_country: Optional[str] = None
    nationality: Optional[str] = None
    full_name: Optional[str] = None
    raw_lines: List[str] = field(default_factory=list)
    checksums: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    has_checksum_failure: bool = False
    failure_details: List[str] = field(default_factory=list)


def verify_check_digit(data: str, expected_char: str, label: str) -> Tuple[bool, Dict[str, Any]]:
    """Verify a check digit against expected character and return status dict."""
    calc = calculate_mrz_checksum(data)
    clean_char = expected_char.upper()
    if clean_char in ("O", "Q"):
        clean_char = "0"
    elif clean_char in ("I", "L"):
        clean_char = "1"
    observed = int(clean_char) if clean_char.isdigit() else -1
    passed = (calc == observed)
    return passed, {
        "field": label,
        "calculated": calc,
        "observed": observed,
        "passed": passed,
    }


def parse_td3_mrz(lines: List[str]) -> MRZCheckResult:
    """Parse and verify a 2-line x 44-character TD3 Passport MRZ."""
    l1, l2 = lines[0], lines[1]
    if len(l1) != 44 or len(l2) != 44:
        return MRZCheckResult(valid_format=False, failure_details=["TD3 line length must be 44 chars."])

    issuing_country = l1[2:5].replace("<", "")
    names_raw = l1[5:44]
    name_parts = names_raw.split("<<")
    surname = name_parts[0].replace("<", " ").strip()
    given_names = name_parts[1].replace("<", " ").strip() if len(name_parts) > 1 else ""
    full_name = f"{surname} {given_names}".strip()

    doc_num_raw = l2[0:9]
    doc_num_clean = doc_num_raw.replace("<", "")
    doc_num_cd = l2[9]
    nationality = l2[10:13].replace("<", "")
    dob_raw = l2[13:19]
    dob_cd = l2[19]
    sex = l2[20]
    sex_clean = "M" if sex == "M" else ("F" if sex == "F" else "X")
    exp_raw = l2[21:27]
    exp_cd = l2[27]
    opt_data = l2[28:42]
    opt_cd = l2[42]
    comp_cd = l2[43]

    checksums: Dict[str, Dict[str, Any]] = {}
    failures: List[str] = []

    p_doc, res_doc = verify_check_digit(doc_num_raw, doc_num_cd, "doc_number")
    checksums["doc_number"] = res_doc
    if not p_doc:
        failures.append(f"Document number checksum mismatch: calc {res_doc['calculated']} vs {doc_num_cd}")

    p_dob, res_dob = verify_check_digit(dob_raw, dob_cd, "dob")
    checksums["dob"] = res_dob
    if not p_dob:
        failures.append(f"DOB checksum mismatch: calc {res_dob['calculated']} vs {dob_cd}")

    p_exp, res_exp = verify_check_digit(exp_raw, exp_cd, "expiry")
    checksums["expiry"] = res_exp
    if not p_exp:
        failures.append(f"Expiry checksum mismatch: calc {res_exp['calculated']} vs {exp_cd}")

    # Composite check digit covers: l2[0:10] + l2[13:20] + l2[21:43]
    comp_data = l2[0:10] + l2[13:20] + l2[21:43]
    p_comp, res_comp = verify_check_digit(comp_data, comp_cd, "composite")
    checksums["composite"] = res_comp
    if not p_comp:
        failures.append(f"Composite MRZ checksum mismatch: calc {res_comp['calculated']} vs {comp_cd}")

    if failures:
        logger.warning("TD3 MRZ checksum failure(s): %s", "; ".join(failures))
    else:
        logger.info("TD3 MRZ verified: all checksums passed.")

    return MRZCheckResult(
        valid_format=True,
        format_type="TD3",
        doc_type="PASSPORT",
        document_number=doc_num_clean,
        dob=parse_mrz_date(dob_raw, is_dob=True),
        expiry=parse_mrz_date(exp_raw, is_dob=False),
        gender=sex_clean,
        issuing_country=issuing_country,
        nationality=nationality,
        full_name=full_name,
        raw_lines=[l1, l2],
        checksums=checksums,
        has_checksum_failure=(len(failures) > 0),
        failure_details=failures,
    )


def parse_td1_mrz(lines: List[str]) -> MRZCheckResult:
    """Parse and verify a 3-line x 30-character TD1 ID Card MRZ."""
    l1, l2, l3 = lines[0], lines[1], lines[2]
    if len(l1) != 30 or len(l2) != 30 or len(l3) != 30:
        return MRZCheckResult(valid_format=False, failure_details=["TD1 line length must be 30 chars."])

    issuing_country = l1[2:5].replace("<", "")
    doc_num_raw = l1[5:14]
    doc_num_clean = doc_num_raw.replace("<", "")
    doc_num_cd = l1[14]

    dob_raw = l2[0:6]
    dob_cd = l2[6]
    sex = l2[7]
    sex_clean = "M" if sex == "M" else ("F" if sex == "F" else "X")
    exp_raw = l2[8:14]
    exp_cd = l2[14]
    nationality = l2[15:18].replace("<", "")
    comp_cd = l2[29]

    name_parts = l3.split("<<")
    surname = name_parts[0].replace("<", " ").strip()
    given_names = name_parts[1].replace("<", " ").strip() if len(name_parts) > 1 else ""
    full_name = f"{surname} {given_names}".strip()

    checksums: Dict[str, Dict[str, Any]] = {}
    failures: List[str] = []

    p_doc, res_doc = verify_check_digit(doc_num_raw, doc_num_cd, "doc_number")
    checksums["doc_number"] = res_doc
    if not p_doc:
        failures.append(f"Document number checksum mismatch in TD1.")

    p_dob, res_dob = verify_check_digit(dob_raw, dob_cd, "dob")
    checksums["dob"] = res_dob
    if not p_dob:
        failures.append(f"DOB checksum mismatch in TD1.")

    p_exp, res_exp = verify_check_digit(exp_raw, exp_cd, "expiry")
    checksums["expiry"] = res_exp
    if not p_exp:
        failures.append(f"Expiry checksum mismatch in TD1.")

    comp_data = l1[5:30] + l2[0:7] + l2[8:15] + l2[18:29]
    p_comp, res_comp = verify_check_digit(comp_data, comp_cd, "composite")
    checksums["composite"] = res_comp
    if not p_comp:
        failures.append(f"Composite MRZ checksum mismatch in TD1.")

    if failures:
        logger.warning("TD1 MRZ checksum failure(s): %s", "; ".join(failures))
    else:
        logger.info("TD1 MRZ verified: all checksums passed.")

    return MRZCheckResult(
        valid_format=True,
        format_type="TD1",
        doc_type="NATIONAL_ID",
        document_number=doc_num_clean,
        dob=parse_mrz_date(dob_raw, is_dob=True),
        expiry=parse_mrz_date(exp_raw, is_dob=False),
        gender=sex_clean,
        issuing_country=issuing_country,
        nationality=nationality,
        full_name=full_name,
        raw_lines=[l1, l2, l3],
        checksums=checksums,
        has_checksum_failure=(len(failures) > 0),
        failure_details=failures,
    )


def extract_and_verify_mrz(text_lines: List[str]) -> Optional[MRZCheckResult]:
    """Identify, clean, and verify MRZ lines from a list of OCR extracted text lines."""
    # Find lines containing typical MRZ filler chars or matching standard lengths
    cleaned = [clean_mrz_line(line) for line in text_lines]
    candidate_lines = [l for l in cleaned if len(l) in (44, 30) or "<" in l]

    # Look for 2 consecutive 44-char lines (TD3)
    for i in range(len(candidate_lines) - 1):
        l1, l2 = candidate_lines[i], candidate_lines[i + 1]
        if l1.startswith("P") or l1.startswith("V"):
            if 42 <= len(l1) <= 46:
                l1 = l1[:44].ljust(44, "<")
            if 42 <= len(l2) <= 46:
                l2 = l2[:44].ljust(44, "<")
            if len(l1) == 44 and len(l2) == 44:
                return parse_td3_mrz([l1, l2])

    # Look for 3 consecutive 30-char lines (TD1)
    for i in range(len(candidate_lines) - 2):
        l1, l2, l3 = candidate_lines[i], candidate_lines[i + 1], candidate_lines[i + 2]
        if l1.startswith("I") or l1.startswith("A"):
            if 28 <= len(l1) <= 32:
                l1 = l1[:30].ljust(30, "<")
            if 28 <= len(l2) <= 32:
                l2 = l2[:30].ljust(30, "<")
            if 28 <= len(l3) <= 32:
                l3 = l3[:30].ljust(30, "<")
            if len(l1) == 30 and len(l2) == 30 and len(l3) == 30:
                return parse_td1_mrz([l1, l2, l3])

    logger.info("No MRZ block detected in OCR text (%d candidate lines).", len(candidate_lines))
    return None

