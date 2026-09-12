# OCR & Consistency Check

Extracts text from ID documents and validates field consistency (e.g. name/DOB matches across fields).

Implements `POST /screen` per [API_CONTRACT.md](../../API_CONTRACT.md). Real MRZ OCR, barcode
decode, checksum/field validation and watchlist matching aren't built yet — `main.py` currently
validates uploads (per [SECURITY.md](../../SECURITY.md)) and returns a stub score so the rest of
the pipeline can be developed and demoed against a real, running service.

## Dev

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8001
python test_main.py   # runnable self-check — starts the server itself, no pytest needed
```
