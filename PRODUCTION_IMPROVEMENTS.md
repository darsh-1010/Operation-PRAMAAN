# Production improvements — what's done, what's deferred

This tracks the production-hardening work from the "make this faster and more
production-grade" review. See each linked source for the research behind a choice.

## Done (implemented, tested against a live docker-compose stack)

| # | Improvement | Where | Library |
|---|---|---|---|
| 1 | Crash isolation for native ML calls | `ocr-consistency-check`, `biometric-matching` | [loky](https://loky.readthedocs.io) (`inference_pool.py`) |
| 4 | Metrics (`/metrics`, RED metrics) | all 4 backend services | [prometheus-fastapi-instrumentator](https://github.com/trallnag/prometheus-fastapi-instrumentator) + Prometheus + Grafana in `docker-compose.yml` |
| 5 | Circuit breaker on the risk-engine push | `ocr-consistency-check`, `visual-image-forensics`, `biometric-matching` | [aiobreaker](https://aiobreaker.netlify.app) (`risk_engine_breaker.py`) |
| 6 | Per-client rate limiting on `/screen` | `ocr-consistency-check`, `visual-image-forensics`, `biometric-matching` | [slowapi](https://github.com/laurentS/slowapi) (`rate_limit.py`), Redis-backed |

Also fixed along the way (see git history around the same date): opencv/deepface missing
system libs, a schema-creation race under multiple uvicorn workers, and Vite not binding to
`0.0.0.0` in Docker.

**Why crash isolation, specifically:** PaddleOCR was found to segfault on real image
inference in this Docker environment (reproduced directly on the main thread — not a
threading bug). A native segfault can't be caught by Python's `try`/`except`, so it silently
killed the whole service process. `loky`'s `get_reusable_executor()` (the same executor
joblib/scikit-learn use) runs each inference call in its own worker process and
auto-replaces a worker that dies, instead of the whole pool going permanently "broken" the
way stdlib's plain `ProcessPoolExecutor` does after any single crash. [loky docs](https://loky.readthedocs.io/en/latest/)

**Why aiobreaker over pybreaker:** pybreaker's `call()` is synchronous and would block the
event loop (or need an executor workaround) if used from an `async def` route; aiobreaker
is an asyncio-native fork built for exactly this. [Comparison](https://www.codingeasypeasy.com/blog/implement-circuit-breakers-for-api-calls-in-fastapi-with-aiobreaker)

**Why slowapi over fastapi-limiter:** fastapi-limiter's published package (checked at
implementation time) doesn't actually export `FastAPILimiter` from its top-level module —
importing it the documented way fails. slowapi (built on the well-established `limits`
library) verified working with a Redis storage backend and is the more mature/maintained
option. [slowapi + Redis](https://adhdecode.com/articles/fastapi/fastapi-rate-limiting-slowapi/)

---

## Deferred — documented here, not implemented

### Face-watchlist vector search (Milvus or pgvector)
**The gap:** `biometric-matching` only compares faces *within one submission*
(doc-to-selfie, cross-doc). There's no way to check "does this face match anyone on a
watchlist of known-fraud faces" — a real capability gap for the border-security use case,
not just a performance one. The service's own code already anticipates this
(`[ ] Milvus integration — not yet needed` in its docstring).

**How to add it:** store watchlist face embeddings in a vector DB — Milvus for a dedicated,
horizontally-scalable ANN index, or `pgvector` (a Postgres extension) if you'd rather not run
a 5th piece of infrastructure and the watchlist stays in the tens-of-thousands of faces
range. On each `/screen` call, after generating the submitted face's embedding, run a
nearest-neighbor search against the watchlist collection and treat a close match as a new
`hard_fail` reason code. [Milvus + face recognition](https://milvus.io/ai-quick-reference/how-can-face-recognition-systems-integrate-with-vector-search) · [Face recognition + Milvus walkthrough](https://medium.com/@devraj.agarwal/creating-a-face-recognition-system-with-mtcnn-facenet-and-milvus-e155c36d8852)

### A real task queue (Celery or RQ)
**The gap:** every `/screen` call holds an HTTP connection open for the full pipeline
duration — we measured 60+ seconds on a cold model load. At real checkpoint volume (a line
of people), requests queue up behind each other even with more uvicorn workers, because each
worker can only run one heavy inference at a time.

**How to add it:** `/screen` enqueues a job to Redis (Celery or the lighter RQ) and returns a
job id immediately; a fixed pool of worker processes — pre-loading models once at startup,
not per job — drains the queue; the frontend polls for the result, which
`risk-scoring-engine`'s `/result/{uuid}` pattern already anticipates. Route short
pre/post-processing work to a different queue than long inference work to avoid one blocking
the other. [Celery+Redis inference architecture](https://markaicode.com/architecture/celery-inference-architecture/) · [FastAPI+Celery+Redis](https://markaicode.com/stack/fastapi-redis-stack/)

**Why not now:** this is real added operational complexity (a broker, worker processes,
monitoring, retry semantics) that isn't worth taking on until there's actual evidence of
requests queueing up under real load — the crash isolation + rate limiting done above buy
meaningful headroom without it.

### Distributed tracing (OpenTelemetry + Jaeger)
**The gap:** Prometheus (added above) tells you *that* something is slow; it doesn't tell
you *where* across a request that fans out through up to 4 services. Following one uuid's
request through `ocr-consistency-check` → `risk-scoring-engine` → back is manual log-grepping
today.

**How to add it:** instrument each service with OpenTelemetry's FastAPI integration, run an
OTel Collector + Jaeger (or Grafana Tempo) in `docker-compose.yml`, and thread the uuid (this
system already generates one per submission) through as a trace/span attribute.
[FastAPI+OTel+Prometheus+Jaeger+Grafana walkthrough](https://dev.to/hashiravc/practical-modern-observability-fastapi-opentelemetry-prometheus-jaeger-and-grafana-46bj)

**Why not now:** bigger infra lift (new services, code instrumentation across all 4) than
the metrics-only version above; worth doing once the Prometheus dashboards actually surface
a "which service is slow" question metrics alone can't answer.

### A dedicated API gateway
**The gap:** what's implemented above is *per-service* rate limiting, not centralized
auth, routing, or request/response transformation. Each of the 3 detection services and the
frontend still talk to each other's raw ports directly.

**How to add it:** a lightweight gateway (nginx, or a small FastAPI proxy) in front of all 4
ports doing auth, centralized rate limiting, and request size limits — most valuable once
this is actually reachable from the public internet rather than a local/demo network.

### GPU inference
**The gap:** everything runs on CPU today. `biometric-matching` and (once its TODO is
implemented) `visual-image-forensics`' CNN inference are the parts that would benefit most.

**Why not now:** real infrastructure cost and complexity — only worth it once CPU inference
is a *measured* bottleneck (profile first, e.g. via the Prometheus latency histograms added
above) rather than an assumption. [GPU inference serving 2026 overview](https://www.digitalocean.com/resources/articles/ai-inference-platforms)
