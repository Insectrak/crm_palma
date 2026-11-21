/**
 * SedeFormModal — crear o editar una sede.
 *
 * Validacion del codigo (slug): a-z 0-9 _- min 2 chars. El backend
 * tambien valida con regex igual; este front-side check es UX (feedback
 * inmediato) — no security boundary.
 */
import { useState } from 'react'
import { X, MapPin } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'

const COLORS = [
  '#ef4444', '#f97316', '#f59e0b', '#eab308', '#84cc16',
  '#10b981', '#14b8a6', '#06b6d4', '#0ea5e9', '#3b82f6',
  '#6366f1', '#8b5cf6', '#d946ef', '#ec4899', '#f43f5e',
  '#64748b',
]

const SLUG_RE = /^[a-z0-9][a-z0-9_-]*[a-z0-9]$/

export default function SedeFormModal({ initial, onClose, onSave }) {
  const editing = !!initial
  const [form, setForm] = useState({
    codigo:    initial?.codigo    || '',
    nombre:    initial?.nombre    || '',
    ciudad:    initial?.ciudad    || '',
    direccion: initial?.direccion || '',
    telefono:  initial?.telefono  || '',
    color_hex: initial?.color_hex || '#6366F1',
    activo:    initial?.activo ?? true,
  })
  const [error, setError]   = useState(null)
  const [saving, setSaving] = useState(false)

  const update = (patch) => setForm(p => ({ ...p, ...patch }))

  const handleSubmit = async (e) => {
    e?.preventDefault()
    setError(null)

    // Validacion front (paridad con backend)
    if (!form.codigo || form.codigo.length < 2) {
      setError('El código es obligatorio (mínimo 2 caracteres).')
      return
    }
    if (!editing && !SLUG_RE.test(form.codigo)) {
      setError('Código inválido. Usá solo a-z, 0-9, "-" y "_". Empieza y termina con letra/número.')
      return
    }
    if (!form.nombre || form.nombre.length < 2) {
      setError('El nombre es obligatorio.')
      return
    }

    setSaving(true)
    try {
      // En editar, NO mandamos codigo (es inmutable post-creacion).
      const payload = editing
        ? {
            nombre:    form.nombre.trim(),
            ciudad:    form.ciudad?.trim() || null,
            direccion: form.direccion?.trim() || null,
            telefono:  form.telefono?.trim() || null,
            color_hex: form.color_hex,
            activo:    form.activo,
          }
        : {
            codigo:    form.codigo.trim().toLowerCase(),
            nombre:    form.nombre.trim(),
            ciudad:    form.ciudad?.trim() || null,
            direccion: form.direccion?.trim() || null,
            telefono:  form.telefono?.trim() || null,
            color_hex: form.color_hex,
          }
      await onSave(payload)
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || 'No se pudo guardar.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md max-h-[90vh] overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-gray-100 px-5 py-4 flex items-center justify-between z-10">
          <h3 className="text-base font-semibold text-gray-900 flex items-center gap-2">
            <MapPin size={16} className="text-indigo-500" />
            {editing ? 'Editar sede' : 'Nueva sede'}
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600" type="button">
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="px-5 py-4 space-y-4">
          {/* Codigo (slug) */}
          <div>
            <Label className="text-xs">Código *</Label>
            <Input
              value={form.codigo}
              onChange={e => update({ codigo: e.target.value.toLowerCase() })}
              placeholder="lima"
              maxLength={40}
              autoFocus={!editing}
              disabled={editing}
              className="mt-1 font-mono text-sm"
            />
            <p className="text-[11px] text-gray-400 mt-1">
              {editing
                ? 'El código no se puede modificar después de crear la sede.'
                : 'Identificador corto en minúsculas — usado en URLs y APIs.'}
            </p>
          </div>

          {/* Nombre */}
          <div>
            <Label className="text-xs">Nombre *</Label>
            <Input
              value={form.nombre}
              onChange={e => update({ nombre: e.target.value })}
              placeholder="Sede Centro"
              maxLength={120}
              autoFocus={editing}
              className="mt-1"
            />
          </div>

          {/* Ciudad + Telefono */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <Label className="text-xs">Ciudad</Label>
              <Input
                value={form.ciudad}
                onChange={e => update({ ciudad: e.target.value })}
                placeholder="Lima"
                maxLength={80}
                className="mt-1"
              />
            </div>
            <div>
              <Label className="text-xs">Teléfono</Label>
              <Input
                value={form.telefono}
                onChange={e => update({ telefono: e.target.value })}
                placeholder="+51 1 234-5678"
                maxLength={40}
                className="mt-1"
              />
            </div>
          </div>

          {/* Direccion */}
          <div>
            <Label className="text-xs">Dirección</Label>
            <Input
              value={form.direccion}
              onChange={e => update({ direccion: e.target.value })}
              placeholder="Av. Larco 123, Miraflores"
              maxLength={255}
              className="mt-1"
            />
          </div>

          {/* Color */}
          <div>
            <Label className="text-xs">Color</Label>
            <div className="grid grid-cols-8 gap-1.5 mt-1.5">
              {COLORS.map(hex => (
                <button
                  key={hex}
                  type="button"
                  onClick={() => update({ color_hex: hex })}
                  className={`w-7 h-7 rounded-full transition-all ${
                    form.color_hex?.toLowerCase() === hex.toLowerCase()
                      ? 'ring-2 ring-offset-2 ring-gray-800 scale-110'
                      : 'hover:scale-110 hover:ring-1 hover:ring-gray-300'
                  }`}
                  style={{ backgroundColor: hex }}
                  title={hex}
                />
              ))}
            </div>
          </div>

          {/* Activo (solo en edicion) */}
          {editing && (
            <label className="flex items-center gap-2 cursor-pointer pt-1">
              <input
                type="checkbox"
                checked={form.activo}
                onChange={e => update({ activo: e.target.checked })}
                className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
              />
              <span className="text-sm text-gray-700">Sede activa</span>
            </label>
          )}

          {error && (
            <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded-md px-3 py-2">
              {error}
            </div>
          )}
        </form>

        <div className="sticky bottom-0 bg-white border-t border-gray-100 px-5 py-3 flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancelar
          </Button>
          <Button onClick={handleSubmit} disabled={saving}>
            {saving ? 'Guardando…' : (editing ? 'Guardar cambios' : 'Crear sede')}
          </Button>
        </div>
      </div>
    </div>
  )
}
