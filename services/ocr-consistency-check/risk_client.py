"""Pushes this module's flag + score to risk-scoring-engine (see its README for the two-stage
contract), authenticated with this module's own bearer token (RISK_ENGINE_TOKEN, which must equal
the risk engine's RISK_TOKEN_OCR).

Best-effort: the risk engine being down must never break this service's /screen response, so
failures are logged, not raised. Circuit-breaker-backed so a down risk engine fails fast — but
only 5xx/network errors count towards opening the breaker: a 4xx is a problem with that one
request (e.g. an unknown screening id), and letting those trip it would let anyone block every
real screening by spamming fake ids.
"""
from __future__ import annotations

import logging
import os

import httpx
from aiobreaker import CircuitBreakerError

from risk_engine_breaker import RISK_ENGINE_BREAKER

logger = logging.getLogger("risk_client")

RISK_ENGINE_URL = os.environ.get("RISK_ENGINE_URL", "http://localhost:8004").rstrip("/")
RISK_ENGINE_TOKEN = os.environ.get("RISK_ENGINE_TOKEN", "").strip()


@RISK_ENGINE_BREAKER
async def _push(uuid: str, hard_fail: bool, score: float, reasons: list[str], evidence: list[str],
                review_required: bool) -> list[str]:
    calls = [
        ("/flag-check", {"uuid": uuid, "module": "ocr", "flag": hard_fail, "reasons": reasons, "evidence": evidence}),
        # If that flag was true, the risk engine already rejected this uuid — the score call then
        # lands on its already-finalized guard, which is harmless.
        ("/submit-score", {"uuid": uuid, "module": "ocr",
                           "ocr": {"score": score, "reasons": reasons, "review_required": review_required}}),
    ]
    rejected = []
    async with httpx.AsyncClient(timeout=5.0, headers={"Authorization": f"Bearer {RISK_ENGINE_TOKEN}"}) as client:
        for path, body in calls:
            resp = await client.post(RISK_ENGINE_URL + path, json=body)
            if resp.status_code >= 500:
                resp.raise_for_status()
            if resp.status_code >= 400:
                rejected.append(f"{path} -> {resp.status_code} {resp.text[:200]}")
    return rejected


async def notify_risk_engine(uuid: str, hard_fail: bool, score: float, reasons: list[str], evidence: list[str],
                             review_required: bool) -> None:
    if not RISK_ENGINE_TOKEN:
        logger.error("uuid=%s RISK_ENGINE_TOKEN not set — result NOT sent to risk-scoring-engine", uuid)
        return
    try:
        rejected = await _push(uuid, hard_fail, score, reasons, evidence, review_required)
    except CircuitBreakerError:
        logger.warning("uuid=%s risk-scoring-engine circuit open, skipping push", uuid)
        return
    except httpx.HTTPError as exc:
        logger.warning("uuid=%s risk-scoring-engine unreachable, skipping push: %s", uuid, exc)
        return
    for problem in rejected:
        logger.error("uuid=%s risk-scoring-engine refused OCR result: %s", uuid, problem)
    if not rejected:
        logger.info("uuid=%s pushed to risk-scoring-engine (flag=%s, score=%s, review=%s)", uuid, hard_fail, score, review_required)
