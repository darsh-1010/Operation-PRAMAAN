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


def weighted_score(ocr_score: float, tamper_score: float, photo_score: float) -> float:
    raw = (
        WEIGHTS["ocr"] * ocr_score
        + WEIGHTS["tamper"] * tamper_score
        + WEIGHTS["photo"] * photo_score
    )
    return round(raw, 2)
