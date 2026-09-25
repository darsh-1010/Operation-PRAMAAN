"""Background anchoring worker: every ANCHOR_INTERVAL_SECONDS, seal all new decisions into one
Merkle batch and write its root to the chain. Runs in every uvicorn worker/replica; a Postgres
advisory lock makes exactly one of them do the work per tick.

Crash-safe by construction — every step can die and the next tick picks up where it stopped:
  batch row PENDING → tx broadcast (hash saved) → mined → N confirmations → CONFIRMED
The contract only accepts strictly sequential batch ids, and every retry first asks the chain
whether that batch id is already there, so a retry can never double-anchor. If the chain holds
a DIFFERENT root for a batch than our DB does, anchoring halts loudly instead of papering over
it — that's evidence, for a human. The chain is never on the screening path: if it's down,
decisions keep being saved and simply wait in PENDING.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Optional

import chain as chain_mod
import ledger_db

logger = logging.getLogger("risk_engine.anchor")

INTERVAL_SECONDS = int(os.environ.get("ANCHOR_INTERVAL_SECONDS", "600"))
MAX_BATCH = int(os.environ.get("ANCHOR_MAX_BATCH", "1024"))
CONFIRMATIONS = int(os.environ.get("ANCHOR_CONFIRMATIONS", "1"))
LOCK_NAME = "praman_anchor"

RECONNECT_BACKOFF_SECONDS = 30

state: dict = {"chain": None, "last_run_at": None, "last_error": None, "last_connect_attempt": 0.0}


def current_chain() -> Optional[chain_mod.Chain]:
    """Connects lazily and reconnects after failures (at most every RECONNECT_BACKOFF_SECONDS,
    so /ledger/* requests don't each hang on a dead RPC), so a chain that's down at boot or
    later never takes the service down with it."""
    if state["chain"] is None and time.time() - state["last_connect_attempt"] >= RECONNECT_BACKOFF_SECONDS:
        state["last_connect_attempt"] = time.time()
        try:
            state["chain"] = chain_mod.from_env()
        except Exception as err:
            state["last_error"] = f"chain connect failed: {err}"
            logger.error("Blockchain anchoring unavailable: %s", err)
    return state["chain"]


def _locate_tx(chain: chain_mod.Chain, batch: dict) -> Optional[dict]:
    """Where an already-anchored root landed: the saved tx if it's the one that mined, else
    the Anchored event (the saved hash may belong to a replaced attempt)."""
    if batch["tx_hash"]:
        try:
            return chain.wait_receipt(batch["tx_hash"], timeout=5)
        except Exception:
            pass
    return chain.find_anchor_tx(batch["batch_id"])


def settle(db, chain: chain_mod.Chain, batch: dict) -> bool:
    """Moves one PENDING batch as far towards CONFIRMED as it can. True once confirmed."""
    batch_id, root = batch["batch_id"], batch["merkle_root"]
    try:
        onchain = chain.get_batch(batch_id)
        if onchain is None:
            tx_hash = chain.send_anchor(batch_id, root, batch["leaf_count"], attempt=min(batch["attempts"], 8))
            ledger_db.set_tx_hash(db, batch_id, tx_hash)
            where = chain.wait_receipt(tx_hash)
        else:
            if (onchain["root"], onchain["leaf_count"]) != (root, batch["leaf_count"]):
                # The chain already holds a DIFFERENT root for this batch id: our DB copy no longer
                # matches what was sealed. Never "fix" this automatically — it is evidence.
                raise chain_mod.ChainError(f"batch {batch_id} on-chain is {onchain['root']}/{onchain['leaf_count']} "
                                           f"leaves but DB says {root}/{batch['leaf_count']} — possible tampering")
            where = _locate_tx(chain, batch) or {"tx_hash": None, "block_number": None}
        if where["block_number"] is not None and chain.confirmations(where["block_number"]) < CONFIRMATIONS:
            return False  # mined but not deep enough yet; next tick re-checks
        ledger_db.mark_confirmed(db, batch_id, where["tx_hash"], where["block_number"], chain.chain_id, chain.address)
        logger.info("batch=%s anchored: root=%s leaves=%s tx=%s", batch_id, root, batch["leaf_count"], where["tx_hash"])
        return True
    except Exception as err:
        ledger_db.mark_attempt_failed(db, batch_id, str(err))
        state["last_error"] = f"batch {batch_id}: {err}"
        logger.error("batch=%s anchor attempt failed (will retry): %s", batch_id, err)
        return False


def anchor_once(db, chain: chain_mod.Chain) -> dict:
    """One tick: finish any PENDING batches, then seal and anchor new decisions."""
    with db.try_lock(LOCK_NAME) as got:
        if not got:
            return {"skipped": "another worker holds the anchor lock"}
        confirmed = 0
        for batch in ledger_db.pending_batches(db):
            if not settle(db, chain, batch):
                return {"confirmed": confirmed, "stalled_on": batch["batch_id"]}  # keep order; retry next tick
            confirmed += 1
        while (batch := ledger_db.create_batch(db, MAX_BATCH, chain.last_batch_id())) is not None:
            if not settle(db, chain, batch):
                break
            confirmed += 1
        return {"confirmed": confirmed}


def tick(db) -> None:
    state["last_run_at"] = time.time()
    chain = current_chain()
    if chain is None:
        return
    state["last_error"] = None  # settle() re-sets it if anything in this tick fails
    try:
        anchor_once(db, chain)
    except Exception as err:
        state["last_error"] = str(err)
        state["chain"] = None  # force a clean reconnect next tick
        logger.exception("anchor tick failed")


async def run_forever(db) -> None:
    if not db.is_postgres:
        logger.warning("Ledger is running on the in-memory SQLite fallback: every uvicorn worker has its "
                       "OWN private copy and all of it is lost on restart. Dev only — use Postgres.")
    while True:
        await asyncio.to_thread(tick, db)  # web3 calls block; keep them off the event loop
        await asyncio.sleep(INTERVAL_SECONDS)
