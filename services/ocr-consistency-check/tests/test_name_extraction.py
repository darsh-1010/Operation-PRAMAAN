"""Unit tests for robust identity name extraction and MRZ candidate ranking."""

from __future__ import annotations
import unittest

from field_extractor import extract_document_fields, _extract_positional_national_id_name
from mrz_verifier import extract_and_verify_mrz
from ocr_engine import OCRResult, TextBlock


class TestNameExtraction(unittest.TestCase):
    def test_us_visa_avoids_control_number(self):
        """Ensure 'Issuing Post Name' does not match 'Control Number' as person's name."""
        lines = [
            "SS Issuing Post Name Control Number CES",
            "LONDON LND1234567890",
            "Surname CAMPBELL",
            "Given Name AMELIA ROSE",
            "Passport Number A12345678",
            "Sex F Birth Date 22NOV1996",
            "Issue Date 22MAY2023 Expiration Date 22NOV2023",
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
        self.assertIsNotNone(parsed.claimed_name)
        self.assertNotIn("CONTROL", parsed.claimed_name.upper())
        self.assertNotIn("NUMBER", parsed.claimed_name.upper())
        self.assertIn("CAMPBELL", parsed.claimed_name)
        self.assertIn("AMELIA", parsed.claimed_name)

    def test_passport_surname_and_given_name_joining(self):
        """Ensure separate Surname and Given Name fields are merged into full name."""
        lines = [
            "REPUBLIC OF INDIA PASSPORT",
            "Surname / उपनाम",
            "PATEL",
            "Given Name(s) / दिए गए नाम",
            "MAHESH KUMAR",
            "Nationality INDIAN",
            "Sex M Date of Birth 05/01/1985",
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
        self.assertEqual(parsed.claimed_name, "PATEL MAHESH KUMAR")

    def test_aadhaar_positional_name_extraction(self):
        """Ensure Aadhaar layout without 'NAME:' label extracts the person's name."""
        lines = [
            "Government of India",
            "भारत सरकार",
            "आरव पटेल",
            "Aarav Patel",
            "DOB: 15/08/1990",
            "पुरुष / MALE",
            "3508 0660 6149",
        ]
        extracted = _extract_positional_national_id_name(lines)
        self.assertEqual(extracted, "Aarav Patel")

        ocr_res = OCRResult(
            blocks=[TextBlock(text=l, confidence=0.95, bbox={"x": 0, "y": 0, "w": 100, "h": 20}) for l in lines],
            full_text="\n".join(lines),
            lines=lines,
            engine="test",
            model_version="test",
            average_confidence=0.95,
        )
        parsed = extract_document_fields(ocr_res)
        self.assertEqual(parsed.claimed_name, "AARAV PATEL")
        self.assertEqual(parsed.document_number, "350806606149")

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
