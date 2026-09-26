"""
Praman - Risk Scoring Engine: per-uuid state store.

Tracks, for each uuid, what's arrived so far (2 flags, then 3 scores) so
the two endpoints in main.py can coordinate even though every module
posts to us independently, in whatever order, over separate HTTP calls.

Also tracks TIMEOUT_SECONDS per entry - if a uuid sits incomplete for
longer than this (one module crashed, or just never called back), the
background sweeper in main.py escalates it instead of leaving it stuck
in memory forever with no decision. Finalized results (normal or
timed-out) get moved into a separate results store so they can still
be retrieved via GET /result/{uuid} after the pending entry is cleared.

Backed by Redis (REDIS_URL) so this survives running this service as
multiple processes/pods - without it, different requests for the same
uuid could land on different instances and never see each other's data.
Falls back to the original in-process dict when Redis isn't reachable
(local dev without `docker compose up redis`), same "best-effort,
degrade rather than break" pattern as every service's db.py.
"""

from __future__ import annotations

import json
import logging
import os
import time
from threading import Lock

logger = logging.getLogger("risk_engine.store")

TIMEOUT_SECONDS = int(os.environ.get("RISK_ENGINE_TIMEOUT_SECONDS", "300"))
# Pending-entry TTL in Redis: comfortably longer than TIMEOUT_SECONDS so the sweeper (which
# polls every 30s in main.py) always gets a chance to see and escalate a stale entry itself,
# rather than Redis silently expiring it out from under the sweeper first.
_PENDING_TTL_SECONDS = TIMEOUT_SECONDS + 120
_RESULT_TTL_SECONDS = 24 * 60 * 60  # finalized results stay pollable for a day
# A screening id is only accepted if this service issued it (POST /sessions) within this window.
SESSION_TTL_SECONDS = int(os.environ.get("RISK_SESSION_TTL_SECONDS", "3600"))

_PENDING_FIELDS = ("flag_ocr", "flag_forensics", "ocr_score", "tamper_score", "photo_score", "rejected",
                   "tamper_unavailable", "review_required")
_BOOL_FIELDS = {"flag_ocr", "flag_forensics", "rejected", "tamper_unavailable", "review_required"}


def _new_entry() -> dict:
    return {
        "flag_ocr": None,  # None = not received yet, else True/False
        "flag_forensics": None,
        "ocr_score": None,
        "tamper_score": None,
        "photo_score": None,
        "tamper_unavailable": False,  # forensics reported it could not assess the images
        "review_required": False,  # a module said a human must look, whatever the score
        "reasons": [],
        "evidence": [],  # "<kind>:<sha256>" of every uploaded file, sealed into the ledger record
        "rejected": False,
        "created_at": time.time(),
    }


def _connect_redis():
    redis_url = os.environ.get("REDIS_URL", "").strip()
    if not redis_url:
        return None
    try:
        import redis
        client = redis.Redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=3)
        client.ping()
        logger.info("Connected to Redis at %s for pending/result state.", redis_url)
        return client
    except Exception as err:
        logger.warning("Redis unavailable (%s). Falling back to in-process store (single instance only).", err)
        return None


_redis = _connect_redis()

# In-process fallback state (used only when _redis is None).
_lock = Lock()
_store: dict = {}
_results: dict = {}
_sessions: dict = {}  # uuid -> expiry epoch seconds


def _pending_key(uuid: str) -> str:
    return f"risk:pending:{uuid}"


def _reasons_key(uuid: str) -> str:
    return f"risk:pending:{uuid}:reasons"


def _result_key(uuid: str) -> str:
    return f"risk:result:{uuid}"


def _evidence_key(uuid: str) -> str:
    return f"risk:pending:{uuid}:evidence"


def _session_key(uuid: str) -> str:
    return f"risk:session:{uuid}"


def _touch_ttl(uuid: str) -> None:
    _redis.expire(_pending_key(uuid), _PENDING_TTL_SECONDS)
    _redis.expire(_reasons_key(uuid), _PENDING_TTL_SECONDS)
    _redis.expire(_evidence_key(uuid), _PENDING_TTL_SECONDS)
    _redis.sadd("risk:pending:index", uuid)
    _redis.expire("risk:pending:index", _PENDING_TTL_SECONDS)


def _decode_entry(uuid: str, raw: dict, reasons: list, evidence: list) -> dict:
    entry = _new_entry()
    entry["created_at"] = float(raw.get("created_at", time.time()))
    for field in _PENDING_FIELDS:
        if field not in raw:
            continue
        entry[field] = raw[field] == "1" if field in _BOOL_FIELDS else float(raw[field])
    entry["reasons"] = reasons
    entry["evidence"] = evidence
    return entry


def _read(uuid: str, raw: dict) -> dict:
    return _decode_entry(uuid, raw, _redis.lrange(_reasons_key(uuid), 0, -1), _redis.lrange(_evidence_key(uuid), 0, -1))


def get(uuid: str) -> dict:
    if _redis is None:
        with _lock:
            if uuid not in _store:
                _store[uuid] = _new_entry()
            return dict(_store[uuid])

    raw = _redis.hgetall(_pending_key(uuid))
    if not raw:
        _redis.hset(_pending_key(uuid), mapping={"created_at": time.time()})
        _touch_ttl(uuid)
        return _new_entry()
    return _read(uuid, raw)


def update(uuid: str, **fields) -> dict:
    if _redis is None:
        with _lock:
            entry = _store.setdefault(uuid, _new_entry())
            entry.update(fields)
            return dict(entry)

    encoded = {k: ("1" if v else "0") if k in _BOOL_FIELDS else v for k, v in fields.items()}
    _redis.hset(_pending_key(uuid), mapping=encoded)
    _touch_ttl(uuid)
    return get(uuid)


def add_reasons(uuid: str, new_reasons: list) -> dict:
    if _redis is None:
        with _lock:
            entry = _store.setdefault(uuid, _new_entry())
            entry["reasons"] = entry["reasons"] + list(new_reasons)
            return dict(entry)

    if new_reasons:
        _redis.rpush(_reasons_key(uuid), *new_reasons)
    _touch_ttl(uuid)
    return get(uuid)


def add_evidence(uuid: str, items: list) -> dict:
    if _redis is None:
        with _lock:
            entry = _store.setdefault(uuid, _new_entry())
            entry["evidence"] = entry["evidence"] + [i for i in items if i not in entry["evidence"]]
            return dict(entry)

    if items:
        _redis.rpush(_evidence_key(uuid), *items)
    _touch_ttl(uuid)
    return get(uuid)


def clear(uuid: str) -> None:
    if _redis is None:
        with _lock:
            _store.pop(uuid, None)
        return

    _redis.delete(_pending_key(uuid), _reasons_key(uuid), _evidence_key(uuid))
    _redis.srem("risk:pending:index", uuid)


def all_entries() -> dict:
    """Snapshot of every pending (not yet finalized) uuid -> entry."""
    if _redis is None:
        with _lock:
            return {u: dict(e) for u, e in _store.items()}

    out = {}
    for uuid in _redis.smembers("risk:pending:index"):
        raw = _redis.hgetall(_pending_key(uuid))
        if not raw:
            _redis.srem("risk:pending:index", uuid)  # expired already, tidy the index
            continue
        out[uuid] = _read(uuid, raw)
    return out


def save_result(uuid: str, score, decision: str, timed_out: bool = False, reasons: list | None = None) -> None:
    result = {
        "uuid": uuid,
        "score": score,
        "decision": decision,
        "timed_out": timed_out,
        "reasons": list(reasons) if reasons else [],
        "finalized_at": time.time(),
    }
    if _redis is None:
        with _lock:
            _results[uuid] = result
        return
    _redis.setex(_result_key(uuid), _RESULT_TTL_SECONDS, json.dumps(result))


def get_result(uuid: str):
    if _redis is None:
        with _lock:
            return _results.get(uuid)
    raw = _redis.get(_result_key(uuid))
    return json.loads(raw) if raw else None


def issue_session(uuid: str) -> None:
    """Records a server-issued screening id. Modules may only report on ids issued here, so a
    caller can't invent ids or re-use a finalized one's echoed decision for a new person."""
    if _redis is None:
        with _lock:
            _sessions[uuid] = time.time() + SESSION_TTL_SECONDS
        return
    _redis.set(_session_key(uuid), "1", ex=SESSION_TTL_SECONDS)


def session_exists(uuid: str) -> bool:
    if _redis is None:
        with _lock:
            return _sessions.get(uuid, 0) > time.time()
    return bool(_redis.exists(_session_key(uuid)))
