"""Optimized OCR Engine using PaddleOCR with fallback support.

Configured for high accuracy on identity documents and low inference latency:
- Singleton warm-loaded model instance (PP-OCRv4)
- CPU multi-threading and MKLDNN acceleration enabled
- Automatic angle / orientation classification
- Extracts text blocks, normalized bounding boxes, and confidence scores
"""

from __future__ import annotations
import logging
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger("ocr_engine")


@dataclass
class TextBlock:
    """Individual OCR text block with coordinates and confidence."""
    text: str
    confidence: float
    bbox: Dict[str, float]  # {"x": int, "y": int, "w": int, "h": int}
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
        """Retrieve the singleton OCR engine instance."""
        if cls._instance is None:
            cls._instance = cls()
            cls._instance._initialize()
        return cls._instance

    def _initialize(self) -> None:
        """Initialize PaddleOCR with high-performance CPU settings."""
        try:
            # Prevent oneDNN PIR executor conflict on Windows CPU with Paddle 3.x
            os.environ["FLAGS_use_mkldnn"] = "0"
            os.environ["PADDLE_PDX_ENABLE_MKLDNN_BYDEFAULT"] = "0"
            from paddleocr import PaddleOCR
            cpu_threads = int(os.environ.get("CPU_THREADS", os.cpu_count() or 4))
            enable_mkldnn = os.environ.get("ENABLE_MKLDNN", "false").lower() == "true"
            use_angle_cls = os.environ.get("USE_ANGLE_CLS", "true").lower() == "true"
            lang = os.environ.get("OCR_LANG", "en")

            logger.info("Initializing PaddleOCR with lang=%s...", lang)
            # PaddleOCR 3.x uses use_textline_orientation, 2.x uses use_angle_cls
            init_kwargs = {
                "lang": lang,
                "enable_mkldnn": enable_mkldnn,
                "use_doc_unwarping": False,
            }
            try:
                self._paddle_ocr = PaddleOCR(use_textline_orientation=use_angle_cls, **init_kwargs)
            except (TypeError, ValueError):
                try:
                    self._paddle_ocr = PaddleOCR(use_angle_cls=use_angle_cls, **init_kwargs)
                except Exception:
                    self._paddle_ocr = PaddleOCR(**init_kwargs)

            self._engine_name = "paddleocr-3.7"
            logger.info("PaddleOCR engine initialized successfully.")
        except Exception as err:
            logger.warning("Failed to initialize PaddleOCR (%s). Fallback to Tesseract will be used.", err)
            self._paddle_ocr = None
            self._engine_name = "tesseract-fallback"

    def extract_text(self, image: np.ndarray) -> OCRResult:
        """Extract text blocks, lines, and bounding boxes from an RGB image."""
        if self._paddle_ocr is not None:
            try:
                return self._extract_paddle(image)
            except Exception as err:
                logger.error("PaddleOCR inference failed: %s. Falling back to Tesseract.", err)

        return self._extract_tesseract(image)

    def _extract_paddle(self, image: np.ndarray) -> OCRResult:
        """Execute OCR extraction using PaddleOCR with format compatibility."""
        try:
            raw_res = self._paddle_ocr.ocr(image)
        except (TypeError, AttributeError):
            raw_res = list(self._paddle_ocr.predict(image))

        blocks: List[TextBlock] = []
        confidences: List[float] = []

        if raw_res:
<<<<<<< Updated upstream
            # PaddleOCR 3.x / PaddleX pipeline: raw_res[0] is a single dict-like
            # OCRResult per page carrying parallel rec_texts/rec_scores/rec_polys
            # lists, not one item per text line. Expand it into per-line items
            # so the loop below can handle it the same as the older formats.
            if (
                isinstance(raw_res, list) and len(raw_res) > 0
                and hasattr(raw_res[0], "get") and raw_res[0].get("rec_texts") is not None
            ):
                page = raw_res[0]
                rec_texts = page.get("rec_texts") or []
                rec_scores = page.get("rec_scores") or []
                rec_polys = page.get("rec_polys")
                if rec_polys is None:
                    rec_polys = page.get("rec_boxes") or []
                items = [
                    {
                        "rec_text": rec_texts[i],
                        "rec_score": rec_scores[i] if i < len(rec_scores) else 0.9,
                        "rec_poly": rec_polys[i] if i < len(rec_polys) else None,
                    }
                    for i in range(len(rec_texts))
                ]
            # Handle list of items or list of lists
            elif isinstance(raw_res, list) and len(raw_res) > 0 and isinstance(raw_res[0], list):
                items = raw_res[0]
            else:
                items = raw_res

            for item in items:
                text_clean = ""
                conf_val = 0.9
                polygon = []

                if isinstance(item, (list, tuple)) and len(item) == 2:
                    poly_candidate, text_data = item
                    if isinstance(poly_candidate, (list, tuple)):
                        polygon = poly_candidate
                    if isinstance(text_data, (list, tuple)) and len(text_data) == 2:
                        text_clean = str(text_data[0]).strip()
                        conf_val = round(float(text_data[1]), 4)
                    else:
                        text_clean = str(text_data).strip()
                elif isinstance(item, dict) and "rec_text" in item:
                    text_clean = str(item["rec_text"]).strip()
                    conf_val = round(float(item["rec_score"]), 4)
                    if item.get("rec_poly") is not None:
                        polygon = np.asarray(item["rec_poly"]).tolist()
                elif hasattr(item, "rec_text") and hasattr(item, "rec_score"):
                    text_clean = str(item.rec_text).strip()
                    conf_val = round(float(item.rec_score), 4)
                    if hasattr(item, "dt_polys"):
                        polygon = np.asarray(item.dt_polys).tolist()
=======
            # Handle PaddleX 3.7 dict output format: {'rec_texts': [...], 'rec_scores': [...], 'rec_polys': [...]}
            if isinstance(raw_res, list) and len(raw_res) > 0 and isinstance(raw_res[0], dict):
                paddlex_res = raw_res[0]
                rec_texts = paddlex_res.get("rec_texts", [])
                rec_scores = paddlex_res.get("rec_scores", [])
                rec_polys = paddlex_res.get("rec_polys", paddlex_res.get("dt_polys", []))
                for idx, text in enumerate(rec_texts):
                    text_clean = str(text).strip()
                    if not text_clean:
                        continue
                    conf_val = round(float(rec_scores[idx]), 4) if idx < len(rec_scores) else 0.9
                    poly = rec_polys[idx] if idx < len(rec_polys) else []
                    polygon = poly.tolist() if hasattr(poly, "tolist") else list(poly)
                    if polygon and len(polygon) >= 4:
                        xs = [pt[0] for pt in polygon]
                        ys = [pt[1] for pt in polygon]
                        bbox = {
                            "x": round(float(min(xs)), 2),
                            "y": round(float(min(ys)), 2),
                            "w": round(float(max(xs) - min(xs)), 2),
                            "h": round(float(max(ys) - min(ys)), 2),
                        }
                    else:
                        bbox = {"x": 0.0, "y": 0.0, "w": float(image.shape[1]), "h": 20.0}
                    confidences.append(conf_val)
                    blocks.append(TextBlock(
                        text=text_clean,
                        confidence=conf_val,
                        bbox=bbox,
                        polygon=[[round(float(p[0]), 2), round(float(p[1]), 2)] for p in polygon] if polygon else [],
                    ))
            else:
                # Handle list of items or list of lists
                items = raw_res[0] if (isinstance(raw_res, list) and len(raw_res) > 0 and isinstance(raw_res[0], list)) else raw_res
>>>>>>> Stashed changes

                for item in items:
                    text_clean = ""
                    conf_val = 0.9
                    polygon = []

                    if isinstance(item, (list, tuple)) and len(item) == 2:
                        poly_candidate, text_data = item
                        if isinstance(poly_candidate, (list, tuple)):
                            polygon = poly_candidate
                        if isinstance(text_data, (list, tuple)) and len(text_data) == 2:
                            text_clean = str(text_data[0]).strip()
                            conf_val = round(float(text_data[1]), 4)
                        else:
                            text_clean = str(text_data).strip()
                    elif hasattr(item, "rec_text") and hasattr(item, "rec_score"):
                        text_clean = str(item.rec_text).strip()
                        conf_val = round(float(item.rec_score), 4)
                        if hasattr(item, "dt_polys"):
                            polygon = item.dt_polys

                    if not text_clean:
                        continue

                    if polygon and len(polygon) >= 4:
                        xs = [pt[0] for pt in polygon]
                        ys = [pt[1] for pt in polygon]
                        min_x, max_x = min(xs), max(xs)
                        min_y, max_y = min(ys), max(ys)
                        bbox = {
                            "x": round(float(min_x), 2),
                            "y": round(float(min_y), 2),
                            "w": round(float(max_x - min_x), 2),
                            "h": round(float(max_y - min_y), 2),
                        }
                    else:
                        bbox = {"x": 0.0, "y": 0.0, "w": float(image.shape[1]), "h": 20.0}

                    confidences.append(conf_val)
                    blocks.append(TextBlock(
                        text=text_clean,
                        confidence=conf_val,
                        bbox=bbox,
                        polygon=[[round(float(p[0]), 2), round(float(p[1]), 2)] for p in polygon] if polygon else [],
                    ))

        lines = [b.text for b in blocks]
        full_text = "\n".join(lines)
        avg_conf = round(sum(confidences) / len(confidences), 4) if confidences else 0.0

        return OCRResult(
            blocks=blocks,
            full_text=full_text,
            lines=lines,
            engine="paddleocr-3.7",
            model_version="PP-OCRv4",
            average_confidence=avg_conf,
        )

    def _extract_tesseract(self, image: np.ndarray) -> OCRResult:
        """Fallback extraction using pytesseract when PaddleOCR is not available."""
        try:
            import pytesseract
            data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
            blocks: List[TextBlock] = []
            confidences: List[float] = []

            n_boxes = len(data["text"])
            for i in range(n_boxes):
                text = data["text"][i].strip()
                conf_raw = float(data["conf"][i])
                if not text or conf_raw <= 0:
                    continue

                conf = round(conf_raw / 100.0, 4)
                bbox = {
                    "x": float(data["left"][i]),
                    "y": float(data["top"][i]),
                    "w": float(data["width"][i]),
                    "h": float(data["height"][i]),
                }
                confidences.append(conf)
                blocks.append(TextBlock(text=text, confidence=conf, bbox=bbox))

            lines = [b.text for b in blocks]
            avg_conf = round(sum(confidences) / len(confidences), 4) if confidences else 0.0
            return OCRResult(
                blocks=blocks,
                full_text="\n".join(lines),
                lines=lines,
                engine="tesseract-5",
                model_version="standard",
                average_confidence=avg_conf,
            )
        except Exception as err:
            logger.error("Tesseract fallback also failed: %s", err)
            return OCRResult(
                blocks=[],
                full_text="",
                lines=[],
                engine="none",
                model_version="none",
                average_confidence=0.0,
            )
