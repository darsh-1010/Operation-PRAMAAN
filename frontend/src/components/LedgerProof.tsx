import { useCallback, useEffect, useState } from 'react'
import { ledgerConfigured, shortHash, verifyRecord, type LedgerStatus, type VerifyResult } from '../lib/ledger'

export const STATUS_STYLE: Record<LedgerStatus, { cls: string; label: string }> = {
  VERIFIED: { cls: 'bg-success-dim text-success', label: 'Verified on blockchain' },
  TAMPERED: { cls: 'bg-danger-dim text-danger', label: 'Tampering detected' },
  PENDING: { cls: 'bg-warning-dim text-warning', label: 'Awaiting anchoring' },
  CHAIN_UNAVAILABLE: { cls: 'bg-warning-dim text-warning', label: 'Chain unreachable' },
  LEGACY_UNSEALED: { cls: 'bg-surface-2 text-text-dim', label: 'Not sealed' },
}

const POLL_MS = 4000
const MAX_POLLS = 150 // ~10 min: covers a production ANCHOR_INTERVAL_SECONDS of 600
const MAX_POLLS_MISSING = 15 // a record should exist within seconds of the decision; demo cases never will

function StepIcon({ ok }: { ok: boolean | null }) {
  if (ok === true) return <span className="h-5 w-5 rounded-full bg-success-dim text-success flex items-center justify-center text-[11px] font-bold">✓</span>
  if (ok === false) return <span className="h-5 w-5 rounded-full bg-danger-dim text-danger flex items-center justify-center text-[11px] font-bold">✗</span>
  return <span className="h-5 w-5 rounded-full bg-warning-dim text-warning flex items-center justify-center text-[11px] animate-pulse">…</span>
}

/** Checks the result against the blockchain audit trail and shows every step of the chain of custody. */
export function LedgerTrace({ result }: { result: VerifyResult }) {
  const [showProof, setShowProof] = useState(false)
  return (
    <div className="space-y-3">
      <ol className="space-y-2">
        {result.checks.map((c, i) => (
          <li key={i} className="flex items-start gap-2.5">
            <StepIcon ok={c.ok} />
            <div className="min-w-0">
              <p className="text-xs font-medium text-text">{c.name}</p>
              <p className="text-[11px] text-text-dim font-mono break-all">{c.detail}</p>
            </div>
          </li>
        ))}
      </ol>

      {result.tx_hash && (
        <p className="text-[11px] text-text-dim">
          Transaction{' '}
          {result.tx_url ? (
            <a href={result.tx_url} target="_blank" rel="noreferrer" className="font-mono text-accent hover:underline">{shortHash(result.tx_hash, 14)} ↗</a>
          ) : (
            <span className="font-mono text-text">{shortHash(result.tx_hash, 14)}</span>
          )}
          {result.contract_address && <> · contract <span className="font-mono">{shortHash(result.contract_address, 8)}</span></>}
        </p>
      )}

      {result.leaf_hash && (
        <button onClick={() => setShowProof((v) => !v)} className="text-[11px] text-accent hover:underline cursor-pointer">
          {showProof ? 'Hide' : 'Show'} cryptographic proof
        </button>
      )}
      {showProof && (
        <div className="rounded-lg bg-surface-2 border border-border p-3 text-[11px] font-mono text-text-dim space-y-1 break-all">
          <p><span className="text-text">leaf</span> {result.leaf_hash}</p>
          {result.proof.map((p, i) => (
            <p key={i}><span className="text-text">+ {p.side === 'L' ? 'left ' : 'right'}</span> {p.hash}</p>
          ))}
          {result.merkle_root && <p><span className="text-text">= root</span> {result.merkle_root}</p>}
          <p className="font-sans pt-1">Only this 32-byte root goes on-chain — no names, document numbers or photos.</p>
        </div>
      )}
    </div>
  )
}

export default function LedgerProof({ uuid }: { uuid: string }) {
  const [result, setResult] = useState<VerifyResult | null>(null)
  const [state, setState] = useState<'loading' | 'ready' | 'missing' | 'error'>('loading')
  const [error, setError] = useState('')

  const check = useCallback(async () => {
    try {
      const r = await verifyRecord(uuid)
      if (r) {
        setResult(r)
        setState('ready')
      } else setState('missing')
      return r
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setState('error')
      return null
    }
  }, [uuid])

  useEffect(() => {
    let polls = 0
    let timer: ReturnType<typeof setTimeout>
    let cancelled = false
    const loop = async () => {
      const r = await check()
      const settled = r && (r.status === 'VERIFIED' || r.status === 'TAMPERED' || r.status === 'LEGACY_UNSEALED')
      if (!cancelled && !settled && ++polls < (r ? MAX_POLLS : MAX_POLLS_MISSING)) timer = setTimeout(loop, POLL_MS)
    }
    if (ledgerConfigured) loop()
    return () => {
      cancelled = true
      clearTimeout(timer)
    }
  }, [check])

  if (!ledgerConfigured) return null
  const style = result ? STATUS_STYLE[result.status] : null

  return (
    <div className="rounded-xl border border-border bg-surface-2 p-4 space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-xs font-semibold text-text flex items-center gap-2">
          <svg viewBox="0 0 24 24" className="h-4 w-4 stroke-accent fill-none" strokeWidth={2}>
            <path d="M10 13a5 5 0 0 0 7.5.5l3-3a5 5 0 0 0-7-7l-1.7 1.7M14 11a5 5 0 0 0-7.5-.5l-3 3a5 5 0 0 0 7 7l1.7-1.7" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
          Blockchain audit trail
        </p>
        <div className="flex items-center gap-2">
          {style && <span className={`text-[11px] font-semibold rounded-full px-2.5 py-0.5 ${style.cls}`}>{style.label}</span>}
          <button onClick={check} className="text-[11px] rounded-md border border-border px-2 py-0.5 hover:bg-surface cursor-pointer">Re-verify</button>
        </div>
      </div>

      {state === 'loading' && <p className="text-xs text-text-dim">Checking the ledger…</p>}
      {state === 'missing' && (
        <p className="text-xs text-text-dim">
          No audit record for this case yet. Live screenings are sealed once the risk engine finalizes them; demo/sample cases are never recorded.
        </p>
      )}
      {state === 'error' && <p className="text-xs text-danger">Ledger unavailable: {error}</p>}
      {result && (
        <>
          <p className={`text-xs ${result.status === 'TAMPERED' ? 'text-danger font-semibold' : 'text-text-dim'}`}>{result.summary}</p>
          <LedgerTrace result={result} />
        </>
      )}
    </div>
  )
}
