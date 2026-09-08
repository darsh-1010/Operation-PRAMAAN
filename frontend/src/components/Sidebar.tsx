const NAV_ITEMS = [
  { href: '#kpis', label: 'Dashboard', icon: 'M4 13h6V4H4v9Zm0 7h6v-5H4v5Zm10 0h6V11h-6v9Zm0-16v5h6V4h-6Z' },
  { href: '#screen', label: 'New Screening', icon: 'M12 5v14M5 12h14' },
  { href: '#recent', label: 'Case History', icon: 'M12 8v4l3 3m6-3a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z' },
]

const SOON_ITEMS = [
  { label: 'Watchlist', icon: 'M12 9v4m0 4h.01M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z' },
  { label: 'Settings', icon: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6Zm7-3a7 7 0 0 0-.1-1.2l2-1.6-2-3.4-2.4 1a7 7 0 0 0-2-1.2L14 3h-4l-.5 2.6a7 7 0 0 0-2 1.2l-2.4-1-2 3.4 2 1.6A7 7 0 0 0 5 12c0 .4 0 .8.1 1.2l-2 1.6 2 3.4 2.4-1c.6.5 1.3.9 2 1.2L10 21h4l.5-2.6c.7-.3 1.4-.7 2-1.2l2.4 1 2-3.4-2-1.6c.1-.4.1-.8.1-1.2Z' },
]

export default function Sidebar() {
  return (
    <aside className="hidden md:flex w-60 shrink-0 flex-col border-r border-border bg-surface px-4 py-6">
      <div className="flex items-center gap-2 px-2 mb-8">
        <div className="h-8 w-8 rounded-lg bg-accent flex items-center justify-center font-bold text-sm">P</div>
        <div>
          <p className="text-sm font-semibold leading-tight">PRAMAN</p>
          <p className="text-xs text-text-dim leading-tight">Border screening</p>
        </div>
      </div>

      <nav className="flex flex-col gap-1">
        {NAV_ITEMS.map((item) => (
          <a
            key={item.label}
            href={item.href}
            className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-text-dim hover:text-text hover:bg-surface-2 transition-colors"
          >
            <svg viewBox="0 0 24 24" className="h-4 w-4 stroke-current fill-none" strokeWidth={2}>
              <path d={item.icon} strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            {item.label}
          </a>
        ))}

        <div className="my-3 border-t border-border" />

        {SOON_ITEMS.map((item) => (
          <div
            key={item.label}
            className="flex items-center justify-between gap-3 rounded-lg px-3 py-2 text-sm text-text-dim/50 cursor-not-allowed"
          >
            <span className="flex items-center gap-3">
              <svg viewBox="0 0 24 24" className="h-4 w-4 stroke-current fill-none" strokeWidth={2}>
                <path d={item.icon} strokeLinecap="round" strokeLinejoin="round" />
              </svg>
              {item.label}
            </span>
            <span className="text-[10px] uppercase tracking-wide rounded-full bg-surface-2 px-1.5 py-0.5">soon</span>
          </div>
        ))}
      </nav>

      <div className="mt-auto rounded-xl bg-surface-2 border border-border p-3">
        <p className="text-xs text-text-dim">SIH26188</p>
        <p className="text-xs text-text-dim">Ministry of Home Affairs</p>
      </div>
    </aside>
  )
}
