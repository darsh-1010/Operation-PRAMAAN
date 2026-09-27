"""Voter 3: the trained tamper/AI-generated-image detection model.

Not wired in yet — training is happening separately. Reports honestly that it assessed
nothing rather than a made-up number, same contract every voter here follows (see
app/voters.py).

Swap this in once a trained checkpoint exists: load it once at import time (module-level,
like biometric-matching's ArcFaceEncoder pattern), run inference here, map its output to a
0-100 score.
"""
from __future__ import annotations

from app.voters import VoterResult

VOTER_NAME = "tamper_model"
NOT_ASSESSED_REASON = "TAMPER_MODEL_NOT_IMPLEMENTED: trained model not wired in yet — no assessment made"


def assess(image_bytes: bytes, label: str) -> VoterResult:
    return VoterResult(name=VOTER_NAME, score=None, reason_codes=[f"{label}: {NOT_ASSESSED_REASON}"])
