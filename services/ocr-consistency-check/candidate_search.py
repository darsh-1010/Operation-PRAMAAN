"""Candidate Document Search and Watchlist Screening.

Implements high-performance queries to find ground-truth candidate records
matching extracted ID credentials and screens against national/Interpol watchlists.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from db import DatabaseManager

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
            WHERE UPPER(TRIM(doc_type)) = %s AND UPPER(TRIM(id_number)) = %s
            LIMIT 5;
        """
        rows = self.db.query(sql, (doc_type.upper(), clean_id))

        # Query 2: If exact match empty and DOB is known, find candidates by (doc_type, dob)
        if not rows and dob:
            sql_fallback = """
                SELECT record_id, doc_type, id_number, full_name, dob, gender, issue_date, expiry_date, issuing_country, status
                FROM ground_truth_records
                WHERE UPPER(TRIM(doc_type)) = %s AND dob = %s
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
        logger.info("Candidate search for doc_type=%s, id_number=%s: %d result(s).", doc_type, id_number, len(candidates))
        return candidates

    def screen_watchlist(self, document_number: Optional[str], full_name: Optional[str], dob: Optional[str]) -> List[WatchlistHitResult]:
        """Screen extracted identity against active watchlists and blacklists."""
        hits: List[WatchlistHitResult] = []

        # Check 1: Document number match
        if document_number:
            clean_num = document_number.strip().upper()
            sql_doc = """
                SELECT entry_id, kind, doc_number, reason, source
                FROM watchlist_entries
                WHERE active = 1 AND UPPER(TRIM(doc_number)) = %s;
            """
            doc_rows = self.db.query(sql_doc, (clean_num,))
            for r in doc_rows:
                hits.append(WatchlistHitResult(
                    entry_id=str(r["entry_id"]),
                    kind=str(r["kind"]),
                    match_basis="DOC_NUMBER",
                    match_score=1.0,
                    reason=str(r.get("reason", "Watchlist document match")),
                    source=str(r.get("source", "NATIONAL_DB")),
                    is_hard_fail=True,
                ))

        # Check 2: Name and DOB match
        if full_name and dob:
            clean_name = full_name.strip().upper()
            sql_person = """
                SELECT entry_id, kind, full_name, reason, source
                FROM watchlist_entries
                WHERE active = 1 AND UPPER(TRIM(full_name)) = %s AND dob = %s;
            """
            person_rows = self.db.query(sql_person, (clean_name, dob))
            for r in person_rows:
                hits.append(WatchlistHitResult(
                    entry_id=str(r["entry_id"]),
                    kind=str(r["kind"]),
                    match_basis="NAME_DOB",
                    match_score=0.95,
                    reason=str(r.get("reason", "Watchlist person match by Name & DOB")),
                    source=str(r.get("source", "INTERPOL")),
                    is_hard_fail=True,
                ))

        if hits:
            logger.warning("Watchlist screening: %d hit(s) for doc_number=%s.", len(hits), document_number)
        else:
            logger.info("Watchlist screening: no hits for doc_number=%s.", document_number)
        return hits

