"""Per-client rate limiting for this service's public upload endpoint(s).

This is the public-facing surface (the frontend calls it directly from the browser, per
API_CONTRACT.md) — nothing today stops one client from hammering /screen as fast as the
network allows, which is both an abuse vector and a way to starve the (expensive, limited)
OCR inference workers of capacity for everyone else.

Backed by slowapi (built on the `limits` library) with Redis as the counter store, so the
limit is shared across every uvicorn worker/replica of this service rather than reset per
process. Falls back to an in-process counter (single instance only) when REDIS_URL isn't
set, same "best-effort, degrade rather than break" pattern as every other Redis use here.
"""
from __future__ import annotations

import os

from slowapi import Limiter
from slowapi.util import get_remote_address

SCREEN_RATE_LIMIT = os.environ.get("SCREEN_RATE_LIMIT", "30/minute")

limiter = Limiter(
    key_func=get_remote_address,
    storage_uri=os.environ.get("REDIS_URL", "").strip() or "memory://",
)
