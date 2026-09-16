"""Tesseract OCR fallback engine with image preprocessing and MRZ extraction."""

from __future__ import annotations
import logging
import re
from typing import Any, Dict, List
import numpy as np

logger = logging.getLogger("ocr_tesseract")


def extract_tesseract(image: np.ndarray, text_block_cls: Any, ocr_result_cls: Any) -> Any:
    """High-accuracy fallback extraction using pytesseract with preprocessing and MRZ crop."""
    try:
        import cv2
        import pytesseract

        h, w = image.shape[:2]
        scale = max(1.0, 1200.0 / w)
        proc_img = cv2.resize(image, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_LANCZOS4) if scale > 1.05 else image
        gray = cv2.cvtColor(proc_img, cv2.COLOR_BGR2GRAY) if len(proc_img.shape) == 3 else proc_img

        data = pytesseract.image_to_data(gray, config="--psm 6", output_type=pytesseract.Output.DICT)
        blocks: List[Any] = []
        confidences: List[float] = []
        lines_map: Dict[Any, List[str]] = {}

        n_boxes = len(data["text"])
        for i in range(n_boxes):
            text = data["text"][i].strip()
            conf_raw = float(data["conf"][i])
            if not text or conf_raw <= 0:
                continue

            conf = round(conf_raw / 100.0, 4)
            bbox = {
                "x": round(float(data["left"][i]) / scale, 2),
                "y": round(float(data["top"][i]) / scale, 2),
                "w": round(float(data["width"][i]) / scale, 2),
                "h": round(float(data["height"][i]) / scale, 2),
            }
            confidences.append(conf)
            blocks.append(text_block_cls(text=text, confidence=conf, bbox=bbox))

            line_key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
            lines_map.setdefault(line_key, []).append(text)

        lines = [" ".join(words) for words in lines_map.values() if words]

        has_valid_mrz = any(("<" in l and len(l) >= 30) for l in lines)
        if not has_valid_mrz and h >= 80:
            mrz_candidates: List[str] = []
            for start_pct in (0.70, 0.76, 0.81):
                strip = image[int(h * start_pct):, :]
                if strip.shape[0] < 10 or strip.shape[1] < 10:
                    continue
                s_gray = cv2.cvtColor(strip, cv2.COLOR_BGR2GRAY) if len(strip.shape) == 3 else strip.copy()
                if s_gray.shape[1] < 1500:
                    sc = 1500.0 / s_gray.shape[1]
                    s_gray = cv2.resize(s_gray, (1500, max(120, int(s_gray.shape[0] * sc))), interpolation=cv2.INTER_CUBIC)

                clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
                contrast_strip = clahe.apply(s_gray)
                _, otsu_strip = cv2.threshold(contrast_strip, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

                for proc_strip in (otsu_strip, contrast_strip):
                    try:
                        m_out = pytesseract.image_to_string(
                            proc_strip,
                            config="--psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<"
                        )
                        for raw_l in m_out.splitlines():
                            cleaned_m = re.sub(r"[\(\{\[\«]", "<", raw_l.strip().upper())
                            cleaned_m = re.sub(r"[^A-Z0-9<]", "", cleaned_m)
                            if len(cleaned_m) >= 25 and ("<" in cleaned_m or cleaned_m.startswith(("P", "V", "I"))):
                                if cleaned_m not in mrz_candidates:
                                    mrz_candidates.append(cleaned_m)
                    except Exception:
                        pass

            if mrz_candidates:
                lines.extend(mrz_candidates)

        avg_conf = round(sum(confidences) / len(confidences), 4) if confidences else 0.0
        return ocr_result_cls(
            blocks=blocks,
            full_text="\n".join(lines),
            lines=lines,
            engine="tesseract-5",
            model_version="standard",
            average_confidence=avg_conf,
        )
    except Exception as err:
        logger.error("Tesseract fallback failed: %s", err)
        return ocr_result_cls(blocks=[], full_text="", lines=[], engine="none", model_version="none", average_confidence=0.0)
