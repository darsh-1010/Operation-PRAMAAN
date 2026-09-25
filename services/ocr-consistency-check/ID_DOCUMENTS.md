# Identity documents: Aadhaar, Voter ID, Nepali citizenship

Code: [`id_verification.py`](id_verification.py), [`aadhaar_qr.py`](aadhaar_qr.py),
tests: [`test_id_verification.py`](test_id_verification.py).

## What each document can prove

| Document | Can a machine prove it's genuine? | What we check |
|---|---|---|
| **Aadhaar** (letter, e-Aadhaar, PVC) | **Yes**: the Secure QR is digitally signed by UIDAI | Signature (RSA-2048/SHA-256 against UIDAI's certificates), signed fields vs printed fields, Verhoeff check digit on the printed number |
| **Aadhaar, old card** | No: the old QR is plain unsigned XML | Flagged `AADHAAR_QR_LEGACY_UNSIGNED` and sent to review |
| **Voter ID (EPIC)** | **No**: the e-EPIC QR is unsigned JSON; old cards have no QR | EPIC format (3 letters + 7 digits), QR-vs-printed consistency, face match, watchlist |
| **Nepali citizenship certificate** | **No**: no central registry, each District Administration Office numbers its own | Devanagari OCR (Tesseract `eng+nep`), number read, and **always sent to an officer** (`NP_CITIZENSHIP_REQUIRE_REVIEW`) |

At the Indo-Nepal border, Indians travel on a **passport or Voter ID**. Aadhaar is *not*
accepted for travel to Nepal (Indian Embassy Kathmandu). Nepali citizens use the citizenship
certificate or Nepal's new national ID card.

## How the document type is identified

The type comes from the document's own content, not just the button the officer clicked:

1. **A QR in the image** (read with zxing-cpp). A long all-digits QR is an Aadhaar Secure QR,
   `<PrintLetterBarcodeData …>` is an old Aadhaar QR, and JSON with `"epic"` is an e-EPIC.
2. **Issuer text** (OCR): "Unique Identification Authority" / "आधार" for Aadhaar, "Election
   Commission of India" / "निर्वाचन आयोग" for Voter ID, "नागरिकताको प्रमाणपत्र" / "नेपाल सरकार"
   for Nepali citizenship.
3. **Number pattern**: a 12-digit `XXXX XXXX XXXX` number in the National-ID slot means Aadhaar.
   The 16-digit VID printed on newer cards is excluded first.
4. **The slot** the officer chose, only as a last resort. If the content disagrees with the
   slot, you get `DOCUMENT_TYPE_MISMATCH` and the case goes to review.

## Aadhaar Secure QR, step by step

```
QR text (≈1,500–3,500 decimal digits)
 → big integer → big-endian bytes → gzip-decompress
 → [optional "V2"/"V<n>" format field] 0xFF name 0xFF dob 0xFF gender 0xFF … (16 text fields)
   JPEG2000 photo, 0–2 × 32-byte SHA-256 of mobile/email, 256-byte RSA signature
 → verify signature over every byte before it with each installed UIDAI certificate
```

| Result | Code | Decision effect |
|---|---|---|
| Signature valid, printed name/DOB/gender/last-4 match | `AADHAAR_QR_SIGNATURE_VALID` | none (strong positive) |
| Signature valid, but **printed last-4 differs**, or name *and* DOB differ | `AADHAAR_QR_BELONGS_TO_ANOTHER_PERSON` | **REJECT** (a genuine QR on someone else's card) |
| Signature valid, smaller field differences | `AADHAAR_QR_PRINTED_MISMATCH` | review |
| Signature invalid under every installed key | `AADHAAR_QR_SIGNATURE_INVALID` | review, **not** auto-reject: a genuine card signed with a newer UIDAI key we haven't installed fails the same way |
| No UIDAI certificate installed | `UIDAI_CERT_NOT_CONFIGURED` | review |
| QR unreadable | `AADHAAR_QR_NOT_READ` | review (officer rescans with the official Aadhaar app) |
| Old unsigned QR | `AADHAAR_QR_LEGACY_UNSIGNED` | review |
| Printed number fails Verhoeff | `AADHAAR_NUMBER_CHECKSUM_INVALID` | review |

Only the **last 4 digits** of an Aadhaar number are ever stored or returned (`XXXXXXXX1234`).
Aadhaar regulations require full numbers to sit in an Aadhaar Data Vault; we don't keep one.

**Operational requirements:**
- **UIDAI certificates must be installed.** See [`certs/uidai/README.md`](certs/uidai/README.md).
  They are not in git: uidai.gov.in refuses scripted downloads, so the fingerprints couldn't be
  independently checked while building this.
- **The QR must be photographed close up.** Measured on synthetic Secure QRs, zxing-cpp read
  60/60 at ~2.4 pixels per QR module and 0/60 below ~1.8. A Secure QR is roughly 150 modules
  wide, so it needs about 400 or more pixels across in the photo. OpenCV's own detector missed
  about 15% of *clean* images, which is why it isn't used.

## Sources

- UIDAI Secure QR specification and certificate details: uidai.gov.in (Developer section, "Data and Downloads")
- Byte layout cross-checked against open implementations: rajdeol/android-aadhaar-card-scanner
  (`SecureQrCode.java`), Vedjamkar/SIHADT (`aadhaar_qr.py`)
- Verhoeff: UIDAI's documented test Aadhaar number `999941057058` validates (see tests)
- e-EPIC QR is unsigned JSON with no public spec; ECI refused an RTI request for one (FOSS United
  forum, "Public Specifications for e-EPIC QR"; open decoder: captn3m0/epicqr)
- Nepal citizenship certificates: no national database; each DAO numbers its own (IRB Canada
  NPL103944.E via ecoi.net)
- Valid travel documents for Indians to Nepal: Embassy of India, Kathmandu
