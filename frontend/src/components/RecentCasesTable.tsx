import type { ScreeningCase } from '../types'

const BADGE: Record<ScreeningCase['decision'], string> = {
  ACCEPT: 'bg-success-dim text-success',
  MANUAL_REVIEW: 'bg-warning-dim text-warning',
  REJECT: 'bg-danger-dim text-danger',
}

export default function RecentCasesTable({ cases, onSelect }: { cases: ScreeningCase[]; onSelect: (c: ScreeningCase) => void }) {
  return (
    <div className="rounded-2xl border border-border bg-surface overflow-hidden">
      <div className="px-5 py-4 border-b border-border">
        <p className="text-sm font-medium">Recent screenings</p>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-text-dim border-b border-border">
              <th className="px-5 py-2 font-medium">Case</th>
              <th className="px-5 py-2 font-medium">Document</th>
              <th className="px-5 py-2 font-medium">Checkpoint</th>
              <th className="px-5 py-2 font-medium">Risk</th>
              <th className="px-5 py-2 font-medium">Decision</th>
            </tr>
          </thead>
          <tbody>
            {cases.map((c) => (
              <tr
                key={c.id}
                onClick={() => onSelect(c)}
                className="border-b border-border last:border-0 cursor-pointer hover:bg-surface-2 transition-colors"
              >
                <td className="px-5 py-3 font-mono text-xs text-text-dim">{c.id}</td>
                <td className="px-5 py-3">{c.documentType}</td>
                <td className="px-5 py-3 text-text-dim">{c.checkpoint}</td>
                <td className="px-5 py-3 tabular-nums">{c.riskScore}</td>
                <td className="px-5 py-3">
                  <span className={`text-[10px] font-medium rounded-full px-2 py-0.5 ${BADGE[c.decision]}`}>
                    {c.decision.replace('_', ' ')}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
