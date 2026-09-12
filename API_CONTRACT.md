# API contract — frontend ↔ detection modules

The frontend doesn't know or care how each module works inside — it only needs every module to
accept the same request shape and return the same response shape. This is that shape. Any of
`ocr-consistency-check`, `visual-image-forensics`, `biometric-matching` must implement it
exactly as written here; `risk-scoring-engine` is the one service that instead *consumes* 3 of
these responses (see bottom).

Enforced today only on the frontend side, in
[frontend/src/lib/submitScreening.ts](frontend/src/lib/submitScreening.ts) — no service has an
implementation yet.

## `POST /screen`

**Request** — `multipart/form-data`:

| Field | Type | Description |
|---|---|---|
| `uuid` | string | Correlates this submission across all 3 modules + the risk engine. Generated client-side (`crypto.randomUUID()`). |
| `documents_present` | string (JSON) | `{"passport": true, "visa": true, "nationalId": true, "drivingLicence": false, "permit": false, "selfie": true}` — which of the 6 slots were actually uploaded. Always check this before looking for a file field; optional documents are frequently absent. |
| `passport`, `visa`, `nationalId`, `drivingLicence`, `permit`, `selfie` | file | Present only when `documents_present` says `true` for that key. Image files unless noted; `selfie` may be image or video. |

**Response** — `200 OK`, `application/json`:

```json
{
  "score": 78,
  "hard_fail": false,
  "reason_codes": ["mrz_checksum_valid", "watchlist_no_match"]
}
```

| Field | Type | Description |
|---|---|---|
| `score` | number, 0–100 | Higher = more trustworthy. Ignored by the risk engine if `hard_fail` is true. |
| `hard_fail` | boolean | true = this module alone is grounds for an outright reject (e.g. watchlist hit, liveness failure, AI-image confidence > 99%). |
| `reason_codes` | string[] | Machine-readable codes explaining the score/flag — the risk engine surfaces these to the officer in plain language, so make them specific (`"liveness_check_failed"`, not `"failed"`). |

**Errors**: return a non-2xx status with `{"error": "<message>"}` on the body for anything that
isn't a normal score (bad/corrupt file, missing required field, internal error). The frontend
treats any non-2xx or network failure as "module unreachable" and does not guess a score.

**Timing**: modules are called in parallel and are expected to respond independently — a slow
module does not block the others. `ocr-consistency-check`'s Stage 1b checks are pure
arithmetic/lookup and should be the fastest to answer in practice.

## How `risk-scoring-engine` fits in

It is not called by the frontend directly — something (today: nothing; eventually the frontend,
a gateway, or one of the 3 modules) collects all 3 `POST /screen` responses for one `uuid` and
forwards them to `risk-scoring-engine`, which applies:

```
IF any hard_fail == true  → REJECT, using that module's reason_codes (scores ignored)
ELSE                       → fuse score_ocr + score_forensics + score_biometric into one
                             risk score, decide ACCEPT / MANUAL_REVIEW, plain-language reasons
```

Its own request/response contract isn't defined yet — write it here when that service is built.
