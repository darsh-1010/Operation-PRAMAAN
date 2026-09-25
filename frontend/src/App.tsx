import { useState } from 'react'
import Sidebar, { type Tab } from './components/Sidebar'
import Topbar from './components/Topbar'
import type { DocKey } from './lib/documents'
import { generateRecentCases } from './mock'
import { runScreening } from './screening'
import StatisticsTab from './tabs/StatisticsTab'
import NewScreeningTab from './tabs/NewScreeningTab'
import LedgerTab from './tabs/LedgerTab'
import { useTheme } from './theme'
import type { ScreeningCase } from './types'

const TAB_COPY: Record<Tab, { title: string; subtitle: string }> = {
  stats: { title: 'Statistics', subtitle: 'Live risk assessment across all checkpoints' },
  screening: { title: 'New Screening', subtitle: 'Upload documents and biometrics to run a check' },
  ledger: { title: 'Blockchain Ledger', subtitle: 'Tamper-evident audit trail of every screening decision' },
}

export default function App() {
  const { theme, toggle } = useTheme()
  const [tab, setTab] = useState<Tab>('stats')
  const [menuOpen, setMenuOpen] = useState(false)
  const [cases, setCases] = useState<ScreeningCase[]>(() => generateRecentCases(8))
  const [active, setActive] = useState<ScreeningCase | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleRun(files: Partial<Record<DocKey, File>>) {
    setLoading(true)
    setError(null)
    try {
      const result = await runScreening(files)
      setCases((prev) => [result, ...prev])
      setActive(result)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setLoading(false)
    }
  }

  const copy = TAB_COPY[tab]

  return (
    <div className="flex min-h-screen bg-bg text-text">
      <Sidebar active={tab} onSelect={setTab} open={menuOpen} onClose={() => setMenuOpen(false)} />
      <div className="flex-1 flex flex-col min-w-0">
        <Topbar title={copy.title} subtitle={copy.subtitle} theme={theme} onToggleTheme={toggle} onOpenMenu={() => setMenuOpen(true)} />
        <main className="flex-1 px-4 sm:px-6 py-6">
          {error && (
            <div role="alert" className="mb-4 rounded-xl border border-danger/30 bg-danger-dim px-4 py-2.5 text-sm text-danger">
              Screening could not run: {error}
            </div>
          )}
          {tab === 'stats' ? (
            <StatisticsTab cases={cases} />
          ) : tab === 'ledger' ? (
            <LedgerTab />
          ) : (
            <NewScreeningTab onRun={handleRun} loading={loading} result={active} onBack={() => setTab('stats')} />
          )}
        </main>
      </div>
    </div>
  )
}
