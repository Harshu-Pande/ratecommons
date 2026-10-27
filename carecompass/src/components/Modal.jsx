import { useEffect } from 'react'
import { X } from 'lucide-react'

export default function Modal({ title, children, onClose, footer }) {
  useEffect(() => {
    const esc = (e) => e.key === 'Escape' && onClose()
    document.addEventListener('keydown', esc)
    return () => document.removeEventListener('keydown', esc)
  }, [onClose])
  return (
    <div className="fixed inset-0 z-[2600] flex items-end justify-center bg-ink/50 sm:items-center sm:p-6" onClick={onClose}
      role="dialog" aria-modal="true" aria-label={title}>
      <div className="flex max-h-[94dvh] w-full max-w-3xl flex-col overflow-hidden rounded-t-3xl bg-canvas shadow-pop sm:rounded-3xl"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between border-b border-line bg-white px-5 py-4">
          <h2 className="text-lg font-bold">{title}</h2>
          <button onClick={onClose} className="rounded-full p-2 hover:bg-canvas" aria-label="Close"><X className="h-5 w-5" /></button>
        </div>
        <div className="overflow-y-auto p-4 sm:p-6">{children}</div>
        {footer && <div className="border-t border-line bg-white p-4">{footer}</div>}
      </div>
    </div>
  )
}
