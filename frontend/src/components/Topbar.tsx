import ThemeToggle from './ThemeToggle'

interface Props {
  title: string
  subtitle: string
  theme: 'dark' | 'light'
  onToggleTheme: () => void
  onOpenMenu: () => void
}

export default function Topbar({ title, subtitle, theme, onToggleTheme, onOpenMenu }: Props) {
  return (
    <header className="flex items-center justify-between border-b border-border bg-surface/60 px-4 sm:px-6 py-4 backdrop-blur">
      <div className="flex items-center gap-3">
        <button
          onClick={onOpenMenu}
          aria-label="Open menu"
          className="md:hidden h-9 w-9 rounded-lg border border-border bg-surface-2 flex items-center justify-center"
        >
          <svg viewBox="0 0 24 24" className="h-4 w-4 stroke-current fill-none" strokeWidth={2}>
            <path d="M4 6h16M4 12h16M4 18h16" strokeLinecap="round" />
          </svg>
        </button>
        <div>
          <h1 className="text-lg font-semibold">{title}</h1>
          <p className="text-xs text-text-dim">{subtitle}</p>
        </div>
      </div>
      <div className="flex items-center gap-3">
        <div className="hidden sm:flex items-center gap-2 rounded-full border border-border bg-surface-2 px-3 py-1.5 text-xs text-text-dim">
          <span className="h-2 w-2 rounded-full bg-success" />
          All modules online
        </div>
        <ThemeToggle theme={theme} onToggle={onToggleTheme} />
        <div className="h-9 w-9 rounded-full bg-accent-dim border border-border flex items-center justify-center text-sm font-medium text-accent">
          OP
        </div>
      </div>
    </header>
  )
}
