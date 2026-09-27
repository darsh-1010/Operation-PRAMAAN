"""GET /ledger/* — read-only endpoints that let anyone check a decision against the chain.

/ledger/verify/{uuid} re-derives everything from scratch rather than trusting any stored
"verified" flag: re-hash the stored record, rebuild its batch's Merkle root from every record
in the batch, then compare with the root the CHAIN holds for that batch id. Each step is
returned as a named check so the UI can show exactly where a chain of custody breaks.
"""
from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

import anchor
import ledger
import ledger_db
from db import RiskResultDB

router = APIRouter(prefix="/ledger", tags=["ledger"])

Status = Literal["VERIFIED", "TAMPERED", "PENDING", "LEGACY_UNSEALED", "CHAIN_UNAVAILABLE"]


class Check(BaseModel):
    name: str
    ok: Optional[bool]  # None = couldn't be evaluated yet (not batched / not anchored / chain down)
    detail: str


class ProofStep(BaseModel):
    side: Literal["L", "R"]
    hash: str


class VerifyResponse(BaseModel):
    uuid: str
    status: Status
    summary: str
    checks: List[Check]
    record: Optional[dict] = None
    leaf_hash: Optional[str] = None
    batch_id: Optional[int] = None
    leaf_index: Optional[int] = None
    leaf_count: Optional[int] = None
    merkle_root: Optional[str] = None
    proof: List[ProofStep] = []
    chain_id: Optional[int] = None
    contract_address: Optional[str] = None
    tx_hash: Optional[str] = None
    block_number: Optional[int] = None
    anchored_at: Optional[str] = None
    tx_url: Optional[str] = None


def _row_matches(row: dict, doc: dict) -> list[str]:
    """Plain columns vs. the sealed canonical record. Catches the classic insider edit:
    `UPDATE risk_results SET decision = 'PASS'` without touching the hashed copy."""
    diffs = []
    if row["session_id"] != doc["uuid"]:
        diffs.append("uuid")
    if row["decision"] != doc["decision"]:
        diffs.append(f"decision (row says {row['decision']}, sealed {doc['decision']})")
    if bool(row["hard_fail"]) != doc["hard_fail"]:
        diffs.append("hard_fail")
    if bool(row["timed_out"]) != doc["timed_out"]:
        diffs.append("timed_out")
    if json.loads(row["reasons"]) != doc["reasons"]:
        diffs.append("reasons")
    a, b = row["score"], doc["score"]
    if (a is None) != (b is None) or (a is not None and not math.isclose(a, b, rel_tol=1e-5, abs_tol=1e-3)):
        diffs.append(f"score (row says {a}, sealed {b})")  # tolerance: Postgres REAL is float4
    return diffs


def verify_record(db, chain, uuid: str) -> VerifyResponse:
    rows = ledger_db.records_for_session(db, uuid)
    if not rows:
        raise HTTPException(status_code=404, detail="No audit record for this uuid")
    row = rows[0]
    checks = [Check(name="Decision recorded", ok=True, detail=f"audit row {row['result_id']}")]
    out = VerifyResponse(uuid=uuid, status="PENDING", summary="", checks=checks)

    if row["canonical"] is None:
        out.status, out.summary = "LEGACY_UNSEALED", "Recorded before blockchain sealing was enabled — cannot be verified."
        return out  # only the first check applies; the constructor's copy is complete

    doc = json.loads(row["canonical"])
    out.record = doc
    diffs = _row_matches(row, doc)
    checks.append(Check(name="Row matches sealed record", ok=not diffs,
                        detail="all fields match" if not diffs else "changed after sealing: " + ", ".join(diffs)))

    leaf = ledger.leaf_hash(row["canonical"])
    out.leaf_hash = leaf.hex()
    checks.append(Check(name="Fingerprint (SHA-256 leaf)", ok=row["leaf_hash"] == leaf.hex(),
                        detail=leaf.hex() if row["leaf_hash"] == leaf.hex() else "stored fingerprint does not match record"))

    if row["batch_id"] is None:
        checks.append(Check(name="Sealed into Merkle batch", ok=None, detail="waiting for the next anchoring run"))
        return _finish(out, checks)

    batch_id, leaf_index = int(row["batch_id"]), int(row["leaf_index"])
    batch = ledger_db.get_batch(db, batch_id)
    leaves = [ledger.leaf_hash(c) for _, _, c in ledger_db.batch_canonicals(db, batch_id)]
    out.batch_id, out.leaf_index, out.leaf_count = batch_id, leaf_index, len(leaves)
    proof = ledger.merkle_proof(leaves, leaf_index) if leaf_index < len(leaves) else []
    out.proof = [ProofStep(side=s, hash=h.hex()) for s, h in proof]
    rebuilt_root = ledger.root_from_proof(leaf, proof).hex()
    out.merkle_root = rebuilt_root
    checks.append(Check(name=f"Sealed into Merkle batch #{batch_id}", ok=True,
                        detail=f"leaf {leaf_index + 1} of {len(leaves)}, {len(proof)}-step proof → root {rebuilt_root[:16]}…"))

    if chain is None:
        checks.append(Check(name="Anchored on blockchain", ok=None, detail="chain not configured or unreachable"))
        return _finish(out, checks, chain_down=True)

    onchain = chain.get_batch(batch_id)
    out.chain_id, out.contract_address = chain.chain_id, chain.address
    if onchain is None:
        checks.append(Check(name="Anchored on blockchain", ok=None,
                            detail=f"batch #{batch_id} not on-chain yet ({batch['status'] if batch else 'unknown'})"))
        return _finish(out, checks)

    if batch:
        out.tx_hash, out.block_number, out.tx_url = batch["tx_hash"], batch["block_number"], chain.tx_url(batch["tx_hash"])
    out.anchored_at = datetime.fromtimestamp(onchain["timestamp"], tz=timezone.utc).isoformat()
    checks.append(Check(name="Anchored on blockchain", ok=True,
                        detail=f"chain {chain.chain_id}, block {out.block_number or '?'}, at {out.anchored_at}"))

    same_root = onchain["root"] == rebuilt_root
    same_count = onchain["leaf_count"] == len(leaves)
    checks.append(Check(
        name="Chain root matches", ok=same_root and same_count,
        detail="rebuilt root equals the root on-chain" if same_root and same_count else
        f"on-chain root {onchain['root'][:16]}… ({onchain['leaf_count']} records) ≠ rebuilt {rebuilt_root[:16]}… "
        f"({len(leaves)} records) — a record in batch #{batch_id} was altered, removed or added",
    ))
    return _finish(out, checks)


def _finish(out: VerifyResponse, checks: list[Check], chain_down: bool = False) -> VerifyResponse:
    out.checks = checks  # pydantic copied the list at construction; hand back the full trace
    if any(c.ok is False for c in checks):
        out.status, out.summary = "TAMPERED", "This record does NOT match what was sealed. Treat as evidence of tampering."
    elif all(c.ok for c in checks):
        out.status, out.summary = "VERIFIED", "Untouched since sealing — matches the blockchain."
    elif chain_down:
        out.status, out.summary = "CHAIN_UNAVAILABLE", "Local checks pass; blockchain could not be consulted."
    else:
        out.status, out.summary = "PENDING", "Recorded and fingerprinted; waiting to be anchored on-chain."
    return out


@router.get("/verify/{uuid}", response_model=VerifyResponse)
def verify(uuid: str) -> VerifyResponse:
    return verify_record(RiskResultDB.get_instance(), anchor.current_chain(), uuid)


@router.get("/status")
def status() -> dict:
    db = RiskResultDB.get_instance()
    chain = anchor.current_chain()
    chain_info = None
    if chain is not None:
        try:
            chain_info = chain.status()
        except Exception as err:
            anchor.state["last_error"] = f"chain status failed: {err}"
    return {
        "enabled": chain is not None,
        "database": "postgres" if db.is_postgres else "sqlite-memory (dev only, not durable)",
        "interval_seconds": anchor.INTERVAL_SECONDS,
        "confirmations_required": anchor.CONFIRMATIONS,
        "last_run_at": anchor.state["last_run_at"],
        "last_error": anchor.state["last_error"],
        "chain": chain_info,
        "counts": ledger_db.counts(db),
    }


@router.get("/batches")
def batches(limit: int = 20) -> list[dict]:
    chain = anchor.current_chain()
    rows = ledger_db.recent_batches(RiskResultDB.get_instance(), max(1, min(limit, 200)))
    for b in rows:
        b["tx_url"] = chain.tx_url(b["tx_hash"]) if chain else None
    return rows


@router.get("/batches/{batch_id}")
def batch_detail(batch_id: int) -> dict:
    db = RiskResultDB.get_instance()
    batch = ledger_db.get_batch(db, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="No such batch")
    records = []
    for result_id, leaf_index, canonical in ledger_db.batch_canonicals(db, batch_id):
        doc = json.loads(canonical)
        records.append({"leaf_index": leaf_index, "uuid": doc["uuid"], "decision": doc["decision"],
                        "leaf_hash": ledger.leaf_hash(canonical).hex()})
    chain = anchor.current_chain()
    batch["tx_url"] = chain.tx_url(batch["tx_hash"]) if chain else None
    return {**batch, "records": records}
