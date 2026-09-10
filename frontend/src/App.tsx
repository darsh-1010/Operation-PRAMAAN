import { useState } from "react";
import { screenDocument, type ScreenResponse } from "./api";

const STATUS_CLASS: Record<string, string> = {
  VERIFIED: "status-verified",
  "NEEDS REVIEW": "status-review",
  "NOT VERIFIED": "status-failed",
};

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ScreenResponse | null>(null);

  async function handleUpload() {
    if (!file) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await screenDocument(file);
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page">
      <h1>Operation PRAMAAN — Document Screening</h1>
      <p className="subtitle">Module 1: OCR extraction, MRZ verification &amp; registry matching</p>

      <div className="upload-box">
        <input
          type="file"
          accept="image/png,image/jpeg,image/webp,application/pdf"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <button onClick={handleUpload} disabled={!file || loading}>
          {loading ? "Screening…" : "Upload & Screen"}
        </button>
      </div>

      {error && <div className="error-box">{error}</div>}

      {result && (
        <div className="result">
          <div className={`status-badge ${STATUS_CLASS[result.status] ?? ""}`}>
            {result.status} — {result.score.toFixed(1)}/100
          </div>

          <section>
            <h2>Extracted Fields</h2>
            <table>
              <tbody>
                <tr><td>Document Type</td><td>{result.doc_type}</td></tr>
                <tr><td>Document Number</td><td>{result.document_number ?? "—"}</td></tr>
                <tr><td>Name</td><td>{result.claimed_name ?? "—"}</td></tr>
                <tr><td>DOB</td><td>{result.claimed_dob ?? "—"}</td></tr>
                <tr><td>Expiry</td><td>{result.claimed_expiry ?? "—"}</td></tr>
                <tr><td>Issuing Country</td><td>{result.issuing_country}</td></tr>
                <tr><td>MRZ Valid</td><td>{result.mrz_valid === null ? "n/a" : result.mrz_valid ? "Yes" : "No"}</td></tr>
                <tr><td>Registry Match</td><td>{result.candidate_matched ? "Found" : "Not found"}</td></tr>
              </tbody>
            </table>
          </section>

          {result.reason_codes.length > 0 && (
            <section>
              <h2>Reason Codes</h2>
              <ul className="reason-list">
                {result.reason_codes.map((r, i) => (
                  <li key={i} className={`severity-${r.severity.toLowerCase()}`}>
                    <strong>{r.code}</strong> ({r.severity}): {r.message}
                  </li>
                ))}
              </ul>
            </section>
          )}

          <section>
            <h2>Validation Checks</h2>
            <table>
              <thead>
                <tr><th>Check</th><th>Field</th><th>Status</th><th>Detail</th></tr>
              </thead>
              <tbody>
                {result.validation_checks.map((c, i) => (
                  <tr key={i}>
                    <td>{c.check_type}</td>
                    <td>{c.field_key ?? "—"}</td>
                    <td className={c.status === "PASS" ? "check-pass" : c.status === "FAIL" ? "check-fail" : "check-warn"}>
                      {c.status}
                    </td>
                    <td>{c.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </div>
      )}
    </div>
  );
}
