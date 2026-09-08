export default function Topbar() {
  return (
    <header className="flex items-center justify-between border-b border-border bg-surface/60 px-6 py-4 backdrop-blur">
      <div>
        <h1 className="text-lg font-semibold">Screening Dashboard</h1>
        <p className="text-xs text-text-dim">Live risk assessment for checkpoint personnel</p>
      </div>
      <div className="flex items-center gap-3">
        <div className="hidden sm:flex items-center gap-2 rounded-full border border-border bg-surface-2 px-3 py-1.5 text-xs text-text-dim">
          <span className="h-2 w-2 rounded-full bg-success" />
          All modules online
        </div>
        <div className="h-9 w-9 rounded-full bg-accent-dim border border-border flex items-center justify-center text-sm font-medium">
          OP
        </div>
      </div>
    </header>
  )
}
