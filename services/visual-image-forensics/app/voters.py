"""Shared shape for every independent forensic "voter" (see fusion.py).

Each voter looks at the same image and reports its own opinion — never as a feature fed
into another voter. A voter that can't assess anything (no trained model yet, no autoencoder
checkpoint yet) reports score=None, the same "honest, not a made-up number" contract this
module has always used (see main.py's history with this exact issue).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class VoterResult:
    name: str
    score: float | None  # 0-100, higher = more likely genuine. None = could not assess.
    hard_fail: bool = False
    reason_codes: list[str] = field(default_factory=list)
