"""
Praman - Risk Scoring Engine: scoring math only.

Just the numbers - band thresholds, the tamper static-score -> reason
mapping, and the weighted sum. The request/response orchestration (wait
for 2 flags, then wait for 3 scores, per uuid) lives in main.py + store.py.
"""

WEIGHTS = {"ocr": 0.25, "tamper": 0.40, "photo": 0.35}
BAND_PASS = 80
BAND_MANUAL_LOW = 40

# The tampering module only ever sends one of these 4 static scores - no
# reasons field, so we derive the reason text ourselves from the value.
TAMPER_REASON_MAP = {
    100: ["tamper_check: PASS", "guilloche_check: PASS"],
    60: ["tamper_check: PASS", "guilloche_check: FAILED"],
    40: ["tamper_check: FAILED", "guilloche_check: PASS"],
    0: ["tamper_check: FAILED", "guilloche_check: FAILED"],
}


def tamper_reasons_for(score) -> list:
    return TAMPER_REASON_MAP.get(score, [f"tamper_score: UNRECOGNIZED_VALUE ({score})"])


def band_for(score: float) -> str:
    if score >= BAND_PASS:
        return "PASS"
    if score >= BAND_MANUAL_LOW:
        return "MANUAL_REVIEW"
    return "FAIL"


FORENSICS_UNAVAILABLE_REASON = "FORENSICS_UNAVAILABLE: image forensics did not run — decision capped at MANUAL_REVIEW"


def weighted_score(ocr_score: float, tamper_score, photo_score: float) -> float:
    """tamper_score None = forensics could not assess the images: the score is renormalized over
    the modules that did run, rather than handing out forensics' 40% for free (a stub that
    always said 100 let a forged document with mediocre OCR + face scores reach PASS)."""
    if tamper_score is None:
        raw = (WEIGHTS["ocr"] * ocr_score + WEIGHTS["photo"] * photo_score) / (WEIGHTS["ocr"] + WEIGHTS["photo"])
    else:
        raw = WEIGHTS["ocr"] * ocr_score + WEIGHTS["tamper"] * tamper_score + WEIGHTS["photo"] * photo_score
    return round(raw, 2)


def decide(ocr_score: float, tamper_score, photo_score: float, review_required: bool = False) -> tuple[float, str]:
    """Final (score, decision). Without forensics, or when a module demands a human look, a case
    can be FAIL or MANUAL_REVIEW, never PASS."""
    score = weighted_score(ocr_score, tamper_score, photo_score)
    decision = band_for(score)
    if (tamper_score is None or review_required) and decision == "PASS":
        decision = "MANUAL_REVIEW"
    return score, decision
