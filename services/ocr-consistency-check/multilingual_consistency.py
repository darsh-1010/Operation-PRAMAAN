"""Multilingual and Regional Identity Consistency Verification.

Performs consistency checks specific to multilingual documents:
- Bikram Sambat (B.S.) to Gregorian (A.D.) calendar reconciliation
- Dual-calendar consistency (when documents contain both B.S. and A.D. dates)
- Nepali Citizenship Certificate and regional ID number format verification
- Multilingual cross-document date and identity matching
"""

from __future__ import annotations
import datetime
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from nepali_calendar import convert_bikram_sambat, NepaliCalendarResult

logger = logging.getLogger("multilingual_consistency")


@dataclass
class MultilingualCheckResult:
    """Outcome of a multilingual consistency check."""
    check_name: str
    status: str  # 'PASS', 'WARN', 'FAIL'
    is_hard_fail: bool
    detail: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MultilingualConsistencyReport:
    """Consolidated multilingual validation outcome."""
    is_consistent: bool
    hard_fail: bool
    checks: List[MultilingualCheckResult] = field(default_factory=list)
    calendar_conversion: Optional[NepaliCalendarResult] = None
    notes: List[str] = field(default_factory=list)


def check_nepali_date_consistency(
    claimed_bs_date: Optional[str],
    claimed_ad_date: Optional[str] = None,
    expected_ad_date: Optional[str] = None,
) -> MultilingualCheckResult:
    """Verify that a Nepali Bikram Sambat date converts accurately and matches Gregorian records."""
    if not claimed_bs_date:
        return MultilingualCheckResult(
            check_name="NEPALI_CALENDAR_CONVERSION",
            status="WARN",
            is_hard_fail=False,
            detail="No Nepali date provided for calendar conversion.",
        )

    res = convert_bikram_sambat(claimed_bs_date)
    if not res.is_valid:
        return MultilingualCheckResult(
            check_name="NEPALI_CALENDAR_CONVERSION",
            status="FAIL",
            is_hard_fail=False,
            detail=f"Invalid Bikram Sambat date format: '{claimed_bs_date}'.",
            metadata={"raw": claimed_bs_date},
        )

    converted_ad = res.gregorian_date
    metadata = {
        "bs_date": claimed_bs_date,
        "converted_ad": converted_ad,
        "bs_year": res.bs_year,
        "gregorian_span": res.gregorian_year_span,
    }

    # If document has both BS and AD printed, compare them
    if claimed_ad_date and converted_ad:
        if claimed_ad_date == converted_ad:
            return MultilingualCheckResult(
                check_name="DUAL_CALENDAR_RECONCILIATION",
                status="PASS",
                is_hard_fail=False,
                detail=f"Dual calendar matches: BS {claimed_bs_date} converts to AD {converted_ad}.",
                metadata=metadata,
            )
        else:
            return MultilingualCheckResult(
                check_name="DUAL_CALENDAR_RECONCILIATION",
                status="FAIL",
                is_hard_fail=True,
                detail=f"Calendar mismatch: BS '{claimed_bs_date}' converted to '{converted_ad}', but document prints AD '{claimed_ad_date}'.",
                metadata=metadata,
            )

    # If comparing against ground truth / MRZ date
    if expected_ad_date and converted_ad:
        if expected_ad_date == converted_ad:
            return MultilingualCheckResult(
                check_name="CALENDAR_REGISTRY_MATCH",
                status="PASS",
                is_hard_fail=False,
                detail=f"Converted BS date matches expected Gregorian date: {converted_ad}.",
                metadata=metadata,
            )
        else:
            return MultilingualCheckResult(
                check_name="CALENDAR_REGISTRY_MATCH",
                status="FAIL",
                is_hard_fail=True,
                detail=f"Registry DOB mismatch: converted BS gives '{converted_ad}' vs registry '{expected_ad_date}'.",
                metadata=metadata,
            )

    return MultilingualCheckResult(
        check_name="NEPALI_CALENDAR_CONVERSION",
        status="PASS",
        is_hard_fail=False,
        detail=f"Successfully converted BS '{claimed_bs_date}' to Gregorian '{converted_ad or res.gregorian_year_span}'.",
        metadata=metadata,
    )


def check_nepali_id_format(id_number: Optional[str]) -> MultilingualCheckResult:
    """Validate format of Nepali Citizenship Certificate or Driving Licence."""
    if not id_number:
        return MultilingualCheckResult(
            check_name="NEPALI_ID_FORMAT",
            status="WARN",
            is_hard_fail=False,
            detail="Document ID number missing.",
        )

    cleaned = id_number.strip().upper()
    # Format: XX-XX-XX-XXXXX or XXXXX/XXXX or similar numeric/district codes
    is_citizenship = bool(re.match(r"^(\d{2}[-\s]?\d{2}[-\s]?\d{2}[-\s]?\d{4,6}|\d{4,8}[/-]\d{2,5}|\d{8,14})$", cleaned))
    # Driving licence: XX-XX-XXXXXXXX
    is_dl = bool(re.match(r"^(\d{2}[-\s]?\d{2}[-\s]?\d{8}|[A-Z0-9\-_]{6,16})$", cleaned))

    if is_citizenship or is_dl:
        return MultilingualCheckResult(
            check_name="NEPALI_ID_FORMAT",
            status="PASS",
            is_hard_fail=False,
            detail=f"Document ID '{cleaned}' matches recognized regional ID pattern.",
            metadata={"id_number": cleaned},
        )

    return MultilingualCheckResult(
        check_name="NEPALI_ID_FORMAT",
        status="WARN",
        is_hard_fail=False,
        detail=f"Document ID '{cleaned}' does not match standard regional ID numbering format.",
        metadata={"id_number": cleaned},
    )


def evaluate_multilingual_consistency(
    document_number: Optional[str],
    claimed_name: Optional[str],
    claimed_bs_date: Optional[str] = None,
    claimed_ad_date: Optional[str] = None,
    expected_ad_date: Optional[str] = None,
    issuing_country: str = "NPL",
) -> MultilingualConsistencyReport:
    """Run full suite of multilingual and regional checks."""
    checks: List[MultilingualCheckResult] = []
    notes: List[str] = []

    cal_res: Optional[NepaliCalendarResult] = None
    if claimed_bs_date:
        cal_res = convert_bikram_sambat(claimed_bs_date)
        cal_check = check_nepali_date_consistency(claimed_bs_date, claimed_ad_date, expected_ad_date)
        checks.append(cal_check)
        notes.append(cal_check.detail)

    if issuing_country == "NPL" and document_number:
        id_check = check_nepali_id_format(document_number)
        checks.append(id_check)
        notes.append(id_check.detail)

    hard_fail = any(c.is_hard_fail and c.status == "FAIL" for c in checks)
    is_consistent = all(c.status != "FAIL" for c in checks)

    return MultilingualConsistencyReport(
        is_consistent=is_consistent,
        hard_fail=hard_fail,
        checks=checks,
        calendar_conversion=cal_res,
        notes=notes,
    )
