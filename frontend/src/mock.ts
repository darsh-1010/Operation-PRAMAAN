import type { Decision, ModuleResult, SubCheck, ScreeningCase } from './types'

const NAMES = ['A. Sharma', 'R. Verma', 'S. Khan', 'P. Nair', 'J. Singh', 'M. Iyer', 'T. Das']
const DOC_TYPES = ['Passport', 'Visa', 'National ID', 'Driving Licence', 'Permit']
const CHECKPOINTS = ['Attari ICP', 'Petrapole LCS', 'Moreh ICP', 'IGI Airport T3']

interface CheckSpec {
  label: string
  critical?: boolean // failing this check alone triggers the module's hard_fail
  failReason: string
}

// Sub-checks per module, from the README's module breakdown.
const OCR_CHECKS: CheckSpec[] = [
  { label: 'MRZ / general OCR', failReason: 'Low-confidence OCR read' },
  { label: 'Barcode / QR decode', failReason: 'Barcode unreadable or malformed' },
  { label: 'MRZ checksum & field format', failReason: 'Checksum or field-format mismatch' },
  { label: 'Blacklist / watchlist match', critical: true, failReason: 'Fuzzy match against a watchlist entry' },
  { label: 'Cross-document field matcher', failReason: 'Fields disagree across submitted documents' },
  { label: 'Base marker verifier', failReason: 'Expected base/security marker not found' },
]
const FORENSICS_CHECKS: CheckSpec[] = [
  { label: 'AI-generated image detector', critical: true, failReason: 'AI-image confidence exceeded 99%' },
  { label: 'Splice / tamper forensics', failReason: 'Splice artifacts detected around photo or text' },
  { label: 'Guilloché / background checker', failReason: 'Guilloché pattern discontinuity' },
]
const BIOMETRIC_CHECKS: CheckSpec[] = [
  { label: 'Liveness detection', critical: true, failReason: 'Liveness check failed' },
  { label: 'Doc-to-selfie face matcher', failReason: 'Selfie does not match document photo' },
  { label: 'Cross-document face consistency', failReason: 'Face differs across submitted documents' },
]

function pick<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)]
}

function randomScore(biasHigh: boolean) {
  const base = biasHigh ? 85 : 35
  const spread = biasHigh ? 30 : 40
  return Math.max(0, Math.min(100, Math.round(base + (Math.random() - 0.5) * spread)))
}

// Critical (hard_fail-eligible) checks pass the vast majority of the time — a watchlist
// hit or a failed liveness check is meant to be a rare event, not a coin flip.
function buildSubCheck(spec: CheckSpec): SubCheck {
  const highChance = spec.critical ? 0.95 : 0.85
  const score = randomScore(Math.random() < highChance)
  const passed = score >= 60
  return { label: spec.label, score, passed, reason: passed ? undefined : spec.failReason }
}

function buildModule(id: ModuleResult['id'], label: string, checks: CheckSpec[]): ModuleResult {
  const subChecks = checks.map(buildSubCheck)
  const score = Math.round(subChecks.reduce((s, c) => s + c.score, 0) / subChecks.length)
  const hardFail = checks.some((spec, i) => spec.critical && !subChecks[i].passed)
  return { id, label, score, hardFail, subChecks }
}

function decide(modules: ModuleResult[]): { decision: Decision; riskScore: number } {
  const anyHardFail = modules.some((m) => m.hardFail)
  const riskScore = Math.round(modules.reduce((s, m) => s + m.score, 0) / modules.length)
  if (anyHardFail) return { decision: 'REJECT', riskScore }
  if (riskScore < 60) return { decision: 'MANUAL_REVIEW', riskScore }
  return { decision: 'ACCEPT', riskScore }
}

export function generateCase(id?: string): ScreeningCase {
  const modules: ModuleResult[] = [
    buildModule('ocr', 'OCR, Extraction & Watchlist', OCR_CHECKS),
    buildModule('forensics', 'Visual / Image Forensics', FORENSICS_CHECKS),
    buildModule('biometric', 'Biometric Matching', BIOMETRIC_CHECKS),
  ]
  const { decision, riskScore } = decide(modules)
  return {
    id: id ?? `PRM-${Math.floor(100000 + Math.random() * 900000)}`,
    subjectName: pick(NAMES),
    documentType: pick(DOC_TYPES),
    checkpoint: pick(CHECKPOINTS),
    timestamp: new Date().toISOString(),
    riskScore,
    decision,
    modules,
  }
}

export function generateRecentCases(count: number): ScreeningCase[] {
  return Array.from({ length: count }, generateCase).sort((a, b) => b.timestamp.localeCompare(a.timestamp))
}
