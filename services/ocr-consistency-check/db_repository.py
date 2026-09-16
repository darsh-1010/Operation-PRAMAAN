"""Repository mixin for Module 1 PostgreSQL database operations."""

from __future__ import annotations
import json
import logging
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("db")


class DbRepositoryMixin:
    """Methods for Module 1 table write operations."""

    execute: Callable[..., None]
    query: Callable[..., List[Dict[str, Any]]]

    def upsert_screening_session(self, session_id: str, pipeline_version: str = "v1.0.0", status: str = "PROCESSING") -> None:
        self.execute(
            """
            INSERT INTO screening_sessions (session_id, status, pipeline_version, started_at)
            VALUES (%s, %s::session_status, %s, now())
            ON CONFLICT (session_id) DO UPDATE SET status = EXCLUDED.status;
            """,
            (session_id, status, pipeline_version),
        )

    def insert_document(
        self, document_id: str, session_id: str, doc_type: str, document_number: Optional[str],
        claimed_name: Optional[str], claimed_dob: Optional[str], claimed_expiry: Optional[str],
        claimed_gender: Optional[str], issuing_country: Optional[str],
    ) -> None:
        self.execute(
            """
            INSERT INTO documents (document_id, session_id, doc_type, issuing_country,
                 document_number, claimed_name, claimed_dob, claimed_expiry, claimed_gender, uploaded_at)
            VALUES (%s, %s, %s::document_type, %s, %s, %s, %s::date, %s::date, %s, now())
            ON CONFLICT (document_id) DO NOTHING;
            """,
            (document_id, session_id, doc_type, issuing_country, document_number, claimed_name, claimed_dob or None, claimed_expiry or None, claimed_gender),
        )

    def insert_capture(
        self, session_id: str, document_id: str, kind: str, storage_uri: str,
        sha256: str, mime_type: Optional[str], width_px: Optional[int], height_px: Optional[int],
    ) -> str:
        rows = self.query(
            """
            INSERT INTO captures (session_id, document_id, kind, storage_uri, sha256, mime_type, width_px, height_px, captured_at)
            VALUES (%s, %s, %s::capture_kind, %s, %s, %s, %s, %s, now()) RETURNING capture_id::text;
            """,
            (session_id, document_id, kind, storage_uri, sha256, mime_type, width_px, height_px),
        )
        return str(rows[0]["capture_id"])

    def insert_ocr_extraction(
        self, extraction_id: str, document_id: str, engine: str, model_version: str, mrz_raw: Optional[str], overall_confidence: float,
    ) -> None:
        self.execute(
            """
            INSERT INTO ocr_extractions (extraction_id, document_id, engine, model_version, mrz_raw, overall_confidence, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, now()) ON CONFLICT (extraction_id) DO NOTHING;
            """,
            (extraction_id, document_id, engine, model_version, mrz_raw, round(overall_confidence, 4)),
        )

    def insert_extracted_field(
        self, extraction_id: str, document_id: str, field_key: str, field_value: Optional[str],
        source: str, confidence: float, bbox: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.execute(
            """
            INSERT INTO extracted_fields (extraction_id, document_id, field_key, field_value, source, confidence, bbox, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, now());
            """,
            (extraction_id, document_id, field_key, field_value, source, round(confidence, 4), json.dumps(bbox) if bbox else None),
        )

    def insert_validation_check(
        self, document_id: str, module: str, check_type: str, field_key: Optional[str],
        status: str, is_hard_fail: bool, expected_value: Optional[str], observed_value: Optional[str], detail: str,
    ) -> None:
        self.execute(
            """
            INSERT INTO validation_checks (document_id, module, check_type, field_key, status, is_hard_fail, expected_value, observed_value, detail, created_at)
            VALUES (%s, %s, %s, %s, %s::check_status, %s, %s, %s, %s, now());
            """,
            (document_id, module, check_type, field_key, status, is_hard_fail, expected_value or None, observed_value or None, detail),
        )

    def insert_watchlist_hit(
        self, session_id: str, document_id: str, entry_id: str, match_basis: str, match_score: float, is_hard_fail: bool,
    ) -> None:
        self.execute(
            """
            INSERT INTO watchlist_hits (session_id, document_id, entry_id, match_basis, match_score, is_hard_fail, created_at)
            VALUES (%s, %s, %s, %s, %s, %s, now());
            """,
            (session_id, document_id, entry_id, match_basis, round(match_score, 4), is_hard_fail),
        )

    def upsert_module_score(self, session_id: str, score_kind: str, value: float, detail: Optional[Dict[str, Any]] = None) -> None:
        self.execute(
            """
            INSERT INTO module_scores (session_id, score_kind, value, detail, created_at)
            VALUES (%s, %s, %s, %s::jsonb, now())
            ON CONFLICT (session_id, score_kind) DO UPDATE SET value = EXCLUDED.value, detail = EXCLUDED.detail;
            """,
            (session_id, score_kind, round(value, 4), json.dumps(detail) if detail else None),
        )

    def insert_audit_log(
        self, session_id: str, action: str, entity_type: str, entity_id: str, payload: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.execute(
            """
            INSERT INTO audit_log (session_id, actor_type, action, entity_type, entity_id, payload, created_at)
            VALUES (%s, 'SYSTEM', %s, %s, %s::uuid, %s::jsonb, now());
            """,
            (session_id, action, entity_type, entity_id, json.dumps(payload) if payload else None),
        )
