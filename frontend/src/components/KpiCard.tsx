interface Props {
  label: string
  value: string
  sublabel: string
  tone?: 'accent' | 'success' | 'warning' | 'danger'
}

const TONE_BG: Record<string, string> = {
  accent: 'bg-accent-dim text-accent',
  success: 'bg-success-dim text-success',
  warning: 'bg-warning-dim text-warning',
  danger: 'bg-danger-dim text-danger',
}

export default function KpiCard({ label, value, sublabel, tone = 'accent' }: Props) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-5">
      <div className="flex items-center justify-between">
        <p className="text-sm text-text-dim">{label}</p>
        <span className={`text-[10px] font-medium rounded-full px-2 py-0.5 ${TONE_BG[tone]}`}>{sublabel}</span>
      </div>
      <p className="mt-3 text-3xl font-semibold tracking-tight">{value}</p>
    </div>
  )
}
