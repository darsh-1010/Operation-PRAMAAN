import type { Decision, ModuleResult, ScreeningCase } from './types'

const NAMES = ['A. Sharma', 'R. Verma', 'S. Khan', 'P. Nair', 'J. Singh', 'M. Iyer', 'T. Das']
const DOC_TYPES = ['Passport', 'Visa', 'National ID', 'Driving Licence', 'Permit']
const CHECKPOINTS = ['Attari ICP', 'Petrapole LCS', 'Moreh ICP', 'IGI Airport T3']

const OCR_REASONS = ['MRZ checksum valid', 'Barcode decoded', 'Field format OK']
const OCR_FAIL_REASONS = ['MRZ checksum mismatch', 'Watchlist fuzzy match', 'Cross-doc field mismatch']
const FORENSICS_REASONS = ['No splice artifacts', 'Guilloché pattern intact']
const FORENSICS_FAIL_REASONS = ['AI-generated image signature', 'Stamp forgery suspected', 'Metadata anomaly']
const BIOMETRIC_REASONS = ['Liveness confirmed', 'Face match above threshold']
const BIOMETRIC_FAIL_REASONS = ['Liveness check failed', 'Doc-to-selfie mismatch']

function pick<T>(arr: T[]): T {
  return arr[Math.floor(Math.random() * arr.length)]
}

function randomScore(biasHigh: boolean) {
  const base = biasHigh ? 70 : 30
  return Math.max(0, Math.min(100, Math.round(base + (Math.random() - 0.5) * 60)))
}

function buildModule(id: ModuleResult['id'], label: string, okReasons: string[], failReasons: string[]): ModuleResult {
  const score = randomScore(Math.random() > 0.2)
  const hardFail = score < 35 && Math.random() > 0.5
  return {
    id,
    label,
    score,
    hardFail,
    reasonCodes: hardFail ? [pick(failReasons), pick(failReasons)] : [pick(okReasons)],
  }
}

function decide(modules: ModuleResult[]): { decision: Decision; riskScore: number } {
  const anyHardFail = modules.some((m) => m.hardFail)
  const riskScore = Math.round(modules.reduce((s, m) => s + m.score, 0) / modules.length)
  if (anyHardFail) return { decision: 'REJECT', riskScore }
  if (riskScore < 60) return { decision: 'MANUAL_REVIEW', riskScore }
  return { decision: 'ACCEPT', riskScore }
}

export function generateCase(): ScreeningCase {
  const modules: ModuleResult[] = [
    buildModule('ocr', 'OCR, Extraction & Watchlist', OCR_REASONS, OCR_FAIL_REASONS),
    buildModule('forensics', 'Visual / Image Forensics', FORENSICS_REASONS, FORENSICS_FAIL_REASONS),
    buildModule('biometric', 'Biometric Matching', BIOMETRIC_REASONS, BIOMETRIC_FAIL_REASONS),
  ]
  const { decision, riskScore } = decide(modules)
  return {
    id: `PRM-${Math.floor(100000 + Math.random() * 900000)}`,
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
