"""Multilingual OCR Engine utilizing local Tesseract installation.

Configured for high-accuracy document extraction across English, Nepali, Hindi,
Bengali, Urdu, and Burmese:
- Automatically binds to local Tesseract executable (e.g. C:\\Program Files\\Tesseract-OCR\\tesseract.exe)
- Configures local regional tessdata language models
- Supports multi-script recognition (e.g. 'eng+nep', 'eng+hin')
- Extracts structured text blocks, bounding boxes, and per-block confidence scores
"""

from __future__ import annotations
import logging
import os
import shutil
from typing import List, Optional

import numpy as np

logger = logging.getLogger("multilingual_ocr")

# Candidates for Tesseract executable on Windows / Linux
TESSERACT_SEARCH_PATHS = [
    os.environ.get("TESSERACT_CMD", ""),
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
    "/usr/bin/tesseract",
    "/usr/local/bin/tesseract",
]


def resolve_tesseract_binary() -> Optional[str]:
    """Locate the installed Tesseract executable across environment and standard paths."""
    for path in TESSERACT_SEARCH_PATHS:
        if path and os.path.isfile(path):
            return os.path.abspath(path)
    which_path = shutil.which("tesseract")
    if which_path:
        return os.path.abspath(which_path)
    return None


def resolve_tessdata_dir() -> str:
    """Locate regional traineddata models directory."""
    env_tessdata = os.environ.get("TESSDATA_PREFIX")
    if env_tessdata and os.path.isdir(env_tessdata):
        return os.path.abspath(env_tessdata)

    service_dir = os.path.dirname(os.path.abspath(__file__))
    local_tessdata = os.path.join(service_dir, "tessdata")
    if os.path.isdir(local_tessdata):
        return local_tessdata

    standard_win = r"C:\Program Files\Tesseract-OCR\tessdata"
    if os.path.isdir(standard_win):
        return standard_win

    return local_tessdata


class MultilingualOCREngine:
    """Tesseract-backed OCR coordinator for regional non-English scripts."""

    _instance: Optional["MultilingualOCREngine"] = None

    def __init__(self) -> None:
        self.tesseract_cmd = resolve_tesseract_binary()
        self.tessdata_dir = resolve_tessdata_dir()
        self._setup_pytesseract()

    @classmethod
    def get_instance(cls) -> "MultilingualOCREngine":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def _setup_pytesseract(self) -> None:
        """Configure pytesseract binary path and tessdata prefix."""
        try:
            import pytesseract
            if self.tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = self.tesseract_cmd
                logger.info("Bound pytesseract to %s", self.tesseract_cmd)
            if self.tessdata_dir:
                os.environ["TESSDATA_PREFIX"] = self.tessdata_dir
        except Exception as err:
            logger.warning("Could not initialize pytesseract: %s", err)

    def extract_text(
        self,
        image: np.ndarray,
        lang: str = "eng",
        psm: int = 3,
    ):
        """Extract text blocks, bounding boxes, and confidence for specified language."""
        from ocr_engine import OCRResult, TextBlock
        try:
            import pytesseract
            config = f'--tessdata-dir {self.tessdata_dir} --psm {psm}'
            data = pytesseract.image_to_data(
                image,
                lang=lang,
                config=config,
                output_type=pytesseract.Output.DICT,
            )

            from collections import OrderedDict
            blocks: List[TextBlock] = []
            confidences: List[float] = []
            lines_dict: Dict[Tuple[int, int, int], List[str]] = OrderedDict()
            n_boxes = len(data["text"])

            for i in range(n_boxes):
                text = str(data["text"][i]).strip()
                conf_raw = float(data["conf"][i])
                if not text or conf_raw < 0:
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

                line_key = (int(data["block_num"][i]), int(data["par_num"][i]), int(data["line_num"][i]))
                if line_key not in lines_dict:
                    lines_dict[line_key] = []
                lines_dict[line_key].append(text)

            lines = [" ".join(words) for words in lines_dict.values()]
            avg_conf = round(sum(confidences) / len(confidences), 4) if confidences else 0.0

            return OCRResult(
                blocks=blocks,
                full_text="\n".join(lines),
                lines=lines,
                engine=f"tesseract-multilingual-{lang}",
                model_version="5.x",
                average_confidence=avg_conf,
            )
        except Exception as err:
            logger.error("Multilingual Tesseract extraction failed: %s", err)
            return OCRResult(
                blocks=[],
                full_text="",
                lines=[],
                engine=f"tesseract-failed-{lang}",
                model_version="5.x",
                average_confidence=0.0,
            )
