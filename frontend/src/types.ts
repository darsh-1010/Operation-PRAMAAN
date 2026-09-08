export type ModuleId = 'ocr' | 'forensics' | 'biometric'

export interface ModuleResult {
  id: ModuleId
  label: string
  score: number // 0-100, higher = more trustworthy
  hardFail: boolean
  reasonCodes: string[]
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
