import { decide, mockModule, randomCaseMeta } from './mock'
import { buildScreeningPayload, dispatchToModules, type ModuleDispatchResult, type ModuleResponse } from './lib/submitScreening'
import type { DocKey } from './lib/documents'
import type { ModuleResult, ScreeningCase, SubCheck } from './types'

function isUnreachable(d: ModuleDispatchResult): d is ModuleDispatchResult & { reachable: false } {
  return !d.reachable
}

const MODULE_ID_BY_SERVICE_NAME: Record<string, ModuleResult['id']> = {
  'ocr-consistency-check': 'ocr',
  'visual-image-forensics': 'forensics',
  'biometric-matching': 'biometric',
}

const MODULE_LABELS: Record<ModuleResult['id'], string> = {
  ocr: 'OCR, Extraction & Watchlist',
  forensics: 'Visual / Image Forensics',
  biometric: 'Biometric Matching',
}

/** Turns a module's real API_CONTRACT.md response into the dashboard's per-check shape.
 * The contract only carries score/hard_fail/reason_codes — no sub-check breakdown — so each
 * reason code becomes one failed row, or a single passed row when there are none. */
function moduleFromResponse(id: ModuleResult['id'], response: ModuleResponse): ModuleResult {
  const subChecks: SubCheck[] = response.reason_codes.length
    ? response.reason_codes.map((code) => ({ label: code, score: response.score, passed: false, reason: code }))
    : [{ label: 'All checks passed', score: response.score, passed: true }]
  return { id, label: MODULE_LABELS[id], score: response.score, hardFail: response.hard_fail, subChecks }
}

/**
 * Runs a screening: builds the uuid + documents_present + files payload and dispatches it
 * to all 3 module services in parallel (see submitScreening.ts). A module that responds
 * (matching API_CONTRACT.md's shape) contributes its real score/hard_fail/reason_codes to
 * the result; a module that's unreachable or not yet implemented falls back to a mocked
 * result for that module only, so the dashboard stays usable during rollout.
 */
export async function runScreening(files: Partial<Record<DocKey, File>>): Promise<ScreeningCase> {
  const payload = buildScreeningPayload(files)
  const dispatch = await dispatchToModules(payload)

  const unreachable = dispatch.filter(isUnreachable)
  if (dispatch.length === 0) {
    console.warn('No module service URLs configured (see .env.example) — using mock result.')
  } else if (unreachable.length) {
    console.warn(`Module services unreachable, mocking their result: ${unreachable.map((d) => `${d.name} (${d.error})`).join(', ')}`)
  }

  const modules = (Object.keys(MODULE_LABELS) as ModuleResult['id'][]).map((id) => {
    const found = dispatch.find((d) => MODULE_ID_BY_SERVICE_NAME[d.name] === id)
    return found && found.reachable ? moduleFromResponse(id, found.response) : mockModule(id)
  })

  const { decision, riskScore } = decide(modules)
  return { id: payload.uuid, ...randomCaseMeta(), timestamp: new Date().toISOString(), riskScore, decision, modules }
}
