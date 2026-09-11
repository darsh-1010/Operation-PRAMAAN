"""Unit and Integration Tests for Module 1 (OCR & Consistency Check).

Verifies:
- Document file ingestion (Images, MIME detection, SHA-256)
- ICAO Doc 9303 MRZ parsing and checksum tampering detection
- Field normalization (Dates, Names, ID numbers)
- Candidate database search and watchlist screening
- Fuzzy and exact matching logic
- Scoring and decision matrix (VERIFIED, NEEDS REVIEW, NOT VERIFIED, hard-fails)
- FastAPI REST API endpoints
"""

import io
import os
import sys
import unittest
import numpy as np
from PIL import Image

# Ensure service directory is on sys.path
SERVICE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVICE_DIR not in sys.path:
    sys.path.insert(0, SERVICE_DIR)

from starlette.testclient import TestClient
from candidate_search import CandidateRecord, CandidateSearchEngine, WatchlistHitResult
from db import DatabaseManager
from decision_matrix import DecisionOutcome, evaluate_decision_matrix
from field_extractor import ParsedDocumentData, extract_document_fields
from ingestion import calculate_sha256, detect_mime_type, ingest_file
from matcher import compute_fuzzy_name_score, match_against_candidate
from mrz_verifier import (
    calculate_mrz_checksum,
    extract_and_verify_mrz,
    parse_td1_mrz,
    parse_td3_mrz,
)
from normalizer import normalize_date, normalize_gender, normalize_id_number, normalize_name
from ocr_engine import OCRResult, TextBlock
from main import app


class TestIngestion(unittest.TestCase):
    """Test file ingestion and metadata extraction."""

    def test_calculate_sha256(self):
        data = b"Operation PRAMAAN SIH26188"
        digest = calculate_sha256(data)
        self.assertEqual(len(digest), 64)
        self.assertIsInstance(digest, str)

    def test_detect_mime_type_jpeg(self):
        # JPEG header: \xff\xd8\xff
        raw_jpeg = b"\xff\xd8\xff\xe0" + b"\x00" * 20
        self.assertEqual(detect_mime_type(raw_jpeg, "test.jpg"), "image/jpeg")

    def test_detect_mime_type_png(self):
        raw_png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
        self.assertEqual(detect_mime_type(raw_png, "doc.png"), "image/png")

    def test_ingest_image_bytes(self):
        # Create a blank image in memory
        img = Image.new("RGB", (200, 100), color=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        raw_bytes = buf.getvalue()

        ingested = ingest_file(raw_bytes, "test_doc.png")
        self.assertEqual(ingested.width_px, 200)
        self.assertEqual(ingested.height_px, 100)
        self.assertEqual(ingested.page_count, 1)
        self.assertEqual(ingested.mime_type, "image/png")
        self.assertEqual(len(ingested.sha256), 64)


class TestMRZVerifier(unittest.TestCase):
    """Test ICAO Doc 9303 checksum and parsing algorithms."""

    def test_calculate_mrz_checksum(self):
        # Standard ICAO test case:
        # Document number "L898902C<" check digit is '3'
        self.assertEqual(calculate_mrz_checksum("L898902C<"), 3)
        # DOB "740812" check digit is '2'
        self.assertEqual(calculate_mrz_checksum("740812"), 2)
        # Expiry "120415" check digit is '9'
        self.assertEqual(calculate_mrz_checksum("120415"), 9)

    def test_valid_td3_passport_mrz(self):
        lines = [
            "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<",
            "L898902C<3UTO7408122F1204159ZE184226B<<<<<16",
        ]
        res = parse_td3_mrz(lines)
        self.assertTrue(res.valid_format)
        self.assertFalse(res.has_checksum_failure)
        self.assertEqual(res.doc_type, "PASSPORT")
        self.assertEqual(res.document_number, "L898902C")
        self.assertEqual(res.dob, "1974-08-12")
        self.assertEqual(res.gender, "F")
        self.assertEqual(res.issuing_country, "UTO")
        self.assertEqual(res.full_name, "ERIKSSON ANNA MARIA")

    def test_tampered_td3_passport_mrz(self):
        # Tamper: changed passport number without updating check digit
        lines = [
            "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<",
            "L898909C<3UTO7408122F1204159ZE184226B<<<<<10",  # L898909C instead of L898902C
        ]
        res = parse_td3_mrz(lines)
        self.assertTrue(res.valid_format)
        self.assertTrue(res.has_checksum_failure)
        self.assertTrue(any("Document number checksum mismatch" in f for f in res.failure_details))


class TestNormalizer(unittest.TestCase):
    """Test standardizing dates, names, and identifiers."""

    def test_normalize_date_formats(self):
        expected = "1995-08-15"
        self.assertEqual(normalize_date("15/08/1995"), expected)
        self.assertEqual(normalize_date("15-08-1995"), expected)
        self.assertEqual(normalize_date("1995-08-15"), expected)
        self.assertEqual(normalize_date("15 AUG 1995"), expected)
        self.assertEqual(normalize_date("AUG 15, 1995"), expected)

    def test_normalize_name(self):
        self.assertEqual(normalize_name("MR. ARYA SHARMA"), "ARYA SHARMA")
        self.assertEqual(normalize_name("SHARMA, ARYA"), "ARYA SHARMA")
        self.assertEqual(normalize_name("Dr. Vikram   Singh"), "VIKRAM SINGH")

    def test_normalize_id_number(self):
        self.assertEqual(normalize_id_number("P 1234567"), "P1234567")
        self.assertEqual(normalize_id_number("DL-04-20110012345"), "DL0420110012345")
        self.assertEqual(normalize_id_number("9876 5432 1012"), "987654321012")


class TestMatchingAndDecisionMatrix(unittest.TestCase):
    """Test candidate search, fuzzy matching, and decision matrix scoring."""

    def setUp(self):
        self.search_engine = CandidateSearchEngine()

    def test_fuzzy_name_matching(self):
        # Inverted names
        score = compute_fuzzy_name_score("ARYA SHARMA", "SHARMA, ARYA")
        self.assertGreaterEqual(score, 0.90)

        # Minor OCR typo
        score_typo = compute_fuzzy_name_score("ROHIT KUMAR", "ROHIT KUMAP")
        self.assertGreaterEqual(score_typo, 0.85)

    def test_decision_matrix_verified(self):
        # Candidate exists and credentials match
        parsed = ParsedDocumentData(
            doc_type="PASSPORT",
            document_number="P1234567",
            claimed_name="ARYA SHARMA",
            claimed_dob="1995-08-15",
            claimed_expiry="2030-01-09",
        )
        candidates = self.search_engine.find_candidate_documents("PASSPORT", "P1234567", "1995-08-15")
        self.assertTrue(len(candidates) > 0)

        match = match_against_candidate(parsed, candidates[0])
        self.assertTrue(match.is_id_matched)
        self.assertTrue(match.is_dob_matched)

        decision = evaluate_decision_matrix(parsed, match, watchlist_hits=[])
        self.assertEqual(decision.status, "VERIFIED")
        self.assertFalse(decision.hard_fail)
        self.assertGreaterEqual(decision.score, 85.0)

    def test_decision_matrix_watchlist_hard_fail(self):
        # Blacklisted passport
        parsed = ParsedDocumentData(
            doc_type="PASSPORT",
            document_number="B6666666",
            claimed_name="DAWOOD KHAN",
            claimed_dob="1975-12-26",
        )
        hits = self.search_engine.screen_watchlist(parsed.document_number, parsed.claimed_name, parsed.claimed_dob)
        self.assertTrue(len(hits) > 0)

        match = match_against_candidate(parsed, None)
        decision = evaluate_decision_matrix(parsed, match, watchlist_hits=hits)

        self.assertEqual(decision.status, "NOT VERIFIED")
        self.assertTrue(decision.hard_fail)
        self.assertEqual(decision.score, 0.0)
        self.assertTrue(any("WATCHLIST_HIT" in r.code for r in decision.reason_codes))

    def test_decision_matrix_revoked_document(self):
        # Candidate document is revoked
        parsed = ParsedDocumentData(
            doc_type="PASSPORT",
            document_number="R9999999",
            claimed_name="VIKRAM SINGH",
            claimed_dob="1985-04-12",
        )
        candidates = self.search_engine.find_candidate_documents("PASSPORT", "R9999999")
        self.assertTrue(len(candidates) > 0)
        self.assertEqual(candidates[0].status, "REVOKED")

        match = match_against_candidate(parsed, candidates[0])
        decision = evaluate_decision_matrix(parsed, match, watchlist_hits=[])

        self.assertEqual(decision.status, "NOT VERIFIED")
        self.assertTrue(decision.hard_fail)
        self.assertEqual(decision.score, 0.0)


class TestAPIEndpoints(unittest.TestCase):
    """Test FastAPI application endpoints."""

    def setUp(self):
        self.client = TestClient(app)

    def test_health_check(self):
        res = self.client.get("/api/v1/health")
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "healthy")
        self.assertEqual(data["service"], "ocr-consistency-check")

    def test_verify_text_endpoint(self):
        payload = {
            "doc_type": "PASSPORT",
            "document_number": "P1234567",
            "full_name": "ARYA SHARMA",
            "dob": "1995-08-15",
        }
        res = self.client.post("/api/v1/verify-text", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["status"], "VERIFIED")
        self.assertFalse(data["hard_fail"])
        self.assertGreaterEqual(data["score"], 85.0)

    def test_screen_endpoint_upload(self):
        img = Image.new("RGB", (300, 100), color=(240, 240, 240))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        file_bytes = buf.getvalue()

        res = self.client.post(
            "/api/v1/screen",
            files={"file": ("doc.png", file_bytes, "image/png")},
            data={"session_id": "test-session-123"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["session_id"], "test-session-123")
        self.assertIn("score", data)
        self.assertIn("hard_fail", data)
        self.assertIn("status", data)
        self.assertIn("reason_codes", data)
        self.assertIn("validation_checks", data)

    def test_extract_only_endpoint_upload(self):
        img = Image.new("RGB", (300, 100), color=(240, 240, 240))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        file_bytes = buf.getvalue()

        res = self.client.post(
            "/api/v1/extract-only",
            files={"file": ("doc.png", file_bytes, "image/png")},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("doc_type", data)
        self.assertIn("fields", data)
        self.assertIn("raw_text", data)


if __name__ == "__main__":
    unittest.main()

