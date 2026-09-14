"""
Praman - Risk Scoring Engine: per-uuid state store.

Tracks, for each uuid, what's arrived so far (2 flags, then 3 scores) so
the two endpoints in main.py can coordinate even though every module
posts to us independently, in whatever order, over separate HTTP calls.

Also tracks TIMEOUT_SECONDS per entry - if a uuid sits incomplete for
longer than this (one module crashed, or just never called back), the
background sweeper in main.py escalates it instead of leaving it stuck
in memory forever with no decision. Finalized results (normal or
timed-out) get moved into a separate _results store so they can still
be retrieved via GET /result/{uuid} after the pending entry is cleared.

NOTE: this is a plain in-process dict behind a lock - fine for a single
instance (hackathon demo). If this service ever runs as multiple
processes/pods, this needs to move to Redis or a DB table keyed by uuid,
otherwise different requests for the same uuid could land on different
instances and never see each other's data.
"""

from __future__ import annotations

import os
import time
from threading import Lock

TIMEOUT_SECONDS = int(os.environ.get("RISK_ENGINE_TIMEOUT_SECONDS", "300"))

_lock = Lock()
_store = {}
_results = {}


def _new_entry():
    return {
        "flag_ocr": None,  # None = not received yet, else True/False
        "flag_forensics": None,
        "ocr_score": None,
        "tamper_score": None,
        "photo_score": None,
        "reasons": [],
        "rejected": False,
        "created_at": time.time(),
    }


def get(uuid: str) -> dict:
    with _lock:
        if uuid not in _store:
            _store[uuid] = _new_entry()
        return dict(_store[uuid])


def update(uuid: str, **fields) -> dict:
    with _lock:
        entry = _store.setdefault(uuid, _new_entry())
        entry.update(fields)
        return dict(entry)


def add_reasons(uuid: str, new_reasons: list) -> dict:
    with _lock:
        entry = _store.setdefault(uuid, _new_entry())
        entry["reasons"] = entry["reasons"] + list(new_reasons)
        return dict(entry)


def clear(uuid: str) -> None:
    with _lock:
        _store.pop(uuid, None)


def all_entries() -> dict:
    """Snapshot of every pending (not yet finalized) uuid -> entry."""
    with _lock:
        return {u: dict(e) for u, e in _store.items()}


def save_result(uuid: str, score, decision: str, timed_out: bool = False, reasons: list | None = None) -> None:
    with _lock:
        _results[uuid] = {
            "uuid": uuid,
            "score": score,
            "decision": decision,
            "timed_out": timed_out,
            "reasons": list(reasons) if reasons else [],
            "finalized_at": time.time(),
        }


def get_result(uuid: str):
    with _lock:
        return _results.get(uuid)
