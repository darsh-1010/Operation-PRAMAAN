import { useEffect } from 'react'

export default function Modal({ onClose, children }: { onClose: () => void; children: React.ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  return (
    <div className="fixed inset-0 z-50 overflow-y-auto bg-black/60 p-4 flex items-start justify-center" onClick={onClose}>
      <div
        className="w-full max-w-4xl my-8 rounded-2xl border border-border bg-surface p-5"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex justify-end mb-2">
          <button
            onClick={onClose}
            aria-label="Close"
            className="h-8 w-8 rounded-full bg-surface-2 border border-border flex items-center justify-center hover:brightness-110"
          >
            <svg viewBox="0 0 24 24" className="h-4 w-4 stroke-current fill-none" strokeWidth={2}>
              <path d="M6 6l12 12M18 6 6 18" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>
        {children}
      </div>
    </div>
  )
}
