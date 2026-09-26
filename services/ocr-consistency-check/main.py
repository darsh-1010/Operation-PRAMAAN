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
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from db import DatabaseManager
from multilingual_service import router as multilingual_router
from ocr_engine import OCREngine
from module_screen import router as screen_router
from rate_limit import limiter
from routes import router as api_router, run_screening_pipeline

# Re-export for any external or test references
_run_screening_pipeline = run_screening_pipeline

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ocr_service")

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

# Per-client limit on /screen (rate_limit.py) — defined long ago but never applied until now.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.include_router(api_router)
app.include_router(screen_router)
app.include_router(multilingual_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8001, reload=True)
