import { useEffect, useRef } from 'react'
import { X } from 'lucide-react'

const SIZE_CLASSES = {
  sm: 'max-w-md',
  md: 'max-w-lg',
  lg: 'max-w-2xl',
  xl: 'max-w-3xl',
}

export function Dialog({ open, onClose, children, size = 'md' }) {
  const overlayRef = useRef(null)
  // V5.63 — anti close-on-text-drag (patron Radix/shadcn).
  // Bug reportado por Soporte: al seleccionar texto dentro de un input del
  // modal y arrastrar el cursor fuera, al soltar el mouse el modal se
  // cerraba aunque el usuario no quiso cerrarlo. Causa: el evento `click`
  // del overlay se dispara cuando el `mouseup` final cae en el overlay,
  // sin importar donde empezo el `mousedown`.
  // Fix: solo cerrar si AMBOS extremos del gesto (down + up) cayeron en
  // el overlay. Si el down fue en el modal (input, texto, etc), nunca
  // cerramos — el usuario esta seleccionando, no cerrando.
  const pointerDownTargetRef = useRef(null)

  useEffect(() => {
    if (!open) return
    const handleKey = (e) => { if (e.key === 'Escape') onClose() }
    document.addEventListener('keydown', handleKey)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', handleKey)
      document.body.style.overflow = ''
    }
  }, [open, onClose])

  if (!open) return null

  const sizeClass = SIZE_CLASSES[size] || SIZE_CLASSES.md

  return (
    <div
      ref={overlayRef}
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm p-4 overflow-y-auto"
      onPointerDown={(e) => { pointerDownTargetRef.current = e.target }}
      onClick={(e) => {
        // Cierra solo si ambos extremos del gesto cayeron en el overlay.
        // Si pointerdown fue dentro del modal (seleccion de texto), el
        // up fuera NO debe cerrar.
        if (
          e.target === overlayRef.current
          && pointerDownTargetRef.current === overlayRef.current
        ) {
          onClose()
        }
        pointerDownTargetRef.current = null
      }}
    >
      <div className={`bg-white rounded-2xl shadow-2xl w-full ${sizeClass} my-8 animate-in fade-in zoom-in-95`}>
        {children}
      </div>
    </div>
  )
}

export function DialogHeader({ children, onClose }) {
  return (
    <div className="flex items-center justify-between px-6 pt-6 pb-2">
      <h2 className="text-lg font-semibold text-gray-900">{children}</h2>
      {onClose && (
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 transition-colors">
          <X size={20} />
        </button>
      )}
    </div>
  )
}

export function DialogContent({ children }) {
  return <div className="px-6 pb-6">{children}</div>
}
