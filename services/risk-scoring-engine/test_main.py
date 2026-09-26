"""Runnable self-check for the risk engine's /flag-check, /submit-score and /result
endpoints, using FastAPI's TestClient (no live server thread needed — these are JSON-only,
unlike the other 3 services' file-upload /screen endpoint).
Run: python test_main.py, or via pytest.
"""
import os
import uuid as _uuid

TOKENS = {m: f"test-{m}-token-" + "x" * 32 for m in ("ocr", "forensics", "biometric")}
for _m, _t in TOKENS.items():
    os.environ.setdefault(f"RISK_TOKEN_{_m.upper()}", _t)

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)
# which module's token each payload "module" value must be sent with
_OWNER = {"ocr": "ocr", "forensics": "forensics", "tamper": "forensics", "photo": "biometric"}


def _new_uuid() -> str:
    return client.post("/sessions").json()["uuid"]


def _post(path: str, body: dict, as_module: str | None = None):
    token = TOKENS[as_module or _OWNER[body["module"]]]
    return client.post(path, json=body, headers={"Authorization": f"Bearer {token}"})


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_full_flow_reaches_decision() -> None:
    uid = _new_uuid()

    resp = _post("/flag-check", {"uuid": uid, "module": "ocr", "flag": False})
    assert resp.json()["status"] == "WAITING_ON_OTHER_FLAG"

    resp = _post("/flag-check", {"uuid": uid, "module": "forensics", "flag": False})
    assert resp.json()["status"] == "WAITING_ON_SCORES"

    resp = _post("/submit-score", {"uuid": uid, "module": "ocr", "ocr": {"score": 90}})
    assert resp.json()["status"] == "STORED_WAITING_ON_FLAGS" or resp.json()["status"] == "WAITING_ON_OTHER_SCORES"

    resp = _post("/submit-score", {"uuid": uid, "module": "tamper", "tamper": {"score": 100}})
    assert resp.json()["status"] == "WAITING_ON_OTHER_SCORES"

    resp = _post("/submit-score", {"uuid": uid, "module": "photo", "photo": {"score": 95, "hard_fail": False}})
    body = resp.json()
    assert body["status"] == "DONE"
    assert body["decision"] == "PASS"
    assert body["score"] == 0.25 * 90 + 0.40 * 100 + 0.35 * 95

    # Finalized result must stay retrievable via GET /result, and a late duplicate
    # /flag-check for the same uuid must echo the decision rather than reopening it.
    resp = client.get(f"/result/{uid}")
    assert resp.status_code == 200
    assert resp.json()["decision"] == "PASS"

    resp = _post("/flag-check", {"uuid": uid, "module": "ocr", "flag": False})
    assert resp.json() == {"uuid": uid, "status": "DONE", "score": body["score"], "decision": "PASS"}


def test_flag_true_rejects_immediately_without_waiting_on_other_flag() -> None:
    uid = _new_uuid()
    resp = _post("/flag-check", {"uuid": uid, "module": "ocr", "flag": True, "reasons": ["FORGED_MRZ"]})
    body = resp.json()
    assert body == {"uuid": uid, "status": "REJECTED", "score": 0, "decision": "REJECTED"}

    # A score arriving after rejection must not resurrect or re-score the uuid — it just
    # echoes the already-finalized decision (status "DONE", same as any late arrival).
    resp = _post("/submit-score", {"uuid": uid, "module": "ocr", "ocr": {"score": 100}})
    late_body = resp.json()
    assert late_body["status"] == "DONE"
    assert late_body["decision"] == "REJECTED"
    assert late_body["score"] == 0


def test_photo_hard_fail_rejects_even_before_flags_clear() -> None:
    uid = _new_uuid()
    resp = _post(
        "/submit-score",
        {"uuid": uid, "module": "photo", "photo": {"score": 0, "hard_fail": True, "reasons": ["SPOOF_DETECTED"]}},
    )
    assert resp.json() == {"uuid": uid, "status": "REJECTED", "score": 0, "decision": "REJECTED"}


def test_result_lookup_404_for_unknown_uuid() -> None:
    resp = client.get(f"/result/{_new_uuid()}")
    assert resp.status_code == 404


def test_writes_need_a_valid_module_token() -> None:
    uid = _new_uuid()
    body = {"uuid": uid, "module": "photo", "photo": {"score": 100, "hard_fail": False}}
    assert client.post("/submit-score", json=body).status_code == 401
    assert client.post("/submit-score", json=body, headers={"Authorization": "Bearer wrong"}).status_code == 401
    # a valid token for a DIFFERENT module can't forge this module's score
    assert _post("/submit-score", body, as_module="ocr").status_code == 403
    assert _post("/submit-score", body).status_code == 200


def test_ids_must_be_issued_by_this_service() -> None:
    made_up = str(_uuid.uuid4())
    resp = _post("/flag-check", {"uuid": made_up, "module": "ocr", "flag": False})
    assert resp.status_code == 409


def test_bad_scores_and_evidence_rejected_at_boundary() -> None:
    uid = _new_uuid()
    assert _post("/submit-score", {"uuid": uid, "module": "ocr", "ocr": {"score": 101}}).status_code == 422
    assert _post("/submit-score", {"uuid": uid, "module": "ocr"}).status_code == 422
    assert _post("/flag-check", {"uuid": uid, "module": "ocr", "flag": False, "evidence": ["passport:nothex"]}).status_code == 422


def _complete(uid: str, ocr: float, tamper, photo: float) -> dict:
    _post("/flag-check", {"uuid": uid, "module": "ocr", "flag": False, "evidence": ["passport:" + "a" * 64]})
    _post("/flag-check", {"uuid": uid, "module": "forensics", "flag": False})
    _post("/submit-score", {"uuid": uid, "module": "ocr", "ocr": {"score": ocr}})
    _post("/submit-score", {"uuid": uid, "module": "tamper", "tamper": {"score": tamper}})
    return _post("/submit-score", {"uuid": uid, "module": "photo", "photo": {"score": photo, "hard_fail": False},
                                   "evidence": ["selfie:" + "b" * 64]}).json()


def test_forensics_unavailable_caps_at_manual_review() -> None:
    body = _complete(_new_uuid(), 100, None, 100)  # would be PASS with any real tamper score
    assert body["status"] == "DONE" and body["decision"] == "MANUAL_REVIEW" and body["score"] == 100
    reasons = client.get(f"/result/{body['uuid']}").json()["reasons"]
    assert any(r.startswith("FORENSICS_UNAVAILABLE") for r in reasons)
    # renormalized, not a free 40 points: 0.25*60 + 0.35*50 over 0.6 = 54.17
    assert _complete(_new_uuid(), 60, None, 50)["score"] == 54.17


def test_ocr_review_required_caps_at_manual_review() -> None:
    uid = _new_uuid()
    _post("/flag-check", {"uuid": uid, "module": "ocr", "flag": False})
    _post("/flag-check", {"uuid": uid, "module": "forensics", "flag": False})
    _post("/submit-score", {"uuid": uid, "module": "ocr", "ocr": {"score": 100, "review_required": True}})
    _post("/submit-score", {"uuid": uid, "module": "tamper", "tamper": {"score": 100}})
    body = _post("/submit-score", {"uuid": uid, "module": "photo", "photo": {"score": 100, "hard_fail": False}}).json()
    assert body["decision"] == "MANUAL_REVIEW" and body["score"] == 100


def test_evidence_hashes_are_sealed_into_the_audit_record() -> None:
    import json
    import main
    body = _complete(_new_uuid(), 90, 100, 95)
    with main._db.transaction() as cur:
        cur.execute("SELECT canonical FROM risk_results WHERE session_id = %s", (body["uuid"],))
        sealed = json.loads(cur.fetchone()[0])
    assert sealed["v"] == 2 and sealed["evidence"] == ["passport:" + "a" * 64, "selfie:" + "b" * 64]


if __name__ == "__main__":
    test_health()
    test_full_flow_reaches_decision()
    test_flag_true_rejects_immediately_without_waiting_on_other_flag()
    test_photo_hard_fail_rejects_even_before_flags_clear()
    test_result_lookup_404_for_unknown_uuid()
    test_writes_need_a_valid_module_token()
    test_ids_must_be_issued_by_this_service()
    test_bad_scores_and_evidence_rejected_at_boundary()
    test_forensics_unavailable_caps_at_manual_review()
    test_ocr_review_required_caps_at_manual_review()
    test_evidence_hashes_are_sealed_into_the_audit_record()
    print("OK: all risk-scoring-engine checks passed")
