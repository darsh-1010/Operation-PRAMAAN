"""Database persistence for the Risk Scoring Engine's final decisions.

Same shape as ocr-consistency-check/db.py and biometric-matching/app/db.py (PostgreSQL 14+,
with an in-memory SQLite fallback) — duplicated rather than shared, per CLAUDE.md's
cross-service-contract-not-imports rule. Self-provisions its one table on connect.

Every finalized uuid — a normal PASS/MANUAL_REVIEW/FAIL, a hard-fail REJECT, or a timeout
escalation — gets one row here. store.py's in-memory _results dict is what GET /result/{uuid}
actually reads from (fast, no DB round-trip); this table is the durable audit copy of the
same thing, since store.py's own docstring already says an in-memory dict can't survive a
restart or a second instance.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from typing import Optional

logger = logging.getLogger("db")

_SCHEMA = """
    CREATE TABLE IF NOT EXISTS risk_results (
        result_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        score REAL,
        decision TEXT NOT NULL,
        hard_fail INTEGER NOT NULL DEFAULT 0,
        timed_out INTEGER NOT NULL DEFAULT 0,
        reasons TEXT NOT NULL,
        finalized_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
"""


class RiskResultDB:
    """Manages the PostgreSQL connection, with a SQLite in-memory fallback for local dev."""

    _instance: Optional["RiskResultDB"] = None

    def __init__(self) -> None:
        self.is_postgres = False
        self._pg_pool = None
        self._sqlite_conn: Optional[sqlite3.Connection] = None
        self._connect()

    @classmethod
    def get_instance(cls) -> "RiskResultDB":
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
        pool_size = int(os.environ.get("POSTGRES_POOL_SIZE", "5"))

        try:
            import psycopg2
            from psycopg2.pool import ThreadedConnectionPool

            dsn_kwargs = {"dsn": db_url} if db_url else dict(
                host=host, port=port, dbname=db, user=user, password=pwd
            )
            pool = ThreadedConnectionPool(1, pool_size, connect_timeout=3, **dsn_kwargs)
            conn = pool.getconn()
            try:
                conn.autocommit = True
                with conn.cursor() as cur:
                    cur.execute(_SCHEMA)
            finally:
                pool.putconn(conn)
            self._pg_pool = pool
            self.is_postgres = True
            logger.info("Connected to PostgreSQL database '%s' at %s:%s (pool size %s).", db, host, port, pool_size)
        except Exception as err:
            logger.warning("PostgreSQL connection unavailable (%s). Initializing SQLite in-memory fallback.", err)
            self.is_postgres = False
            self._sqlite_conn = sqlite3.connect(":memory:", check_same_thread=False)
            self._sqlite_conn.executescript(_SCHEMA)
            self._sqlite_conn.commit()

    def save_risk_result(self, result_id: str, session_id: str, score, decision: str, hard_fail: bool, timed_out: bool, reasons: list) -> None:
        """Best-effort persistence — a DB outage must never break the risk engine's own
        response to the module that's waiting on it, so failures are logged and swallowed."""
        sql = """
            INSERT INTO risk_results (result_id, session_id, score, decision, hard_fail, timed_out, reasons)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """
        params = (result_id, session_id, score, decision, int(hard_fail), int(timed_out), json.dumps(reasons))
        try:
            if self.is_postgres and self._pg_pool is not None:
                conn = self._pg_pool.getconn()
                try:
                    conn.autocommit = True
                    with conn.cursor() as cur:
                        cur.execute(sql, params)
                finally:
                    self._pg_pool.putconn(conn)
            else:
                cur = self._sqlite_conn.cursor()
                cur.execute(sql.replace("%s", "?"), params)
                self._sqlite_conn.commit()
        except Exception as err:
            logger.error("Failed to persist risk result for session=%s: %s", session_id, err)
