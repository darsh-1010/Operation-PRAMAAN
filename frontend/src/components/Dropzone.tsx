import { useEffect, useRef, useState } from 'react'
import { guardFile } from '../lib/fileGuard'
import WebcamCapture from './WebcamCapture'

interface Props {
  label: string
  hint: string
  accept: string
  required?: boolean
  onFile: (file: File | null) => void
  /** 'box' (default): big dashed drag & drop area with Choose file + Webcam buttons.
   *  'compact': a two-button row (e.g. "Capture selfie" / "Upload") with no drop area — used
   *  where screen space is tight, like the selfie slot. */
  variant?: 'box' | 'compact'
  webcamLabel?: string
  facingMode?: 'user' | 'environment'
}

export default function Dropzone({
  label,
  hint,
  accept,
  required,
  onFile,
  variant = 'box',
  webcamLabel = 'Webcam',
  facingMode = 'environment',
}: Props) {
  const [file, setFile] = useState<File | null>(null)
  const [previewUrl, setPreviewUrl] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [checking, setChecking] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [showWebcam, setShowWebcam] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const allowVideo = accept.includes('video')

  useEffect(() => {
    if (!file || !/^(image|video)\//.test(file.type)) {
      setPreviewUrl(null)
      return
    }
    const url = URL.createObjectURL(file)
    setPreviewUrl(url)
    return () => URL.revokeObjectURL(url)
  }, [file])

  async function acceptFile(next: File | null) {
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

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    const next = e.target.files?.[0] ?? null
    e.target.value = '' // allow re-selecting the same file after a rejection or removal
    void acceptFile(next)
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault()
    setDragOver(false)
    void acceptFile(e.dataTransfer.files?.[0] ?? null)
  }

  function handleClear(e: React.MouseEvent) {
    e.preventDefault()
    e.stopPropagation()
    setFile(null)
    setError(null)
    onFile(null)
  }

  const statusText = checking ? 'Checking file…' : (error ?? file?.name ?? hint)
  const statusClass = error ? 'text-danger' : 'text-text-dim'

  const preview = previewUrl ? (
    file?.type.startsWith('video/') ? (
      <video src={previewUrl} className="h-16 w-16 shrink-0 rounded-md object-cover" muted />
    ) : (
      <img src={previewUrl} alt="" className="h-16 w-16 shrink-0 rounded-md object-cover" />
    )
  ) : null

  const hiddenInput = <input ref={inputRef} type="file" accept={accept} className="hidden" onChange={handleChange} />

  if (variant === 'compact') {
    return (
      <div className="flex flex-col gap-2.5">
        {hiddenInput}
        {showWebcam && (
          <WebcamCapture facingMode={facingMode} onCapture={(f) => void acceptFile(f)} onClose={() => setShowWebcam(false)} />
        )}
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setShowWebcam(true)}
            className="rounded-lg border border-border bg-surface-2 px-4 py-2 text-sm font-medium hover:border-accent/60 cursor-pointer"
          >
            {webcamLabel}
          </button>
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            className="rounded-lg border border-border bg-surface-2 px-4 py-2 text-sm font-medium hover:border-accent/60 cursor-pointer"
          >
            Upload
          </button>
        </div>
        {(file || error) && (
          <div className={`flex items-center gap-2 rounded-lg border px-2.5 py-1.5 text-xs ${error ? 'border-danger/60 bg-danger-dim' : 'border-success/60 bg-success-dim'}`}>
            {preview}
            <span className={`truncate ${statusClass}`}>{statusText}</span>
            {file && (
              <button type="button" onClick={handleClear} className="ml-auto shrink-0 text-text-dim hover:text-text cursor-pointer">
                ✕
              </button>
            )}
          </div>
        )}
      </div>
    )
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault()
        setDragOver(true)
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      className={`relative flex flex-col items-center justify-center gap-2 rounded-xl border border-dashed px-4 py-8 text-center transition-colors ${
        error
          ? 'border-danger/60 bg-danger-dim'
          : file
            ? 'border-success/60 bg-success-dim'
            : dragOver
              ? 'border-accent bg-accent/5'
              : 'border-border bg-surface-2'
      }`}
    >
      {hiddenInput}
      {showWebcam && (
        <WebcamCapture facingMode={facingMode} onCapture={(f) => void acceptFile(f)} onClose={() => setShowWebcam(false)} />
      )}

      {file && (
        <button
          type="button"
          onClick={handleClear}
          aria-label={`Remove ${label}`}
          className="absolute top-2 right-2 h-5 w-5 rounded-full bg-surface/90 border border-border flex items-center justify-center hover:brightness-110 cursor-pointer"
        >
          <svg viewBox="0 0 24 24" className="h-3 w-3 stroke-current fill-none" strokeWidth={2.5}>
            <path d="M6 6l12 12M18 6 6 18" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      )}

      {preview ?? (
        <svg viewBox="0 0 24 24" className={`h-6 w-6 fill-none ${error ? 'stroke-danger' : 'stroke-text-dim'}`} strokeWidth={1.5}>
          <path d="M12 16V4m0 0 4 4m-4-4-4 4M4 16v2a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-2" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      )}

      <p className={`text-sm ${statusClass}`}>{file ? statusText : 'Drag & drop here, or'}</p>

      <div className="flex flex-wrap justify-center gap-2 mt-1">
        <button
          type="button"
          onClick={() => inputRef.current?.click()}
          className="rounded-lg border border-border bg-surface px-4 py-2 text-sm font-medium hover:border-accent/60 cursor-pointer"
        >
          Choose file
        </button>
        <button
          type="button"
          onClick={() => setShowWebcam(true)}
          className="rounded-lg border border-border bg-surface px-4 py-2 text-sm font-medium hover:border-accent/60 cursor-pointer"
        >
          {webcamLabel}
        </button>
      </div>

      <p className="text-xs font-medium text-text mt-1">
        {label}
        {required && <span className="text-danger"> *</span>}
      </p>
    </div>
  )
}
