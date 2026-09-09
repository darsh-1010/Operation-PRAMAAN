"""Database Connection and Persistence Module.

Provides connection handling for PostgreSQL 14+, with automatic fallback
to an in-memory SQLite store when running in offline/testing environments.
Supports transaction execution, candidate lookups, and screening audit logging.
"""

from __future__ import annotations
import logging
import os
import sqlite3
import uuid
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("db")


class DatabaseManager:
    """Manages PostgreSQL connection with transparent SQLite fallback."""

    _instance: Optional["DatabaseManager"] = None

    def __init__(self) -> None:
        self.is_postgres = False
        self._pg_conn = None
        self._sqlite_conn: Optional[sqlite3.Connection] = None
        self._init_connection()

    @classmethod
    def get_instance(cls) -> "DatabaseManager":
        """Retrieve database manager singleton."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _init_connection(self) -> None:
        """Attempt PostgreSQL connection or fallback to SQLite."""
        db_url = os.environ.get("DATABASE_URL")
        host = os.environ.get("POSTGRES_HOST", "localhost")
        port = os.environ.get("POSTGRES_PORT", "5432")
        db = os.environ.get("POSTGRES_DB", "postgres")
        user = os.environ.get("POSTGRES_USER", "postgres")
        pwd = os.environ.get("POSTGRES_PASSWORD", "Aarya")

        try:
            import psycopg2
            if db_url:
                conn = psycopg2.connect(db_url, connect_timeout=3)
            else:
                conn = psycopg2.connect(
                    host=host, port=port, dbname=db, user=user, password=pwd, connect_timeout=3
                )
            conn.autocommit = True
            self._pg_conn = conn
            self.is_postgres = True
            logger.info("Connected to PostgreSQL database '%s' at %s:%s.", db, host, port)
        except Exception as err:
            logger.warning("PostgreSQL connection unavailable (%s). Initializing SQLite in-memory fallback.", err)
            self.is_postgres = False
            self._sqlite_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._sqlite_conn.row_factory = sqlite3.Row
            self._init_sqlite_schema()

    def _init_sqlite_schema(self) -> None:
        """Create reference tables in SQLite fallback environment."""
        cur = self._sqlite_conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS ground_truth_records (
                record_id TEXT PRIMARY KEY,
                doc_type TEXT NOT NULL,
                id_number TEXT NOT NULL,
                full_name TEXT NOT NULL,
                dob TEXT NOT NULL,
                gender TEXT,
                issue_date TEXT,
                expiry_date TEXT,
                issuing_country TEXT DEFAULT 'IND',
                status TEXT DEFAULT 'ACTIVE'
            );

            CREATE TABLE IF NOT EXISTS watchlist_entries (
                entry_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                doc_number TEXT,
                full_name TEXT,
                dob TEXT,
                nationality TEXT,
                reason TEXT,
                source TEXT,
                active INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS watchlist_hits (
                hit_id TEXT PRIMARY KEY,
                session_id TEXT,
                document_id TEXT,
                entry_id TEXT,
                match_basis TEXT,
                match_score REAL,
                is_hard_fail INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS validation_checks (
                check_id TEXT PRIMARY KEY,
                document_id TEXT,
                module TEXT DEFAULT 'MODULE_1',
                check_type TEXT,
                field_key TEXT,
                status TEXT,
                is_hard_fail INTEGER DEFAULT 0,
                expected_value TEXT,
                observed_value TEXT,
                detail TEXT
            );

            CREATE TABLE IF NOT EXISTS module_scores (
                score_id TEXT PRIMARY KEY,
                session_id TEXT,
                score_kind TEXT,
                value REAL,
                detail TEXT
            );

            CREATE TABLE IF NOT EXISTS reason_codes (
                reason_id TEXT PRIMARY KEY,
                assessment_id TEXT,
                code TEXT,
                message TEXT,
                severity TEXT,
                contribution REAL
            );

            -- Sample seed data for testing
            INSERT OR IGNORE INTO ground_truth_records 
                (record_id, doc_type, id_number, full_name, dob, gender, issue_date, expiry_date, status)
            VALUES
                ('g1', 'PASSPORT', 'P1234567', 'SHARMA, ARYA', '1995-08-15', 'M', '2020-01-10', '2030-01-09', 'ACTIVE'),
                ('g2', 'PASSPORT', 'L898902C', 'ERIKSSON, ANNA MARIA', '1974-08-12', 'F', '2019-01-01', '2029-01-01', 'ACTIVE'),
                ('g3', 'PASSPORT', 'R9999999', 'SINGH, VIKRAM', '1985-04-12', 'M', '2018-02-15', '2028-02-14', 'REVOKED'),
                ('g4', 'PASSPORT', 'E1111111', 'GUPTA, PRIYA', '1988-06-30', 'F', '2012-07-01', '2022-06-30', 'EXPIRED'),
                ('g5', 'NATIONAL_ID', '987654321012', 'KUMAR, ROHIT', '1990-11-20', 'M', '2015-05-01', '2035-05-01', 'ACTIVE');

            INSERT OR IGNORE INTO watchlist_entries 
                (entry_id, kind, doc_number, full_name, dob, nationality, reason, source, active)
            VALUES
                ('w1', 'BLACKLIST_DOC', 'B6666666', 'KHAN, DAWOOD', '1975-12-26', 'IND', 'Fraudulent Passport Flagged by CBI', 'NATIONAL_DB', 1),
                ('w2', 'LOST_STOLEN', 'S5555555', 'BROWN, DAVID', '1982-05-14', 'GBR', 'Stolen passport reported to Interpol SLTD', 'INTERPOL_SLTD', 1),
                ('w3', 'BLACKLIST_PERSON', NULL, 'MALIK, TARIQ', '1979-03-25', 'IND', 'High-risk security watchlist', 'INTERPOL', 1);
        """)
        self._sqlite_conn.commit()

    def query(self, sql: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
        """Execute a SELECT query and return rows as dictionaries."""
        if self.is_postgres and self._pg_conn is not None:
            try:
                import psycopg2.extras
                with self._pg_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
                    cur.execute(sql, params)
                    rows = cur.fetchall()
                    return [dict(r) for r in rows]
            except Exception as err:
                logger.error("Postgres query failed (%s). Reverting query to fallback.", err)

        # Fallback SQLite query
        cur = self._sqlite_conn.cursor()
        # Convert Postgres %s parameter syntax to SQLite ? if needed
        sql_converted = sql.replace("%s", "?")
        cur.execute(sql_converted, params)
        rows = cur.fetchall()
        return [dict(r) for r in rows]

    def execute(self, sql: str, params: Tuple[Any, ...] = ()) -> None:
        """Execute an INSERT/UPDATE statement."""
        if self.is_postgres and self._pg_conn is not None:
            try:
                with self._pg_conn.cursor() as cur:
                    cur.execute(sql, params)
                return
            except Exception as err:
                logger.error("Postgres execute failed: %s", err)

        cur = self._sqlite_conn.cursor()
        sql_converted = sql.replace("%s", "?")
        cur.execute(sql_converted, params)
        self._sqlite_conn.commit()

