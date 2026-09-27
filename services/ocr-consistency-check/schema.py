"""Module 1's database schema, self-provisioned on connect (db.py) — the same pattern as
risk-scoring-engine and biometric-matching.

Until this file existed the schema lived nowhere in the repo: db_repository.py targeted a
"migration schema" (Postgres enums session_status / document_type / capture_kind / check_status)
that was never committed, while deployed databases carried an older layout (TEXT ids with no
default, 0/1 INTEGER flags, no created_at). Every OCR write failed against both.

Compatibility rules, so an existing database keeps all its data and every reader keeps working:
  * only CREATE ... IF NOT EXISTS, ADD COLUMN IF NOT EXISTS and SET DEFAULT — nothing is ever
    dropped, renamed or retyped;
  * types follow the deployed layout (TEXT ids, INTEGER 0/1 flags, TEXT dates — Aadhaar often
    carries only a year of birth, which a DATE column would reject);
  * ids default to gen_random_uuid() (built into Postgres 13+).
"""
from __future__ import annotations

_ID = "TEXT PRIMARY KEY DEFAULT gen_random_uuid()::text"
_TS = "TIMESTAMPTZ DEFAULT now()"

TABLES = [
    f"""CREATE TABLE IF NOT EXISTS screening_sessions (
        session_id TEXT PRIMARY KEY, status TEXT, pipeline_version TEXT, started_at {_TS})""",
    f"""CREATE TABLE IF NOT EXISTS documents (
        document_id TEXT PRIMARY KEY, session_id TEXT, doc_type TEXT, issuing_country TEXT,
        document_number TEXT, claimed_name TEXT, claimed_dob TEXT, claimed_expiry TEXT,
        claimed_gender TEXT, uploaded_at {_TS})""",
    f"""CREATE TABLE IF NOT EXISTS captures (
        capture_id {_ID}, session_id TEXT, document_id TEXT, kind TEXT, storage_uri TEXT, sha256 TEXT,
        mime_type TEXT, width_px INTEGER, height_px INTEGER, captured_at {_TS})""",
    f"""CREATE TABLE IF NOT EXISTS ocr_extractions (
        extraction_id TEXT PRIMARY KEY, document_id TEXT, engine TEXT, model_version TEXT, mrz_raw TEXT,
        overall_confidence REAL, created_at {_TS})""",
    f"""CREATE TABLE IF NOT EXISTS extracted_fields (
        field_id {_ID}, extraction_id TEXT, document_id TEXT, field_key TEXT, field_value TEXT, source TEXT,
        confidence REAL, bbox TEXT, created_at {_TS})""",
    f"""CREATE TABLE IF NOT EXISTS validation_checks (
        check_id {_ID}, document_id TEXT, module TEXT DEFAULT 'MODULE_1', check_type TEXT, field_key TEXT,
        status TEXT, is_hard_fail INTEGER DEFAULT 0, expected_value TEXT, observed_value TEXT, detail TEXT,
        created_at {_TS})""",
    """CREATE TABLE IF NOT EXISTS watchlist_entries (
        entry_id TEXT PRIMARY KEY, kind TEXT NOT NULL, doc_number TEXT, full_name TEXT, dob TEXT,
        nationality TEXT, reason TEXT, source TEXT, active INTEGER DEFAULT 1)""",
    f"""CREATE TABLE IF NOT EXISTS watchlist_hits (
        hit_id {_ID}, session_id TEXT, document_id TEXT, entry_id TEXT, match_basis TEXT, match_score REAL,
        is_hard_fail INTEGER DEFAULT 0, created_at {_TS})""",
    f"""CREATE TABLE IF NOT EXISTS module_scores (
        score_id {_ID}, session_id TEXT, score_kind TEXT, value REAL, detail TEXT, created_at {_TS})""",
    """CREATE TABLE IF NOT EXISTS ground_truth_records (
        record_id TEXT PRIMARY KEY, doc_type TEXT NOT NULL, id_number TEXT NOT NULL, full_name TEXT NOT NULL,
        dob TEXT NOT NULL, gender TEXT, issue_date TEXT, expiry_date TEXT, issuing_country TEXT DEFAULT 'IND',
        status TEXT DEFAULT 'ACTIVE')""",
    f"""CREATE TABLE IF NOT EXISTS audit_log (
        audit_id {_ID}, session_id TEXT, actor_type TEXT, action TEXT, entity_type TEXT, entity_id TEXT,
        payload TEXT, created_at {_TS})""",
]

# Brings tables created by the older layout up to what db_repository.py writes. Harmless no-ops
# on a database created from TABLES above.
UPGRADES = [
    "ALTER TABLE validation_checks ALTER COLUMN check_id SET DEFAULT gen_random_uuid()::text",
    "ALTER TABLE watchlist_hits ALTER COLUMN hit_id SET DEFAULT gen_random_uuid()::text",
    "ALTER TABLE module_scores ALTER COLUMN score_id SET DEFAULT gen_random_uuid()::text",
    f"ALTER TABLE validation_checks ADD COLUMN IF NOT EXISTS created_at {_TS}",
    f"ALTER TABLE watchlist_hits ADD COLUMN IF NOT EXISTS created_at {_TS}",
    f"ALTER TABLE module_scores ADD COLUMN IF NOT EXISTS created_at {_TS}",
    # upsert_module_score's ON CONFLICT (session_id, score_kind) needs this.
    "CREATE UNIQUE INDEX IF NOT EXISTS module_scores_session_kind ON module_scores (session_id, score_kind)",
    "CREATE INDEX IF NOT EXISTS documents_session ON documents (session_id)",
    "CREATE INDEX IF NOT EXISTS validation_checks_document ON validation_checks (document_id)",
]


def apply(cursor) -> None:
    """Idempotent: safe on every start, from every worker (caller holds an advisory lock)."""
    for statement in TABLES + UPGRADES:
        cursor.execute(statement)
