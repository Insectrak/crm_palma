import { AlertTriangle, Check, X, Plus, Minus, Users } from 'lucide-react'
import { Button } from '@/components/ui/button'

/**
 * ApplyChangesPreviewDialog — Modal con preview de impacto antes de guardar.
 *
 * Patrón estándar de la industria: en cambios estructurales (permisos,
 * rotación, sharing rules), NO basta con "¿Confirmar?". El usuario necesita
 * ver el **impacto concreto** antes de aplicar.
 *
 * Reemplaza el ConfirmDialog genérico para 3 superficies críticas:
 *   - Roles y permisos: cuántos usuarios afectados + diff de permisos
 *   - Reparto leads:    cambio de estrategia y a qué supervisor van los leads
 *   - Sharing rules:    qué leads/usuarios pasan a tener acceso o lo pierden
 *
 * Props:
 *   open          — boolean
 *   title         — string
 *   subtitle      — string corto, ej: "Vas a actualizar el rol 'marketing'"
 *   impactCount   — { value, label }, ej: { value: 10, label: "usuarios afectados" }
 *   adds          — string[] o {label, hint}[]: ej. permisos que se agregan
 *   removes       — string[] o {label, hint}[]: ej. permisos que se quitan
 *   notes         — node opcional para texto adicional o avisos
 *   confirmLabel  — string (default "Sí, aplicar")
 *   cancelLabel   — string (default "Volver a revisar")
 *   applying      — boolean → muestra spinner en el botón
 *   onConfirm     — () => void
 *   onCancel      — () => void
 *
 * Si adds/removes son ambos vacíos, el modal muestra solo el impactCount y
 * las notes (útil para "Vas a cambiar estrategia de rotación X → Y").
 */
export default function ApplyChangesPreviewDialog({
  open,
  title = 'Revisa el impacto de este cambio',
  subtitle,
  impactCount,
  adds = [],
  removes = [],
  notes,
  confirmLabel = 'Sí, aplicar',
  cancelLabel = 'Volver a revisar',
  applying = false,
  onConfirm,
  onCancel,
}) {
  if (!open) return null

  const showDiff = (adds && adds.length > 0) || (removes && removes.length > 0)

  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/40 backdrop-blur-sm"
        onClick={onCancel}
      />
      <div className="relative bg-white rounded-2xl shadow-xl w-full max-w-lg mx-4 animate-in fade-in zoom-in-95 duration-150 overflow-hidden">
        {/* Header */}
        <div className="px-6 pt-6 pb-4 border-b border-gray-100">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 bg-amber-50 rounded-full flex items-center justify-center shrink-0">
              <AlertTriangle size={18} className="text-amber-600" />
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="text-base font-semibold text-gray-900 leading-tight">{title}</h3>
              {subtitle && (
                <p className="text-sm text-gray-500 mt-0.5">{subtitle}</p>
              )}
            </div>
            <button
              onClick={onCancel}
              aria-label="Cerrar"
              className="p-1 rounded-md text-gray-400 hover:text-gray-600 hover:bg-gray-50 transition-colors"
            >
              <X size={16} />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="px-6 py-5 space-y-4 max-h-[60vh] overflow-y-auto">
          {/* Impacto principal: cuántos afectados */}
          {impactCount && (
            <div className="flex items-center gap-3 bg-slate-50 border border-slate-200 rounded-xl px-4 py-3">
              <Users size={18} className="text-slate-500 shrink-0" />
              <div>
                <p className="text-2xl font-semibold text-gray-900 leading-tight">
                  {impactCount.value}
                </p>
                <p className="text-xs text-gray-500">{impactCount.label}</p>
              </div>
            </div>
          )}

          {/* Diff: lo que se agrega + lo que se quita */}
          {showDiff && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              {adds && adds.length > 0 && (
                <div className="bg-emerald-50 border border-emerald-200 rounded-xl px-4 py-3">
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-emerald-700 mb-2">
                    <Plus size={13} />
                    {adds.length === 1 ? 'Se agrega' : `Se agregan (${adds.length})`}
                  </div>
                  <ul className="space-y-1">
                    {adds.map((it, i) => {
                      const label = typeof it === 'string' ? it : it.label
                      const hint  = typeof it === 'string' ? null : it.hint
                      return (
                        <li key={i} className="text-sm text-emerald-900 leading-snug flex items-start gap-1.5">
                          <Check size={12} className="text-emerald-600 mt-1 shrink-0" />
                          <span>
                            {label}
                            {hint && <span className="block text-[11px] text-emerald-700/70">{hint}</span>}
                          </span>
                        </li>
                      )
                    })}
                  </ul>
                </div>
              )}
              {removes && removes.length > 0 && (
                <div className="bg-rose-50 border border-rose-200 rounded-xl px-4 py-3">
                  <div className="flex items-center gap-1.5 text-xs font-semibold text-rose-700 mb-2">
                    <Minus size={13} />
                    {removes.length === 1 ? 'Se quita' : `Se quitan (${removes.length})`}
                  </div>
                  <ul className="space-y-1">
                    {removes.map((it, i) => {
                      const label = typeof it === 'string' ? it : it.label
                      const hint  = typeof it === 'string' ? null : it.hint
                      return (
                        <li key={i} className="text-sm text-rose-900 leading-snug flex items-start gap-1.5">
                          <X size={12} className="text-rose-600 mt-1 shrink-0" />
                          <span>
                            {label}
                            {hint && <span className="block text-[11px] text-rose-700/70">{hint}</span>}
                          </span>
                        </li>
                      )
                    })}
                  </ul>
                </div>
              )}
            </div>
          )}

          {/* Notes opcionales (warnings, explicaciones) */}
          {notes && (
            <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-sm text-amber-900 leading-relaxed">
              {notes}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 bg-gray-50 border-t border-gray-100 flex gap-3 justify-end">
          <Button
            variant="outline"
            onClick={onCancel}
            disabled={applying}
          >
            {cancelLabel}
          </Button>
          <Button
            onClick={onConfirm}
            disabled={applying}
            className="bg-amber-600 hover:bg-amber-700 text-white border-amber-600 gap-1.5"
          >
            {applying ? 'Aplicando…' : confirmLabel}
          </Button>
        </div>
      </div>
    </div>
  )
}
