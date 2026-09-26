import { generateCase } from './mock'
import { buildScreeningPayload, dispatchToModules, type ModuleDispatchResult } from './lib/submitScreening'
import { buildLiveCase } from './lib/buildLiveCase'
import { createSession, pollRiskResult } from './lib/riskEngine'
import type { DocKey } from './lib/documents'
import type { ScreeningCase } from './types'

function isUnreachable(d: ModuleDispatchResult): d is ModuleDispatchResult & { reachable: false } {
  return !d.reachable
}

/**
 * Runs a screening: builds the uuid + documents_present + files payload, dispatches it to
 * all 3 module services in parallel, and turns their real responses into a ScreeningCase —
 * see lib/buildLiveCase.ts for how the modules' scores are fused into one decision.
 *
 * Only falls back to a fabricated demo case when no module URLs are configured at all (a
 * fresh checkout with no .env yet) — a real submission that reaches at least one module
 * always renders that module's real result rather than a mock.
 */
export async function runScreening(files: Partial<Record<DocKey, File>>): Promise<ScreeningCase> {
  if (!import.meta.env.VITE_OCR_SERVICE_URL && !import.meta.env.VITE_FORENSICS_SERVICE_URL && !import.meta.env.VITE_BIOMETRIC_SERVICE_URL) {
    console.warn('No module service URLs configured (see .env.example) — using mock result.')
    await new Promise((resolve) => setTimeout(resolve, 1000))
    return generateCase(crypto.randomUUID())
  }

  const payload = buildScreeningPayload(files, await createSession())
  const dispatch = await dispatchToModules(payload)

  const unreachable = dispatch.filter(isUnreachable)
  if (unreachable.length) {
    console.warn(`Module services unreachable: ${unreachable.map((d) => `${d.name} (${d.error})`).join(', ')}`)
  }

  const riskResult = await pollRiskResult(payload.uuid)
  return buildLiveCase(payload, dispatch, riskResult)
}
