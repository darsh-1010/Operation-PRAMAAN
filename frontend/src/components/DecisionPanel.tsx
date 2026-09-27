import type { ScreeningCase } from '../types'
import LedgerProof from './LedgerProof'
import ModuleResultCard from './ModuleResultCard'

const DECISION_STYLE = {
  ACCEPT: { bg: 'bg-success-dim', text: 'text-success', label: 'ACCEPT' },
  MANUAL_REVIEW: { bg: 'bg-warning-dim', text: 'text-warning', label: 'MANUAL REVIEW' },
  REJECT: { bg: 'bg-danger-dim', text: 'text-danger', label: 'REJECT' },
} as const

export default function DecisionPanel({ result }: { result: ScreeningCase | null }) {
  if (!result) {
    return (
      <div className="rounded-2xl border border-dashed border-border bg-surface p-8 text-center text-sm text-text-dim">
        Upload a document and click "Run screening" to see live OCR extraction, accuracy breakdown, and timing here.
      </div>
    )
  }

  const style = DECISION_STYLE[result.decision]

  return (
    <div className="rounded-2xl border border-border bg-surface p-5 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-mono bg-surface-2 px-2 py-0.5 rounded border border-border text-text-dim">{result.id}</span>
            <span className="text-xs text-text-dim font-medium">{result.documentType}</span>
            {result.latencyMs !== undefined && (
              <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-accent/10 text-accent border border-accent/20">
                ⏱ {result.latencyMs > 1000 ? `${(result.latencyMs / 1000).toFixed(2)}s` : `${result.latencyMs}ms`}
              </span>
            )}
          </div>
          <p className="text-base font-semibold text-text">{result.subjectName}</p>
        </div>
        <div className={`rounded-xl px-4 py-2 text-center ${style.bg}`}>
          <p className={`text-sm font-bold ${style.text}`}>{style.label}</p>
          <p className="text-[11px] text-text-dim">risk score {result.riskScore}</p>
        </div>
      </div>

      {result.reasonCodes && result.reasonCodes.length > 0 && (
        <div className="flex flex-wrap gap-1.5 items-center">
          <span className="text-xs text-text-dim font-medium mr-1">Signals:</span>
          {result.reasonCodes.map((code) => (
            <span key={code} className="text-[11px] font-mono px-2 py-0.5 rounded bg-surface-2 border border-border text-text-dim">
              {code}
            </span>
          ))}
        </div>
      )}

      {result.decision === 'REJECT' && result.modules.some((m) => m.hardFail) && (
        <div className="rounded-xl border border-danger/30 bg-danger-dim/30 p-3 flex items-start gap-2.5 text-xs text-danger">
          <svg viewBox="0 0 24 24" className="h-4 w-4 shrink-0 stroke-danger fill-none mt-0.5" strokeWidth={2}>
            <circle cx="12" cy="12" r="10" />
            <line x1="12" y1="8" x2="12" y2="12" />
            <line x1="12" y1="16" x2="12.01" y2="16" />
          </svg>
          <div className="leading-relaxed">
            <span className="font-bold">Hard Fail Triggered: </span>
            {result.reasonCodes?.includes('cross_document_mismatch')
              ? 'Multiple documents were uploaded for this identity screening, but key fields (such as Name, Date of Birth, or Gender) conflict between them. Review the sub-checks and extracted fields below.'
              : result.reasonCodes?.includes('MRZ_CHECKSUM_FAILED')
              ? 'Cryptographic MRZ check digits failed validation against the ICAO 9303 specification.'
              : result.reasonCodes?.some((r) => r.includes('WATCHLIST'))
              ? 'The document holder or document number matched an active security watchlist alert.'
              : 'A mandatory non-negotiable security check failed during document screening.'}
          </div>
        </div>
      )}

      <div className="grid gap-3 lg:grid-cols-3">
        {result.modules.map((m) => (
          <ModuleResultCard key={m.id} module={m} />
        ))}
      </div>

      {result.extractedFields && result.extractedFields.length > 0 && (
        <div className="rounded-xl border border-border bg-surface-2 p-4">
          <p className="text-xs font-semibold text-text mb-2.5 flex items-center justify-between">
            <span>OCR Extracted Identity Fields</span>
            <span className="text-[11px] font-normal text-text-dim">{result.extractedFields.length} fields recognized</span>
          </p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-2">
            {result.extractedFields.map((f, i) => (
              <div key={i} className="flex items-center justify-between p-2 rounded-lg bg-surface border border-border/50 text-xs">
                <div>
                  <p className="text-[10px] uppercase font-semibold text-text-dim tracking-wider">{f.field_key}</p>
                  <p className="font-medium text-text mt-0.5 truncate max-w-[170px]">{f.field_value}</p>
                </div>
                <div className="text-right shrink-0">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${f.source === 'MRZ' ? 'bg-success-dim text-success' : 'bg-surface-2 text-text-dim'}`}>
                    {f.source}
                  </span>
                  <p className="text-[10px] text-text-dim mt-0.5">{Math.round(f.confidence * 100)}%</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <LedgerProof key={result.id} uuid={result.id} />
    </div>
  )
}

