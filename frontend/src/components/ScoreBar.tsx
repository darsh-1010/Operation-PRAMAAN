export default function ScoreBar({ score }: { score: number }) {
  const color = score >= 60 ? 'bg-success' : score >= 35 ? 'bg-warning' : 'bg-danger'
  return (
    <div className="flex items-center gap-3">
      <div className="h-1.5 flex-1 rounded-full bg-surface-2 overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${score}%` }} />
      </div>
      <span className="w-8 text-right text-xs tabular-nums text-text-dim">{score}</span>
    </div>
  )
}
