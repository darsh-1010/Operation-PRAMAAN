"""Encrypted evidence store: every uploaded file is kept, AES-256-GCM encrypted, so a decision can
be backed by the exact images it was made on. Its SHA-256 goes to the risk engine and is sealed
into the blockchain-anchored decision record, so the stored file can later be proven untouched
(decrypt → hash → compare with the sealed record).

Same file in ocr-consistency-check/evidence.py (duplicated, not imported — CLAUDE.md rule).

    EVIDENCE_KEY  base64 of 32 random bytes:
                  python -c "import base64,os; print(base64.b64encode(os.urandom(32)).decode())"
                  Losing it = losing every stored file. Keep it in a secrets manager, not git.
    EVIDENCE_DIR  where files go (a docker volume in compose).

ponytail: no automatic deletion yet — DPDP needs a written retention period; add a scheduled
purge of EVIDENCE_DIR/<uuid>/ folders older than it once the period is decided.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import os
import uuid as _uuid
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MAGIC = b"PRMEV1"
EVIDENCE_DIR = Path(os.environ.get("EVIDENCE_DIR", "/data/evidence"))


class EvidenceError(RuntimeError):
    pass


def _key() -> bytes:
    raw = os.environ.get("EVIDENCE_KEY", "").strip()
    if not raw:
        raise EvidenceError("EVIDENCE_KEY is not set — uploaded files are NOT being retained")
    try:
        key = base64.b64decode(raw, validate=True)
    except binascii.Error as err:
        raise EvidenceError("EVIDENCE_KEY is not valid base64") from err
    if len(key) != 32:
        raise EvidenceError("EVIDENCE_KEY must decode to exactly 32 bytes (AES-256)")
    return key


def _path(session_uuid: str, kind: str, digest: str) -> Path:
    session = str(_uuid.UUID(session_uuid))  # raises on anything that isn't a UUID: no path tricks
    if not kind.isalpha():
        raise EvidenceError(f"invalid evidence kind {kind!r}")
    return EVIDENCE_DIR / session / f"{kind}-{digest[:16]}.bin"


def evidence_ref(kind: str, data: bytes) -> str:
    """'<kind>:<sha256>' — the form sealed into the ledger record."""
    return f"{kind}:{hashlib.sha256(data).hexdigest()}"


def store(session_uuid: str, kind: str, data: bytes) -> str:
    """Encrypts and writes one uploaded file; returns its evidence ref. Raises EvidenceError
    (never silently skips) when it can't be retained."""
    ref = evidence_ref(kind, data)
    try:
        path = _path(session_uuid, kind, ref.split(":", 1)[1])
    except ValueError as err:
        raise EvidenceError(f"invalid screening id {session_uuid!r}") from err
    nonce = os.urandom(12)
    # Associated data binds the ciphertext to this case + document kind.
    sealed = MAGIC + nonce + AESGCM(_key()).encrypt(nonce, data, f"{path.parent.name}/{kind}".encode())
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "wb") as fh:
            fh.write(sealed)
    except OSError as err:
        raise EvidenceError(f"could not write evidence: {err}") from err
    return ref


def load(session_uuid: str, kind: str, digest: str) -> bytes:
    """Decrypts a stored file (audits/tests). Raises if missing, tampered or keyed differently."""
    path = _path(session_uuid, kind, digest)
    blob = path.read_bytes()
    if not blob.startswith(MAGIC):
        raise EvidenceError("not a PRAMAN evidence file")
    nonce, ciphertext = blob[len(MAGIC):len(MAGIC) + 12], blob[len(MAGIC) + 12:]
    data = AESGCM(_key()).decrypt(nonce, ciphertext, f"{path.parent.name}/{kind}".encode())
    if hashlib.sha256(data).hexdigest() != digest:
        raise EvidenceError("decrypted evidence does not match its recorded SHA-256")
    return data
