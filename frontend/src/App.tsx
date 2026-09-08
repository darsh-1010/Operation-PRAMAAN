import { useState } from 'react'
import Sidebar, { type Tab } from './components/Sidebar'
import Topbar from './components/Topbar'
import { generateRecentCases } from './mock'
import { runScreening } from './screening'
import StatisticsTab from './tabs/StatisticsTab'
import NewScreeningTab from './tabs/NewScreeningTab'
import { useTheme } from './theme'
import type { ScreeningCase } from './types'

const TAB_COPY: Record<Tab, { title: string; subtitle: string }> = {
  stats: { title: 'Statistics', subtitle: 'Live risk assessment across all checkpoints' },
  screening: { title: 'New Screening', subtitle: 'Upload documents and biometrics to run a check' },
}

export default function App() {
  const { theme, toggle } = useTheme()
  const [tab, setTab] = useState<Tab>('stats')
  const [menuOpen, setMenuOpen] = useState(false)
  const [cases, setCases] = useState<ScreeningCase[]>(() => generateRecentCases(8))
  const [active, setActive] = useState<ScreeningCase | null>(null)
  const [loading, setLoading] = useState(false)

  async function handleRun() {
    setLoading(true)
    const result = await runScreening()
    setCases((prev) => [result, ...prev])
    setActive(result)
    setLoading(false)
  }

  function handleSelectCase(c: ScreeningCase) {
    setActive(c)
    setTab('screening')
  }

  const copy = TAB_COPY[tab]

  return (
    <div className="flex min-h-screen bg-bg text-text">
      <Sidebar active={tab} onSelect={setTab} open={menuOpen} onClose={() => setMenuOpen(false)} />
      <div className="flex-1 flex flex-col min-w-0">
        <Topbar title={copy.title} subtitle={copy.subtitle} theme={theme} onToggleTheme={toggle} onOpenMenu={() => setMenuOpen(true)} />
        <main className="flex-1 px-4 sm:px-6 py-6">
          {tab === 'stats' ? (
            <StatisticsTab cases={cases} onSelect={handleSelectCase} />
          ) : (
            <NewScreeningTab onRun={handleRun} loading={loading} result={active} />
          )}
        </main>
      </div>
    </div>
  )
}
