# Risk Scoring Engine

Aggregates outputs from the other services into a final risk score/decision.
# Risk Scoring Engine — Operation PRAMAN

Combines signals from OCR, tampering detection, and photo-match (plus an
AI-generated-document flag) into one risk score + decision, sent back to
the OCR module so it can update its database record.

## Flow (two stages, because modules call us independently over time)

**Stage 1 — flags (arrive first, fast).**
OCR and the AI-doc-detector each `POST /flag-check` as soon as they know
their flag. The moment *either* is `true`, we reject immediately — we
don't wait for the other one, and this is where a "stop other modules"
signal should go out (not wired up yet, no endpoint exists on the other
services for it).

**Stage 2 — scores (only once both flags are confirmed false).**
OCR, tampering, and photo-match each `POST /submit-score` whenever their
score is ready. We hold onto whatever arrives until all 3 are in, then
compute:

```
score = 0.25 × OCR + 0.40 × Tampering + 0.35 × Photo-match
```

Bands: `score ≥ 80 → PASS`, `40 ≤ score < 80 → MANUAL_REVIEW`,
`score < 40 → FAIL`.

Photo-match also carries its own `hard_fail` — if that's true when its
score arrives, we reject right there even though the flag stage already
passed.

**Race safety.** Because every module posts independently and in any
order, a score can arrive before both flags are confirmed — it's just
held (`WAITING_ON_FLAGS`) until they clear. And a flag can arrive `true`
even after some scores are already in — that's still an immediate reject.
Nothing is decided until we know it's safe to decide.

**Final output** sent back: `{uuid, score, decision}` only — no reasons
in this payload. Reasons (from OCR's `reasons`, tamper's derived reason
text, photo-match's `reason_codes`, and a flag's own name if that's what
triggered a reject) are printed to the service's console/logs at the
moment of decision, for explainability/audit — just never sent back in
the DB-update payload itself.

## Timeout / expiry (no more hanging forever)

If a `uuid` sits incomplete for longer than `RISK_ENGINE_TIMEOUT_SECONDS`
(default 300s / 5 min — env-var configurable), a background sweeper
(runs every 30s) auto-escalates it to `MANUAL_REVIEW` instead of leaving
it stuck in memory with no decision ever reached, in case a module
crashed or never called back. `score` is left `null` in that case rather
than a fake number, since it genuinely wasn't computable — `decision`
is what matters here.

Every finalized result — normal completion, an outright reject, or a
timeout escalation — is saved and retrievable via `GET /result/{uuid}`,
since a crashed module obviously isn't the one that's going to come
back and collect it.

## Files

- `store.py` — per-uuid in-memory state (which flags/scores have arrived
  so far). Single-process only — see the note at the top of the file if
  this ever needs to run as multiple instances.
- `scoring.py` — the actual math: weights, bands, tamper-score → reason
  mapping.
- `main.py` — FastAPI app, `POST /flag-check` and `POST /submit-score`.
- `ledger.py`, `ledger_db.py`, `chain.py`, `anchor.py`, `ledger_routes.py`, `contracts/` —
  blockchain anchoring of every final decision + `GET /ledger/*`. See [LEDGER.md](LEDGER.md).
- `requirements.txt`

## Module payload shapes (confirmed so far — may still change)

| Module | Endpoint | Payload |
|---|---|---|
| OCR | `/flag-check` then `/submit-score` | `{uuid, module: "ocr", flag}` then `{uuid, module: "ocr", ocr: {score, reasons}}` |
| Visual-forensics (tampering + AI-generated-doc check) | `/flag-check` then `/submit-score` | `{uuid, module: "forensics", flag}` then `{uuid, module: "tamper", tamper: {score}}` — score is always exactly 100 / 60 / 40 / 0, no reasons field (we derive the reason text ourselves from the value) |
| Photo-match | `/submit-score` only | `{uuid, module: "photo", photo: {score, hard_fail, reasons}}` |

There is no separate AI-generated-document service — that check is folded
into visual-forensics's own `hard_fail`/flag.

## Open items / things to confirm with the team

- **Who calls `/flag-check` vs `/submit-score` and when** — this needs to
  be communicated to the OCR, AI-doc-detector, tampering, and photo-match
  teams; nothing calls these endpoints automatically.
- **"Stop other modules" signal** — no endpoint exists yet on the other
  3 services to actually receive this; today the reject just stops us
  from going further, it doesn't reach back out to cancel their work.
- **Who polls `/result/{uuid}` after a timeout escalation** — mostly
  solved now via the `OCR_CALLBACK_URL` push below, but only once that
  URL is actually configured.
- **`score: null` on timeout** — confirm this convention (vs. some
  numeric placeholder) works for whatever consumes `/result/{uuid}` or
  the push below.
- **`OCR_CALLBACK_URL`** — set this in `.env` once OCR gives us their
  endpoint, and every finalized decision (normal, reject, or timeout)
  gets pushed there automatically as `{uuid, score, decision}`. Until
  it's set, nothing is pushed — results just sit in `/result/{uuid}`
  for polling. A failed push is logged but never breaks anything else.
- **AI-doc-detector** — still training on GPU, not wired into a live
  call yet.
- **Multi-instance deployment** — `store.py` is a single-process dict.
  Fine for the demo; would need Redis or a DB if this ever runs behind
  a load balancer with multiple replicas.

## Run locally

```bash
pip install -r requirements.txt
uvicorn main:app --reload --port 8004
```
