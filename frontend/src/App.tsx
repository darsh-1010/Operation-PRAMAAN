import { useMemo, useState } from 'react'
import DecisionPanel from './components/DecisionPanel'
import KpiCard from './components/KpiCard'
import RecentCasesTable from './components/RecentCasesTable'
import Sidebar from './components/Sidebar'
import Topbar from './components/Topbar'
import UploadPanel from './components/UploadPanel'
import { generateRecentCases } from './mock'
import { runScreening } from './screening'
import type { ScreeningCase } from './types'

export default function App() {
  const [cases, setCases] = useState<ScreeningCase[]>(() => generateRecentCases(8))
  const [active, setActive] = useState<ScreeningCase | null>(null)
  const [loading, setLoading] = useState(false)

  const kpis = useMemo(() => {
    const total = cases.length
    const count = (d: ScreeningCase['decision']) => cases.filter((c) => c.decision === d).length
    return {
      total,
      accept: count('ACCEPT'),
      review: count('MANUAL_REVIEW'),
      reject: count('REJECT'),
    }
  }, [cases])

  async function handleRun() {
    setLoading(true)
    const result = await runScreening()
    setCases((prev) => [result, ...prev])
    setActive(result)
    setLoading(false)
  }

  return (
    <div className="flex min-h-screen bg-bg text-text">
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0">
        <Topbar />
        <main className="flex-1 px-6 py-6 space-y-6">
          <section id="kpis" className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <KpiCard label="Screenings today" value={String(kpis.total)} sublabel="live" tone="accent" />
            <KpiCard label="Accepted" value={String(kpis.accept)} sublabel="pass" tone="success" />
            <KpiCard label="Manual review" value={String(kpis.review)} sublabel="flagged" tone="warning" />
            <KpiCard label="Rejected" value={String(kpis.reject)} sublabel="hard fail" tone="danger" />
          </section>

          <section id="screen" className="grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] gap-6">
            <UploadPanel onRun={handleRun} loading={loading} />
            <DecisionPanel result={active} />
          </section>

          <section id="recent">
            <RecentCasesTable cases={cases} onSelect={setActive} />
          </section>
        </main>
      </div>
    </div>
  )
}
