"""Unit tests for MRZ identity name extraction and MRZ candidate ranking."""

from __future__ import annotations
import unittest

from field_extractor import extract_document_fields
from mrz_verifier import extract_and_verify_mrz
from ocr_engine import OCRResult, TextBlock


class TestNameExtraction(unittest.TestCase):
    def test_td3_passport_mrz_name_extraction(self):
        """Ensure full name is extracted from TD3 passport MRZ."""
        lines = [
            "P<INDMAHESH<<KUMAR<<<<<<<<<<<<<<<<<<<<<<<<<<",
            "Z1234567<8IND8501055M3001018<<<<<<<<<<<<<<<2",
        ]
        ocr_res = OCRResult(
            blocks=[TextBlock(text=l, confidence=0.95, bbox={"x": 0, "y": 0, "w": 100, "h": 20}) for l in lines],
            full_text="\n".join(lines),
            lines=lines,
            engine="test",
            model_version="test",
            average_confidence=0.95,
        )
        parsed = extract_document_fields(ocr_res)
        self.assertEqual(parsed.claimed_name, "MAHESH KUMAR")
        self.assertEqual(parsed.document_number, "Z1234567")
        self.assertEqual(parsed.doc_type, "PASSPORT")

    def test_td1_national_id_mrz_name_extraction(self):
        """Ensure full name is extracted from TD1 3-line MRZ."""
        lines = [
            "I<UTOD231458907<<<<<<<<<<<<<<<",
            "7408122F1204159UTO<<<<<<<<<<<6",
            "ERIKSSON<<ANNA<MARIA<<<<<<<<<<",
        ]
        ocr_res = OCRResult(
            blocks=[TextBlock(text=l, confidence=0.95, bbox={"x": 0, "y": 0, "w": 100, "h": 20}) for l in lines],
            full_text="\n".join(lines),
            lines=lines,
            engine="test",
            model_version="test",
            average_confidence=0.95,
        )
        parsed = extract_document_fields(ocr_res)
        self.assertEqual(parsed.claimed_name, "ERIKSSON ANNA MARIA")
        self.assertEqual(parsed.document_number, "D23145890")
        self.assertEqual(parsed.doc_type, "NATIONAL_ID")

    def test_non_mrz_document_returns_none_for_identity_fields(self):
        """Ensure non-MRZ document does not extract visual text as identity fields (VIZ moved to other module)."""
        lines = [
            "Government of India",
            "Aarav Patel",
            "DOB: 15/08/1990",
            "3508 0660 6149",
        ]
        ocr_res = OCRResult(
            blocks=[TextBlock(text=l, confidence=0.95, bbox={"x": 0, "y": 0, "w": 100, "h": 20}) for l in lines],
            full_text="\n".join(lines),
            lines=lines,
            engine="test",
            model_version="test",
            average_confidence=0.95,
        )
        parsed = extract_document_fields(ocr_res)
        self.assertIsNone(parsed.claimed_name)
        self.assertIsNone(parsed.document_number)

    def test_mrz_checksum_candidate_ranking(self):
        """Ensure error-free MRZ lines are preferred over corrupted 44-character strings."""
        lines = [
            # Corrupted candidate with 4 checksum errors
            "P<IMDRONAMMED<CABBULCRASHEED<<<<<<6KKE60<<<K",
            "N7690965<1IND7BO1OSSMZ2002215<<<<<<<KKKKKKKG",
            # Clean candidate with passing checksums
            "P<INDMOHAMMED<<ABDUL<RASHEED<<<<<<<<<<<<<<<<",
            "H7690945<1IND7801055M2002215<<<<<<<<<<<<<<<6",
        ]
        mrz = extract_and_verify_mrz(lines)
        self.assertIsNotNone(mrz)
        self.assertEqual(mrz.full_name, "MOHAMMED ABDUL RASHEED")
        self.assertEqual(mrz.document_number, "H7690945")
        self.assertFalse(mrz.has_checksum_failure)


if __name__ == "__main__":
    unittest.main()
