"""Scoring and Decision Matrix Engine.

Calculates Module 1 (Score A) across identity elements:
- MRZ / Format Integrity: 35%
- VIZ vs MRZ Consistency: 35%
- Expiry / Validity: 20%
- Extraction Completeness: 10%
"""

from __future__ import annotations
from datetime import date, datetime
from typing import Any, List, Optional

from candidate_search import WatchlistHitResult
from decision_models import (
    DecisionOutcome,
    ReasonCode,
    ValidationCheckRecord,
    validate_field_formats,
)
from field_extractor import ParsedDocumentData
from matcher import MatchOutcome

# Re-export for backward compatibility
_validate_field_formats = validate_field_formats


def _check_watchlist(hits: List[WatchlistHitResult], reasons: List[ReasonCode], checks: List[ValidationCheckRecord]) -> bool:
    if not hits:
        return False
    for hit in hits:
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
    return True


def _check_mrz(mrz: Any, reasons: List[ReasonCode], checks: List[ValidationCheckRecord]) -> bool:
    if not mrz:
        return False
    if mrz.has_checksum_failure:
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
        return True
    checks.append(ValidationCheckRecord(
        check_type="MRZ_CHECKSUM",
        field_key="mrz",
        status="PASS",
        is_hard_fail=False,
        expected_value="VALID_CHECKSUM",
        observed_value="VALID",
        detail="All MRZ check digits verified against ICAO 9303 standard.",
    ))
    return False


def _check_expiry(expiry_str: Optional[str], reasons: List[ReasonCode], checks: List[ValidationCheckRecord]) -> bool:
    is_doc_expired = False
    if expiry_str:
        try:
            exp_date = datetime.strptime(str(expiry_str)[:10], "%Y-%m-%d").date()
            if exp_date < date.today():
                is_doc_expired = True
        except Exception:
            pass

    if is_doc_expired:
        reasons.append(ReasonCode(
            code="DOCUMENT_EXPIRED",
            message=f"Document validity expired on {expiry_str}.",
            severity="HIGH",
            contribution=0.25,
        ))
        checks.append(ValidationCheckRecord(
            check_type="EXPIRY",
            field_key="expiry_date",
            status="FAIL",
            is_hard_fail=False,
            expected_value="FUTURE_DATE",
            observed_value=str(expiry_str),
            detail="Document validity period has expired.",
        ))
    elif expiry_str:
        checks.append(ValidationCheckRecord(
            check_type="EXPIRY",
            field_key="expiry_date",
            status="PASS",
            is_hard_fail=False,
            expected_value="FUTURE_DATE",
            observed_value=str(expiry_str),
            detail="Document is within validity period.",
        ))
    return is_doc_expired


def evaluate_decision_matrix(
    extracted: ParsedDocumentData,
    match: MatchOutcome,
    watchlist_hits: List[WatchlistHitResult],
) -> DecisionOutcome:
    """Calculate weighted Score A and determine verification status and reason codes."""
    reasons: List[ReasonCode] = []
    checks: List[ValidationCheckRecord] = []

    hard_fail = _check_watchlist(watchlist_hits, reasons, checks)
    if extracted.mrz_result and _check_mrz(extracted.mrz_result, reasons, checks):
        hard_fail = True

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

    expiry_str = (
        match.candidate.expiry_date
        if match and match.has_candidate and match.candidate and match.candidate.expiry_date
        else extracted.claimed_expiry
    )
    is_doc_expired = _check_expiry(expiry_str, reasons, checks)

    if match and match.has_candidate and match.candidate and not match.is_status_active:
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

    mrz_int = 0.0 if (extracted.mrz_result and extracted.mrz_result.has_checksum_failure) else (1.0 if extracted.document_number else 0.6)
    cons_sc = 1.0 if extracted.viz_mrz_consistent else 0.35
    val_sc = 0.0 if is_doc_expired else 1.0
    comp_sc = (0.5 if extracted.document_number else 0.0) + (0.5 if extracted.claimed_name else 0.0)

    sub_scores = {"mrz_integrity": mrz_int, "viz_mrz_consistency": cons_sc, "validity": val_sc, "completeness": comp_sc}

    if hard_fail:
        canonical_score, status = 0.0, "NOT VERIFIED"
    elif match and match.has_candidate and match.candidate:
        weighted = (0.35 * match.id_score) + (0.30 * match.name_score) + (0.20 * match.dob_score) + (0.15 * match.validity_score)
        canonical_score = round(max(0.0, min(1.0, weighted)), 4)
        status = "VERIFIED" if canonical_score >= 0.85 else ("NEEDS REVIEW" if canonical_score >= 0.60 else "NOT VERIFIED")
    else:
        weighted = (0.35 * mrz_int) + (0.35 * cons_sc) + (0.20 * val_sc) + (0.10 * comp_sc)
        canonical_score = round(max(0.0, min(1.0, weighted)), 4)
        status = "VERIFIED" if canonical_score >= 0.85 else ("NEEDS REVIEW" if canonical_score >= 0.60 else "NOT VERIFIED")

    return DecisionOutcome(
        status=status, score=round(canonical_score * 100.0, 2), canonical_score=canonical_score,
        hard_fail=hard_fail, reason_codes=reasons, validation_checks=checks, sub_scores=sub_scores,
    )
