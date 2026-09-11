import { useState } from "react";
import { convertNepaliCalendar, screenDocument, type CalendarConvertResponse, type ScreenResponse } from "./api";

const STATUS_CLASS: Record<string, string> = {
  VERIFIED: "status-verified",
  "NEEDS REVIEW": "status-review",
  "NOT VERIFIED": "status-failed",
};

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [countryHint, setCountryHint] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ScreenResponse | null>(null);

  // Nepali Calendar Converter Widget State
  const [calInput, setCalInput] = useState<string>("2082-04-25");
  const [calResult, setCalResult] = useState<CalendarConvertResponse | null>(null);
  const [calLoading, setCalLoading] = useState(false);
  const [calError, setCalError] = useState<string | null>(null);

  async function handleUpload() {
    if (!file) return;
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await screenDocument(file, countryHint || undefined);
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  async function handleConvertCalendar() {
    if (!calInput.trim()) return;
    setCalLoading(true);
    setCalError(null);
    try {
      const res = await convertNepaliCalendar(calInput.trim());
      setCalResult(res);
    } catch (err) {
      setCalError(err instanceof Error ? err.message : String(err));
    } finally {
      setCalLoading(false);
    }
  }

  return (
    <div className="page">
      <h1>Operation PRAMAAN — Document Screening</h1>
      <p className="subtitle">
        Multilingual OCR extraction, Nepali Bikram Sambat calendar translation &amp; consistency verification
      </p>

      {/* Document Upload Card */}
      <div className="card">
        <h2>Upload Document</h2>
        <div className="upload-box">
          <input
            type="file"
            accept="image/png,image/jpeg,image/webp,application/pdf"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          />
          <select
            value={countryHint}
            onChange={(e) => setCountryHint(e.target.value)}
            className="select-input"
          >
            <option value="">Auto-Detect Script / Country</option>
            <option value="NPL">Nepal (NPL) — Devanagari &amp; B.S. Calendar</option>
            <option value="IND">India (IND) — English / Hindi</option>
            <option value="BGD">Bangladesh (BGD) — Bengali</option>
            <option value="PAK">Pakistan (PAK) — Urdu</option>
            <option value="MMR">Myanmar (MMR) — Burmese</option>
            <option value="BTN">Bhutan (BTN) — Dzongkha</option>
          </select>
          <button onClick={handleUpload} disabled={!file || loading}>
            {loading ? "Screening…" : "Upload & Screen"}
          </button>
        </div>
      </div>

      {error && <div className="error-box">{error}</div>}

      {/* Screening Result */}
      {result && (
        <div className="result card">
          <div className="result-header">
            <div className={`status-badge ${STATUS_CLASS[result.status] ?? ""}`}>
              {result.status} — {result.score.toFixed(1)}/100
            </div>
            <div className="language-badge">
              🌐 {result.detected_language} ({result.detected_script})
            </div>
            {result.calendar_system === "BIKRAM_SAMBAT" && (
              <div className="calendar-badge">
                📅 Bikram Sambat (B.S.) Calendar Detected
              </div>
            )}
          </div>

          <section>
            <h2>Extracted Fields &amp; Calendar Translation</h2>
            <table>
              <tbody>
                <tr><td>Document Type</td><td>{result.doc_type}</td></tr>
                <tr><td>Document Number</td><td>{result.document_number ?? "—"}</td></tr>
                <tr><td>Name</td><td>{result.claimed_name ?? "—"}</td></tr>
                {result.claimed_dob_bs && (
                  <tr>
                    <td>DOB (Bikram Sambat)</td>
                    <td><strong>{result.claimed_dob_bs}</strong></td>
                  </tr>
                )}
                <tr>
                  <td>DOB (Gregorian Normalized)</td>
                  <td>{result.claimed_dob ?? "—"}</td>
                </tr>
                <tr><td>Calendar System</td><td>{result.calendar_system}</td></tr>
                <tr><td>Detected Script</td><td>{result.detected_script}</td></tr>
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

      {/* Nepali Calendar Conversion Tool Card */}
      <div className="card cal-tool-card">
        <h2>Nepali Bikram Sambat (B.S.) to Gregorian (A.D.) Converter</h2>
        <p className="hint-text">
          Enter a Nepali year (e.g. <code>2080 BS</code>, <code>२०८०</code>) or date with Nepali month
          (e.g. <code>2082-04-25</code>, <code>15 Baishakh 2080</code>, <code>१५ बैशाख २०८०</code>) to convert to Gregorian.
        </p>
        <div className="cal-tool-row">
          <input
            type="text"
            className="text-input"
            value={calInput}
            onChange={(e) => setCalInput(e.target.value)}
            placeholder="e.g. 2082-04-25, 15 Baishakh 2080, or 2080 BS"
          />
          <button onClick={handleConvertCalendar} disabled={calLoading || !calInput.trim()}>
            {calLoading ? "Converting…" : "Convert to Gregorian"}
          </button>
        </div>

        {calError && <div className="error-box">{calError}</div>}

        {calResult && (
          <div className="cal-result-box">
            <div className="cal-result-title">Conversion Result:</div>
            <div className="cal-result-grid">
              <div><span>Input:</span> <strong>{calResult.raw_input}</strong></div>
              <div><span>B.S. Year:</span> <strong>{calResult.bs_year}</strong></div>
              {calResult.bs_month_name && (
                <div><span>B.S. Month:</span> <strong>{calResult.bs_month_name} ({calResult.bs_month})</strong></div>
              )}
              {calResult.gregorian_date ? (
                <div><span>Gregorian Date:</span> <strong className="highlight-date">{calResult.gregorian_date}</strong></div>
              ) : (
                <div><span>Gregorian Year Span:</span> <strong className="highlight-date">{calResult.gregorian_year_span}</strong></div>
              )}
            </div>
            <div className="cal-result-detail">{calResult.detail}</div>
          </div>
        )}
      </div>
    </div>
  );
}
