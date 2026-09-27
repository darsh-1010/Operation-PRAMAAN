# OCR & Consistency Check (Module 1)

Implements `POST /screen` per [API_CONTRACT.md](../../API_CONTRACT.md) in [`module_screen.py`](module_screen.py):
OCR of every uploaded document, MRZ check digits, field format/expiry checks, watchlist
screening, cross-document consistency, identity-document checks (Aadhaar Secure QR signature,
Voter ID, Nepali citizenship; see [ID_DOCUMENTS.md](ID_DOCUMENTS.md)) and encrypted evidence
retention. It then pushes its flag and score to `risk-scoring-engine`.

- **OCR engines.** PaddleOCR is tried first, in a crash-isolated worker process
  (`inference_pool.py`). It segfaults on some builds (reproduced on aarch64 Docker); the service
  then falls back to Tesseract (`OCR_FALLBACK_TESSERACT`) and skips Paddle for
  `PADDLE_RETRY_AFTER_SECONDS`. Tesseract reads MRZ lines poorly, and a passport or visa whose
  MRZ can't be read goes to review (`MRZ_NOT_READ`).
- **Database.** Schema in [`schema.py`](schema.py), created and upgraded automatically on
  connect. It is additive only, so it's safe on existing databases.
- **Watchlist** (`candidate_search.py`). A document number matches exactly, ignoring spaces and
  dashes. A name matches fuzzily and in any word order. Name plus the same DOB is a hard fail;
  name with no DOB goes to officer review.

## Dev

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
python seed_demo_data.py      # demo watchlist + registry records (never automatic)
python -m pytest tests test_id_verification.py test_schema_watchlist.py
```

The tests in `tests/` and the DB half of `test_schema_watchlist.py` need a reachable Postgres
(`POSTGRES_*` env vars) with the demo data seeded.
