/**
 * FieldMappings — gestión de propiedades custom y mapeos de formularios.
 *
 * Panel admin al patrón estándar ("Data Management > Properties") y
 * patrón estándar ("Object Manager > Custom Fields & Field Mapping"):
 *
 *   Tab 1 — Propiedades
 *     Catálogo de propiedades custom tipadas (text, number, date, select…).
 *     Las propiedades creadas aquí quedan disponibles como target de
 *     mapeos y se muestran en el detalle de cada lead.
 *
 *   Tab 2 — Mapeos
 *     Regla "meta_field_name → target" (columna nativa, propiedad custom
 *     o ignore). Se aplica durante la ingesta de cada webhook de Meta.
 *
 *   Tab 3 — Sin mapear
 *     Campos detectados en submits recientes que no tienen regla aún —
 *     la to-do list del admin.
 */
import { useEffect, useMemo, useState, useCallback, useRef } from 'react'
import {
  Database, Tag, List as ListIcon, Plus, Save, Trash2, Edit3, X,
  RefreshCw, AlertCircle, CheckCircle2, Search, Filter,
  SlidersHorizontal, Sparkles, Columns3, Layers,
  Calendar, Hash, ToggleLeft, Type as TypeIcon, ChevronDown,
  ArrowRight, Zap, Eraser, ShieldAlert, Loader2,
} from 'lucide-react'
import api from '@/lib/api'
import { Card, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import LoadingSpinner from '@/components/shared/LoadingSpinner'
import EmptyState from '@/components/shared/EmptyState'
import ConfirmDialog from '@/components/shared/ConfirmDialog'
import { cn } from '@/lib/utils'

/* ─────────────────────────────────────────────────────────────────────── */
/* Helpers de presentación                                                  */
/* ─────────────────────────────────────────────────────────────────────── */

const TYPE_META = {
  text:    { label: 'Texto',   icon: TypeIcon,    tone: 'bg-slate-50 text-slate-700 ring-slate-200' },
  number:  { label: 'Número',  icon: Hash,        tone: 'bg-blue-50 text-blue-700 ring-blue-200' },
  date:    { label: 'Fecha',   icon: Calendar,    tone: 'bg-violet-50 text-violet-700 ring-violet-200' },
  boolean: { label: 'Sí/No',   icon: ToggleLeft,  tone: 'bg-amber-50 text-amber-700 ring-amber-200' },
  select:  { label: 'Opción',  icon: ListIcon,    tone: 'bg-emerald-50 text-emerald-700 ring-emerald-200' },
}

const TARGET_META = {
  column:   { label: 'Columna nativa',    icon: Columns3, tone: 'bg-indigo-50 text-indigo-700 ring-indigo-200' },
  property: { label: 'Propiedad custom',  icon: Sparkles, tone: 'bg-violet-50 text-violet-700 ring-violet-200' },
  ignore:   { label: 'Ignorar',           icon: X,        tone: 'bg-gray-50 text-gray-500 ring-gray-200' },
}

function TypeChip({ type, size = 'sm' }) {
  const m = TYPE_META[type] || TYPE_META.text
  const Icon = m.icon
  return (
    <span className={cn(
      'inline-flex items-center gap-1 rounded-md ring-1 font-medium',
      size === 'sm' ? 'px-1.5 py-0.5 text-[11px]' : 'px-2 py-1 text-xs',
      m.tone,
    )}>
      <Icon size={size === 'sm' ? 10 : 12} /> {m.label}
    </span>
  )
}

function TargetChip({ type, name }) {
  const m = TARGET_META[type] || TARGET_META.column
  const Icon = m.icon
  return (
    <span className={cn(
      'inline-flex items-center gap-1.5 px-2 py-1 rounded-md ring-1 text-xs font-medium',
      m.tone,
    )}>
      <Icon size={11} />
      <span className="opacity-75">{m.label}</span>
      {name && type !== 'ignore' && (
        <>
          <span className="opacity-30">·</span>
          <span className="font-semibold">{name}</span>
        </>
      )}
    </span>
  )
}

function slugify(raw) {
  if (!raw) return ''
  return raw.toString()
    .normalize('NFKD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/\s+/g, '_')
    .replace(/[^a-z0-9_]+/g, '_')
    .replace(/^_+|_+$/g, '')
}

/* ─────────────────────────────────────────────────────────────────────── */
/* Modal de propiedad — crear / editar                                      */
/* ─────────────────────────────────────────────────────────────────────── */

function PropertyModal({ open, initial, onClose, onSaved, allowedTypes }) {
  const isEdit = !!initial?.property_key
  const [displayName, setDisplayName] = useState('')
  const [key, setKey]                 = useState('')
  const [keyTouched, setKeyTouched]   = useState(false)
  const [type, setType]               = useState('text')
  const [description, setDescription] = useState('')
  const [category, setCategory]       = useState('')
  const [optionsText, setOptionsText] = useState('')
  const [saving, setSaving]           = useState(false)
  const [error, setError]             = useState(null)

  useEffect(() => {
    if (!open) return
    setDisplayName(initial?.display_name || '')
    setKey(initial?.property_key || '')
    setKeyTouched(!!initial?.property_key)
    setType(initial?.property_type || 'text')
    setDescription(initial?.description || '')
    setCategory(initial?.category || '')
    setOptionsText(
      Array.isArray(initial?.options) ? initial.options.join('\n') : ''
    )
    setError(null)
  }, [open, initial])

  // Al editar display name, el key se auto-sluga hasta que el admin lo
  // edite manualmente. Tras eso, se fija. En modo edición, el key es
  // inmutable (PK lógica).
  useEffect(() => {
    if (isEdit || keyTouched) return
    setKey(slugify(displayName))
  }, [displayName, keyTouched, isEdit])

  const handleSave = async () => {
    setError(null)
    if (!displayName.trim()) { setError('El nombre visible es obligatorio.'); return }
    if (!key.trim())         { setError('La clave interna es obligatoria.');  return }

    let options = null
    if (type === 'select') {
      options = optionsText.split('\n').map(s => s.trim()).filter(Boolean)
      if (!options.length) { setError('Para tipo "Opción" indica al menos un valor.'); return }
    }

    setSaving(true)
    try {
      const payload = {
        property_key:  key.trim(),
        display_name:  displayName.trim(),
        property_type: type,
        options,
        description:   description.trim() || null,
        category:      category.trim() || null,
      }
      const res = await api.post('/api/integrations/field-mappings/properties', payload)
      onSaved?.(res.data)
      onClose()
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo guardar la propiedad.')
    } finally {
      setSaving(false)
    }
  }

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-sm flex items-start justify-center pt-16 px-4"
         onClick={onClose}>
      <div
        className="bg-white w-full max-w-lg rounded-2xl shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-violet-50 text-violet-600 flex items-center justify-center">
              <Sparkles size={17} />
            </div>
            <div>
              <h3 className="text-base font-semibold text-gray-900">
                {isEdit ? 'Editar propiedad' : 'Nueva propiedad'}
              </h3>
              <p className="text-xs text-gray-500">
                Campo custom que aparecerá en cada lead y estará disponible como target de mapeos.
              </p>
            </div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X size={18} />
          </button>
        </div>

        <div className="px-6 py-5 space-y-4 max-h-[70vh] overflow-y-auto">
          <div>
            <label className="text-[11px] font-semibold text-gray-700 uppercase tracking-wide">
              Nombre visible *
            </label>
            <Input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              placeholder="Ej. Proyecto de interés"
              autoFocus
              disabled={saving}
            />
          </div>

          <div>
            <label className="text-[11px] font-semibold text-gray-700 uppercase tracking-wide">
              Clave interna *
            </label>
            <Input
              value={key}
              onChange={(e) => { setKey(slugify(e.target.value)); setKeyTouched(true) }}
              placeholder="proyecto_de_interes"
              disabled={isEdit || saving}
              className="font-mono text-xs"
            />
            <p className="text-[11px] text-gray-500 mt-1">
              {isEdit
                ? 'La clave es inmutable después de crear la propiedad.'
                : 'snake_case automático. Se usa internamente; no se muestra al asesor.'}
            </p>
          </div>

          <div>
            <label className="text-[11px] font-semibold text-gray-700 uppercase tracking-wide">
              Tipo
            </label>
            <div className="grid grid-cols-5 gap-1.5 mt-1">
              {(allowedTypes || ['text','number','date','boolean','select']).map((t) => {
                const m = TYPE_META[t] || TYPE_META.text
                const Icon = m.icon
                const active = type === t
                return (
                  <button
                    key={t}
                    type="button"
                    onClick={() => setType(t)}
                    disabled={saving}
                    className={cn(
                      'flex flex-col items-center gap-1 py-2 rounded-lg border transition-all',
                      active
                        ? 'border-violet-400 bg-violet-50 text-violet-700 shadow-sm'
                        : 'border-gray-200 text-gray-500 hover:border-gray-300 hover:bg-gray-50',
                    )}
                  >
                    <Icon size={15} />
                    <span className="text-[10px] font-medium">{m.label}</span>
                  </button>
                )
              })}
            </div>
          </div>

          {type === 'select' && (
            <div>
              <label className="text-[11px] font-semibold text-gray-700 uppercase tracking-wide">
                Opciones (una por línea) *
              </label>
              <textarea
                value={optionsText}
                onChange={(e) => setOptionsText(e.target.value)}
                disabled={saving}
                rows={4}
                className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-violet-400 focus:border-transparent"
                placeholder={'Opción 1\nOpción 2\nOpción 3\nOtro'}
              />
            </div>
          )}

          <div>
            <label className="text-[11px] font-semibold text-gray-700 uppercase tracking-wide">
              Categoría <span className="text-gray-400 font-normal">(opcional)</span>
            </label>
            <Input
              value={category}
              onChange={(e) => setCategory(e.target.value)}
              disabled={saving}
              placeholder="Comercial, Personal, Demográfico…"
            />
          </div>

          <div>
            <label className="text-[11px] font-semibold text-gray-700 uppercase tracking-wide">
              Descripción <span className="text-gray-400 font-normal">(opcional)</span>
            </label>
            <textarea
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              disabled={saving}
              rows={2}
              className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-400 focus:border-transparent"
              placeholder="¿Para qué sirve esta propiedad? ¿Qué representa?"
            />
          </div>

          {error && (
            <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-red-50 border border-red-100 text-red-700 text-xs">
              <AlertCircle size={14} className="shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-6 py-3 bg-gray-50 border-t border-gray-100">
          <Button variant="outline" size="sm" onClick={onClose} disabled={saving}>Cancelar</Button>
          <Button size="sm" onClick={handleSave} disabled={saving}>
            <Save size={13} className="mr-1" /> {saving ? 'Guardando…' : 'Guardar'}
          </Button>
        </div>
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────── */
/* Modal de mapping — crear / editar                                         */
/* ─────────────────────────────────────────────────────────────────────── */

function MappingModal({
  open, initial, onClose, onSaved,
  properties, allowedColumns, allowedTargetTypes,
}) {
  const [formId, setFormId] = useState('')
  const [metaField, setMetaField] = useState('')
  const [targetType, setTargetType] = useState('property')
  const [targetKey, setTargetKey] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!open) return
    setFormId(initial?.form_id || '')
    setMetaField(initial?.meta_field_name || '')
    setTargetType(initial?.target_type || 'property')
    setTargetKey(initial?.target_key || '')
    setError(null)
  }, [open, initial])

  const handleSave = async () => {
    setError(null)
    if (!formId.trim())    { setError('form_id es obligatorio (usa "_any_" para aplicar a cualquier formulario).'); return }
    if (!metaField.trim()) { setError('El nombre del campo Meta es obligatorio.'); return }
    if (targetType !== 'ignore' && !targetKey) {
      setError('Selecciona el target (columna o propiedad).')
      return
    }
    setSaving(true)
    try {
      const res = await api.post('/api/integrations/field-mappings/mappings', {
        provider: 'meta',
        form_id: formId.trim(),
        meta_field_name: metaField.trim().toLowerCase(),
        target_type: targetType,
        target_key: targetType === 'ignore' ? null : targetKey,
      })
      onSaved?.(res.data)
      onClose()
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo guardar el mapeo.')
    } finally {
      setSaving(false)
    }
  }

  const targetOptions = useMemo(() => {
    if (targetType === 'column') {
      return (allowedColumns || []).map((c) => ({ value: c, label: c }))
    }
    if (targetType === 'property') {
      return (properties || [])
        .filter((p) => p.is_active !== false)
        .map((p) => ({
          value: p.property_key,
          label: `${p.display_name} — ${p.property_key}`,
          typeBadge: p.property_type,
        }))
    }
    return []
  }, [targetType, allowedColumns, properties])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/40 backdrop-blur-sm flex items-start justify-center pt-16 px-4"
         onClick={onClose}>
      <div
        className="bg-white w-full max-w-xl rounded-2xl shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between px-6 py-4 border-b border-gray-100">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-lg bg-indigo-50 text-indigo-600 flex items-center justify-center">
              <SlidersHorizontal size={17} />
            </div>
            <div>
              <h3 className="text-base font-semibold text-gray-900">
                {initial?.id ? 'Editar mapeo' : 'Nuevo mapeo'}
              </h3>
              <p className="text-xs text-gray-500">
                Regla "campo Meta → target" que se aplica en cada ingesta.
              </p>
            </div>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <X size={18} />
          </button>
        </div>

        <div className="px-6 py-5 space-y-4 max-h-[70vh] overflow-y-auto">
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] font-semibold text-gray-700 uppercase tracking-wide">
                form_id de Meta *
              </label>
              <Input
                value={formId}
                onChange={(e) => setFormId(e.target.value)}
                placeholder="1234567890 o _any_"
                disabled={saving || !!initial?.id}
                className="font-mono text-xs"
              />
              <p className="text-[11px] text-gray-500 mt-1">
                Usa <code className="font-mono">_any_</code> para aplicar a todos los formularios.
              </p>
            </div>

            <div>
              <label className="text-[11px] font-semibold text-gray-700 uppercase tracking-wide">
                Campo Meta *
              </label>
              <Input
                value={metaField}
                onChange={(e) => setMetaField(e.target.value.toLowerCase())}
                placeholder="proyecto_interes"
                disabled={saving || !!initial?.id}
                className="font-mono text-xs"
              />
              <p className="text-[11px] text-gray-500 mt-1">
                Se normaliza en lowercase automáticamente.
              </p>
            </div>
          </div>

          <div>
            <label className="text-[11px] font-semibold text-gray-700 uppercase tracking-wide">
              Tipo de target
            </label>
            <div className="grid grid-cols-3 gap-1.5 mt-1">
              {(allowedTargetTypes || ['column','property','ignore']).map((t) => {
                const m = TARGET_META[t] || TARGET_META.property
                const Icon = m.icon
                const active = targetType === t
                return (
                  <button
                    key={t}
                    type="button"
                    onClick={() => { setTargetType(t); setTargetKey('') }}
                    disabled={saving}
                    className={cn(
                      'flex flex-col items-center gap-1 py-2.5 rounded-lg border transition-all',
                      active
                        ? 'border-indigo-400 bg-indigo-50 text-indigo-700 shadow-sm'
                        : 'border-gray-200 text-gray-500 hover:border-gray-300 hover:bg-gray-50',
                    )}
                  >
                    <Icon size={16} />
                    <span className="text-[11px] font-semibold">{m.label}</span>
                  </button>
                )
              })}
            </div>
          </div>

          {targetType !== 'ignore' && (
            <div>
              <label className="text-[11px] font-semibold text-gray-700 uppercase tracking-wide">
                {targetType === 'column' ? 'Columna de crm.leads' : 'Propiedad custom'}
              </label>
              <select
                value={targetKey}
                onChange={(e) => setTargetKey(e.target.value)}
                disabled={saving}
                className="mt-1 w-full rounded-lg border border-gray-200 px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400 focus:border-transparent"
              >
                <option value="">— Seleccionar —</option>
                {targetOptions.map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
              {targetType === 'property' && properties?.length === 0 && (
                <p className="text-[11px] text-amber-700 mt-1.5 flex items-center gap-1">
                  <AlertCircle size={12} /> No hay propiedades custom aún. Creá una desde el tab "Propiedades".
                </p>
              )}
            </div>
          )}

          {error && (
            <div className="flex items-start gap-2 px-3 py-2 rounded-lg bg-red-50 border border-red-100 text-red-700 text-xs">
              <AlertCircle size={14} className="shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}
        </div>

        <div className="flex items-center justify-end gap-2 px-6 py-3 bg-gray-50 border-t border-gray-100">
          <Button variant="outline" size="sm" onClick={onClose} disabled={saving}>Cancelar</Button>
          <Button size="sm" onClick={handleSave} disabled={saving}>
            <Save size={13} className="mr-1" /> {saving ? 'Guardando…' : 'Guardar'}
          </Button>
        </div>
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────── */
/* Tab: Propiedades                                                        */
/* ─────────────────────────────────────────────────────────────────────── */

function PropertiesTab({ properties, loading, onReload, onEdit, onDelete, onPurgeValues, onCreate }) {
  const [search, setSearch] = useState('')
  const [categoryFilter, setCategoryFilter] = useState('')

  const categories = useMemo(() => {
    const set = new Set()
    for (const p of properties || []) if (p.category) set.add(p.category)
    return Array.from(set).sort()
  }, [properties])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (properties || []).filter((p) => {
      if (categoryFilter && p.category !== categoryFilter) return false
      if (!q) return true
      return (
        p.display_name.toLowerCase().includes(q) ||
        p.property_key.toLowerCase().includes(q) ||
        (p.description || '').toLowerCase().includes(q)
      )
    })
  }, [properties, search, categoryFilter])

  const grouped = useMemo(() => {
    const by = new Map()
    for (const p of filtered) {
      const k = p.category || 'Sin categoría'
      if (!by.has(k)) by.set(k, [])
      by.get(k).push(p)
    }
    return Array.from(by.entries()).sort(([a], [b]) => a.localeCompare(b))
  }, [filtered])

  return (
    <div>
      <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
        <div className="flex items-center gap-2 flex-1 min-w-[260px]">
          <div className="relative flex-1 max-w-md">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Buscar propiedades…"
              className="pl-9 h-9"
            />
          </div>
          {categories.length > 0 && (
            <select
              value={categoryFilter}
              onChange={(e) => setCategoryFilter(e.target.value)}
              className="h-9 rounded-lg border border-gray-200 px-3 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400"
            >
              <option value="">Todas las categorías</option>
              {categories.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={onReload} disabled={loading}>
            <RefreshCw size={13} className={cn(loading && 'animate-spin')} />
          </Button>
          <Button size="sm" onClick={onCreate}>
            <Plus size={13} className="mr-1" /> Nueva propiedad
          </Button>
        </div>
      </div>

      {loading ? (
        <Card><CardContent className="p-10"><LoadingSpinner /></CardContent></Card>
      ) : !filtered.length ? (
        <Card>
          <CardContent className="py-10">
            <EmptyState
              icon={Sparkles}
              title={search || categoryFilter ? 'Sin resultados' : 'Todavía no hay propiedades custom'}
              description={search || categoryFilter
                ? 'Prueba con otro término o quita el filtro.'
                : 'Crea tu primera propiedad custom para empezar a capturar campos extra de los formularios.'}
            />
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-5">
          {grouped.map(([category, items]) => (
            <div key={category}>
              <h4 className="text-[11px] font-bold uppercase tracking-wider text-gray-500 mb-2">
                {category} <span className="text-gray-300 font-normal">· {items.length}</span>
              </h4>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                {items.map((p) => {
                  const m = TYPE_META[p.property_type] || TYPE_META.text
                  const Icon = m.icon
                  return (
                    <div
                      key={p.property_key}
                      className="group relative bg-white border border-gray-100 rounded-xl p-4 hover:border-gray-200 hover:shadow-[0_4px_12px_rgba(0,0,0,0.05)] transition-all"
                    >
                      <div className="flex items-start gap-3">
                        <div className={cn('w-9 h-9 rounded-lg flex items-center justify-center shrink-0', m.tone.replace('ring-', 'border-').replace('ring-1', ''), 'ring-1')}>
                          <Icon size={15} />
                        </div>
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <h5 className="text-sm font-semibold text-gray-900 truncate">{p.display_name}</h5>
                            {p.is_system && (
                              <span className="px-1.5 py-0.5 text-[9px] font-bold uppercase rounded bg-gray-100 text-gray-500">
                                Sistema
                              </span>
                            )}
                          </div>
                          <p className="text-[11px] text-gray-400 font-mono mt-0.5">{p.property_key}</p>
                          <div className="mt-2"><TypeChip type={p.property_type} /></div>
                          {p.description && (
                            <p className="text-xs text-gray-500 mt-2 leading-relaxed line-clamp-2">{p.description}</p>
                          )}
                          {p.property_type === 'select' && Array.isArray(p.options) && (
                            <div className="flex flex-wrap gap-1 mt-2">
                              {p.options.slice(0, 4).map((o) => (
                                <span key={o} className="px-1.5 py-0.5 rounded bg-emerald-50 text-emerald-700 text-[10px]">{o}</span>
                              ))}
                              {p.options.length > 4 && (
                                <span className="px-1.5 py-0.5 text-[10px] text-gray-400">+{p.options.length - 4}</span>
                              )}
                            </div>
                          )}
                        </div>
                      </div>
                      <div className="absolute top-3 right-3 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={() => onEdit(p)}
                          className="w-7 h-7 rounded-md bg-white text-gray-400 hover:text-gray-700 hover:bg-gray-100 flex items-center justify-center"
                          title="Editar"
                        >
                          <Edit3 size={13} />
                        </button>
                        {!p.is_system && onPurgeValues && (
                          <button
                            onClick={() => onPurgeValues(p)}
                            className="w-7 h-7 rounded-md bg-white text-gray-400 hover:text-red-600 hover:bg-red-50 flex items-center justify-center"
                            title="Borrar valores guardados"
                          >
                            <Eraser size={13} />
                          </button>
                        )}
                        {!p.is_system && (
                          <button
                            onClick={() => onDelete(p)}
                            className="w-7 h-7 rounded-md bg-white text-gray-400 hover:text-red-600 hover:bg-red-50 flex items-center justify-center"
                            title="Desactivar"
                          >
                            <Trash2 size={13} />
                          </button>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────── */
/* Tab: Mapeos                                                             */
/* ─────────────────────────────────────────────────────────────────────── */

function BackfillProgress({ job, onClose }) {
  if (!job) return null
  const t = job.totals || {}
  const isRunning = job.status === 'pending' || job.status === 'running'
  const isDone = job.status === 'completed'
  const isError = job.status === 'failed' || job.status === 'rejected'

  const title = {
    pending: 'Encolando reproceso…',
    running: 'Reprocesando leads existentes…',
    completed: 'Reproceso completado',
    failed: 'El reproceso falló',
    rejected: 'Otro reproceso ya está corriendo',
  }[job.status] || job.status

  return (
    <div className={cn(
      'mb-4 rounded-xl border px-4 py-3 flex items-start gap-3',
      isRunning && 'bg-indigo-50/60 border-indigo-100',
      isDone    && 'bg-emerald-50/60 border-emerald-100',
      isError   && 'bg-red-50/60 border-red-100',
    )}>
      <div className={cn(
        'w-8 h-8 rounded-lg flex items-center justify-center shrink-0',
        isRunning && 'bg-indigo-100 text-indigo-600',
        isDone    && 'bg-emerald-100 text-emerald-600',
        isError   && 'bg-red-100 text-red-600',
      )}>
        {isRunning ? <RefreshCw size={15} className="animate-spin" />
          : isDone ? <CheckCircle2 size={16} />
          : <AlertCircle size={16} />}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <p className="text-sm font-semibold text-gray-900">{title}</p>
          <span className="font-mono text-[10px] text-gray-400">job {(job.job_id || '').slice(0, 8)}</span>
        </div>
        {isError && job.error && (
          <p className="text-xs text-red-700 mt-1">{job.error}</p>
        )}
        {(t.interactions_seen ?? 0) > 0 && (
          <dl className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-1 mt-2 text-xs">
            <div><dt className="text-gray-500">Revisadas</dt><dd className="font-semibold text-gray-800">{t.interactions_seen ?? 0}</dd></div>
            <div><dt className="text-gray-500">Leads tocados</dt><dd className="font-semibold text-gray-800">{t.leads_touched ?? 0}</dd></div>
            <div><dt className="text-gray-500">Escrituras</dt><dd className="font-semibold text-emerald-700">{t.applied ?? 0}</dd></div>
            <div><dt className="text-gray-500">Errores</dt><dd className={cn('font-semibold', (t.errors ?? 0) > 0 ? 'text-red-700' : 'text-gray-400')}>{t.errors ?? 0}</dd></div>
          </dl>
        )}
      </div>
      {!isRunning && (
        <button onClick={onClose} className="text-gray-400 hover:text-gray-600 shrink-0">
          <X size={16} />
        </button>
      )}
    </div>
  )
}


function MappingsTab({
  mappings, loading, onReload, onEdit, onDelete, onCreate,
  onBackfill, backfillJob, onCloseBackfill, properties,
}) {
  const [search, setSearch] = useState('')
  const [formFilter, setFormFilter] = useState('')
  const backfilling = backfillJob && (backfillJob.status === 'pending' || backfillJob.status === 'running')

  const forms = useMemo(() => {
    const set = new Set()
    for (const m of mappings || []) set.add(m.form_id)
    return Array.from(set).sort()
  }, [mappings])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (mappings || []).filter((m) => {
      if (formFilter && m.form_id !== formFilter) return false
      if (!q) return true
      return (
        m.meta_field_name.toLowerCase().includes(q) ||
        (m.target_key || '').toLowerCase().includes(q) ||
        m.form_id.toLowerCase().includes(q)
      )
    })
  }, [mappings, search, formFilter])

  const propByKey = useMemo(() => {
    const m = new Map()
    for (const p of properties || []) m.set(p.property_key, p)
    return m
  }, [properties])

  return (
    <div>
      <BackfillProgress job={backfillJob} onClose={onCloseBackfill} />
      <div className="flex items-center justify-between gap-3 mb-4 flex-wrap">
        <div className="flex items-center gap-2 flex-1 min-w-[260px]">
          <div className="relative flex-1 max-w-md">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <Input
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Buscar por campo, form_id o target…"
              className="pl-9 h-9"
            />
          </div>
          {forms.length > 1 && (
            <select
              value={formFilter}
              onChange={(e) => setFormFilter(e.target.value)}
              className="h-9 rounded-lg border border-gray-200 px-3 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-indigo-400"
            >
              <option value="">Todos los formularios</option>
              {forms.map((f) => <option key={f} value={f}>{f === '_any_' ? 'Wildcard (_any_)' : f}</option>)}
            </select>
          )}
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={onReload} disabled={loading}>
            <RefreshCw size={13} className={cn(loading && 'animate-spin')} />
          </Button>
          {onBackfill && mappings?.length > 0 && (
            <Button
              variant="outline"
              size="sm"
              onClick={onBackfill}
              disabled={backfilling || loading}
              title="Aplica las reglas actuales a los leads que ya tienen el campo en su historial de Meta"
            >
              <Zap size={13} className={cn('mr-1', backfilling && 'animate-pulse')} />
              {backfilling ? 'Reprocesando…' : 'Reprocesar existentes'}
            </Button>
          )}
          <Button size="sm" onClick={onCreate}>
            <Plus size={13} className="mr-1" /> Nuevo mapeo
          </Button>
        </div>
      </div>

      {loading ? (
        <Card><CardContent className="p-10"><LoadingSpinner /></CardContent></Card>
      ) : !filtered.length ? (
        <Card>
          <CardContent className="py-10">
            <EmptyState
              icon={SlidersHorizontal}
              title={search || formFilter ? 'Sin resultados' : 'Aún no hay mapeos configurados'}
              description={search || formFilter
                ? 'Ajusta los filtros para ver más.'
                : 'Los campos custom caen en observaciones hasta que configures un mapeo. Revisa el tab "Sin mapear" para detectar campos pendientes.'}
            />
          </CardContent>
        </Card>
      ) : (
        <div className="bg-white border border-gray-100 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr className="text-left text-[11px] font-bold uppercase tracking-wider text-gray-500">
                <th className="px-4 py-3">Formulario</th>
                <th className="px-4 py-3">Campo Meta</th>
                <th className="px-4 py-3">Target</th>
                <th className="px-4 py-3 w-24"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {filtered.map((m) => {
                const prop = m.target_type === 'property' ? propByKey.get(m.target_key) : null
                return (
                  <tr key={m.id} className="hover:bg-gray-50/60 group">
                    <td className="px-4 py-3">
                      {m.form_id === '_any_' ? (
                        <span className="inline-flex items-center gap-1.5 text-xs font-medium text-violet-600">
                          <Sparkles size={11} /> Wildcard — todos
                        </span>
                      ) : (
                        <span className="font-mono text-xs text-gray-700">{m.form_id}</span>
                      )}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-gray-800">{m.meta_field_name}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <ArrowRight size={12} className="text-gray-300" />
                        <TargetChip type={m.target_type} name={m.target_key} />
                        {prop && <TypeChip type={prop.property_type} />}
                      </div>
                    </td>
                    <td className="px-4 py-3 text-right">
                      <div className="flex items-center gap-1 justify-end opacity-0 group-hover:opacity-100 transition-opacity">
                        <button
                          onClick={() => onEdit(m)}
                          className="w-7 h-7 rounded-md text-gray-400 hover:text-gray-700 hover:bg-gray-100 flex items-center justify-center"
                          title="Editar"
                        >
                          <Edit3 size={13} />
                        </button>
                        <button
                          onClick={() => onDelete(m)}
                          className="w-7 h-7 rounded-md text-gray-400 hover:text-red-600 hover:bg-red-50 flex items-center justify-center"
                          title="Eliminar"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────── */
/* Tab: Sin mapear                                                         */
/* ─────────────────────────────────────────────────────────────────────── */

function UnmappedTab({ unmapped, loading, onReload, onMap }) {
  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <p className="text-xs text-gray-500">
            Campos detectados en los últimos 90 días que aún no tienen regla.
            Estos caen hoy en <code className="font-mono text-[10px] px-1 py-0.5 rounded bg-gray-100">observaciones</code>.
          </p>
        </div>
        <Button variant="outline" size="sm" onClick={onReload} disabled={loading}>
          <RefreshCw size={13} className={cn(loading && 'animate-spin')} />
        </Button>
      </div>

      {loading ? (
        <Card><CardContent className="p-10"><LoadingSpinner /></CardContent></Card>
      ) : !unmapped?.length ? (
        <Card>
          <CardContent className="py-10">
            <EmptyState
              icon={CheckCircle2}
              title="Todo al día"
              description="No hay campos sin mapear en los últimos 90 días. Buen trabajo."
            />
          </CardContent>
        </Card>
      ) : (
        <div className="bg-white border border-gray-100 rounded-xl overflow-hidden">
          <div className="bg-amber-50 border-b border-amber-100 px-4 py-2.5 flex items-center gap-2">
            <AlertCircle size={14} className="text-amber-600" />
            <p className="text-xs text-amber-900">
              <span className="font-semibold">{unmapped.length} campo{unmapped.length === 1 ? '' : 's'} sin mapear</span>
              {' '}— configúralos para que aparezcan como datos estructurados en el lead.
            </p>
          </div>
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr className="text-left text-[11px] font-bold uppercase tracking-wider text-gray-500">
                <th className="px-4 py-3">Formulario</th>
                <th className="px-4 py-3">Campo</th>
                <th className="px-4 py-3">Valor ejemplo</th>
                <th className="px-4 py-3">Submits</th>
                <th className="px-4 py-3 w-28"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {unmapped.map((u, i) => (
                <tr key={`${u.form_id}-${u.meta_field_name}-${i}`} className="hover:bg-gray-50/60 group">
                  <td className="px-4 py-3">
                    <div className="flex flex-col">
                      <span className="text-xs text-gray-800 truncate max-w-[200px]">
                        {u.form_nombre || <span className="text-gray-400 italic">Sin nombre</span>}
                      </span>
                      <span className="font-mono text-[10px] text-gray-400">{u.form_id}</span>
                    </div>
                  </td>
                  <td className="px-4 py-3 font-mono text-xs text-gray-800">{u.meta_field_name}</td>
                  <td className="px-4 py-3 text-xs text-gray-600 max-w-[300px] truncate" title={u.sample_value}>
                    {u.sample_value || <span className="text-gray-400 italic">(vacío)</span>}
                  </td>
                  <td className="px-4 py-3">
                    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 text-[11px] font-semibold">
                      {u.submit_count}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Button size="sm" variant="outline" onClick={() => onMap(u)}>
                      <SlidersHorizontal size={12} className="mr-1" /> Mapear
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────── */
/* Dialog: Borrar valores guardados (destructivo, typed-confirmation)      */
/* ─────────────────────────────────────────────────────────────────────── */
/* Patrón servicio externo/patrón estándar: typed-confirmation + dry-run preview.
 * Flujo:
 *   1. Al abrir, llama dry_run para mostrar cuántos valores existen.
 *   2. Si no hay valores, muestra mensaje vacío y permite cerrar.
 *   3. Si hay, exige tipear el property_key exacto para habilitar el botón.
 *   4. Al confirmar, dispara el DELETE real y muestra resultado inline.
 */
function DeleteValuesDialog({ open, property, onClose, onDeleted }) {
  const [phase, setPhase]     = useState('loading')   // loading | preview | running | done | error
  const [count, setCount]     = useState(0)
  const [deleted, setDeleted] = useState(0)
  const [typed, setTyped]     = useState('')
  const [error, setError]     = useState(null)

  const propertyKey = property?.property_key || ''
  const displayName = property?.display_name || propertyKey

  // Reset al abrir / cambiar de propiedad.
  useEffect(() => {
    if (!open || !propertyKey) return
    setPhase('loading')
    setCount(0)
    setDeleted(0)
    setTyped('')
    setError(null)
    let cancelled = false
    api.delete(
      `/api/integrations/field-mappings/properties/${encodeURIComponent(propertyKey)}/values`,
      { params: { dry_run: true } },
    ).then((res) => {
      if (cancelled) return
      setCount(res.data?.count ?? 0)
      setPhase('preview')
    }).catch((err) => {
      if (cancelled) return
      setError(err.response?.data?.detail || 'No se pudo consultar el impacto.')
      setPhase('error')
    })
    return () => { cancelled = true }
  }, [open, propertyKey])

  if (!open || !property) return null

  const canConfirm = phase === 'preview' && count > 0 && typed === propertyKey
  const isBusy = phase === 'loading' || phase === 'running'

  const handleConfirm = async () => {
    setPhase('running')
    setError(null)
    try {
      const res = await api.delete(
        `/api/integrations/field-mappings/properties/${encodeURIComponent(propertyKey)}/values`,
        { params: { dry_run: false } },
      )
      setDeleted(res.data?.deleted ?? 0)
      setPhase('done')
      onDeleted?.()
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo borrar los valores.')
      setPhase('error')
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div
        className="absolute inset-0 bg-black/50 backdrop-blur-sm"
        onClick={isBusy ? undefined : onClose}
      />
      <div className="relative bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Header con franja de peligro */}
        <div className="bg-gradient-to-br from-red-50 to-rose-50 border-b border-red-100 px-6 py-5">
          <div className="flex items-start gap-3">
            <div className="w-11 h-11 rounded-xl bg-red-100 flex items-center justify-center shrink-0">
              <ShieldAlert size={20} className="text-red-600" />
            </div>
            <div className="min-w-0 flex-1">
              <h3 className="text-base font-semibold text-gray-900">
                Borrar valores guardados
              </h3>
              <p className="text-sm text-gray-600 mt-0.5">
                Acción irreversible — limpia el historial de esta propiedad en todos los leads.
              </p>
            </div>
          </div>
        </div>

        <div className="px-6 py-5 space-y-4">
          {/* Identidad de la propiedad */}
          <div className="rounded-lg bg-gray-50 border border-gray-100 px-3 py-2.5">
            <p className="text-[11px] uppercase tracking-wider text-gray-400 font-semibold">Propiedad</p>
            <p className="text-sm font-semibold text-gray-900 truncate">{displayName}</p>
            <p className="font-mono text-xs text-gray-500 truncate">{propertyKey}</p>
          </div>

          {/* Estado: loading dry-run */}
          {phase === 'loading' && (
            <div className="flex items-center gap-2 text-sm text-gray-500 py-2">
              <Loader2 size={14} className="animate-spin" />
              Calculando impacto…
            </div>
          )}

          {/* Estado: preview con count */}
          {phase === 'preview' && count === 0 && (
            <div className="flex items-start gap-2 rounded-lg bg-emerald-50 border border-emerald-100 px-3 py-2.5 text-sm text-emerald-800">
              <CheckCircle2 size={16} className="shrink-0 mt-0.5" />
              <span>No hay valores guardados para esta propiedad. No hay nada que borrar.</span>
            </div>
          )}

          {phase === 'preview' && count > 0 && (
            <>
              <div className="rounded-lg bg-red-50 border border-red-100 px-4 py-3">
                <p className="text-[11px] uppercase tracking-wider text-red-700 font-bold">Impacto</p>
                <p className="text-2xl font-bold text-red-700 mt-0.5 leading-none">
                  {count.toLocaleString()}
                </p>
                <p className="text-xs text-red-700 mt-1">
                  valor{count === 1 ? '' : 'es'} se eliminará{count === 1 ? '' : 'n'} de <span className="font-mono">crm.lead_properties</span>
                </p>
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1.5">
                  Para confirmar, tipea <span className="font-mono bg-gray-100 px-1.5 py-0.5 rounded text-red-700">{propertyKey}</span>
                </label>
                <Input
                  autoFocus
                  value={typed}
                  onChange={(e) => setTyped(e.target.value)}
                  placeholder={propertyKey}
                  className={cn(
                    'font-mono',
                    typed && typed !== propertyKey && 'border-red-300 focus-visible:ring-red-300',
                    typed === propertyKey && 'border-emerald-300 focus-visible:ring-emerald-300',
                  )}
                />
              </div>
            </>
          )}

          {/* Estado: running */}
          {phase === 'running' && (
            <div className="flex items-center gap-2 text-sm text-gray-700 py-2">
              <Loader2 size={14} className="animate-spin" />
              Borrando {count.toLocaleString()} valor{count === 1 ? '' : 'es'}…
            </div>
          )}

          {/* Estado: done */}
          {phase === 'done' && (
            <div className="flex items-start gap-2 rounded-lg bg-emerald-50 border border-emerald-100 px-3 py-2.5 text-sm text-emerald-800">
              <CheckCircle2 size={16} className="shrink-0 mt-0.5" />
              <span>
                <span className="font-semibold">{deleted.toLocaleString()}</span> valor{deleted === 1 ? '' : 'es'} eliminado{deleted === 1 ? '' : 's'}.
              </span>
            </div>
          )}

          {/* Estado: error */}
          {phase === 'error' && error && (
            <div className="flex items-start gap-2 rounded-lg bg-red-50 border border-red-100 px-3 py-2.5 text-sm text-red-800">
              <AlertCircle size={16} className="shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}
        </div>

        {/* Acciones */}
        <div className="px-6 py-4 bg-gray-50 border-t border-gray-100 flex gap-3">
          <Button
            variant="outline"
            className="flex-1"
            onClick={onClose}
            disabled={isBusy}
          >
            {phase === 'done' ? 'Cerrar' : 'Cancelar'}
          </Button>
          {phase !== 'done' && (
            <Button
              className="flex-1 gap-1.5 bg-red-600 hover:bg-red-700 text-white border-red-600 disabled:bg-red-300 disabled:border-red-300"
              onClick={handleConfirm}
              disabled={!canConfirm || isBusy}
            >
              {phase === 'running'
                ? <Loader2 size={14} className="animate-spin" />
                : <Eraser size={14} />}
              Borrar valores
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────── */
/* Página principal                                                        */
/* ─────────────────────────────────────────────────────────────────────── */

export default function FieldMappings() {
  const [tab, setTab] = useState('properties')
  const [options, setOptions] = useState(null)
  const [properties, setProperties] = useState([])
  const [mappings, setMappings] = useState([])
  const [unmapped, setUnmapped] = useState([])
  const [loadingProps, setLoadingProps] = useState(false)
  const [loadingMaps, setLoadingMaps]   = useState(false)
  const [loadingUnmap, setLoadingUnmap] = useState(false)

  const [propertyModal, setPropertyModal] = useState({ open: false, initial: null })
  const [mappingModal, setMappingModal]   = useState({ open: false, initial: null })
  const [confirmProp, setConfirmProp]     = useState(null)
  const [confirmMapping, setConfirmMapping] = useState(null)
  const [purgeProp, setPurgeProp]         = useState(null)
  const [confirmBackfill, setConfirmBackfill] = useState(false)
  const [backfillJob, setBackfillJob] = useState(null)
  const pollRef = useRef(null)

  const loadOptions = useCallback(async () => {
    try {
      const res = await api.get('/api/integrations/field-mappings/options')
      setOptions(res.data)
    } catch { /* fallback a defaults en UI */ }
  }, [])

  const loadProperties = useCallback(async () => {
    setLoadingProps(true)
    try {
      const res = await api.get('/api/integrations/field-mappings/properties')
      setProperties(res.data?.items || [])
    } finally { setLoadingProps(false) }
  }, [])

  const loadMappings = useCallback(async () => {
    setLoadingMaps(true)
    try {
      const res = await api.get('/api/integrations/field-mappings/mappings')
      setMappings(res.data?.items || [])
    } finally { setLoadingMaps(false) }
  }, [])

  const loadUnmapped = useCallback(async () => {
    setLoadingUnmap(true)
    try {
      const res = await api.get('/api/integrations/field-mappings/unmapped')
      setUnmapped(res.data?.items || [])
    } finally { setLoadingUnmap(false) }
  }, [])

  useEffect(() => { loadOptions(); loadProperties(); loadMappings(); loadUnmapped() }, [
    loadOptions, loadProperties, loadMappings, loadUnmapped
  ])

  const handleDeleteProperty = async (p) => {
    try {
      await api.delete(`/api/integrations/field-mappings/properties/${encodeURIComponent(p.property_key)}`)
      setConfirmProp(null)
      loadProperties()
    } catch (err) {
      alert(err.response?.data?.detail || 'No se pudo desactivar.')
    }
  }

  const handleDeleteMapping = async (m) => {
    try {
      await api.delete(`/api/integrations/field-mappings/mappings/${m.id}`)
      setConfirmMapping(null)
      loadMappings()
      loadUnmapped()
    } catch (err) {
      alert(err.response?.data?.detail || 'No se pudo eliminar.')
    }
  }

  const stopPolling = useCallback(() => {
    if (pollRef.current) {
      clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  // Limpia intervalo al desmontar.
  useEffect(() => () => stopPolling(), [stopPolling])

  const pollJob = useCallback(async (jobId) => {
    try {
      const res = await api.get(
        `/api/integrations/field-mappings/backfill/status/${jobId}`
      )
      setBackfillJob(res.data)
      const done = ['completed', 'failed', 'rejected'].includes(res.data?.status)
      if (done) {
        stopPolling()
        loadUnmapped()
      }
    } catch {
      stopPolling()
    }
  }, [stopPolling, loadUnmapped])

  const runBackfill = async () => {
    setConfirmBackfill(false)
    stopPolling()
    try {
      const res = await api.post('/api/integrations/field-mappings/backfill')
      const jobId = res.data?.job_id
      if (!jobId) return
      setBackfillJob({ job_id: jobId, status: 'pending', totals: {} })
      pollRef.current = setInterval(() => pollJob(jobId), 1500)
      pollJob(jobId)
    } catch (err) {
      setBackfillJob({
        job_id: '—',
        status: 'failed',
        error: err.response?.data?.detail || 'No se pudo iniciar el reproceso.',
      })
    }
  }

  const tabs = [
    { id: 'properties', label: 'Propiedades', icon: Sparkles, count: properties.length },
    { id: 'mappings',   label: 'Mapeos',      icon: SlidersHorizontal, count: mappings.length },
    { id: 'unmapped',   label: 'Sin mapear',  icon: AlertCircle, count: unmapped.length, highlight: unmapped.length > 0 },
  ]

  return (
    <div className="p-6 max-w-6xl mx-auto">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1.5 text-xs text-gray-500 mb-3" aria-label="Ruta">
        <span className="text-gray-400">Integraciones</span>
        <span className="text-gray-300">›</span>
        <span className="text-gray-700 font-medium">Propiedades y mapeos</span>
      </nav>

      {/* Header premium */}
      <div className="flex items-start gap-3 pb-5 mb-6 border-b border-gray-100">
        <div
          className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
          style={{ backgroundColor: 'rgba(var(--brand-primary-rgb), 0.1)' }}
        >
          <Database size={20} style={{ color: 'var(--brand-primary)' }} />
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-semibold text-gray-900 leading-tight">
            Propiedades y mapeos
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">
            Define propiedades custom tipadas y decide cómo se traducen los campos de los formularios externos
            — patrón estándar Properties / patrón estándar Field Mapping.
          </p>
        </div>
      </div>

      {/* Tab bar */}
      <div className="border-b border-gray-200 flex items-center gap-1 overflow-x-auto mb-6">
        {tabs.map((t) => {
          const Icon = t.icon
          const active = tab === t.id
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={cn(
                'flex items-center gap-2 px-4 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 transition-colors',
                active
                  ? 'border-[var(--brand-primary)] text-[var(--brand-primary)]'
                  : 'border-transparent text-gray-500 hover:text-gray-700',
              )}
            >
              <Icon size={15} />
              {t.label}
              {typeof t.count === 'number' && t.count > 0 && (
                <span className={cn(
                  'ml-1 px-1.5 py-0.5 rounded-full text-[10px] font-bold leading-tight',
                  t.highlight
                    ? 'bg-amber-100 text-amber-800'
                    : active
                      ? 'bg-[var(--brand-primary)] text-white'
                      : 'bg-gray-100 text-gray-600',
                )}>
                  {t.count}
                </span>
              )}
            </button>
          )
        })}
      </div>

      {tab === 'properties' && (
        <PropertiesTab
          properties={properties}
          loading={loadingProps}
          onReload={loadProperties}
          onCreate={() => setPropertyModal({ open: true, initial: null })}
          onEdit={(p) => setPropertyModal({ open: true, initial: p })}
          onDelete={(p) => setConfirmProp(p)}
          onPurgeValues={(p) => setPurgeProp(p)}
        />
      )}

      {tab === 'mappings' && (
        <MappingsTab
          mappings={mappings}
          loading={loadingMaps}
          properties={properties}
          onReload={loadMappings}
          onCreate={() => setMappingModal({ open: true, initial: null })}
          onEdit={(m) => setMappingModal({ open: true, initial: m })}
          onDelete={(m) => setConfirmMapping(m)}
          onBackfill={() => setConfirmBackfill(true)}
          backfillJob={backfillJob}
          onCloseBackfill={() => setBackfillJob(null)}
        />
      )}

      {tab === 'unmapped' && (
        <UnmappedTab
          unmapped={unmapped}
          loading={loadingUnmap}
          onReload={loadUnmapped}
          onMap={(u) => setMappingModal({
            open: true,
            initial: {
              form_id: u.form_id,
              meta_field_name: u.meta_field_name,
              target_type: 'property',
              target_key: '',
            },
          })}
        />
      )}

      <PropertyModal
        open={propertyModal.open}
        initial={propertyModal.initial}
        allowedTypes={options?.property_types}
        onClose={() => setPropertyModal({ open: false, initial: null })}
        onSaved={() => { loadProperties() }}
      />

      <MappingModal
        open={mappingModal.open}
        initial={mappingModal.initial}
        properties={properties}
        allowedColumns={options?.allowed_columns}
        allowedTargetTypes={options?.target_types}
        onClose={() => setMappingModal({ open: false, initial: null })}
        onSaved={() => { loadMappings(); loadUnmapped() }}
      />

      <ConfirmDialog
        open={!!confirmProp}
        title={confirmProp ? `Desactivar "${confirmProp.display_name}"` : ''}
        message="La propiedad se marcará como inactiva. Los valores ya guardados en los leads se conservan — podrás reactivarla creando otra con la misma clave."
        confirmLabel="Desactivar"
        onConfirm={() => confirmProp && handleDeleteProperty(confirmProp)}
        onCancel={() => setConfirmProp(null)}
      />

      <ConfirmDialog
        open={!!confirmMapping}
        title="Eliminar mapeo"
        message={confirmMapping
          ? `Se eliminará la regla para "${confirmMapping.meta_field_name}" en el form ${confirmMapping.form_id}. Los valores ya capturados se conservan — solo se deja de aplicar a submits nuevos.`
          : ''}
        confirmLabel="Eliminar"
        onConfirm={() => confirmMapping && handleDeleteMapping(confirmMapping)}
        onCancel={() => setConfirmMapping(null)}
      />

      <ConfirmDialog
        open={confirmBackfill}
        variant="warning"
        title="Reprocesar leads existentes"
        message="Aplicará las reglas actuales a los submits de Meta de los últimos 180 días. Es idempotente (no duplica), corre en background y puedes seguir usando el panel. ¿Iniciar?"
        confirmLabel="Iniciar reproceso"
        onConfirm={runBackfill}
        onCancel={() => setConfirmBackfill(false)}
      />

      <DeleteValuesDialog
        open={!!purgeProp}
        property={purgeProp}
        onClose={() => setPurgeProp(null)}
        onDeleted={() => { /* no recargamos: la tab de propiedades no muestra valores */ }}
      />
    </div>
  )
}
