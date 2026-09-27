"""Who may write to the risk engine, and on which screening ids.

Before this, anyone who could reach port 8004 could POST three scores and mint a PASS for any
uuid — which the blockchain ledger would then seal as genuine. Now:

1. Each detection module has its own bearer token (RISK_TOKEN_OCR / _FORENSICS / _BIOMETRIC,
   >= 32 chars; generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`),
   and a token only authorizes that module's own inputs: the OCR token can't submit a face
   score. No tokens configured = every write is refused (503), never silently open.
2. Screening ids are issued by this service (POST /sessions) and expire; modules may only
   report on an id issued here.

ponytail: bearer tokens over the internal network; add mTLS between services before this
leaves a closed checkpoint LAN.
"""
from __future__ import annotations

import hmac
import os
import uuid as _uuid
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

import store
from schemas import SessionResponse

MIN_TOKEN_LENGTH = 32

# module identity -> the (kind, target) writes it may make
_ALLOWED = {
    "ocr": {("flag", "ocr"), ("score", "ocr")},
    "forensics": {("flag", "forensics"), ("score", "tamper")},
    "biometric": {("score", "photo")},
}


def _load_tokens() -> dict[str, str]:
    tokens = {}
    for module in _ALLOWED:
        token = os.environ.get(f"RISK_TOKEN_{module.upper()}", "").strip()
        if not token:
            continue
        if len(token) < MIN_TOKEN_LENGTH:
            raise RuntimeError(f"RISK_TOKEN_{module.upper()} is shorter than {MIN_TOKEN_LENGTH} chars — refusing a guessable token")
        tokens[module] = token
    return tokens


TOKENS = _load_tokens()


def caller_module(authorization: Optional[str] = Header(default=None)) -> str:
    """FastAPI dependency: which module is calling, from its bearer token."""
    if not TOKENS:
        raise HTTPException(503, "Module authentication is not configured (set RISK_TOKEN_* env vars)")
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing bearer token")
    presented = authorization[len("Bearer "):].encode()
    for module, token in TOKENS.items():
        if hmac.compare_digest(presented, token.encode()):
            return module
    raise HTTPException(401, "Invalid token")


def authorize(module: str, kind: str, target: str, uuid: str) -> None:
    if (kind, target) not in _ALLOWED[module]:
        raise HTTPException(403, f"module '{module}' may not submit {kind} for '{target}'")
    if not store.session_exists(uuid):
        raise HTTPException(409, "Unknown or expired screening id — ids must come from POST /sessions")


router = APIRouter()


@router.post("/sessions", response_model=SessionResponse, status_code=201)
def create_session() -> SessionResponse:
    """Issues a fresh screening id. Unauthenticated by design: an id alone grants nothing —
    only a module holding its token can report results against it."""
    uuid = str(_uuid.uuid4())
    store.issue_session(uuid)
    return SessionResponse(uuid=uuid, expires_in_seconds=store.SESSION_TTL_SECONDS)
