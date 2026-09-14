"""Database persistence for Module 3 — Biometric Matching.

Same shape as ../../ocr-consistency-check/db.py (PostgreSQL 14+, with a transparent
in-memory SQLite fallback when Postgres isn't reachable) — duplicated rather than shared,
per CLAUDE.md's cross-service-contract-not-imports rule. Self-provisions its one table on
connect; see that file's _init_postgres_schema for why there's no separate migration tool.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from typing import Optional

logger = logging.getLogger(__name__)

_SCHEMA = """
    CREATE TABLE IF NOT EXISTS biometric_results (
        result_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        score INTEGER NOT NULL,
        hard_fail INTEGER NOT NULL DEFAULT 0,
        reason_codes TEXT NOT NULL,
        documents_checked TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
"""


class BiometricDB:
    """Manages the PostgreSQL connection, with a SQLite in-memory fallback for local dev."""

    _instance: Optional["BiometricDB"] = None

    def __init__(self) -> None:
        self.is_postgres = False
        self._pg_conn = None
        self._sqlite_conn: Optional[sqlite3.Connection] = None
        self._connect()

    @classmethod
    def get_instance(cls) -> "BiometricDB":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _connect(self) -> None:
        db_url = os.environ.get("DATABASE_URL", "").strip()
        host = os.environ.get("POSTGRES_HOST", "localhost")
        port = os.environ.get("POSTGRES_PORT", "5432")
        db = os.environ.get("POSTGRES_DB", "postgres")
        user = os.environ.get("POSTGRES_USER", "postgres")
        pwd = os.environ.get("POSTGRES_PASSWORD", "postgres")

        try:
            import psycopg2
            if db_url:
                conn = psycopg2.connect(db_url, connect_timeout=3)
            else:
                conn = psycopg2.connect(host=host, port=port, dbname=db, user=user, password=pwd, connect_timeout=3)
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute(_SCHEMA)
            self._pg_conn = conn
            self.is_postgres = True
            logger.info("Connected to PostgreSQL database '%s' at %s:%s.", db, host, port)
        except Exception as err:
            logger.warning("PostgreSQL connection unavailable (%s). Initializing SQLite in-memory fallback.", err)
            self.is_postgres = False
            self._sqlite_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._sqlite_conn.executescript(_SCHEMA)
            self._sqlite_conn.commit()

    def save_result(self, result_id: str, session_id: str, score: int, hard_fail: bool, reason_codes: list[str], documents_checked: list[str]) -> None:
        """Best-effort persistence — a DB outage must never break /screen's response to the
        frontend, so failures are logged and swallowed rather than raised."""
        sql = """
            INSERT INTO biometric_results (result_id, session_id, score, hard_fail, reason_codes, documents_checked)
            VALUES (%s, %s, %s, %s, %s, %s)
        """
        params = (result_id, session_id, score, int(hard_fail), json.dumps(reason_codes), json.dumps(documents_checked))
        try:
            if self.is_postgres and self._pg_conn is not None:
                with self._pg_conn.cursor() as cur:
                    cur.execute(sql, params)
            else:
                cur = self._sqlite_conn.cursor()
                cur.execute(sql.replace("%s", "?"), params)
                self._sqlite_conn.commit()
        except Exception as err:
            logger.error("Failed to persist biometric result for session=%s: %s", session_id, err)
