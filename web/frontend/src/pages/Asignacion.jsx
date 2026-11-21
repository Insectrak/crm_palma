import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import {
  UserPlus, RefreshCw, Check, AlertCircle,
  Search, X, Users, ArrowRightLeft,
  ChevronLeft, ChevronRight, Trash2, List, Filter,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import DataTable from '@/components/shared/DataTable'
import ConfirmDialog from '@/components/shared/ConfirmDialog'
import LoadingSpinner from '@/components/shared/LoadingSpinner'
import ViewsBar from '@/components/shared/views/ViewsBar'
import SaveViewModal from '@/components/shared/views/SaveViewModal'
import useSavedViews from '@/hooks/useSavedViews'
import useCopyProtection from '@/hooks/useCopyProtection'
import useAuthStore from '@/store/authStore'
import useCrmStore from '@/store/crmStore'
import { hasPermission } from '@/lib/permissions'
import api from '@/lib/api'
import { fireAssignmentChanged } from '@/lib/events'
import { buildTeamGroups } from '@/lib/teamGroups'
import FilterBuilder from '@/components/ui/FilterBuilder'
import { Globe, Megaphone } from 'lucide-react'

const PAGE_SIZE = 50

const ASIG_COLUMNS = [
  { key: 'fuente', label: 'Fuente' },
  { key: 'campana', label: 'Campaña' },
  { key: 'estado', label: 'Estado' },
  { key: 'antecedente', label: 'Antecedente' },
  { key: 'creacion', label: 'Creación' },
]
const ASIG_STORAGE_KEY = 'asig_visible_cols'
function loadAsigCols() {
  try {
    const raw = localStorage.getItem(ASIG_STORAGE_KEY)
    if (raw) return new Set(JSON.parse(raw))
  } catch { /* ignore */ }
  return new Set(ASIG_COLUMNS.map(c => c.key))
}

function buildName(n, a) {
  return [n, a].filter(v => v && v.trim() && v.toUpperCase() !== 'NULL').join(' ') || 'Sin nombre'
}
function formatDateTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  const date = d.toLocaleDateString('es-PE', { day: '2-digit', month: 'short' })
  const time = d.toLocaleTimeString('es-PE', { hour: '2-digit', minute: '2-digit', hour12: false })
  return `${date}, ${time}`
}

// ─── Barra flotante de asignación masiva ─────────────────────────────────────
// V070.81: el boton trash abre directo el modal ConfirmDialog del padre
// (estandarizado con Leads.jsx). Antes existia una confirmacion inline
// adicional que producia doble confirmacion.
function BulkBar({ count, supervisorGroups, sinEquipo, onAssign, onDelete, onClear, isAssigning, isDeleting, canDelete }) {
  const [toAsesorId, setToAsesorId] = useState('')
  if (count === 0) return null
  const allGroups = [...supervisorGroups, sinEquipo.length > 0 ? { supervisor_id: '__sin__', supervisor_nombre: 'Sin equipo', asesores: sinEquipo } : null].filter(Boolean)

  return (
    <div className="sticky bottom-4 z-40 mx-auto max-w-2xl">
      <div className="bg-slate-900 text-white rounded-2xl shadow-2xl px-5 py-3.5 flex items-center gap-3 flex-wrap">
        <div className="flex items-center gap-2 shrink-0">
          <span className="bg-[var(--brand-primary)] text-white text-sm font-bold w-7 h-7 rounded-full flex items-center justify-center">{count}</span>
          <span className="text-sm font-medium">lead{count !== 1 ? 's' : ''} seleccionado{count !== 1 ? 's' : ''}</span>
        </div>
        <ArrowRightLeft size={14} className="text-slate-500 shrink-0" />
        <select
          value={toAsesorId}
          onChange={e => setToAsesorId(e.target.value)}
          className="flex-1 min-w-[180px] text-sm bg-slate-800 border border-slate-700 text-white rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-500"
        >
          <option value="">→ Seleccionar asesor…</option>
          {allGroups.map(g => (
            <optgroup key={g.supervisor_id} label={`Equipo: ${g.supervisor_nombre}`}>
              {g.asesores.map(a => (
                <option key={a.id} value={a.id}>{a.nombre_completo}</option>
              ))}
            </optgroup>
          ))}
        </select>
        <Button
          size="sm"
          disabled={!toAsesorId || isAssigning}
          onClick={() => { onAssign(toAsesorId); setToAsesorId('') }}
          className="shrink-0 gap-1.5"
        >
          <UserPlus size={13} />
          {isAssigning ? 'Asignando…' : `Asignar ${count}`}
        </Button>
        {canDelete && (
          <button
            onClick={onDelete}
            disabled={isDeleting}
            className="w-9 h-9 flex items-center justify-center rounded-lg bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 hover:text-red-300 hover:border-red-500/40 transition-colors shrink-0 disabled:opacity-50 disabled:cursor-not-allowed"
            title={`Eliminar ${count} seleccionado${count !== 1 ? 's' : ''}`}
          >
            <Trash2 size={15} />
          </button>
        )}
        <button onClick={onClear} className="text-slate-400 hover:text-white shrink-0">
          <X size={16} />
        </button>
      </div>
    </div>
  )
}

// ─── Tabla de leads seleccionables ───────────────────────────────────────────
// V063: migrada a DataTable global → hereda sticky thead, scroll horizontal
// siempre accesible y drag & drop de columnas. La logica de seleccion sigue
// igual: click en la fila toggle el lead, checkbox tambien (con stopPropagation
// para no doblar toggle).
function LeadsTable({ leads, selected, onToggle, onToggleAll, estados, isLoading, visibleCols, hasActiveFilters, onClearFilters, controlledOrder, onColumnOrderChange }) {
  const allSelected = leads.length > 0 && selected.size === leads.length
  const someSelected = selected.size > 0 && !allSelected
  const show = (key) => visibleCols.has(key)

  // Build dinamico del header — solo se incluyen las columnas visibles
  // (toggle desde el menu Campos). El orden de las arrastrables lo
  // maneja DataTable internamente y se persiste en localStorage.
  const headers = [
    {
      key: '_select',
      label: (
        <input
          type="checkbox"
          checked={allSelected}
          ref={el => { if (el) el.indeterminate = someSelected }}
          onChange={onToggleAll}
          onClick={e => e.stopPropagation()}
          className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
        />
      ),
      className: 'w-10',
    },
    { key: 'lead', label: 'Lead', className: 'min-w-[180px]' },
    ...(show('fuente') ? [{ key: 'fuente', label: 'Fuente' }] : []),
    ...(show('campana') ? [{ key: 'campana', label: 'Campaña' }] : []),
    ...(show('estado') ? [{ key: 'estado', label: 'Estado' }] : []),
    ...(show('antecedente') ? [{ key: 'antecedente', label: 'Antecedente' }] : []),
    ...(show('creacion') ? [{ key: 'creacion', label: 'Creación' }] : []),
  ]

  const renderCell = (lead, key) => {
    switch (key) {
      case '_select':
        return (
          <input
            type="checkbox"
            checked={selected.has(lead.id)}
            onChange={() => onToggle(lead.id)}
            onClick={e => e.stopPropagation()}
            className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
          />
        )
      case 'lead':
        return (
          <div className="pii-cell">
            <p className="text-sm font-medium text-gray-900 leading-tight">
              {buildName(lead.nombres, lead.apellidos)}
            </p>
            <p className="text-xs text-gray-400 font-mono mt-0.5">{lead.telefono || '—'}</p>
          </div>
        )
      case 'fuente':
        return (
          <div className="flex items-center gap-1.5 flex-wrap">
            {lead.fuente_nombre
              ? <Badge variant="secondary" className="capitalize text-xs">{lead.fuente_nombre}</Badge>
              : <span className="text-gray-400">—</span>}
            {lead.origen_wa_numero && (
              <span
                className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-200"
                title={`Línea WhatsApp de origen: ${lead.origen_wa_numero}`}
              >
                WA · {lead.origen_wa_numero}
              </span>
            )}
          </div>
        )
      case 'campana':
        return lead.campana
          ? <span className="text-xs text-gray-600 truncate max-w-[140px] inline-block" title={lead.campana}>{lead.campana}</span>
          : <span className="text-gray-300">—</span>
      case 'estado': {
        const estadoObj = estados.find(e => e.id === lead.estado_id)
        if (!estadoObj) return <span className="text-gray-400">—</span>
        return (
          <span
            className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium border"
            style={{
              backgroundColor: (estadoObj.color_hex || '#6b7280') + '20',
              color: estadoObj.color_hex || '#6b7280',
              borderColor: (estadoObj.color_hex || '#6b7280') + '40',
            }}
          >
            {estadoObj.nombre}
          </span>
        )
      }
      case 'antecedente':
        if (lead.es_recontacto) {
          return (
            <div className="flex flex-col gap-0.5">
              <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium bg-amber-50 text-amber-700 border border-amber-200 w-fit">
                Ya fue lead
              </span>
              {lead.intentos_contacto > 0 && (
                <span className="text-[11px] text-gray-400">
                  {lead.intentos_contacto} intento{lead.intentos_contacto !== 1 ? 's' : ''}
                  {lead.ultimo_asesor_contacto ? ` · ${lead.ultimo_asesor_contacto.split(' ')[0]}` : ''}
                </span>
              )}
            </div>
          )
        }
        if (lead.intentos_contacto > 0) {
          return (
            <div className="flex flex-col gap-0.5">
              <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium bg-blue-50 text-blue-700 border border-blue-200 w-fit">
                Ya contactado
              </span>
              <span className="text-[11px] text-gray-400">
                {lead.intentos_contacto} intento{lead.intentos_contacto !== 1 ? 's' : ''}
                {lead.ultimo_asesor_contacto ? ` · ${lead.ultimo_asesor_contacto.split(' ')[0]}` : ''}
              </span>
            </div>
          )
        }
        return (
          <span className="inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium bg-green-50 text-green-600 border border-green-200">
            Nuevo
          </span>
        )
      case 'creacion':
        return (
          <div className="text-xs whitespace-nowrap">
            <div className={lead.cola_estancada ? 'text-amber-700 font-medium' : 'text-gray-400'}>
              {formatDateTime(lead.fecha_ingreso)}
            </div>
            {lead.cola_estancada && (
              <div className="text-[10px] text-amber-600 uppercase tracking-wide mt-0.5">
                ⚠ +24h en cola
              </div>
            )}
          </div>
        )
      default:
        return <span className="text-gray-300">—</span>
    }
  }

  return (
    <DataTable
      headers={headers}
      rows={leads}
      renderCell={renderCell}
      isLoading={isLoading}
      onRowClick={(lead) => onToggle(lead.id)}
      rowClassName={(lead) => selected.has(lead.id) ? 'bg-indigo-50 hover:bg-indigo-100/60' : ''}
      // Scroll vertical confinado + thead sticky + scrollbar horizontal
      // siempre accesible. Patron Leads: ~320px arriba del viewport.
      maxHeight="calc(100vh - 360px)"
      // Drag & drop de columnas persistido por usuario.
      columnOrderKey="asig_columns_order"
      controlledOrder={controlledOrder && controlledOrder.length > 0 ? controlledOrder : null}
      onColumnOrderChange={onColumnOrderChange}
      emptyTitle={hasActiveFilters ? 'Sin resultados' : 'Sin leads para asignar'}
      emptyDescription={hasActiveFilters
        ? 'Prueba ajustando o quitando filtros.'
        : 'Cuando lleguen leads sin asignar aparecerán acá.'}
      emptyIcon={Filter}
      emptyAction={hasActiveFilters && onClearFilters ? (
        <button
          onClick={onClearFilters}
          className="text-xs text-indigo-600 hover:text-indigo-700 font-medium underline-offset-2 hover:underline"
        >
          Limpiar filtros
        </button>
      ) : null}
    />
  )
}

// ─── Resumen de equipos compacto ─────────────────────────────────────────────
function EquiposPanel({ supervisorGroups, sessionAsesorMap, filterSupervisor, onFilter }) {
  if (supervisorGroups.length === 0) return null
  return (
    <div className="bg-white border border-gray-100 rounded-xl p-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide flex items-center gap-1.5">
          <Users size={13} /> Equipos
        </p>
        <div className="flex gap-1 flex-wrap">
          <button onClick={() => onFilter('todos')}
            className={`px-2.5 py-1 rounded-full text-xs border transition-colors ${filterSupervisor === 'todos' ? 'bg-slate-800 text-white border-slate-800' : 'text-gray-500 border-gray-200 hover:border-gray-400'}`}>
            Todos
          </button>
          {supervisorGroups.map(g => (
            <button key={g.supervisor_id}
              onClick={() => onFilter(filterSupervisor === g.supervisor_id ? 'todos' : g.supervisor_id)}
              className={`px-2.5 py-1 rounded-full text-xs border transition-colors ${filterSupervisor === g.supervisor_id ? 'bg-[var(--brand-primary)] text-white border-[var(--brand-primary)]' : 'text-gray-500 border-gray-200 hover:border-gray-400'}`}>
              {g.supervisor_nombre.split(' ')[0]} ({g.asesores.length})
            </button>
          ))}
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5">
        {supervisorGroups
          .filter(g => filterSupervisor === 'todos' || g.supervisor_id === filterSupervisor)
          .flatMap(g => g.asesores)
          .map(a => {
            const c = sessionAsesorMap[a.id] || 0
            return (
              <div key={a.id} className="flex items-center gap-1 bg-gray-50 border border-gray-200 rounded-full px-2.5 py-1">
                <div className="w-5 h-5 bg-indigo-100 rounded-full flex items-center justify-center text-indigo-600 text-[10px] font-bold shrink-0">
                  {(a.nombre_completo || 'A')[0].toUpperCase()}
                </div>
                <span className="text-xs text-gray-700">{a.nombre_completo.split(' ')[0]}</span>
                {c > 0 && <span className="text-[10px] font-bold bg-green-100 text-green-700 px-1 rounded-full">+{c}</span>}
              </div>
            )
          })}
      </div>
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Componente principal
// ─────────────────────────────────────────────────────────────────────────────

export default function Asignacion() {
  const { user } = useAuthStore()
  const role = user?.role || 'asesor'
  const { fuentes, loadCatalogs: loadCrmCatalogs } = useCrmStore()

  // Protección anti-copy-paste + context menu en toda la página (política de
  // seguridad de datos — abril 2026). Los inputs de búsqueda quedan exentos.
  useCopyProtection(true, 'asignacion')

  // Catálogos (cargados una vez)
  const [supervisorGroups, setSupervisorGroups] = useState([])
  const [sinEquipo, setSinEquipo] = useState([])
  const [estados, setEstados] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)

  // Leads paginados
  const [leadsNuevos, setLeadsNuevos] = useState([])
  const [totalSinAsignar, setTotalSinAsignar] = useState(0)
  const [page, setPage] = useState(1)
  const [isLeadsLoading, setIsLeadsLoading] = useState(false)

  // Conteo por estado
  const [estadoCounts, setEstadoCounts] = useState([])
  const [filterEstadoId, setFilterEstadoId] = useState(null)

  // Nuevos leads detectados en background
  const [newLeadsCount, setNewLeadsCount] = useState(0)
  const knownTotalRef = useRef(null)

  // Sesión
  const [selected, setSelected] = useState(new Set())
  const [sessionCount, setSessionCount] = useState(0)
  const [sessionAsesorMap, setSessionAsesorMap] = useState({})
  const [filterSupervisor, setFilterSupervisor] = useState('todos')
  const [isAssigning, setIsAssigning] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  // V070.80 — confirmacion antes de eliminar bulk (mismo patron que Leads.jsx,
  // antes era confirm() nativo del browser que no respeta el diseno + se
  // saltea el flujo standard de CRMs profesionales).
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false)
  const canDelete = hasPermission(user, 'asignacion.manage') || role === 'admin' || role === 'supervisor'

  // Filtros extra (fuente, campana)
  const [filterFuenteId, setFilterFuenteId] = useState('')
  const [filterCampana, setFilterCampana] = useState('')
  const [campanas, setCampanas] = useState([])

  // Columnas visibles
  const [visibleCols, setVisibleCols] = useState(loadAsigCols)
  const [showColMenu, setShowColMenu] = useState(false)
  const colMenuRef = useRef(null)
  const toggleCol = (key) => {
    setVisibleCols(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key); else next.add(key)
      localStorage.setItem(ASIG_STORAGE_KEY, JSON.stringify([...next]))
      return next
    })
  }
  useEffect(() => {
    if (!showColMenu) return
    const handler = (e) => { if (colMenuRef.current && !colMenuRef.current.contains(e.target)) setShowColMenu(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [showColMenu])

  // Búsqueda con debounce
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const searchRef = useRef(null)

  // Cualquier filtro/búsqueda activo — diferencia el empty state
  // "todo asignado" del "sin resultados para filtros aplicados".
  const hasActiveFilters = !!(search || filterFuenteId || filterCampana || filterEstadoId)

  // V063 — Saved views para Asignacion. Mismo patron que Leads:
  // snapshot del estado actual + applyView restaura los 4 ejes.
  const [columnsOrder, setColumnsOrder] = useState(() => {
    try {
      const raw = localStorage.getItem('asig_columns_order')
      if (raw) return JSON.parse(raw)
    } catch { /* ignore */ }
    return []
  })
  const currentViewState = useMemo(() => ({
    filters: {
      search: search || '',
      filterFuenteId: filterFuenteId || '',
      filterCampana: filterCampana || '',
      filterEstadoId: filterEstadoId || null,
      filterSupervisor: filterSupervisor || 'todos',
    },
    sort: [],  // Asignacion no tiene sort multi-campo por ahora
    columns_order: columnsOrder,
    visible_columns: [...visibleCols].sort(),
  }), [search, filterFuenteId, filterCampana, filterEstadoId, filterSupervisor, columnsOrder, visibleCols])

  const {
    views, activeView, activeViewId, setActiveViewId, isDirty, isMutating,
    createView, updateView, saveCurrentToActive, deleteView, setDefault, duplicateView,
  } = useSavedViews({ scope: 'asignacion', currentState: currentViewState })

  const [viewModal, setViewModal] = useState(null)
  const [confirmDeleteView, setConfirmDeleteView] = useState(null)

  const applyView = useCallback((view) => {
    if (!view) {
      setSearchInput('')
      setSearch('')
      setFilterFuenteId('')
      setFilterCampana('')
      setFilterEstadoId(null)
      setFilterSupervisor('todos')
      setVisibleCols(new Set(ASIG_COLUMNS.map(c => c.key)))
      setColumnsOrder([])
      try { localStorage.setItem(ASIG_STORAGE_KEY, JSON.stringify(ASIG_COLUMNS.map(c => c.key))) } catch { /* ignore */ }
      setActiveViewId(null)
      setPage(1)
      return
    }
    const f = view.filters || {}
    setSearchInput(f.search || '')
    setSearch(f.search || '')
    setFilterFuenteId(f.filterFuenteId || '')
    setFilterCampana(f.filterCampana || '')
    setFilterEstadoId(f.filterEstadoId || null)
    setFilterSupervisor(f.filterSupervisor || 'todos')
    if (Array.isArray(view.visible_columns) && view.visible_columns.length > 0) {
      const vc = new Set(view.visible_columns)
      setVisibleCols(vc)
      try { localStorage.setItem(ASIG_STORAGE_KEY, JSON.stringify([...vc])) } catch { /* ignore */ }
    }
    setColumnsOrder(Array.isArray(view.columns_order) ? view.columns_order : [])
    setActiveViewId(view.id)
    setPage(1)
  }, [setActiveViewId])

  // Auto-aplicar default al cargar (solo si no hay vista forzada via URL).
  const [defaultApplied, setDefaultApplied] = useState(false)
  useEffect(() => {
    if (defaultApplied || views.length === 0) return
    const def = views.find(v => v.is_default)
    if (def) applyView(def)
    setDefaultApplied(true)
  }, [views, defaultApplied, applyView])

  // ── Cargar catálogos (usuarios, equipos, estados) ─────────────────────────
  const loadCatalogs = useCallback(async () => {
    setIsLoading(true); setError(null)
    try {
      const [usersRes, equiposRes, estadosRes] = await Promise.all([
        api.get('/auth/users'),
        api.get('/api/equipos'),
        api.get('/api/estados'),
      ])

      setEstados(estadosRes.data || [])

      // Estructura unificada (compartida con Leads y LeadDetalle).
      const asignacionScope = user?.permissions?.['asignacion.scope'] || (role === 'admin' ? 'global' : 'equipo')
      const allowedUserIds = user?.permissions?.['asignacion.allowed_users'] || []
      const { groups, sinEquipo: noSup } = buildTeamGroups({
        users: usersRes.data || [],
        equipos: equiposRes.data || [],
        role,
        currentUserId: user?.user_id,
        asignacionScope,
        allowedUserIds,
      })
      setSupervisorGroups(groups)
      setSinEquipo(noSup)
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al cargar datos.')
    } finally { setIsLoading(false) }
  }, [])

  // ── Cargar conteo por estado (sin asesor) ─────────────────────────────────
  const fetchEstadoCounts = useCallback(async () => {
    try {
      const res = await api.get('/api/dashboard/leads-por-estado?sin_asesor=true')
      setEstadoCounts(res.data || [])
    } catch { /* silencioso */ }
  }, [])

  // ── Cargar leads de la página actual ─────────────────────────────────────
  const fetchLeads = useCallback(async () => {
    setIsLeadsLoading(true)
    try {
      const params = new URLSearchParams({
        sin_asesor: 'true',
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      })
      if (search) params.set('search', search)
      if (filterEstadoId) params.set('estado_id', filterEstadoId)
      if (filterFuenteId) params.set('fuente_id', filterFuenteId)
      if (filterCampana) params.set('campana', filterCampana)
      const res = await api.get(`/api/leads?${params}`)
      const items = (res.data.items || []).filter(l => !l.asesor_id)
      setLeadsNuevos(items)
      setTotalSinAsignar(res.data.total || 0)
    } catch {
      /* error cargando leads: se maneja silenciosamente, ya hay estados de error globales */
    }
    finally { setIsLeadsLoading(false) }
  }, [page, search, filterEstadoId, filterFuenteId, filterCampana])

  useEffect(() => { loadCatalogs(); fetchEstadoCounts() }, [loadCatalogs, fetchEstadoCounts])
  useEffect(() => { fetchLeads() }, [fetchLeads])

  // Catálogos para filtros (fuentes + campañas)
  useEffect(() => {
    loadCrmCatalogs()
    api.get('/api/leads/campanas').then(r => setCampanas(r.data || [])).catch(() => { })
  }, [])

  // Reset página al cambiar filtros extra
  useEffect(() => { setPage(1); setSelected(new Set()) }, [filterFuenteId, filterCampana])

  // V067.1 — Baseline para detectar leads nuevos:
  // Antes setteabamos knownTotalRef = totalSinAsignar (filtrado por vista,
  // fuente, campana, etc.), pero el polling siguiente solo usaba `search` y
  // `filterEstadoId`. Cuando habia vista/fuente/campana activos, baseline y
  // polling quedaban desalineados -> el banner mostraba un numero falso
  // tipo "464 nuevos leads sin asignar".
  //
  // Fix: baseline + polling ambos hacen el MISMO fetch minimo
  // (sin_asesor=true sin otros filtros). Asi el banner refleja siempre
  // "X leads sin asesor nuevos globalmente, click para refrescar" — que
  // es lo que el admin de Asignacion necesita.
  useEffect(() => {
    let active = true
    api.get('/api/leads?sin_asesor=true&limit=1&offset=0')
      .then(res => {
        if (active && knownTotalRef.current === null) {
          knownTotalRef.current = res.data.total || 0
        }
      })
      .catch(() => { })
    return () => { active = false }
  }, [])

  // Polling cada 30s — mismo fetch que la baseline (sin filtros adicionales).
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const res = await api.get('/api/leads?sin_asesor=true&limit=1&offset=0')
        const serverTotal = res.data.total || 0
        if (knownTotalRef.current !== null && serverTotal > knownTotalRef.current) {
          setNewLeadsCount(serverTotal - knownTotalRef.current)
        }
      } catch { /* silencioso */ }
    }, 30000)
    return () => clearInterval(interval)
  }, [])

  const handleRefreshNewLeads = async () => {
    setNewLeadsCount(0)
    fetchLeads()
    // V067.1: resincronizar baseline para que el proximo polling no vuelva
    // a mostrar el banner con los mismos leads.
    try {
      const res = await api.get('/api/leads?sin_asesor=true&limit=1&offset=0')
      knownTotalRef.current = res.data.total || 0
    } catch { /* silent */ }
  }

  // Debounce de búsqueda
  useEffect(() => {
    const t = setTimeout(() => { setSearch(searchInput.trim()); setPage(1) }, 400)
    return () => clearTimeout(t)
  }, [searchInput])

  // Atajo "/" para búsqueda
  useEffect(() => {
    const handler = (e) => {
      if (e.key === '/' && !['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName)) {
        e.preventDefault(); searchRef.current?.focus()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const activeGroups = filterSupervisor === 'todos'
    ? supervisorGroups
    : supervisorGroups.filter(g => g.supervisor_id === filterSupervisor)
  const totalPages = Math.ceil(totalSinAsignar / PAGE_SIZE)

  const toggle = (id) => setSelected(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  const toggleAll = () => setSelected(selected.size === leadsNuevos.length ? new Set() : new Set(leadsNuevos.map(l => l.id)))

  const handleBulkAssign = async (toAsesorId) => {
    if (selected.size === 0 || !toAsesorId) return
    setIsAssigning(true)
    let ok = 0
    try {
      const res = await api.patch('/api/leads/bulk/asesor', {
        ids: [...selected],
        asesor_id: toAsesorId,
      })
      ok = res.data?.changed ?? 0
    } catch (err) {
      alert(err.response?.data?.detail || 'Error al asignar los leads.')
    }
    setSessionCount(c => c + ok)
    setSessionAsesorMap(prev => ({ ...prev, [toAsesorId]: (prev[toAsesorId] || 0) + ok }))
    setTotalSinAsignar(prev => Math.max(0, prev - ok))
    setSelected(new Set())
    setIsAssigning(false)
    // V070.79 — notificar a otros componentes (Sidebar badge) que la
    // asignacion cambio, para que refresquen su contador en <500ms.
    fireAssignmentChanged()
    // Si la página actual queda vacía y no es la 1, retroceder
    const remaining = leadsNuevos.length - ok
    fetchEstadoCounts()
    if (remaining <= 0 && page > 1) setPage(p => p - 1)
    else fetchLeads()
  }

  // V070.80 — accion destructiva: abre modal de confirmacion en vez de
  // ejecutar directo. El delete real ocurre en handleBulkDeleteConfirm.
  const handleBulkDeleteRequest = () => {
    if (selected.size === 0) return
    setConfirmBulkDelete(true)
  }

  const handleBulkDeleteConfirm = async () => {
    setConfirmBulkDelete(false)
    if (selected.size === 0) return
    setIsDeleting(true)
    const deletedCount = selected.size
    try {
      await api.delete('/api/leads/bulk', { data: { ids: [...selected] } })
      setTotalSinAsignar(prev => Math.max(0, prev - deletedCount))
      setSelected(new Set())
      // V070.79 — el contador del sidebar refresca en <500ms via evento.
      fireAssignmentChanged()
      fetchEstadoCounts()
      fetchLeads()
    } catch (err) {
      alert(err.response?.data?.detail || 'Error al eliminar los leads.')
    } finally {
      setIsDeleting(false)
    }
  }

  const handleRefresh = () => {
    setSelected(new Set())
    setSearchInput('')
    setSearch('')
    setPage(1)
    setFilterEstadoId(null)
    setFilterFuenteId('')
    setFilterCampana('')
    loadCatalogs()
    fetchEstadoCounts()
  }

  // Solo el rol admin puede acceder a la página de Asignación.
  const canAccessAssignment = role === 'admin'
  if (!canAccessAssignment) return (
    <div className="flex flex-col items-center justify-center py-20 gap-3">
      <AlertCircle size={36} className="text-gray-300" />
      <p className="text-gray-500 text-sm">No tienes permisos para acceder a esta sección. Solo administradores pueden ingresar.</p>
    </div>
  )

  return (
    <div className="space-y-4">
      {/* Encabezado */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Asignación de Leads</h1>
          <div className="flex items-center gap-2 mt-0.5 flex-wrap">
            <p className="text-sm text-gray-400">Asigna leads sin asesor entre los asesores del equipo.</p>
            {!isLoading && (
              <>
                <span className="text-gray-300 text-sm">·</span>
                <span className="text-sm font-semibold text-orange-600">
                  {totalSinAsignar.toLocaleString()} sin asignar
                </span>
                {sessionCount > 0 && (
                  <>
                    <span className="text-gray-300 text-sm">·</span>
                    <span className="text-sm font-semibold text-green-600 flex items-center gap-1">
                      <Check size={13} />{sessionCount} asignados hoy
                    </span>
                  </>
                )}
              </>
            )}
          </div>
        </div>
        <div className="flex gap-2 shrink-0">
          <Button variant="outline" size="sm" onClick={handleRefresh} disabled={isLoading} className="gap-1.5">
            <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} /> Actualizar
          </Button>
        </div>
      </div>

      {isLoading && <LoadingSpinner />}
      {!isLoading && error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">{error}</div>
      )}

      {!isLoading && !error && (
        <>
          {/* Panel de equipos */}
          <EquiposPanel
            supervisorGroups={supervisorGroups}
            sessionAsesorMap={sessionAsesorMap}
            filterSupervisor={filterSupervisor}
            onFilter={setFilterSupervisor}
          />

          {/* Tabs por estado */}
          {estadoCounts.length > 0 && (
            <div className="flex flex-wrap gap-1.5">
              <button
                onClick={() => { setFilterEstadoId(null); setPage(1); setSelected(new Set()) }}
                className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border transition-colors ${!filterEstadoId
                    ? 'bg-slate-800 text-white border-slate-800'
                    : 'text-gray-600 border-gray-200 hover:border-gray-400 bg-white'
                  }`}
              >
                Todos
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${!filterEstadoId ? 'bg-white/20 text-white' : 'bg-gray-100 text-gray-500'
                  }`}>
                  {estadoCounts.reduce((sum, e) => sum + (e.count || 0), 0)}
                </span>
              </button>
              {estadoCounts.filter(e => e.count > 0).map(e => (
                <button
                  key={e.estado_id}
                  onClick={() => { setFilterEstadoId(filterEstadoId === e.estado_id ? null : e.estado_id); setPage(1); setSelected(new Set()) }}
                  className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full text-xs font-medium border transition-colors ${filterEstadoId === e.estado_id
                      ? 'text-white border-transparent'
                      : 'bg-white border-gray-200 hover:border-gray-400'
                    }`}
                  style={filterEstadoId === e.estado_id
                    ? { backgroundColor: e.color_hex || '#6b7280', borderColor: e.color_hex || '#6b7280' }
                    : { color: e.color_hex || '#6b7280' }
                  }
                >
                  {e.estado}
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${filterEstadoId === e.estado_id ? 'bg-white/20' : 'bg-gray-100'
                    }`}>
                    {e.count}
                  </span>
                </button>
              ))}
            </div>
          )}

          {/* Banner de nuevos leads (V067.1 — discreto, sin pulse) */}
          {newLeadsCount > 0 && (
            <button
              onClick={handleRefreshNewLeads}
              className="w-full flex items-center justify-center gap-2 py-1.5 px-3 bg-indigo-50 hover:bg-indigo-100 border border-indigo-200 rounded-md text-xs font-medium text-indigo-700 transition-colors"
            >
              {newLeadsCount > 500
                ? 'Hay leads nuevos sin asignar — actualizar'
                : `${newLeadsCount} lead${newLeadsCount !== 1 ? 's' : ''} nuevo${newLeadsCount !== 1 ? 's' : ''} sin asignar — actualizar`}
            </button>
          )}

          {/* Empty state cuando NO hay leads — y NO hay filtros activos.
              Si hay filtros, dejamos pasar para mostrar la barra y el mensaje
              contextual "Sin resultados para los filtros aplicados". Esto
              evita que el usuario quede sin forma de limpiar el filtro. */}
          {totalSinAsignar === 0 && !isLeadsLoading && !hasActiveFilters ? (
            <div className="bg-green-50 border border-green-200 rounded-xl px-4 py-12 text-center">
              <Check size={32} className="text-green-400 mx-auto mb-2" />
              <p className="text-sm font-medium text-gray-700">
                {sessionCount > 0 ? `¡Listo! ${sessionCount} leads asignados en esta sesión.` : 'Todos los leads están asignados.'}
              </p>
            </div>
          ) : (
            <>
              {/* V063: barra de vistas guardadas */}
              <ViewsBar
                views={views}
                activeViewId={activeViewId}
                isDirty={isDirty}
                isMutating={isMutating}
                onSelect={(id) => applyView(id ? views.find(v => v.id === id) : null)}
                onCreate={() => setViewModal({ mode: 'create', initial: null })}
                onSaveChanges={() => saveCurrentToActive()}
                onDiscardChanges={() => activeView && applyView(activeView)}
                onRename={(v) => setViewModal({ mode: 'rename', initial: v })}
                onDuplicate={async (v) => {
                  const copy = await duplicateView({
                    ...v,
                    filters: currentViewState.filters,
                    sort: currentViewState.sort,
                    columns_order: currentViewState.columns_order,
                    visible_columns: currentViewState.visible_columns,
                  })
                  if (copy) setActiveViewId(copy.id)
                }}
                onSetDefault={(v) => setDefault(v.id)}
                onDelete={(v) => setConfirmDeleteView(v)}
              />

              {/* Barra de búsqueda + filtros + columnas */}
              <div className="flex items-center gap-2 flex-wrap">
                <div className="relative flex-1 min-w-[200px] max-w-sm">
                  <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
                  <input
                    ref={searchRef}
                    type="text"
                    name="asignacion-search"
                    autoComplete="off"
                    placeholder="Buscar nombre o teléfono… (/)"
                    value={searchInput == null || searchInput === 'null' ? '' : searchInput}
                    onChange={e => {
                      const v = e.target.value
                      setSearchInput(v === 'null' ? '' : v)
                    }}
                    className="w-full pl-8 pr-8 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                  {searchInput && (
                    <button onClick={() => { setSearchInput(''); setSearch(''); setPage(1) }}
                      className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                      <X size={13} />
                    </button>
                  )}
                </div>
                <FilterBuilder
                  fields={[
                    {
                      v: 'fuente_id', label: 'Fuente', type: 'select', icon: Globe,
                      options: (fuentes || []).map(f => ({ value: String(f.id), label: f.nombre })),
                      placeholder: 'Todas'
                    },
                    {
                      v: 'campana', label: 'Campaña', type: 'select', icon: Megaphone,
                      options: campanas.map(c => ({ value: c, label: c })),
                      placeholder: 'Todas', searchable: true
                    },
                  ]}
                  values={{ fuente_id: filterFuenteId, campana: filterCampana }}
                  onChange={(d) => {
                    setFilterFuenteId(d.fuente_id || '')
                    setFilterCampana(d.campana || '')
                  }}
                />
                <div ref={colMenuRef} className="relative shrink-0">
                  <Button variant="outline" size="sm" onClick={() => setShowColMenu(v => !v)} className="gap-1.5">
                    <List size={14} />
                    Campos
                  </Button>
                  {showColMenu && (
                    <div className="absolute right-0 z-30 mt-1 bg-white border border-gray-200 rounded-xl shadow-xl py-2 w-48">
                      {ASIG_COLUMNS.map(c => (
                        <label key={c.key} className="flex items-center gap-2 px-3 py-1.5 hover:bg-gray-50 cursor-pointer text-sm text-gray-700">
                          <input type="checkbox" checked={visibleCols.has(c.key)} onChange={() => toggleCol(c.key)}
                            className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500" />
                          {c.label}
                        </label>
                      ))}
                    </div>
                  )}
                </div>
                {/* V067: paginacion estilo correo profesional SIEMPRE visible cuando
                    hay leads. Flechas deshabilitadas si no aplica. */}
                {totalSinAsignar > 0 && (
                  <div className="inline-flex items-center gap-2 shrink-0 ml-auto whitespace-nowrap">
                    <span className="text-sm text-gray-500 select-none leading-none">
                      {((page - 1) * PAGE_SIZE + 1).toLocaleString()}–{Math.min(page * PAGE_SIZE, totalSinAsignar).toLocaleString()} de {totalSinAsignar.toLocaleString()}
                    </span>
                    <div className="inline-flex items-center gap-1 shrink-0">
                      <button
                        onClick={() => { setPage(p => p - 1); setSelected(new Set()) }}
                        disabled={page <= 1 || isLeadsLoading}
                        className="w-8 h-8 inline-flex items-center justify-center rounded-full border border-gray-200 text-gray-500 hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                      >
                        <ChevronLeft size={16} />
                      </button>
                      <button
                        onClick={() => { setPage(p => p + 1); setSelected(new Set()) }}
                        disabled={page >= totalPages || isLeadsLoading}
                        className="w-8 h-8 inline-flex items-center justify-center rounded-full border border-gray-200 text-gray-500 hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
                      >
                        <ChevronRight size={16} />
                      </button>
                    </div>
                  </div>
                )}
              </div>


              {/* Tabla */}
              <LeadsTable
                leads={leadsNuevos}
                selected={selected}
                onToggle={toggle}
                onToggleAll={toggleAll}
                estados={estados}
                isLoading={isLeadsLoading}
                visibleCols={visibleCols}
                hasActiveFilters={hasActiveFilters}
                onClearFilters={() => {
                  setSearchInput('')
                  setSearch('')
                  setFilterFuenteId('')
                  setFilterCampana('')
                  setFilterEstadoId('')
                  setPage(1)
                }}
                controlledOrder={activeView ? (activeView.columns_order || null) : (columnsOrder.length > 0 ? columnsOrder : null)}
                onColumnOrderChange={(next) => setColumnsOrder(next)}
              />


              {/* BulkBar */}
              <BulkBar
                count={selected.size}
                supervisorGroups={activeGroups}
                sinEquipo={sinEquipo}
                onAssign={handleBulkAssign}
                onDelete={handleBulkDeleteRequest}
                onClear={() => setSelected(new Set())}
                isAssigning={isAssigning}
                isDeleting={isDeleting}
                canDelete={canDelete}
              />
            </>
          )}
        </>
      )}

      {/* V063: modales de vistas guardadas */}
      {viewModal && (
        <SaveViewModal
          mode={viewModal.mode}
          initial={viewModal.initial}
          onClose={() => setViewModal(null)}
          onSave={async (payload) => {
            if (viewModal.mode === 'rename' && viewModal.initial) {
              await updateView(viewModal.initial.id, payload)
            } else {
              await createView(payload)
            }
            setViewModal(null)
          }}
        />
      )}
      {/* V070.80 — Confirmacion bulk delete (mismo patron que Leads.jsx) */}
      <ConfirmDialog
        open={confirmBulkDelete}
        variant="danger"
        title="Eliminar leads seleccionados"
        confirmLabel="Sí, eliminar"
        cancelLabel="Cancelar"
        message={`¿Estás seguro de eliminar ${selected.size} lead${selected.size !== 1 ? 's' : ''}? Esta acción no se puede deshacer.`}
        onConfirm={handleBulkDeleteConfirm}
        onCancel={() => setConfirmBulkDelete(false)}
      />

      <ConfirmDialog
        open={!!confirmDeleteView}
        variant="danger"
        title="Eliminar vista"
        confirmLabel="Sí, eliminar"
        cancelLabel="Cancelar"
        message={confirmDeleteView
          ? `Vas a eliminar la vista "${confirmDeleteView.name}". Esta acción no se puede deshacer — los filtros y configuración guardada se perderán.\n\nLos leads NO se ven afectados.`
          : ''}
        onConfirm={async () => {
          if (!confirmDeleteView) { setConfirmDeleteView(null); return }
          // V067.1: si era la vista activa, limpiar filtros/sort/cols
          const wasActive = activeViewId === confirmDeleteView.id
          const target = confirmDeleteView
          setConfirmDeleteView(null)
          await deleteView(target.id)
          if (wasActive) applyView(null)
        }}
        onCancel={() => setConfirmDeleteView(null)}
      />
    </div>
  )
}
