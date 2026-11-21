/**
 * Pantalla de gestión de Roles y Permisos (ADR-0011, Sprint 3).
 *
 * Adaptada del componente de gestión de roles de productos hermanos.
 * Misma UX por coherencia entre productos:
 *   - Lista de roles a la izquierda (built-in arriba, custom abajo).
 *   - Panel derecho con grupos de permisos + checkboxes + permission key visible.
 *   - Botones: Guardar permisos / Nuevo rol / Eliminar (solo customs).
 */
import { useEffect, useMemo, useState } from 'react'
import { Save, Shield, Plus, Trash2, X as XIcon, Lock, AlertCircle, Users, EyeOff, Eye, Edit3, ArrowRightLeft, Search, Check, Globe } from 'lucide-react'
import { Button } from '@/components/ui/button'
import SafeTextInput from '@/components/ui/SafeTextInput'
import api from '@/lib/api'
import { PERMISSION_GROUPS } from '@/lib/permissions'
import { FIELD_CATALOG } from '@/lib/fieldCatalog'
import ApplyChangesPreviewDialog from '@/components/shared/ApplyChangesPreviewDialog'
import UnsavedChangesGuard from '@/components/shared/UnsavedChangesGuard'

// V087.1 — diccionario plano permission_key → label legible. Se usa para
// que el preview modal muestre "Ver leads" en vez de "leads.view".
const PERMISSION_LABELS = (() => {
  const out = {}
  for (const g of PERMISSION_GROUPS) {
    for (const p of g.perms) out[p.key] = p.label
  }
  return out
})()

// V087.1 — Catálogo flat de field keys para preview de field-level security.
// Convierte field.<obj>.<field>.<kind> en "Lead · Teléfono (Lectura)".
const FIELD_LABELS = (() => {
  const out = {}
  for (const [objKey, fields] of Object.entries(FIELD_CATALOG)) {
    for (const f of fields) {
      const objCap = objKey.charAt(0).toUpperCase() + objKey.slice(1)
      out[`field.${objKey}.${f.key}.read`] = `${objCap} · ${f.label} (lectura)`
      out[`field.${objKey}.${f.key}.edit`] = `${objCap} · ${f.label} (edición)`
    }
  }
  return out
})()

function permLabel(key, currentPerms = {}) {
  if (key === 'asignacion.scope') {
    const sc = currentPerms['asignacion.scope'] || 'equipo'
    const map = { global: 'Global (como admin)', equipo: 'Solo su equipo', personalizado: 'Personalizado' }
    return `Alcance asignación leads: ${map[sc] || sc}`
  }
  if (key === 'asignacion.allowed_users') {
    const count = (currentPerms['asignacion.allowed_users'] || []).length
    return `Usuarios autorizados para asignar leads (${count} seleccionados)`
  }
  return PERMISSION_LABELS[key] || FIELD_LABELS[key] || key
}

function MsgBox({ msg, onClose }) {
  if (!msg) return null
  const isOk = msg.tipo === 'ok'
  return (
    <div className={`rounded-lg p-3 text-sm flex items-center justify-between gap-2 ${
      isOk ? 'bg-green-50 border border-green-200 text-green-800' : 'bg-red-50 border border-red-200 text-red-700'
    }`}>
      <span>{msg.texto}</span>
      <button onClick={onClose} className="opacity-60 hover:opacity-100">
        <XIcon size={14} />
      </button>
    </div>
  )
}

export default function RolesPage() {
  const [roles, setRoles] = useState([])
  const [loading, setLoading] = useState(false)
  const [selectedId, setSelectedId] = useState(null)
  const [perms, setPerms] = useState({})
  const [saving, setSaving] = useState(false)
  const [showNew, setShowNew] = useState(false)
  // ADR-0011 Amendment 2026-06-15 — el portal del proveedor externo quedó
  // descartado. is_external se mantiene en backend para deploys mixtos pero
  // ya no se expone en el formulario. Si en el futuro vuelve la necesidad,
  // reabrir el ADR y restaurar el checkbox.
  const [newForm, setNewForm] = useState({ name: '', description: '' })
  const [creating, setCreating] = useState(false)
  const [msg, setMsg] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(null)
  // V087.1 — preview de impacto antes de aplicar (clase mundial).
  const [showPreview, setShowPreview] = useState(false)
  const [usersList, setUsersList] = useState([])
  const [userSearch, setUserSearch] = useState('')
  const [userRoleFilter, setUserRoleFilter] = useState('todos')

  async function load() {
    setLoading(true)
    try {
      const [rolesRes, usersRes] = await Promise.all([
        api.get('/api/roles'),
        api.get('/auth/users').catch(() => ({ data: [] })),
      ])
      const arr = Array.isArray(rolesRes.data) ? rolesRes.data : []
      setRoles(arr)
      const uArr = Array.isArray(usersRes.data) ? usersRes.data.filter(u => u.is_active !== false) : []
      setUsersList(uArr)
      if (arr.length && selectedId === null) selectRole(arr[0])
    } catch {
      setMsg({ tipo: 'error', texto: 'Error al cargar los roles' })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [])

  function selectRole(r) {
    setSelectedId(r.id)
    setPerms({ ...(r.permissions || {}) })
  }

  function toggle(key) {
    setPerms((p) => {
      const nextVal = !p[key]
      const next = { ...p, [key]: nextVal }
      if (key === 'asignacion.manage' && nextVal && !next['asignacion.scope']) {
        next['asignacion.scope'] = 'equipo'
      }
      return next
    })
  }

  function setAsignacionScope(scope) {
    setPerms((p) => ({ ...p, 'asignacion.scope': scope }))
  }

  function toggleAllowedUser(userId) {
    setPerms((p) => {
      const current = Array.isArray(p['asignacion.allowed_users']) ? p['asignacion.allowed_users'] : []
      const next = current.includes(userId)
        ? current.filter(id => id !== userId)
        : [...current, userId]
      return { ...p, 'asignacion.allowed_users': next }
    })
  }

  function selectAllAllowed(usersToSelect) {
    setPerms((p) => ({
      ...p,
      'asignacion.allowed_users': usersToSelect.map(u => u.id),
    }))
  }

  function clearAllowedUsers() {
    setPerms((p) => ({
      ...p,
      'asignacion.allowed_users': [],
    }))
  }

  const filteredUsers = useMemo(() => {
    let list = usersList
    if (userRoleFilter === 'supervisor') {
      list = list.filter(u => u.role === 'supervisor')
    } else if (userRoleFilter === 'asesor') {
      list = list.filter(u => u.role === 'asesor')
    }
    if (userSearch.trim()) {
      const q = userSearch.toLowerCase().trim()
      list = list.filter(u => {
        const fullName = `${u.first_name || ''} ${u.last_name || ''}`.toLowerCase()
        const email = (u.email || '').toLowerCase()
        return fullName.includes(q) || email.includes(q)
      })
    }
    return list
  }, [usersList, userRoleFilter, userSearch])

  // Field-Level Security (ADR-0011 Sprint 5).
  // Convencion: si la key NO esta en `perms`, default = true (acceso libre).
  // Solo persistimos `false` para no inflar el JSONB con redundancia.
  function fieldFlag(obj, field, kind) {
    const k = `field.${obj}.${field}.${kind}`
    return perms[k] !== false
  }

  function toggleFieldFlag(obj, field, kind) {
    const k = `field.${obj}.${field}.${kind}`
    setPerms((p) => {
      const next = { ...p }
      // Si actualmente es true (sea explicito o por default), apretarlo lo
      // pone en false (restriccion). Si es false, lo borramos -> vuelve al
      // default true.
      if (next[k] === false) {
        delete next[k]
      } else {
        next[k] = false
      }
      // Coherencia: si quito READ, EDIT tambien queda restringido.
      if (kind === 'read' && next[k] === false) {
        next[`field.${obj}.${field}.edit`] = false
      }
      // Si vuelvo a permitir READ, dejo EDIT con el default (true) — el admin
      // puede deshabilitarlo aparte si quiere lectura sin edicion.
      return next
    })
  }

  async function applyPermissions() {
    if (selectedId === null) return
    setSaving(true)
    setMsg(null)
    try {
      await api.patch(`/api/roles/${selectedId}/permissions`, { permissions: perms })
      setMsg({ tipo: 'ok', texto: 'Permisos actualizados. Los usuarios verán el cambio al volver a iniciar sesión.' })
      setShowPreview(false)
      await load()
    } catch (e) {
      const detail = e?.response?.data?.detail || 'Error al guardar los permisos'
      setMsg({ tipo: 'error', texto: detail })
    } finally {
      setSaving(false)
    }
  }

  // V087.1 — Diff entre los permisos guardados en backend y los del state.
  // Solo consideramos cambios "efectivos": si una key estaba en true y sigue
  // en true (aunque sea por default), no la mostramos como cambio.
  const permsDiff = useMemo(() => {
    const original = roles.find((r) => r.id === selectedId)?.permissions || {}
    const adds = []
    const removes = []
    const keys = new Set([...Object.keys(original), ...Object.keys(perms)])
    for (const k of keys) {
      const before = original[k]
      const after  = perms[k]

      if (k === 'asignacion.scope') {
        const bScope = before || (original['asignacion.manage'] ? 'equipo' : '')
        const aScope = after || (perms['asignacion.manage'] ? 'equipo' : '')
        if (bScope !== aScope && perms['asignacion.manage']) {
          adds.push(k)
        }
        continue
      }
      if (k === 'asignacion.allowed_users') {
        const bUsers = Array.isArray(before) ? [...before].sort().join(',') : ''
        const aUsers = Array.isArray(after) ? [...after].sort().join(',') : ''
        if (bUsers !== aUsers && perms['asignacion.manage'] && perms['asignacion.scope'] === 'personalizado') {
          adds.push(k)
        }
        continue
      }

      if (before === after) continue
      // Para field flags: ausencia equivale a true. Solo persistimos `false`.
      // Si pasamos de "ausente (true)" a `false` → removes (se quita acceso).
      // Si pasamos de `false` a "ausente (true)" → adds (se devuelve acceso).
      if (k.startsWith('field.')) {
        const beforeAllowed = before !== false
        const afterAllowed  = after !== false
        if (beforeAllowed === afterAllowed) continue
        if (afterAllowed) adds.push(k); else removes.push(k)
      } else {
        // Permisos normales: true = activo, todo lo demás = inactivo.
        const beforeActive = !!before
        const afterActive  = !!after
        if (beforeActive === afterActive) continue
        if (afterActive) adds.push(k); else removes.push(k)
      }
    }
    return { adds, removes, total: adds.length + removes.length }
  }, [roles, selectedId, perms])

  const hasUnsavedChanges = permsDiff.total > 0

  function requestSave() {
    // Si no hay diff, no abrimos el modal — solo notificamos.
    if (!hasUnsavedChanges) {
      setMsg({ tipo: 'ok', texto: 'No hay cambios para guardar.' })
      return
    }
    setShowPreview(true)
  }

  async function createRole() {
    if (!newForm.name.trim()) {
      setMsg({ tipo: 'error', texto: 'El nombre del rol es requerido' })
      return
    }
    setCreating(true)
    setMsg(null)
    try {
      const { data } = await api.post('/api/roles', {
        name: newForm.name.trim(),
        description: newForm.description.trim() || null,
        permissions: {},
        is_external: false,  // Amendment ADR-0011 — portal proveedor descartado
      })
      setShowNew(false)
      setNewForm({ name: '', description: '' })
      await load()
      // Seleccionar el rol recién creado
      if (data?.id) {
        setSelectedId(data.id)
        setPerms({})
      }
      setMsg({ tipo: 'ok', texto: `Rol "${data.name}" creado. Marcá los permisos y guardalos.` })
    } catch (e) {
      const detail = e?.response?.data?.detail || 'Error al crear el rol'
      setMsg({ tipo: 'error', texto: detail })
    } finally {
      setCreating(false)
    }
  }

  async function deleteRole(roleId) {
    setMsg(null)
    try {
      const { data } = await api.delete(`/api/roles/${roleId}`)
      const affected = data?.users_affected ?? 0
      // ADR-0011 patrón estándar: el delete desvincula transparente. Mostramos
      // cuántos usuarios quedaron en el rol legacy.
      const msg = affected > 0
        ? `Rol eliminado. ${affected} usuario${affected === 1 ? '' : 's'} volvió al rol legacy.`
        : 'Rol eliminado.'
      setMsg({ tipo: 'ok', texto: msg })
      setSelectedId(null)
      setPerms({})
      await load()
    } catch (e) {
      const status = e?.response?.status
      const detail = e?.response?.data?.detail || 'Error al eliminar el rol'
      let texto = detail
      if (status === 403) texto = 'No se puede eliminar un rol built-in (admin/supervisor/asesor).'
      setMsg({ tipo: 'error', texto })
    } finally {
      setConfirmDelete(null)
    }
  }

  const selected = roles.find((r) => r.id === selectedId)
  const isBuiltin = !!selected?.is_builtin

  return (
    <div className="space-y-4">
      {/* Header de la página */}
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-slate-900">Roles y Permisos</h2>
          <p className="text-sm text-slate-600">
            Define qué módulos puede ver cada rol del CRM. Los cambios aplican al próximo inicio de sesión.
          </p>
        </div>
        <Button onClick={() => setShowNew(true)} className="shrink-0">
          <Plus size={16} className="mr-1" />
          Nuevo rol
        </Button>
      </div>

      <MsgBox msg={msg} onClose={() => setMsg(null)} />

      {/* Formulario inline de "Nuevo rol" */}
      {showNew && (
        <div className="border border-slate-200 rounded-lg p-4 bg-slate-50 space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold text-slate-900">Crear rol</h3>
            <button
              onClick={() => { setShowNew(false); setNewForm({ name: '', description: '' }) }}
              className="text-slate-400 hover:text-slate-600"
            >
              <XIcon size={16} />
            </button>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-slate-700">Nombre <span className="text-red-500">*</span></label>
              {/* SafeTextInput blinda contra el bug del Escape → "null" causado por
                  extensiones del browser que sobreescriben el value directo al DOM. */}
              <SafeTextInput
                value={newForm.name}
                onChange={(v) => setNewForm({ ...newForm, name: v })}
                placeholder="ej. marketing, contabilidad"
                name="crm_role_name_unique"
                className="mt-1 w-full px-3 py-2 text-sm border border-slate-300 rounded-md"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-slate-700">Descripción</label>
              <SafeTextInput
                value={newForm.description}
                onChange={(v) => setNewForm({ ...newForm, description: v })}
                placeholder="¿Para qué equipo es este rol?"
                name="crm_role_description_unique"
                className="mt-1 w-full px-3 py-2 text-sm border border-slate-300 rounded-md"
              />
            </div>
          </div>
          <div className="flex justify-end gap-2">
            <Button
              variant="ghost"
              onClick={() => { setShowNew(false); setNewForm({ name: '', description: '' }) }}
            >
              Cancelar
            </Button>
            <Button onClick={createRole} disabled={creating}>
              {creating ? 'Creando…' : 'Crear rol'}
            </Button>
          </div>
        </div>
      )}

      {loading ? (
        <p className="text-sm text-slate-500">Cargando…</p>
      ) : (
        // Layout responsive: 1 columna en mobile/tablet, 2 columnas en pantallas >= lg.
        // Antes era col-span-3/9 fijos -> requería zoom 90% para verse bien dentro
        // del wrapper de Configuración (que ya consume espacio con su sidebar).
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-4">
          {/* Lista de roles */}
          <aside className="lg:col-span-4 xl:col-span-3 border border-slate-200 rounded-lg p-2 space-y-1 h-fit">
            {roles.length === 0 && (
              <p className="text-sm text-slate-500 p-3">Sin roles</p>
            )}
            {roles.map((r) => {
              const isSelected = selectedId === r.id
              return (
                <button
                  key={r.id}
                  onClick={() => selectRole(r)}
                  className={`w-full text-left px-3 py-2 rounded-md text-sm flex items-center gap-2 transition-colors ${
                    isSelected
                      ? 'bg-indigo-600 text-white'
                      : 'hover:bg-slate-100 text-slate-700'
                  }`}
                >
                  <Shield className="h-4 w-4 shrink-0" />
                  <span className="flex-1 truncate">{r.name}</span>
                  {r.is_builtin && (
                    <span className={`text-[10px] px-1.5 py-0.5 rounded ${
                      isSelected ? 'bg-white/20' : 'bg-slate-200 text-slate-600'
                    }`}>
                      built-in
                    </span>
                  )}
                  {r.user_count > 0 && (
                    <span className={`text-[10px] px-1.5 py-0.5 rounded flex items-center gap-0.5 ${
                      isSelected ? 'bg-white/20' : 'bg-blue-50 text-blue-700'
                    }`}>
                      <Users size={10} />
                      {r.user_count}
                    </span>
                  )}
                </button>
              )
            })}
          </aside>

          {/* Panel de permisos */}
          <section className="lg:col-span-8 xl:col-span-9 border border-slate-200 rounded-lg p-4 md:p-5 space-y-4">
            {selected ? (
              <>
                <header className="flex items-start justify-between gap-3 border-b border-slate-200 pb-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2">
                      <h3 className="text-base font-semibold text-slate-900 truncate">{selected.name}</h3>
                      {selected.is_builtin && (
                        <span className="text-[10px] bg-slate-100 text-slate-600 px-1.5 py-0.5 rounded inline-flex items-center gap-1">
                          <Lock size={10} /> built-in
                        </span>
                      )}
                      {selected.is_external && (
                        <span className="text-[10px] bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded">
                          externo
                        </span>
                      )}
                    </div>
                    {selected.description && (
                      <p className="text-sm text-slate-600 mt-1">{selected.description}</p>
                    )}
                    {selected.permissions?._all === true && (
                      <p className="text-xs text-amber-700 mt-2 flex items-center gap-1">
                        <AlertCircle size={12} />
                        Este rol tiene el flag <code className="bg-amber-50 px-1 rounded">_all</code>: ve todo. Los checkboxes individuales no aplican.
                      </p>
                    )}
                  </div>
                  <div className="flex gap-2 shrink-0">
                    {!isBuiltin && (
                      <Button
                        variant="ghost"
                        onClick={() => setConfirmDelete(selected.id)}
                        className="text-red-600 hover:bg-red-50"
                      >
                        <Trash2 size={14} className="mr-1" /> Eliminar
                      </Button>
                    )}
                    <Button onClick={requestSave} disabled={saving || !hasUnsavedChanges}>
                      <Save size={14} className="mr-1" />
                      {saving ? 'Guardando…' : hasUnsavedChanges ? `Revisar y guardar (${permsDiff.total})` : 'Sin cambios'}
                    </Button>
                  </div>
                </header>

                {PERMISSION_GROUPS.map((g) => (
                  <div key={g.group} className="space-y-2">
                    <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wide">{g.group}</h4>
                    {/* 1 col mobile, 2 cols xl+ — antes salía a 2 cols desde md y los
                        permisos quedaban apretados con la permission key tapada. */}
                    <div className="grid grid-cols-1 xl:grid-cols-2 gap-1">
                      {g.perms.map((p) => {
                        const isAsignacion = p.key === 'asignacion.manage'
                        const isChecked = !!perms[p.key]
                        const currentScope = perms['asignacion.scope'] || 'equipo'

                        return (
                          <div key={p.key} className={isAsignacion && isChecked ? 'col-span-full' : ''}>
                            <label
                              className="flex items-center gap-2 px-3 py-2 rounded-md hover:bg-slate-50 cursor-pointer min-w-0"
                            >
                              <input
                                type="checkbox"
                                checked={isChecked}
                                onChange={() => toggle(p.key)}
                                className="rounded shrink-0 text-indigo-600 focus:ring-indigo-500"
                              />
                              <span className="text-sm text-slate-700 truncate font-medium">{p.label}</span>
                              <code className="text-[10px] text-slate-400 ml-auto truncate">{p.key}</code>
                            </label>

                            {/* Sub-panel de opciones cuando asignacion.manage está activo */}
                            {isAsignacion && isChecked && (
                              <div className="mt-2 mb-3 p-4 rounded-xl bg-slate-50 border border-indigo-100 dark:bg-slate-900/40 dark:border-indigo-900/40 shadow-xs space-y-3.5 animate-in fade-in duration-150">
                                <div className="flex items-center justify-between border-b border-slate-200/80 pb-2.5">
                                  <div className="flex items-center gap-2">
                                    <span className="p-1 rounded-md bg-indigo-100 text-indigo-700 dark:bg-indigo-900/60 dark:text-indigo-300">
                                      <ArrowRightLeft size={14} />
                                    </span>
                                    <span className="text-xs font-semibold text-slate-800 dark:text-slate-200 uppercase tracking-wide">
                                      Alcance de la asignación de leads
                                    </span>
                                  </div>
                                  <span className="text-[11px] font-medium px-2.5 py-0.5 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-200/60">
                                    {currentScope === 'global' ? '🌐 Global' : currentScope === 'personalizado' ? '⚙️ Personalizado' : '👥 Solo su equipo'}
                                  </span>
                                </div>

                                <div className="grid grid-cols-1 md:grid-cols-3 gap-2.5">
                                  {/* 1. Global */}
                                  <div
                                    onClick={() => setAsignacionScope('global')}
                                    className={`p-3 rounded-lg border text-left cursor-pointer transition-all ${
                                      currentScope === 'global'
                                        ? 'border-indigo-600 bg-white ring-2 ring-indigo-500/20 shadow-xs'
                                        : 'border-slate-200 bg-white/70 hover:border-slate-300 hover:bg-white'
                                    }`}
                                  >
                                    <div className="flex items-center gap-2 font-medium text-xs text-slate-900">
                                      <input
                                        type="radio"
                                        name="asignacionScope"
                                        checked={currentScope === 'global'}
                                        onChange={() => setAsignacionScope('global')}
                                        className="text-indigo-600"
                                      />
                                      <span>🌐 Global (Como Admin)</span>
                                    </div>
                                    <p className="text-[11px] text-slate-500 mt-1 pl-5 leading-relaxed">
                                      Puede asignar leads a cualquier asesor o supervisor activo de toda la empresa.
                                    </p>
                                  </div>

                                  {/* 2. Solo su equipo */}
                                  <div
                                    onClick={() => setAsignacionScope('equipo')}
                                    className={`p-3 rounded-lg border text-left cursor-pointer transition-all ${
                                      currentScope === 'equipo'
                                        ? 'border-indigo-600 bg-white ring-2 ring-indigo-500/20 shadow-xs'
                                        : 'border-slate-200 bg-white/70 hover:border-slate-300 hover:bg-white'
                                    }`}
                                  >
                                    <div className="flex items-center gap-2 font-medium text-xs text-slate-900">
                                      <input
                                        type="radio"
                                        name="asignacionScope"
                                        checked={currentScope === 'equipo'}
                                        onChange={() => setAsignacionScope('equipo')}
                                        className="text-indigo-600"
                                      />
                                      <span>👥 Solo su equipo</span>
                                    </div>
                                    <p className="text-[11px] text-slate-500 mt-1 pl-5 leading-relaxed">
                                      Encapsulado a su equipo actual: puede asignar a cualquiera de su equipo, sea supervisor o no.
                                    </p>
                                  </div>

                                  {/* 3. Personalizado */}
                                  <div
                                    onClick={() => setAsignacionScope('personalizado')}
                                    className={`p-3 rounded-lg border text-left cursor-pointer transition-all ${
                                      currentScope === 'personalizado'
                                        ? 'border-indigo-600 bg-white ring-2 ring-indigo-500/20 shadow-xs'
                                        : 'border-slate-200 bg-white/70 hover:border-slate-300 hover:bg-white'
                                    }`}
                                  >
                                    <div className="flex items-center gap-2 font-medium text-xs text-slate-900">
                                      <input
                                        type="radio"
                                        name="asignacionScope"
                                        checked={currentScope === 'personalizado'}
                                        onChange={() => setAsignacionScope('personalizado')}
                                        className="text-indigo-600"
                                      />
                                      <span>⚙️ Personalizado</span>
                                    </div>
                                    <p className="text-[11px] text-slate-500 mt-1 pl-5 leading-relaxed">
                                      Permite elegir supervisores y asesores específicos de la plataforma.
                                    </p>
                                  </div>
                                </div>

                                {/* Si es Personalizado: selector de usuarios */}
                                {currentScope === 'personalizado' && (
                                  <div className="mt-2 pt-3 border-t border-slate-200 space-y-2.5">
                                    <div className="flex flex-wrap items-center justify-between gap-2">
                                      <div className="text-xs font-semibold text-slate-700">
                                        Selecciona los supervisores y asesores autorizados:
                                      </div>
                                      <div className="flex items-center gap-2">
                                        <button
                                          type="button"
                                          onClick={() => selectAllAllowed(filteredUsers)}
                                          className="text-[11px] text-indigo-600 hover:text-indigo-800 font-medium"
                                        >
                                          Seleccionar visibles ({filteredUsers.length})
                                        </button>
                                        <span className="text-slate-300">|</span>
                                        <button
                                          type="button"
                                          onClick={clearAllowedUsers}
                                          className="text-[11px] text-slate-500 hover:text-slate-700 font-medium"
                                        >
                                          Deseleccionar todos
                                        </button>
                                      </div>
                                    </div>

                                    {/* Buscador + Filtros rápidos de rol */}
                                    <div className="flex items-center gap-2">
                                      <div className="relative flex-1">
                                        <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
                                        <input
                                          type="text"
                                          placeholder="Buscar supervisor o asesor por nombre o email..."
                                          value={userSearch}
                                          onChange={e => setUserSearch(e.target.value)}
                                          className="w-full text-xs pl-8 pr-3 py-1.5 border border-slate-200 rounded-md bg-white focus:outline-none focus:ring-1 focus:ring-indigo-500"
                                        />
                                      </div>
                                      <div className="flex items-center gap-1 bg-slate-100 p-0.5 rounded-md text-[11px]">
                                        <button
                                          type="button"
                                          onClick={() => setUserRoleFilter('todos')}
                                          className={`px-2 py-1 rounded font-medium transition-colors ${
                                            userRoleFilter === 'todos' ? 'bg-white shadow-xs text-slate-900' : 'text-slate-600 hover:text-slate-900'
                                          }`}
                                        >
                                          Todos ({usersList.length})
                                        </button>
                                        <button
                                          type="button"
                                          onClick={() => setUserRoleFilter('supervisor')}
                                          className={`px-2 py-1 rounded font-medium transition-colors ${
                                            userRoleFilter === 'supervisor' ? 'bg-white shadow-xs text-slate-900' : 'text-slate-600 hover:text-slate-900'
                                          }`}
                                        >
                                          Supervisores ({usersList.filter(u => u.role === 'supervisor').length})
                                        </button>
                                        <button
                                          type="button"
                                          onClick={() => setUserRoleFilter('asesor')}
                                          className={`px-2 py-1 rounded font-medium transition-colors ${
                                            userRoleFilter === 'asesor' ? 'bg-white shadow-xs text-slate-900' : 'text-slate-600 hover:text-slate-900'
                                          }`}
                                        >
                                          Asesores ({usersList.filter(u => u.role === 'asesor').length})
                                        </button>
                                      </div>
                                    </div>

                                    {/* Lista con checkboxes */}
                                    <div className="max-h-56 overflow-y-auto border border-slate-200 rounded-lg divide-y divide-slate-100 bg-white">
                                      {filteredUsers.length === 0 ? (
                                        <div className="p-4 text-center text-xs text-slate-400">
                                          No se encontraron usuarios activos.
                                        </div>
                                      ) : (
                                        filteredUsers.map(u => {
                                          const isAllowed = (perms['asignacion.allowed_users'] || []).includes(u.id)
                                          const name = [u.first_name, u.last_name].filter(Boolean).join(' ') || u.email
                                          return (
                                            <label
                                              key={u.id}
                                              className="flex items-center gap-3 px-3 py-2 hover:bg-slate-50 cursor-pointer text-xs"
                                            >
                                              <input
                                                type="checkbox"
                                                checked={isAllowed}
                                                onChange={() => toggleAllowedUser(u.id)}
                                                className="rounded shrink-0 text-indigo-600"
                                              />
                                              <div className="flex-1 min-w-0">
                                                <div className="flex items-center gap-2">
                                                  <span className="font-medium text-slate-800 truncate">{name}</span>
                                                  <span className={`text-[10px] px-1.5 py-0.2 rounded font-medium ${
                                                    u.role === 'supervisor'
                                                      ? 'bg-blue-50 text-blue-700 border border-blue-200'
                                                      : 'bg-slate-100 text-slate-600'
                                                  }`}>
                                                    {u.role === 'supervisor' ? 'Supervisor' : 'Asesor'}
                                                  </span>
                                                </div>
                                                <span className="text-[11px] text-slate-400 truncate block">{u.email}</span>
                                              </div>
                                            </label>
                                          )
                                        })
                                      )}
                                    </div>

                                    <div className="text-[11px] text-slate-500 font-medium">
                                      {(perms['asignacion.allowed_users'] || []).length} de {usersList.length} usuarios autorizados
                                    </div>
                                  </div>
                                )}
                              </div>
                            )}
                          </div>
                        )
                      })}
                    </div>
                  </div>
                ))}

                {/* Field-Level Security (ADR-0011 Sprint 5).
                    Patrón patrón estándar FLS: por cada objeto, definimos qué fields
                    son visibles/editables. Default: todo visible y editable
                    (compat con roles existentes). El admin restringe explícito. */}
                <div className="pt-4 border-t border-slate-200 space-y-3">
                  <div>
                    <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wide">
                      Seguridad a nivel de campo
                    </h4>
                    <p className="text-xs text-slate-500 mt-0.5">
                      Define qué campos sensibles puede ver y editar este rol.
                      Marca «No ver» para ocultar el campo o «No editar» para
                      bloquear cambios (campos marcados como No ver implican
                      No editar automáticamente).
                    </p>
                  </div>

                  {Object.entries(FIELD_CATALOG).map(([objKey, fields]) => (
                    <div key={objKey} className="border border-slate-100 rounded-md p-3 space-y-1">
                      <div className="text-xs font-medium text-slate-700 capitalize mb-2">
                        Objeto: {objKey}
                      </div>
                      <div className="grid grid-cols-12 gap-2 text-[11px] font-medium text-slate-500 px-2 pb-1 border-b border-slate-100">
                        <div className="col-span-6">Campo</div>
                        <div className="col-span-3 text-center">Lectura</div>
                        <div className="col-span-3 text-center">Edición</div>
                      </div>
                      {fields.map((f) => {
                        const canRead = fieldFlag(objKey, f.key, 'read')
                        const canEdit = fieldFlag(objKey, f.key, 'edit')
                        return (
                          <div
                            key={f.key}
                            className="grid grid-cols-12 gap-2 items-center px-2 py-1.5 rounded hover:bg-slate-50 text-sm"
                          >
                            <div className="col-span-6 flex items-center gap-2 min-w-0">
                              <span className="text-slate-700 truncate">{f.label}</span>
                              <code className="text-[10px] text-slate-400 truncate">{f.key}</code>
                            </div>
                            <div className="col-span-3 flex justify-center">
                              <button
                                type="button"
                                onClick={() => toggleFieldFlag(objKey, f.key, 'read')}
                                className={`inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium ${
                                  canRead
                                    ? 'bg-green-50 text-green-700 hover:bg-green-100'
                                    : 'bg-red-50 text-red-700 hover:bg-red-100'
                                }`}
                                title={canRead ? 'Marcar como No ver' : 'Permitir lectura'}
                              >
                                {canRead ? <Eye size={12} /> : <EyeOff size={12} />}
                                {canRead ? 'Ver' : 'No ver'}
                              </button>
                            </div>
                            <div className="col-span-3 flex justify-center">
                              <button
                                type="button"
                                onClick={() => toggleFieldFlag(objKey, f.key, 'edit')}
                                disabled={!canRead}
                                className={`inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium ${
                                  !canRead
                                    ? 'bg-slate-100 text-slate-400 cursor-not-allowed'
                                    : canEdit
                                    ? 'bg-blue-50 text-blue-700 hover:bg-blue-100'
                                    : 'bg-amber-50 text-amber-700 hover:bg-amber-100'
                                }`}
                                title={
                                  !canRead
                                    ? 'Habilita lectura primero'
                                    : canEdit
                                    ? 'Marcar como No editar'
                                    : 'Permitir edición'
                                }
                              >
                                <Edit3 size={12} />
                                {canEdit ? 'Editar' : 'Solo lectura'}
                              </button>
                            </div>
                          </div>
                        )
                      })}
                    </div>
                  ))}
                </div>
              </>
            ) : (
              <p className="text-sm text-slate-500">Selecciona un rol de la lista para editar sus permisos.</p>
            )}
          </section>
        </div>
      )}

      {/* V087.1 — Guard: si hay cambios sin guardar y el usuario intenta
          navegar fuera, le preguntamos primero. */}
      <UnsavedChangesGuard
        isDirty={hasUnsavedChanges}
        message="Tienes cambios de permisos sin guardar. Si sales ahora vas a perderlos. ¿Estás seguro?"
      />

      {/* V087.1 — Preview de impacto antes de aplicar. Muestra cuántos
          usuarios tiene el rol + diff legible de permisos. */}
      <ApplyChangesPreviewDialog
        open={showPreview}
        title={`Revisa los cambios al rol "${selected?.name || ''}"`}
        subtitle={`${permsDiff.total} permiso${permsDiff.total === 1 ? '' : 's'} a actualizar`}
        impactCount={
          (selected?.user_count ?? 0) > 0
            ? {
                value: selected.user_count,
                label: `usuario${selected.user_count === 1 ? '' : 's'} con este rol verán el cambio al volver a iniciar sesión`,
              }
            : null
        }
        adds={permsDiff.adds.map(k => permLabel(k, perms))}
        removes={permsDiff.removes.map(k => permLabel(k, perms))}
        notes={(() => {
          // V088 — Si el rol queda SIN permisos efectivos tras aplicar el
          // cambio, avisamos: los usuarios con este rol no van a poder
          // iniciar sesión. Patrón estándar de la industria.
          const hasAnyTrue = Object.values(perms || {}).some(v => v === true)
          const userCount = selected?.user_count ?? 0
          if (!hasAnyTrue && !selected?.is_builtin) {
            return (
              <>
                <strong>Atención:</strong> este rol no tiene ningún permiso marcado.
                {userCount > 0
                  ? ` Los ${userCount} usuario${userCount === 1 ? '' : 's'} con este rol no podrá${userCount === 1 ? '' : 'n'} iniciar sesión. Si querés quitarles acceso definitivamente, considerá usar "Deshabilitar usuario" en su lugar.`
                  : ' Cuando le asignes este rol a un usuario, ese usuario no va a poder iniciar sesión.'}
              </>
            )
          }
          if (userCount === 0) {
            return 'Este rol no tiene usuarios asignados todavía, así que el cambio no afecta a nadie por ahora.'
          }
          return null
        })()}
        confirmLabel="Sí, aplicar permisos"
        applying={saving}
        onConfirm={applyPermissions}
        onCancel={() => setShowPreview(false)}
      />

      {/* Diálogo simple de confirmación */}
      {confirmDelete !== null && (() => {
        const role = roles.find((r) => r.id === confirmDelete)
        const userCount = role?.user_count ?? 0
        return (
          <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
            <div className="bg-white rounded-lg shadow-xl max-w-md w-full p-5 space-y-4">
              <h3 className="font-semibold text-slate-900">¿Eliminar rol &quot;{role?.name}&quot;?</h3>
              <p className="text-sm text-slate-600">
                Esta acción no se puede deshacer.
              </p>
              {userCount > 0 && (
                <div className="bg-amber-50 border border-amber-200 text-amber-800 text-sm rounded-md p-3 space-y-1">
                  <p className="font-medium">
                    {userCount} usuario{userCount === 1 ? '' : 's'} {userCount === 1 ? 'tiene' : 'tienen'} este rol asignado.
                  </p>
                  <p className="text-xs">
                    Al eliminarlo, {userCount === 1 ? 'volverá' : 'volverán'} al comportamiento del rol legacy (asesor) y perderán los permisos custom inmediatamente.
                  </p>
                </div>
              )}
              <div className="flex justify-end gap-2">
                <Button variant="ghost" onClick={() => setConfirmDelete(null)}>Cancelar</Button>
                <Button onClick={() => deleteRole(confirmDelete)} className="bg-red-600 hover:bg-red-700">
                  Eliminar
                </Button>
              </div>
            </div>
          </div>
        )
      })()}
    </div>
  )
}
