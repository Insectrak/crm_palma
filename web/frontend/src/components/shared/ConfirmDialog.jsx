import { AlertTriangle, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'

/**
 * Modal de confirmación profesional.
 * Reemplaza window.confirm() nativo del navegador.
 *
 * Props:
 *   open       — boolean
 *   title      — string  (ej: "Eliminar contacto")
 *   message    — string  (ej: "¿Estás seguro de que deseas eliminar este registro?")
 *   confirmLabel — string (default: "Eliminar")
 *   cancelLabel  — string (default: "Cancelar")
 *   variant    — "danger" | "warning" (default: "danger")
 *   onConfirm  — () => void
 *   onCancel   — () => void
 */
export default function ConfirmDialog({
  open,
  title = 'Confirmar acción',
  message = '¿Estás seguro de que deseas continuar? Esta acción no se puede deshacer.',
  confirmLabel = 'Eliminar',
  cancelLabel = 'Cancelar',
  variant = 'danger',
  onConfirm,
  onCancel,
}) {
  if (!open) return null

  const isDanger = variant === 'danger'

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center">
      {/* Overlay */}
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={onCancel}
      />
      {/* Panel */}
      <div className="relative bg-white rounded-2xl shadow-xl w-full max-w-sm mx-4 p-6 animate-in fade-in zoom-in-95 duration-150">
        {/* Ícono */}
        <div className={`w-12 h-12 rounded-full flex items-center justify-center mx-auto mb-4 ${
          isDanger ? 'bg-red-100' : 'bg-amber-100'
        }`}>
          {isDanger
            ? <Trash2 size={22} className="text-red-600" />
            : <AlertTriangle size={22} className="text-amber-600" />
          }
        </div>

        {/* Texto */}
        <h3 className="text-base font-semibold text-gray-900 text-center mb-1.5">
          {title}
        </h3>
        <p className="text-sm text-gray-500 text-center leading-relaxed">
          {message}
        </p>

        {/* Acciones */}
        <div className="flex gap-3 mt-6">
          <Button
            variant="outline"
            className="flex-1"
            onClick={onCancel}
          >
            {cancelLabel}
          </Button>
          <Button
            className={`flex-1 gap-1.5 ${
              isDanger
                ? 'bg-red-600 hover:bg-red-700 text-white border-red-600'
                : 'bg-amber-500 hover:bg-amber-600 text-white border-amber-500'
            }`}
            onClick={onConfirm}
          >
            {isDanger && <Trash2 size={14} />}
            {confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
