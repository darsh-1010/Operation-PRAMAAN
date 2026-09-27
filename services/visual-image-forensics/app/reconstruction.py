"""Voter 2: reconstruction-error check (autoencoder trained on genuine documents only).

Not built yet — needs a trained autoencoder checkpoint (and a labeled set of genuine,
unmodified documents to train it on), neither of which exist yet. Reports honestly that it
assessed nothing rather than a made-up number — same contract every voter here follows (see
app/voters.py and main.py's own history with a fabricated-score bug in this exact module).

Swap this in once a real checkpoint exists: decode the image, run it through the encoder,
measure reconstruction error against the input, map error -> a 0-100 score the same way
noise_residual.py does.
"""
from __future__ import annotations

from app.voters import VoterResult

VOTER_NAME = "reconstruction"
NOT_ASSESSED_REASON = "RECONSTRUCTION_NOT_IMPLEMENTED: no trained autoencoder checkpoint yet — no assessment made"


def assess(image_bytes: bytes, label: str) -> VoterResult:
    return VoterResult(name=VOTER_NAME, score=None, reason_codes=[f"{label}: {NOT_ASSESSED_REASON}"])
