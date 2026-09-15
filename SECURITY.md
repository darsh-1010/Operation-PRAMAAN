# Upload security

This app exists to receive images/video from untrusted members of the public and hand them
to parsers (OCR, computer-vision forensics, face matchers) that were historically a common
RCE/DoS source — see [ImageTragick](https://imagetragick.com/) (CVE-2016-3714, RCE via
crafted image delegates) and the classic
[decompression-bomb](https://owasp.org/www-community/vulnerabilities/Unrestricted_File_Upload)
DoS (a 50KB PNG that claims to be 50,000×50,000px and OOMs the process decoding it). Treat
every uploaded byte as hostile input, not just "a photo."

Sources: [OWASP File Upload Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/File_Upload_Cheat_Sheet.html),
[OWASP Unrestricted File Upload](https://owasp.org/www-community/vulnerabilities/Unrestricted_File_Upload).

## What exists today (frontend)

[frontend/src/lib/fileGuard.ts](frontend/src/lib/fileGuard.ts) runs before a file is previewed
or accepted:
- **Magic-byte sniffing** — checks real file signatures (PNG/JPEG/WEBP/MP4), not the
  browser-reported MIME type or extension, which are attacker-controlled and trivially spoofed.
- **Size caps** — 15MB images, 50MB video.
- **Decode + pixel-count check** — `createImageBitmap` must succeed, and width×height is
  capped at ~30MP, to reject decompression-bomb-style images before the browser burns memory
  decoding them.

**This is a UX filter, not a security boundary.** A direct API call skips the browser
entirely. Real enforcement has to happen server-side, independently, once each service exists.

## What each backend service must do (not yet implemented — no service has code yet)

Every one of `ocr-consistency-check`, `visual-image-forensics`, `biometric-matching` receives
attacker-controlled file bytes directly. Each needs, at minimum:

1. **Re-validate independently of the client.** Never trust that the frontend's checks ran.
   Re-check magic bytes and size server-side on every request.
2. **Parse with a format-specific library, then re-encode — don't trust the original bytes.**
   Open with Pillow (`Image.open(...).load()` inside `try/except`) and re-save to a fresh
   buffer before any further processing. Re-encoding is what actually defeats polyglots
   (a JPEG with a PHP payload appended after the image data, or a GIF-header-plus-payload
   polyglot) — the payload doesn't survive a real decode+re-encode round trip. A magic-byte
   check alone does not catch this.
3. **Cap decoded pixels before decoding**, e.g. `PIL.Image.MAX_IMAGE_PIXELS` set explicitly
   (don't rely on Pillow's default ~89MP ceiling — set it to match this app's real needs).
4. **Never shell out to ImageMagick/`convert` with user-controlled input or filenames.**
   If any tool in the pipeline uses ImageMagick, keep it patched and set an
   [ImageTragick-style policy.xml](https://imagetragick.com/) disabling the dangerous
   coders (`MVG`, `MSL`, `EPHEMERAL`, `URL`, `HTTPS`, `FTP`) even years after the original CVE.
5. **Reject SVG entirely.** It's XML, not a raster format, and can carry embedded
   `<script>`/XSS — there's no legitimate reason a passport photo is an SVG.
6. **Generate the stored filename server-side** (e.g. a UUID) — never reuse the
   client-supplied filename or write it into any path.
7. **Store uploads outside the webroot**, non-executable, and never serve them back with a
   content-type sniffed from the file itself (force `Content-Disposition: attachment` +
   explicit content-type if they're ever served back at all).
8. **Run the decode/parse step sandboxed and resource-limited** — each service is already a
   separate Docker container (see each service's `Dockerfile`); add a CPU/memory/time limit
   on the container or the specific worker process so one malicious file can't take the host
   down, and run as a non-root user.
9. **Rate-limit uploads per client** at the reverse proxy / gateway layer, independent of
   `risk-scoring-engine`'s business logic, to blunt DoS attempts distinct from any single
   malicious file.
10. **Antivirus scan before processing**, if feasible (e.g. ClamAV as a sidecar) — belt and
    braces on top of #2, since re-encoding covers image-polyglot payloads but not, say, an
    EICAR test file or a payload smuggled purely to be forwarded/stored rather than parsed.

None of this is implemented yet because none of the 3 detection services have any code yet —
this file exists so whoever builds them does it with the threat model in mind from the start,
not bolted on after.
