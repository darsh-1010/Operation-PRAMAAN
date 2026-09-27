"""Synthetic Benchmark Suite for Identity Document Screening (Module 1).

Generates annotated synthetic ICAO Doc 9303 identity documents (TD3 Passports)
across diverse real-world conditions (clean, rotations, noise/blur, and tampering)
and benchmarks OCR extraction, MRZ parsing, and fraud/tamper detection accuracy.
"""

from __future__ import annotations
import os
import random
import sys
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# Ensure service modules can be imported
SERVICE_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVICE_DIR not in sys.path:
    sys.path.insert(0, SERVICE_DIR)

from candidate_search import CandidateRecord
from decision_matrix import evaluate_decision_matrix
from field_extractor import extract_document_fields
from matcher import match_against_candidate
from mrz_verifier import (
    calculate_mrz_checksum,
    clean_mrz_line,
    extract_and_verify_mrz,
)
from ocr_engine import OCREngine


@dataclass
class SyntheticDocMeta:
    """Ground truth metadata for a synthetic document."""
    doc_id: str
    doc_type: str            # 'PASSPORT'
    condition: str           # 'clean', 'rot90', 'rot180', 'rot270', 'noisy', 'tampered'
    surname: str
    given_name: str
    full_name: str
    doc_number: str
    country: str
    dob_iso: str             # YYYY-MM-DD
    dob_yymmdd: str          # YYMMDD
    expiry_iso: str          # YYYY-MM-DD
    expiry_yymmdd: str       # YYMMDD
    gender: str              # 'M' or 'F'
    mrz_lines: List[str]
    is_tampered: bool
    tamper_reason: Optional[str] = None


def create_td3_mrz(meta: Dict[str, Any], tamper: bool = False) -> List[str]:
    """Generate valid or deliberately tampered ICAO TD3 passport MRZ lines (44 chars each)."""
    country = meta["country"].ljust(3, "<")[:3]
    s_clean = meta["surname"].upper().replace(" ", "<")
    g_clean = meta["given_name"].upper().replace(" ", "<")
    l1 = f"P<{country}{s_clean}<<{g_clean}".ljust(44, "<")[:44]

    doc_num = meta["doc_number"].ljust(9, "<")[:9]
    cd_doc = calculate_mrz_checksum(doc_num)

    dob_str = meta["dob_yymmdd"]
    cd_dob = calculate_mrz_checksum(dob_str)

    gender_char = meta["gender"]
    exp_str = meta["expiry_yymmdd"]
    cd_exp = calculate_mrz_checksum(exp_str)

    opt_data = "".ljust(14, "<")
    cd_opt = calculate_mrz_checksum(opt_data)

    comp_data = doc_num + str(cd_doc) + dob_str + str(cd_dob) + exp_str + str(cd_exp) + opt_data + str(cd_opt)
    cd_comp = calculate_mrz_checksum(comp_data)

    # In tamper mode, flip a check digit to simulate forged data
    if tamper:
        tampered_cd_doc = (cd_doc + 1) % 10
        l2 = f"{doc_num}{tampered_cd_doc}{country}{dob_str}{cd_dob}{gender_char}{exp_str}{cd_exp}{opt_data}{cd_opt}{cd_comp}"
    else:
        l2 = f"{doc_num}{cd_doc}{country}{dob_str}{cd_dob}{gender_char}{exp_str}{cd_exp}{opt_data}{cd_opt}{cd_comp}"

    return [l1, l2]


def render_passport_image(meta: SyntheticDocMeta) -> Image.Image:
    """Render a synthetic passport document page with photo and MRZ."""
    w, h = 850, 560
    img = Image.new("RGB", (w, h), color=(245, 246, 240))
    draw = ImageDraw.Draw(img)

    # Background frame & subtle security guilloché lines
    draw.rectangle([(20, 20), (w - 20, h - 20)], outline=(180, 180, 170), width=2)
    for y_offset in range(30, h - 160, 25):
        draw.line([(30, y_offset), (w - 30, y_offset)], fill=(235, 236, 230), width=1)

    # Document Header
    draw.text((280, 35), f"REPUBLIC OF {meta.country} / PASSPORT", fill=(20, 30, 80))
    draw.text((280, 65), f"Type: P   Code: {meta.country}   Passport No: {meta.doc_number}", fill=(0, 0, 0))

    # Placeholder Photo Box
    draw.rectangle([(45, 90), (220, 310)], fill=(200, 210, 220), outline=(100, 100, 100), width=2)
    draw.text((85, 190), "PHOTO", fill=(100, 100, 100))

    # Visual Inspection Zone (VIZ) Fields
    viz_fields = [
        ("Surname", meta.surname),
        ("Given Names", meta.given_name),
        ("Nationality", meta.country),
        ("Date of Birth", meta.dob_iso),
        ("Sex", meta.gender),
        ("Date of Expiry", meta.expiry_iso),
    ]
    for idx, (lbl, val) in enumerate(viz_fields):
        y = 100 + idx * 35
        draw.text((280, y), f"{lbl}: {val}", fill=(10, 10, 10))

    # Machine Readable Zone (MRZ)
    mrz_bg = [(30, h - 140), (w - 30, h - 30)]
    draw.rectangle(mrz_bg, fill=(255, 255, 255), outline=(210, 210, 210))
    draw.text((45, h - 120), meta.mrz_lines[0], fill=(0, 0, 0))
    draw.text((45, h - 75), meta.mrz_lines[1], fill=(0, 0, 0))

    return img


def apply_condition(img: Image.Image, condition: str) -> Image.Image:
    """Apply real-world conditions (rotation, noise, blur) to the image."""
    if condition == "rot90":
        return img.rotate(90, expand=True)
    if condition == "rot180":
        return img.rotate(180, expand=True)
    if condition == "rot270":
        return img.rotate(270, expand=True)
    if condition == "noisy":
        blurred = img.filter(ImageFilter.GaussianBlur(radius=0.5))
        np_arr = np.array(blurred, dtype=np.int16)
        noise = np.random.normal(0, 10, np_arr.shape).astype(np.int16)
        noisy = np.clip(np_arr + noise, 0, 255).astype(np.uint8)
        return Image.fromarray(noisy)
    return img


def compute_levenshtein(s1: str, s2: str) -> int:
    """Calculate edit distance between two strings."""
    if len(s1) < len(s2):
        return compute_levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev = list(range(len(s2) + 1))
    for i, c1 in enumerate(s1):
        curr = [i + 1]
        for j, c2 in enumerate(s2):
            cost = 0 if c1 == c2 else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[-1]


def compute_cer(ground_truth: str, predicted: str) -> float:
    """Calculate Character Error Rate (CER)."""
    gt_clean = ground_truth.strip().upper()
    pred_clean = predicted.strip().upper()
    if not gt_clean:
        return 0.0 if not pred_clean else 1.0
    dist = compute_levenshtein(gt_clean, pred_clean)
    return min(1.0, dist / len(gt_clean))


def generate_sample_dataset(size: int = 12) -> List[SyntheticDocMeta]:
    """Create a balanced set of synthetic documents across conditions."""
    first_names = ["ANNA", "JOHN", "PRIYA", "RAHUL", "MARIA", "ALEX"]
    last_names = ["ERIKSSON", "DOE", "SHARMA", "KUMAR", "GARCIA", "SMITH"]
    countries = ["IND", "USA", "DEU", "GBR", "FRA", "CAN"]
    conditions = ["clean", "rot90", "rot180", "rot270", "noisy", "tampered"]

    samples: List[SyntheticDocMeta] = []
    for i in range(size):
        cond = conditions[i % len(conditions)]
        is_tamp = (cond == "tampered")
        fn = first_names[i % len(first_names)]
        ln = last_names[i % len(last_names)]
        ctry = countries[i % len(countries)]
        doc_num = f"A{10000000 + i * 7891}"
        dob_yymmdd = f"{(80 + i * 2) % 100:02d}0515"
        dob_iso = f"19{(80 + i * 2) % 100:02d}-05-15"
        exp_yymmdd = f"{(29 + i) % 100:02d}0820"
        exp_iso = f"20{(29 + i) % 100:02d}-08-20"
        gender = "F" if i % 2 == 0 else "M"

        meta_dict = {
            "country": ctry, "surname": ln, "given_name": fn,
            "doc_number": doc_num, "dob_yymmdd": dob_yymmdd,
            "expiry_yymmdd": exp_yymmdd, "gender": gender,
        }
        mrz_lines = create_td3_mrz(meta_dict, tamper=is_tamp)

        samples.append(SyntheticDocMeta(
            doc_id=f"SYN-{i+1:03d}",
            doc_type="PASSPORT",
            condition=cond,
            surname=ln,
            given_name=fn,
            full_name=f"{ln} {fn}",
            doc_number=doc_num,
            country=ctry,
            dob_iso=dob_iso,
            dob_yymmdd=dob_yymmdd,
            expiry_iso=exp_iso,
            expiry_yymmdd=exp_yymmdd,
            gender=gender,
            mrz_lines=mrz_lines,
            is_tampered=is_tamp,
            tamper_reason="Document number check digit mismatch (altered digit)" if is_tamp else None,
        ))

    return samples


def run_benchmark(sample_count: int = 12) -> Dict[str, Any]:
    """Execute complete benchmark test against Module 1 OCR and screening."""
    print("\n=======================================================")
    print("   OPERATION PRAMAAN - MODULE 1 ACCURACY BENCHMARK   ")
    print("=======================================================\n")
    print(f"Evaluating {sample_count} synthetic identity documents...")
    dataset = generate_sample_dataset(sample_count)
    engine = OCREngine.get_instance()

    latencies: List[float] = []
    cer_list: List[float] = []
    mrz_detected_count = 0
    mrz_docnum_correct = 0
    mrz_name_correct = 0

    # Fraud detection confusion matrix
    tp = 0  # Tampered correctly flagged as fail
    fp = 0  # Valid incorrectly flagged as fail
    tn = 0  # Valid correctly passed
    fn = 0  # Tampered missed

    condition_results: Dict[str, Dict[str, Any]] = {}

    for idx, sample in enumerate(dataset):
        base_img = render_passport_image(sample)
        test_img = apply_condition(base_img, sample.condition)
        np_img = np.array(test_img)

        # 1. Measure OCR inference
        t0 = time.perf_counter()
        ocr_res = engine.extract_text(np_img)
        dt_ms = (time.perf_counter() - t0) * 1000.0
        latencies.append(dt_ms)

        # 2. MRZ parsing & verification
        mrz_res = extract_and_verify_mrz(ocr_res.lines)
        has_mrz = (mrz_res is not None and mrz_res.valid_format)

        # 3. Measure MRZ CER against ground truth
        if has_mrz and mrz_res.raw_lines:
            pred_mrz = "\n".join(mrz_res.raw_lines)
            gt_mrz = "\n".join(sample.mrz_lines)
            cer = compute_cer(gt_mrz, pred_mrz)
        else:
            # Check best OCR match among lines
            best_d = 88
            gt_mrz = "\n".join(sample.mrz_lines)
            for i in range(len(ocr_res.lines) - 1):
                cand = ocr_res.lines[i] + "\n" + ocr_res.lines[i + 1]
                d = compute_levenshtein(gt_mrz, cand)
                if d < best_d:
                    best_d = d
            cer = min(1.0, best_d / 88.0)
        cer_list.append(cer)

        if has_mrz:
            mrz_detected_count += 1
            if mrz_res.document_number == sample.doc_number:
                mrz_docnum_correct += 1
            if sample.surname in (mrz_res.full_name or ""):
                mrz_name_correct += 1

        # 4. Field extraction & Decision Matrix evaluation
        parsed_doc = extract_document_fields(ocr_res)
        candidate = CandidateRecord(
            record_id=sample.doc_id,
            full_name=sample.full_name,
            doc_type=sample.doc_type,
            id_number=sample.doc_number,
            dob=sample.dob_iso,
            gender=sample.gender,
            expiry_date=sample.expiry_iso,
            status="ACTIVE",
            issuing_country=sample.country,
        )
        match_outcome = match_against_candidate(parsed_doc, candidate)
        decision = evaluate_decision_matrix(parsed_doc, match_outcome, watchlist_hits=[])

        # 5. Track Tamper / Fraud Detection
        detected_tamper = decision.hard_fail or (mrz_res is not None and mrz_res.has_checksum_failure)
        if sample.is_tampered:
            if detected_tamper:
                tp += 1
            else:
                fn += 1
        else:
            if detected_tamper:
                fp += 1
            else:
                tn += 1

        # Condition breakdown
        cond = sample.condition
        if cond not in condition_results:
            condition_results[cond] = {"count": 0, "mrz_detected": 0, "cer": [], "correct_decision": 0}
        condition_results[cond]["count"] += 1
        condition_results[cond]["cer"].append(cer)
        if has_mrz:
            condition_results[cond]["mrz_detected"] += 1
        if (sample.is_tampered and detected_tamper) or (not sample.is_tampered and not detected_tamper):
            condition_results[cond]["correct_decision"] += 1

        verdict = "REJECT/TAMPER" if detected_tamper else "VERIFIED"
        print(f"[{idx+1:02d}/{sample_count}] {sample.doc_id} | Cond: {cond:<9} | CER: {cer:5.1%} | MRZ Found: {str(has_mrz):<5} | Status: {verdict:<13} ({dt_ms:.1f}ms)")

    # Aggregate Statistics
    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    f1 = 2 * (precision * recall) / (precision + recall) if (precision + recall) > 0 else 1.0
    overall_accuracy = (tp + tn) / sample_count
    mean_latency = sum(latencies) / len(latencies)
    mean_cer = sum(cer_list) / len(cer_list)

    report = {
        "total_samples": sample_count,
        "ocr_engine": engine._engine_name,
        "mean_cer": round(mean_cer, 4),
        "mean_latency_ms": round(mean_latency, 2),
        "mrz_detection_rate": round(mrz_detected_count / sample_count, 4),
        "mrz_docnum_accuracy": round(mrz_docnum_correct / max(1, mrz_detected_count), 4),
        "fraud_detection": {
            "true_positives": tp,
            "false_positives": fp,
            "true_negatives": tn,
            "false_negatives": fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1_score": round(f1, 4),
        },
        "overall_accuracy": round(overall_accuracy, 4),
        "condition_breakdown": condition_results,
    }

    return report


if __name__ == "__main__":
    report = run_benchmark(sample_count=12)
    print("\n-------------------------------------------------------")
    print("BENCHMARK RESULTS SUMMARY:")
    print(f"  OCR Engine:                 {report['ocr_engine']}")
    print(f"  Overall Decision Accuracy:  {report['overall_accuracy']:.1%}")
    print(f"  Mean MRZ CER:               {report['mean_cer']:.1%}")
    print(f"  MRZ Detection Rate:         {report['mrz_detection_rate']:.1%}")
    print(f"  Document Number Accuracy:   {report['mrz_docnum_accuracy']:.1%}")
    print(f"  Fraud Detection Recall:     {report['fraud_detection']['recall']:.1%}")
    print(f"  Fraud Detection Precision:  {report['fraud_detection']['precision']:.1%}")
    print(f"  Fraud Detection F1-Score:   {report['fraud_detection']['f1_score']:.1%}")
    print(f"  Average Inference Latency:  {report['mean_latency_ms']:.1f} ms")
    print("-------------------------------------------------------\n")
