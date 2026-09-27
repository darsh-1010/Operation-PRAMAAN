"""Candidate Document Search and Watchlist Screening.

Implements high-performance queries to find ground-truth candidate records
matching extracted ID credentials and screens against national/Interpol watchlists.
"""

from __future__ import annotations
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from rapidfuzz import fuzz

from db import DatabaseManager
from normalizer import normalize_date

logger = logging.getLogger("candidate_search")


@dataclass
class CandidateRecord:
    """Represents a ground-truth registry document record."""
    record_id: str
    doc_type: str
    id_number: str
    full_name: str
    dob: str
    gender: Optional[str] = None
    issue_date: Optional[str] = None
    expiry_date: Optional[str] = None
    issuing_country: str = "IND"
    status: str = "ACTIVE"  # 'ACTIVE', 'REVOKED', 'EXPIRED', 'SUSPENDED'


@dataclass
class WatchlistHitResult:
    """Represents a hit against blacklists or stolen document lists."""
    entry_id: str
    kind: str  # 'BLACKLIST_DOC', 'BLACKLIST_PERSON', 'LOST_STOLEN', 'FACE'
    match_basis: str  # 'DOC_NUMBER' or 'NAME_DOB'
    match_score: float
    reason: str
    source: str
    is_hard_fail: bool = True


class CandidateSearchEngine:
    """Orchestrates candidate lookup and watchlist checks against database."""

    def __init__(self, db: Optional[DatabaseManager] = None) -> None:
        self.db = db or DatabaseManager.get_instance()

    def find_candidate_documents(self, doc_type: str, id_number: Optional[str], dob: Optional[str] = None) -> List[CandidateRecord]:
        """Search ground truth records for candidate identities."""
        if not id_number:
            return []

        clean_id = id_number.strip().upper()
        # Query 1: Exact match on (doc_type, id_number)
        sql = """
            SELECT record_id, doc_type, id_number, full_name, dob, gender, issue_date, expiry_date, issuing_country, status
            FROM ground_truth_records
            WHERE UPPER(doc_type::text) = %s AND UPPER(TRIM(id_number)) = %s
            LIMIT 5;
        """
        rows = self.db.query(sql, (doc_type.upper(), clean_id))

        # Query 2: If exact match empty and DOB is known, find candidates by (doc_type, dob)
        if not rows and dob:
            sql_fallback = """
                SELECT record_id, doc_type, id_number, full_name, dob, gender, issue_date, expiry_date, issuing_country, status
                FROM ground_truth_records
                WHERE UPPER(doc_type::text) = %s AND dob = %s
                LIMIT 5;
            """
            rows = self.db.query(sql_fallback, (doc_type.upper(), dob))

        candidates: List[CandidateRecord] = []
        for r in rows:
            candidates.append(CandidateRecord(
                record_id=str(r["record_id"]),
                doc_type=str(r["doc_type"]),
                id_number=str(r["id_number"]),
                full_name=str(r["full_name"]),
                dob=str(r["dob"]),
                gender=str(r["gender"]) if r["gender"] else None,
                issue_date=str(r["issue_date"]) if r.get("issue_date") else None,
                expiry_date=str(r["expiry_date"]) if r.get("expiry_date") else None,
                issuing_country=str(r.get("issuing_country", "IND")),
                status=str(r.get("status", "ACTIVE")),
            ))
        return candidates

    def screen_watchlist(self, document_number: Optional[str], full_name: Optional[str], dob: Optional[str]) -> List[WatchlistHitResult]:
        """Screen an extracted identity against every active watchlist entry.

        * Document number: exact after dropping spaces/dashes/punctuation → hard fail.
        * Name: order-insensitive fuzzy match (normalize_watchlist_name + rapidfuzz) so a stored
          "KHAN, DAWOOD" matches OCR's "DAWOOD KHAN" and spelling variants (Mohammed/Mohammad)
          or small OCR slips still hit. Then the date of birth decides:
            same DOB            → hard fail (NAME_DOB)
            DOB not available   → possible match, officer review, NOT a reject (NAME_ONLY) —
                                  common names would otherwise reject innocent travellers
            different DOB       → not a hit.
        One hit per entry at most (a document-number hit wins).

        ponytail: scans all active entries in Python (fine to tens of thousands); for a national-
        scale list move the name match into Postgres with pg_trgm + an index.
        """
        rows = self.db.query(
            "SELECT entry_id, kind, doc_number, full_name, dob, reason, source "
            "FROM watchlist_entries WHERE CAST(active AS INTEGER) = 1"
        )
        doc_key = normalize_doc_number(document_number)
        name_key = normalize_watchlist_name(full_name)
        dob_key = normalize_date(dob) if dob else None
        hits: List[WatchlistHitResult] = []
        for r in rows:
            hit = None
            if doc_key and normalize_doc_number(r.get("doc_number")) == doc_key:
                hit = ("DOC_NUMBER", 1.0, True, "Watchlist document match")
            elif name_key and r.get("full_name"):
                score = fuzz.token_sort_ratio(name_key, normalize_watchlist_name(r["full_name"])) / 100.0
                entry_dob = normalize_date(r.get("dob")) if r.get("dob") else None
                if score >= NAME_MATCH_THRESHOLD:
                    if dob_key and entry_dob:
                        if dob_key == entry_dob:
                            hit = ("NAME_DOB", round(score, 4), True, "Watchlist person match by name and date of birth")
                    else:
                        hit = ("NAME_ONLY", round(score, 4), False, "Possible watchlist name match — date of birth unavailable, verify manually")
            if hit:
                basis, score, hard, default_reason = hit
                hits.append(WatchlistHitResult(
                    entry_id=str(r["entry_id"]), kind=str(r["kind"]), match_basis=basis, match_score=score,
                    reason=str(r.get("reason") or default_reason), source=str(r.get("source") or "NATIONAL_DB"),
                    is_hard_fail=hard,
                ))
        return hits


NAME_MATCH_THRESHOLD = 0.90


# Names never contain digits, so a digit in an OCR'd name is a misread letter.
_OCR_DIGIT_TO_LETTER = str.maketrans("0158", "OISB")


def normalize_watchlist_name(name: Optional[str]) -> str:
    """'Khan, Dawood' / 'DAWOOD  KHAN.' / 'DAW0OD KHAN' → 'DAWOOD KHAN' (letters only, uppercase,
    words sorted)."""
    words = re.sub(r"[^A-Z\u0900-\u097F ]", " ", (name or "").upper().translate(_OCR_DIGIT_TO_LETTER)).split()
    return " ".join(sorted(words))


def normalize_doc_number(number: Optional[str]) -> str:
    return re.sub(r"[^A-Z0-9]", "", (number or "").upper())
