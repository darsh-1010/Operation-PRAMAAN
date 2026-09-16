"""OCR & Consistency Check Microservice (Module 1 - Operation PRAMAAN).

Entry point for SIH26188 Module 1.
Handles document ingestion (PDF/Images), PaddleOCR text extraction,
MRZ ICAO 9303 validation, watchlist screening, registry candidate matching,
and weighted Score A calculation.
"""

from __future__ import annotations
from contextlib import asynccontextmanager
import logging
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from db import DatabaseManager
from multilingual_service import router as multilingual_router
from ocr_engine import OCREngine
from routes import router as api_router, run_screening_pipeline

# Re-export for any external or test references
_run_screening_pipeline = run_screening_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ocr_service")

RISK_ENGINE_URL = os.environ.get("RISK_ENGINE_URL", "http://localhost:8004").rstrip("/")
_cache = ResultCache(namespace="ocr")


@RISK_ENGINE_BREAKER
async def _push_to_risk_engine(session_id: str, hard_fail: bool, score: float, reasons: List[str]) -> None:
    async with httpx.AsyncClient(timeout=5.0) as client:
        await client.post(
            f"{RISK_ENGINE_URL}/flag-check",
            json={"uuid": session_id, "module": "ocr", "flag": hard_fail, "reasons": reasons},
        )
        # If that flag was true, the risk engine already rejected and cleared this uuid —
        # this second call still fires (simpler than branching), but lands on the
        # already-finalized guard on the other end rather than a live wait.
        await client.post(
            f"{RISK_ENGINE_URL}/submit-score",
            json={"uuid": session_id, "module": "ocr", "ocr": {"score": score, "reasons": reasons}},
        )
    logger.info("uuid=%s pushed to risk-scoring-engine (flag=%s, score=%s)", session_id, hard_fail, score)


async def _notify_risk_engine(session_id: str, hard_fail: bool, score: float, reasons: List[str]) -> None:
    """Push this module's flag + score to risk-scoring-engine (see
    ../../services/risk-scoring-engine/README.md for the two-stage contract). Best-effort:
    the risk engine being down must never break this service's own /screen response to the
    frontend, so failures are logged and swallowed rather than raised. Circuit-breaker-backed
    (see risk_engine_breaker.py) so a down risk-scoring-engine fails fast instead of costing
    a full httpx timeout on every single request."""
    try:
        await _push_to_risk_engine(session_id, hard_fail, score, reasons)
    except CircuitBreakerError:
        logger.warning("uuid=%s risk-scoring-engine circuit open, skipping push", session_id)
    except httpx.HTTPError as exc:
        logger.warning("uuid=%s risk-scoring-engine unreachable, skipping push: %s", session_id, exc)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Pre-warm models and initialize connections at service startup."""
    logger.info("Initializing OCR & Consistency Check Service...")
    db = DatabaseManager.get_instance()
    logger.info("Database backend initialized (PostgreSQL: %s).", db.is_postgres)
    engine = OCREngine.get_instance()
    logger.info("OCR Engine initialized: %s.", engine._engine_name)
    yield
    logger.info("Shutting down OCR & Consistency Check Service...")


app = FastAPI(
    title="Operation PRAMAAN — Module 1 (OCR & Consistency Check)",
    description="FastAPI service for document text extraction, MRZ checksum verification, and registry matching.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
app.include_router(multilingual_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
