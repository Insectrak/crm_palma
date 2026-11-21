/**
 * SaveViewModal — modal para crear una vista nueva o renombrar/duplicar
 * una existente. Captura el estado actual (filtros + sort + columnas)
 * en el momento de guardar; el caller le pasa ese snapshot.
 */
import { useState } from 'react'
import { X, Star } from 'lucide-react'
import { VIEW_COLORS as COLORS } from '@/lib/viewColors'

export default function SaveViewModal({
  mode = 'create',         // 'create' | 'rename'
  initial = null,          // vista actual cuando se renombra/duplica
  onClose,
  onSave,                  // (payload) => Promise
}) {
  const [name,       setName]       = useState(initial?.name || '')
  const [color,      setColor]      = useState(initial?.color || 'indigo')
  const [isDefault,  setIsDefault]  = useState(!!initial?.is_default)
  const [submitting, setSubmitting] = useState(false)
  const [error,      setError]      = useState(null)

  const handleSave = async () => {
    if (!name.trim()) {
      setError('Poné un nombre para la vista.')
      return
    }
    setSubmitting(true)
    setError(null)
    try {
      // V063 fase 1: solo vistas personales. Cuando extendamos a equipo/
      // publicas reactivamos el selector de visibilidad.
      await onSave({
        name: name.trim(),
        share_level: 'personal',
        team_supervisor_id: null,
        color,
        is_default: isDefault,
      })
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Error al guardar la vista.')
    } finally {
      setSubmitting(false)
    }
  }

  const title = mode === 'rename' ? 'Editar vista' : 'Guardar como vista'

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md">
        <div className="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900">{title}</h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600" type="button">
            <X size={16} />
          </button>
        </div>

        <div className="px-5 py-4 space-y-4">
          {/* Nombre */}
          <div>
            <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1">
              Nombre
            </label>
            <input
              type="text"
              value={name}
              onChange={e => setName(e.target.value)}
              placeholder="Mis leads urgentes…"
              className="w-full text-sm border border-gray-200 rounded-md px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              autoFocus
              maxLength={120}
            />
          </div>

          {/* Color — paleta amplia tipo patrón premium/patrón premium (16 tonos). Grilla
              de 8 cols para que entre cómodo en cualquier viewport. */}
          <div>
            <label className="block text-[11px] font-semibold text-gray-500 uppercase tracking-wide mb-1.5">
              Color
            </label>
            <div className="grid grid-cols-8 gap-1.5">
              {COLORS.map(c => (
                <button
                  key={c.value}
                  type="button"
                  onClick={() => setColor(c.value)}
                  className={`w-7 h-7 rounded-full transition-all ${color === c.value ? 'ring-2 ring-offset-2 ring-gray-800 scale-110' : 'hover:scale-110 hover:ring-1 hover:ring-gray-300'}`}
                  style={{ backgroundColor: c.hex }}
                  title={c.label}
                  aria-label={c.label}
                />
              ))}
            </div>
          </div>

          {/* Default */}
          <label className="flex items-center gap-2 cursor-pointer pt-1">
            <input
              type="checkbox"
              checked={isDefault}
              onChange={e => setIsDefault(e.target.checked)}
              className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
            />
            <Star size={12} className={isDefault ? 'text-amber-500 fill-amber-400' : 'text-gray-400'} />
            <span className="text-sm text-gray-700">
              Cargar esta vista por default al entrar a Leads
            </span>
          </label>

          {error && (
            <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded-md px-3 py-2">
              {error}
            </div>
          )}
        </div>

        <div className="px-5 py-3 border-t border-gray-100 flex justify-end gap-2">
          <button
            onClick={onClose}
            disabled={submitting}
            className="px-3 py-1.5 rounded-md text-sm text-gray-600 hover:bg-gray-100 disabled:opacity-50"
            type="button"
          >
            Cancelar
          </button>
          <button
            onClick={handleSave}
            disabled={submitting || !name.trim()}
            className="px-3 py-1.5 rounded-md text-sm font-medium bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
            type="button"
          >
            {submitting ? 'Guardando…' : (mode === 'rename' ? 'Guardar cambios' : 'Crear vista')}
          </button>
        </div>
      </div>
    </div>
  )
}
