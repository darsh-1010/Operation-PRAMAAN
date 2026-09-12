import { useState } from 'react'
import DecisionPanel from '../components/DecisionPanel'
import Dropzone from '../components/Dropzone'
import { DOCUMENT_SLOTS, REQUIRED_KEYS, type DocKey } from '../lib/documents'
import type { ScreeningCase } from '../types'

interface Props {
  onRun: (files: Partial<Record<DocKey, File>>) => void
  loading: boolean
  result: ScreeningCase | null
}

export default function NewScreeningTab({ onRun, loading, result }: Props) {
  const [files, setFiles] = useState<Partial<Record<DocKey, File>>>({})

  function setFile(key: DocKey) {
    return (file: File | null) => setFiles((prev) => ({ ...prev, [key]: file ?? undefined }))
  }

  const readyCount = REQUIRED_KEYS.filter((k) => files[k]).length
  const canRun = readyCount === REQUIRED_KEYS.length

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-border bg-surface p-5">
        <p className="text-sm font-medium mb-1">Identity documents &amp; biometrics</p>
        <p className="text-xs text-text-dim mb-4">
          Passport, Visa, National ID and the live selfie/video are required. Driving Licence and Permit are
          supporting documents.
        </p>

        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
          {DOCUMENT_SLOTS.map((slot) => (
            <Dropzone
              key={slot.key}
              label={slot.label}
              hint={slot.hint}
              accept="image/*"
              required={slot.required}
              onFile={setFile(slot.key)}
            />
          ))}
          <Dropzone label="Live selfie / video" hint="JPG/PNG/MP4" accept="image/*,video/*" required onFile={setFile('selfie')} />
        </div>

        <div className="mt-5 flex flex-col sm:flex-row items-center gap-3">
          <button
            onClick={() => onRun(files)}
            disabled={loading || !canRun}
            className="w-full sm:w-auto sm:px-8 rounded-xl bg-accent text-accent-fg px-4 py-2.5 text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed hover:brightness-110 transition"
          >
            {loading ? 'Screening…' : 'Run screening'}
          </button>
          {!canRun && !loading && (
            <p className="text-xs text-text-dim">{readyCount} of {REQUIRED_KEYS.length} required uploads added</p>
          )}
        </div>
      </div>

      <DecisionPanel result={result} />
    </div>
  )
}
