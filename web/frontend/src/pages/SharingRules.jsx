/**
 * Pantalla de gestión de Sharing Rules (ADR-0012, Sprint 4).
 *
 * Patrón inspirado en reglas de visibilidad profesionales / patrón estándar Shared Views:
 * el admin define reglas DECLARATIVAS que comparten leads que cumplan un
 * criterio (fuente / estado / sede / calidad) con un rol custom.
 *
 * Los usuarios con ese rol ven SUS leads (los asignados a ellos) + los
 * leads que matchean cualquier regla activa para su rol — patron OR.
 */
import { useEffect, useState } from 'react'
import { Save, Plus, Trash2, Eye, Pencil, X as XIcon, Share2, Power, AlertCircle } from 'lucide-react'
import { Button } from '@/components/ui/button'
import SafeTextInput from '@/components/ui/SafeTextInput'
import api from '@/lib/api'
import ApplyChangesPreviewDialog from '@/components/shared/ApplyChangesPreviewDialog'

const EMPTY_FILTER = {
  fuente_ids: [],
  estado_ids: [],
  sede_ids: [],
  api_client_ids: [],
  // Cuando true, api_client_ids hace UNION con leads donde esos
  // proveedores mandaron al menos un recontacto (no solo origen del lead).
  // Backwards-compat: si la regla no tiene esta clave, default es false.
  incluir_recontactos: false,
}

function MsgBox({ msg, onClose }) {
  if (!msg) return null
  const isOk = msg.tipo === 'ok'
  return (
    <div className={`rounded-lg p-3 text-sm flex items-center justify-between gap-2 ${
      isOk ? 'bg-green-50 border border-green-200 text-green-800' : 'bg-red-50 border border-red-200 text-red-700'
    }`}>
      <span>{msg.texto}</span>
      <button onClick={onClose} className="opacity-60 hover:opacity-100"><XIcon size={14} /></button>
    </div>
  )
}

// Multi-select de IDs sobre una lista de opciones {id, nombre}
function MultiCheck({ label, options, value, onChange, emptyLabel = 'Sin restricción' }) {
  const set = new Set(value || [])
  function toggle(id) {
    const next = new Set(set)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    onChange(Array.from(next))
  }
  return (
    <div className="space-y-1.5">
      <label className="text-xs font-semibold text-slate-700 uppercase tracking-wide">{label}</label>
      <div className="border border-slate-200 rounded-md p-2 max-h-32 overflow-y-auto bg-white">
        {options.length === 0 && (
          <p className="text-xs text-slate-400 px-2 py-1">Sin opciones disponibles</p>
        )}
        {options.map((opt) => (
          <label key={opt.id} className="flex items-center gap-2 px-2 py-1 rounded hover:bg-slate-50 cursor-pointer">
            <input
              type="checkbox"
              checked={set.has(opt.id)}
              onChange={() => toggle(opt.id)}
              className="rounded"
            />
            <span className="text-sm text-slate-700">{opt.nombre}</span>
          </label>
        ))}
      </div>
      {set.size === 0 && (
        <p className="text-[11px] text-slate-400">{emptyLabel} (no filtra por este campo)</p>
      )}
    </div>
  )
}

export default function SharingRulesPage() {
  const [rules, setRules] = useState([])
  const [roles, setRoles] = useState([])
  const [fuentes, setFuentes] = useState([])
  const [estados, setEstados] = useState([])
  const [sedes, setSedes] = useState([])
  // ADR-0012 follow-up — proveedores (api_clients activos) para filtrar leads
  // por quién los entregó vía /api/ingest/leads (caso de uso real: marketing
  // ve los leads que entregó Wedo, no los que vinieron por Meta directo).
  const [apiClients, setApiClients] = useState([])
  const [loading, setLoading] = useState(false)
  const [msg, setMsg] = useState(null)
  const [editing, setEditing] = useState(null)  // null | 'new' | {...rule}
  const [confirmDelete, setConfirmDelete] = useState(null)
  // V087.1 — preview de impacto antes de guardar la regla.
  const [showPreview, setShowPreview] = useState(false)
  const [savingRule, setSavingRule] = useState(false)

  async function loadAll() {
    setLoading(true)
    try {
      // ADR-0012 follow-up — Endpoints correctos verificados contra el backend:
      //   /api/sedes/lookup           → array directo de sedes activas
      //   /api/api-clients/lookup     → { clients: [...], legacy: [...] }
      // Los endpoints /api/sedes y /api/api-clients (sin /lookup) eran admin-only
      // con estructuras distintas — el .catch silencioso enmascaraba el error.
      const [r1, r2, r3, r4, r5, r6] = await Promise.all([
        api.get('/api/sharing-rules'),
        api.get('/api/roles'),
        api.get('/api/fuentes').catch(() => ({ data: [] })),
        api.get('/api/estados').catch(() => ({ data: [] })),
        api.get('/api/sedes/lookup', { params: { only_active: true } }).catch(() => ({ data: [] })),
        api.get('/api/api-clients/lookup').catch(() => ({ data: { clients: [] } })),
      ])
      setRules(Array.isArray(r1.data) ? r1.data : [])
      // Solo roles custom (no built-in admin/supervisor/asesor)
      setRoles((Array.isArray(r2.data) ? r2.data : []).filter((r) => !r.is_builtin))
      setFuentes(Array.isArray(r3.data) ? r3.data : (r3.data?.items || []))
      setEstados(Array.isArray(r4.data) ? r4.data : (r4.data?.items || []))
      setSedes(Array.isArray(r5.data) ? r5.data : (r5.data?.items || []))
      // Proveedores: el endpoint /lookup devuelve { clients: [{id, slug, nombre, activo}], legacy: [...] }.
      // Solo nos importan los `clients` activos (los `legacy` son slugs huérfanos sin id).
      setApiClients((Array.isArray(r6.data?.clients) ? r6.data.clients : []).filter((c) => c.activo))
    } catch {
      setMsg({ tipo: 'error', texto: 'Error al cargar reglas o catálogos.' })
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { loadAll() /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [])

  function startNew() {
    if (roles.length === 0) {
      setMsg({ tipo: 'error', texto: 'Primero crea un rol custom en /configuracion/roles antes de definir una regla.' })
      return
    }
    setEditing({
      id: null,
      name: '',
      description: '',
      role_id: roles[0]?.id || null,
      filter_jsonb: { ...EMPTY_FILTER },
      can_view: true,
      can_edit: false,
      is_active: true,
    })
  }

  function startEdit(rule) {
    setEditing({
      id: rule.id,
      name: rule.name || '',
      description: rule.description || '',
      role_id: rule.role_id,
      filter_jsonb: { ...EMPTY_FILTER, ...(rule.filter_jsonb || {}) },
      can_view: !!rule.can_view,
      can_edit: !!rule.can_edit,
      is_active: !!rule.is_active,
    })
  }

  function requestSaveRule() {
    if (!editing) return
    setMsg(null)
    if (!editing.name.trim()) {
      setMsg({ tipo: 'error', texto: 'El nombre de la regla es requerido.' })
      return
    }
    if (!editing.role_id) {
      setMsg({ tipo: 'error', texto: 'Selecciona el rol al que se comparten los leads.' })
      return
    }
    setShowPreview(true)
  }

  async function applySaveRule() {
    if (!editing) return
    setSavingRule(true)
    setMsg(null)
    try {
      const payload = {
        name: editing.name.trim(),
        description: editing.description?.trim() || null,
        filter_jsonb: editing.filter_jsonb,
        can_view: editing.can_view,
        can_edit: editing.can_edit,
        is_active: editing.is_active,
      }
      if (editing.id) {
        await api.patch(`/api/sharing-rules/${editing.id}`, payload)
      } else {
        await api.post('/api/sharing-rules', { ...payload, role_id: editing.role_id })
      }
      setShowPreview(false)
      setEditing(null)
      await loadAll()
      setMsg({ tipo: 'ok', texto: 'Regla guardada.' })
    } catch (e) {
      const detail = e?.response?.data?.detail || 'Error al guardar la regla.'
      setMsg({ tipo: 'error', texto: detail })
    } finally {
      setSavingRule(false)
    }
  }

  // V087.1 — Convierte filter_jsonb en descripciones legibles ("Fuente:
  // Instagram, Facebook" en vez de [3, 4]). Cada criterio que NO está vacío
  // se vuelve un "ADD" para el modal de preview.
  function describeFilter(filter) {
    if (!filter) return []
    const labels = []
    const nameOf = (list, ids) => (ids || [])
      .map(id => list.find(x => x.id === id)?.nombre || `#${id}`)
      .join(', ')
    if (filter.fuente_ids?.length)     labels.push({ label: 'Fuente', hint: nameOf(fuentes, filter.fuente_ids) })
    if (filter.estado_ids?.length)     labels.push({ label: 'Estado', hint: nameOf(estados, filter.estado_ids) })
    if (filter.sede_ids?.length)       labels.push({ label: 'Sede',   hint: nameOf(sedes, filter.sede_ids) })
    if (filter.api_client_ids?.length) labels.push({ label: 'Proveedor', hint: nameOf(apiClients, filter.api_client_ids) })
    if (filter.incluir_recontactos)    labels.push({ label: 'Incluye recontactos del proveedor', hint: 'Suma leads donde el proveedor sólo aparece en algún recontacto' })
    if (labels.length === 0) labels.push({ label: 'Sin filtros: comparte TODOS los leads del CRM', hint: '⚠️ Esto da visibilidad amplia' })
    return labels
  }

  async function deleteRule(id) {
    setMsg(null)
    try {
      await api.delete(`/api/sharing-rules/${id}`)
      setConfirmDelete(null)
      await loadAll()
      setMsg({ tipo: 'ok', texto: 'Regla eliminada.' })
    } catch (e) {
      const detail = e?.response?.data?.detail || 'Error al eliminar.'
      setMsg({ tipo: 'error', texto: detail })
    }
  }

  async function toggleActive(rule) {
    setMsg(null)
    try {
      await api.patch(`/api/sharing-rules/${rule.id}`, { is_active: !rule.is_active })
      await loadAll()
    } catch (e) {
      const detail = e?.response?.data?.detail || 'Error al cambiar estado.'
      setMsg({ tipo: 'error', texto: detail })
    }
  }

  function FilterSummary({ filter }) {
    const f = filter || {}
    const parts = []
    if (f.fuente_ids?.length) parts.push(`${f.fuente_ids.length} fuente${f.fuente_ids.length > 1 ? 's' : ''}`)
    if (f.estado_ids?.length) parts.push(`${f.estado_ids.length} estado${f.estado_ids.length > 1 ? 's' : ''}`)
    if (f.sede_ids?.length) parts.push(`${f.sede_ids.length} sede${f.sede_ids.length > 1 ? 's' : ''}`)
    if (f.api_client_ids?.length) {
      const label = `${f.api_client_ids.length} proveedor${f.api_client_ids.length > 1 ? 'es' : ''}`
      // Marca visual de que la regla extiende sobre recontactos (V086).
      parts.push(f.incluir_recontactos ? `${label} (incl. recontactos)` : label)
    }
    if (parts.length === 0) return <span className="text-xs text-amber-700">⚠️ Sin filtros (no comparte nada)</span>
    return <span className="text-xs text-slate-500">{parts.join(' · ')}</span>
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900 flex items-center gap-2">
            <Share2 size={18} />
            Vistas compartidas
          </h2>
          <p className="text-sm text-slate-600">
            Define qué leads ve cada rol personalizado según criterios (fuente, estado, sede, proveedor). Patrón Sharing Rules: la regla se aplica en runtime a todos los leads que matcheen.
          </p>
        </div>
        <Button onClick={startNew} className="shrink-0">
          <Plus size={16} className="mr-1" />
          Nueva regla
        </Button>
      </div>

      <MsgBox msg={msg} onClose={() => setMsg(null)} />

      {loading ? (
        <p className="text-sm text-slate-500">Cargando…</p>
      ) : (
        <div className="border border-slate-200 rounded-lg overflow-hidden bg-white">
          {rules.length === 0 ? (
            <div className="p-8 text-center text-slate-500 text-sm">
              No hay reglas. Creá una para que los usuarios con rol personalizado vean leads compartidos.
            </div>
          ) : (
            <table className="w-full text-sm">
              <thead className="bg-slate-50 border-b border-slate-200">
                <tr>
                  <th className="text-left px-4 py-2 font-medium text-slate-600 text-xs uppercase">Regla</th>
                  <th className="text-left px-4 py-2 font-medium text-slate-600 text-xs uppercase">Rol</th>
                  <th className="text-left px-4 py-2 font-medium text-slate-600 text-xs uppercase">Filtro</th>
                  <th className="text-left px-4 py-2 font-medium text-slate-600 text-xs uppercase">Permisos</th>
                  <th className="text-center px-4 py-2 font-medium text-slate-600 text-xs uppercase w-24">Estado</th>
                  <th className="text-right px-4 py-2 font-medium text-slate-600 text-xs uppercase w-32">Acciones</th>
                </tr>
              </thead>
              <tbody>
                {rules.map((r) => (
                  <tr key={r.id} className="border-b border-slate-100 hover:bg-slate-50/60">
                    <td className="px-4 py-2.5">
                      <p className="font-medium text-slate-900">{r.name}</p>
                      {r.description && <p className="text-xs text-slate-500">{r.description}</p>}
                    </td>
                    <td className="px-4 py-2.5 text-slate-700">{r.role_name}</td>
                    <td className="px-4 py-2.5"><FilterSummary filter={r.filter_jsonb} /></td>
                    <td className="px-4 py-2.5">
                      <div className="flex gap-1.5 text-[10px]">
                        {r.can_view && <span className="bg-blue-50 text-blue-700 px-1.5 py-0.5 rounded">ver</span>}
                        {r.can_edit && <span className="bg-purple-50 text-purple-700 px-1.5 py-0.5 rounded">editar</span>}
                      </div>
                    </td>
                    <td className="px-4 py-2.5 text-center">
                      <button
                        onClick={() => toggleActive(r)}
                        className={`text-[10px] px-2 py-0.5 rounded inline-flex items-center gap-1 ${
                          r.is_active ? 'bg-green-100 text-green-700' : 'bg-slate-200 text-slate-600'
                        }`}
                      >
                        <Power size={10} />
                        {r.is_active ? 'Activa' : 'Inactiva'}
                      </button>
                    </td>
                    <td className="px-4 py-2.5 text-right">
                      <div className="inline-flex gap-1">
                        <button
                          onClick={() => startEdit(r)}
                          className="p-1.5 rounded-md hover:bg-slate-100 text-slate-500"
                          title="Editar"
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          onClick={() => setConfirmDelete(r.id)}
                          className="p-1.5 rounded-md hover:bg-red-50 text-red-500"
                          title="Eliminar"
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Modal de edición — items-start (no items-center) para que cuando el
          contenido sea mas alto que el viewport, el header no quede cortado
          arriba. my-auto + my-8 sirven como margen mínimo. */}
      {editing && (
        <div className="fixed inset-0 bg-black/40 flex items-start sm:items-center justify-center z-50 p-4 overflow-y-auto">
          <div className="bg-white rounded-lg shadow-xl max-w-2xl w-full p-5 space-y-4 my-8 max-h-[calc(100vh-4rem)] overflow-y-auto">
            <div className="flex items-center justify-between">
              <h3 className="font-semibold text-slate-900">
                {editing.id ? 'Editar regla' : 'Nueva regla'}
              </h3>
              <button onClick={() => setEditing(null)} className="text-slate-400 hover:text-slate-600">
                <XIcon size={18} />
              </button>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-slate-700">Nombre <span className="text-red-500">*</span></label>
                <SafeTextInput
                  value={editing.name}
                  onChange={(v) => setEditing({ ...editing, name: v })}
                  placeholder="ej. Marketing ve Facebook"
                  name="crm_sharing_rule_name_unique"
                  className="mt-1 w-full px-3 py-2 text-sm border border-slate-300 rounded-md"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-slate-700">Rol al que se comparte <span className="text-red-500">*</span></label>
                <select
                  value={editing.role_id || ''}
                  onChange={(e) => setEditing({ ...editing, role_id: parseInt(e.target.value, 10) })}
                  disabled={!!editing.id}  // No permitir cambiar rol en edición
                  className="mt-1 w-full px-3 py-2 text-sm border border-slate-300 rounded-md bg-white disabled:bg-slate-50"
                >
                  {roles.map((r) => (
                    <option key={r.id} value={r.id}>{r.name}</option>
                  ))}
                </select>
              </div>
            </div>
            <div>
              <label className="text-xs font-medium text-slate-700">Descripción</label>
              <SafeTextInput
                value={editing.description}
                onChange={(v) => setEditing({ ...editing, description: v })}
                placeholder="¿Qué leads comparte esta regla y para qué?"
                name="crm_sharing_rule_desc_unique"
                className="mt-1 w-full px-3 py-2 text-sm border border-slate-300 rounded-md"
              />
            </div>

            <div className="border-t border-slate-200 pt-3">
              <h4 className="text-sm font-semibold text-slate-700 mb-2">Filtros (los leads que matcheen TODOS se comparten)</h4>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <MultiCheck
                  label="Fuentes"
                  options={fuentes.map((f) => ({ id: f.id, nombre: f.nombre }))}
                  value={editing.filter_jsonb.fuente_ids}
                  onChange={(v) => setEditing({ ...editing, filter_jsonb: { ...editing.filter_jsonb, fuente_ids: v } })}
                />
                <MultiCheck
                  label="Estados"
                  options={estados.map((e) => ({ id: e.id, nombre: e.nombre }))}
                  value={editing.filter_jsonb.estado_ids}
                  onChange={(v) => setEditing({ ...editing, filter_jsonb: { ...editing.filter_jsonb, estado_ids: v } })}
                />
                <MultiCheck
                  label="Sedes"
                  options={sedes.map((s) => ({ id: s.id, nombre: s.nombre }))}
                  value={editing.filter_jsonb.sede_ids}
                  onChange={(v) => setEditing({ ...editing, filter_jsonb: { ...editing.filter_jsonb, sede_ids: v } })}
                />
                <MultiCheck
                  label="Proveedor"
                  options={apiClients.map((c) => ({ id: c.id, nombre: c.nombre }))}
                  value={editing.filter_jsonb.api_client_ids}
                  onChange={(v) => setEditing({ ...editing, filter_jsonb: { ...editing.filter_jsonb, api_client_ids: v } })}
                />
              </div>

              {/* Toggle: extender el filtro "Proveedor" para incluir leads
                  donde el proveedor mandó algún recontacto (no solo origen).
                  Solo tiene sentido si hay al menos un proveedor seleccionado. */}
              {editing.filter_jsonb.api_client_ids?.length > 0 && (
                <div className="border-t border-slate-100 mt-3 pt-3">
                  <label className="flex items-start gap-2 cursor-pointer text-sm">
                    <input
                      type="checkbox"
                      checked={!!editing.filter_jsonb.incluir_recontactos}
                      onChange={(e) => setEditing({
                        ...editing,
                        filter_jsonb: { ...editing.filter_jsonb, incluir_recontactos: e.target.checked },
                      })}
                      className="rounded mt-0.5"
                    />
                    <div>
                      <div className="font-medium text-slate-700">Incluir leads con recontactos del proveedor</div>
                      <div className="text-xs text-slate-500 mt-0.5">
                        Si está activo, también comparte leads donde el proveedor seleccionado mandó al menos un
                        recontacto, aunque el origen del lead sea otro (ej: lead viejo cargado por carga masiva
                        que después wedo trajo de vuelta con una nueva campaña).
                      </div>
                    </div>
                  </label>
                </div>
              )}

              <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md p-2 mt-3 flex items-start gap-2">
                <AlertCircle size={12} className="mt-0.5 shrink-0" />
                <span>Si todos los filtros quedan vacíos, la regla no comparte ningún lead (defensa anti-config vacía). Marcá al menos un valor en algún campo.</span>
              </p>
            </div>

            <div className="border-t border-slate-200 pt-3 flex items-center gap-4 text-sm">
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={editing.can_view} onChange={(e) => setEditing({ ...editing, can_view: e.target.checked })} className="rounded" />
                <span><Eye size={12} className="inline mr-1" /> Puede ver</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={editing.can_edit} onChange={(e) => setEditing({ ...editing, can_edit: e.target.checked })} className="rounded" />
                <span><Pencil size={12} className="inline mr-1" /> Puede editar</span>
              </label>
              <label className="flex items-center gap-2 cursor-pointer ml-auto">
                <input type="checkbox" checked={editing.is_active} onChange={(e) => setEditing({ ...editing, is_active: e.target.checked })} className="rounded" />
                <span>Activa</span>
              </label>
            </div>

            <div className="flex justify-end gap-2 pt-2">
              <Button variant="ghost" onClick={() => setEditing(null)}>Cancelar</Button>
              <Button onClick={requestSaveRule}>
                <Save size={14} className="mr-1" />
                {editing.id ? 'Guardar cambios' : 'Crear regla'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Confirm delete */}
      {confirmDelete !== null && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-5 space-y-4">
            <h3 className="font-semibold text-slate-900">¿Eliminar regla?</h3>
            <p className="text-sm text-slate-600">Los usuarios con el rol asociado dejarán de ver los leads compartidos por esta regla.</p>
            <div className="flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setConfirmDelete(null)}>Cancelar</Button>
              <Button onClick={() => deleteRule(confirmDelete)} className="bg-red-600 hover:bg-red-700">Eliminar</Button>
            </div>
          </div>
        </div>
      )}

      {/* V087.1 — Preview de impacto antes de aplicar la sharing rule.
          Muestra a qué rol se comparte, cuántos usuarios lo tienen y los
          criterios de filtrado en lenguaje natural. */}
      {editing && (() => {
        const role = roles.find(r => r.id === editing.role_id)
        const userCount = role?.user_count ?? 0
        const accessTags = []
        if (editing.can_view) accessTags.push('Pueden ver los leads')
        if (editing.can_edit) accessTags.push('Pueden editarlos')
        if (!editing.is_active) accessTags.push('⚠️ La regla queda INACTIVA: el cambio no aplica todavía')
        return (
          <ApplyChangesPreviewDialog
            open={showPreview}
            title={editing.id ? `Actualizar regla "${editing.name.trim()}"` : `Crear regla "${editing.name.trim() || 'sin nombre'}"`}
            subtitle={role ? `Rol asociado: ${role.name}` : null}
            impactCount={
              userCount > 0
                ? {
                    value: userCount,
                    label: `usuario${userCount === 1 ? '' : 's'} con el rol "${role?.name}" recibirán acceso adicional al guardar`,
                  }
                : null
            }
            adds={describeFilter(editing.filter_jsonb)}
            removes={accessTags.length ? accessTags.map(t => ({ label: t })) : []}
            notes={
              userCount === 0
                ? `Ningún usuario tiene todavía el rol "${role?.name || ''}". Cuando le asignes el rol a alguien, ya va a ver estos leads automáticamente.`
                : null
            }
            confirmLabel={editing.id ? 'Sí, actualizar regla' : 'Sí, crear regla'}
            applying={savingRule}
            onConfirm={applySaveRule}
            onCancel={() => setShowPreview(false)}
          />
        )
      })()}
    </div>
  )
}
