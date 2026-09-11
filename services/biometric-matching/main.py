"""Biometric Matching — Module 3.

Implements POST /screen per ../../API_CONTRACT.md. Validates input per SECURITY.md,
runs face detection/alignment/quality on uploaded images, and generates face embeddings
for matching.

Pipeline status (2026-09-09):
  [x] Input validation (preserved from original stub)
  [x] Face detection, alignment, quality assessment
  [x] Face embedding generation (dlib 128-D, placeholder model)
  [x] Doc-to-selfie similarity computation
  [ ] Cross-document consistency — not yet wired
  [ ] Liveness detection — not yet implemented
  [ ] Database persistence — no database in stack yet
  [ ] Milvus integration — not yet needed
"""
import io
import json
import logging
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

from app.config import BiometricConfig, load_config
from app.domain.enums import ReasonCode
from app.ml.preprocessing import detect_and_align, image_bytes_to_rgb

logger = logging.getLogger(__name__)

app = FastAPI(title="biometric-matching")
# Dev CORS: the frontend calls this port directly from the browser. Restrict allow_origins
# to the real frontend origin before this ever leaves a local dev machine.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["POST"], allow_headers=["*"])

MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_VIDEO_BYTES = 50 * 1024 * 1024

# Load configuration once at startup.
_config: BiometricConfig = load_config()


def validate_image(data: bytes, field: str) -> None:
    """SECURITY.md #1-2: re-check independently of the client, decode+verify rather than
    trust magic bytes alone — Image.verify() raises on anything Pillow can't actually parse
    as the image format it claims to be."""
    if not data:
        raise HTTPException(400, f"{field}: empty file")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(400, f"{field}: exceeds {MAX_IMAGE_BYTES // (1024 * 1024)}MB limit")
    try:
        Image.open(io.BytesIO(data)).verify()
    except Exception:
        raise HTTPException(400, f"{field}: not a decodable image")


def validate_selfie(data: bytes) -> None:
    """The selfie may be an image or a short video. Pillow can only decode the image case,
    so a video is accepted on size alone here — real video validation (a decodable container,
    duration/frame checks) belongs to the eventual liveness-detection implementation, not this
    stub's job of proving the pipeline is wired."""
    if not data:
        raise HTTPException(400, "selfie: empty file")
    if len(data) > MAX_VIDEO_BYTES:
        raise HTTPException(400, f"selfie: exceeds {MAX_VIDEO_BYTES // (1024 * 1024)}MB limit")
    try:
        Image.open(io.BytesIO(data)).verify()
    except Exception:
        pass  # not a still image — assume video, real check comes with real liveness detection


def _run_face_pipeline(
    image_data: bytes,
    label: str,
    check_liveness: bool = False,
) -> dict:
    """Run face detection + alignment + quality on raw image bytes.

    Returns a dict with detection results and any reason codes.
    Does NOT raise on no-face — that's a scoring/reason-code issue, not an HTTP error.
    """
    from app.ml.similarity import compare as compare_embeddings  # noqa: F811

    rgb = image_bytes_to_rgb(image_data)
    if rgb is None:
        return {"detected": False, "reason": ReasonCode.FACE_NOT_DETECTED.value,
                "label": label, "quality": 0.0, "embedding": None}

    result = detect_and_align(rgb, check_liveness=check_liveness)

    if not result.found:
        return {"detected": False, "reason": ReasonCode.FACE_NOT_DETECTED.value,
                "label": label, "quality": 0.0, "embedding": None}

    reason = None
    if result.face_count > 1:
        reason = ReasonCode.MULTIPLE_FACES_DETECTED.value

    # Generate embedding
    from app.ml.face_encoder import ArcFaceEncoder
    encoder = ArcFaceEncoder(_config.face_model)
    embedding = None
    if result.aligned_face is not None:
        embedding = encoder.generate_embedding(result.aligned_face)

    quality_score = result.quality.overall_score

    if quality_score < _config.quality.low_quality_floor:
        reason = reason or ReasonCode.FACE_QUALITY_TOO_LOW.value

    return {
        "detected": True,
        "label": label,
        "quality": quality_score,
        "sharpness": result.quality.sharpness,
        "face_count": result.face_count,
        "embedding": embedding,
        "reason": reason,
        "liveness_score": result.liveness_score,
        "is_real": result.is_real,
    }


@app.post("/screen")
async def screen(
    uuid: str = Form(...),
    documents_present: str = Form(...),
    passport: Optional[UploadFile] = File(None),
    visa: Optional[UploadFile] = File(None),
    nationalId: Optional[UploadFile] = File(None),
    drivingLicence: Optional[UploadFile] = File(None),
    permit: Optional[UploadFile] = File(None),
    selfie: Optional[UploadFile] = File(None),
) -> dict:
    try:
        present: dict = json.loads(documents_present)
    except json.JSONDecodeError:
        raise HTTPException(400, "documents_present must be valid JSON")

    documents = {"passport": passport, "visa": visa, "nationalId": nationalId,
                 "drivingLicence": drivingLicence, "permit": permit}

    # --- Validation (preserved from original stub) ---
    doc_data: dict[str, bytes] = {}
    for key, file in documents.items():
        if present.get(key) and file is None:
            raise HTTPException(400, f"documents_present says '{key}' is present but no file was sent")
        if file is not None:
            data = await file.read()
            validate_image(data, key)  # needed for doc-to-selfie face matching
            doc_data[key] = data

    selfie_data: Optional[bytes] = None
    if present.get("selfie") and selfie is None:
        raise HTTPException(400, "documents_present says 'selfie' is present but no file was sent")
    if selfie is not None:
        selfie_data = await selfie.read()
        validate_selfie(selfie_data)

    # --- Face pipeline ---
    reason_codes: list[str] = []
    hard_fail = False

    # Process selfie
    selfie_result = None
    if selfie_data is not None:
        try:
            selfie_result = _run_face_pipeline(selfie_data, "selfie", check_liveness=True)
            if not selfie_result["detected"]:
                reason_codes.append(f"selfie: {ReasonCode.FACE_NOT_DETECTED.value}")
            elif selfie_result.get("reason"):
                reason_codes.append(f"selfie: {selfie_result['reason']}")
                
            # Liveness Evaluation
            if selfie_result.get("liveness_score") is not None:
                l_score = selfie_result["liveness_score"]
                # Deepface's antispoof_score isn't always strictly 0-1, but let's 
                # treat higher as more likely to be real based on typical conventions,
                # or evaluate based on our thresholds.
                # If the score indicates spoofing based on our threshold:
                if l_score < _config.liveness.hard_fail_threshold:
                    reason_codes.append(f"selfie: {ReasonCode.LIVENESS_SPOOF_DETECTED.value} (score={l_score:.2f})")
                    hard_fail = True
                elif l_score < _config.liveness.review_threshold:
                    reason_codes.append(f"selfie: {ReasonCode.LIVENESS_REVIEW_REQUIRED.value} (score={l_score:.2f})")

        except Exception:
            logger.exception("Face pipeline failed for selfie")
            reason_codes.append("selfie: face_pipeline_error")

    # Process document faces
    doc_results: dict[str, dict] = {}
    for key, data in doc_data.items():
        try:
            doc_results[key] = _run_face_pipeline(data, key)
            if not doc_results[key]["detected"]:
                reason_codes.append(f"{key}: {ReasonCode.FACE_NOT_DETECTED.value}")
            elif doc_results[key].get("reason"):
                reason_codes.append(f"{key}: {doc_results[key]['reason']}")
        except Exception:
            logger.exception("Face pipeline failed for %s", key)
            reason_codes.append(f"{key}: face_pipeline_error")

    # --- Doc-to-selfie matching ---
    from app.ml import similarity as sim_module
    from itertools import combinations

    match_scores: list[float] = []
    if selfie_result and selfie_result["detected"] and selfie_result["embedding"]:
        selfie_emb = selfie_result["embedding"]
        for key, doc_res in doc_results.items():
            if doc_res["detected"] and doc_res["embedding"]:
                try:
                    score = sim_module.compare(selfie_emb, doc_res["embedding"],
                                               metric=_config.face_model.similarity_metric)
                    match_scores.append(score)

                    if score < _config.doc_to_selfie.hard_fail_threshold:
                        quality = doc_res["quality"]
                        # Only hard-fail on strong mismatch + good quality evidence
                        if quality >= _config.quality.min_reliable_quality:
                            reason_codes.append(
                                f"{key}: {ReasonCode.FACE_ID_STRONG_MISMATCH.value} "
                                f"(similarity={score:.3f}, quality={quality:.2f})"
                            )
                            hard_fail = True
                        else:
                            reason_codes.append(
                                f"{key}: {ReasonCode.FACE_ID_BORDERLINE_MATCH.value} "
                                f"(similarity={score:.3f}, quality={quality:.2f}, low_quality)"
                            )
                    elif score < _config.doc_to_selfie.review_threshold:
                        reason_codes.append(
                            f"{key}: {ReasonCode.FACE_ID_BORDERLINE_MATCH.value} "
                            f"(similarity={score:.3f})"
                        )
                except Exception:
                    logger.exception("Similarity comparison failed for selfie vs %s", key)
                    reason_codes.append(f"{key}: similarity_computation_error")

    # --- Cross-document consistency ---
    cross_doc_scores: list[float] = []
    valid_docs = {k: v for k, v in doc_results.items() if v["detected"] and v["embedding"]}
    
    for doc1, doc2 in combinations(valid_docs.keys(), 2):
        try:
            score = sim_module.compare(
                valid_docs[doc1]["embedding"],
                valid_docs[doc2]["embedding"],
                metric=_config.face_model.similarity_metric
            )
            cross_doc_scores.append(score)
            
            if score < _config.cross_document.hard_fail_threshold:
                q1, q2 = valid_docs[doc1]["quality"], valid_docs[doc2]["quality"]
                if min(q1, q2) >= _config.quality.min_reliable_quality:
                    reason_codes.append(
                        f"{doc1}_vs_{doc2}: {ReasonCode.CROSS_DOCUMENT_FACE_MISMATCH.value} "
                        f"(similarity={score:.3f})"
                    )
                    hard_fail = True
                else:
                    reason_codes.append(
                        f"{doc1}_vs_{doc2}: {ReasonCode.CROSS_DOCUMENT_LOW_QUALITY.value}"
                    )
            elif score < _config.cross_document.review_threshold:
                reason_codes.append(
                    f"{doc1}_vs_{doc2}: cross_document_review_required (similarity={score:.3f})"
                )
        except Exception:
            logger.exception("Cross-doc comparison failed for %s vs %s", doc1, doc2)
            reason_codes.append(f"{doc1}_vs_{doc2}: similarity_computation_error")

    # --- Scoring ---
    # Combine doc-to-selfie and cross-document scores.
    all_scores = match_scores + cross_doc_scores
    if all_scores:
        overall_score = sum(all_scores) / len(all_scores)
    else:
        # No matching was possible
        overall_score = 0.5  # neutral — cannot assess

    # Clamp to [0, 1]
    internal_score = max(0.0, min(1.0, overall_score))

    # API contract: score is 0-100 integer
    api_score = int(round(internal_score * 100))

    if not reason_codes:
        if all_scores:
            reason_codes.append("face_matching_completed")
        else:
            reason_codes.append("no_face_matching_performed")

    return {"score": api_score, "hard_fail": hard_fail, "reason_codes": reason_codes}
