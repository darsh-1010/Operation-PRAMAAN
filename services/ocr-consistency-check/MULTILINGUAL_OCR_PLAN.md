# Multilingual Document Support — Implementation Plan

Module 1 (`ocr-consistency-check`) currently OCRs everything with a single English-only
model (`OCR_LANG=en`). This plan covers driving licences and national IDs of India's land
neighbors / frequent land-border nationalities — the population this module (built for
Sashastra Seema Bal, which guards the open India-Nepal and India-Bhutan borders) actually
sees day to day.

## 1. Research findings

| Country | Driving licence | National ID | English coverage today | Real risk to this module |
|---|---|---|---|---|
| **Nepal** | Bilingual (Nepali + English); explicit English name field | Citizenship certificate — name in English + Nepali | Name/label fields usually readable | **DOB is printed in the Bikram Sambat calendar** (~56–57 yrs ahead of AD) — Latin digits, but wrong calendar. Silent wrong-year bug, not an OCR problem. |
| **Bhutan** | English licences exist/in use | CID card — bilingual application forms; actual card content **unconfirmed**, Dzongkha is primary | Unverified | Dzongkha OCR is an unsolved research problem (see §1.2) — no reliable off-the-shelf reading path exists yet |
| **Bangladesh** | Not confirmed | Smart NID — name/DOB/ID number in **English on the front**; address fields Bangla-only on the back | Front-side core fields should already work | Low risk for the fields this module extracts (name/DOB/doc number are front-side) |
| **Myanmar** | Bilingual (Burmese + English) | **NRC is Burmese-only, no English at all** | None | Hard failure today — `en` OCR model cannot read Burmese script at all |
| **Pakistan** | Not confirmed | CNIC — explicitly bilingual English + Urdu, by design for passport compatibility | Should mostly work | Low-medium risk |
| **China** | — | Chinese-script only | None | Lowest priority — no meaningful civilian land-crossing traffic (LAC is closed to civilian crossing) |

**Bottom line:** the two real gaps are (a) Myanmar NRC — completely unreadable today, and
(b) Nepal's calendar mismatch — readable but silently wrong.

### 1.1 OCR engine options evaluated

| Option | Verdict | Why |
|---|---|---|
| PaddleOCR additional language packs | **Rejected (for now)** | Current pinned version (`paddleocr>=2.7.0`) has unconfirmed Burmese support; the newer PaddleOCR-VL that does claim broader coverage is a much larger model (0.9B params) — a big memory/cold-start cost increase for a singleton service, and still doesn't confirm Burmese. |
| Cloud OCR API (Google Cloud Vision, Azure, AWS Textract) | **Rejected (for now)** | Confirmed Burmese support, but: (1) sends photographs of government ID documents to a third-party API — a real data-sensitivity question for a border-security tool that needs sign-off, not a unilateral call; (2) adds a network dependency at a checkpoint kiosk; (3) recurring per-call cost. Worth reconsidering only if Tesseract's Burmese quality proves unusable in practice. |
| **Tesseract regional language packs** | **Recommended** | `pytesseract`/Tesseract is *already* a dependency and *already* wired as the fallback engine in `ocr_engine.py`. Official trained models exist for every script we need: `mya` (Burmese), `nep` (Nepali/Devanagari), `ben` (Bengali), `urd` (Urdu), `dzo` (Dzongkha) — all in the official [tessdata_best](https://github.com/tesseract-ocr/tessdata_best) repo. Zero new Python dependencies, fully offline, free. |

### 1.2 Known limitation: Dzongkha

Dzongkha OCR is an active, unsolved research problem — there's a dedicated from-scratch
`dzongkha-ocr` research project because "existing OCR solutions do not adequately support
[Dzongkha]." Tesseract's `dzo.traineddata` exists but should be assumed **low-accuracy**
until tested against real Bhutanese specimens. Recommendation: route Bhutanese CID/Dzongkha
documents to `NEEDS REVIEW` (human check) rather than trusting automated extraction — don't
build false confidence around it.

## 2. Architecture design

### 2.1 Language selection: hint, not auto-detection

A border checkpoint is a manned kiosk, not anonymous public upload — the officer already
knows (or the traveller states) which country's document is being scanned. Building
automatic script/language detection is solving a problem the deployment context doesn't
actually have (YAGNI) and adds real complexity (multi-pass OCR, confidence comparison across
passes, slower per-document time). Instead:

- Add an **optional** `expected_country` field (ISO alpha-3, e.g. `NPL`, `MMR`, `BTN`,
  `BGD`, `PAK`) to `/api/v1/screen` and `/api/v1/extract-only` (`Form(None)` — fully
  backward compatible, existing callers unaffected, defaults to today's English-only path).
- A small lookup table maps country → Tesseract language string:

  ```python
  COUNTRY_OCR_LANG = {
      "NPL": "eng+nep",
      "BTN": "eng+dzo",   # flagged low-confidence, see §1.2
      "BGD": "eng+ben",
      "MMR": "eng+mya",
      "PAK": "eng+urd",
  }
  ```
  `eng+<script>` (not just `<script>`) because these are bilingual documents in practice —
  keeping `eng` in the mix means the parts that *are* in English (which is most of the
  Bangladesh/Pakistan/Nepal cases per §1) still extract via the existing English label
  regexes without any translation work.

### 2.2 `OCREngine` changes

Today `OCREngine` is a singleton with one fixed language baked in at construction
(`OCR_LANG` env var → one `PaddleOCR(lang=...)` instance, one Tesseract lang string).
Needs to support a **per-call** language override without breaking the default path:

- `OCREngine.extract_text(image, lang: str | None = None)` — `lang=None` (default) keeps
  today's exact behavior (whatever `OCR_LANG` is, unchanged).
- When `lang` is given and PaddleOCR is active: PaddleOCR only supports one language per
  loaded model instance, so a non-`en` hint routes straight to `_extract_tesseract(image,
  lang=lang)`, bypassing Paddle for that call — Tesseract is the multilingual path per §1.1,
  Paddle stays the fast English default.
- `_extract_tesseract` already exists; just needs `lang` threaded through to
  `pytesseract.image_to_data(image, lang=lang, ...)` instead of the hardcoded default.

This is additive: no existing call site changes behavior, since every current caller passes
no `lang` arg.

### 2.3 Field-label matching for non-English scripts

`field_extractor.extract_labeled_field()` regexes are English-only (`NAME`, `DATE OF
BIRTH`, `SEX`, ...). Once Tesseract can *read* a script, label matching still needs the
right words. Two tiers:

- **Bilingual documents (Nepal, Bangladesh, Pakistan)**: their English-language field labels
  already exist on the document — no translation dictionary needed, the current regexes
  should already hit the English side once OCR isn't failing outright.
- **Myanmar NRC (no English at all)**: needs an actual label dictionary. Add a small
  per-language label map only when we have real Myanmar specimens to validate against
  (see §4, Phase 3) — building translated regexes against zero real samples is exactly the
  kind of speculative work that bit us with the visa/national-ID dataset earlier this
  session; don't repeat that.

### 2.4 Bikram Sambat wiring

`normalize_bikram_sambat_date()` already exists (`normalizer.py`) and is tested, but
unwired. Once `expected_country == "NPL"`, `field_extractor.py`'s DOB/expiry extraction
should call it instead of `normalize_date()`. Gated strictly behind the explicit hint — no
behavior change for any document that isn't flagged Nepali.

### 2.5 Decision-matrix / response changes

None needed structurally — `doc_type`, `mrz_result`, etc. all already flow through
unchanged; this is purely an input-side (OCR + normalization) change.

## 3. What does *not* need to change

- `mrz_verifier.py` — MRZ is always ICAO 9303 Latin-script by international standard,
  regardless of the document's front-side script. No changes needed for passports.
- `matcher.py`, `decision_matrix.py`, `candidate_search.py`, `db.py` — untouched; they
  operate on already-normalized fields regardless of source script.
- Existing `/screen`, `/extract-only`, `/verify-text` behavior for any caller that doesn't
  pass `expected_country` — byte-identical to today.

## 4. Phased rollout

| Phase | Work | Effort | Depends on |
|---|---|---|---|
| **0 — done** | `normalize_bikram_sambat_date()` utility + tests | done | — |
| **1** | Install Tesseract language packs: `apt-get install tesseract-ocr-nep tesseract-ocr-ben tesseract-ocr-urd tesseract-ocr-script-mymr tesseract-ocr-dzo` in `services/ocr-consistency-check/Dockerfile`. Local dev: same packages via the OS package manager. | ~1 hr (infra only) | — |
| **2** | `OCREngine.extract_text(image, lang=None)` per-call override (§2.2) + unit tests confirming default path is unchanged | ~2–3 hrs | Phase 1 |
| **3** | `expected_country` param on `/screen`/`/extract-only`, `COUNTRY_OCR_LANG` table, wire into `main.py` | ~2 hrs | Phase 2 |
| **4** | Wire Bikram Sambat conversion behind `expected_country == "NPL"` in `field_extractor.py` | ~1 hr | Phase 3 |
| **5** | Validation: generate synthetic Nepali/Bangladeshi/Myanmar/Pakistani specimen images (same approach as this session's `generate_synthetic_docs.py`) with known ground truth, run the batch-test harness per language, measure real extraction accuracy | ~3–4 hrs | Phase 3–4 |
| **6 (optional, only if Phase 5 shows Tesseract's Burmese/Dzongkha accuracy is unusable)** | Revisit Cloud OCR API for just those two scripts — needs an explicit data-handling decision, not a default | — | Phase 5 results |

Total for Phases 1–5: roughly **1–1.5 days** of focused work, no new paid dependencies, no
architecture changes outside `ocr_engine.py`/`field_extractor.py`/`main.py`.

## 5. Open decisions for you to confirm before Phase 1

1. **Bhutan/Dzongkha**: ship it flagged as low-confidence / force `NEEDS REVIEW`, or hold
   off entirely until real specimens can validate it? (Recommended: ship flagged, don't
   silently trust it.)
2. **Docker image size**: each `tessdata_best` file is roughly 10–15 MB; five languages
   adds well under 100 MB to the image — flagging only because it's a deploy-time cost, not
   because it's actually a concern.
3. Should `expected_country` be a free-text officer selection in the frontend (dropdown), or
   inferred some other way? This plan assumes a frontend dropdown — the cheapest correct
   answer given the manned-kiosk deployment context.
