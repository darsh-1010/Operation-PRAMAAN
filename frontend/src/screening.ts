import { generateCase } from './mock'
import { buildScreeningPayload, dispatchToModules } from './lib/submitScreening'
import type { DocKey } from './lib/documents'
import type { ScreeningCase } from './types'

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

  // TODO once the services define a response contract: parse dispatch's real responses
  // instead of falling back to a mock decision below.
  const unreachable = dispatch.filter((d) => !d.reachable)
  if (dispatch.length === 0) {
    console.warn('No module service URLs configured (see .env.example) — using mock result.')
  } else if (unreachable.length) {
    console.warn(`Module services unreachable, using mock result: ${unreachable.map((d) => `${d.name} (${d.error})`).join(', ')}`)
  }

  await new Promise((resolve) => setTimeout(resolve, 1000)) // simulate pipeline latency for the demo
  return generateCase(payload.uuid)
}
