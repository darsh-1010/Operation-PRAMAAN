export type ModuleId = 'ocr' | 'forensics' | 'biometric'

export interface SubCheck {
  label: string
  score: number // 0-100
  passed: boolean
  reason?: string // present when !passed — why this specific check failed
}

export interface ModuleResult {
  id: ModuleId
  label: string
  score: number // 0-100, average of subChecks
  hardFail: boolean
  subChecks: SubCheck[]
}

export type Decision = 'ACCEPT' | 'MANUAL_REVIEW' | 'REJECT'

export interface ScreeningCase {
  id: string
  subjectName: string
  documentType: string
  checkpoint: string
  timestamp: string
  riskScore: number
  decision: Decision
  modules: ModuleResult[]
}
