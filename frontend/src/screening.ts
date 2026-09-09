import { generateCase } from './mock'
import { buildScreeningPayload, dispatchToModules, type ModuleDispatchResult } from './lib/submitScreening'
import type { DocKey } from './lib/documents'
import type { ScreeningCase } from './types'

function isUnreachable(d: ModuleDispatchResult): d is ModuleDispatchResult & { reachable: false } {
  return !d.reachable
}

/**
 * Runs a screening: builds the uuid + documents_present + files payload and dispatches it
 * to all 3 module services in parallel (see submitScreening.ts). None of them have an
 * implementation yet, so every dispatch is expected to fail right now — that's logged, and
 * a mock result stands in so the dashboard stays usable. Swap the fallback for awaiting the
 * real module responses + risk-scoring-engine once those services exist.
 */
export async function runScreening(files: Partial<Record<DocKey, File>>): Promise<ScreeningCase> {
  const payload = buildScreeningPayload(files)
  const dispatch = await dispatchToModules(payload)

  // TODO once the services are actually implemented: fuse dispatch's real ModuleResponses
  // (API_CONTRACT.md) via risk-scoring-engine instead of falling back to a mock decision below.
  const unreachable = dispatch.filter(isUnreachable)
  if (dispatch.length === 0) {
    console.warn('No module service URLs configured (see .env.example) — using mock result.')
  } else if (unreachable.length) {
    console.warn(`Module services unreachable, using mock result: ${unreachable.map((d) => `${d.name} (${d.error})`).join(', ')}`)
  }

  await new Promise((resolve) => setTimeout(resolve, 1000)) // simulate pipeline latency for the demo
  return generateCase(payload.uuid)
}
