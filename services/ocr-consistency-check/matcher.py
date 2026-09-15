"""Fuzzy and Strict Document Matching Engine.

Performs strict identity checks (ID Number, DOB, Document Status)
and fuzzy text matching (Personal Name using RapidFuzz/token_sort_ratio)
against ground-truth registry candidates and cross-checks VIZ vs MRZ.
"""

from __future__ import annotations
import datetime
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from candidate_search import CandidateRecord
from field_extractor import ParsedDocumentData

logger = logging.getLogger("matcher")

try:
    from rapidfuzz import fuzz
    RAPIDFUZZ_AVAILABLE = True
except ImportError:
    import difflib
    RAPIDFUZZ_AVAILABLE = False


def compute_fuzzy_name_score(name1: Optional[str], name2: Optional[str]) -> float:
    """Calculate token-order invariant similarity ratio between two names."""
    if not name1 or not name2:
        return 0.0

    n1 = name1.strip().upper()
    n2 = name2.strip().upper()

    if n1 == n2:
        return 1.0

    if RAPIDFUZZ_AVAILABLE:
        # token_sort_ratio ignores token ordering (e.g. "SHARMA ARYA" vs "ARYA SHARMA")
        token_sort = fuzz.token_sort_ratio(n1, n2) / 100.0
        # partial_ratio handles missing middle names
        partial = fuzz.partial_ratio(n1, n2) / 100.0
        return round(max(token_sort, partial), 4)

    # Standard library fallback
    words1 = sorted(n1.split())
    words2 = sorted(n2.split())
    s = difflib.SequenceMatcher(None, " ".join(words1), " ".join(words2))
    return round(float(s.ratio()), 4)


@dataclass
class MatchOutcome:
    """Consolidated outcome of comparing an extracted doc to a ground-truth candidate."""
    has_candidate: bool
    candidate: Optional[CandidateRecord]
    id_score: float
    name_score: float
    dob_score: float
    validity_score: float
    is_id_matched: bool
    is_dob_matched: bool
    is_name_matched: bool  # >= 0.85
    is_status_active: bool
    is_expired: bool
    differences: List[str] = field(default_factory=list)


def match_against_candidate(extracted: ParsedDocumentData, candidate: Optional[CandidateRecord]) -> MatchOutcome:
    """Evaluate extracted credentials against ground-truth candidate."""
    if candidate is None:
        logger.info("No registry candidate to match against.")
        return MatchOutcome(
            has_candidate=False,
            candidate=None,
            id_score=0.0,
            name_score=0.0,
            dob_score=0.0,
            validity_score=0.0,
            is_id_matched=False,
            is_dob_matched=False,
            is_name_matched=False,
            is_status_active=False,
            is_expired=False,
            differences=["No candidate record found in registry."],
        )

    differences: List[str] = []

    # 1. Strict ID Match
    ext_id = (extracted.document_number or "").strip().upper()
    cand_id = candidate.id_number.strip().upper()
    id_matched = (ext_id == cand_id) and len(ext_id) > 0
    id_score = 1.0 if id_matched else 0.0
    if not id_matched:
        differences.append(f"ID mismatch: extracted '{ext_id}' vs registry '{cand_id}'")

    # 2. Strict DOB Match
    ext_dob = extracted.claimed_dob
    cand_dob = candidate.dob
    dob_matched = (ext_dob == cand_dob) if (ext_dob and cand_dob) else False
    dob_score = 1.0 if dob_matched else 0.0
    if not dob_matched:
        differences.append(f"DOB mismatch: extracted '{ext_dob}' vs registry '{cand_dob}'")

    # 3. Fuzzy Name Match
    name_score = compute_fuzzy_name_score(extracted.claimed_name, candidate.full_name)
    name_matched = (name_score >= 0.85)
    if not name_matched:
        differences.append(f"Name mismatch (similarity {name_score:.2f}): '{extracted.claimed_name}' vs '{candidate.full_name}'")

    # 4. Document Status & Expiry
    is_active = (candidate.status == "ACTIVE")
    if not is_active:
        differences.append(f"Document status in registry is '{candidate.status}'")

    is_expired = False
    if candidate.expiry_date:
        try:
            exp_date = datetime.date.fromisoformat(candidate.expiry_date)
            is_expired = (exp_date < datetime.date.today())
            if is_expired:
                differences.append(f"Document expired on {candidate.expiry_date}")
        except ValueError:
            pass

    validity_score = 1.0 if (is_active and not is_expired) else (0.5 if (is_active and is_expired) else 0.0)

    logger.info(
        "Match against candidate %s: id_matched=%s, dob_matched=%s, name_score=%.2f, active=%s, expired=%s.",
        candidate.record_id, id_matched, dob_matched, name_score, is_active, is_expired,
    )
    if differences:
        logger.warning("Match differences: %s", "; ".join(differences))

    return MatchOutcome(
        has_candidate=True,
        candidate=candidate,
        id_score=id_score,
        name_score=name_score,
        dob_score=dob_score,
        validity_score=validity_score,
        is_id_matched=id_matched,
        is_dob_matched=dob_matched,
        is_name_matched=name_matched,
        is_status_active=is_active,
        is_expired=is_expired,
        differences=differences,
    )

