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

## Expected outcomes

- Reduce verification time from minutes to seconds
- Improve forged/tampered document detection
- Standardize screening across checkpoints
- Enable data-driven risk assessment
- Create digital investigation trails

## Structure

```
frontend/                              # Web UI for checkpoint personnel
services/
  ocr-consistency-check/               # Extracts data from passports/visas/IDs/permits, validates against standards
  visual-image-forensics/              # Detects tampering: photo replacement, text manipulation, forged stamps
  biometric-matching/                  # Matches document photo to the person presenting it
  risk-scoring-engine/                 # Aggregates signals from other services into a risk score/decision
```

Each service under `services/` is an independently deployable module with its own
dependencies, Dockerfile, and README. `frontend/` is a separate deployable app.

## Branches

- `main` — stable/demo-ready
- `dev` — active development, merge here first

## Getting started

Per-module setup instructions live in each module's own README (TBD as modules are built).
