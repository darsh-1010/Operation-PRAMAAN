"""Loads the DEMO watchlist + issuer-registry records the team has been testing with (and that
tests/test_ocr_service.py expects). Never runs automatically: demo people on a real watchlist
would reject real travellers. Idempotent (existing ids are left untouched).

    python seed_demo_data.py
    docker compose exec ocr-consistency-check python seed_demo_data.py
"""
from db import DatabaseManager

WATCHLIST = [
    ("w1", "BLACKLIST_DOC", "B6666666", "KHAN, DAWOOD", "1975-12-26", "IND", "Fraudulent Passport Flagged by CBI", "NATIONAL_DB"),
    ("w2", "LOST_STOLEN", "S5555555", "BROWN, DAVID", "1982-05-14", "GBR", "Stolen passport reported to Interpol SLTD", "INTERPOL_SLTD"),
    ("w3", "BLACKLIST_PERSON", None, "MALIK, TARIQ", "1979-03-25", "IND", "High-risk security watchlist", "INTERPOL"),
]
REGISTRY = [
    ("g1", "PASSPORT", "P1234567", "SHARMA, ARYA", "1995-08-15", "M", "2020-01-10", "2030-01-09", "IND", "ACTIVE"),
    ("g2", "PASSPORT", "L898902C", "ERIKSSON, ANNA MARIA", "1974-08-12", "F", "2019-01-01", "2029-01-01", "IND", "ACTIVE"),
    ("g3", "PASSPORT", "R9999999", "SINGH, VIKRAM", "1985-04-12", "M", "2018-02-15", "2028-02-14", "IND", "REVOKED"),
    ("g4", "PASSPORT", "E1111111", "GUPTA, PRIYA", "1988-06-30", "F", "2012-07-01", "2022-06-30", "IND", "EXPIRED"),
    ("g5", "NATIONAL_ID", "987654321012", "KUMAR, ROHIT", "1990-11-20", "M", "2015-05-01", "2035-05-01", "IND", "ACTIVE"),
]


def main() -> None:
    db = DatabaseManager.get_instance()
    for row in WATCHLIST:
        db.execute(
            "INSERT INTO watchlist_entries (entry_id, kind, doc_number, full_name, dob, nationality, reason, source, active) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 1) ON CONFLICT (entry_id) DO NOTHING", row)
    for row in REGISTRY:
        db.execute(
            "INSERT INTO ground_truth_records (record_id, doc_type, id_number, full_name, dob, gender, issue_date, "
            "expiry_date, issuing_country, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (record_id) DO NOTHING", row)
    print(f"Demo data present: {len(WATCHLIST)} watchlist entries, {len(REGISTRY)} registry records.")


if __name__ == "__main__":
    main()
