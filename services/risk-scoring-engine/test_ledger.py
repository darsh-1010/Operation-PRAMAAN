"""Self-check for the blockchain ledger: Merkle maths, then the full path — _persist → batch →
anchor on a REAL in-process EVM (py-evm via eth-tester, running the compiled
contracts/PramanAnchor.json) → /ledger/verify — including the insider-tampering cases the
whole feature exists to catch. Needs `pip install "web3[tester]"` (dev only, not in the image).
Run: python test_ledger.py, or via pytest.
"""
import hashlib
import os
import uuid as _uuid

os.environ.setdefault("DATABASE_URL", "postgresql://nobody@127.0.0.1:1/none")  # force SQLite fallback

from eth_account import Account
from fastapi.testclient import TestClient
from web3 import EthereumTesterProvider, Web3

import anchor
import chain as chain_mod
import ledger
import ledger_db
import main
from db import RiskResultDB
from ledger_routes import verify_record

# ---------------------------------------------------------------- Merkle maths


def _leaves(n: int) -> list[bytes]:
    return [ledger.leaf_hash(f"record-{i}") for i in range(n)]


def test_every_leaf_proves_into_root_for_many_sizes() -> None:
    for n in range(1, 34):
        leaves = _leaves(n)
        root = ledger.merkle_root(leaves)
        for i, leaf in enumerate(leaves):
            assert ledger.root_from_proof(leaf, ledger.merkle_proof(leaves, i)) == root, (n, i)


def test_changed_leaf_or_wrong_proof_fails() -> None:
    leaves = _leaves(7)
    root = ledger.merkle_root(leaves)
    proof = ledger.merkle_proof(leaves, 3)
    assert ledger.root_from_proof(ledger.leaf_hash("forged"), proof) != root
    assert ledger.root_from_proof(leaves[3], ledger.merkle_proof(leaves, 4)) != root


def test_no_duplicate_last_leaf_collision() -> None:
    a, b, c = _leaves(3)
    assert ledger.merkle_root([a, b, c]) != ledger.merkle_root([a, b, c, c])  # CVE-2012-2459 shape
    assert ledger.merkle_root([a, b]) != hashlib.sha256(a + b).digest()  # inner nodes are domain-separated


def test_canonical_is_key_order_independent() -> None:
    assert ledger.canonical({"b": 1, "a": [2, 3]}) == ledger.canonical({"a": [2, 3], "b": 1}) == '{"a":[2,3],"b":1}'


# ---------------------------------------------------------------- chain + DB end-to-end

OWNER_KEY = "0x" + "11" * 32


def _fresh_env():
    """New SQLite DB + new EVM with PramanAnchor deployed by OWNER_KEY."""
    w3 = Web3(EthereumTesterProvider())
    owner = Account.from_key(OWNER_KEY)
    w3.eth.send_transaction({"from": w3.eth.accounts[0], "to": owner.address, "value": w3.to_wei(10, "ether")})
    factory = w3.eth.contract(abi=chain_mod.ARTIFACT["abi"], bytecode=chain_mod.ARTIFACT["bytecode"])
    tx = factory.constructor().build_transaction({"from": owner.address, "nonce": 0, "chainId": w3.eth.chain_id})
    receipt = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(owner.sign_transaction(tx).raw_transaction))
    db = RiskResultDB()
    main._db = db  # _persist writes here
    chain = chain_mod.Chain(w3, receipt["contractAddress"], OWNER_KEY, "https://explorer.example")
    return db, chain


def _decide(n: int) -> list[str]:
    uuids = [str(_uuid.uuid4()) for _ in range(n)]
    for i, u in enumerate(uuids):
        main._persist(u, 50.0 + i + 0.123456789, "MANUAL_REVIEW", [f"REASON_{i}"], [])
    return uuids


def _status(db, chain, uuid: str) -> str:
    return verify_record(db, chain, uuid).status


def test_anchor_then_verify_all_records() -> None:
    db, chain = _fresh_env()
    uuids = _decide(5)
    assert _status(db, chain, uuids[0]) == "PENDING"
    assert anchor.anchor_once(db, chain) == {"confirmed": 1}
    assert chain.last_batch_id() == 1
    for u in uuids:
        res = verify_record(db, chain, u)
        assert res.status == "VERIFIED", res.checks
        assert res.leaf_count == 5 and res.tx_hash and res.tx_url.startswith("https://explorer.example/tx/0x")

    later = _decide(2)  # new decisions go into the next batch, old ones stay verified
    assert _status(db, chain, later[0]) == "PENDING"
    assert anchor.anchor_once(db, chain) == {"confirmed": 1}
    assert _status(db, chain, later[1]) == "VERIFIED" and _status(db, chain, uuids[4]) == "VERIFIED"
    assert anchor.anchor_once(db, chain) == {"confirmed": 0}  # nothing new: no empty batch


def test_insider_edits_decision_column() -> None:
    db, chain = _fresh_env()
    uuids = _decide(3)
    anchor.anchor_once(db, chain)
    with db.transaction() as cur:
        cur.execute("UPDATE risk_results SET decision = 'PASS' WHERE session_id = %s", (uuids[1],))
    res = verify_record(db, chain, uuids[1])
    assert res.status == "TAMPERED"
    assert any(c.ok is False and "decision" in c.detail for c in res.checks)
    assert _status(db, chain, uuids[0]) == "VERIFIED"  # untouched neighbours unaffected


def test_insider_rewrites_sealed_copy_consistently() -> None:
    """Attacker edits the column AND the canonical JSON AND the stored leaf hash so the row is
    self-consistent. Only the on-chain root can catch this — and it does, for the whole batch."""
    db, chain = _fresh_env()
    uuids = _decide(4)
    anchor.anchor_once(db, chain)
    row = verify_record(db, chain, uuids[2]).record
    forged = ledger.canonical({**row, "decision": "PASS"})
    with db.transaction() as cur:
        cur.execute("UPDATE risk_results SET decision = 'PASS', canonical = %s, leaf_hash = %s WHERE session_id = %s",
                    (forged, ledger.leaf_hash(forged).hex(), uuids[2]))
    res = verify_record(db, chain, uuids[2])
    assert res.status == "TAMPERED" and res.checks[-1].name == "Chain root matches" and res.checks[-1].ok is False
    assert _status(db, chain, uuids[0]) == "TAMPERED"  # batch-mates are flagged too


def test_insider_deletes_a_record() -> None:
    db, chain = _fresh_env()
    uuids = _decide(4)
    anchor.anchor_once(db, chain)
    with db.transaction() as cur:
        cur.execute("DELETE FROM risk_results WHERE session_id = %s", (uuids[3],))
    res = verify_record(db, chain, uuids[0])
    assert res.status == "TAMPERED" and "removed" in res.checks[-1].detail


def test_crash_after_broadcast_recovers_without_double_anchoring() -> None:
    db, chain = _fresh_env()
    uuids = _decide(2)
    batch = ledger_db.create_batch(db, 100, chain.last_batch_id())
    tx = chain.send_anchor(batch["batch_id"], batch["merkle_root"], batch["leaf_count"])  # ...then "crash"
    chain.wait_receipt(tx)
    assert anchor.anchor_once(db, chain) == {"confirmed": 1}
    assert chain.last_batch_id() == 1
    assert ledger_db.get_batch(db, 1)["tx_hash"] == tx  # recovered from the Anchored event
    assert _status(db, chain, uuids[1]) == "VERIFIED"


def test_contract_rules() -> None:
    db, chain = _fresh_env()
    _decide(1)
    anchor.anchor_once(db, chain)
    for batch_id, reason in ((1, "out of sequence"), (5, "out of sequence")):
        try:
            chain.send_anchor(batch_id, "ab" * 32, 1)
            raise AssertionError("contract accepted a bad batch id")
        except Exception as err:
            assert reason in str(err), err
    try:
        chain_mod.Chain(chain.w3, chain.address, "0x" + "22" * 32)
        raise AssertionError("non-owner signer accepted")
    except chain_mod.ChainError as err:
        assert "not the contract owner" in str(err)
    try:
        chain_mod.Chain(chain.w3, chain.address, chain_mod._PUBLIC_DEV_KEY)
        raise AssertionError("public dev key accepted on a non-dev chain")
    except chain_mod.ChainError as err:
        assert "public Anvil dev key" in str(err)


def test_http_endpoints() -> None:
    db, chain = _fresh_env()
    RiskResultDB._instance, anchor.state["chain"] = db, chain
    uuids = _decide(3)
    anchor.anchor_once(db, chain)
    client = TestClient(main.app)
    body = client.get(f"/ledger/verify/{uuids[0]}").json()
    assert body["status"] == "VERIFIED" and len(body["checks"]) == 6
    assert client.get(f"/ledger/verify/{_uuid.uuid4()}").status_code == 404
    status = client.get("/ledger/status").json()
    assert status["enabled"] and status["chain"]["last_batch_id"] == 1 and status["counts"]["records"] == 3
    batches = client.get("/ledger/batches").json()
    assert batches[0]["status"] == "CONFIRMED" and batches[0]["leaf_count"] == 3
    detail = client.get("/ledger/batches/1").json()
    assert [r["uuid"] for r in detail["records"]] == uuids
    anchor.state["chain"] = None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all ledger checks passed")
