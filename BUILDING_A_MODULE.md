# Building your module — a guide for the 3 detection services

You're building the real logic inside one of `ocr-consistency-check`, `visual-image-forensics`,
or `biometric-matching`. The frontend and the input pipeline are already done — this doc is
everything you need to know to plug your detection logic into what already exists, without
having to read the frontend code.

If you only read one other file, read [API_CONTRACT.md](API_CONTRACT.md) — this doc explains
*how to work with* that contract; API_CONTRACT.md is the contract itself.

## The short version

1. A `main.py` already exists in your service folder. It receives the request, validates the
   files, and returns a **stub** answer. Your job is to replace the stub with real detection
   logic — the request-handling and validation code around it, you can mostly leave alone.
2. You do not need to know anything about React, the frontend, or the other 2 services. You
   receive files and a JSON-shaped question ("what's in this submission?") and you return a
   score, a flag, and reasons. That's the entire interface.
3. Run it, test it, open `/docs` in your browser and try it by hand before touching any real
   detection code — see **Running it yourself** below.

## What a request actually looks like

The frontend does **not** send JSON. It sends `multipart/form-data` — the same format a browser
uses when you submit a form with a file input. Concretely, one request contains:

```
uuid                = "7147f10d-e7ac-480a-9050-3db595bef7a9"
documents_present   = '{"passport":true,"visa":true,"nationalId":true,"drivingLicence":false,"permit":false,"selfie":true}'
passport            = <binary file data>
visa                = <binary file data>
nationalId          = <binary file data>
selfie              = <binary file data>
```

Notice `drivingLicence` and `permit` have **no file field at all** in this example — they were
`false` in `documents_present`, so the frontend didn't attach them. This is the single most
important thing to get right:

> **Always check `documents_present` before looking for a file.** Never assume all 6 fields
> are there. Passport, Visa, National ID and the selfie are the only ones the frontend requires
> from the user — Driving Licence and Permit are genuinely optional and will very often be
> absent.

`selfie` is special: it can be either an **image** (a still selfie) or a **video** (a few
seconds of live video) — check the content, don't assume it decodes like the document photos.

## How `main.py` already reads this for you

Every service's `main.py` uses FastAPI's `Form(...)` and `File(...)` to pull exactly those
fields out of the request — you don't have to parse multipart data by hand:

```python
@app.post("/screen")
async def screen(
    uuid: str = Form(...),
    documents_present: str = Form(...),      # JSON string — json.loads() it
    passport: Optional[UploadFile] = File(None),
    visa: Optional[UploadFile] = File(None),
    nationalId: Optional[UploadFile] = File(None),
    drivingLicence: Optional[UploadFile] = File(None),
    permit: Optional[UploadFile] = File(None),
    selfie: Optional[UploadFile] = File(None),
) -> dict:
```

`UploadFile` is FastAPI's wrapper around an uploaded file. To get the raw bytes:
`data = await passport.read()`.

The existing code already:
- Parses `documents_present` and raises a clean `400` if it's not valid JSON.
- Raises `400` if `documents_present` claims a file is present but none was actually attached
  (someone lying about what they sent, or a bug on the frontend).
- **Re-validates every file server-side** — decodes it with an image library and rejects
  anything that isn't a real, decodable image, *regardless of what the client claimed it was*.
  This is not optional boilerplate: see [SECURITY.md](SECURITY.md) for why (a browser's file-type
  check can always be bypassed by calling the API directly, so your service must never trust it).

**Leave this part alone unless you have a specific reason to change it.** Your real work goes in
one place — see below.

## Where your detection logic goes

Look for the `TODO` comment near the bottom of `main.py`:

```python
    # TODO: real MRZ OCR, barcode decode, checksum/field-format validation, and fuzzy
    # watchlist matching. Stub result below keeps the contract honest (score/hard_fail/
    # reason_codes) without pretending to have run checks that don't exist yet.
    return {"score": 85, "hard_fail": False, "reason_codes": ["stub: real OCR/watchlist checks not implemented yet"]}
```

Replace that stub with your real logic. You have the raw bytes of every present file (read them
the same way the validation code above does — `await passport.read()`, etc.) — do whatever OCR /
forensics / face-matching work is yours to do, then return the same shape:

```python
return {
    "score": 92,                                  # 0-100, higher = more trustworthy
    "hard_fail": False,                            # true = reject outright, ignore score
    "reason_codes": ["mrz_checksum_valid", "watchlist_no_match"],
}
```

**Do not change this response shape.** The frontend and (eventually) `risk-scoring-engine`
depend on exactly `score` / `hard_fail` / `reason_codes` with those names and types. If your
module has a case where it must reject outright (a watchlist hit, a failed liveness check, an
AI-image confidence over 99% — see API_CONTRACT.md for which check triggers `hard_fail` in which
module), set `hard_fail: true`. When you do, `score` is ignored by the risk engine, so it doesn't
matter what you put there — but you still need to include the field.

If you need a genuinely new field on the response, don't just add it — that changes the
contract every other service and the frontend agree on. Raise it with the team and update
[API_CONTRACT.md](API_CONTRACT.md) first, then implement it everywhere that reads the contract.

## Running it yourself

```bash
cd services/<your-service>
pip install -r requirements.txt
uvicorn main:app --reload --port <8001|8002|8003>   # see your service's README for its port
```

Then open `http://localhost:<port>/docs` in a browser. FastAPI gives you a free interactive UI
there — expand `POST /screen`, click "Try it out", type a `documents_present` JSON string, attach
a real image file, and hit Execute. You'll see your actual response, no frontend needed.

To confirm nothing's broken after you change something:

```bash
python test_main.py
```

This starts your service itself (no separate terminal, no pytest) and checks: a valid submission
gets a contract-shaped response, a non-image file gets rejected, and a `documents_present` lie
gets rejected. It's not a substitute for testing your actual detection logic — add your own
checks to it (or a new `test_*.py`) as you build real logic in.

## Talking to the frontend without waiting for the frontend team

You don't need the actual React app running to develop against this. Anyone can hit your
endpoint with `curl`:

```bash
curl -X POST http://localhost:8001/screen \
  -F 'uuid=test-123' \
  -F 'documents_present={"passport":true,"selfie":true}' \
  -F 'passport=@/path/to/a/real/photo.jpg' \
  -F 'selfie=@/path/to/a/real/selfie.jpg'
```

## Checklist before you open a PR

- [ ] Response is exactly `{score: number, hard_fail: boolean, reason_codes: string[]}` — no
      renamed/extra/missing fields.
- [ ] You checked `documents_present` before assuming a file exists.
- [ ] You did not remove the existing file-validation step (or if you replaced it with your own,
      it still independently re-checks the file rather than trusting the client — see
      [SECURITY.md](SECURITY.md)).
- [ ] Non-2xx errors return `{"error": "<message>"}` (FastAPI's `HTTPException(status, detail)`
      already does this for you).
- [ ] New third-party library needed? Add it to **your service's own** `requirements.txt` only —
      never share dependencies across services (see [CLAUDE.md](CLAUDE.md)/[AGENTS.md](AGENTS.md)
      coding standards).
- [ ] `python test_main.py` still passes.
