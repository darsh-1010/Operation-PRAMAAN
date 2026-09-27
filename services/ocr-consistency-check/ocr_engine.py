"""Optimized OCR Engine using PaddleOCR with fallback support."""

from __future__ import annotations
from dataclasses import dataclass, field
import logging
import os
from typing import Any, Dict, List, Optional
import cv2
import numpy as np

from ocr_tesseract import extract_tesseract

logger = logging.getLogger("ocr_engine")


@dataclass
class TextBlock:
    """Individual OCR text block with coordinates and confidence."""
    text: str
    confidence: float
    bbox: Dict[str, float]
    polygon: List[List[float]] = field(default_factory=list)


@dataclass
class OCRResult:
    """Consolidated OCR result across an image."""
    blocks: List[TextBlock]
    full_text: str
    lines: List[str]
    engine: str
    model_version: str
    average_confidence: float


class OCREngine:
    """Singleton OCR coordinator supporting optimized PaddleOCR with Tesseract fallback."""

    _instance: Optional["OCREngine"] = None
    _paddle_ocr: Any = None
    _engine_name: str = "paddleocr-3.7"

    @classmethod
    def get_instance(cls) -> "OCREngine":
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._initialize()
        return cls._instance

    def _initialize(self) -> None:
        """Initialize PaddleOCR with high-speed settings avoiding 3D unwarping overhead."""
        try:
            os.environ["FLAGS_use_mkldnn"] = "0"
            os.environ["FLAGS_enable_pir_api"] = "0"
            from paddleocr import PaddleOCR
            lang = os.environ.get("OCR_LANG", "en")
            logger.info("Initializing PaddleOCR (fast pipeline, lang=%s)...", lang)

            init_kwargs = {
                "text_detection_model_name": "PP-OCRv6_small_det",
                "text_recognition_model_name": "PP-OCRv6_small_rec",
                "enable_mkldnn": False,
                "use_doc_unwarping": False,
                "use_doc_orientation_classify": False,
                "use_textline_orientation": False,
            }
            try:
                self._paddle_ocr = PaddleOCR(**init_kwargs)
            except Exception as err:
                logger.warning("PP-OCRv6_small load failed (%s). Retrying default...", err)
                self._paddle_ocr = PaddleOCR(lang=lang, enable_mkldnn=False, use_doc_unwarping=False)

            self._engine_name = "paddleocr-v6-small"
            logger.info("PaddleOCR engine (PP-OCRv6_small) initialized successfully.")
        except Exception as err:
            logger.warning("PaddleOCR init failed (%s). Fallback to Tesseract will be used.", err)
            self._paddle_ocr = None
            self._engine_name = "tesseract-fallback"

    def extract_text(self, image: np.ndarray, lang: Optional[str] = None) -> OCRResult:
        if lang and lang.lower() not in ("en", "eng"):
            from multilingual_ocr import MultilingualOCREngine
            return MultilingualOCREngine.get_instance().extract_text(image, lang=lang)

        engine_cfg = os.environ.get("OCR_ENGINE", "paddleocr").lower()
        use_paddle = engine_cfg in ("paddleocr", "paddle") or os.environ.get("USE_PADDLEOCR", "false").lower() == "true"
        if use_paddle and self._paddle_ocr is not None:
            try:
                return self._extract_paddle(image)
            except Exception as err:
                logger.error("PaddleOCR inference failed: %s. Falling back to Tesseract.", err)

        return extract_tesseract(image, TextBlock, OCRResult)

    def _extract_paddle(self, image: np.ndarray) -> OCRResult:
        """Run fast inference with pre-scaling for large phone camera captures."""
        h, w = image.shape[:2]
        max_dim = max(h, w)
        scale = 1.0
        proc_img = image
        if max_dim > 1800:
            scale = 1800.0 / max_dim
            proc_img = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)

        try:
            raw_res = list(self._paddle_ocr.predict(proc_img)) if hasattr(self._paddle_ocr, "predict") else self._paddle_ocr.ocr(proc_img)
        except Exception:
            raw_res = self._paddle_ocr.ocr(proc_img) if not hasattr(self._paddle_ocr, "predict") else list(self._paddle_ocr.predict(proc_img))

        blocks: List[TextBlock] = []
        confidences: List[float] = []
        inv_scale = 1.0 / scale if scale != 1.0 else 1.0

        if raw_res:
            first_item = raw_res[0]
            if isinstance(first_item, dict) and ("rec_texts" in first_item or "rec_text" in first_item):
                texts = first_item.get("rec_texts") or first_item.get("rec_text") or []
                scores = first_item.get("rec_scores") or first_item.get("rec_score") or []
                polys = first_item.get("dt_polys")
                boxes = first_item.get("rec_boxes")

                for idx, t in enumerate(texts):
                    text_clean = str(t).strip()
                    if not text_clean:
                        continue
                    conf_val = round(float(scores[idx]), 4) if idx < len(scores) else 0.90
                    poly_list: List[List[float]] = []
                    bbox = {"x": 0.0, "y": 0.0, "w": float(w), "h": 20.0}

                    if polys is not None and idx < len(polys):
                        p_arr = polys[idx]
                        if len(p_arr) >= 4:
                            xs = [float(pt[0]) * inv_scale for pt in p_arr]
                            ys = [float(pt[1]) * inv_scale for pt in p_arr]
                            bbox = {"x": round(min(xs), 2), "y": round(min(ys), 2), "w": round(max(xs) - min(xs), 2), "h": round(max(ys) - min(ys), 2)}
                            poly_list = [[round(x, 2), round(y, 2)] for x, y in zip(xs, ys)]
                    elif boxes is not None and idx < len(boxes):
                        b = boxes[idx]
                        if len(b) >= 4:
                            bbox = {"x": round(float(b[0]) * inv_scale, 2), "y": round(float(b[1]) * inv_scale, 2), "w": round(float(b[2] - b[0]) * inv_scale, 2), "h": round(float(b[3] - b[1]) * inv_scale, 2)}

                    confidences.append(conf_val)
                    blocks.append(TextBlock(text=text_clean, confidence=conf_val, bbox=bbox, polygon=poly_list))
            elif isinstance(first_item, list):
                for line_item in first_item:
                    if not line_item or len(line_item) < 2:
                        continue
                    polygon, text_info = line_item[0], line_item[1]
                    text_clean = str(text_info[0]).strip() if isinstance(text_info, (list, tuple)) else str(text_info).strip()
                    conf_val = round(float(text_info[1]), 4) if isinstance(text_info, (list, tuple)) and len(text_info) > 1 else 0.90
                    if not text_clean:
                        continue
                    bbox = {"x": 0.0, "y": 0.0, "w": float(w), "h": 20.0}
                    poly_list = []
                    if polygon and len(polygon) >= 4:
                        xs = [float(pt[0]) * inv_scale for pt in polygon]
                        ys = [float(pt[1]) * inv_scale for pt in polygon]
                        bbox = {"x": round(min(xs), 2), "y": round(min(ys), 2), "w": round(max(xs) - min(xs), 2), "h": round(max(ys) - min(ys), 2)}
                        poly_list = [[round(x, 2), round(y, 2)] for x, y in zip(xs, ys)]
                    confidences.append(conf_val)
                    blocks.append(TextBlock(text=text_clean, confidence=conf_val, bbox=bbox, polygon=poly_list))

        lines = [b.text for b in blocks]
        avg_conf = round(sum(confidences) / len(confidences), 4) if confidences else 0.0
        return OCRResult(
            blocks=blocks, full_text="\n".join(lines), lines=lines,
            engine="paddleocr-3.7", model_version="PP-OCRv6", average_confidence=avg_conf
        )
