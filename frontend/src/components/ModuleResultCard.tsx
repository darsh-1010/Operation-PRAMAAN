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
      <ul className="mt-3 flex flex-wrap gap-1.5">
        {module.reasonCodes.map((code) => (
          <li key={code} className="text-[11px] text-text-dim bg-surface rounded-md px-2 py-1 border border-border">
            {code}
          </li>
        ))}
      </ul>
    </div>
  )
}
