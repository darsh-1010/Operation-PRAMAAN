// Client for Module 1 — OCR & Consistency Check service.
const OCR_SERVICE_URL = import.meta.env.VITE_OCR_SERVICE_URL || "http://localhost:8001";

export interface ReasonCode {
  code: string;
  message: string;
  severity: string;
  contribution: number;
}

export interface ValidationCheck {
  check_type: string;
  field_key: string | null;
  status: string;
  is_hard_fail: boolean;
  expected: string | null;
  observed: string | null;
  detail: string;
}

export interface ExtractedField {
  field_key: string;
  field_value: string | null;
  source: string;
  confidence: number;
}

export interface ScreenResponse {
  session_id: string;
  document_id: string;
  status: string;
  score: number;
  canonical_score: number;
  hard_fail: boolean;
  doc_type: string;
  document_number: string | null;
  claimed_name: string | null;
  claimed_dob: string | null;
  claimed_expiry: string | null;
  claimed_gender: string | null;
  issuing_country: string;
  reason_codes: ReasonCode[];
  validation_checks: ValidationCheck[];
  candidate_matched: boolean;
  candidate_details: Record<string, unknown> | null;
  mrz_valid: boolean | null;
  extracted_fields: ExtractedField[];
}

export async function screenDocument(file: File): Promise<ScreenResponse> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${OCR_SERVICE_URL}/api/v1/screen`, {
    method: "POST",
    body: form,
  });
  if (!res.ok) {
    const detail = await res.text();
    throw new Error(`Screening failed (${res.status}): ${detail}`);
  }
  return res.json();
}
