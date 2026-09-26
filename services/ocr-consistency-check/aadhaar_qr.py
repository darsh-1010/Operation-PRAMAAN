"""Aadhaar QR: find it in the card image, decode it, and verify UIDAI's digital signature.

Two generations exist and only one can be trusted:
  * Legacy QR (older cards): plain XML <PrintLetterBarcodeData uid=… name=…/>, NOT signed.
    Anyone can type that XML and print a QR of it, so it proves nothing.
  * Secure QR (current letters, e-Aadhaar, PVC cards): a long decimal number →
    big-endian bytes → gzip → 0xFF-separated text fields (optionally led by a "V<n>" format
    field), a JPEG2000 photo, optional 32-byte mobile/email hashes, and a final 256-byte
    RSA-2048 signature (PKCS#1 v1.5, SHA-256) over every byte before it, made with UIDAI's key.

A valid signature proves exactly one thing: these field values were issued by UIDAI and not
altered by a single bit. It does NOT prove the card in front of you carries this QR honestly
(a genuine QR can be pasted onto a fake card) — id_verification.py cross-checks the signed
fields against the printed text for that — nor that the holder is the subject (the face match).

Certificates: UIDAI publishes its signing certificates on uidai.gov.in and has rotated them
several times. Download them in a browser into UIDAI_CERT_DIR (see certs/uidai/README.md).
Without them every Secure QR comes back as signature_valid=None ("cannot verify"), never as valid.
"""
from __future__ import annotations

import gzip
import hashlib
import logging
import os
import xml.etree.ElementTree as ElementTree
import zlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np
import zxingcpp
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.x509 import load_der_x509_certificate, load_pem_x509_certificate

logger = logging.getLogger("aadhaar_qr")

SIGNATURE_LENGTH = 256
DELIMITER = 0xFF
MAX_PAYLOAD_DIGITS = 20_000  # real Secure QRs are a few thousand digits; cap before big-int maths
FIELD_ORDER = (
    "email_mobile_flag", "reference_id", "name", "dob", "gender", "care_of", "district", "landmark",
    "house", "location", "pincode", "post_office", "state", "street", "sub_district", "vtc",
)
CERT_DIR = Path(os.environ.get("UIDAI_CERT_DIR", Path(__file__).parent / "certs" / "uidai"))


@dataclass
class AadhaarQR:
    kind: str                         # "SECURE" | "LEGACY"
    signature_valid: Optional[bool]   # None = unsigned (legacy) or no UIDAI certificate loaded
    fields: dict = field(default_factory=dict)
    signing_key: Optional[str] = None  # sha256 fingerprint of the certificate that verified it

    @property
    def last4(self) -> Optional[str]:
        ref = self.fields.get("reference_id") or ""
        return ref[:4] if len(ref) >= 4 and ref[:4].isdigit() else None


# ------------------------------------------------------------------ certificates

def load_uidai_keys(cert_dir: Path = CERT_DIR) -> list[tuple[str, rsa.RSAPublicKey]]:
    """Every .cer/.pem in cert_dir as (sha256 fingerprint of the file, public key). Each loaded
    fingerprint is logged so operators can check it against uidai.gov.in."""
    keys = []
    for path in sorted(cert_dir.glob("*")) if cert_dir.is_dir() else []:
        if path.suffix.lower() not in (".cer", ".crt", ".pem"):
            continue
        raw = path.read_bytes()
        try:
            cert = load_pem_x509_certificate(raw) if b"-----BEGIN" in raw else load_der_x509_certificate(raw)
        except ValueError as err:
            logger.error("Unreadable UIDAI certificate %s: %s", path.name, err)
            continue
        key = cert.public_key()
        if not isinstance(key, rsa.RSAPublicKey):
            logger.error("UIDAI certificate %s is not RSA — skipped", path.name)
            continue
        fingerprint = hashlib.sha256(raw).hexdigest()
        logger.info("Loaded UIDAI certificate %s sha256=%s (expires %s)", path.name, fingerprint, cert.not_valid_after_utc.date())
        keys.append((fingerprint, key))
    if not keys:
        logger.warning("No UIDAI certificates in %s — Aadhaar Secure QR signatures cannot be verified.", cert_dir)
    return keys


# ------------------------------------------------------------------ image -> payload

def read_qr_payloads(image: np.ndarray) -> list[str]:
    """QR payloads found in an RGB card image, via zxing-cpp. Measured on synthetic Secure QRs:
    OpenCV's QRCodeDetector missed ~15% of perfectly clean images and every degraded one, where
    zxing-cpp read 60/60 at ~2.4 px per QR module. Below ~2 px/module nothing decodes it — the
    officer must photograph the QR close up (a Secure QR is ~150+ modules wide, so it needs
    ~400+ px across in the photo). Also tried 2x upscaled, for small crops."""
    found: list[str] = []
    for variant in (image, cv2.resize(image, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)):
        if max(variant.shape[:2]) > 6000:
            break
        found += [r.text for r in zxingcpp.read_barcodes(variant, formats=zxingcpp.BarcodeFormat.QRCode)
                  if r.text and r.text not in found]
        if found:
            break
    return found


# ------------------------------------------------------------------ payload -> fields

def _decimal_to_bytes(digits: str) -> bytes:
    """Big decimal string → big-endian bytes without lifting Python's 4300-digit int() guard
    process-wide: fold it in 1000-digit chunks instead."""
    number = 0
    for i in range(0, len(digits), 1000):
        chunk = digits[i:i + 1000]
        number = number * 10 ** len(chunk) + int(chunk)
    return number.to_bytes((number.bit_length() + 7) // 8, "big")


def _decompress(raw: bytes) -> bytes:
    if raw[:2] == b"\x1f\x8b":
        return gzip.decompress(raw)
    for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
        try:
            return zlib.decompress(raw, wbits)
        except zlib.error:
            continue
    raise ValueError("Secure QR payload is not gzip/zlib compressed")


def _take_fields(data: bytes, count: int, start: int = 0) -> tuple[list[str], int]:
    """First `count` 0xFF-delimited fields. Never split the whole buffer on 0xFF: the embedded
    JPEG2000 photo is binary and full of 0xFF bytes."""
    out = []
    for _ in range(count):
        end = data.find(bytes([DELIMITER]), start)
        if end == -1:
            raise ValueError(f"Secure QR has fewer than {count} text fields")
        out.append(data[start:end].decode("iso-8859-1").strip())
        start = end + 1
    return out, start


def _parse_legacy(payload: str) -> AadhaarQR:
    try:
        node = ElementTree.fromstring(payload.split("?>", 1)[-1] if payload.startswith("<?xml") else payload)
    except ElementTree.ParseError as err:
        raise ValueError(f"malformed legacy Aadhaar XML: {err}") from err
    a = {k.lower(): v for k, v in node.attrib.items()}
    return AadhaarQR("LEGACY", None, {
        "reference_id": (a.get("uid") or "")[-4:], "name": a.get("name", ""),
        "dob": a.get("dob") or a.get("yob", ""), "gender": a.get("gender", ""), "pincode": a.get("pc", ""),
    })


def _parse_secure(payload: str, keys: list[tuple[str, rsa.RSAPublicKey]]) -> AadhaarQR:
    if len(payload) > MAX_PAYLOAD_DIGITS:
        raise ValueError("Secure QR payload implausibly long")
    data = _decompress(_decimal_to_bytes(payload))
    if len(data) <= SIGNATURE_LENGTH:
        raise ValueError("Secure QR payload too short to carry a signature")
    signed, signature = data[:-SIGNATURE_LENGTH], data[-SIGNATURE_LENGTH:]

    verdict, signer = (None, None) if not keys else (False, None)
    for fingerprint, key in keys:
        try:
            key.verify(signature, signed, padding.PKCS1v15(), hashes.SHA256())
            verdict, signer = True, fingerprint
            break
        except InvalidSignature:
            continue

    first, cursor = _take_fields(signed, 1)
    fmt = first[0] if first[0][:1].upper() == "V" and first[0][1:].isdigit() else None
    values, _ = _take_fields(signed, len(FIELD_ORDER), cursor if fmt else 0)
    fields = dict(zip(FIELD_ORDER, values))
    if fmt:
        fields["format"] = fmt
    return AadhaarQR("SECURE", verdict, fields, signer)


def parse_payload(payload: str, keys: list[tuple[str, rsa.RSAPublicKey]]) -> Optional[AadhaarQR]:
    """None if this QR isn't an Aadhaar QR at all (e.g. some other barcode on the card)."""
    payload = payload.strip()
    if "PrintLetterBarcodeData" in payload:
        return _parse_legacy(payload)
    if payload.isdigit() and len(payload) > 500:
        return _parse_secure(payload, keys)
    return None
