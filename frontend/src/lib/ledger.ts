// Read-only client for risk-scoring-engine's GET /ledger/* endpoints (blockchain audit trail).
// Shapes mirror services/risk-scoring-engine/ledger_routes.py.

export type LedgerStatus = 'VERIFIED' | 'TAMPERED' | 'PENDING' | 'LEGACY_UNSEALED' | 'CHAIN_UNAVAILABLE'

export interface LedgerCheck {
  name: string
  ok: boolean | null // null = not evaluable yet
  detail: string
}

export interface VerifyResult {
  uuid: string
  status: LedgerStatus
  summary: string
  checks: LedgerCheck[]
  record: Record<string, unknown> | null
  leaf_hash: string | null
  batch_id: number | null
  leaf_index: number | null
  leaf_count: number | null
  merkle_root: string | null
  proof: { side: 'L' | 'R'; hash: string }[]
  chain_id: number | null
  contract_address: string | null
  tx_hash: string | null
  block_number: number | null
  anchored_at: string | null
  tx_url: string | null
}

export interface LedgerBatch {
  batch_id: number
  merkle_root: string
  leaf_count: number
  status: 'PENDING' | 'CONFIRMED'
  attempts: number
  last_error: string | null
  tx_hash: string | null
  block_number: number | null
  chain_id: number | null
  contract_address: string | null
  created_at: string | null
  confirmed_at: string | null
  tx_url: string | null
}

export interface LedgerBatchDetail extends LedgerBatch {
  records: { leaf_index: number; uuid: string; decision: string; leaf_hash: string }[]
}

export interface LedgerOverview {
  enabled: boolean
  database: string
  interval_seconds: number
  confirmations_required: number
  last_run_at: number | null
  last_error: string | null
  chain: {
    chain_id: number
    latest_block: number
    last_batch_id: number
    contract_address: string
    signer_address: string
    signer_balance_wei: string
    explorer_url: string | null
    contract_url: string | null
  } | null
  counts: { records: number; awaiting_batch: number; legacy_unhashed: number; batches: number; batches_pending: number }
}

const RISK_URL = (import.meta.env.VITE_RISK_SERVICE_URL ?? '').replace(/\/$/, '')

export const ledgerConfigured = Boolean(RISK_URL)

/** null on 404 (no audit record for that uuid, e.g. a demo/mock case); throws on anything else. */
async function get<T>(path: string): Promise<T | null> {
  if (!RISK_URL) throw new Error('VITE_RISK_SERVICE_URL is not set (see .env.example)')
  const res = await fetch(`${RISK_URL}/ledger${path}`)
  if (res.status === 404) return null
  if (!res.ok) throw new Error(`ledger ${path} → HTTP ${res.status}`)
  return (await res.json()) as T
}

export const verifyRecord = (uuid: string) => get<VerifyResult>(`/verify/${encodeURIComponent(uuid)}`)
export const fetchLedgerOverview = () => get<LedgerOverview>('/status')
export const fetchBatches = (limit = 20) => get<LedgerBatch[]>(`/batches?limit=${limit}`)
export const fetchBatch = (id: number) => get<LedgerBatchDetail>(`/batches/${id}`)

export const shortHash = (h: string | null | undefined, n = 10) => (h ? `${h.slice(0, n)}…${h.slice(-4)}` : '—')
