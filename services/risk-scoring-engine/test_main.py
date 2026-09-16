"""Runnable self-check for the risk engine's /flag-check, /submit-score and /result
endpoints, using FastAPI's TestClient (no live server thread needed — these are JSON-only,
unlike the other 3 services' file-upload /screen endpoint).
Run: python test_main.py, or via pytest.
"""
import uuid as _uuid

from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def _new_uuid() -> str:
    return str(_uuid.uuid4())


def test_health() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_full_flow_reaches_decision() -> None:
    uid = _new_uuid()

    resp = client.post("/flag-check", json={"uuid": uid, "module": "ocr", "flag": False})
    assert resp.json()["status"] == "WAITING_ON_OTHER_FLAG"

    resp = client.post("/flag-check", json={"uuid": uid, "module": "forensics", "flag": False})
    assert resp.json()["status"] == "WAITING_ON_SCORES"

    resp = client.post("/submit-score", json={"uuid": uid, "module": "ocr", "ocr": {"score": 90}})
    assert resp.json()["status"] == "STORED_WAITING_ON_FLAGS" or resp.json()["status"] == "WAITING_ON_OTHER_SCORES"

    resp = client.post("/submit-score", json={"uuid": uid, "module": "tamper", "tamper": {"score": 100}})
    assert resp.json()["status"] == "WAITING_ON_OTHER_SCORES"

    resp = client.post("/submit-score", json={"uuid": uid, "module": "photo", "photo": {"score": 95, "hard_fail": False}})
    body = resp.json()
    assert body["status"] == "DONE"
    assert body["decision"] == "PASS"
    assert body["score"] == 0.25 * 90 + 0.40 * 100 + 0.35 * 95

    # Finalized result must stay retrievable via GET /result, and a late duplicate
    # /flag-check for the same uuid must echo the decision rather than reopening it.
    resp = client.get(f"/result/{uid}")
    assert resp.status_code == 200
    assert resp.json()["decision"] == "PASS"

    resp = client.post("/flag-check", json={"uuid": uid, "module": "ocr", "flag": False})
    assert resp.json() == {"uuid": uid, "status": "DONE", "score": body["score"], "decision": "PASS"}


def test_flag_true_rejects_immediately_without_waiting_on_other_flag() -> None:
    uid = _new_uuid()
    resp = client.post("/flag-check", json={"uuid": uid, "module": "ocr", "flag": True, "reasons": ["FORGED_MRZ"]})
    body = resp.json()
    assert body == {"uuid": uid, "status": "REJECTED", "score": 0, "decision": "REJECTED"}

    # A score arriving after rejection must not resurrect or re-score the uuid — it just
    # echoes the already-finalized decision (status "DONE", same as any late arrival).
    resp = client.post("/submit-score", json={"uuid": uid, "module": "ocr", "ocr": {"score": 100}})
    late_body = resp.json()
    assert late_body["status"] == "DONE"
    assert late_body["decision"] == "REJECTED"
    assert late_body["score"] == 0


def test_photo_hard_fail_rejects_even_before_flags_clear() -> None:
    uid = _new_uuid()
    resp = client.post(
        "/submit-score",
        json={"uuid": uid, "module": "photo", "photo": {"score": 0, "hard_fail": True, "reasons": ["SPOOF_DETECTED"]}},
    )
    assert resp.json() == {"uuid": uid, "status": "REJECTED", "score": 0, "decision": "REJECTED"}


def test_result_lookup_404_for_unknown_uuid() -> None:
    resp = client.get(f"/result/{_new_uuid()}")
    assert resp.status_code == 404


if __name__ == "__main__":
    test_health()
    test_full_flow_reaches_decision()
    test_flag_true_rejects_immediately_without_waiting_on_other_flag()
    test_photo_hard_fail_rejects_even_before_flags_clear()
    test_result_lookup_404_for_unknown_uuid()
    print("OK: all risk-scoring-engine checks passed")
