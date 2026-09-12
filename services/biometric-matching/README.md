# Biometric Matching

Matches selfie/live capture against the ID document photo.

Implements `POST /screen` per [API_CONTRACT.md](../../API_CONTRACT.md). Real liveness detection
and face matching aren't built yet — `main.py` currently validates uploads (per
[SECURITY.md](../../SECURITY.md)) and returns a stub score so the rest of the pipeline can be
developed and demoed against a real, running service.

## Dev

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8003
python test_main.py   # runnable self-check — starts the server itself, no pytest needed
```
