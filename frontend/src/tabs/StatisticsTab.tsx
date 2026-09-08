import { useMemo } from 'react'
import KpiCard from '../components/KpiCard'
import RecentCasesTable from '../components/RecentCasesTable'
import type { ScreeningCase } from '../types'

export default function StatisticsTab({ cases, onSelect }: { cases: ScreeningCase[]; onSelect: (c: ScreeningCase) => void }) {
  const kpis = useMemo(() => {
    const count = (d: ScreeningCase['decision']) => cases.filter((c) => c.decision === d).length
    return { total: cases.length, accept: count('ACCEPT'), review: count('MANUAL_REVIEW'), reject: count('REJECT') }
  }, [cases])

  return (
    <div className="space-y-6">
      <section className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard label="Screenings today" value={String(kpis.total)} sublabel="live" tone="accent" />
        <KpiCard label="Accepted" value={String(kpis.accept)} sublabel="pass" tone="success" />
        <KpiCard label="Manual review" value={String(kpis.review)} sublabel="flagged" tone="warning" />
        <KpiCard label="Rejected" value={String(kpis.reject)} sublabel="hard fail" tone="danger" />
      </section>

      <RecentCasesTable cases={cases} onSelect={onSelect} />
    </div>
  )
}
