# Operation PRAMAN

Document/identity verification system built as independent microservices plus a frontend.

## Structure

```
frontend/                              # Web UI
services/
  ocr-consistency-check/               # OCR extraction + field consistency checks
  visual-image-forensics/              # Tamper/forgery detection on document images
  biometric-matching/                  # Face/biometric match against ID photo
  risk-scoring-engine/                 # Aggregates signals from other services into a risk score
```

Each service under `services/` is an independently deployable module with its own
dependencies, Dockerfile, and README. `frontend/` is a separate deployable app.

## Getting started

Per-module setup instructions live in each module's own README (TBD as modules are built).
