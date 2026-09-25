# UIDAI signing certificates (not committed)

`aadhaar_qr.py` verifies the Aadhaar Secure QR signature against every `.cer` / `.crt` / `.pem`
file in this folder (override with `UIDAI_CERT_DIR`). **With none here, no Aadhaar QR can ever
verify — screenings with Aadhaar go to manual review with `UIDAI_CERT_NOT_CONFIGURED`.**

UIDAI publishes these on its developer page ("Data and Downloads" → "UIDAI Certificate
Details", https://uidai.gov.in). It has rotated its offline-verification key several times, so
install **all** current and previous ones; a card signed with a key that is missing here fails
verification exactly like a forgery would (`AADHAAR_QR_SIGNATURE_INVALID` → manual review).

Filenames seen in the wild (2018–2026): `uidai_offline_publickey_26022019.cer`,
`uidai_offline_publickey_29032019.cer`, `uidai_offline_publickey_26022021.cer`,
`uidai_offline_publickey_17022026.cer`, `uidai_offline_publickey_2026.cer`.

1. Download them **in a browser** from uidai.gov.in (the site refuses scripted downloads).
2. Put them in this folder (or mount a folder at `UIDAI_CERT_DIR` in production).
3. Restart the service and check the log: each certificate is printed with its SHA-256
   fingerprint and expiry date. Record those fingerprints in your change log so a swapped
   certificate is noticed.

Never accept a certificate from anywhere but uidai.gov.in: whoever controls this folder decides
what counts as "signed by UIDAI".
