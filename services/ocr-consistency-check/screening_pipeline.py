"""Core single-document screening execution pipeline."""

from __future__ import annotations
from typing import Optional

from candidate_search import CandidateSearchEngine
from decision_matrix import evaluate_decision_matrix
from field_extractor import extract_document_fields
from ingestion import ingest_file
from matcher import match_against_candidate
from ocr_engine import OCREngine
from script_detector import COUNTRY_TO_LANG


def resolve_ocr_lang(expected_country: Optional[str], expected_language: Optional[str]) -> Optional[str]:
    """Map a country or language hint to a regional Tesseract language pack."""
    if expected_country and expected_country.upper() in COUNTRY_TO_LANG:
        return COUNTRY_TO_LANG[expected_country.upper()][2]
    if expected_language:
        return f"eng+{expected_language}" if expected_language != "eng" else "eng"
    return None


def run_screening_pipeline(
    content: bytes, filename: str, expected_country: Optional[str] = None, expected_language: Optional[str] = None,
):
    """Execute ingestion, OCR, field parsing, watchlist search, and decision matrix."""
    ingested = ingest_file(content, filename or "")
    ocr_engine = OCREngine.get_instance()
    ocr_lang = resolve_ocr_lang(expected_country, expected_language)
    ocr_res = ocr_engine.extract_text(ingested.images[0], lang=ocr_lang)
    parsed = extract_document_fields(ocr_res, expected_country=expected_country, expected_language=expected_language)

    search_engine = CandidateSearchEngine()
    watchlist_hits = search_engine.screen_watchlist(
        document_number=parsed.document_number, full_name=parsed.claimed_name, dob=parsed.claimed_dob
    )
    selected_candidate = None
    match_outcome = match_against_candidate(parsed, selected_candidate)
    decision = evaluate_decision_matrix(parsed, match_outcome, watchlist_hits)
    return ingested, ocr_res, parsed, match_outcome, decision, watchlist_hits, selected_candidate
