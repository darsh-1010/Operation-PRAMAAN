"""SQL for the blockchain ledger: carving unanchored decisions into Merkle batches, tracking
each batch's on-chain status, and reading back what /ledger/* needs. Storage only — the
hashing is ledger.py, the chain calls chain.py, the orchestration anchor.py."""
from __future__ import annotations

from typing import Optional

import ledger

_BATCH_COLS = ("batch_id", "merkle_root", "leaf_count", "status", "attempts", "last_error",
               "tx_hash", "block_number", "chain_id", "contract_address", "created_at", "confirmed_at")


def _batch_row(row) -> dict:
    out = dict(zip(_BATCH_COLS, row))
    for key in ("created_at", "confirmed_at"):
        if out[key] is not None and not isinstance(out[key], str):
            out[key] = out[key].isoformat()
    return out


def create_batch(db, max_leaves: int, chain_last_batch_id: int = 0) -> Optional[dict]:
    """Assigns up to max_leaves not-yet-batched decisions (oldest first) to a new PENDING
    batch and stores its Merkle root. Caller must hold the anchor lock (single writer).
    The id continues past whatever the chain has already seen, since the contract only accepts
    strictly sequential ids. Returns the new batch, or None when there is nothing to anchor."""
    with db.transaction() as cur:
        cur.execute(
            "SELECT result_id, canonical FROM risk_results "
            "WHERE batch_id IS NULL AND canonical IS NOT NULL "
            "ORDER BY finalized_at, result_id LIMIT %s",
            (max_leaves,),
        )
        rows = cur.fetchall()
        if not rows:
            return None
        root = ledger.merkle_root([ledger.leaf_hash(c) for _, c in rows]).hex()
        cur.execute("SELECT COALESCE(MAX(batch_id), 0) FROM anchor_batches")
        batch_id = max(int(cur.fetchone()[0]), chain_last_batch_id) + 1
        cur.execute(
            "INSERT INTO anchor_batches (batch_id, merkle_root, leaf_count, status) VALUES (%s, %s, %s, 'PENDING')",
            (batch_id, root, len(rows)),
        )
        for index, (result_id, _) in enumerate(rows):
            cur.execute(
                "UPDATE risk_results SET batch_id = %s, leaf_index = %s WHERE result_id = %s",
                (batch_id, index, result_id),
            )
    return get_batch(db, batch_id)


def pending_batches(db) -> list[dict]:
    with db.transaction() as cur:
        cur.execute(f"SELECT {', '.join(_BATCH_COLS)} FROM anchor_batches WHERE status = 'PENDING' ORDER BY batch_id")
        return [_batch_row(r) for r in cur.fetchall()]


def get_batch(db, batch_id: int) -> Optional[dict]:
    with db.transaction() as cur:
        cur.execute(f"SELECT {', '.join(_BATCH_COLS)} FROM anchor_batches WHERE batch_id = %s", (batch_id,))
        row = cur.fetchone()
    return _batch_row(row) if row else None


def recent_batches(db, limit: int) -> list[dict]:
    with db.transaction() as cur:
        cur.execute(f"SELECT {', '.join(_BATCH_COLS)} FROM anchor_batches ORDER BY batch_id DESC LIMIT %s", (limit,))
        return [_batch_row(r) for r in cur.fetchall()]


def mark_confirmed(db, batch_id: int, tx_hash: str, block_number: int, chain_id: int, contract: str) -> None:
    with db.transaction() as cur:
        cur.execute(
            "UPDATE anchor_batches SET status = 'CONFIRMED', tx_hash = %s, block_number = %s, chain_id = %s, "
            "contract_address = %s, last_error = NULL, confirmed_at = CURRENT_TIMESTAMP WHERE batch_id = %s",
            (tx_hash, block_number, chain_id, contract, batch_id),
        )


def set_tx_hash(db, batch_id: int, tx_hash: str) -> None:
    """Saved the moment a tx is broadcast, before waiting on it, so a crash mid-wait can
    still find it again."""
    with db.transaction() as cur:
        cur.execute("UPDATE anchor_batches SET tx_hash = %s WHERE batch_id = %s", (tx_hash, batch_id))


def mark_attempt_failed(db, batch_id: int, error: str) -> None:
    with db.transaction() as cur:
        cur.execute(
            "UPDATE anchor_batches SET attempts = attempts + 1, last_error = %s WHERE batch_id = %s",
            (error[:500], batch_id),
        )


def batch_canonicals(db, batch_id: int) -> list[tuple[str, int, str]]:
    """(result_id, leaf_index, canonical) for every decision in the batch, in leaf order."""
    with db.transaction() as cur:
        cur.execute(
            "SELECT result_id, leaf_index, canonical FROM risk_results WHERE batch_id = %s ORDER BY leaf_index",
            (batch_id,),
        )
        return [(r[0], r[1], r[2]) for r in cur.fetchall()]


def records_for_session(db, session_id: str) -> list[dict]:
    """Every audit row for a screening uuid, newest first (normally exactly one)."""
    with db.transaction() as cur:
        cur.execute(
            "SELECT result_id, session_id, score, decision, hard_fail, timed_out, reasons, canonical, "
            "leaf_hash, batch_id, leaf_index FROM risk_results WHERE session_id = %s "
            "ORDER BY finalized_at DESC, result_id",
            (session_id,),
        )
        cols = ("result_id", "session_id", "score", "decision", "hard_fail", "timed_out", "reasons",
                "canonical", "leaf_hash", "batch_id", "leaf_index")
        return [dict(zip(cols, r)) for r in cur.fetchall()]


def counts(db) -> dict:
    with db.transaction() as cur:
        cur.execute(
            "SELECT COUNT(*), SUM(CASE WHEN batch_id IS NULL AND canonical IS NOT NULL THEN 1 ELSE 0 END), "
            "SUM(CASE WHEN canonical IS NULL THEN 1 ELSE 0 END) FROM risk_results"
        )
        total, unbatched, legacy = cur.fetchone()
        cur.execute(
            "SELECT COUNT(*), SUM(CASE WHEN status = 'PENDING' THEN 1 ELSE 0 END) FROM anchor_batches"
        )
        batches, pending = cur.fetchone()
    return {"records": total or 0, "awaiting_batch": unbatched or 0, "legacy_unhashed": legacy or 0,
            "batches": batches or 0, "batches_pending": pending or 0}
