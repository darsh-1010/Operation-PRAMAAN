import { useMemo, useState } from 'react'
import DecisionPanel from '../components/DecisionPanel'
import KpiCard from '../components/KpiCard'
import Modal from '../components/Modal'
import RecentCasesTable, { type UserRow } from '../components/RecentCasesTable'
import type { ScreeningCase } from '../types'

export default function StatisticsTab({ cases }: { cases: ScreeningCase[] }) {
  const [selected, setSelected] = useState<ScreeningCase | null>(null)

  const kpis = useMemo(() => {
    const count = (d: ScreeningCase['decision']) => cases.filter((c) => c.decision === d).length
    return { total: cases.length, accept: count('ACCEPT'), review: count('MANUAL_REVIEW'), reject: count('REJECT') }
  }, [cases])

  // cases is newest-first, so the first occurrence of a name is that person's latest screening.
  const userRows = useMemo<UserRow[]>(() => {
    const seen = new Map<string, UserRow>()
    for (const c of cases) {
      const row = seen.get(c.subjectName)
      if (row) row.screeningCount += 1
      else seen.set(c.subjectName, { case: c, screeningCount: 1 })
    }
    return [...seen.values()]
  }, [cases])

  return (
    <div className="space-y-6">
      <section className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard label="Screenings today" value={String(kpis.total)} sublabel="live" tone="accent" />
        <KpiCard label="Accepted" value={String(kpis.accept)} sublabel="pass" tone="success" />
        <KpiCard label="Manual review" value={String(kpis.review)} sublabel="flagged" tone="warning" />
        <KpiCard label="Rejected" value={String(kpis.reject)} sublabel="hard fail" tone="danger" />
      </section>

      <RecentCasesTable rows={userRows} onSelect={setSelected} />

      {selected && (
        <Modal onClose={() => setSelected(null)}>
          <DecisionPanel result={selected} />
        </Modal>
      )}
    </div>
  )
}
