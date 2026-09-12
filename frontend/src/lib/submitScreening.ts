import { ALL_KEYS, type DocKey } from './documents'

// Per the architecture diagram: INPUT 1 (document photos) + INPUT 2 (selfie/video) are sent
// to all three detection modules simultaneously — they run fully in parallel, not gated on
// each other. Every module gets the same three things: a uuid to correlate this submission
// across all three (and later the risk-scoring-engine) responses, which document types are
// actually present, and the files themselves. The endpoint path and response shape below
// implement API_CONTRACT.md at the repo root — see that file for the full spec.

const SCREEN_PATH = '/screen'

export interface ScreeningPayload {
  uuid: string
  documentsPresent: Record<DocKey, boolean>
  files: Partial<Record<DocKey, File>>
}

/** Every file here has already passed src/lib/fileGuard.ts (Dropzone never calls onFile with
 * one that failed the guard) — this only assembles what already-validated input into a payload. */
export function buildScreeningPayload(files: Partial<Record<DocKey, File>>): ScreeningPayload {
  const documentsPresent = Object.fromEntries(ALL_KEYS.map((k) => [k, Boolean(files[k])])) as Record<DocKey, boolean>
  return { uuid: crypto.randomUUID(), documentsPresent, files }
}

function toFormData({ uuid, documentsPresent, files }: ScreeningPayload): FormData {
  const form = new FormData()
  form.set('uuid', uuid)
  form.set('documents_present', JSON.stringify(documentsPresent))
  for (const key of ALL_KEYS) {
    const file = files[key]
    if (file) form.append(key, file)
  }
  return form
}

const MODULE_ENDPOINTS: { name: string; url: string | undefined }[] = [
  { name: 'ocr-consistency-check', url: import.meta.env.VITE_OCR_SERVICE_URL },
  { name: 'visual-image-forensics', url: import.meta.env.VITE_FORENSICS_SERVICE_URL },
  { name: 'biometric-matching', url: import.meta.env.VITE_BIOMETRIC_SERVICE_URL },
]

/** A module's POST /screen response — API_CONTRACT.md's exact shape. */
export interface ModuleResponse {
  score: number
  hard_fail: boolean
  reason_codes: string[]
}

function isModuleResponse(body: unknown): body is ModuleResponse {
  if (typeof body !== 'object' || body === null) return false
  const b = body as Record<string, unknown>
  return typeof b.score === 'number' && typeof b.hard_fail === 'boolean' && Array.isArray(b.reason_codes)
}

export type ModuleDispatchResult =
  | { name: string; reachable: true; response: ModuleResponse }
  | { name: string; reachable: false; error: string }

/** Fires the same payload at all three module services' POST /screen in parallel (a fresh
 * FormData per request — FormData with file entries can't be reused across fetch calls).
 * None of them have an implementation yet, so every call is expected to fail right now;
 * that's reported per-service rather than thrown, so the caller can fall back to a demo result. */
export async function dispatchToModules(payload: ScreeningPayload): Promise<ModuleDispatchResult[]> {
  const targets = MODULE_ENDPOINTS.filter((m): m is { name: string; url: string } => Boolean(m.url))

  const settled = await Promise.allSettled(
    targets.map(async (m) => {
      const res = await fetch(m.url.replace(/\/$/, '') + SCREEN_PATH, { method: 'POST', body: toFormData(payload) })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const body: unknown = await res.json()
      if (!isModuleResponse(body)) throw new Error('Response did not match API_CONTRACT.md')
      return body
    }),
  )

  return settled.map((result, i) => {
    const name = targets[i].name
    if (result.status === 'fulfilled') return { name, reachable: true, response: result.value }
    return { name, reachable: false, error: String(result.reason) }
  })
}
