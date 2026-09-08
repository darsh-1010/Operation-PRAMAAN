import type { ModuleResult } from '../types'
import ScoreBar from './ScoreBar'

export default function ModuleResultCard({ module }: { module: ModuleResult }) {
  return (
    <div className="rounded-xl border border-border bg-surface-2 p-4">
      <div className="flex items-center justify-between mb-2">
        <p className="text-sm font-medium">{module.label}</p>
        {module.hardFail && (
          <span className="text-[10px] font-medium rounded-full bg-danger-dim text-danger px-2 py-0.5">HARD FAIL</span>
        )}
      </div>
      <ScoreBar score={module.score} />

      <ul className="mt-3 space-y-2">
        {module.subChecks.map((check) => (
          <li key={check.label} className="flex items-start gap-2">
            {check.passed ? (
              <svg viewBox="0 0 24 24" className="mt-0.5 h-3.5 w-3.5 shrink-0 stroke-success fill-none" strokeWidth={2.5}>
                <path d="m5 13 4 4L19 7" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            ) : (
              <svg viewBox="0 0 24 24" className="mt-0.5 h-3.5 w-3.5 shrink-0 stroke-danger fill-none" strokeWidth={2.5}>
                <path d="M6 6l12 12M18 6 6 18" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            )}
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2">
                <span className="text-xs">{check.label}</span>
                <span className="text-[11px] tabular-nums text-text-dim shrink-0">{check.score}</span>
              </div>
              {!check.passed && <p className="text-[11px] text-danger mt-0.5">{check.reason}</p>}
            </div>
          </li>
        ))}
      </ul>
    </div>
  )
}
