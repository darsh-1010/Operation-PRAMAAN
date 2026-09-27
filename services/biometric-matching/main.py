"""Biometric Matching — Module 3.

Implements POST /screen per ../../API_CONTRACT.md. Validates input per SECURITY.md,
runs face detection/alignment/quality on uploaded images, and generates face embeddings
for matching.

Pipeline status:
  [x] Input validation (preserved from original stub)
  [x] Face detection, alignment, quality assessment
  [x] Face embedding generation (ArcFace 512-D, via DeepFace)
  [x] Doc-to-selfie similarity computation
  [x] Cross-document consistency
  [x] Liveness detection (FASNet via DeepFace)
  [x] Database persistence (Postgres via db.py)
  [x] Milvus integration (1:N Blacklist & Failure tracking)
"""
import asyncio
import io
import json
import logging
import os
import uuid as py_uuid
from typing import Optional

import httpx
from aiobreaker import CircuitBreakerError
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

import evidence
from app.config import BiometricConfig, load_config
from app.db import BiometricDB
from app.vector_db import MilvusClientWrapper
from app.domain.enums import ReasonCode
from app.ml.preprocessing import detect_and_align, image_bytes_to_rgb
from inference_pool import InferenceCrashed, run_isolated
from rate_limit import SCREEN_RATE_LIMIT, limiter
from result_cache import ResultCache
from risk_engine_breaker import RISK_ENGINE_BREAKER

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

RISK_ENGINE_URL = os.environ.get("RISK_ENGINE_URL", "http://localhost:8004").rstrip("/")
# Must equal risk-scoring-engine's RISK_TOKEN_BIOMETRIC.
RISK_ENGINE_TOKEN = os.environ.get("RISK_ENGINE_TOKEN", "").strip()


@RISK_ENGINE_BREAKER
async def _push_to_risk_engine(uuid: str, score: int, hard_fail: bool, reasons: list[str], evidence_refs: list[str]) -> None:
    async with httpx.AsyncClient(timeout=5.0, headers={"Authorization": f"Bearer {RISK_ENGINE_TOKEN}"}) as client:
        resp = await client.post(
            f"{RISK_ENGINE_URL}/submit-score",
            json={"uuid": uuid, "module": "photo", "photo": {"score": score, "hard_fail": hard_fail, "reasons": reasons},
                  "evidence": evidence_refs},
        )
    # Only 5xx counts towards the breaker; a 4xx (e.g. unknown screening id) is that request's
    # problem, and letting those trip it would let fake ids block every real screening.
    if resp.status_code >= 500:
        resp.raise_for_status()
    if resp.status_code >= 400:
        logger.error("uuid=%s risk-scoring-engine refused biometric result: %s %s", uuid, resp.status_code, resp.text[:200])
        return
    logger.info("uuid=%s pushed to risk-scoring-engine (score=%s, hard_fail=%s)", uuid, score, hard_fail)


async def _notify_risk_engine(uuid: str, score: int, hard_fail: bool, reasons: list[str], evidence_refs: list[str]) -> None:
    """Push this module's score to risk-scoring-engine as the "photo" module (see
    ../../services/risk-scoring-engine/README.md) — photo-match only ever calls /submit-score,
    never /flag-check; its hard_fail travels inside the score payload instead. Best-effort:
    the risk engine being down must never break this service's own /screen response.
    Circuit-breaker-backed (see risk_engine_breaker.py) so a down risk-scoring-engine fails
    fast instead of costing a full httpx timeout on every single request."""
    if not RISK_ENGINE_TOKEN:
        logger.error("uuid=%s RISK_ENGINE_TOKEN not set — result NOT sent to risk-scoring-engine", uuid)
        return
    try:
        await _push_to_risk_engine(uuid, score, hard_fail, reasons, evidence_refs)
    except CircuitBreakerError:
        logger.warning("uuid=%s risk-scoring-engine circuit open, skipping push", uuid)
    except httpx.HTTPError as exc:
        logger.warning("uuid=%s risk-scoring-engine unreachable, skipping push: %s", uuid, exc)

app = FastAPI(title="biometric-matching")
# Dev CORS: the frontend calls this port directly from the browser. Restrict allow_origins
# to the real frontend origin before this ever leaves a local dev machine.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["POST"], allow_headers=["*"])

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Exposes /metrics (request count/latency/in-flight, per route+status) for Prometheus.
Instrumentator().instrument(app).expose(app)

MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_VIDEO_BYTES = 50 * 1024 * 1024

# Load configuration and DB connection once at startup.
_config: BiometricConfig = load_config()
_db = BiometricDB.get_instance()
_cache = ResultCache(namespace="biometric")
_milvus = MilvusClientWrapper(_config.milvus.host, _config.milvus.port)


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
    """A still image only. Video liveness isn't implemented, so a video "selfie" used to be
    accepted on size alone and then never actually checked by anything — accepting one would
    mean accepting a selfie nobody looked at. The frontend only captures stills from the camera."""
    validate_image(data, "selfie")


def _keep_selfie(uuid: str, selfie_data: Optional[bytes]) -> tuple[list[str], list[str]]:
    """(evidence refs, problems). Documents are retained by ocr-consistency-check; this module
    keeps the selfie. The ref is sent even if storage fails, but the failure is surfaced."""
    if selfie_data is None:
        return [], []
    try:
        return [evidence.store(uuid, "selfie", selfie_data)], []
    except evidence.EvidenceError as err:
        logger.error("uuid=%s selfie evidence not retained: %s", uuid, err)
        return [evidence.evidence_ref("selfie", selfie_data)], ["EVIDENCE_NOT_RETAINED"]


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
@limiter.limit(SCREEN_RATE_LIMIT)
async def screen(
    request: Request,
    uuid: str = Form(...),
    documents_present: str = Form(...),
    passport: Optional[UploadFile] = File(None),
    visa: Optional[UploadFile] = File(None),
    nationalId: Optional[UploadFile] = File(None),
    drivingLicence: Optional[UploadFile] = File(None),
    permit: Optional[UploadFile] = File(None),
    voterId: Optional[UploadFile] = File(None),
    citizenship: Optional[UploadFile] = File(None),
    selfie: Optional[UploadFile] = File(None),
) -> dict:
    try:
        present: dict = json.loads(documents_present)
    except json.JSONDecodeError:
        raise HTTPException(400, "documents_present must be valid JSON")

    documents = {"passport": passport, "visa": visa, "nationalId": nationalId,
                 "drivingLicence": drivingLicence, "permit": permit, "voterId": voterId, "citizenship": citizenship}

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

    logger.info("uuid=%s /screen received: docs=%s selfie=%s", uuid, list(doc_data.keys()), selfie_data is not None)
    evidence_refs, evidence_problem = _keep_selfie(uuid, selfie_data)

    # Same exact set of files re-submitted (retry, refresh, duplicate kiosk scan)? The face
    # pipeline is deterministic for identical input, so skip re-running detection/embedding/
    # matching entirely and reuse last time's result. Order is fixed (docs by key, then
    # selfie) so the same submission always fingerprints the same way.
    fingerprint = ResultCache.fingerprint(
        *(doc_data[k] for k in sorted(doc_data)), *( [selfie_data] if selfie_data is not None else [] )
    )
    cached = _cache.get(fingerprint)
    if cached is not None:
        logger.info("uuid=%s /screen cache hit (fingerprint=%s)", uuid, fingerprint[:12])
        await _notify_risk_engine(uuid, cached["score"], cached["hard_fail"], cached["reason_codes"] + evidence_problem, evidence_refs)
        return cached

    # --- Face pipeline ---
    # Face detection + embedding is CPU/GPU-bound (blocks a thread, not the event loop) and
    # each image is independent of the others until the matching step below — run them off
    # the event loop and concurrently instead of one at a time.
    reason_codes: list[str] = []
    hard_fail = False

    async def _pipeline(data: bytes, label: str, check_liveness: bool = False) -> dict:
        try:
            # Isolated worker process (see inference_pool.py): a native crash in OpenCV/
            # DeepFace only fails this one image instead of the whole service.
            return await run_isolated(_run_face_pipeline, data, label, check_liveness)
        except InferenceCrashed:
            logger.error("Face pipeline worker crashed for %s", label)
            return {"detected": False, "reason": None, "label": label, "quality": 0.0,
                    "embedding": None, "pipeline_error": True}
        except Exception:
            logger.exception("Face pipeline failed for %s", label)
            return {"detected": False, "reason": None, "label": label, "quality": 0.0,
                    "embedding": None, "pipeline_error": True}

    selfie_task = _pipeline(selfie_data, "selfie", check_liveness=True) if selfie_data is not None else None
    doc_tasks = {key: _pipeline(data, key) for key, data in doc_data.items()}
    gathered = await asyncio.gather(*([selfie_task] if selfie_task else []), *doc_tasks.values())
    it = iter(gathered)
    selfie_result = next(it) if selfie_task else None
    doc_results: dict[str, dict] = dict(zip(doc_tasks.keys(), it))

    if selfie_result is not None:
        if selfie_result.get("pipeline_error"):
            reason_codes.append("selfie: face_pipeline_error")
        else:
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

            # 1:N Blacklist Check (Milvus)
            if selfie_result.get("embedding") is not None and not hard_fail:
                blacklist_match = _milvus.search_face(
                    selfie_result["embedding"], 
                    "blacklisted", 
                    _config.vector_search.blacklist_match_threshold
                )
                if blacklist_match:
                    reason_codes.append(f"selfie: BLACKLISTED_PERSON_DETECTED (similarity={blacklist_match['similarity']:.2f})")
                    hard_fail = True

    # Process document faces (pipeline already ran concurrently above)
    for key, result in doc_results.items():
        if result.get("pipeline_error"):
            reason_codes.append(f"{key}: face_pipeline_error")
        elif not result["detected"]:
            reason_codes.append(f"{key}: {ReasonCode.FACE_NOT_DETECTED.value}")
        elif result.get("reason"):
            reason_codes.append(f"{key}: {result['reason']}")

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
    # Combine signals using configured fusion weights
    liveness_score_val = selfie_result.get("liveness_score", 0.5) if selfie_result else 0.5
    avg_doc_score = sum(match_scores) / len(match_scores) if match_scores else 0.5
    avg_cross_doc = sum(cross_doc_scores) / len(cross_doc_scores) if cross_doc_scores else 0.5

    active_weights = {}
    if selfie_result and selfie_result.get("liveness_score") is not None:
        active_weights["liveness"] = _config.fusion.liveness_weight
    if match_scores:
        active_weights["doc_match"] = _config.fusion.doc_match_weight
    if cross_doc_scores:
        active_weights["cross_doc"] = _config.fusion.cross_document_weight

    total_weight = sum(active_weights.values())
    
    if total_weight > 0:
        overall_score = 0.0
        if "liveness" in active_weights:
            overall_score += liveness_score_val * (active_weights["liveness"] / total_weight)
        if "doc_match" in active_weights:
            overall_score += avg_doc_score * (active_weights["doc_match"] / total_weight)
        if "cross_doc" in active_weights:
            overall_score += avg_cross_doc * (active_weights["cross_doc"] / total_weight)
    else:
        overall_score = 0.0  # nothing could be assessed — never a "neutral" pass-through score

    # Clamp to [0, 1]
    internal_score = max(0.0, min(1.0, overall_score))

    if selfie_data is None:
        reason_codes.append("SELFIE_MISSING: a live selfie is required to verify the holder")
    if not match_scores:
        # The core job is binding the person to the document. Without a doc-to-selfie match that
        # never happened, so the face score is 0 — not the old "neutral" 0.5, which let a genuine
        # passport presented by anyone reach PASS with no face check at all.
        internal_score = 0.0
        reason_codes.append("FACE_MATCH_NOT_PERFORMED: holder not verified against the document photo")
    api_score = int(round(internal_score * 100))  # API contract: score is 0-100 integer

    if not reason_codes:
        reason_codes.append("face_matching_completed")

    logger.info("uuid=%s /screen result: score=%s hard_fail=%s reasons=%s", uuid, api_score, hard_fail, reason_codes)

    documents_checked = list(doc_data.keys()) + (["selfie"] if selfie_data is not None else [])

    # 1:N Failure Tracking (Milvus)
    if hard_fail and selfie_result and selfie_result.get("embedding"):
        if not any("BLACKLISTED" in r for r in reason_codes):
            _milvus.upsert_face(uuid, selfie_result["embedding"], "failed")
    elif not hard_fail and selfie_result and selfie_result.get("embedding"):
        fail_match = _milvus.search_face(
            selfie_result["embedding"], 
            "failed", 
            _config.vector_search.blacklist_match_threshold
        )
        if fail_match:
            _milvus.delete_face_by_uuid(fail_match["uuid"])

    await run_in_threadpool(
        _db.save_result, str(py_uuid.uuid4()), uuid, api_score, hard_fail, reason_codes, documents_checked
    )

    result = {"score": api_score, "hard_fail": hard_fail, "reason_codes": reason_codes}
    _cache.set(fingerprint, result)
    await _notify_risk_engine(uuid, api_score, hard_fail, reason_codes + evidence_problem, evidence_refs)
    return result


