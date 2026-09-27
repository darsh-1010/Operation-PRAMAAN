"""Script and Language Detection for Multilingual Documents.

Analyzes text character distributions and linguistic markers across:
- Devanagari (Nepali and Hindi)
- Bengali
- Perso-Arabic (Urdu)
- Myanmar (Burmese)
- Latin (English)

Operates 100% offline using Unicode character properties and vocabulary heuristics.
"""

from __future__ import annotations
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


@dataclass
class ScriptDetectionResult:
    """Result of script and language classification."""
    detected_script: str
    language_code: str
    language_name: str
    confidence: float
    is_english: bool
    tesseract_lang: str
    script_distribution: Dict[str, float]


# Unicode script ranges
SCRIPT_RANGES: List[Tuple[str, str, re.Pattern[str]]] = [
    ("Devanagari", "Devanagari", re.compile(r"[\u0900-\u097F]")),
    ("Bengali", "Bengali", re.compile(r"[\u0980-\u09FF]")),
    ("Perso-Arabic", "Arabic", re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")),
    ("Myanmar", "Myanmar", re.compile(r"[\u1000-\u109F]")),
    ("Tibetan", "Tibetan", re.compile(r"[\u0F00-\u0FFF]")),
    ("Latin", "Latin", re.compile(r"[A-Za-z]")),
]

# Vocabulary markers to distinguish Nepali from Hindi in Devanagari text
NEPALI_MARKERS = {
    "नेपाल", "नागरिकता", "प्रमाणपत्र", "जिल्ला", "बाबुको", "आमाको", "पति", "पत्नी",
    "जन्म मिति", "वि.सं", "वि.सं.", "गा.वि.स", "गा.वि.स.", "नगरपालिका", "मिति",
    "हस्ताक्षर", "सवारी", "चालक", "अनुमतिपत्र", "प्रदेश", "साविक", "जारी",
}

HINDI_MARKERS = {
    "भारत", "आधार", "पहचान", "सरकार", "पिता", "माता", "जन्म तिथि",
    "निवासी", "पुरुष", "महिला", "निर्वाचन", "मतदाता", "कार्ड",
}

COUNTRY_TO_LANG: Dict[str, Tuple[str, str, str]] = {
    "NPL": ("nep", "Nepali", "eng+nep"),
    "IND": ("hin", "Hindi", "eng+hin"),
    "BGD": ("ben", "Bengali", "eng+ben"),
    "PAK": ("urd", "Urdu", "eng+urd"),
    "MMR": ("mya", "Burmese", "eng+mya"),
    "BTN": ("dzo", "Dzongkha", "eng+dzo"),
}


def _analyze_char_distribution(text: str) -> Dict[str, float]:
    """Calculate the distribution of scripts across non-whitespace characters."""
    counts: Dict[str, int] = {}
    total = 0
    for name, _, pattern in SCRIPT_RANGES:
        c = len(pattern.findall(text))
        if c > 0:
            counts[name] = c
            total += c

    if total == 0:
        return {"Latin": 1.0}
    return {k: round(v / total, 4) for k, v in counts.items()}


def _distinguish_devanagari(text: str) -> Tuple[str, str, str]:
    """Distinguish between Nepali and Hindi in Devanagari text."""
    nepali_hits = sum(1 for m in NEPALI_MARKERS if m in text)
    hindi_hits = sum(1 for m in HINDI_MARKERS if m in text)

    if nepali_hits > hindi_hits:
        return "nep", "Nepali", "eng+nep"
    if hindi_hits > nepali_hits:
        return "hin", "Hindi", "eng+hin"
    # Default to Nepali when ambiguous in SSB border inspection context
    return "nep", "Nepali", "eng+nep"


def detect_script_and_language(
    text: Optional[str],
    expected_country: Optional[str] = None,
    expected_language: Optional[str] = None,
) -> ScriptDetectionResult:
    """Detect dominant script and language from text with optional officer hint."""
    # 1. Respect explicit country or language hint if provided
    if expected_country and expected_country.upper() in COUNTRY_TO_LANG:
        code, name, tess = COUNTRY_TO_LANG[expected_country.upper()]
        return ScriptDetectionResult(
            detected_script="Hinted",
            language_code=code,
            language_name=name,
            confidence=1.0,
            is_english=(code == "eng"),
            tesseract_lang=tess,
            script_distribution={name: 1.0},
        )

    if expected_language and expected_language.lower() in ("nep", "nepali"):
        return ScriptDetectionResult(
            detected_script="Devanagari",
            language_code="nep",
            language_name="Nepali",
            confidence=1.0,
            is_english=False,
            tesseract_lang="eng+nep",
            script_distribution={"Devanagari": 1.0},
        )

    clean_text = (text or "").strip()
    if not clean_text:
        return ScriptDetectionResult(
            detected_script="Latin",
            language_code="eng",
            language_name="English",
            confidence=0.5,
            is_english=True,
            tesseract_lang="eng",
            script_distribution={"Latin": 1.0},
        )

    dist = _analyze_char_distribution(clean_text)
    primary_script = max(dist.items(), key=lambda x: x[1])[0]
    script_conf = dist[primary_script]

    if primary_script == "Devanagari":
        code, name, tess = _distinguish_devanagari(clean_text)
        return ScriptDetectionResult(
            detected_script="Devanagari",
            language_code=code,
            language_name=name,
            confidence=script_conf,
            is_english=False,
            tesseract_lang=tess,
            script_distribution=dist,
        )

    if primary_script == "Bengali":
        return ScriptDetectionResult(
            detected_script="Bengali",
            language_code="ben",
            language_name="Bengali",
            confidence=script_conf,
            is_english=False,
            tesseract_lang="eng+ben",
            script_distribution=dist,
        )

    if primary_script == "Perso-Arabic":
        return ScriptDetectionResult(
            detected_script="Perso-Arabic",
            language_code="urd",
            language_name="Urdu",
            confidence=script_conf,
            is_english=False,
            tesseract_lang="eng+urd",
            script_distribution=dist,
        )

    if primary_script == "Myanmar":
        return ScriptDetectionResult(
            detected_script="Myanmar",
            language_code="mya",
            language_name="Burmese",
            confidence=script_conf,
            is_english=False,
            tesseract_lang="eng+mya",
            script_distribution=dist,
        )

    return ScriptDetectionResult(
        detected_script="Latin",
        language_code="eng",
        language_name="English",
        confidence=script_conf,
        is_english=True,
        tesseract_lang="eng",
        script_distribution=dist,
    )
