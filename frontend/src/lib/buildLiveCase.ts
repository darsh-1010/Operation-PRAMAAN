import { DOCUMENT_SLOTS, ALL_KEYS } from './documents'
import type { ModuleDispatchResult, ScreeningPayload } from './submitScreening'
import type { RiskResult } from './riskEngine'
import type { Decision, ModuleResult, ScreeningCase, SubCheck } from '../types'

const DOC_LABELS: Record<string, string> = {
  ...Object.fromEntries(DOCUMENT_SLOTS.map((s) => [s.key, s.label])),
  selfie: 'Selfie',
}

const MODULE_META: Record<string, { id: ModuleResult['id']; label: string }> = {
  'ocr-consistency-check': { id: 'ocr', label: 'OCR, Extraction & Watchlist' },
  'visual-image-forensics': { id: 'forensics', label: 'Visual / Image Forensics' },
  'biometric-matching': { id: 'biometric', label: 'Biometric Matching' },
}

// Same weights/bands as services/risk-scoring-engine/scoring.py — duplicated rather than
// imported (separate services per CLAUDE.md's cross-service-contract-not-imports rule) so the
// frontend can still produce a decision when the risk engine hasn't finalized one yet.
const WEIGHTS: Record<ModuleResult['id'], number> = { ocr: 0.25, forensics: 0.4, biometric: 0.35 }

function isUnreachable(d: ModuleDispatchResult): d is ModuleDispatchResult & { reachable: false; error: string } {
  return !d.reachable
}

function unreachable(meta: { id: ModuleResult['id']; label: string }, reason: string): ModuleResult {
  return { id: meta.id, label: meta.label, score: 0, hardFail: false, subChecks: [{ label: 'Service unreachable', score: 0, passed: false, reason }] }
}

function toModuleResult(name: string, dispatch: ModuleDispatchResult | undefined): ModuleResult {
  const meta = MODULE_META[name]
  if (!dispatch) return unreachable(meta, 'No service URL configured (see .env.example)')
  if (isUnreachable(dispatch)) return unreachable(meta, dispatch.error)

  const { score, hard_fail, reason_codes, review_required } = dispatch.response
  const codes = reason_codes.length ? reason_codes : ['no reason codes returned']
  // ponytail: real modules return a flat reason_codes list, not per-check pass/fail — every
  // code is shown against the module's one verdict rather than guessed apart into sub-checks.
  const subChecks: SubCheck[] = codes.map((code) => ({ label: code, score: score ?? 0, passed: !hard_fail && score !== null, reason: hard_fail || score === null ? code : undefined }))
  return { id: meta.id, label: meta.label, score: score ?? 0, hardFail: hard_fail, subChecks, notAssessed: score === null, reviewRequired: Boolean(review_required) }
}

/** Fuses the 3 modules' scores the same way risk-scoring-engine does (scoring.py: decide), for
 * when its own fused result isn't available yet. Any hard_fail, any module we couldn't reach, a
 * module that assessed nothing, or one demanding review forces a conservative call — never ACCEPT. */
function fuseClientSide(dispatch: ModuleDispatchResult[], modules: ModuleResult[]): { decision: Decision; riskScore: number } {
  const anyHardFail = modules.some((m) => m.hardFail)
  const anyUnreachable = dispatch.some((d) => !d.reachable)
  const assessed = modules.filter((m) => !m.notAssessed)
  const totalWeight = assessed.reduce((sum, m) => sum + WEIGHTS[m.id], 0)
  // Renormalized over the modules that actually assessed something, like the risk engine.
  const riskScore = totalWeight ? Math.round(assessed.reduce((sum, m) => sum + WEIGHTS[m.id] * m.score, 0) / totalWeight) : 0

  if (anyHardFail) return { decision: 'REJECT', riskScore }
  if (anyUnreachable) return { decision: 'MANUAL_REVIEW', riskScore }
  const mustReview = modules.some((m) => m.notAssessed || m.reviewRequired)
  if (riskScore >= 80) return { decision: mustReview ? 'MANUAL_REVIEW' : 'ACCEPT', riskScore }
  if (riskScore >= 40) return { decision: 'MANUAL_REVIEW', riskScore }
  return { decision: 'REJECT', riskScore }
}

function decisionFromRiskEngine(d: RiskResult['decision']): Decision {
  if (d === 'PASS') return 'ACCEPT'
  if (d === 'MANUAL_REVIEW') return 'MANUAL_REVIEW'
  return 'REJECT' // FAIL or REJECTED
}

/** Builds a ScreeningCase entirely from real data: the 3 modules' actual /screen responses,
 * fused by risk-scoring-engine's own decision when it resolved in time, else fused the same
 * way client-side (see fuseClientSide). No random name/checkpoint — those don't exist in the
 * real contract, so the case says plainly that this is a live submission instead of inventing
 * demo-style detail. */
export function buildLiveCase(payload: ScreeningPayload, dispatch: ModuleDispatchResult[], riskResult: RiskResult | null): ScreeningCase {
  const modules = Object.keys(MODULE_META).map((name) => toModuleResult(name, dispatch.find((d) => d.name === name)))

  const { decision, riskScore } =
    riskResult && riskResult.score !== null
      ? { decision: decisionFromRiskEngine(riskResult.decision), riskScore: Math.round(riskResult.score) }
      : fuseClientSide(dispatch, modules)

  const presentDocs = ALL_KEYS.filter((k) => payload.files[k]).map((k) => DOC_LABELS[k])

  return {
    id: payload.uuid,
    subjectName: `Live submission (${payload.uuid.slice(0, 8)})`,
    documentType: presentDocs.join(' + ') || 'No documents',
    checkpoint: '—',
    timestamp: new Date().toISOString(),
    riskScore,
    decision,
    modules,
  }
}
