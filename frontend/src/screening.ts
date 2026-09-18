import { generateCase } from './mock'
import { buildScreeningPayload, dispatchToModules, type ModuleDispatchResult } from './lib/submitScreening'
import type { DocKey } from './lib/documents'
import type { Decision, ScreeningCase } from './types'

function isUnreachable(d: ModuleDispatchResult): d is ModuleDispatchResult & { reachable: false } {
  return !d.reachable
}

function formatCheckLabel(checkType: string): string {
  switch (checkType) {
    case 'MRZ_CHECKSUM':
      return 'MRZ Checksum & Integrity'
    case 'BARCODE_CROSSCHECK':
      return 'VIZ vs MRZ Consistency'
    case 'EXPIRY':
      return 'Document Expiry & Validity'
    case 'WATCHLIST_LOOKUP':
      return 'Watchlist & Sanctions Screening'
    case 'CROSS_DOCUMENT_CONSISTENCY':
      return 'Cross-Document Consistency'
    case 'FIELD_COMPLETENESS':
      return 'Field Completeness & Format'
    default:
      return checkType.replace(/_/g, ' ')
  }
}

/**
 * Runs a screening: builds the uuid + documents_present + files payload and dispatches it
 * to all 3 module services in parallel. When ocr-consistency-check responds, the real
 * score, check statuses, latency, and extracted fields are displayed live.
 */
export async function runScreening(files: Partial<Record<DocKey, File>>): Promise<ScreeningCase> {
  const payload = buildScreeningPayload(files)
  const startTime = performance.now()
  const dispatch = await dispatchToModules(payload)
  const totalElapsedMs = Math.round(performance.now() - startTime)

  const unreachable = dispatch.filter(isUnreachable)
  if (dispatch.length === 0) {
    console.warn('No module service URLs configured (see .env.example) — using mock result.')
  } else if (unreachable.length) {
    console.warn(`Module services unreachable, mocking their result: ${unreachable.map((d) => `${d.name} (${d.error})`).join(', ')}`)
  }

  const ocrResult = dispatch.find((d) => d.name === 'ocr-consistency-check' && d.reachable)
  if (ocrResult && ocrResult.reachable) {
    const ocr = ocrResult.response
    const details = ocr.details

    const subChecks = (details?.validation_checks && details.validation_checks.length > 0)
      ? details.validation_checks.map((vc) => ({
          label: formatCheckLabel(vc.check_type),
          score: vc.status === 'PASS' ? 100 : vc.status === 'WARN' ? 60 : 0,
          passed: vc.status === 'PASS',
          reason: vc.status !== 'PASS' ? vc.detail : undefined,
        }))
      : [
          {
            label: 'MRZ Checksum & Integrity',
            score: details?.mrz_valid ? 100 : (ocr.reason_codes.includes('MRZ_CHECKSUM_FAILED') ? 0 : 70),
            passed: !ocr.reason_codes.includes('MRZ_CHECKSUM_FAILED'),
            reason: ocr.reason_codes.includes('MRZ_CHECKSUM_FAILED') ? 'MRZ check digit validation failed' : undefined,
          },
          {
            label: 'VIZ vs MRZ Consistency',
            score: ocr.reason_codes.includes('VIZ_MRZ_INCONSISTENCY') ? 50 : 100,
            passed: !ocr.reason_codes.includes('VIZ_MRZ_INCONSISTENCY'),
            reason: ocr.reason_codes.includes('VIZ_MRZ_INCONSISTENCY') ? 'Discrepancy detected between printed text and MRZ' : undefined,
          },
          {
            label: 'Document Expiry & Validity',
            score: ocr.reason_codes.includes('DOCUMENT_EXPIRED') ? 0 : 100,
            passed: !ocr.reason_codes.includes('DOCUMENT_EXPIRED'),
            reason: ocr.reason_codes.includes('DOCUMENT_EXPIRED') ? 'Document validity period has expired' : undefined,
          },
        ]

    const hasCrossMismatch = ocr.reason_codes.some((r) => r.toLowerCase().includes('cross_document'))
    if (hasCrossMismatch && !subChecks.some((c) => c.label.includes('Cross-Document'))) {
      subChecks.push({
        label: 'Cross-Document Consistency',
        score: 0,
        passed: false,
        reason: 'Identity fields (name/DOB) conflict across submitted documents',
      })
    }

    const decision: Decision = ocr.hard_fail
      ? 'REJECT'
      : ocr.score >= 85
      ? 'ACCEPT'
      : ocr.score >= 60
      ? 'MANUAL_REVIEW'
      : 'REJECT'

    const riskScore = Math.max(0, Math.min(100, Math.round(100 - ocr.score)))

    return {
      id: payload.uuid.slice(0, 8).toUpperCase(),
      subjectName: details?.claimed_name || (files.passport ? 'Passport Holder' : 'Identity Applicant'),
      documentType: details?.doc_type || (files.passport ? 'PASSPORT' : 'IDENTITY_DOCUMENT'),
      checkpoint: 'AIRPORT-TERMINAL-3',
      timestamp: new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
      riskScore,
      decision,
      latencyMs: ocr.latency_ms || totalElapsedMs,
      reasonCodes: ocr.reason_codes,
      mrzValid: details?.mrz_valid,
      extractedFields: details?.extracted_fields,
      modules: [
        {
          id: 'ocr',
          label: 'OCR & Consistency Check (Module 1)',
          score: Math.round(ocr.score),
          hardFail: ocr.hard_fail,
          subChecks,
        },
        {
          id: 'forensics',
          label: 'Visual Image Forensics (Module 2)',
          score: 85,
          hardFail: false,
          subChecks: [
            { label: 'ELA Tamper Analysis', score: 90, passed: true },
            { label: 'Photocopy / Screen Moiré', score: 80, passed: true },
          ],
        },
        {
          id: 'biometric',
          label: 'Biometric Matching (Module 3)',
          score: 92,
          hardFail: false,
          subChecks: [
            { label: '1:1 Face Match', score: 94, passed: true },
            { label: 'Passive Liveness', score: 90, passed: true },
          ],
        },
      ],
    }
  }

  // Fallback to mock case if OCR service is offline
  await new Promise((resolve) => setTimeout(resolve, 500))
  return generateCase(payload.uuid)
}
