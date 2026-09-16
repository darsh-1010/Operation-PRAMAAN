"""Field Extraction and Document Parser."""

from __future__ import annotations
import re
from typing import Any, Dict, List, Optional

from field_patterns import (
    BLACKLIST,
    COLUMN_HEADER,
    HEADER_MARKERS,
    LABEL_TAGS,
    STOP_MARKERS,
    ExtractedField,
    ParsedDocumentData,
    detect_document_type,
    extract_regex_value,
)
from mrz_verifier import MRZCheckResult, extract_and_verify_mrz
from nepali_calendar import convert_bikram_sambat
from normalizer import normalize_date, normalize_gender, normalize_id_number, normalize_name
from ocr_engine import OCRResult, TextBlock
from script_detector import detect_script_and_language


def extract_labeled_field(
    lines: List[str], label_pattern: str, max_lookahead: int = 3, disallowed_preceding: Optional[str] = None
) -> Optional[str]:
    """Find a value adjacent to or on the line following a field label, ignoring header junk."""
    for idx, line in enumerate(lines):
        for match in re.finditer(label_pattern, line, re.IGNORECASE):
            preceding_text = line[:match.start()].strip()
            if disallowed_preceding and preceding_text and re.search(disallowed_preceding, preceding_text, re.IGNORECASE):
                continue

            remainder = line[match.end():].strip()
            remainder = re.sub(r"^\([a-zA-Z\s]{1,4}\)", "", remainder).strip().lstrip(":/-").strip()

            while True:
                rem_clean = remainder.lstrip(":/-–— \t").strip()
                m_label = LABEL_TAGS.search(rem_clean)
                if m_label and m_label.end() > 0:
                    remainder = rem_clean[m_label.end():].strip()
                else:
                    break

            if COLUMN_HEADER.search(remainder):
                remainder = ""

            if len(remainder) >= 2 and not LABEL_TAGS.search(remainder) and not re.search(r"^(OF|AND|THE|NO|को|नं|CONTROL\s*NUMBER)\b", remainder, re.I) and re.search(r"[A-Za-z0-9\u0900-\u097F]", remainder):
                return remainder

            for offset in range(1, max_lookahead + 1):
                if idx + offset < len(lines):
                    cand = lines[idx + offset].strip().lstrip(":/-").strip()
                    if not cand or len(cand) < 2:
                        continue
                    hdrs = COLUMN_HEADER.findall(cand)
                    words = cand.split()
                    if hdrs and (len(words) <= 3 or len(hdrs) >= max(1, len(words) // 2)):
                        continue
                    if not LABEL_TAGS.search(cand) and not re.search(r"(NAME|DOB|DATE|SEX|PASSPORT|NUMBER|EXPIRY|नाम|मिति|लिंग|CONTROL\s*NUMBER)", cand, re.I) and re.search(r"[A-Za-z0-9\u0900-\u097F]", cand):
                        clean_cand = re.split(r"\b(VISA|TYPE|CLASS|SEX|BIRTH|EXP|DATE|R\s*K[-0-9]?)\b", cand, flags=re.I)[0].strip()
                        clean_cand = re.sub(r"^[^A-Za-z0-9\u0900-\u097F]+", "", clean_cand).strip()
                        return clean_cand if len(clean_cand) >= 2 else cand
    return None


def _is_valid_name_line(cand: str) -> bool:
    if not cand or BLACKLIST.search(cand) or HEADER_MARKERS.search(cand):
        return False
    words = cand.split()
    return (1 <= len(words) <= 4 and all(re.match(r"^[A-Za-z]+$", w) and len(w) >= 2 for w in words)
            and not any(w.upper() in ("INDIA", "GOVERNMENT", "MALE", "FEMALE", "YEAR", "BIRTH", "ENROLMENT", "CARD", "AUTHORITY", "UNIQUE") for w in words))


def _extract_positional_national_id_name(lines: List[str]) -> Optional[str]:
    """Positional extraction for Aadhaar and standard National IDs without an explicit 'NAME:' label."""
    dob_idx = next((i for i, l in enumerate(lines) if re.search(r"\b(DOB|D\.O\.B|DATE\s*OF\s*BIRTH|YEAR\s*OF\s*BIRTH|जन्म)\b", l, re.I)), -1)
    if dob_idx > 0:
        for offset in range(1, min(4, dob_idx + 1)):
            cand = lines[dob_idx - offset].strip()
            if _is_valid_name_line(cand):
                return cand

    header_idx = next((i for i, l in enumerate(lines) if HEADER_MARKERS.search(l)), -1)
    stop_idx = next((i for i, l in enumerate(lines) if STOP_MARKERS.search(l)), len(lines))
    for i in range(max(0, header_idx + 1), min(stop_idx, len(lines))):
        if _is_valid_name_line(lines[i].strip()):
            return lines[i].strip()
    return None


def extract_document_fields(
    ocr_result: OCRResult, expected_country: Optional[str] = None, expected_language: Optional[str] = None
) -> ParsedDocumentData:
    """Orchestrate extraction across MRZ, VIZ, and regional language/calendar formats."""
    lines, full_text = ocr_result.lines, ocr_result.full_text
    fields_list: List[ExtractedField] = []
    lang_info = detect_script_and_language(full_text, expected_country, expected_language)

    mrz = extract_and_verify_mrz(lines)
    doc_type = mrz.doc_type if (mrz and mrz.valid_format) else detect_document_type(full_text)

    viz_surname = extract_labeled_field(lines, r"\b(SURNAME|LAST\s*NAME|उपनाम|थर|APELLIDOS?)\b", disallowed_preceding=r"(POST|FATHER|MOTHER|SPOUSE|HUSBAND)\b")
    viz_given = extract_labeled_field(lines, r"\b(GIVEN\s*NAME(\([sS]\)|S)?|FIRST\s*NAME|दिए\s*गए\s*नाम|PRENOMS?)\b", disallowed_preceding=r"(POST|FATHER|MOTHER|SPOUSE|HUSBAND)\b")
    if viz_surname and viz_given:
        viz_name_raw = f"{viz_surname} {viz_given}"
    elif viz_surname or viz_given:
        viz_name_raw = viz_surname or viz_given
    else:
        viz_name_raw = extract_labeled_field(lines, r"\b(FULL\s*NAME|NAME|नाम|नाम,\s*थर)\b", disallowed_preceding=r"(POST|ISSUING\s*POST|FATHER['’]?S?|MOTHER['’]?S?|SPOUSE['’]?S?|HUSBAND['’]?S?|BANK|BRANCH|PLACE|CITY|STATE|DISTRICT|CARD|FILE)\b")

    if not viz_name_raw and doc_type == "NATIONAL_ID":
        viz_name_raw = _extract_positional_national_id_name(lines)

    viz_dob_raw = extract_labeled_field(lines, r"\b(DATE\s*OF\s*BIRTH|DOB|D\.O\.B|BIRTH\s*DATE|जन्म\s*मिति|जन्म\s*तिथि|वि\.सं\.?)\b")
    viz_exp_raw = extract_labeled_field(lines, r"\b(DATE\s*OF\s*EXPIRY|EXPIRY\s*DATE|VALID\s*UNTIL|EXP|म्याद|अवधि|बहाल\s*रहने\s*अवधि)\b")
    viz_sex_raw = extract_labeled_field(lines, r"\b(SEX|GENDER|लिंग)\b")
    if not viz_sex_raw:
        for line in lines:
            m_gen = re.search(r"\b(MALE|FEMALE|पुरुष|महिला)\b", line, re.I)
            if m_gen:
                viz_sex_raw = m_gen.group(1)
                break

    # Document Number regexes
    viz_id_raw = (
        extract_regex_value(full_text, r"\b([A-PR-WY][0-9O]{7,8})\b") if doc_type in ("PASSPORT", "VISA")
        else (extract_regex_value(full_text, r"\b([0-9]{4}\s+[0-9]{4}\s+[0-9]{4})\b") or extract_regex_value(full_text, r"\b([A-Z]{5}[0-9]{4}[A-Z])\b") or extract_regex_value(full_text, r"\b([0-9]{2}-[0-9]{2}-[0-9]{2}-[0-9]{4,5})\b"))
    ) or extract_labeled_field(lines, r"\b(PASSPORT\s*(?:NO\.?|NUMBER)|VISA\s*(?:NO\.?|NUMBER)|ID\s*(?:NO\.?|NUMBER)|DOCUMENT\s*(?:NO\.?|NUMBER)|LICEN[SC]E\s*(?:NO\.?|NUMBER)|नम्बर|नं)\b", disallowed_preceding=r"(POST|ISSUING|CONTROL|BATCH|PHONE)\b")

    viz_name = normalize_name(viz_name_raw) if viz_name_raw else None
    viz_dob, viz_dob_bs, calendar_sys = (None, None, "GREGORIAN")
    if viz_dob_raw:
        has_bs = bool(re.search(r"(B\.?S\.?|VI\.?SAM\.?|वि\.?सं\.?)", viz_dob_raw, re.I) or expected_country == "NPL")
        norm = normalize_date(viz_dob_raw) if not has_bs else None
        if norm:
            viz_dob = norm
        else:
            bs = convert_bikram_sambat(viz_dob_raw)
            if bs and bs.is_valid and bs.gregorian_date:
                viz_dob, viz_dob_bs, calendar_sys = bs.gregorian_date, bs.raw_input, "BIKRAM_SAMBAT"
            else:
                viz_dob = normalize_date(viz_dob_raw)
    viz_exp = normalize_date(viz_exp_raw) if viz_exp_raw else None
    viz_gender = normalize_gender(viz_sex_raw) if viz_sex_raw else None
    viz_id = normalize_id_number(viz_id_raw) if viz_id_raw else None

    for k, v in [("NAME", viz_name), ("DOB", viz_dob), ("EXPIRY", viz_exp), ("GENDER", viz_gender), ("DOCUMENT_NUMBER", viz_id)]:
        if v:
            fields_list.append(ExtractedField(k, v, "VIZ", 0.90))

    if mrz and mrz.valid_format:
        for k, v in [("NAME", mrz.full_name), ("DOB", mrz.dob), ("EXPIRY", mrz.expiry), ("GENDER", mrz.gender), ("DOCUMENT_NUMBER", mrz.document_number)]:
            if v:
                fields_list.append(ExtractedField(k, v, "MRZ", 0.99 if not mrz.has_checksum_failure else 0.70))

    inconsistencies = []
    final_name, final_id = viz_name, viz_id
    if mrz and mrz.valid_format:
        if mrz.document_number and viz_id and mrz.document_number != viz_id:
            inconsistencies.append(f"Doc Number mismatch: VIZ '{viz_id}' vs MRZ '{mrz.document_number}'")
        final_id = mrz.document_number or viz_id
        if mrz.full_name:
            if viz_name and mrz.full_name != viz_name:
                from matcher import compute_fuzzy_name_score
                if compute_fuzzy_name_score(viz_name, mrz.full_name) >= 0.85:
                    final_name = viz_name
                else:
                    inconsistencies.append(f"Name mismatch: VIZ '{viz_name}' vs MRZ '{mrz.full_name}'")
                    final_name = mrz.full_name
            else:
                final_name = viz_name or mrz.full_name

    final_dob = (mrz.dob if (mrz and mrz.dob) else viz_dob)
    final_exp = (mrz.expiry if (mrz and mrz.expiry) else viz_exp)
    final_gen = (mrz.gender if (mrz and mrz.gender) else viz_gender)

    return ParsedDocumentData(
        doc_type=doc_type, document_number=final_id, claimed_name=final_name,
        claimed_dob=final_dob, claimed_expiry=final_exp, claimed_gender=final_gen,
        issuing_country=mrz.issuing_country if (mrz and mrz.issuing_country) else "IND",
        fields=fields_list, mrz_result=mrz, viz_mrz_consistent=(len(inconsistencies) == 0),
        inconsistencies=inconsistencies, detected_language=lang_info.language_name,
        detected_script=lang_info.detected_script, claimed_dob_bs=viz_dob_bs, calendar_system=calendar_sys,
    )
