# Operation PRAMAN

**Smart India Hackathon 2026 — Problem Statement [SIH26188](https://sih2026.vuce.in/ps/SIH26188)**

**AI-Based Fake Identity & Document Screening System**

| | |
|---|---|
| **Organization** | Ministry of Home Affairs (Sashastra Seema Bal, Police II Division) |
| **Category** | Software |
| **Theme** | Blockchain & Cybersecurity |

## Problem

Border checkpoints rely on human inspection and basic database lookups to catch fraudulent
travel documents, altered photographs, forged stamps, and identity impersonation — slow and
error-prone. We're building an AI-powered platform that analyzes identity documents, detects
tampering/forgery, validates information against databases, and generates a risk score so
security personnel can decide faster and more accurately.

## Architecture

A user submits (1) photo(s) of their ID document(s) and (2) a live selfie/video. Both inputs
go to all three detection modules **simultaneously** — they run fully in parallel, not
sequentially. Each module returns the same shape of result: a score 0–100, a `hard_fail` flag,
and plain-language reason codes.

```
                    INPUT 1: Document Photo(s)      INPUT 2: Live Selfie/Video
                              |                              |
              +---------------+---------------+--------------+
              |                                |              |
              v                                v              v
    MODULE 1: OCR, Extraction          MODULE 2: Visual /   MODULE 3: Biometric
    & Watchlist                        Image Forensics      Matching
    - MRZ / general OCR                - AI-generated image  - Liveness detection
    - Barcode/QR decode                  detector             - Doc-to-selfie face
    - MRZ checksum, field format       - Splice/tamper          matcher
    - Blacklist/watchlist fuzzy          forensics            - Cross-document face
      match (hard_fail source)         - Guilloché/background   consistency
    - Cross-doc field matcher            checker
    - Base marker verifier             (hard_fail: AI-image    (hard_fail: liveness
                                         confidence > 99%)       check fails)
              |                                |              |
         Score A + hard_fail             Score B + hard_fail   Score C + hard_fail
              |                                |              |
              +---------------+---------------+--------------+
                              v
              HARD-FAIL BROADCAST: if any module hard_fail = true,
              it overrides everything else
                              |
                              v
                RISK SCORING ENGINE (fusion)
      hard_fail=true  -> REJECT immediately (using that module's reason codes)
      hard_fail=false -> fuse Score A + Score B + Score C (weighted rules /
                          gradient-boosted model) into one risk score
                              |
                              v
              FINAL OUTPUT: ACCEPT / MANUAL REVIEW / REJECT
              + plain-language reason codes
```

Full diagram: `SIH26188_Architecture_Flow_Diagram.pdf` (not committed — ask a team lead for it).

## Structure

```
frontend/                              # Web UI for checkpoint personnel
services/
  ocr-consistency-check/               # Module 1: OCR, extraction & watchlist checks -> Score A
  visual-image-forensics/              # Module 2: AI-image / tamper / guilloché forensics -> Score B
  biometric-matching/                  # Module 3: liveness + face matching -> Score C
  risk-scoring-engine/                 # Hard-fail broadcast + fusion -> final decision
```

Each service under `services/` is an independently deployable module with its own
`Dockerfile`, `.env.example`, and `requirements.txt` (dependencies differ per module — OCR,
CV/forensics, biometrics, and the scoring model each need different libraries, so they're
kept separate rather than shared). `frontend/` is a separate deployable app.

## Branches

- `main` — stable/demo-ready
- `dev` — active development, merge here first

## Getting started

Per-module setup instructions live in each module's own README (TBD as modules are built).
`docker-compose.yml` at the repo root runs everything together for local dev.
