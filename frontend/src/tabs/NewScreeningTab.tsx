import { useState } from 'react'
import DecisionPanel from '../components/DecisionPanel'
import Dropzone from '../components/Dropzone'
import type { ScreeningCase } from '../types'

const DOCUMENT_SLOTS = [
  { key: 'passport', label: 'Passport', hint: 'Bio-data page', required: true },
  { key: 'visa', label: 'Visa', hint: 'Visa page / sticker', required: true },
  { key: 'nationalId', label: 'National ID', hint: 'Front & back', required: true },
  { key: 'drivingLicence', label: 'Driving Licence', hint: 'Optional', required: false },
  { key: 'permit', label: 'Permit', hint: 'Border / transit permit, optional', required: false },
] as const

type SlotKey = (typeof DOCUMENT_SLOTS)[number]['key'] | 'selfie'

const REQUIRED_KEYS: SlotKey[] = [...DOCUMENT_SLOTS.filter((s) => s.required).map((s) => s.key), 'selfie']

interface Props {
  onRun: () => void
  loading: boolean
  result: ScreeningCase | null
}

export default function NewScreeningTab({ onRun, loading, result }: Props) {
  const [files, setFiles] = useState<Partial<Record<SlotKey, File>>>({})

  function setFile(key: SlotKey) {
    return (file: File | null) => setFiles((prev) => ({ ...prev, [key]: file ?? undefined }))
  }

  const readyCount = REQUIRED_KEYS.filter((k) => files[k]).length
  const canRun = readyCount === REQUIRED_KEYS.length

  return (
    <div className="grid lg:grid-cols-[minmax(0,1fr)_minmax(0,1.4fr)] gap-6 items-start">
      <div className="rounded-2xl border border-border bg-surface p-5">
        <p className="text-sm font-medium mb-1">Identity documents</p>
        <p className="text-xs text-text-dim mb-4">
          Passport, Visa and National ID are required. Driving Licence and Permit are supporting documents.
        </p>
        <div className="grid grid-cols-2 gap-3">
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
        </div>

        <p className="text-sm font-medium mt-5 mb-1">Biometric capture</p>
        <p className="text-xs text-text-dim mb-3">Live selfie or short video, used for liveness and doc-to-selfie face match.</p>
        <Dropzone
          label="Live selfie / video"
          hint="JPG, PNG or MP4"
          accept="image/*,video/*"
          required
          onFile={setFile('selfie')}
        />

        <button
          onClick={onRun}
          disabled={loading || !canRun}
          className="mt-5 w-full rounded-xl bg-accent text-accent-fg px-4 py-2.5 text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed hover:brightness-110 transition"
        >
          {loading ? 'Screening…' : 'Run screening'}
        </button>
        {!canRun && !loading && (
          <p className="mt-2 text-center text-xs text-text-dim">{readyCount} of {REQUIRED_KEYS.length} required uploads added</p>
        )}
      </div>

      <DecisionPanel result={result} />
    </div>
  )
}
