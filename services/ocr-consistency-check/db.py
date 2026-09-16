"""Database Connection and Persistence Manager."""

from __future__ import annotations
import logging
import os
from typing import Any, Dict, List, Optional, Tuple
import psycopg2
import psycopg2.extras
from db_repository import DbRepositoryMixin

logger = logging.getLogger("db")


class DatabaseManager(DbRepositoryMixin):
    """PostgreSQL connection singleton with typed Module-1 repository methods."""

    _instance: Optional["DatabaseManager"] = None

    def __init__(self) -> None:
        self._conn = self._connect()

    @classmethod
    def get_instance(cls) -> "DatabaseManager":
        """Return the module-level singleton, creating it on first call."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _connect(self) -> psycopg2.extensions.connection:
        """Open a PostgreSQL connection from environment variables."""
        db_url = os.environ.get("DATABASE_URL")
        host = os.environ.get("POSTGRES_HOST", "localhost")
        port = os.environ.get("POSTGRES_PORT", "5432")
        db = os.environ.get("POSTGRES_DB", "postgres")
        user = os.environ.get("POSTGRES_USER", "postgres")
        pwd = os.environ.get("POSTGRES_PASSWORD", "Aarya")

        try:
            if db_url:
                conn = psycopg2.connect(db_url, connect_timeout=5)
            else:
                conn = psycopg2.connect(host=host, port=port, dbname=db, user=user, password=pwd, connect_timeout=5)
            conn.autocommit = True
            logger.info("Connected to PostgreSQL '%s' at %s:%s.", db, host, port)
            return conn
        except Exception as err:
            raise RuntimeError(f"PostgreSQL connection failed — cannot start without a database: {err}") from err

    @property
    def is_postgres(self) -> bool:
        """Always True — kept for backward-compat with health-check response."""
        return True

    def query(self, sql: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
        """Execute a SELECT and return rows as plain dicts."""
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def execute(self, sql: str, params: Tuple[Any, ...] = ()) -> None:
        """Execute an INSERT / UPDATE / DELETE."""
        with self._conn.cursor() as cur:
            cur.execute(sql, params)
