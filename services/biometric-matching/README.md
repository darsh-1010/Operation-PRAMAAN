# Biometric Matching — Module 3

Matches selfie/live capture against the ID document photo.

Implements `POST /screen` per [API_CONTRACT.md](../../API_CONTRACT.md).

## Current status (2026-09-09)

| Component | Status |
|---|---|
| Input validation | ✅ Implemented (per SECURITY.md) |
| Face detection | ✅ dlib HOG via `face_recognition` |
| Face alignment | ✅ Eye-landmark similarity transform |
| Face quality | ✅ Sharpness (Laplacian), face-size ratio |
| Face embedding | ✅ dlib ResNet 128-D (placeholder model) |
| Doc-to-selfie match | ✅ Cosine similarity |
| Cross-document | ⬜ Not yet wired |
| Liveness detection | ⬜ Not yet implemented |
| Database persistence | ⬜ No database in stack |
| Milvus | ⬜ Not yet needed |

## Architecture

```
POST /screen
  │
  ├─ validate_image / validate_selfie  (SECURITY.md)
  │
  ├─ _run_face_pipeline (per image)
  │   ├─ image_bytes_to_rgb
  │   ├─ detect_and_align (detection + landmarks + alignment + quality)
  │   └─ DlibFaceEncoder.generate_embedding
  │
  ├─ doc-to-selfie similarity (cosine)
  │
  └─ {score: 0-100, hard_fail, reason_codes}
```

## Structure

```
app/
  domain/
    enums.py         # CheckType, Decision, ReasonCode
    models.py        # BoundingBox, QualityMetrics, FaceDetectionResult, FaceEmbedding, MatchResult
  ml/
    preprocessing.py # face detection, alignment, quality (dlib/face_recognition)
    face_encoder.py  # FaceEncoder ABC + DlibFaceEncoder
    similarity.py    # cosine_similarity, compare()
  config.py          # BiometricConfig loader (reads configs/thresholds.yaml)
configs/
  thresholds.yaml    # configurable thresholds (PLACEHOLDER values)
```

## Model

| Field | Value |
|---|---|
| model_name | `dlib-resnet-v1` |
| model_version | `0.1.0-placeholder` |
| embedding_dimension | 128 |
| similarity_metric | cosine |
| preprocessing | eye-landmark alignment |

> **⚠️ Not production-calibrated.** Thresholds are initial placeholders.
> The model has not been validated against genuine/impostor data.

## Dev

```bash
cd services/biometric-matching
pip install -r requirements.txt
uvicorn main:app --reload --port 8003
python test_main.py   # runnable self-check
```

## Configuration

Thresholds live in `configs/thresholds.yaml`. Override the path via:
```bash
BIOMETRIC_CONFIG_PATH=/path/to/custom.yaml
```
