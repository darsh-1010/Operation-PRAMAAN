import { useEffect, useState } from 'react'
import { guardFile } from '../lib/fileGuard'

interface Props {
  label: string
  hint: string
  accept: string
  required?: boolean
  onFile: (file: File | null) => void
}

export default function Dropzone({ label, hint, accept, required, onFile }: Props) {
  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)
  const allowVideo = accept.includes('video')

  // Build an object URL for image/video previews and clean it up when the file changes or unmounts.
  useEffect(() => {
    if (!file || !/^(image|video)\//.test(file.type)) {
      setPreviewUrl(null)
      return
    }
    const url = URL.createObjectURL(file)
    setPreviewUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  async function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const next = e.target.files?.[0] ?? null
    e.target.value = '' // allow re-selecting the same file after a rejection or removal
    if (!next) return

    setChecking(true)
    setError(null)
    const result = await guardFile(next, allowVideo)
    setChecking(false)

    if (!result.ok) {
      setError(result.reason ?? 'File rejected')
      setFile(null)
      onFile(null)
      return
    }
    setFile(next)
    onFile(next)
  }

  function handleClear(e: React.MouseEvent) {
    e.preventDefault()
    e.stopPropagation()
    setFile(null)
    setError(null)
    onFile(null)
  }

  return (
    <label
      className={`relative flex flex-col items-center justify-center gap-1 rounded-xl border border-dashed px-4 py-5 text-center cursor-pointer transition-colors overflow-hidden ${
        error
          ? 'border-danger/60 bg-danger-dim'
          : file
            ? 'border-success/60 bg-success-dim'
            : 'border-border bg-surface-2 hover:border-accent/60'
      }`}
    >
      <input type="file" accept={accept} className="hidden" onChange={handleChange} />

      {file && (
        <button
          type="button"
          onClick={handleClear}
          aria-label={`Remove ${label}`}
          className="absolute top-1.5 right-1.5 h-5 w-5 rounded-full bg-surface/90 border border-border flex items-center justify-center hover:brightness-110"
        >
          <svg viewBox="0 0 24 24" className="h-3 w-3 stroke-current fill-none" strokeWidth={2.5}>
            <path d="M6 6l12 12M18 6 6 18" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      )}

      {previewUrl ? (
        file?.type.startsWith('video/') ? (
          <video src={previewUrl} className="h-16 w-full rounded-md object-cover mb-1" muted />
        ) : (
          <img src={previewUrl} alt="" className="h-16 w-full rounded-md object-cover mb-1" />
        )
      ) : file ? (
        <svg viewBox="0 0 24 24" className="h-5 w-5 stroke-success fill-none mb-1" strokeWidth={2}>
          <path d="m5 13 4 4L19 7" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      ) : error ? (
        <svg viewBox="0 0 24 24" className="h-5 w-5 stroke-danger fill-none mb-1" strokeWidth={2}>
          <path d="M12 9v4m0 4h.01M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z" strokeLinecap="round" strokeLinejoin="round" />
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
      <p className={`text-xs truncate max-w-full ${error ? 'text-danger' : 'text-text-dim'}`}>
        {checking ? 'Checking file…' : (error ?? file?.name ?? hint)}
      </p>
    </label>
  )
}
