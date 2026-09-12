"""Nepali Bikram Sambat (B.S.) Calendar Conversion Engine.

Converts Nepali calendar dates, months, and years into standard Gregorian (A.D.):
- Handles Devanagari numerals (०-९) and Latin digits
- Supports all 12 Nepali month names in Devanagari and Latin transliteration
- Converts full B.S. dates to canonical ISO-8601 Gregorian (YYYY-MM-DD)
- Converts B.S. years (which begin mid-April) to primary Gregorian year and year span
"""

from __future__ import annotations
import datetime
import re
from dataclasses import dataclass
from typing import Dict, Optional, Tuple

DEVANAGARI_DIGITS = {
    "०": "0", "१": "1", "२": "2", "३": "3", "४": "4",
    "५": "5", "६": "6", "७": "7", "८": "8", "९": "9",
}

NEPALI_MONTH_NAMES = {
    1: "Baishakh", 2: "Jestha", 3: "Ashadh", 4: "Shrawan",
    5: "Bhadra", 6: "Ashwin", 7: "Kartik", 8: "Mangsir",
    9: "Poush", 10: "Magh", 11: "Falgun", 12: "Chaitra",
}

# Lookup for both Devanagari and Latin variations of Nepali month names
NEPALI_MONTH_MAP: Dict[str, int] = {
    # 1. Baishakh (~ mid Apr - mid May)
    "बैशाख": 1, "वैशाख": 1, "BAISHAKH": 1, "BAISAKH": 1, "VAISHAKH": 1, "BAISAK": 1,
    # 2. Jestha (~ mid May - mid Jun)
    "जेठ": 2, "ज्येष्ठ": 2, "जेष्ठ": 2, "JESTHA": 2, "JETH": 2, "JYESHTHA": 2, "JESTA": 2,
    # 3. Ashadh (~ mid Jun - mid Jul)
    "असार": 3, "आषाढ": 3, "अषाढ": 3, "ASHADH": 3, "ASAR": 3, "AASHADH": 3, "ASADH": 3,
    # 4. Shrawan (~ mid Jul - mid Aug)
    "साउन": 4, "श्रावण": 4, "SHRAWAN": 4, "SAUN": 4, "SRAWAN": 4, "SHRAVAN": 4,
    # 5. Bhadra (~ mid Aug - mid Sep)
    "भदौ": 5, "भाद्र": 5, "BHADRA": 5, "BHAU": 5, "BHADO": 5, "BHADRAPAD": 5,
    # 6. Ashwin (~ mid Sep - mid Oct)
    "असोज": 6, "आश्विन": 6, "आसोज": 6, "ASHWIN": 6, "ASOJ": 6, "AASHOJ": 6, "ASWIN": 6,
    # 7. Kartik (~ mid Oct - mid Nov)
    "कात्तिक": 7, "कार्तिक": 7, "KARTIK": 7, "KATTIK": 7, "KARTIKA": 7,
    # 8. Mangsir (~ mid Nov - mid Dec)
    "मंसिर": 8, "मार्गशीर्ष": 8, "मंगसिर": 8, "MANGSIR": 8, "MARGASHIRSHA": 8, "MANGSHIR": 8,
    # 9. Poush (~ mid Dec - mid Jan)
    "पुष": 9, "पौष": 9, "POUSH": 9, "PAUSH": 9, "PUSH": 9,
    # 10. Magh (~ mid Jan - mid Feb)
    "माघ": 10, "MAGH": 10, "MAGHA": 10,
    # 11. Falgun (~ mid Feb - mid Mar)
    "फागुन": 11, "फाल्गुन": 11, "FALGUN": 11, "PHAGUN": 11, "FALGUNA": 11, "PHALGUNA": 11,
    # 12. Chaitra (~ mid Mar - mid Apr)
    "चैत": 12, "चैत्र": 12, "CHAITRA": 12, "CHAIT": 12,
}


@dataclass
class NepaliCalendarResult:
    """Consolidated outcome of Bikram Sambat conversion."""
    raw_input: str
    bs_year: int
    bs_month: Optional[int]
    bs_day: Optional[int]
    bs_month_name: Optional[str]
    gregorian_date: Optional[str]  # ISO YYYY-MM-DD
    gregorian_primary_year: int
    gregorian_year_span: str  # e.g. "2023-2024"
    is_valid: bool
    detail: str


def to_ascii_digits(text: str) -> str:
    """Translate Devanagari numerals (०..९) to ASCII Latin digits (0..9)."""
    if not text:
        return ""
    return "".join(DEVANAGARI_DIGITS.get(ch, ch) for ch in text)


def convert_bs_year_to_gregorian(bs_year: int) -> Tuple[int, str]:
    """Calculate Gregorian equivalent year and span for a Bikram Sambat year.

    Bikram Sambat is approximately 56 years 8.5 months ahead of Gregorian.
    Year BS Y begins ~April 13/14 of Gregorian (Y - 57) and ends ~April 12 of (Y - 56).
    """
    g_start = bs_year - 57
    g_end = bs_year - 56
    return g_start, f"{g_start}-{g_end}"


def _bs_to_ad_date(bs_y: int, bs_m: int, bs_d: int) -> Optional[str]:
    """Convert (year, month, day) in BS to ISO Gregorian string."""
    try:
        import nepali_datetime
        bs_date = nepali_datetime.date(bs_y, bs_m, bs_d)
        ad_date = bs_date.to_datetime_date()
        return ad_date.isoformat()
    except Exception:
        # Fallback approximation (56 years 8 months offset)
        try:
            ad_y = bs_y - 57 if bs_m <= 8 else bs_y - 56
            ad_m = ((bs_m + 3) % 12) or 12
            ad_d = min(bs_d, 28)
            return datetime.date(ad_y, ad_m, ad_d).isoformat()
        except Exception:
            return None


def _parse_bs_components(cleaned: str) -> Optional[Tuple[int, int, int]]:
    """Extract (year, month, day) from numeric and text-month representations."""
    # Pattern 1: ISO style YYYY-MM-DD or YYYY/MM/DD
    m_iso = re.match(r"^(\d{4})[-/. ](\d{1,2})[-/. ](\d{1,2})$", cleaned)
    if m_iso:
        return int(m_iso.group(1)), int(m_iso.group(2)), int(m_iso.group(3))

    # Pattern 2: DMY style DD/MM/YYYY or DD-MM-YYYY
    m_dmy = re.match(r"^(\d{1,2})[-/. ](\d{1,2})[-/. ](\d{4})$", cleaned)
    if m_dmy:
        return int(m_dmy.group(3)), int(m_dmy.group(2)), int(m_dmy.group(1))

    # Pattern 3: Text month: e.g. "15 Baishakh 2080" or "१५ बैशाख २०८०"
    m_text = re.match(r"^(\d{1,2})[-/ ]+([^\d\s\-_/]+)[-/ ]+(\d{4})$", cleaned)
    if m_text:
        d = int(m_text.group(1))
        m_str = m_text.group(2).upper()
        y = int(m_text.group(3))
        if m_str in NEPALI_MONTH_MAP:
            return y, NEPALI_MONTH_MAP[m_str], d

    # Pattern 4: Year first with text month: e.g. "2080 Baishakh 15" or "२०८० बैशाख १५"
    m_y_first = re.match(r"^(\d{4})[-/ ]+([^\d\s\-_/]+)[-/ ]+(\d{1,2})$", cleaned)
    if m_y_first:
        y = int(m_y_first.group(1))
        m_str = m_y_first.group(2).upper()
        d = int(m_y_first.group(3))
        if m_str in NEPALI_MONTH_MAP:
            return y, NEPALI_MONTH_MAP[m_str], d

    return None


def convert_bikram_sambat(date_or_year_str: Optional[str]) -> NepaliCalendarResult:
    """Parse and convert any Bikram Sambat date or year into Gregorian.

    Accepts:
    - Full numeric dates: "2082-04-25", "25/04/2082", "२०८२/०४/२५"
    - Text month dates: "15 Baishakh 2080", "१५ बैशाख २०८०"
    - Year-only strings: "2080", "२०८०", "2080 BS", "वि.सं. २०८०"
    """
    if not date_or_year_str:
        return NepaliCalendarResult(
            raw_input="", bs_year=0, bs_month=None, bs_day=None,
            bs_month_name=None, gregorian_date=None, gregorian_primary_year=0,
            gregorian_year_span="", is_valid=False, detail="Empty input",
        )

    # 1. Normalize Devanagari digits to ASCII and remove prefixes
    text = to_ascii_digits(date_or_year_str.strip())
    text = re.sub(r"(?i)\b(B\.?S\.?|VI\.?SAM\.?|वि\.?सं\.?)\b", "", text).strip()
    text = re.sub(r"\s+", " ", text).strip()

    # 2. Check for full date components
    comps = _parse_bs_components(text)
    if comps:
        bs_y, bs_m, bs_d = comps
        g_year, g_span = convert_bs_year_to_gregorian(bs_y)
        g_date = _bs_to_ad_date(bs_y, bs_m, bs_d)
        m_name = NEPALI_MONTH_NAMES.get(bs_m)
        return NepaliCalendarResult(
            raw_input=date_or_year_str,
            bs_year=bs_y,
            bs_month=bs_m,
            bs_day=bs_d,
            bs_month_name=m_name,
            gregorian_date=g_date,
            gregorian_primary_year=g_year,
            gregorian_year_span=g_span,
            is_valid=(g_date is not None),
            detail=f"Converted BS {bs_y}-{bs_m:02d}-{bs_d:02d} ({m_name}) to Gregorian {g_date or 'N/A'}",
        )

    # 3. Check for year-only input (e.g. 2080)
    m_year = re.search(r"\b(19\d{2}|20\d{2}|21\d{2})\b", text)
    if m_year:
        bs_y = int(m_year.group(1))
        g_year, g_span = convert_bs_year_to_gregorian(bs_y)
        return NepaliCalendarResult(
            raw_input=date_or_year_str,
            bs_year=bs_y,
            bs_month=None,
            bs_day=None,
            bs_month_name=None,
            gregorian_date=None,
            gregorian_primary_year=g_year,
            gregorian_year_span=g_span,
            is_valid=True,
            detail=f"BS year {bs_y} corresponds to Gregorian year span {g_span} (primary {g_year})",
        )

    return NepaliCalendarResult(
        raw_input=date_or_year_str, bs_year=0, bs_month=None, bs_day=None,
        bs_month_name=None, gregorian_date=None, gregorian_primary_year=0,
        gregorian_year_span="", is_valid=False, detail="Could not parse as Bikram Sambat date or year",
    )
