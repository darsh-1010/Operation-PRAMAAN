"""Cross-Document Field Consistency Verifier.

Compares extracted identity fields (name, DOB, gender) across multiple
documents submitted for the same person (e.g. passport + driving licence +
visa) to catch inconsistent or fraudulent document sets. This is independent
of, and does not affect, the single-document /screen pipeline.
"""
from __future__ import annotations
import logging
from dataclasses import dataclass, field
from typing import List, Optional

from field_extractor import ParsedDocumentData
from matcher import compute_fuzzy_name_score

logger = logging.getLogger("cross_document")

NAME_MATCH_THRESHOLD = 0.85


@dataclass
class CrossDocFieldResult:
    """Consistency outcome for one field compared across all submitted documents."""
    field_key: str
    consistent: bool
    values: List[str]  # one value per document, in submission order ("—" if missing)
    detail: str


@dataclass
class CrossDocumentOutcome:
    """Consolidated cross-document consistency result."""
    consistent: bool
    field_results: List[CrossDocFieldResult] = field(default_factory=list)


def _compare_names(names: List[Optional[str]]) -> CrossDocFieldResult:
    """Fuzzy-compare name across documents (allows minor OCR/spelling variance)."""
    present = [n for n in names if n]
    consistent = True
    for other in present[1:]:
        if compute_fuzzy_name_score(present[0], other) < NAME_MATCH_THRESHOLD:
            consistent = False
            break
    detail = "Name consistent across documents." if consistent else "Name differs across documents beyond fuzzy-match tolerance."
    return CrossDocFieldResult("name", consistent, [n or "—" for n in names], detail)


def _compare_exact(field_key: str, values: List[Optional[str]], label: str) -> CrossDocFieldResult:
    """Exact-compare a field (e.g. DOB, gender) across documents."""
    present = [v for v in values if v]
    consistent = len(set(present)) <= 1
    detail = f"{label} consistent across documents." if consistent else f"{label} differs across documents."
    return CrossDocFieldResult(field_key, consistent, [v or "—" for v in values], detail)


def cross_check_documents(documents: List[ParsedDocumentData]) -> CrossDocumentOutcome:
    """Compare name/DOB/gender across 2+ parsed documents believed to belong to one person."""
    results = [
        _compare_names([d.claimed_name for d in documents]),
        _compare_exact("dob", [d.claimed_dob for d in documents], "Date of birth"),
        _compare_exact("gender", [d.claimed_gender for d in documents], "Gender"),
    ]
    outcome = CrossDocumentOutcome(consistent=all(r.consistent for r in results), field_results=results)
    if not outcome.consistent:
        logger.warning("Cross-document inconsistency: %s", [r.detail for r in results if not r.consistent])
    return outcome


def _demo() -> None:
    """Runnable self-check — not a full test suite, just a smoke check."""
    same_person = [
        ParsedDocumentData(doc_type="PASSPORT", claimed_name="SHARMA ARYA", claimed_dob="1995-08-15", claimed_gender="M"),
        ParsedDocumentData(doc_type="DRIVING_LICENSE", claimed_name="ARYA SHARMA", claimed_dob="1995-08-15", claimed_gender="M"),
    ]
    outcome = cross_check_documents(same_person)
    assert outcome.consistent, "fuzzy name match + exact dob/gender should be consistent"

    mismatched = [
        ParsedDocumentData(doc_type="PASSPORT", claimed_name="SHARMA ARYA", claimed_dob="1995-08-15", claimed_gender="M"),
        ParsedDocumentData(doc_type="VISA", claimed_name="KHAN IMRAN", claimed_dob="1990-01-01", claimed_gender="M"),
    ]
    outcome2 = cross_check_documents(mismatched)
    assert not outcome2.consistent, "different name and dob should be flagged inconsistent"
    name_result = next(r for r in outcome2.field_results if r.field_key == "name")
    assert not name_result.consistent

    print("cross_document self-check passed")


if __name__ == "__main__":
    _demo()
