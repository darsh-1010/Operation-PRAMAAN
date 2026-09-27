# API contract — frontend ↔ detection modules

The frontend doesn't know or care how each module works inside — it only needs every module to
accept the same request shape and return the same response shape. This is that shape. Any of
`ocr-consistency-check`, `visual-image-forensics`, `biometric-matching` must implement it
exactly as written here; `risk-scoring-engine` is the one service that instead *consumes* 3 of
these responses (see bottom).

Enforced on the frontend side in
[frontend/src/lib/submitScreening.ts](frontend/src/lib/submitScreening.ts). Implemented today by
`ocr-consistency-check` and `biometric-matching`; `visual-image-forensics` still returns a stub
result (see its `main.py` TODO).

## `POST /screen`

**Request** — `multipart/form-data`:

| Field | Type | Description |
|---|---|---|
| `uuid` | string (UUID) | Correlates this submission across all 3 modules + the risk engine. **Issued by the risk engine** (`POST /sessions`) — modules' reports on any other id are refused. |
| `documents_present` | string (JSON) | `{"passport": true, "voterId": false, "citizenship": false, "nationalId": true, "visa": false, "drivingLicence": false, "permit": false, "selfie": true}` — which slots were actually uploaded. Always check this before looking for a file field; optional documents are frequently absent. |
| `passport`, `visa`, `nationalId` (Aadhaar / other national ID), `voterId` (Indian EPIC), `citizenship` (Nepali citizenship certificate), `drivingLicence`, `permit`, `selfie` | file | Present only when `documents_present` says `true` for that key. Still images. `selfie` is a live camera capture and is required by the UI. |

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
| `score` | number 0–100, or `null` | Higher = more trustworthy. `null` = the module could not assess this submission at all (never invent a number) — the risk engine then caps the decision at MANUAL_REVIEW. Ignored if `hard_fail` is true. |
| `hard_fail` | boolean | true = this module alone is grounds for an outright reject (e.g. watchlist hit, liveness failure, AI-image confidence > 99%). |
| `reason_codes` | string[] | Machine-readable codes explaining the score/flag — the risk engine surfaces these to the officer in plain language, so make them specific (`"liveness_check_failed"`, not `"failed"`). |
| `review_required` | boolean, optional | true = a human must look whatever the score (e.g. Aadhaar QR unverifiable, Nepali citizenship certificate). Capped at MANUAL_REVIEW. |

**Errors**: return a non-2xx status with `{"error": "<message>"}` on the body for anything that
isn't a normal score (bad/corrupt file, missing required field, internal error). The frontend
treats any non-2xx or network failure as "module unreachable" and does not guess a score.

**Timing**: modules are called in parallel and are expected to respond independently — a slow
module does not block the others. `ocr-consistency-check`'s Stage 1b checks are pure
arithmetic/lookup and should be the fastest to answer in practice.

## How `risk-scoring-engine` fits in

The frontend calls it twice: `POST /sessions` → `{"uuid": …}` before a screening, and
`GET /result/{uuid}` after. Each module pushes its own result to it as a side effect of `/screen`
(`POST /flag-check`, `POST /submit-score`), authenticated with **its own** bearer token
(`Authorization: Bearer <RISK_ENGINE_TOKEN>`, matching the engine's `RISK_TOKEN_<MODULE>`). A token
only authorizes that module's inputs (the OCR token can't submit a face score). Pushes may carry
`evidence: ["<kind>:<sha256 of the uploaded bytes>", …]`, which is sealed into the
blockchain-anchored decision record (see `services/risk-scoring-engine/LEDGER.md`). It applies:

```
IF any hard_fail == true  → REJECT, using that module's reason_codes (scores ignored)
ELSE                       → fuse score_ocr + score_forensics + score_biometric into one
                             risk score, decide ACCEPT / MANUAL_REVIEW, plain-language reasons
```

Payload shapes: `services/risk-scoring-engine/schemas.py`.
