import { useCallback, useEffect, useState } from 'react'
import KpiCard from '../components/KpiCard'
import { LedgerTrace, STATUS_STYLE } from '../components/LedgerProof'
import {
  fetchBatch, fetchBatches, fetchLedgerOverview, ledgerConfigured, shortHash, verifyRecord,
  type LedgerBatch, type LedgerBatchDetail, type LedgerOverview, type VerifyResult,
} from '../lib/ledger'

const CHAIN_NAMES: Record<number, string> = { 31337: 'Local dev chain (Anvil)', 80002: 'Polygon Amoy testnet', 137: 'Polygon PoS mainnet' }
const REFRESH_MS = 10_000

const FLOW = [
  { title: 'Decision', body: 'Risk engine finalizes ACCEPT / REVIEW / REJECT and stores it in Postgres.' },
  { title: 'Fingerprint', body: 'The exact record is hashed with SHA-256. No names, numbers or photos leave the database.' },
  { title: 'Merkle batch', body: 'Every few minutes all new fingerprints are combined into one 32-byte Merkle root.' },
  { title: 'Blockchain', body: 'The root is written to the PramanAnchor smart contract. Nobody can change it afterwards.' },
]

function timeAgo(epochSeconds: number | null): string {
  if (!epochSeconds) return 'never'
  const s = Math.max(0, Math.round(Date.now() / 1000 - epochSeconds))
  return s < 60 ? `${s}s ago` : `${Math.round(s / 60)} min ago`
}

function BatchRow({ batch, onVerify }: { batch: LedgerBatch; onVerify: (uuid: string) => void }) {
  const [detail, setDetail] = useState<LedgerBatchDetail | null>(null)
  const [open, setOpen] = useState(false)
  const toggle = async () => {
    setOpen((v) => !v)
    if (!detail) setDetail(await fetchBatch(batch.batch_id).catch(() => null))
  }
  const confirmed = batch.status === 'CONFIRMED'
  return (
    <>
      <tr onClick={toggle} className="border-t border-border hover:bg-surface-2 cursor-pointer">
        <td className="py-2.5 px-3 font-semibold">#{batch.batch_id}</td>
        <td className="py-2.5 px-3 font-mono text-text-dim">{shortHash(batch.merkle_root, 12)}</td>
        <td className="py-2.5 px-3">{batch.leaf_count}</td>
        <td className="py-2.5 px-3">
          <span className={`text-[11px] font-semibold rounded-full px-2 py-0.5 ${confirmed ? 'bg-success-dim text-success' : 'bg-warning-dim text-warning'}`}>
            {confirmed ? 'Anchored' : batch.attempts ? `Retrying (${batch.attempts})` : 'Pending'}
          </span>
        </td>
        <td className="py-2.5 px-3 font-mono">
          {batch.tx_url ? (
            <a href={batch.tx_url} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className="text-accent hover:underline">
              {shortHash(batch.tx_hash, 10)} ↗
            </a>
          ) : (
            <span className="text-text-dim">{shortHash(batch.tx_hash, 10)}</span>
          )}
        </td>
        <td className="py-2.5 px-3 text-text-dim">{batch.block_number ?? '—'}</td>
      </tr>
      {open && (
        <tr className="bg-surface-2">
          <td colSpan={6} className="px-3 py-3">
            {batch.last_error && <p className="text-[11px] text-danger mb-2">Last error: {batch.last_error}</p>}
            {!detail ? (
              <p className="text-xs text-text-dim">Loading records…</p>
            ) : (
              <div className="space-y-1">
                {detail.records.map((r) => (
                  <div key={r.leaf_index} className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px]">
                    <span className="text-text-dim w-8">leaf {r.leaf_index}</span>
                    <span className="font-mono">{r.uuid}</span>
                    <span className="rounded bg-surface px-1.5 border border-border">{r.decision}</span>
                    <span className="font-mono text-text-dim">{shortHash(r.leaf_hash, 10)}</span>
                    <button onClick={() => onVerify(r.uuid)} className="text-accent hover:underline cursor-pointer">verify →</button>
                  </div>
                ))}
              </div>
            )}
          </td>
        </tr>
      )}
    </>
  )
}

export default function LedgerTab() {
  const [overview, setOverview] = useState<LedgerOverview | null>(null)
  const [batches, setBatches] = useState<LedgerBatch[]>([])
  const [error, setError] = useState('')
  const [query, setQuery] = useState('')
  const [verified, setVerified] = useState<VerifyResult | null | 'missing'>(null)
  const [verifying, setVerifying] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const [o, b] = await Promise.all([fetchLedgerOverview(), fetchBatches(25)])
      setOverview(o)
      setBatches(b ?? [])
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    }
  }, [])

  useEffect(() => {
    if (!ledgerConfigured) return
    refresh()
    const id = setInterval(refresh, REFRESH_MS)
    return () => clearInterval(id)
  }, [refresh])

  async function verify(uuid: string) {
    const id = uuid.trim()
    if (!id) return
    setQuery(id)
    setVerifying(true)
    try {
      setVerified((await verifyRecord(id)) ?? 'missing')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setVerifying(false)
    }
  }

  if (!ledgerConfigured) {
    return <p className="text-sm text-text-dim">Set VITE_RISK_SERVICE_URL (see frontend/.env.example) to connect the blockchain ledger.</p>
  }

  const chain = overview?.chain
  const counts = overview?.counts

  return (
    <div className="space-y-6">
      <section className="rounded-2xl border border-border bg-surface p-5">
        <p className="text-sm font-medium mb-1">How every decision is made tamper-evident</p>
        <p className="text-xs text-text-dim mb-4">
          If anyone edits, deletes or back-dates a stored decision, its fingerprint no longer matches the root on the blockchain, and verification fails.
        </p>
        <ol className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {FLOW.map((step, i) => (
            <li key={step.title} className="rounded-xl border border-border bg-surface-2 p-3">
              <p className="text-xs font-semibold text-accent mb-1">{i + 1}. {step.title}</p>
              <p className="text-[11px] text-text-dim leading-relaxed">{step.body}</p>
            </li>
          ))}
        </ol>
      </section>

      {error && <p className="rounded-xl border border-danger/30 bg-danger-dim/40 px-4 py-2 text-xs text-danger">Ledger service: {error}</p>}

      <section className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <KpiCard label="Decisions recorded" value={String(counts?.records ?? '—')} sublabel="audit rows" tone="accent" />
        <KpiCard label="Batches anchored" value={String(chain?.last_batch_id ?? '—')} sublabel="on-chain" tone="success" />
        <KpiCard label="Awaiting anchoring" value={String((counts?.awaiting_batch ?? 0) + (counts?.batches_pending ?? 0))} sublabel="records + batches" tone="warning" />
        <KpiCard label="Latest block" value={chain ? String(chain.latest_block) : '—'} sublabel={chain ? 'live' : 'offline'} tone={chain ? 'accent' : 'danger'} />
      </section>

      <section className="rounded-2xl border border-border bg-surface p-5 grid gap-4 lg:grid-cols-2">
        <div className="space-y-1.5 text-xs">
          <p className="text-sm font-medium mb-2 flex items-center gap-2">
            Network
            <span className={`text-[10px] font-semibold rounded-full px-2 py-0.5 ${overview?.enabled ? 'bg-success-dim text-success' : 'bg-danger-dim text-danger'}`}>
              {overview?.enabled ? 'connected' : 'disconnected'}
            </span>
          </p>
          <p><span className="text-text-dim">Chain:</span> {chain ? CHAIN_NAMES[chain.chain_id] ?? `EVM chain ${chain.chain_id}` : '—'}</p>
          <p className="break-all">
            <span className="text-text-dim">Contract:</span>{' '}
            {chain?.contract_url ? (
              <a href={chain.contract_url} target="_blank" rel="noreferrer" className="font-mono text-accent hover:underline">{chain.contract_address} ↗</a>
            ) : (
              <span className="font-mono">{chain?.contract_address ?? '—'}</span>
            )}
          </p>
          <p className="break-all"><span className="text-text-dim">Signer:</span> <span className="font-mono">{chain?.signer_address ?? '—'}</span></p>
          <p><span className="text-text-dim">Anchoring every</span> {overview?.interval_seconds ?? '—'}s · last run {timeAgo(overview?.last_run_at ?? null)}</p>
          <p><span className="text-text-dim">Storage:</span> {overview?.database ?? '—'}</p>
          {overview?.last_error && <p className="text-danger break-all">Last error: {overview.last_error}</p>}
        </div>

        <div>
          <p className="text-sm font-medium mb-2">Verify a decision</p>
          <form onSubmit={(e) => { e.preventDefault(); verify(query) }} className="flex gap-2 mb-3">
            <input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Screening UUID"
              className="flex-1 min-w-0 rounded-lg border border-border bg-surface-2 px-3 py-2 text-xs font-mono outline-none focus:border-accent"
            />
            <button disabled={verifying} className="rounded-lg bg-accent text-accent-fg px-4 py-2 text-xs font-semibold disabled:opacity-50 cursor-pointer">
              {verifying ? 'Checking…' : 'Verify'}
            </button>
          </form>
          {verified === 'missing' && <p className="text-xs text-text-dim">No audit record for that UUID.</p>}
          {verified && verified !== 'missing' && (
            <div className="space-y-2">
              <span className={`inline-block text-[11px] font-semibold rounded-full px-2.5 py-0.5 ${STATUS_STYLE[verified.status].cls}`}>
                {STATUS_STYLE[verified.status].label}
              </span>
              <LedgerTrace result={verified} />
            </div>
          )}
        </div>
      </section>

      <section className="rounded-2xl border border-border bg-surface overflow-hidden">
        <div className="px-5 py-4 flex items-center justify-between">
          <p className="text-sm font-medium">Anchored batches</p>
          <button onClick={refresh} className="text-[11px] rounded-md border border-border px-2 py-0.5 hover:bg-surface-2 cursor-pointer">Refresh</button>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead className="text-text-dim text-left">
              <tr>
                <th className="py-2 px-3 font-medium">Batch</th>
                <th className="py-2 px-3 font-medium">Merkle root</th>
                <th className="py-2 px-3 font-medium">Records</th>
                <th className="py-2 px-3 font-medium">Status</th>
                <th className="py-2 px-3 font-medium">Transaction</th>
                <th className="py-2 px-3 font-medium">Block</th>
              </tr>
            </thead>
            <tbody>
              {batches.map((b) => <BatchRow key={b.batch_id} batch={b} onVerify={verify} />)}
              {batches.length === 0 && (
                <tr><td colSpan={6} className="px-3 py-6 text-center text-text-dim">No batches yet. Run a screening; it is anchored on the next cycle.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  )
}
