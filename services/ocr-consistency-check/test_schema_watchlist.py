"""Self-check for schema.py + db_repository.py (every write method, against a real Postgres) and
for watchlist name matching. The DB part needs a reachable Postgres (the usual POSTGRES_* env
vars) and is skipped without one; the matching part runs anywhere.
Run: python test_schema_watchlist.py, or via pytest.
"""
import uuid

from candidate_search import CandidateSearchEngine, normalize_doc_number, normalize_watchlist_name
from decision_matrix import evaluate_decision_matrix
from field_patterns import ParsedDocumentData
from matcher import match_against_candidate

ENTRIES = [
    {"entry_id": "w1", "kind": "BLACKLIST_DOC", "doc_number": "B6666666", "full_name": "KHAN, DAWOOD", "dob": "1975-12-26", "reason": None, "source": "NATIONAL_DB"},
    {"entry_id": "w3", "kind": "BLACKLIST_PERSON", "doc_number": None, "full_name": "MALIK, TARIQ", "dob": "1979-03-25", "reason": None, "source": "INTERPOL"},
    {"entry_id": "w4", "kind": "BLACKLIST_PERSON", "doc_number": None, "full_name": "MOHAMMED IQBAL SHAIKH", "dob": "1981-02-02", "reason": None, "source": "NATIONAL_DB"},
]


class FakeDB:
    def query(self, sql, params=()):
        assert "CAST(active AS INTEGER) = 1" in sql
        return [dict(e) for e in ENTRIES]


def _screen(number=None, name=None, dob=None):
    return CandidateSearchEngine(db=FakeDB()).screen_watchlist(number, name, dob)


def test_normalizers() -> None:
    assert normalize_watchlist_name("Khan, Dawood.") == normalize_watchlist_name("DAWOOD  KHAN") == "DAWOOD KHAN"
    assert normalize_doc_number(" b-666 6666 ") == "B6666666" and normalize_doc_number(None) == ""


def test_document_number_hit_ignores_formatting() -> None:
    hits = _screen("b 6666-666")
    assert [(h.entry_id, h.match_basis, h.is_hard_fail) for h in hits] == [("w1", "DOC_NUMBER", True)]


def test_name_in_any_order_with_same_dob_is_a_hard_hit() -> None:
    for name in ("TARIQ MALIK", "MALIK TARIQ", "Malik, Tariq"):
        hits = _screen(name=name, dob="1979-03-25")
        assert [(h.entry_id, h.match_basis, h.is_hard_fail) for h in hits] == [("w3", "NAME_DOB", True)], name


def test_spelling_variant_and_ocr_slip_still_hit() -> None:
    assert _screen(name="MOHAMMAD IQBAL SHAIKH", dob="02/02/1981")[0].entry_id == "w4"  # Mohammed/Mohammad, DD/MM/YYYY
    assert _screen(name="TAR1Q MALIK", dob="1979-03-25")[0].entry_id == "w3"  # OCR read I as 1


def test_same_name_different_dob_is_not_a_hit() -> None:
    assert _screen(name="TARIQ MALIK", dob="1990-01-01") == []


def test_name_without_dob_is_review_not_reject() -> None:
    hits = _screen(name="TARIQ MALIK")
    assert [(h.match_basis, h.is_hard_fail) for h in hits] == [("NAME_ONLY", False)]
    parsed = ParsedDocumentData(doc_type="PASSPORT", document_number="Z1234567", claimed_name="TARIQ MALIK")
    decision = evaluate_decision_matrix(parsed, match_against_candidate(parsed, None), hits)
    assert not decision.hard_fail and decision.reason_codes[0].code == "WATCHLIST_POSSIBLE_BLACKLIST_PERSON"


def test_unrelated_person_is_not_a_hit() -> None:
    assert _screen("P1234567", "ARYA SHARMA", "1995-08-15") == []


def test_every_repository_write_against_real_postgres() -> None:
    try:
        from db import DatabaseManager
        db = DatabaseManager.get_instance()  # runs schema.apply()
    except RuntimeError as err:
        print(f"SKIPPED (no Postgres): {err}")
        return
    s, d, x = str(uuid.uuid4()), str(uuid.uuid4()), str(uuid.uuid4())
    db.upsert_screening_session(s, "test", "PROCESSING")
    db.upsert_screening_session(s, "test", "COMPLETED")  # ON CONFLICT path
    db.insert_document(d, s, "NATIONAL_ID", "XXXXXXXX7058", "RAVI", "1990", None, "M", "IND")  # year-only DOB
    assert db.insert_capture(s, d, "DOCUMENT_PHOTO", "evidence://x", "ab" * 32, "image/png", 10, 10)
    db.insert_ocr_extraction(x, d, "tesseract-5", "5", None, 0.9)
    db.insert_extracted_field(x, d, "NAME", "RAVI", "VIZ", 0.9, {"x": 1})
    db.insert_validation_check(d, "MODULE_1", "MRZ_CHECKSUM", "mrz", "PASS", False, "VALID", "VALID", "ok")
    db.insert_watchlist_hit(s, d, "w1", "DOC_NUMBER", 1.0, True)
    db.upsert_module_score(s, "A", 0.5, {"k": 1})
    db.upsert_module_score(s, "A", 0.9, {"k": 2})  # ON CONFLICT (session_id, score_kind)
    db.insert_audit_log(s, "TEST", "SESSION", s, {"ok": True})
    status = db.query("SELECT status FROM screening_sessions WHERE session_id = %s", (s,))[0]["status"]
    score = db.query("SELECT value FROM module_scores WHERE session_id = %s", (s,))
    flag = db.query("SELECT is_hard_fail FROM watchlist_hits WHERE session_id = %s", (s,))[0]["is_hard_fail"]
    assert status == "COMPLETED" and len(score) == 1 and abs(score[0]["value"] - 0.9) < 1e-6 and flag == 1


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: schema + watchlist checks passed")
