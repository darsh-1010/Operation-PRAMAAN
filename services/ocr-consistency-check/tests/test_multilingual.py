"""Comprehensive Tests for Multilingual OCR, Language Detection, and Nepali Calendar Conversion."""

import io
import os
import sys
import unittest
from PIL import Image

# Ensure service directory is on sys.path
SERVICE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVICE_DIR not in sys.path:
    sys.path.insert(0, SERVICE_DIR)

from starlette.testclient import TestClient
from main import app
from nepali_calendar import (
    convert_bikram_sambat,
    convert_bs_year_to_gregorian,
    to_ascii_digits,
)
from script_detector import detect_script_and_language
from multilingual_consistency import (
    check_nepali_date_consistency,
    check_nepali_id_format,
    evaluate_multilingual_consistency,
)


class TestScriptDetector(unittest.TestCase):
    """Test Unicode script analysis and language classification."""

    def test_detect_english(self):
        res = detect_script_and_language("PASSPORT REPUBLIC OF INDIA P1234567")
        self.assertEqual(res.detected_script, "Latin")
        self.assertEqual(res.language_code, "eng")
        self.assertTrue(res.is_english)

    def test_detect_nepali_devanagari(self):
        res = detect_script_and_language("नेपाल नागरिकता प्रमाणपत्र जन्म मिति २०५२/०४/२५")
        self.assertEqual(res.detected_script, "Devanagari")
        self.assertEqual(res.language_code, "nep")
        self.assertEqual(res.language_name, "Nepali")
        self.assertFalse(res.is_english)
        self.assertEqual(res.tesseract_lang, "eng+nep")

    def test_detect_hindi_devanagari(self):
        res = detect_script_and_language("भारत सरकार पहचान पत्र आधार जन्म तिथि निवासी")
        self.assertEqual(res.detected_script, "Devanagari")
        self.assertEqual(res.language_code, "hin")
        self.assertEqual(res.language_name, "Hindi")

    def test_detect_bengali(self):
        res = detect_script_and_language("গণপ্রজাতন্ত্রী বাংলাদেশ জাতীয় পরিচয়পত্র")
        self.assertEqual(res.detected_script, "Bengali")
        self.assertEqual(res.language_code, "ben")

    def test_detect_urdu(self):
        res = detect_script_and_language("حکومت پاکستان قومی شناختی کارڈ")
        self.assertEqual(res.detected_script, "Perso-Arabic")
        self.assertEqual(res.language_code, "urd")

    def test_hint_country_override(self):
        res = detect_script_and_language("ANY TEXT", expected_country="NPL")
        self.assertEqual(res.language_code, "nep")
        self.assertEqual(res.tesseract_lang, "eng+nep")


class TestNepaliCalendarEngine(unittest.TestCase):
    """Test Bikram Sambat date and year conversions to Gregorian."""

    def test_devanagari_digits_conversion(self):
        self.assertEqual(to_ascii_digits("०१२३४५६७८९"), "0123456789")
        self.assertEqual(to_ascii_digits("२०८०-०४-२५"), "2080-04-25")

    def test_known_numeric_bs_date(self):
        res = convert_bikram_sambat("2082-04-25")
        self.assertTrue(res.is_valid)
        self.assertEqual(res.gregorian_date, "2025-08-10")
        self.assertEqual(res.bs_year, 2082)
        self.assertEqual(res.bs_month, 4)
        self.assertEqual(res.bs_day, 25)
        self.assertEqual(res.bs_month_name, "Shrawan")

    def test_devanagari_numeric_date(self):
        res = convert_bikram_sambat("२०८०/०१/१५")
        self.assertTrue(res.is_valid)
        self.assertEqual(res.gregorian_date, "2023-04-28")
        self.assertEqual(res.bs_month_name, "Baishakh")

    def test_text_nepali_month_latin(self):
        res = convert_bikram_sambat("15 Baishakh 2080")
        self.assertTrue(res.is_valid)
        self.assertEqual(res.gregorian_date, "2023-04-28")
        self.assertEqual(res.bs_month, 1)

    def test_text_nepali_month_devanagari(self):
        res = convert_bikram_sambat("१५ बैशाख २०८०")
        self.assertTrue(res.is_valid)
        self.assertEqual(res.gregorian_date, "2023-04-28")

    def test_bs_year_conversion(self):
        start_year, span = convert_bs_year_to_gregorian(2080)
        self.assertEqual(start_year, 2023)
        self.assertEqual(span, "2023-2024")

        res = convert_bikram_sambat("2080 BS")
        self.assertTrue(res.is_valid)
        self.assertEqual(res.bs_year, 2080)
        self.assertEqual(res.gregorian_primary_year, 2023)
        self.assertEqual(res.gregorian_year_span, "2023-2024")

    def test_bs_year_devanagari(self):
        res = convert_bikram_sambat("वि.सं. २०८२")
        self.assertTrue(res.is_valid)
        self.assertEqual(res.bs_year, 2082)
        self.assertEqual(res.gregorian_primary_year, 2025)
        self.assertEqual(res.gregorian_year_span, "2025-2026")


class TestMultilingualConsistency(unittest.TestCase):
    """Test consistency evaluation for regional formats and dual calendars."""

    def test_dual_calendar_match(self):
        # 2082-04-25 BS == 2025-08-10 AD
        res = check_nepali_date_consistency("2082-04-25", claimed_ad_date="2025-08-10")
        self.assertEqual(res.status, "PASS")
        self.assertFalse(res.is_hard_fail)

    def test_dual_calendar_mismatch(self):
        # 2082-04-25 BS != 1999-01-01 AD
        res = check_nepali_date_consistency("2082-04-25", claimed_ad_date="1999-01-01")
        self.assertEqual(res.status, "FAIL")
        self.assertTrue(res.is_hard_fail)

    def test_nepali_id_format(self):
        res_pass = check_nepali_id_format("27-01-78-01234")
        self.assertEqual(res_pass.status, "PASS")

        res_dl = check_nepali_id_format("01-06-00123456")
        self.assertEqual(res_dl.status, "PASS")

    def test_full_consistency_report(self):
        report = evaluate_multilingual_consistency(
            document_number="27-01-78-01234",
            claimed_name="RAM SHRESTHA",
            claimed_bs_date="2082-04-25",
            claimed_ad_date="2025-08-10",
            issuing_country="NPL",
        )
        self.assertTrue(report.is_consistent)
        self.assertFalse(report.hard_fail)


class TestMultilingualMicroserviceAPI(unittest.TestCase):
    """Test FastAPI endpoints for multilingual screening and calendar conversion."""

    def setUp(self):
        self.client = TestClient(app)

    def test_detect_language_api(self):
        payload = {"text": "नेपाल नागरिकता प्रमाणपत्र"}
        res = self.client.post("/api/v1/multilingual/detect-language", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertEqual(data["language_code"], "nep")
        self.assertEqual(data["detected_script"], "Devanagari")

    def test_convert_calendar_api(self):
        payload = {"date_or_year": "2082-04-25"}
        res = self.client.post("/api/v1/multilingual/convert-calendar", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["is_valid"])
        self.assertEqual(data["gregorian_date"], "2025-08-10")
        self.assertEqual(data["bs_year"], 2082)

    def test_convert_calendar_year_api(self):
        payload = {"date_or_year": "2080 BS"}
        res = self.client.post("/api/v1/multilingual/convert-calendar", json=payload)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data["is_valid"])
        self.assertEqual(data["gregorian_primary_year"], 2023)
        self.assertEqual(data["gregorian_year_span"], "2023-2024")

    def test_multilingual_screen_api(self):
        img = Image.new("RGB", (300, 100), color=(255, 255, 255))
        buf = io.BytesIO()
        img.save(buf, format="PNG")

        res = self.client.post(
            "/api/v1/multilingual/screen",
            files={"file": ("doc.png", buf.getvalue(), "image/png")},
            data={"expected_country": "NPL"},
        )
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn("detected_language", data)
        self.assertIn("validation_checks", data)


if __name__ == "__main__":
    unittest.main()
