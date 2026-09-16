import { useState } from 'react'
import DecisionPanel from '../components/DecisionPanel'
import Dropzone from '../components/Dropzone'
import { DOCUMENT_SLOTS, type DocKey } from '../lib/documents'

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

  const uploadedCount = Object.values(files).filter(Boolean).length
  const canRun = uploadedCount > 0

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-border bg-surface p-5">
        <p className="text-sm font-medium mb-1">Identity documents &amp; biometrics</p>
        <p className="text-xs text-text-dim mb-4">
          Upload any document (Passport, Visa, National ID, Driving Licence) to test OCR extraction, accuracy, and latency.
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
          <Dropzone label="Live selfie / video" hint="JPG/PNG/MP4" accept="image/*,video/*" required={false} onFile={setFile('selfie')} />
        </div>

        <div className="mt-5 flex flex-col sm:flex-row items-center gap-3">
          <button
            onClick={() => onRun(files)}
            disabled={loading || !canRun}
            className="w-full sm:w-auto sm:px-8 rounded-xl bg-accent text-accent-fg px-4 py-2.5 text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed hover:brightness-110 transition cursor-pointer"
          >
            {loading ? 'Processing OCR & Screening…' : 'Run screening'}
          </button>
          {!canRun && !loading && (
            <p className="text-xs text-text-dim">Upload at least one document to start</p>
          )}
          {canRun && !loading && (
            <p className="text-xs text-success font-medium">{uploadedCount} document{uploadedCount > 1 ? 's' : ''} ready for screening</p>
          )}
        </div>
      </div>

      <DecisionPanel result={result} />
    </div>
  )
}
