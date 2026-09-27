"""Process-pool isolation for the heavy native-library inference calls (OpenCV face
detection, DeepFace/ArcFace embedding) this service makes.

Why this exists: a native crash (segfault) inside a C++ library like OpenCV or one of
DeepFace's backends can't be caught by Python's try/except — it kills the whole OS process.
Without this, one bad image could take down an entire uvicorn worker (and every other
request it was serving). ocr-consistency-check's PaddleOCR hit exactly this failure mode in
this same Docker environment — same fix applied here pre-emptively for this service's own
native-library calls.

Running each call in a separate worker process means a crash there only fails that one
request; this server and every other in-flight request keep running.

Backed by loky (https://loky.readthedocs.io — the same executor joblib/scikit-learn use for
exactly this reason) rather than stdlib's concurrent.futures.ProcessPoolExecutor, which
permanently "breaks" the *entire* pool the moment any single worker dies and has to be
manually recreated. loky auto-replaces the crashed worker and keeps serving new requests
without any special handling on our end.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Callable, TypeVar

from loky import get_reusable_executor

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Worker processes each hold their own copy of the OCR model once warmed (first call pays
# the load cost) — keep this small by default; raise it only if you have the RAM to spare.
_WORKERS = int(os.environ.get("INFERENCE_WORKERS", "2"))
_TASK_TIMEOUT_SECONDS = int(os.environ.get("INFERENCE_TIMEOUT_SECONDS", "600"))


class InferenceCrashed(Exception):
    """Raised when the isolated worker process running this call died (e.g. a native
    library segfault) instead of returning a result — as opposed to a normal Python
    exception raised *by* the call, which propagates through unchanged."""


async def run_isolated(fn: Callable[..., T], *args) -> T:
    """Run fn(*args) in an isolated worker process. Raises InferenceCrashed instead of
    taking this service down if that worker process dies mid-call."""
    executor = get_reusable_executor(max_workers=_WORKERS, timeout=300)
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(executor, fn, *args), timeout=_TASK_TIMEOUT_SECONDS
        )
    except asyncio.TimeoutError as err:
        logger.error("Isolated inference call exceeded %ss — treating as crashed.", _TASK_TIMEOUT_SECONDS)
        raise InferenceCrashed(f"timed out after {_TASK_TIMEOUT_SECONDS}s") from err
    except Exception as err:
        # loky's own crash-reporting exceptions live in the loky.* namespace; anything else
        # is a normal application exception raised by fn itself and should propagate as-is.
        if type(err).__module__.startswith("loky"):
            logger.error("Isolated inference worker crashed: %s", err)
            raise InferenceCrashed(str(err)) from err
        raise
