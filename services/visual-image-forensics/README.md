# Visual Image Forensics

Detects tampering/forgery in document images.

Implements `POST /screen` per [API_CONTRACT.md](../../API_CONTRACT.md). Real AI-generated-image
detection, splice/tamper forensics, and guilloché checking aren't built yet — `main.py` currently
validates uploads (per [SECURITY.md](../../SECURITY.md)) and returns a stub score so the rest of
the pipeline can be developed and demoed against a real, running service.

## Dev

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8002
python test_main.py   # runnable self-check — starts the server itself, no pytest needed
```
