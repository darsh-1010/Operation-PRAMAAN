"""Tests for Bikram Sambat (Nepali calendar) date conversion."""
import os
import sys
import unittest

SERVICE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if SERVICE_DIR not in sys.path:
    sys.path.insert(0, SERVICE_DIR)

from normalizer import normalize_bikram_sambat_date


class TestBikramSambatConversion(unittest.TestCase):
    def test_known_bs_to_ad_date(self):
        # 2082-04-25 B.S. is a known reference date == 2025-08-10 A.D.
        self.assertEqual(normalize_bikram_sambat_date("2082-04-25"), "2025-08-10")

    def test_dmy_format(self):
        self.assertEqual(normalize_bikram_sambat_date("25/04/2082"), "2025-08-10")

    def test_none_input(self):
        self.assertIsNone(normalize_bikram_sambat_date(None))

    def test_garbage_input(self):
        self.assertIsNone(normalize_bikram_sambat_date("not a date"))


if __name__ == "__main__":
    unittest.main()
