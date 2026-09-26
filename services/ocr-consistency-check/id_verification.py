"""Identity-document-specific checks layered on top of the generic OCR pipeline:
Aadhaar (UIDAI Secure QR signature + Verhoeff + printed-vs-signed cross-check), Indian Voter ID
(EPIC format + e-EPIC QR consistency) and Nepali citizenship certificates.

What each can and cannot prove (see ID_DOCUMENTS.md for sources):
  * Aadhaar — the Secure QR is digitally signed by UIDAI: the ONLY one of these three that can
    be verified cryptographically, offline.
  * Voter ID — the e-EPIC QR is plain, UNSIGNED JSON (ECI has published no spec and refused an
    RTI request for one); older physical cards have no QR at all. Format + consistency only.
  * Nepali citizenship certificate — no central registry (each District Administration Office
    numbers its own), printed in Devanagari, partly handwritten, laminated paper. Nothing can
    verify it automatically; by default it always goes to an officer.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

import aadhaar_qr
from decision_models import ReasonCode, ValidationCheckRecord
from field_patterns import ParsedDocumentData
from matcher import compute_fuzzy_name_score
from nepali_calendar import to_ascii_digits
from normalizer import normalize_date, normalize_gender

NP_CITIZENSHIP_REQUIRE_REVIEW = os.environ.get("NP_CITIZENSHIP_REQUIRE_REVIEW", "true").lower() == "true"

AADHAAR_MARKERS = re.compile(r"AADHAAR|UNIQUE\s*IDENTIFICATION\s*AUTHORITY|UIDAI|आधार|भारतीय\s*विशिष्ट\s*पहचान", re.I)
VOTER_MARKERS = re.compile(r"ELECTION\s*COMMISSION\s*OF\s*INDIA|ELECTOR'?S?\s*PHOTO\s*IDENTITY|निर्वाचन\s*आयोग|मतदाता", re.I)
NP_CITIZENSHIP_MARKERS = re.compile(r"नागरिकता(को)?\s*प्रमाण|CITIZENSHIP\s*CERTIFICATE|नेपाल\s*सरकार|GOVERNMENT\s*OF\s*NEPAL", re.I)
AADHAAR_NUMBER = re.compile(r"(?<!\d)([2-9]\d{3})\s?(\d{4})\s?(\d{4})(?!\d)")
MASKED_AADHAAR = re.compile(r"[Xx*]{4}\s?[Xx*]{4}\s?(\d{4})(?!\d)")
EPIC_NUMBER = re.compile(r"\b([A-Z]{3}[0-9]{7})\b")
NP_CITIZENSHIP_NUMBER = re.compile(r"(?<!\d)(\d{1,3}(?:\s?[-/]\s?\d{1,6}){2,4})(?!\d)")

SLOT_SUBTYPE = {"voterId": "VOTER_ID", "citizenship": "NP_CITIZENSHIP"}

# Verhoeff (dihedral group D5) — the check-digit scheme UIDAI uses for Aadhaar numbers.
_D = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 2, 3, 4, 0, 6, 7, 8, 9, 5], [2, 3, 4, 0, 1, 7, 8, 9, 5, 6],
      [3, 4, 0, 1, 2, 8, 9, 5, 6, 7], [4, 0, 1, 2, 3, 9, 5, 6, 7, 8], [5, 9, 8, 7, 6, 0, 4, 3, 2, 1],
      [6, 5, 9, 8, 7, 1, 0, 4, 3, 2], [7, 6, 5, 9, 8, 2, 1, 0, 4, 3], [8, 7, 6, 5, 9, 3, 2, 1, 0, 4],
      [9, 8, 7, 6, 5, 4, 3, 2, 1, 0]]
_P = [[0, 1, 2, 3, 4, 5, 6, 7, 8, 9], [1, 5, 7, 6, 2, 8, 3, 0, 9, 4], [5, 8, 0, 3, 7, 9, 6, 1, 4, 2],
      [8, 9, 1, 6, 0, 4, 3, 5, 2, 7], [9, 4, 5, 3, 1, 2, 6, 8, 7, 0], [4, 2, 8, 6, 5, 7, 3, 9, 0, 1],
      [2, 7, 9, 3, 8, 0, 6, 4, 1, 5], [7, 0, 4, 6, 9, 1, 3, 2, 5, 8]]


def verhoeff_valid(number: str) -> bool:
    check = 0
    for i, digit in enumerate(reversed(number)):
        check = _D[check][_P[i % 8][int(digit)]]
    return check == 0


@dataclass
class IdCheckResult:
    subtype: Optional[str] = None
    checks: list = field(default_factory=list)
    reasons: list = field(default_factory=list)
    hard_fail: bool = False
    review_required: bool = False

    def add(self, check_type: str, status: str, detail: str, code: Optional[str] = None, severity: str = "INFO",
            hard_fail: bool = False, review: bool = False, expected: str = "", observed: str = "") -> None:
        self.checks.append(ValidationCheckRecord(check_type, "document", status, hard_fail, expected, observed, detail))
        if code:
            self.reasons.append(ReasonCode(code, detail, severity, 1.0 if hard_fail else 0.0))
        self.hard_fail |= hard_fail
        self.review_required |= review


def detect_subtype(slot: str, text: str, qr_payloads: list[str]) -> Optional[str]:
    """What the document IS, from its own content — never from what the officer clicked alone.
    A signed/legacy Aadhaar QR is the strongest signal; then printed issuer markers; then the
    Aadhaar number pattern. The slot is only a fallback for documents with no markers."""
    if any("PrintLetterBarcodeData" in p or (p.isdigit() and len(p) > 500) for p in qr_payloads):
        return "AADHAAR"
    if AADHAAR_MARKERS.search(text):
        return "AADHAAR"
    if VOTER_MARKERS.search(text) or any('"epic"' in p for p in qr_payloads):
        return "VOTER_ID"
    if NP_CITIZENSHIP_MARKERS.search(text):
        return "NP_CITIZENSHIP"
    if AADHAAR_NUMBER.search(text) and slot == "nationalId":
        return "AADHAAR"
    return SLOT_SUBTYPE.get(slot)


def verify_identity_document(slot: str, image: np.ndarray, text: str, parsed: ParsedDocumentData,
                             uidai_keys: list) -> IdCheckResult:
    if slot not in ("nationalId", "voterId", "citizenship"):
        return IdCheckResult()
    payloads = aadhaar_qr.read_qr_payloads(image)
    result = IdCheckResult(subtype=detect_subtype(slot, text, payloads))
    expected = SLOT_SUBTYPE.get(slot)
    if expected and result.subtype and result.subtype != expected:
        result.add("DOCUMENT_TYPE", "WARN", f"Uploaded as {expected} but the document reads as {result.subtype}",
                   "DOCUMENT_TYPE_MISMATCH", "HIGH", review=True, expected=expected, observed=result.subtype)
    if result.subtype == "AADHAAR":
        _verify_aadhaar(result, text, parsed, payloads, uidai_keys)
    elif result.subtype == "VOTER_ID":
        _verify_voter_id(result, text, parsed, payloads)
    elif result.subtype == "NP_CITIZENSHIP":
        _verify_np_citizenship(result, text, parsed)
    return result


# ------------------------------------------------------------------ Aadhaar

def _printed_aadhaar(text: str) -> tuple[Optional[str], Optional[str]]:
    """(full 12-digit number or None, last 4 digits or None) as printed on the card. The 16-digit
    Virtual ID (VID) printed on newer cards is removed first — its first 12 digits would
    otherwise look like an Aadhaar number with a bad check digit."""
    text = re.sub(r"VID\s*:?\s*(?:\d\s?){16}", " ", text, flags=re.I)
    full = AADHAAR_NUMBER.search(text)
    if full:
        number = "".join(full.groups())
        return number, number[-4:]
    masked = MASKED_AADHAAR.search(text)
    return None, masked.group(1) if masked else None


def _verify_aadhaar(result: IdCheckResult, text: str, parsed: ParsedDocumentData, payloads: list, keys: list) -> None:
    number, last4 = _printed_aadhaar(text)
    if number:
        if verhoeff_valid(number):
            result.add("AADHAAR_CHECKSUM", "PASS", "Printed Aadhaar number passes the Verhoeff check digit")
        else:
            result.add("AADHAAR_CHECKSUM", "FAIL", "Printed Aadhaar number fails the Verhoeff check digit (misread or fake)",
                       "AADHAAR_NUMBER_CHECKSUM_INVALID", "HIGH", review=True)
            last4 = None  # an unreliable read can't be used to accuse the QR below
    mask_aadhaar_number(parsed, number)

    qr = None
    for payload in payloads:
        try:
            qr = aadhaar_qr.parse_payload(payload, keys)
        except ValueError as err:
            result.add("AADHAAR_QR", "FAIL", f"Aadhaar QR present but undecodable: {err}", "AADHAAR_QR_UNDECODABLE", "HIGH", review=True)
            return
        if qr:
            break
    if qr is None:
        result.add("AADHAAR_QR", "WARN", "No Aadhaar QR could be read from the image — rescan the QR with the official Aadhaar app",
                   "AADHAAR_QR_NOT_READ", "MEDIUM", review=True)
        return
    if qr.kind == "LEGACY":
        result.add("AADHAAR_QR", "WARN", "Old-style Aadhaar QR: unsigned plain text, anyone can generate it — proves nothing",
                   "AADHAAR_QR_LEGACY_UNSIGNED", "HIGH", review=True)
        return
    if qr.signature_valid is None:
        result.add("AADHAAR_QR_SIGNATURE", "SKIPPED", "Secure QR found but no UIDAI certificate is installed to verify it",
                   "UIDAI_CERT_NOT_CONFIGURED", "HIGH", review=True)
    elif not qr.signature_valid:
        # Not an automatic REJECT: a genuine card signed with a UIDAI key we haven't installed yet
        # (UIDAI rotates keys) fails identically. An officer must check it with the Aadhaar app.
        result.add("AADHAAR_QR_SIGNATURE", "FAIL", "Secure QR signature does NOT verify against any installed UIDAI key: "
                   "forged/altered QR, or signed with a newer UIDAI key not yet installed", "AADHAAR_QR_SIGNATURE_INVALID",
                   "CRITICAL", review=True)
        return
    else:
        result.add("AADHAAR_QR_SIGNATURE", "PASS", f"Secure QR digitally signed by UIDAI (key {qr.signing_key[:12]}…)",
                   "AADHAAR_QR_SIGNATURE_VALID")
    _cross_check_aadhaar(result, qr, parsed, last4)


def _cross_check_aadhaar(result: IdCheckResult, qr: aadhaar_qr.AadhaarQR, parsed: ParsedDocumentData,
                         printed_last4: Optional[str]) -> None:
    """A genuine signed QR only helps if it belongs to THIS card: a forger can paste someone
    else's real QR onto a fake card. Compare what UIDAI signed with what is printed."""
    signed_by_uidai = qr.signature_valid is True
    if printed_last4 and qr.last4 and printed_last4 != qr.last4:
        result.add("AADHAAR_QR_CROSSCHECK", "FAIL", f"Printed Aadhaar ends {printed_last4} but the QR belongs to …{qr.last4}",
                   "AADHAAR_QR_BELONGS_TO_ANOTHER_PERSON", "CRITICAL", hard_fail=signed_by_uidai, review=True,
                   expected=qr.last4, observed=printed_last4)
        return
    qr_dob, qr_name = normalize_date(qr.fields.get("dob")), qr.fields.get("name")
    name_score = compute_fuzzy_name_score(parsed.claimed_name, qr_name) if parsed.claimed_name and qr_name else None
    dob_differs = bool(qr_dob and parsed.claimed_dob and qr_dob != parsed.claimed_dob)
    gender_differs = bool(parsed.claimed_gender and normalize_gender(qr.fields.get("gender")) not in (None, parsed.claimed_gender))
    if dob_differs and name_score is not None and name_score < 0.6:
        result.add("AADHAAR_QR_CROSSCHECK", "FAIL", "Printed name AND date of birth both differ from the UIDAI-signed QR",
                   "AADHAAR_QR_BELONGS_TO_ANOTHER_PERSON", "CRITICAL", hard_fail=signed_by_uidai, review=True)
    elif dob_differs or gender_differs or (name_score is not None and name_score < 0.85):
        result.add("AADHAAR_QR_CROSSCHECK", "WARN", "Printed details differ from the UIDAI-signed QR (possible OCR misread or alteration)",
                   "AADHAAR_QR_PRINTED_MISMATCH", "HIGH", review=True)
    else:
        result.add("AADHAAR_QR_CROSSCHECK", "PASS", "Printed name/DOB/gender/last-4 match the UIDAI-signed QR")


def mask_aadhaar_number(parsed: ParsedDocumentData, number: Optional[str]) -> None:
    """Aadhaar rules forbid keeping full Aadhaar numbers outside an Aadhaar Data Vault — keep
    only the last 4 digits in anything persisted or returned (the watchlist lookup has already
    run on the in-memory value)."""
    digits = number or re.sub(r"\D", "", parsed.document_number or "")
    if len(digits) != 12:
        return
    masked = "XXXXXXXX" + digits[-4:]
    parsed.document_number = masked
    for f in parsed.fields:
        if f.field_key == "DOCUMENT_NUMBER":
            f.field_value = masked


# ------------------------------------------------------------------ Voter ID (EPIC)

def _verify_voter_id(result: IdCheckResult, text: str, parsed: ParsedDocumentData, payloads: list) -> None:
    printed = EPIC_NUMBER.search(text.upper())
    if printed:
        parsed.document_number = printed.group(1)
        result.add("EPIC_FORMAT", "PASS", f"EPIC number {printed.group(1)} has the standard 3-letter + 7-digit format")
    else:
        result.add("EPIC_FORMAT", "WARN", "No standard-format EPIC number (ABC1234567) read — old-format card or misread",
                   "EPIC_NUMBER_NOT_FOUND", "MEDIUM", review=True)
    for payload in payloads:
        try:
            qr = json.loads(payload)
        except ValueError:
            continue
        qr_epic = str(qr.get("epic", "")).upper() if isinstance(qr, dict) else ""
        if not qr_epic:
            continue
        if printed and qr_epic != printed.group(1):
            result.add("EPIC_QR_CROSSCHECK", "FAIL", f"Printed EPIC {printed.group(1)} differs from the e-EPIC QR's {qr_epic}",
                       "EPIC_QR_MISMATCH", "CRITICAL", review=True, expected=qr_epic, observed=printed.group(1))
        else:
            result.add("EPIC_QR_CROSSCHECK", "PASS", "e-EPIC QR matches the printed EPIC (QR is unsigned: consistency, not proof)")
        break
    result.add("VOTER_ID_AUTHENTICITY", "SKIPPED", "Voter ID cannot be verified cryptographically — ECI publishes no signed QR; "
               "rely on face match + watchlist", "VOTER_ID_NOT_CRYPTOGRAPHICALLY_VERIFIABLE")


# ------------------------------------------------------------------ Nepali citizenship certificate

def _verify_np_citizenship(result: IdCheckResult, text: str, parsed: ParsedDocumentData) -> None:
    latin = to_ascii_digits(text)
    number = NP_CITIZENSHIP_NUMBER.search(latin)
    if number:
        parsed.document_number = re.sub(r"\s", "", number.group(1))
        result.add("NP_CITIZENSHIP_NUMBER", "PASS", f"Citizenship number {parsed.document_number} read")
    else:
        result.add("NP_CITIZENSHIP_NUMBER", "WARN", "No citizenship number read (often handwritten)",
                   "NP_CITIZENSHIP_NUMBER_NOT_FOUND", "MEDIUM", review=True)
    result.add("NP_CITIZENSHIP_AUTHENTICITY", "SKIPPED", "Nepal has no central citizenship registry — authenticity can only be "
               "confirmed by the issuing District Administration Office", "NP_CITIZENSHIP_NO_CENTRAL_REGISTRY", "HIGH",
               review=NP_CITIZENSHIP_REQUIRE_REVIEW)
