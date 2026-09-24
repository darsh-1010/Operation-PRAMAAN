import { useState } from 'react'
import DecisionPanel from '../components/DecisionPanel'
import Dropzone from '../components/Dropzone'
import { DOCUMENT_SLOTS, type DocKey } from '../lib/documents'

import type { ScreeningCase } from '../types'

interface Props {
  onRun: (files: Partial<Record<DocKey, File>>) => void
  loading: boolean
  result: ScreeningCase | null
  onBack?: () => void
}

type DocType = (typeof DOCUMENT_SLOTS)[number]['key']

interface QuickValues {
  fullName: string
  documentNumber: string
  dateOfBirth: string
  expiryDate: string
}

const EMPTY_QUICK_VALUES: QuickValues = { fullName: '', documentNumber: '', dateOfBirth: '', expiryDate: '' }

export default function NewScreeningTab({ onRun, loading, result, onBack }: Props) {
  const [docType, setDocType] = useState<DocType>(DOCUMENT_SLOTS[0].key)
  const [files, setFiles] = useState<Partial<Record<DocKey, File>>>({})
  const [quickValues, setQuickValues] = useState<QuickValues>(EMPTY_QUICK_VALUES)

  function setFile(key: DocKey) {
    return (file: File | null) => setFiles((prev) => ({ ...prev, [key]: file ?? undefined }))
  }

  const canRun = Boolean(files[docType])

  return (
    <div className="space-y-6">
      <div className="rounded-2xl border border-border bg-surface p-5">
        <div className="flex items-start justify-between gap-3 mb-5">
          <div>
            <p className="text-sm font-medium mb-1">New Screening</p>
            <p className="text-xs text-text-dim">Follow the stages; correct OCR fields before deciding.</p>
          </div>
          {onBack && (
            <button
              onClick={onBack}
              className="shrink-0 rounded-lg border border-border bg-surface-2 px-3 py-1.5 text-xs font-medium hover:bg-surface cursor-pointer"
            >
              ← Console
            </button>
          )}
        </div>

        <div className="grid gap-4 lg:grid-cols-2">
          <section className="rounded-xl border border-border p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-text-dim mb-3">1 · Document type</p>
            <div className="grid grid-cols-2 gap-2">
              {DOCUMENT_SLOTS.map((slot) => (
                <button
                  key={slot.key}
                  type="button"
                  onClick={() => setDocType(slot.key)}
                  className={`rounded-lg px-3 py-2.5 text-sm font-semibold text-left transition-colors cursor-pointer ${
                    docType === slot.key
                      ? 'bg-accent text-accent-fg'
                      : 'border border-border bg-surface-2 hover:border-accent/60'
                  }`}
                >
                  {slot.label}
                </button>
              ))}
            </div>
          </section>

          <section className="rounded-xl border border-border p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-text-dim mb-3">2 · Document image</p>
            <Dropzone
              key={docType}
              label={DOCUMENT_SLOTS.find((s) => s.key === docType)!.label}
              hint={DOCUMENT_SLOTS.find((s) => s.key === docType)!.hint}
              accept="image/*"
              required
              onFile={setFile(docType)}
              facingMode="environment"
            />
          </section>

          <section className="rounded-xl border border-border p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-text-dim mb-3">
              3 · Live selfie <span className="normal-case font-normal">(optional — enables face verification)</span>
            </p>
            <Dropzone
              label="Selfie"
              hint="JPG/PNG/MP4"
              accept="image/*,video/*"
              onFile={setFile('selfie')}
              variant="compact"
              webcamLabel="Capture selfie"
              facingMode="user"
            />
          </section>

          <section className="rounded-xl border border-border p-4">
            <p className="text-xs font-semibold uppercase tracking-wide text-text-dim mb-3">
              4 · Quick values <span className="normal-case font-normal">(what you can read off the document)</span>
            </p>
            <div className="grid grid-cols-2 gap-3">
              {([
                ['fullName', 'fullName'],
                ['documentNumber', 'documentNumber'],
                ['dateOfBirth', 'dateOfBirth'],
                ['expiryDate', 'expiryDate'],
              ] as const).map(([key, placeholder]) => (
                <div key={key}>
                  <label className="text-xs text-text-dim">{key}</label>
                  <input
                    type="text"
                    value={quickValues[key]}
                    placeholder={placeholder}
                    onChange={(e) => setQuickValues((prev) => ({ ...prev, [key]: e.target.value }))}
                    className="mt-1 w-full rounded-lg border border-border bg-surface-2 px-3 py-2 text-sm outline-none focus:border-accent/60"
                  />
                </div>
              ))}
            </div>
          </section>
        </div>

        <div className="mt-5 flex flex-col sm:flex-row sm:justify-end items-center gap-3">
          {!canRun && !loading && <p className="text-xs text-text-dim">Upload the document image to continue</p>}
          {canRun && !loading && <p className="text-xs text-success font-medium">Ready to run</p>}
          <button
            onClick={() => onRun(files)}
            disabled={loading || !canRun}
            className="w-full sm:w-auto sm:px-8 rounded-xl bg-accent text-accent-fg px-4 py-2.5 text-sm font-semibold disabled:opacity-50 disabled:cursor-not-allowed hover:brightness-110 transition cursor-pointer"
          >
            {loading ? 'Processing OCR & Screening…' : 'Run verification pipeline →'}
          </button>
        </div>
      </div>

      <DecisionPanel result={result} />
    </div>
  )
}
