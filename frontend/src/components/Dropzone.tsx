import { useState } from 'react'

interface Props {
  label: string
  hint: string
  accept: string
  required?: boolean
  onFile: (file: File | null) => void
}

export default function Dropzone({ label, hint, accept, required, onFile }: Props) {
  const [fileName, setFileName] = useState<string | null>(null)

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0] ?? null
    setFileName(file?.name ?? null)
    onFile(file)
  }

  return (
    <label
      className={`flex flex-col items-center justify-center gap-1 rounded-xl border border-dashed px-4 py-5 text-center cursor-pointer transition-colors ${
        fileName ? 'border-success/60 bg-success-dim' : 'border-border bg-surface-2 hover:border-accent/60'
      }`}
    >
      <input type="file" accept={accept} className="hidden" onChange={handleChange} />
      {fileName ? (
        <svg viewBox="0 0 24 24" className="h-5 w-5 stroke-success fill-none mb-1" strokeWidth={2}>
          <path d="m5 13 4 4L19 7" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      ) : (
        <svg viewBox="0 0 24 24" className="h-5 w-5 stroke-text-dim fill-none mb-1" strokeWidth={1.5}>
          <path d="M12 16V4m0 0 4 4m-4-4-4 4M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}
      <p className="text-sm font-medium truncate max-w-full">
        {label}
        {required && <span className="text-danger"> *</span>}
      </p>
      <p className="text-xs text-text-dim truncate max-w-full">{fileName ?? hint}</p>
    </label>
  )
}
