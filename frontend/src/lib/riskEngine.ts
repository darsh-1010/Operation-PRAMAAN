// Each module's own /screen handler pushes its flag + score to risk-scoring-engine as a
// side effect (see services/*/main.py) — the frontend never calls /flag-check or /submit-score
// itself. This file only reads back the fused result.

export interface RiskResult {
  uuid: string
  score: number | null
  decision: 'PASS' | 'MANUAL_REVIEW' | 'FAIL' | 'REJECTED'
  timed_out: boolean
}

const RISK_URL = import.meta.env.VITE_RISK_SERVICE_URL

/** Polls GET /result/{uuid} a handful of times. This resolves fast for an outright reject
 * (any module's hard_fail short-circuits the risk engine immediately) or once every module
 * has pushed a score. It will NOT resolve within this window for a "needs fusion" case while
 * visual-image-forensics is still a stub that never pushes — that uuid sits on the risk
 * engine's side until its 5-minute timeout auto-escalates it. Rather than block the UI for
 * that long, screening.ts falls back to fusing the modules' own scores client-side. */
export async function pollRiskResult(uuid: string, { attempts = 8, intervalMs = 400 } = {}): Promise<RiskResult | null> {
  if (!RISK_URL) return null
  const url = `${RISK_URL.replace(/\/$/, '')}/result/${uuid}`

  for (let i = 0; i < attempts; i++) {
    try {
      const res = await fetch(url)
      if (res.ok) return (await res.json()) as RiskResult
    } catch {
      // risk engine unreachable this attempt — retry, then give up and let the caller fall back
    }
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }
  return null
}
