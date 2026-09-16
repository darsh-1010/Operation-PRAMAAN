"""Data models and validation check structures for Module 1 Decision Matrix."""

from __future__ import annotations
from dataclasses import dataclass, field
import datetime
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from field_extractor import ParsedDocumentData


@dataclass
class ReasonCode:
    """Explainability reason code for risk assessment."""
    code: str
    message: str
    severity: str  # 'CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'
    contribution: float  # How much it moved or penalized the score


@dataclass
class ValidationCheckRecord:
    """Corresponds to the validation_checks table."""
    check_type: str  # 'MRZ_CHECKSUM', 'FIELD_FORMAT', 'EXPIRY', 'VIZ_MRZ_CROSSCHECK'
    field_key: Optional[str]
    status: str      # 'PASS', 'FAIL', 'WARN', 'SKIPPED'
    is_hard_fail: bool
    expected_value: Optional[str]
    observed_value: Optional[str]
    detail: str


@dataclass
class DecisionOutcome:
    """Consolidated Module 1 decision output matching the cross-service contract."""
    status: str               # 'VERIFIED', 'NEEDS REVIEW', 'NOT VERIFIED'
    score: float              # 0..100 display score
    canonical_score: float    # 0..1 database score
    hard_fail: bool
    reason_codes: List[ReasonCode] = field(default_factory=list)
    validation_checks: List[ValidationCheckRecord] = field(default_factory=list)
    sub_scores: Dict[str, float] = field(default_factory=dict)


def validate_field_formats(doc: ParsedDocumentData) -> List[ValidationCheckRecord]:
    """Validate format and semantics of extracted fields for cross-document consistency."""
    checks: List[ValidationCheckRecord] = []

    # 1. Name check
    if doc.claimed_name and len(doc.claimed_name.strip()) >= 2:
        checks.append(ValidationCheckRecord(
            check_type="FIELD_FORMAT",
            field_key="name",
            status="PASS",
            is_hard_fail=False,
            expected_value="NON_EMPTY",
            observed_value=doc.claimed_name,
            detail="Name is formatted correctly.",
        ))
    else:
        checks.append(ValidationCheckRecord(
            check_type="FIELD_FORMAT",
            field_key="name",
            status="FAIL",
            is_hard_fail=False,
            expected_value="NON_EMPTY",
            observed_value=doc.claimed_name,
            detail="Name is missing or invalid.",
        ))

    # 2. DOB check
    if doc.claimed_dob:
        try:
            dob_dt = datetime.date.fromisoformat(doc.claimed_dob)
            if dob_dt > datetime.date.today():
                checks.append(ValidationCheckRecord(
                    check_type="FIELD_FORMAT",
                    field_key="dob",
                    status="FAIL",
                    is_hard_fail=False,
                    expected_value="PAST_DATE",
                    observed_value=doc.claimed_dob,
                    detail="Date of birth cannot be in the future.",
                ))
            else:
                checks.append(ValidationCheckRecord(
                    check_type="FIELD_FORMAT",
                    field_key="dob",
                    status="PASS",
                    is_hard_fail=False,
                    expected_value="PAST_DATE",
                    observed_value=doc.claimed_dob,
                    detail="Date of birth is valid.",
                ))
        except ValueError:
            checks.append(ValidationCheckRecord(
                check_type="FIELD_FORMAT",
                field_key="dob",
                status="FAIL",
                is_hard_fail=False,
                expected_value="YYYY-MM-DD",
                observed_value=doc.claimed_dob,
                detail="Date of birth has invalid format.",
            ))
    else:
        checks.append(ValidationCheckRecord(
            check_type="FIELD_FORMAT",
            field_key="dob",
            status="WARN",
            is_hard_fail=False,
            expected_value="YYYY-MM-DD",
            observed_value=None,
            detail="Date of birth is missing.",
        ))

    # 3. Document number check
    if doc.document_number and len(doc.document_number.strip()) >= 3:
        checks.append(ValidationCheckRecord(
            check_type="FIELD_FORMAT",
            field_key="document_number",
            status="PASS",
            is_hard_fail=False,
            expected_value="VALID_ID",
            observed_value=doc.document_number,
            detail="Document number is formatted correctly.",
        ))
    else:
        checks.append(ValidationCheckRecord(
            check_type="FIELD_FORMAT",
            field_key="document_number",
            status="FAIL",
            is_hard_fail=False,
            expected_value="VALID_ID",
            observed_value=doc.document_number,
            detail="Document number is missing or too short.",
        ))

    # 4. Expiry check
    if doc.claimed_expiry:
        try:
            datetime.date.fromisoformat(doc.claimed_expiry)
            checks.append(ValidationCheckRecord(
                check_type="FIELD_FORMAT",
                field_key="expiry",
                status="PASS",
                is_hard_fail=False,
                expected_value="DATE",
                observed_value=doc.claimed_expiry,
                detail="Expiry date format is valid.",
            ))
        except ValueError:
            checks.append(ValidationCheckRecord(
                check_type="FIELD_FORMAT",
                field_key="expiry",
                status="FAIL",
                is_hard_fail=False,
                expected_value="DATE",
                observed_value=doc.claimed_expiry,
                detail="Expiry date format is invalid.",
            ))
    else:
        checks.append(ValidationCheckRecord(
            check_type="FIELD_FORMAT",
            field_key="expiry",
            status="WARN",
            is_hard_fail=False,
            expected_value="DATE",
            observed_value=None,
            detail="Expiry date is missing.",
        ))

    return checks
