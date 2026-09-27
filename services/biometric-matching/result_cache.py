"""Redis-backed cache for full /screen results, keyed by a hash of the uploaded file
bytes. Skips re-running the OCR/watchlist pipeline when the exact same file(s) are
re-submitted (retry, page refresh, duplicate kiosk scan) — the pipeline's output for
identical bytes is deterministic, so reusing it is safe. Falls back to a no-op cache
(always a miss) when Redis isn't reachable — same "best-effort, never break the
request" pattern as every service's db.py.

Duplicated into biometric-matching too rather than shared, per CLAUDE.md's
cross-service-contract-not-imports rule (each service owns its own copy).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

_DEFAULT_TTL_SECONDS = 6 * 60 * 60  # long enough to absorb retries, short enough that a
                                     # registry/watchlist update doesn't stay stale for long


class ResultCache:
    """Content-hash cache for one service's /screen result, backed by Redis."""

    def __init__(self, namespace: str, ttl_seconds: int = _DEFAULT_TTL_SECONDS) -> None:
        self._namespace = namespace
        self._ttl = ttl_seconds
        self._redis = self._connect()

    def _connect(self):
        redis_url = os.environ.get("REDIS_URL", "").strip()
        if not redis_url:
            return None
        try:
            import redis
            client = redis.Redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=3)
            client.ping()
            logger.info("Connected to Redis at %s for %s result cache.", redis_url, self._namespace)
            return client
        except Exception as err:
            logger.warning("Redis unavailable (%s) - %s result cache disabled.", err, self._namespace)
            return None

    @staticmethod
    def fingerprint(*byte_blobs: bytes) -> str:
        """Stable content hash for a fixed-order set of file uploads. Length-prefixing each
        blob guards against two different blob splits hashing to the same bytes."""
        digest = hashlib.sha256()
        for blob in byte_blobs:
            digest.update(len(blob).to_bytes(8, "big"))
            digest.update(blob)
        return digest.hexdigest()

    def get(self, fingerprint: str) -> Optional[dict]:
        if self._redis is None:
            return None
        try:
            raw = self._redis.get(f"{self._namespace}:result:{fingerprint}")
            return json.loads(raw) if raw else None
        except Exception as err:
            logger.warning("%s result cache read failed: %s", self._namespace, err)
            return None

    def set(self, fingerprint: str, result: dict) -> None:
        if self._redis is None:
            return
        try:
            self._redis.setex(f"{self._namespace}:result:{fingerprint}", self._ttl, json.dumps(result))
        except Exception as err:
            logger.warning("%s result cache write failed: %s", self._namespace, err)
