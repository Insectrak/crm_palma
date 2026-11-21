import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Check, RotateCcw, X } from 'lucide-react'

/**
 * UndoToast — Toast premium con botón "Deshacer".
 *
 * Patrón estándar de la industria (correo profesional, patrón premium, patrón estándar, patrón premium): tras una
 * operación reversible mostramos un toast no-modal por 8 segundos con la
 * opción de revertir. Mejor que confirmar antes — el usuario no sufre
 * fricción cuando todo va bien, pero tiene una salida si se equivocó.
 *
 * Diseño:
 *   - Provider único montado en App.jsx → un solo toast a la vez (cola FIFO).
 *   - Hook `useUndoToast()` expone `showUndoToast({ message, onUndo, durationMs })`.
 *   - El onUndo es responsabilidad del caller (típicamente otro API call al
 *     endpoint inverso). Si onUndo no se pasa, se muestra como toast simple
 *     de éxito (compat con saves sin reversa).
 *   - Pause-on-hover: si el usuario está mirando el toast, no se cierra.
 *   - Auto-cierre limpia el timer si el usuario aprieta Deshacer o X.
 *
 * Accesibilidad:
 *   - role="status" + aria-live="polite" → screen readers anuncian sin
 *     interrumpir flujos en curso.
 *   - Focus trap NO necesario: el toast es opcional, no bloqueante.
 */

const UndoToastContext = createContext({ showUndoToast: () => {}, showToast: () => {} })

export function useUndoToast() {
  return useContext(UndoToastContext)
}

export function UndoToastProvider({ children }) {
  const [toast, setToast] = useState(null)
  // {id, message, onUndo, durationMs, undoing}
  const timerRef = useRef(null)
  const pausedRef = useRef(false)
  const remainingRef = useRef(0)
  const startedAtRef = useRef(0)

  const clearTimer = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
  }, [])

  const dismiss = useCallback(() => {
    clearTimer()
    setToast(null)
  }, [clearTimer])

  const armTimer = useCallback((ms) => {
    clearTimer()
    startedAtRef.current = Date.now()
    remainingRef.current = ms
    timerRef.current = setTimeout(() => setToast(null), ms)
  }, [clearTimer])

  const handleUndo = useCallback(async () => {
    if (!toast?.onUndo) { dismiss(); return }
    clearTimer()
    setToast(t => t ? { ...t, undoing: true } : null)
    try {
      await toast.onUndo()
    } finally {
      setToast(null)
    }
  }, [toast, dismiss, clearTimer])

  const showUndoToast = useCallback(({ message, onUndo, durationMs = 8000 }) => {
    // Cualquier toast previo se descarta (FIFO con preferencia al ultimo).
    clearTimer()
    const id = Date.now() + Math.random()
    setToast({ id, message, onUndo, durationMs, undoing: false })
    armTimer(durationMs)
  }, [armTimer, clearTimer])

  // V087.1 — Compat con saves sin reversa: equivale a showUndoToast sin onUndo.
  const showToast = useCallback((message, durationMs = 3000) => {
    showUndoToast({ message, onUndo: null, durationMs })
  }, [showUndoToast])

  // Pause-on-hover: congela el timer mientras el cursor está sobre el toast.
  const onMouseEnter = useCallback(() => {
    if (!toast || pausedRef.current) return
    pausedRef.current = true
    const elapsed = Date.now() - startedAtRef.current
    remainingRef.current = Math.max(0, remainingRef.current - elapsed)
    clearTimer()
  }, [toast, clearTimer])

  const onMouseLeave = useCallback(() => {
    if (!toast || !pausedRef.current) return
    pausedRef.current = false
    armTimer(remainingRef.current)
  }, [toast, armTimer])

  useEffect(() => () => clearTimer(), [clearTimer])

  return (
    <UndoToastContext.Provider value={{ showUndoToast, showToast, dismiss }}>
      {children}
      {toast && createPortal(
        <div
          role="status"
          aria-live="polite"
          onMouseEnter={onMouseEnter}
          onMouseLeave={onMouseLeave}
          className="fixed top-4 right-4 z-[100] flex items-center gap-3 bg-slate-900 text-white pl-4 pr-2 py-2.5 rounded-xl shadow-2xl border border-slate-700/60 animate-in slide-in-from-top-2 fade-in duration-200 max-w-md"
        >
          <Check size={16} className="text-emerald-400 shrink-0" />
          <span className="text-sm leading-snug">{toast.message}</span>
          {toast.onUndo && (
            <button
              onClick={handleUndo}
              disabled={toast.undoing}
              className="flex items-center gap-1.5 ml-2 px-3 py-1.5 rounded-lg text-xs font-semibold text-amber-300 hover:text-amber-200 hover:bg-slate-800 transition-colors disabled:opacity-50"
            >
              <RotateCcw size={13} />
              {toast.undoing ? 'Deshaciendo…' : 'Deshacer'}
            </button>
          )}
          <button
            onClick={dismiss}
            aria-label="Cerrar"
            className="p-1 rounded-md text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <X size={14} />
          </button>
        </div>,
        document.body,
      )}
    </UndoToastContext.Provider>
  )
}
