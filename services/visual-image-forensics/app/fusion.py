"""Combines this module's independent voters into the one score/hard_fail/reason_codes
triplet POST /screen returns (API_CONTRACT.md's shape) — never lets one voter's fabricated
certainty stand in for the others (see main.py's own history: this module used to return a
flat 100 when it hadn't assessed anything at all).

Rules, mirroring how risk-scoring-engine itself fuses the 3 top-level modules:
  - A voter that didn't assess anything (score=None) contributes nothing and is never
    treated as "passed" — the average is renormalized over whichever voters did assess.
  - If every voter that DID assess something agrees nothing is hard_fail-worthy, the final
    score is theirs; if none of them could assess anything, the honest answer is still None.
  - Any voter's hard_fail wins outright — one voter finding something wrong is not diluted by
    two others that didn't notice.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.voters import VoterResult

# How much each voter counts once it HAS assessed something — renormalized over whichever
# voters actually ran. Tune once the trained model's real-world precision is known; for now
# it's weighted highest since it should end up the strongest, most-validated signal.
VOTER_WEIGHTS = {"noise_residual": 0.3, "reconstruction": 0.3, "tamper_model": 0.4}


@dataclass
class FusionResult:
    score: float | None
    hard_fail: bool
    reason_codes: list[str] = field(default_factory=list)


def reduce_per_image(voter_name: str, per_image_results: list[VoterResult]) -> VoterResult:
    """Collapses one voter's per-document-image results into a single result for the whole
    submission — the worst (lowest) score wins, since one tampered document is what matters,
    not the average of a tampered one and clean ones."""
    reason_codes = [code for r in per_image_results for code in r.reason_codes]
    assessed = [r for r in per_image_results if r.score is not None]
    if not assessed:
        return VoterResult(name=voter_name, score=None, reason_codes=reason_codes)
    worst = min(assessed, key=lambda r: r.score)
    hard_fail = any(r.hard_fail for r in assessed)
    return VoterResult(name=voter_name, score=worst.score, hard_fail=hard_fail, reason_codes=reason_codes)


def fuse(voters: list[VoterResult]) -> FusionResult:
    reason_codes = [code for v in voters for code in v.reason_codes]
    assessed = [v for v in voters if v.score is not None]

    if not assessed:
        return FusionResult(score=None, hard_fail=False, reason_codes=reason_codes)

    if any(v.hard_fail for v in assessed):
        return FusionResult(score=0.0, hard_fail=True, reason_codes=reason_codes)

    total_weight = sum(VOTER_WEIGHTS[v.name] for v in assessed)
    score = sum(VOTER_WEIGHTS[v.name] * v.score for v in assessed) / total_weight
    return FusionResult(score=round(score, 1), hard_fail=False, reason_codes=reason_codes)


def demo() -> None:
    """ponytail self-check for the fusion rules above."""
    # A voter that never ran contributes nothing; the other two's average stands.
    result = fuse([
        VoterResult(name="noise_residual", score=90.0),
        VoterResult(name="reconstruction", score=None, reason_codes=["not built"]),
        VoterResult(name="tamper_model", score=70.0),
    ])
    assert result.score is not None and 75 < result.score < 82, result  # weighted 0.3/0.4 renormalized
    assert not result.hard_fail

    # Any single hard_fail wins, regardless of the others' scores.
    result = fuse([
        VoterResult(name="noise_residual", score=10.0, hard_fail=True, reason_codes=["NOISE_BAD"]),
        VoterResult(name="reconstruction", score=95.0),
    ])
    assert result.hard_fail and result.score == 0.0

    # Nothing assessed anything -> the honest answer is still "not assessed."
    result = fuse([
        VoterResult(name="reconstruction", score=None),
        VoterResult(name="tamper_model", score=None),
    ])
    assert result.score is None and not result.hard_fail

    print("OK: fusion.demo")


if __name__ == "__main__":
    demo()
