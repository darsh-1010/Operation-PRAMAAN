# Biometric Module 3 — Development Log

## 2026-09-09 — Face Preprocessing and Match Pipeline

Branch:
aayush/feat/face-preprocessing

Status:
Implemented

Summary:
Added the core face preprocessing pipeline (detection, alignment, quality) and a model-agnostic face encoder abstraction. Replaced the hardcoded stub in `POST /screen` with real doc-to-selfie similarity calculation while preserving the existing input validation and API contract.

Files/areas changed:
- `services/biometric-matching/app/domain/*`: Domain data models (BoundingBox, QualityMetrics) and enums.
- `services/biometric-matching/app/ml/*`: Preprocessing, Face Encoder abstraction, and Similarity metrics.
- `services/biometric-matching/app/config.py`, `configs/thresholds.yaml`: Configuration loader and uncalibrated thresholds.
- `services/biometric-matching/main.py`: Wired real face pipeline into the API.
- `services/biometric-matching/test_main.py`: Expanded tests to cover face pipeline scenarios.
- `services/biometric-matching/requirements.txt`: Added `pyyaml`.

Tests:
- Contract tests preserved (400 on bad files/missing inputs).
- Face pipeline tests added (200 on no-face image with correct `FACE_NOT_DETECTED` reason code).

Database:
- No schema changes (database layer not yet in stack).

API:
- No external API change. `POST /screen` response contract exactly preserved (`score`, `hard_fail`, `reason_codes`).

Model:
- Initial placeholder provider: `dlib-resnet-v1` via `face_recognition` library.

Known limitations:
- Thresholds are placeholders and must be validated/calibrated.
- Liveness detection not yet implemented.
- Cross-document face matching not yet wired.
- No database persistence.

Next step:
- Implement cross-document consistency matching.
