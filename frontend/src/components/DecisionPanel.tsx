import type { ScreeningCase } from '../types'
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
        Run a screening to see the per-module, per-check breakdown and the fused risk decision here.
      </div>
    )
  }

  const style = DECISION_STYLE[result.decision]

  return (
    <div className="rounded-2xl border border-border bg-surface p-5">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <div>
          <p className="text-xs text-text-dim">{result.id} · {result.documentType} · {result.checkpoint}</p>
          <p className="text-sm font-medium">{result.subjectName}</p>
        </div>
        <div className={`rounded-xl px-4 py-2 text-center ${style.bg}`}>
          <p className={`text-sm font-bold ${style.text}`}>{style.label}</p>
          <p className="text-[11px] text-text-dim">risk score {result.riskScore}</p>
        </div>
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        {result.modules.map((m) => (
          <ModuleResultCard key={m.id} module={m} />
        ))}
      </div>
    </div>
  )
}
