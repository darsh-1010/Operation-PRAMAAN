"""Scoring and Decision Matrix Engine.

Calculates Module 1 (Score A) across identity elements:
- ID Match: 35%
- Name Fuzzy Match: 30%
- DOB Match: 20%
- Document Status & Expiry: 15%

Applies hard-fail rules (Watchlist hit, Revoked status, MRZ tampering)
and classifies the encounter as: VERIFIED, NEEDS REVIEW, or NOT VERIFIED.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from candidate_search import WatchlistHitResult
from field_extractor import ParsedDocumentData
from matcher import MatchOutcome


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


def evaluate_decision_matrix(
    extracted: ParsedDocumentData,
    match: MatchOutcome,
    watchlist_hits: List[WatchlistHitResult],
) -> DecisionOutcome:
    """Calculate weighted Score A and determine verification status and reason codes."""
    hard_fail = False
    reasons: List[ReasonCode] = []
    checks: List[ValidationCheckRecord] = []

    # -------------------------------------------------------------
    # 1. Watchlist Screening Checks
    # -------------------------------------------------------------
    if watchlist_hits:
        hard_fail = True
        for hit in watchlist_hits:
            reasons.append(ReasonCode(
                code=f"WATCHLIST_HIT_{hit.kind}",
                message=f"Flagged on {hit.source} watchlist: {hit.reason}",
                severity="CRITICAL",
                contribution=1.0,
            ))
            checks.append(ValidationCheckRecord(
                check_type="WATCHLIST_LOOKUP",
                field_key="document_number",
                status="FAIL",
                is_hard_fail=True,
                expected_value="NOT_ON_WATCHLIST",
                observed_value=hit.kind,
                detail=hit.reason,
            ))

    # -------------------------------------------------------------
    # 2. MRZ Integrity & Checksum Checks
    # -------------------------------------------------------------
    if extracted.mrz_result:
        mrz = extracted.mrz_result
        if mrz.has_checksum_failure:
            hard_fail = True
            fail_desc = "; ".join(mrz.failure_details)
            reasons.append(ReasonCode(
                code="MRZ_CHECKSUM_FAILED",
                message=f"MRZ check digit validation failed: {fail_desc}",
                severity="CRITICAL",
                contribution=0.8,
            ))
            checks.append(ValidationCheckRecord(
                check_type="MRZ_CHECKSUM",
                field_key="mrz",
                status="FAIL",
                is_hard_fail=True,
                expected_value="VALID_CHECKSUM",
                observed_value="INVALID",
                detail=fail_desc,
            ))
        else:
            checks.append(ValidationCheckRecord(
                check_type="MRZ_CHECKSUM",
                field_key="mrz",
                status="PASS",
                is_hard_fail=False,
                expected_value="VALID_CHECKSUM",
                observed_value="VALID",
                detail="All MRZ check digits verified against ICAO 9303 standard.",
            ))

    # -------------------------------------------------------------
    # 3. VIZ vs MRZ Cross-Check
    # -------------------------------------------------------------
    if not extracted.viz_mrz_consistent:
        incon_desc = "; ".join(extracted.inconsistencies)
        reasons.append(ReasonCode(
            code="VIZ_MRZ_INCONSISTENCY",
            message=f"Discrepancy between printed text and MRZ: {incon_desc}",
            severity="HIGH",
            contribution=0.35,
        ))
        checks.append(ValidationCheckRecord(
            check_type="BARCODE_CROSSCHECK",
            field_key="cross_check",
            status="WARN",
            is_hard_fail=False,
            expected_value="MATCH",
            observed_value="MISMATCH",
            detail=incon_desc,
        ))

    # -------------------------------------------------------------
    # 4. Ground Truth Candidate Evaluation
    # -------------------------------------------------------------
    if not match.has_candidate:
        reasons.append(ReasonCode(
            code="REGISTRY_RECORD_NOT_FOUND",
            message="No matching document found in the civil/issuer registry.",
            severity="HIGH",
            contribution=0.5,
        ))
        checks.append(ValidationCheckRecord(
            check_type="ISSUER_RULE",
            field_key="document_number",
            status="FAIL",
            is_hard_fail=False,
            expected_value="EXISTS_IN_REGISTRY",
            observed_value="NOT_FOUND",
            detail="Document number not registered in issuer database.",
        ))
    else:
        # Document status check
        if not match.is_status_active:
            hard_fail = True
            reasons.append(ReasonCode(
                code=f"DOCUMENT_{match.candidate.status.upper()}",
                message=f"Document is marked as {match.candidate.status} in issuer registry.",
                severity="CRITICAL",
                contribution=1.0,
            ))
            checks.append(ValidationCheckRecord(
                check_type="ISSUER_RULE",
                field_key="status",
                status="FAIL",
                is_hard_fail=True,
                expected_value="ACTIVE",
                observed_value=match.candidate.status,
                detail=f"Registry status is {match.candidate.status}.",
            ))

        # Expiry check
        if match.is_expired:
            reasons.append(ReasonCode(
                code="DOCUMENT_EXPIRED",
                message=f"Document expired on {match.candidate.expiry_date}.",
                severity="HIGH",
                contribution=0.25,
            ))
            checks.append(ValidationCheckRecord(
                check_type="EXPIRY",
                field_key="expiry_date",
                status="FAIL",
                is_hard_fail=False,
                expected_value="FUTURE_DATE",
                observed_value=match.candidate.expiry_date,
                detail="Document validity period has expired.",
            ))
        else:
            checks.append(ValidationCheckRecord(
                check_type="EXPIRY",
                field_key="expiry_date",
                status="PASS",
                is_hard_fail=False,
                expected_value="FUTURE_DATE",
                observed_value=match.candidate.expiry_date,
                detail="Document is within validity period.",
            ))

        # Check differences
        for diff in match.differences:
            if "Name mismatch" in diff:
                reasons.append(ReasonCode(
                    code="NAME_FUZZY_MISMATCH",
                    message=diff,
                    severity="MEDIUM",
                    contribution=0.15,
                ))

    # -------------------------------------------------------------
    # 5. Calculate Weighted Score A
    # -------------------------------------------------------------
    sub_scores = {
        "id_match": match.id_score,
        "name_match": match.name_score,
        "dob_match": match.dob_score,
        "validity": match.validity_score,
    }

    if hard_fail:
        canonical_score = 0.0
        status = "NOT VERIFIED"
    elif not match.has_candidate:
        canonical_score = 0.30  # OCR read the doc, but identity is unverified in DB
        status = "NOT VERIFIED"
    else:
        # Weights: ID 35%, Name 30%, DOB 20%, Validity 15%
        weighted = (
            (0.35 * match.id_score) +
            (0.30 * match.name_score) +
            (0.20 * match.dob_score) +
            (0.15 * match.validity_score)
        )
        canonical_score = round(max(0.0, min(1.0, weighted)), 4)

        if canonical_score >= 0.85:
            status = "VERIFIED"
        elif canonical_score >= 0.60:
            status = "NEEDS REVIEW"
        else:
            status = "NOT VERIFIED"

    score_100 = round(canonical_score * 100.0, 2)

    return DecisionOutcome(
        status=status,
        score=score_100,
        canonical_score=canonical_score,
        hard_fail=hard_fail,
        reason_codes=reasons,
        validation_checks=checks,
        sub_scores=sub_scores,
    )

