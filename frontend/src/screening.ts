import { generateCase } from './mock'
import type { ScreeningCase } from './types'

/**
 * Runs a screening for the given inputs and returns the fused result.
 *
 * The 4 backend services (see .env.example: VITE_OCR_SERVICE_URL,
 * VITE_FORENSICS_SERVICE_URL, VITE_BIOMETRIC_SERVICE_URL, VITE_RISK_SERVICE_URL)
 * have no implementation yet, so this simulates the pipeline latency and returns
 * mock data. Swap the body for parallel fetch() calls to the 3 module services
 * + risk-scoring-engine once they exist — the ScreeningCase shape already matches
 * the README's module contract (score, hard_fail, reason codes).
 */
export async function runScreening(): Promise<ScreeningCase> {
  await new Promise((resolve) => setTimeout(resolve, 1400))
  return generateCase()
}
