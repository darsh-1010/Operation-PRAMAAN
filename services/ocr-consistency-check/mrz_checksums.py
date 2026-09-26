"""ICAO Doc 9303 MRZ Checksum and Check Digit Verification Helpers."""

from __future__ import annotations
from dataclasses import dataclass, field
import datetime
import re
from typing import Any, Dict, List, Optional, Tuple

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
    century = (1900 if yy > current_yy else 2000) if is_dob else (2000 if yy <= current_yy + 25 else 1900)
    try:
        return datetime.date(century + yy, mm, dd).isoformat()
    except ValueError:
        return None


def clean_mrz_line(line: str) -> str:
    """Clean and normalize a detected MRZ line string."""
    line = line.strip().upper()
    line = re.sub(r"[\(\{\[\«\§]", "<", line)
    line = re.sub(r"[^A-Z0-9<]", "", line)
    if re.match(r"^P[CEK][A-Z]{3}", line):
        line = "P<" + line[2:]
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
    observed = int(expected_char) if expected_char.isdigit() else -1
    passed = (calc == observed)
    return passed, {
        "field": label,
        "calculated": calc,
        "observed": observed,
        "passed": passed,
    }
