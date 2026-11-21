/**
 * FilterBuilder — builder dinamico de filtros estilo patrón premium / patrón premium.
 * Generico: parametrizado por la lista de campos disponibles.
 *
 *   [⚲ Filtros (2)]
 *
 * Click abre un dropdown con:
 *   DONDE [campo ▾]  [op]  [valor]   🗑️
 *   Y     [campo ▾]  [op]  [valor]   🗑️
 *   + Añadir filtro                      X Limpiar todo
 *
 * Empty state compacto (320px) — solo "+ Añadir filtro" + texto helper.
 * Con filtros: panel 680px con rows.
 *
 * Operadores fijos por tipo:
 *   select    → 'eq' (es)
 *   text      → 'contains' (contiene)
 *   date_from → 'gte' (desde)
 *   date_to   → 'lte' (hasta)
 *   bool      → 'true' (sí)
 *
 * Props:
 *   fields  — [{ v, label, type, icon?, options?, searchable?, placeholder? }]
 *             options: [{value, label}] para type=select
 *   values  — dict { fieldKey: currentValue }
 *   onChange— (newValues) => void  (recibe dict con TODOS los keys del fields,
 *             vacios cuando no hay filtro activo)
 */
import { useState, useRef, useEffect, useMemo } from 'react'
import FieldPicker from './FieldPicker'
import {
  Filter, Plus, Trash2, X, ChevronDown,
} from 'lucide-react'
import PortalSelect from './PortalSelect'

const OPERATORS_BY_TYPE = {
  select:    [{ v: 'eq', label: 'es' }],
  text:      [{ v: 'contains', label: 'contiene' }],
  date_from: [{ v: 'gte', label: 'desde' }],
  date_to:   [{ v: 'lte', label: 'hasta' }],
  bool:      [{ v: 'true', label: 'sí' }],
}

const defaultValueForType = (type) => type === 'bool' ? true : ''

// Convierte el dict externo en lista de filas {id, field, value}
function buildFromValues(values, fields) {
  const list = []
  for (const f of fields) {
    const v = values?.[f.v]
    const has = f.type === 'bool' ? v === true : (v !== '' && v != null)
    if (has) list.push({ id: f.v, field: f.v, value: v })
  }
  return list
}

export default function FilterBuilder({
  fields,
  values = {},
  onChange,
  buttonLabel = 'Filtros',
}) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(() => buildFromValues(values, fields))
  const ref = useRef(null)

  // Resync solo cuando externalmente todo se limpia (clearFilters del parent)
  const externalIsEmpty = useMemo(() => {
    return fields.every(f => {
      const v = values?.[f.v]
      return f.type === 'bool' ? v !== true : (v === '' || v == null)
    })
  }, [fields, values])
  useEffect(() => {
    if (externalIsEmpty && draft.length > 0) setDraft([])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [externalIsEmpty])

  const appliedCount = useMemo(() =>
    draft.filter(f => f.value === true || (f.value !== '' && f.value != null)).length,
    [draft]
  )

  // Click afuera (excluye popups portalizados)
  useEffect(() => {
    if (!open) return
    const handler = (e) => {
      if (!ref.current) return
      if (ref.current.contains(e.target)) return
      if (e.target.closest && e.target.closest('[data-filter-popup]')) return
      setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  const propagate = (newDraft) => {
    setDraft(newDraft)
    const dict = {}
    for (const f of fields) {
      dict[f.v] = f.type === 'bool' ? false : ''
    }
    newDraft.forEach(f => {
      if (!f.field || f.value === '' || f.value == null) return
      const def = fields.find(x => x.v === f.field)
      if (!def) return
      dict[f.field] = def.type === 'bool' ? !!f.value : f.value
    })
    onChange && onChange(dict)
  }

  const addFilter = () => {
    const used = new Set(draft.map(f => f.field))
    const next = fields.find(f => !used.has(f.v))
    if (!next) return
    const newRow = {
      id: `f-${Date.now()}-${Math.random()}`,
      field: next.v,
      value: defaultValueForType(next.type),
    }
    const newDraft = [...draft, newRow]
    // Solo propagar si el valor default es valido (bool=true)
    if (newRow.value === true) propagate(newDraft)
    else setDraft(newDraft)
  }

  const removeFilter = (id) => {
    propagate(draft.filter(f => f.id !== id))
  }

  const hasMeaningfulValue = (row) =>
    row && (row.value === true || (row.value !== '' && row.value != null))

  const updateFilter = (id, patch) => {
    const oldRow = draft.find(f => f.id === id)
    const oldActive = hasMeaningfulValue(oldRow)

    const newDraft = draft.map(f => f.id === id ? { ...f, ...patch } : f)
    if ('field' in patch) {
      const newField = fields.find(x => x.v === patch.field)
      if (newField) {
        const idx = newDraft.findIndex(f => f.id === id)
        newDraft[idx] = { ...newDraft[idx], value: defaultValueForType(newField.type) }
      }
    }
    const newActive = hasMeaningfulValue(newDraft.find(f => f.id === id))

    // Solo dispara fetch al parent si el cambio afecta a un filtro activo
    if (oldActive || newActive) propagate(newDraft)
    else setDraft(newDraft)
  }

  const clearAll = () => propagate([])

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border text-sm font-medium transition-colors
          ${appliedCount > 0
            ? 'border-indigo-300 bg-indigo-50 text-indigo-700 hover:bg-indigo-100'
            : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'}`}
      >
        <Filter size={14} />
        {buttonLabel}
        {appliedCount > 0 && (
          <span className="bg-indigo-600 text-white text-[10px] font-bold px-1.5 py-0.5 rounded-full min-w-[18px] text-center leading-tight">
            {appliedCount}
          </span>
        )}
      </button>

      {open && (
        <div
          className={`absolute top-full left-0 mt-2 z-40 bg-white border border-gray-200 rounded-xl shadow-[0_12px_40px_rgba(0,0,0,0.12)] max-w-[calc(100vw-2rem)] ${
            draft.length === 0 ? 'w-[320px]' : 'w-[680px]'
          }`}
        >
          {draft.length === 0 ? (
            <>
              <button
                onClick={addFilter}
                className="w-full inline-flex items-center gap-2 px-4 py-2.5 text-sm text-indigo-600 hover:bg-indigo-50 font-medium transition-colors rounded-t-xl"
              >
                <Plus size={14} /> Añadir filtro
              </button>
              <p className="px-4 py-2.5 text-xs text-gray-400 border-t border-gray-100 text-center rounded-b-xl bg-gray-50/40">
                No hay filtros añadidos
              </p>
            </>
          ) : (
            <>
              <div className="wa-scrollbar p-4 max-h-[60vh] overflow-y-auto overflow-x-hidden">
                <div className="space-y-2.5">
                  {draft.map((f, idx) => (
                    <FilterRow
                      key={f.id}
                      filter={f}
                      isFirst={idx === 0}
                      fields={fields}
                      onChange={(patch) => updateFilter(f.id, patch)}
                      onRemove={() => removeFilter(f.id)}
                      usedFields={new Set(draft.filter(x => x.id !== f.id).map(x => x.field))}
                    />
                  ))}
                </div>
              </div>
              <div className="flex items-center gap-2 px-4 py-2.5 border-t border-gray-100 bg-gray-50/40 rounded-b-xl">
                <button
                  onClick={addFilter}
                  disabled={draft.length >= fields.length}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs text-indigo-600 hover:bg-indigo-50 font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <Plus size={13} /> Añadir filtro
                </button>
                <button
                  onClick={clearAll}
                  className="ml-auto inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs text-gray-500 hover:text-gray-700 hover:bg-gray-100"
                >
                  <X size={11} /> Limpiar todo
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function FilterRow({ filter, isFirst, fields, onChange, onRemove, usedFields }) {
  const fieldDef = fields.find(f => f.v === filter.field) || fields[0]
  const operators = OPERATORS_BY_TYPE[fieldDef.type] || OPERATORS_BY_TYPE.text

  return (
    <div className="flex items-center gap-2 group">
      <span className="text-[11px] font-medium uppercase tracking-wide text-gray-400 w-10 shrink-0 text-right">
        {isFirst ? 'Donde' : 'Y'}
      </span>
      <FieldPicker
        fields={fields}
        value={filter.field}
        onChange={(v) => onChange({ field: v })}
        usedFields={usedFields}
      />
      <span className="text-[11px] font-medium text-gray-500 bg-gray-100 px-2 py-1 rounded select-none whitespace-nowrap">
        {operators[0].label}
      </span>
      <div className="flex-1 min-w-0">
        <ValueInput
          field={fieldDef}
          value={filter.value}
          onChange={(v) => onChange({ value: v })}
        />
      </div>
      <button
        onClick={onRemove}
        className="text-gray-300 hover:text-red-500 p-1.5 rounded-md hover:bg-red-50 transition-colors opacity-60 group-hover:opacity-100"
        title="Eliminar filtro"
      >
        <Trash2 size={13} />
      </button>
    </div>
  )
}

// V067.10 — FieldPicker movido a components/ui/FieldPicker.jsx
// para deduplicacion (antes existia copia identica en AdvancedFilters.jsx).
// El import se hace al tope del archivo.

function ValueInput({ field, value, onChange }) {
  const cls = "w-full text-xs border border-gray-200 rounded-md px-2.5 py-1.5 bg-white hover:border-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-400 transition-colors"

  if (field.type === 'select') {
    if (field.groups) {
      return <PortalSelect
        value={value} onChange={onChange}
        groups={field.groups}
        placeholder={field.placeholder || '— Seleccionar —'}
        searchable={field.searchable}
      />
    }
    return <PortalSelect
      value={value} onChange={onChange}
      options={field.options || []}
      placeholder={field.placeholder || '— Seleccionar —'}
      searchable={field.searchable}
    />
  }
  if (field.type === 'date_from' || field.type === 'date_to') {
    return <input type="date" value={value || ''} onChange={e => onChange(e.target.value)} className={cls} />
  }
  if (field.type === 'bool') {
    return (
      <label className="flex items-center gap-1.5 text-xs text-gray-700 px-2">
        <input type="checkbox" checked={!!value} onChange={e => onChange(e.target.checked)} className="rounded" />
        {field.boolLabel || 'Sí'}
      </label>
    )
  }
  return (
    <input type="text" value={value || ''} onChange={e => onChange(e.target.value)}
      placeholder={field.placeholder || ''} className={cls} />
  )
}
