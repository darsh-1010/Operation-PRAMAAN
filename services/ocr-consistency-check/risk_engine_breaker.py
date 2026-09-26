"""Circuit breaker around this service's push to risk-scoring-engine.

Without this, every single /screen request pays a full httpx timeout (5s) trying to reach
risk-scoring-engine whenever it's down — on top of being pointless work, that's 5 extra
seconds of latency per request stacked onto whatever's already slow. After RISK_ENGINE_
FAIL_MAX consecutive failures, the breaker opens and every push fails instantly (no network
call attempted) for RISK_ENGINE_COOLDOWN_SECONDS, then allows one attempt through to test
whether risk-scoring-engine has recovered.

Uses aiobreaker (an asyncio-native fork of pybreaker) rather than pybreaker itself — pybreaker's
call() is synchronous and blocks the event loop if used directly from an async route.
"""
from __future__ import annotations

import os
from datetime import timedelta

from aiobreaker import CircuitBreaker

RISK_ENGINE_BREAKER = CircuitBreaker(
    fail_max=int(os.environ.get("RISK_ENGINE_FAIL_MAX", "5")),
    timeout_duration=timedelta(seconds=int(os.environ.get("RISK_ENGINE_COOLDOWN_SECONDS", "30"))),
)
