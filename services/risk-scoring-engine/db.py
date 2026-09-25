"""Database persistence for the Risk Scoring Engine's final decisions.

Same shape as ocr-consistency-check/db.py and biometric-matching/app/db.py (PostgreSQL 14+,
with an in-memory SQLite fallback) — duplicated rather than shared, per CLAUDE.md's
cross-service-contract-not-imports rule. Self-provisions its tables on connect.

Every finalized uuid — a normal PASS/MANUAL_REVIEW/FAIL, a hard-fail REJECT, or a timeout
escalation — gets one row here. store.py's Redis copy is what GET /result/{uuid} reads (fast,
24h TTL); this table is the durable audit copy. Each row also carries the exact canonical JSON
that was hashed into its blockchain leaf (see ledger.py / LEDGER.md), and anchor_batches
records which Merkle root on which chain covers it.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator, Optional

from prometheus_client import Counter

logger = logging.getLogger("db")

PERSIST_FAILURES = Counter(
    "praman_audit_persist_failures_total",
    "Finalized decisions that could NOT be written to the audit table (so will never be anchored).",
)

# Portable across Postgres and SQLite: no SERIAL — batch ids are assigned by anchor.py while it
# holds the anchor lock, so there is only ever one writer.
_SCHEMA = [
    """CREATE TABLE IF NOT EXISTS risk_results (
        result_id TEXT PRIMARY KEY,
        session_id TEXT NOT NULL,
        score REAL,
        decision TEXT NOT NULL,
        hard_fail INTEGER NOT NULL DEFAULT 0,
        timed_out INTEGER NOT NULL DEFAULT 0,
        reasons TEXT NOT NULL,
        finalized_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        canonical TEXT,
        leaf_hash TEXT,
        batch_id BIGINT,
        leaf_index INTEGER
    )""",
    """CREATE TABLE IF NOT EXISTS anchor_batches (
        batch_id BIGINT PRIMARY KEY,
        merkle_root TEXT NOT NULL UNIQUE,
        leaf_count INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING',
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        tx_hash TEXT,
        block_number BIGINT,
        chain_id BIGINT,
        contract_address TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        confirmed_at TIMESTAMP
    )""",
    "CREATE INDEX IF NOT EXISTS idx_risk_results_session ON risk_results (session_id)",
    "CREATE INDEX IF NOT EXISTS idx_risk_results_batch ON risk_results (batch_id)",
]

# Tables created before the ledger existed (a persisted Postgres volume) lack these columns.
_PG_MIGRATIONS = [
    "ALTER TABLE risk_results ADD COLUMN IF NOT EXISTS canonical TEXT",
    "ALTER TABLE risk_results ADD COLUMN IF NOT EXISTS leaf_hash TEXT",
    "ALTER TABLE risk_results ADD COLUMN IF NOT EXISTS batch_id BIGINT",
    "ALTER TABLE risk_results ADD COLUMN IF NOT EXISTS leaf_index INTEGER",
]


class _SqliteCursor:
    """Lets callers write Postgres-style %s placeholders against SQLite too."""

    def __init__(self, cur: sqlite3.Cursor) -> None:
        self._cur = cur

    def execute(self, sql: str, params: tuple = ()) -> None:
        self._cur.execute(sql.replace("%s", "?"), params)

    def fetchone(self):
        return self._cur.fetchone()

    def fetchall(self):
        return self._cur.fetchall()


class RiskResultDB:
    """Manages the PostgreSQL connection, with a SQLite in-memory fallback for local dev."""

    _instance: Optional["RiskResultDB"] = None

    def __init__(self) -> None:
        self.is_postgres = False
        self._pg_pool = None
        self._sqlite_conn: Optional[sqlite3.Connection] = None
        self._sqlite_lock = threading.RLock()
        self._local_mutex = threading.Lock()  # try_lock()'s SQLite stand-in; never held by writes
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
                    # WEB_CONCURRENCY workers each call _connect() independently at startup —
                    # an advisory lock serializes "CREATE TABLE IF NOT EXISTS" across them.
                    # Without it, two processes racing on the same DDL can both pass the
                    # existence check and hit Postgres's own internal duplicate-catalog-row
                    # error (not "already exists" — a genuine race, IF NOT EXISTS isn't atomic
                    # across concurrent sessions).
                    cur.execute("SELECT pg_advisory_lock(hashtext('risk_scoring_engine_schema'))")
                    try:
                        for stmt in _SCHEMA[:1] + _PG_MIGRATIONS + _SCHEMA[1:]:
                            cur.execute(stmt)
                    finally:
                        cur.execute("SELECT pg_advisory_unlock(hashtext('risk_scoring_engine_schema'))")
            finally:
                pool.putconn(conn)
            self._pg_pool = pool
            self.is_postgres = True
            logger.info("Connected to PostgreSQL database '%s' at %s:%s (pool size %s).", db, host, port, pool_size)
        except Exception as err:
            logger.warning("PostgreSQL connection unavailable (%s). Initializing SQLite in-memory fallback.", err)
            self.is_postgres = False
            self._sqlite_conn = sqlite3.connect(":memory:", check_same_thread=False)
            for stmt in _SCHEMA:
                self._sqlite_conn.execute(stmt)
            self._sqlite_conn.commit()

    @contextmanager
    def transaction(self) -> Iterator:
        """One cursor inside one transaction: commit on success, rollback on any error.
        SQL is written with %s placeholders for both backends."""
        if self.is_postgres:
            conn = self._pg_pool.getconn()
            try:
                conn.autocommit = False
                with conn.cursor() as cur:
                    yield cur
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                self._pg_pool.putconn(conn)
            return
        with self._sqlite_lock:
            try:
                yield _SqliteCursor(self._sqlite_conn.cursor())
                self._sqlite_conn.commit()
            except Exception:
                self._sqlite_conn.rollback()
                raise

    @contextmanager
    def try_lock(self, name: str) -> Iterator[bool]:
        """Cross-process mutex (Postgres session advisory lock) held for the whole block.
        Yields False without waiting if another worker/replica already holds it. SQLite is
        per-process anyway, so a thread lock is enough there."""
        if not self.is_postgres:
            got = self._local_mutex.acquire(blocking=False)
            try:
                yield got
            finally:
                if got:
                    self._local_mutex.release()
            return
        conn = self._pg_pool.getconn()
        try:
            conn.autocommit = True
            with conn.cursor() as cur:
                cur.execute("SELECT pg_try_advisory_lock(hashtext(%s))", (name,))
                got = bool(cur.fetchone()[0])
                try:
                    yield got
                finally:
                    if got:
                        cur.execute("SELECT pg_advisory_unlock(hashtext(%s))", (name,))
        finally:
            self._pg_pool.putconn(conn)

    def save_risk_result(self, record: dict, canonical: str, leaf_hash_hex: str) -> None:
        """Best-effort persistence — a DB outage must never break the risk engine's own
        response to the module that's waiting on it. Failures are logged AND counted in
        praman_audit_persist_failures_total: such a decision has no audit row, so it can never
        be anchored or verified — alert on that metric being non-zero."""
        sql = """
            INSERT INTO risk_results (result_id, session_id, score, decision, hard_fail, timed_out,
                                      reasons, finalized_at, canonical, leaf_hash)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """
        params = (
            record["result_id"], record["uuid"], record["score"], record["decision"],
            int(record["hard_fail"]), int(record["timed_out"]), json.dumps(record["reasons"]),
            record["finalized_at"], canonical, leaf_hash_hex,
        )
        try:
            with self.transaction() as cur:
                cur.execute(sql, params)
        except Exception as err:
            PERSIST_FAILURES.inc()
            logger.error("AUDIT GAP: failed to persist risk result for session=%s: %s", record["uuid"], err)
