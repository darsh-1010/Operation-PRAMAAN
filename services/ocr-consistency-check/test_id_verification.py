"""Self-check for Aadhaar Secure QR verification, Voter ID and Nepali citizenship checks, and the
encrypted evidence store. The Aadhaar tests build a real Secure-QR-format payload (fields →
0xFF-delimited bytes → RSA-SHA256 signature → gzip → decimal), render it as an actual QR image
and run it through the full image → decode → verify path, signed with a throwaway key standing
in for UIDAI's (real UIDAI keys can't sign test data, obviously).
Run: python test_id_verification.py, or via pytest.
"""
import base64
import datetime
import gzip
import json
import os
import tempfile
import uuid as _uuid
from pathlib import Path

import cv2
import numpy as np
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509.oid import NameOID

import aadhaar_qr
import evidence
from field_patterns import ParsedDocumentData
from id_verification import verhoeff_valid, verify_identity_document

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
PERSON = {"email_mobile_flag": "3", "reference_id": "705820190101120000000", "name": "Ravi Kumar Sharma",
          "dob": "15-08-1990", "gender": "M", "care_of": "S/O Mohan", "district": "Darjeeling", "landmark": "",
          "house": "12", "location": "Siliguri", "pincode": "734001", "post_office": "Siliguri", "state": "West Bengal",
          "street": "Hill Cart Road", "sub_district": "Siliguri", "vtc": "Siliguri"}
AADHAAR_TEXT = "GOVERNMENT OF INDIA\nRavi Kumar Sharma\nDOB: 15/08/1990\nMALE\n9999 4105 7058\nVID : 9134 5678 9012 3456"


def _keys_dir(*keys) -> Path:
    folder = Path(tempfile.mkdtemp())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test-uidai")])
    now = datetime.datetime.now(datetime.timezone.utc)
    for i, key in enumerate(keys):
        cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                .serial_number(x509.random_serial_number()).not_valid_before(now)
                .not_valid_after(now + datetime.timedelta(days=30)).sign(key, hashes.SHA256()))
        (folder / f"uidai_{i}.cer").write_bytes(cert.public_bytes(serialization.Encoding.DER))
    return folder


def _secure_payload(fields: dict, sign_with=KEY, tamper_after_signing: bool = False) -> str:
    text = b"\xff".join([b"V2"] + [fields[k].encode("iso-8859-1") for k in aadhaar_qr.FIELD_ORDER]) + b"\xff"
    photo = bytes([0xFF, 0x4F, 0xFF, 0x51]) + os.urandom(120)  # JPEG2000-like bytes, full of 0xFF
    signed = text + photo + os.urandom(64)  # + mobile & email hashes (flag 3)
    signature = sign_with.sign(signed, padding.PKCS1v15(), hashes.SHA256())
    if tamper_after_signing:
        signed = signed.replace(b"Ravi", b"Ravj")
    return str(int.from_bytes(gzip.compress(signed + signature), "big"))


def _qr_image(payload: str) -> np.ndarray:
    matrix = cv2.QRCodeEncoder.create().encode(payload)
    big = cv2.resize(matrix, None, fx=6, fy=6, interpolation=cv2.INTER_NEAREST)
    big = cv2.copyMakeBorder(big, 40, 40, 40, 40, cv2.BORDER_CONSTANT, value=255)
    return cv2.cvtColor(big, cv2.COLOR_GRAY2RGB)


def _parsed(name="RAVI KUMAR SHARMA", dob="1990-08-15", gender="M", number="999941057058") -> ParsedDocumentData:
    from field_patterns import ExtractedField
    return ParsedDocumentData(doc_type="NATIONAL_ID", document_number=number, claimed_name=name, claimed_dob=dob,
                              claimed_gender=gender, fields=[ExtractedField("DOCUMENT_NUMBER", number, "VIZ", 0.9)])


def _codes(result) -> set:
    return {r.code for r in result.reasons}


def _aadhaar(payload: str, keys_dir: Path, text=AADHAAR_TEXT, parsed=None, slot="nationalId"):
    parsed = parsed or _parsed()
    return verify_identity_document(slot, _qr_image(payload), text, parsed, aadhaar_qr.load_uidai_keys(keys_dir)), parsed


def test_verhoeff_matches_published_examples() -> None:
    assert verhoeff_valid("999941057058")  # UIDAI's documented test Aadhaar number
    assert verhoeff_valid("2363") and not verhoeff_valid("2364")  # Wikipedia worked example
    assert not verhoeff_valid("999941057059")


def test_genuine_signed_aadhaar_passes_and_number_is_masked() -> None:
    result, parsed = _aadhaar(_secure_payload(PERSON), _keys_dir(OTHER_KEY, KEY))  # key rotation: any installed key
    assert result.subtype == "AADHAAR"
    assert "AADHAAR_QR_SIGNATURE_VALID" in _codes(result), result.checks
    assert not result.hard_fail and not result.review_required, [c.detail for c in result.checks]
    assert parsed.document_number == "XXXXXXXX7058" and parsed.fields[0].field_value == "XXXXXXXX7058"


def test_edited_qr_fails_signature() -> None:
    result, _ = _aadhaar(_secure_payload(PERSON, tamper_after_signing=True), _keys_dir(KEY))
    assert "AADHAAR_QR_SIGNATURE_INVALID" in _codes(result) and result.review_required


def test_qr_signed_by_unknown_key_fails_signature() -> None:
    result, _ = _aadhaar(_secure_payload(PERSON, sign_with=OTHER_KEY), _keys_dir(KEY))
    assert "AADHAAR_QR_SIGNATURE_INVALID" in _codes(result)


def test_genuine_qr_pasted_on_another_persons_card_is_rejected() -> None:
    text = AADHAAR_TEXT.replace("9999 4105 7058", "2345 6789 0124")
    assert verhoeff_valid("234567890124")
    result, _ = _aadhaar(_secure_payload(PERSON), _keys_dir(KEY), text=text, parsed=_parsed(number="234567890124"))
    assert "AADHAAR_QR_BELONGS_TO_ANOTHER_PERSON" in _codes(result) and result.hard_fail


def test_no_certificates_means_cannot_verify_not_pass() -> None:
    result, _ = _aadhaar(_secure_payload(PERSON), Path(tempfile.mkdtemp()))
    assert "UIDAI_CERT_NOT_CONFIGURED" in _codes(result) and result.review_required


def test_legacy_unsigned_qr_proves_nothing() -> None:
    xml = '<?xml version="1.0"?><PrintLetterBarcodeData uid="999941057058" name="Ravi Kumar Sharma" gender="M" yob="1990"/>'
    result, _ = _aadhaar(xml, _keys_dir(KEY))
    assert "AADHAAR_QR_LEGACY_UNSIGNED" in _codes(result) and result.review_required


def test_aadhaar_without_readable_qr_needs_review() -> None:
    blank = np.full((300, 400, 3), 255, np.uint8)
    result = verify_identity_document("nationalId", blank, AADHAAR_TEXT, _parsed(), [])
    assert result.subtype == "AADHAAR" and "AADHAAR_QR_NOT_READ" in _codes(result)
    assert "AADHAAR_NUMBER_CHECKSUM_INVALID" not in _codes(result)  # the 16-digit VID is not misread as Aadhaar


def test_voter_id_epic_and_unsigned_qr() -> None:
    text = "ELECTION COMMISSION OF INDIA\nELECTOR PHOTO IDENTITY CARD\nABC1234567\nName: Sita Devi"
    qr = json.dumps({"ac_no": "1", "part_no": "1", "epic": "ABC1234567"})
    parsed = _parsed(number=None)
    ok = verify_identity_document("voterId", _qr_image(qr), text, parsed, [])
    assert ok.subtype == "VOTER_ID" and parsed.document_number == "ABC1234567"
    assert "VOTER_ID_NOT_CRYPTOGRAPHICALLY_VERIFIABLE" in _codes(ok) and not ok.review_required
    bad = verify_identity_document("voterId", _qr_image(qr.replace("ABC1234567", "XYZ7654321")), text, _parsed(number=None), [])
    assert "EPIC_QR_MISMATCH" in _codes(bad) and bad.review_required


def test_nepali_citizenship_devanagari_number_and_review() -> None:
    text = "नेपाल सरकार\nनागरिकताको प्रमाणपत्र\nना.प्र.नं. २७-०१-७२-१२३४५\nनाम थर: राम बहादुर"
    parsed = _parsed(number=None)
    result = verify_identity_document("citizenship", np.full((300, 400, 3), 255, np.uint8), text, parsed, [])
    assert result.subtype == "NP_CITIZENSHIP" and parsed.document_number == "27-01-72-12345"
    assert "NP_CITIZENSHIP_NO_CENTRAL_REGISTRY" in _codes(result) and result.review_required


def test_uploaded_as_voter_id_but_is_aadhaar() -> None:
    result, _ = _aadhaar(_secure_payload(PERSON), _keys_dir(KEY), slot="voterId")
    assert result.subtype == "AADHAAR" and "DOCUMENT_TYPE_MISMATCH" in _codes(result)


def test_evidence_roundtrip_and_binding() -> None:
    evidence.EVIDENCE_DIR = Path(tempfile.mkdtemp())
    os.environ["EVIDENCE_KEY"] = base64.b64encode(os.urandom(32)).decode()
    session, data = str(_uuid.uuid4()), b"\x89PNG fake passport bytes"
    ref = evidence.store(session, "passport", data)
    digest = ref.split(":")[1]
    assert evidence.load(session, "passport", digest) == data
    stored = next(evidence.EVIDENCE_DIR.rglob("*.bin")).read_bytes()
    assert data not in stored  # encrypted at rest
    try:  # a file can't be passed off as another case's
        evidence.load(str(_uuid.uuid4()), "passport", digest)
        raise AssertionError("loaded evidence under the wrong case")
    except FileNotFoundError:
        pass
    for bad_session in ("../../etc", "not-a-uuid"):
        try:
            evidence.store(bad_session, "passport", data)
            raise AssertionError("accepted a non-UUID path component")
        except evidence.EvidenceError:
            pass


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("OK: all identity-document checks passed")
