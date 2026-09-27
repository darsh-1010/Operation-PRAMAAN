import { useEffect, useRef, useState } from 'react'

interface Props {
  facingMode?: 'user' | 'environment'
  onCapture: (file: File) => void
  onClose: () => void
}

/** Inline camera modal — native MediaDevices.getUserMedia, no library needed (rung 4). */
export default function WebcamCapture({ facingMode = 'user', onCapture, onClose }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode } })
      .then((stream) => {
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop())
          return
        }
        streamRef.current = stream
        if (videoRef.current) videoRef.current.srcObject = stream
      })
      .catch(() => setError('Camera access denied or unavailable'))

    return () => {
      cancelled = true
      streamRef.current?.getTracks().forEach((t) => t.stop())
    }
  }, [facingMode])

  function stop() {
    streamRef.current?.getTracks().forEach((t) => t.stop())
  }

  function capture() {
    const video = videoRef.current
    if (!video || !video.videoWidth) return
    const canvas = document.createElement('canvas')
    canvas.width = video.videoWidth
    canvas.height = video.videoHeight
    canvas.getContext('2d')?.drawImage(video, 0, 0)
    canvas.toBlob(
      (blob) => {
        if (!blob) return
        onCapture(new File([blob], `capture-${Date.now()}.jpg`, { type: 'image/jpeg' }))
        stop()
        onClose()
      },
      'image/jpeg',
      0.92,
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => (stop(), onClose())}>
      <div className="w-full max-w-md rounded-2xl border border-border bg-surface p-4" onClick={(e) => e.stopPropagation()}>
        {error ? (
          <p className="py-10 text-center text-sm text-danger">{error}</p>
        ) : (
          <video ref={videoRef} autoPlay playsInline muted className="aspect-video w-full rounded-xl bg-black object-cover" />
        )}
        <div className="mt-4 flex justify-end gap-2">
          <button
            type="button"
            onClick={() => (stop(), onClose())}
            className="rounded-lg border border-border px-4 py-2 text-sm hover:bg-surface-2 cursor-pointer"
          >
            Cancel
          </button>
          {!error && (
            <button
              type="button"
              onClick={capture}
              className="rounded-lg bg-accent px-4 py-2 text-sm font-semibold text-accent-fg hover:brightness-110 cursor-pointer"
            >
              Capture
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
