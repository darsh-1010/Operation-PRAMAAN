"""Request/response models for the risk engine's module-facing API (validated at the boundary:
scores are finite 0-100, evidence entries are `<kind>:<sha256 hex>`)."""
from typing import Annotated, List, Literal, Optional

from pydantic import BaseModel, Field

Score = Annotated[float, Field(ge=0, le=100, allow_inf_nan=False)]
# "<document kind>:<sha256 of the exact uploaded bytes>", e.g. "passport:9f86d0…". Sealed into
# the ledger record so the stored evidence files can later be proven untouched.
EvidenceItem = Annotated[str, Field(pattern=r"^[A-Za-z]{1,32}:[0-9a-f]{64}$")]


class FlagCheckRequest(BaseModel):
    uuid: str
    module: Literal["ocr", "forensics"]
    flag: bool
    reasons: List[str] = Field(default_factory=list)
    evidence: List[EvidenceItem] = Field(default_factory=list, max_length=20)


class FlagCheckResponse(BaseModel):
    uuid: str
    status: str  # "REJECTED" | "WAITING_ON_OTHER_FLAG" | "WAITING_ON_SCORES" | "DONE"
    score: Optional[float] = None
    decision: Optional[str] = None


class OCRScorePayload(BaseModel):
    score: Score
    reasons: List[str] = Field(default_factory=list)
    # The document can't be trusted without a human look (e.g. Aadhaar QR unverifiable, Nepali
    # citizenship certificate): the final decision is capped at MANUAL_REVIEW.
    review_required: bool = False


class TamperScorePayload(BaseModel):
    # One of 100 / 60 / 40 / 0 — or null when forensics could not assess the images at all
    # (see scoring.decide: the decision is then capped at MANUAL_REVIEW, never PASS).
    score: Optional[float] = Field(default=None, ge=0, le=100, allow_inf_nan=False)
    reasons: List[str] = Field(default_factory=list)


class PhotoScorePayload(BaseModel):
    score: Score
    hard_fail: bool
    reasons: List[str] = Field(default_factory=list)


class SubmitScoreRequest(BaseModel):
    uuid: str
    module: Literal["ocr", "tamper", "photo"]
    ocr: Optional[OCRScorePayload] = None
    tamper: Optional[TamperScorePayload] = None
    photo: Optional[PhotoScorePayload] = None
    evidence: List[EvidenceItem] = Field(default_factory=list, max_length=20)


class SubmitScoreResponse(BaseModel):
    uuid: str
    status: str  # "REJECTED" | "STORED_WAITING_ON_FLAGS" | "WAITING_ON_OTHER_SCORES" | "DONE"
    score: Optional[float] = None
    decision: Optional[str] = None


class ResultResponse(BaseModel):
    uuid: str
    score: Optional[float]
    decision: str
    timed_out: bool
    reasons: List[str] = Field(default_factory=list)


class SessionResponse(BaseModel):
    uuid: str
    expires_in_seconds: int
