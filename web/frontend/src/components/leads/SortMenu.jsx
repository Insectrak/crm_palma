/**
 * SortMenu — menú de ordenación estilo patrón premium / patrón premium.
 *
 *   [⇅ Ordenar (1)]
 *
 * Click abre un dropdown con:
 *   [📅 fecha_ingreso ▾]  [9 → 1 ▾]   🗑️
 *   + Añadir opción de ordenación
 *
 * Soporta múltiples órdenes (primero por A, después por B).
 */
import { useState, useRef, useEffect } from 'react'
import { ArrowUpDown, Plus, Trash2 } from 'lucide-react'

const SORT_FIELDS = [
  // V094 — "Actividad reciente" es el sort por DEFAULT del backend si el
  // user no elige nada (patron estandar). Aqui aparece al tope del menu
  // para que se descubra rapido y el user pueda re-aplicarlo si lo cambio.
  { v: 'actividad_reciente',     label: 'Actividad reciente (default)', type: 'date' },
  { v: 'ultima_actividad',       label: 'Última actividad',             type: 'date' },
  { v: 'fecha_ingreso',          label: 'Fecha de creación',            type: 'date' },
  { v: 'fecha_asignacion',       label: 'Fecha de asignación',          type: 'date' },
  { v: 'fecha_primer_contacto',  label: 'Fecha primer contacto',        type: 'date' },
  { v: 'fecha_ultimo_contacto',  label: 'Fecha último contacto',        type: 'date' },
  { v: 'updated_at',             label: 'Última actualización',         type: 'date' },
  { v: 'nombre_completo',        label: 'Nombre',                       type: 'text' },
  { v: 'estado_id',              label: 'Estado',                       type: 'text' },
  { v: 'intentos_contacto',      label: 'Cantidad de contactos',        type: 'number' },
]

const DIR_LABELS_NUMBER = {
  desc: 'De mayor a menor (9 → 1)',
  asc:  'De menor a mayor (1 → 9)',
}

const DIR_LABELS_DATE = {
  desc: 'Más reciente primero',
  asc:  'Más antiguo primero',
}

const DIR_LABELS_TEXT = {
  asc:  'A → Z',
  desc: 'Z → A',
}

const getDirLabel = (field, dir) => {
  const fieldObj = SORT_FIELDS.find(f => f.v === field)
  const type = fieldObj?.type || (field === 'intentos_contacto' ? 'number' : 'date')
  if (type === 'number') return DIR_LABELS_NUMBER[dir] || dir
  if (type === 'text') return DIR_LABELS_TEXT[dir] || dir
  return DIR_LABELS_DATE[dir] || dir
}

export default function SortMenu({ sorts = [], onChange }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const isText = (field) => field === 'nombre_completo' || field === 'estado_id'

  const addSort = () => {
    const used = new Set(sorts.map(s => s.field))
    const next = SORT_FIELDS.find(f => !used.has(f.v))
    if (!next) return
    onChange([...sorts, { field: next.v, dir: 'desc' }])
  }

  const updateSort = (idx, patch) => {
    const next = sorts.map((s, i) => i === idx ? { ...s, ...patch } : s)
    onChange(next)
  }

  const removeSort = (idx) => onChange(sorts.filter((_, i) => i !== idx))

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border text-sm font-medium transition-colors
          ${sorts.length > 0
            ? 'border-indigo-300 bg-indigo-50 text-indigo-700 hover:bg-indigo-100'
            : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'}`}
      >
        <ArrowUpDown size={14} />
        Ordenar
        {sorts.length > 0 && (
          <span className="bg-indigo-600 text-white text-[10px] font-bold px-1.5 py-0.5 rounded-full min-w-[18px] text-center leading-tight">
            {sorts.length}
          </span>
        )}
      </button>

      {open && (
        // V069.1 — Standard pattern compartido con FilterBuilder/AdvancedFilters:
        //   empty state  -> 320px compacto, solo CTA "Añadir orden"
        //   con orders   -> 480px ancho para los rows (campo + direccion + remove)
        <div
          className={`absolute top-full left-0 mt-2 z-40 bg-white border border-gray-200 rounded-xl shadow-[0_12px_40px_rgba(0,0,0,0.12)] max-w-[calc(100vw-2rem)] ${
            sorts.length === 0 ? 'w-[320px]' : 'w-[480px]'
          }`}
        >
          {sorts.length === 0 ? (
            // Empty state compacto estilo patrón premium (paridad con FilterBuilder)
            <>
              <button
                onClick={addSort}
                className="w-full inline-flex items-center gap-2 px-4 py-2.5 text-sm text-indigo-600 hover:bg-indigo-50 font-medium transition-colors rounded-t-xl"
              >
                <Plus size={14} /> Añadir orden
              </button>
              <p className="px-4 py-2.5 text-xs text-gray-400 border-t border-gray-100 text-center rounded-b-xl bg-gray-50/40">
                Por defecto: más recientes primero
              </p>
            </>
          ) : (
            <>
              {/* Body */}
              <div className="wa-scrollbar p-4 max-h-[60vh] overflow-y-auto overflow-x-hidden">
                <div className="space-y-2.5">
                  {sorts.map((s, idx) => {
                    const used = new Set(sorts.filter((_, i) => i !== idx).map(x => x.field))
                    const text = isText(s.field)
                    return (
                      <div key={idx} className="flex items-center gap-2 group">
                        <span className="text-[11px] font-medium uppercase tracking-wide text-gray-400 w-10 shrink-0 text-right">
                          {idx === 0 ? 'Por' : 'Y'}
                        </span>
                        <select
                          value={s.field}
                          onChange={e => updateSort(idx, { field: e.target.value })}
                          className="flex-1 text-xs font-medium border border-gray-200 rounded-md px-2.5 py-1.5 bg-white hover:border-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-400 transition-colors cursor-pointer"
                        >
                          {SORT_FIELDS.map(f => (
                            <option key={f.v} value={f.v} disabled={used.has(f.v)}>
                              {f.label}{used.has(f.v) ? ' (en uso)' : ''}
                            </option>
                          ))}
                        </select>
                        <select
                          value={s.dir}
                          onChange={e => updateSort(idx, { dir: e.target.value })}
                          className="text-xs border border-gray-200 rounded-md px-2.5 py-1.5 bg-white hover:border-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-400 min-w-[165px] cursor-pointer transition-colors"
                        >
                          <option value="desc">{getDirLabel(s.field, 'desc')}</option>
                          <option value="asc">{getDirLabel(s.field, 'asc')}</option>
                        </select>
                        <button
                          onClick={() => removeSort(idx)}
                          className="text-gray-300 hover:text-red-500 p-1.5 rounded-md hover:bg-red-50 transition-colors opacity-60 group-hover:opacity-100"
                          title="Quitar ordenación"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    )
                  })}
                </div>
              </div>
              {/* Footer */}
              <div className="flex items-center gap-2 px-4 py-2.5 border-t border-gray-100 bg-gray-50/40 rounded-b-xl">
                <button
                  onClick={addSort}
                  disabled={sorts.length >= SORT_FIELDS.length}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs text-indigo-600 hover:bg-indigo-50 font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <Plus size={13} /> Añadir orden
                </button>
                <button
                  onClick={() => onChange([])}
                  className="ml-auto inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs text-gray-500 hover:text-gray-700 hover:bg-gray-100"
                >
                  <Trash2 size={11} /> Limpiar
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}
