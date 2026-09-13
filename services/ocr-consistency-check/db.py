"""Database Connection and Persistence Module.

Provides a PostgreSQL 14+ connection singleton and typed repository methods
for every table that Module 1 (OCR & Consistency Check) writes to.

Table write ownership for Module 1:
    screening_sessions  – upsert_screening_session()
    documents           – insert_document()
    captures            – insert_capture()
    ocr_extractions     – insert_ocr_extraction()
    extracted_fields    – insert_extracted_field()
    validation_checks   – insert_validation_check()
    watchlist_hits      – insert_watchlist_hit()
    module_scores       – upsert_module_score()
    audit_log           – insert_audit_log()

Read-only tables (queried by candidate_search.py):
    ground_truth_records  – seeded once by migration scripts
    watchlist_entries     – maintained by admin / external feed, not by this service

No static seed data lives here. All document/capture rows are created at
runtime when a user uploads a file. Blacklist and registry data are already
present in the database from the migration scripts.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import psycopg2
import psycopg2.extras

logger = logging.getLogger("db")


class DatabaseManager:
    """PostgreSQL connection singleton with typed Module-1 repository methods.

    Fails loudly at startup if PostgreSQL is unreachable — no silent SQLite
    fallback, so missing data is never hidden behind an in-memory store.
    """

    _instance: Optional["DatabaseManager"] = None

    def __init__(self) -> None:
        self._conn = self._connect()

    # ------------------------------------------------------------------
    # Singleton factory
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls) -> "DatabaseManager":
        """Return the module-level singleton, creating it on first call."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _connect(self) -> psycopg2.extensions.connection:
        """Open a PostgreSQL connection from environment variables.

        Priority: DATABASE_URL env var → individual POSTGRES_* vars.
        Raises RuntimeError on failure so the FastAPI lifespan hook surfaces
        the problem immediately rather than silently degrading.
        """
        db_url = os.environ.get("DATABASE_URL")
        host = os.environ.get("POSTGRES_HOST", "localhost")
        port = os.environ.get("POSTGRES_PORT", "5432")
        db   = os.environ.get("POSTGRES_DB",   "postgres")
        user = os.environ.get("POSTGRES_USER", "postgres")
        pwd  = os.environ.get("POSTGRES_PASSWORD", "Aarya")

        try:
            if db_url:
                conn = psycopg2.connect(db_url, connect_timeout=5)
            else:
                conn = psycopg2.connect(
                    host=host, port=port, dbname=db,
                    user=user, password=pwd, connect_timeout=5,
                )
            conn.autocommit = True
            logger.info("Connected to PostgreSQL '%s' at %s:%s.", db, host, port)
            return conn
        except Exception as err:
            raise RuntimeError(
                f"PostgreSQL connection failed — cannot start without a database: {err}"
            ) from err

    # ------------------------------------------------------------------
    # Public compat property (used by health-check endpoint)
    # ------------------------------------------------------------------

    @property
    def is_postgres(self) -> bool:
        """Always True — kept for backward-compat with the health-check response."""
        return True

    # ------------------------------------------------------------------
    # Generic query helpers
    # ------------------------------------------------------------------

    def query(self, sql: str, params: Tuple[Any, ...] = ()) -> List[Dict[str, Any]]:
        """Execute a SELECT and return rows as plain dicts.

        Raises psycopg2.Error on any database problem — never swallows errors
        or falls back silently.
        """
        with self._conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return [dict(r) for r in cur.fetchall()]

    def execute(self, sql: str, params: Tuple[Any, ...] = ()) -> None:
        """Execute an INSERT / UPDATE / DELETE.

        Raises psycopg2.Error on failure.
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, params)

    # ------------------------------------------------------------------
    # Module-1 repository methods
    # Each method maps 1-to-1 to a table in the migration schema.
    # Rows are created at runtime per upload — no static data here.
    # ------------------------------------------------------------------

    def upsert_screening_session(
        self,
        session_id: str,
        pipeline_version: str = "v1.0.0",
        status: str = "PROCESSING",
    ) -> None:
        """Insert a new screening session, or update its status if it already exists.

        Called twice per upload: once at the start (PROCESSING) and once at
        the end (COMPLETED or FAILED).
        """
        self.execute(
            """
            INSERT INTO screening_sessions
                (session_id, status, pipeline_version, started_at)
            VALUES (%s, %s::session_status, %s, now())
            ON CONFLICT (session_id) DO UPDATE
                SET status = EXCLUDED.status;
            """,
            (session_id, status, pipeline_version),
        )
        logger.debug("Upserted screening_session %s → %s.", session_id, status)

    def insert_document(
        self,
        document_id: str,
        session_id: str,
        doc_type: str,
        document_number: Optional[str],
        claimed_name: Optional[str],
        claimed_dob: Optional[str],
        claimed_expiry: Optional[str],
        claimed_gender: Optional[str],
        issuing_country: Optional[str],
    ) -> None:
        """Insert the identity claim extracted from one uploaded document.

        Every row represents a real user-uploaded file, created at runtime.
        `claimed_*` fields come from OCR/MRZ extraction — they are what the
        document asserts, before any verification against the registry.
        """
        self.execute(
            """
            INSERT INTO documents
                (document_id, session_id, doc_type, issuing_country,
                 document_number, claimed_name, claimed_dob, claimed_expiry,
                 claimed_gender, uploaded_at)
            VALUES
                (%s, %s, %s::document_type, %s, %s, %s,
                 %s::date, %s::date, %s, now())
            ON CONFLICT (document_id) DO NOTHING;
            """,
            (
                document_id, session_id, doc_type, issuing_country,
                document_number, claimed_name,
                claimed_dob or None, claimed_expiry or None, claimed_gender,
            ),
        )
        logger.debug("Inserted document %s (type=%s).", document_id, doc_type)

    def insert_capture(
        self,
        session_id: str,
        document_id: str,
        kind: str,
        storage_uri: str,
        sha256: str,
        mime_type: Optional[str],
        width_px: Optional[int],
        height_px: Optional[int],
    ) -> str:
        """Insert file capture metadata and return the generated capture_id.

        The binary file is NOT stored in the database — only the storage path
        (S3 / MinIO URI or local path) and SHA-256 for integrity verification.
        Both are derived at runtime from the uploaded file bytes.
        """
        rows = self.query(
            """
            INSERT INTO captures
                (session_id, document_id, kind, storage_uri, sha256,
                 mime_type, width_px, height_px, captured_at)
            VALUES
                (%s, %s, %s::capture_kind, %s, %s, %s, %s, %s, now())
            RETURNING capture_id::text;
            """,
            (session_id, document_id, kind, storage_uri, sha256,
             mime_type, width_px, height_px),
        )
        capture_id: str = rows[0]["capture_id"]
        logger.debug("Inserted capture %s for document %s.", capture_id, document_id)
        return capture_id

    def insert_ocr_extraction(
        self,
        extraction_id: str,
        document_id: str,
        engine: str,
        model_version: str,
        mrz_raw: Optional[str],
        overall_confidence: float,
    ) -> None:
        """Insert OCR engine run metadata for reproducibility and forensic review.

        Records which model version produced the extraction so results can be
        re-evaluated if a model is updated or found to be inaccurate.
        """
        self.execute(
            """
            INSERT INTO ocr_extractions
                (extraction_id, document_id, engine, model_version,
                 mrz_raw, overall_confidence, created_at)
            VALUES
                (%s, %s, %s, %s, %s, %s, now())
            ON CONFLICT (extraction_id) DO NOTHING;
            """,
            (
                extraction_id, document_id, engine, model_version,
                mrz_raw, round(overall_confidence, 4),
            ),
        )

    def insert_extracted_field(
        self,
        extraction_id: str,
        document_id: str,
        field_key: str,
        field_value: Optional[str],
        source: str,
        confidence: float,
        bbox: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Insert one extracted key-value field from OCR output.

        One row per field per extraction. `source` distinguishes visual zone
        (VIZ), machine-readable zone (MRZ), or barcode. `bbox` lets the UI
        highlight exactly where on the document image the field was found.
        """
        self.execute(
            """
            INSERT INTO extracted_fields
                (extraction_id, document_id, field_key, field_value,
                 source, confidence, bbox, created_at)
            VALUES
                (%s, %s, %s, %s, %s, %s, %s::jsonb, now());
            """,
            (
                extraction_id, document_id, field_key, field_value,
                source, round(confidence, 4),
                json.dumps(bbox) if bbox else None,
            ),
        )

    def insert_validation_check(
        self,
        document_id: str,
        module: str,
        check_type: str,
        field_key: Optional[str],
        status: str,
        is_hard_fail: bool,
        expected_value: Optional[str],
        observed_value: Optional[str],
        detail: str,
    ) -> None:
        """Insert one deterministic validation check result.

        `module` must be 'MODULE_1', 'MODULE_2', or 'MODULE_3'.
        `check_type` examples: 'MRZ_CHECKSUM', 'FIELD_FORMAT',
        'BARCODE_CROSSCHECK', 'EXPIRY', 'ISSUER_RULE', 'WATCHLIST_LOOKUP'.
        """
        self.execute(
            """
            INSERT INTO validation_checks
                (document_id, module, check_type, field_key, status,
                 is_hard_fail, expected_value, observed_value, detail, created_at)
            VALUES
                (%s, %s, %s, %s, %s::check_status, %s, %s, %s, %s, now());
            """,
            (
                document_id, module, check_type, field_key,
                status, is_hard_fail,
                expected_value or None, observed_value or None, detail,
            ),
        )

    def insert_watchlist_hit(
        self,
        session_id: str,
        document_id: str,
        entry_id: str,
        match_basis: str,
        match_score: float,
        is_hard_fail: bool,
    ) -> None:
        """Insert a positive watchlist hit.

        Only called when `candidate_search.screen_watchlist()` returns a hit.
        `entry_id` is the UUID of the matching row in `watchlist_entries`
        (populated by migration / external feed, not by this service).
        `match_basis` must be 'DOC_NUMBER', 'NAME_DOB', or 'FACE'.
        """
        self.execute(
            """
            INSERT INTO watchlist_hits
                (session_id, document_id, entry_id, match_basis,
                 match_score, is_hard_fail, created_at)
            VALUES
                (%s, %s, %s, %s, %s, %s, now());
            """,
            (
                session_id, document_id, entry_id,
                match_basis, round(match_score, 4), is_hard_fail,
            ),
        )

    def upsert_module_score(
        self,
        session_id: str,
        score_kind: str,
        value: float,
        detail: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Insert or update the normalized module score (0.0–1.0).

        `score_kind` must be 'A' (OCR/text), 'B' (forensics), or 'C' (biometric).
        The UNIQUE(session_id, score_kind) constraint makes re-runs idempotent.
        The display layer multiplies by 100 to show an out-of-100 score to officers.
        """
        self.execute(
            """
            INSERT INTO module_scores
                (session_id, score_kind, value, detail, created_at)
            VALUES
                (%s, %s, %s, %s::jsonb, now())
            ON CONFLICT (session_id, score_kind) DO UPDATE
                SET value  = EXCLUDED.value,
                    detail = EXCLUDED.detail;
            """,
            (
                session_id, score_kind, round(value, 4),
                json.dumps(detail) if detail else None,
            ),
        )

    def insert_audit_log(
        self,
        session_id: str,
        action: str,
        entity_type: str,
        entity_id: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Append one system event to the immutable audit trail.

        `action` examples: 'OCR_RUN', 'WATCHLIST_HIT', 'DECISION_OVERRIDE'.
        The audit_log table is append-only — rows are never updated or deleted.
        """
        self.execute(
            """
            INSERT INTO audit_log
                (session_id, actor_type, action, entity_type, entity_id,
                 payload, created_at)
            VALUES
                (%s, 'SYSTEM', %s, %s, %s::uuid, %s::jsonb, now());
            """,
            (
                session_id, action, entity_type, entity_id,
                json.dumps(payload) if payload else None,
            ),
        )
