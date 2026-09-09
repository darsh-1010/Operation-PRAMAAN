"""Data Normalization Utilities.

Standardizes extracted fields into canonical formats:
- Dates to ISO-8601 (YYYY-MM-DD)
- Personal names to normalized uppercase, stripping honorifics
- Document ID numbers to clean alphanumeric strings
- Gender to single character ('M', 'F', 'X')
"""

from __future__ import annotations
import datetime
import re
from typing import Optional

MONTH_MAP = {
    "JAN": 1, "JANUARY": 1, "FEB": 2, "FEBRUARY": 2, "MAR": 3, "MARCH": 3,
    "APR": 4, "APRIL": 4, "MAY": 5, "JUN": 6, "JUNE": 6, "JUL": 7, "JULY": 7,
    "AUG": 8, "AUGUST": 8, "SEP": 9, "SEPTEMBER": 9, "OCT": 10, "OCTOBER": 10,
    "NOV": 11, "NOVEMBER": 11, "DEC": 12, "DECEMBER": 12,
}

HONORIFICS = {"MR", "MRS", "MS", "DR", "PROF", "SHRI", "SMT", "KUMAR", "MISS"}


def normalize_date(date_str: Optional[str]) -> Optional[str]:
    """Parse and normalize diverse date formats into standard YYYY-MM-DD string."""
    if not date_str:
        return None

    cleaned = date_str.strip().upper()

    # Pattern: ISO format YYYY-MM-DD or YYYY/MM/DD
    m_iso = re.match(r"^(\d{4})[-/. ](\d{1,2})[-/. ](\d{1,2})$", cleaned)
    if m_iso:
        y, m, d = int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))
        return _validate_date(y, m, d)

    # Pattern: Day-Month-Year e.g. 15/08/1995 or 15-08-1995 or 15.08.1995
    m_dmy = re.match(r"^(\d{1,2})[-/. ](\d{1,2})[-/. ](\d{4})$", cleaned)
    if m_dmy:
        d, m, y = int(m_dmy.group(1)), int(m_dmy.group(2)), int(m_dmy.group(3))
        return _validate_date(y, m, d)

    # Pattern: Text month e.g. "15 AUG 1995" or "15-AUG-1995"
    m_text = re.match(r"^(\d{1,2})[-/ ]([A-Z]{3,9})[-/ ](\d{4})$", cleaned)
    if m_text:
        d = int(m_text.group(1))
        month_str = m_text.group(2)
        y = int(m_text.group(3))
        m = MONTH_MAP.get(month_str)
        if m:
            return _validate_date(y, m, d)

    # Pattern: Month first e.g. "AUG 15, 1995"
    m_month_first = re.match(r"^([A-Z]{3,9})[-/ ](\d{1,2}),?[-/ ](\d{4})$", cleaned)
    if m_month_first:
        month_str = m_month_first.group(1)
        d = int(m_month_first.group(2))
        y = int(m_month_first.group(3))
        m = MONTH_MAP.get(month_str)
        if m:
            return _validate_date(y, m, d)

    return None


def _validate_date(year: int, month: int, day: int) -> Optional[str]:
    """Validate calendar date components and return ISO string."""
    try:
        dt = datetime.date(year, month, day)
        return dt.isoformat()
    except (ValueError, OverflowError):
        return None


def normalize_name(name_str: Optional[str]) -> Optional[str]:
    """Clean and normalize personal names, removing noise and honorifics."""
    if not name_str:
        return None

    cleaned = name_str.upper()
    cleaned = re.sub(r"[^A-Z\s,]", " ", cleaned)

    # Handle "LASTNAME, FIRSTNAME" inverted format
    if "," in cleaned:
        parts = [p.strip() for p in cleaned.split(",") if p.strip()]
        if len(parts) >= 2:
            cleaned = f"{parts[1]} {parts[0]}"
        elif parts:
            cleaned = parts[0]

    words = [w for w in cleaned.split() if w not in HONORIFICS and len(w) > 0]
    result = " ".join(words).strip()
    return result if result else None


def normalize_id_number(id_str: Optional[str]) -> Optional[str]:
    """Normalize document/ID number by stripping whitespace and non-alphanumeric noise."""
    if not id_str:
        return None

    cleaned = id_str.upper().strip()
    cleaned = re.sub(r"[\s\-_./]", "", cleaned)
    return cleaned if cleaned else None


def normalize_gender(gender_str: Optional[str]) -> Optional[str]:
    """Normalize gender code to 'M', 'F', or 'X'."""
    if not gender_str:
        return None

    g = gender_str.strip().upper()
    if g in ("M", "MALE", "MAN"):
        return "M"
    if g in ("F", "FEMALE", "WOMAN"):
        return "F"
    return "X"

