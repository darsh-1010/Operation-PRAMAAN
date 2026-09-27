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

/** Every screening id is issued by the risk engine (POST /sessions): modules may only report
 * results against ids it issued, so ids can't be invented or re-used. No risk engine = no
 * screening — throws rather than falling back to a browser-made id. */
export async function createSession(): Promise<string> {
  if (!RISK_URL) throw new Error('VITE_RISK_SERVICE_URL is not set (see .env.example)')
  const res = await fetch(`${RISK_URL.replace(/\/$/, '')}/sessions`, { method: 'POST' })
  if (!res.ok) throw new Error(`Could not start a screening: risk engine answered HTTP ${res.status}`)
  const body = (await res.json()) as { uuid?: unknown }
  if (typeof body.uuid !== 'string') throw new Error('Risk engine returned no screening id')
  return body.uuid
}

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
