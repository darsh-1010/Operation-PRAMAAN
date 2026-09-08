import { useState } from 'react'

interface Props {
  onRun: () => void
  loading: boolean
}

function Dropzone({ label, hint, accept }: { label: string; hint: string; accept: string }) {
  const [fileName, setFileName] = useState<string | null>(null)

  return (
    <label className="flex flex-col items-center justify-center gap-1 rounded-xl border border-dashed border-border bg-surface-2 px-4 py-6 text-center cursor-pointer hover:border-accent/60 transition-colors">
      <input
        type="file"
        accept={accept}
        className="hidden"
        onChange={(e) => setFileName(e.target.files?.[0]?.name ?? null)}
      />
      <svg viewBox="0 0 24 24" className="h-6 w-6 stroke-text-dim fill-none mb-1" strokeWidth={1.5}>
        <path d="M12 16V4m0 0 4 4m-4-4-4 4M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
      <p className="text-sm font-medium">{fileName ?? label}</p>
      <p className="text-xs text-text-dim">{hint}</p>
    </label>
  )
}

export default function UploadPanel({ onRun, loading }: Props) {
  return (
    <div className="rounded-2xl border border-border bg-surface p-5">
      <p className="text-sm font-medium mb-1">New screening</p>
      <p className="text-xs text-text-dim mb-4">Both inputs run through OCR, forensics and biometric checks in parallel.</p>

      <div className="grid sm:grid-cols-2 gap-3">
        <Dropzone label="Document photo(s)" hint="Passport, visa, ID or licence · JPG/PNG" accept="image/*" />
        <Dropzone label="Live selfie / video" hint="For liveness + face match · JPG/PNG/MP4" accept="image/*,video/*" />
      </div>

      <button
        onClick={onRun}
        disabled={loading}
        className="mt-4 w-full rounded-xl bg-accent px-4 py-2.5 text-sm font-semibold disabled:opacity-60 disabled:cursor-not-allowed hover:brightness-110 transition"
      >
        {loading ? 'Screening…' : 'Run screening'}
      </button>
    </div>
  )
}
