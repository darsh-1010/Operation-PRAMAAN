"""Tamper-evidence primitives for finalized decisions: canonical record, leaf hash, Merkle
tree, inclusion proofs. Pure stdlib, no I/O — anchor.py does the chain side, db.py storage.

Hashing follows RFC 6962 (Certificate Transparency) domain separation: leaves are
sha256(0x00 ‖ data), inner nodes sha256(0x01 ‖ left ‖ right). Without the prefixes a
leaf could be passed off as an inner node and a second, different tree could produce the
same root (the Bitcoin CVE-2012-2459 family). An odd node at the end of a level is carried
up unchanged rather than duplicated, for the same reason.
"""
from __future__ import annotations

import hashlib
import json

LEAF_PREFIX = b"\x00"
NODE_PREFIX = b"\x01"


def canonical(record: dict) -> str:
    """Byte-stable JSON: sorted keys, no whitespace, no NaN. This exact string is what gets
    hashed AND stored — never re-serialize a record from DB columns to verify it (Postgres
    REAL is a 4-byte float, so a round-tripped score would hash differently)."""
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def leaf_hash(canonical_record: str) -> bytes:
    return hashlib.sha256(LEAF_PREFIX + canonical_record.encode("utf-8")).digest()


def _node(left: bytes, right: bytes) -> bytes:
    return hashlib.sha256(NODE_PREFIX + left + right).digest()


def _next_level(level: list[bytes]) -> list[bytes]:
    nxt = [_node(level[i], level[i + 1]) for i in range(0, len(level) - 1, 2)]
    if len(level) % 2:
        nxt.append(level[-1])  # carried up, not duplicated
    return nxt


def merkle_root(leaves: list[bytes]) -> bytes:
    if not leaves:
        raise ValueError("cannot build a Merkle root over zero leaves")
    level = list(leaves)
    while len(level) > 1:
        level = _next_level(level)
    return level[0]


def merkle_proof(leaves: list[bytes], index: int) -> list[tuple[str, bytes]]:
    """Sibling path from leaf `index` to the root, as ("L"|"R", sibling) pairs, where the
    side says which side the SIBLING sits on."""
    if not 0 <= index < len(leaves):
        raise IndexError(f"leaf index {index} out of range for {len(leaves)} leaves")
    proof: list[tuple[str, bytes]] = []
    level = list(leaves)
    while len(level) > 1:
        sibling = index ^ 1
        if sibling < len(level):
            proof.append(("L" if sibling < index else "R", level[sibling]))
        index //= 2
        level = _next_level(level)
    return proof


def root_from_proof(leaf: bytes, proof: list[tuple[str, bytes]]) -> bytes:
    acc = leaf
    for side, sibling in proof:
        acc = _node(sibling, acc) if side == "L" else _node(acc, sibling)
    return acc
