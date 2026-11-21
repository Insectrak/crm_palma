import { CheckCircle2, AlertTriangle, XCircle, Info } from 'lucide-react'
import { Button } from '@/components/ui/button'

/**
 * Modal de informacion / resultado (un solo boton OK).
 * Reemplaza window.alert() para resultados de operaciones bulk,
 * errores recuperables y mensajes informativos. Estilo premium
 * tipo CRMs profesionales: card blanco con icono de color
 * segun severidad, texto legible y un solo CTA.
 *
 * Props:
 *   open      — boolean
 *   variant   — "success" | "warning" | "error" | "info" (default "info")
 *   title     — string
 *   message   — string | string[] (array → linea por bullet)
 *   okLabel   — string (default "Aceptar")
 *   onClose   — () => void
 */
export default function InfoDialog({
  open,
  variant = 'info',
  title = 'Aviso',
  message = '',
  okLabel = 'Aceptar',
  onClose,
}) {
  if (!open) return null

  const config = {
    success: { Icon: CheckCircle2, iconColor: 'text-emerald-600', bg: 'bg-emerald-100', btn: 'bg-emerald-600 hover:bg-emerald-700' },
    warning: { Icon: AlertTriangle, iconColor: 'text-amber-600',   bg: 'bg-amber-100',   btn: 'bg-amber-500 hover:bg-amber-600' },
    error:   { Icon: XCircle,       iconColor: 'text-red-600',     bg: 'bg-red-100',     btn: 'bg-red-600 hover:bg-red-700' },
    info:    { Icon: Info,          iconColor: 'text-indigo-600',  bg: 'bg-indigo-100',  btn: 'bg-indigo-600 hover:bg-indigo-700' },
  }[variant] || { Icon: Info, iconColor: 'text-indigo-600', bg: 'bg-indigo-100', btn: 'bg-indigo-600 hover:bg-indigo-700' }

  const lines = Array.isArray(message) ? message.filter(Boolean) : null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={onClose}
      />
      <div className="relative bg-white rounded-2xl shadow-xl w-full max-w-sm mx-4 p-6 animate-in fade-in zoom-in-95 duration-150">
        <div className={`w-12 h-12 rounded-full flex items-center justify-center mx-auto mb-4 ${config.bg}`}>
          <config.Icon size={22} className={config.iconColor} />
        </div>
        <h3 className="text-base font-semibold text-gray-900 text-center mb-1.5">
          {title}
        </h3>
        {lines ? (
          <ul className="text-sm text-gray-600 leading-relaxed space-y-1 mt-2">
            {lines.map((line, i) => (
              <li key={i} className="flex items-start gap-2">
                <span className={`mt-1.5 w-1 h-1 rounded-full ${config.iconColor.replace('text-', 'bg-')} shrink-0`} />
                <span>{line}</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-gray-500 text-center leading-relaxed whitespace-pre-line">
            {message}
          </p>
        )}
        <div className="mt-6">
          <Button
            className={`w-full text-white border-0 ${config.btn}`}
            onClick={onClose}
          >
            {okLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
