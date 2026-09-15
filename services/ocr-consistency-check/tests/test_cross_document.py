"""Tests for cross-document consistency checking and field-type validation.

Kept separate from test_ocr_service.py so that file stays within the
project's soft file-size cap.
"""
import io
import os
import sys
import unittest

import numpy as np
from PIL import Image

SERVICE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVICE_DIR not in sys.path:
    sys.path.insert(0, SERVICE_DIR)

from starlette.testclient import TestClient
from cross_document import cross_check_documents
from decision_matrix import _validate_field_formats
from field_extractor import ParsedDocumentData
from main import app


def _tiny_png_bytes() -> bytes:
    img = Image.fromarray(np.full((100, 200, 3), 255, dtype=np.uint8))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class TestCrossDocumentConsistency(unittest.TestCase):
    def test_consistent_documents(self):
        docs = [
            ParsedDocumentData(doc_type="PASSPORT", claimed_name="SHARMA ARYA", claimed_dob="1995-08-15", claimed_gender="M"),
            ParsedDocumentData(doc_type="DRIVING_LICENSE", claimed_name="ARYA SHARMA", claimed_dob="1995-08-15", claimed_gender="M"),
        ]
        outcome = cross_check_documents(docs)
        self.assertTrue(outcome.consistent)

    def test_name_mismatch_flagged(self):
        docs = [
            ParsedDocumentData(doc_type="PASSPORT", claimed_name="SHARMA ARYA", claimed_dob="1995-08-15"),
            ParsedDocumentData(doc_type="VISA", claimed_name="KHAN IMRAN", claimed_dob="1995-08-15"),
        ]
        outcome = cross_check_documents(docs)
        self.assertFalse(outcome.consistent)
        name_result = next(r for r in outcome.field_results if r.field_key == "name")
        self.assertFalse(name_result.consistent)

    def test_dob_mismatch_flagged(self):
        docs = [
            ParsedDocumentData(doc_type="PASSPORT", claimed_name="SHARMA ARYA", claimed_dob="1995-08-15"),
            ParsedDocumentData(doc_type="NATIONAL_ID", claimed_name="SHARMA ARYA", claimed_dob="1980-01-01"),
        ]
        outcome = cross_check_documents(docs)
        dob_result = next(r for r in outcome.field_results if r.field_key == "dob")
        self.assertFalse(dob_result.consistent)

    def test_missing_field_does_not_break_comparison(self):
        docs = [
            ParsedDocumentData(doc_type="PASSPORT", claimed_name="SHARMA ARYA", claimed_dob=None),
            ParsedDocumentData(doc_type="VISA", claimed_name="SHARMA ARYA", claimed_dob="1995-08-15"),
        ]
        outcome = cross_check_documents(docs)
        self.assertTrue(outcome.consistent)


class TestFieldFormatValidation(unittest.TestCase):
    def test_valid_fields_pass(self):
        doc = ParsedDocumentData(
            doc_type="PASSPORT", document_number="P1234567", claimed_name="SHARMA ARYA",
            claimed_dob="1995-08-15", claimed_expiry="2030-01-01",
        )
        checks = _validate_field_formats(doc)
        statuses = {c.field_key: c.status for c in checks}
        self.assertEqual(statuses["name"], "PASS")
        self.assertEqual(statuses["dob"], "PASS")
        self.assertEqual(statuses["document_number"], "PASS")
        self.assertEqual(statuses["expiry"], "PASS")

    def test_future_dob_fails(self):
        doc = ParsedDocumentData(doc_type="PASSPORT", claimed_dob="2999-01-01")
        checks = _validate_field_formats(doc)
        dob_check = next(c for c in checks if c.field_key == "dob")
        self.assertEqual(dob_check.status, "FAIL")

    def test_missing_name_fails(self):
        doc = ParsedDocumentData(doc_type="PASSPORT", claimed_name=None)
        checks = _validate_field_formats(doc)
        name_check = next(c for c in checks if c.field_key == "name")
        self.assertEqual(name_check.status, "FAIL")


class TestCrossVerifyEndpoint(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)

    def test_requires_at_least_two_files(self):
        resp = self.client.post(
            "/api/v1/cross-verify",
            files=[("files", ("a.png", _tiny_png_bytes(), "image/png"))],
        )
        self.assertEqual(resp.status_code, 400)

    def test_accepts_two_files(self):
        png = _tiny_png_bytes()
        resp = self.client.post(
            "/api/v1/cross-verify",
            files=[
                ("files", ("a.png", png, "image/png")),
                ("files", ("b.png", png, "image/png")),
            ],
        )
        self.assertEqual(resp.status_code, 200)
        body = resp.json()
        self.assertIn("consistent", body)
        self.assertEqual(len(body["documents"]), 2)


if __name__ == "__main__":
    unittest.main()
