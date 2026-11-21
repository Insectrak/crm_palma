import { useEffect, useState, useCallback, useMemo, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Search, X, ChevronLeft, ChevronRight, Archive,
  Phone, Mail, List, Download, Plus, Upload, UserCheck, UserX,
  Building2, Radio, Tag, User, Calendar, CheckSquare, Square,
  AlertCircle, CheckCircle2, FileSpreadsheet, RefreshCw,
  Save, AlertTriangle, Info, DownloadCloud, XCircle, FileDown,
  Trash2, ExternalLink, Eye, Clock, CalendarDays, History
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import DataTable from '@/components/shared/DataTable'
import ConfirmDialog from '@/components/shared/ConfirmDialog'
import ModalDetalleCarga from '@/components/admin/ModalDetalleCarga'
import ModalDuplicadosAsignacion from '@/components/admin/ModalDuplicadosAsignacion'
import ViewsBar from '@/components/shared/views/ViewsBar'
import SaveViewModal from '@/components/shared/views/SaveViewModal'
import useSavedViews from '@/hooks/useSavedViews'
import useCopyProtection from '@/hooks/useCopyProtection'
import useCrmStore from '@/store/crmStore'
import api from '@/lib/api'
import FilterBuilder from '@/components/ui/FilterBuilder'
import { normalizePhonePE } from '@/lib/phone'

const PAGE_SIZE = 50

const HIST_COLUMNS = [
  { key: 'contacto', label: 'Contacto' },
  { key: 'proyecto', label: 'Proyecto / Campaña' },
  { key: 'canal', label: 'Canal / Fuente' },
  { key: 'estado', label: 'Estado del Lead' },
  { key: 'asesor', label: 'Asesor' },
  { key: 'crm_status', label: 'Pipeline / Leads' },
  { key: 'fecha_creacion', label: 'Creación' },
  { key: 'fecha_asignacion', label: 'Asignación' },
  { key: 'ultimo_contacto', label: 'Último Contacto' },
  { key: 'ciudad', label: 'Ciudad' },
  { key: 'observaciones', label: 'Observaciones' },
]

const HIST_STORAGE_KEY = 'hist_visible_cols_v5'

function loadHistCols() {
  try {
    const raw = localStorage.getItem(HIST_STORAGE_KEY)
    if (raw) return new Set(JSON.parse(raw))
  } catch { /* ignore */ }
  return new Set(HIST_COLUMNS.map(c => c.key))
}

function formatDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso + 'T00:00:00')
  return d.toLocaleDateString('es-PE', { day: '2-digit', month: 'short', year: 'numeric' })
}

function formatApiError(err, fallback = 'Error inesperado.') {
  const detail = err?.response?.data?.detail
  if (detail == null) return err?.message || fallback
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail
      .map(d => {
        if (typeof d === 'string') return d
        const msg = d?.msg || d?.message || JSON.stringify(d)
        const loc = Array.isArray(d?.loc) ? d.loc.filter(x => x !== 'body').join('.') : ''
        return loc ? `${msg} (${loc})` : msg
      })
      .join(' · ')
  }
  if (typeof detail === 'object') {
    return detail.msg || detail.message || JSON.stringify(detail)
  }
  return String(detail)
}

export default function Historicos() {
  useCopyProtection(true, 'historicos')
  const navigate = useNavigate()

  const { estados, fuentes, loadCatalogs } = useCrmStore()

  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)

  // Meses y desglose
  const [meses, setMeses] = useState([])
  const [selectedMes, setSelectedMes] = useState('todos')

  // Búsqueda y filtros
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const searchRef = useRef(null)

  const [filtros, setFiltros] = useState(null)
  const [filterProyecto, setFilterProyecto] = useState('')
  const [filterCanal, setFilterCanal] = useState('')
  const [filterEstado, setFilterEstado] = useState('')
  const [filterAsesor, setFilterAsesor] = useState('')

  // Catálogo de asesores para asignación
  const [asesores, setAsesores] = useState([])
  const [campanas, setCampanas] = useState([])
  const [stats, setStats] = useState(null)
  const [isExporting, setIsExporting] = useState(false)

  // Selección múltiple para reasignación y borrado
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [bulkAsesorId, setBulkAsesorId] = useState('')
  const [isReassigning, setIsReassigning] = useState(false)
  const [actionSuccessMsg, setActionSuccessMsg] = useState('')

  // Pestaña activa (V105: sin_asignar | asignados | duplicados)
  const [activeTab, setActiveTab] = useState('sin_asignar')

  // Modales
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showUploadModal, setShowUploadModal] = useState(false)
  const [singleReassignTarget, setSingleReassignTarget] = useState(null)
  const [duplicatesModal, setDuplicatesModal] = useState({
    open: false,
    duplicates: [],
    promotedCount: 0,
    asesorNombre: '',
  })

  // Historial de cargas masivas
  const [historialCargas, setHistorialCargas] = useState([])
  const [isLoadingHistorial, setIsLoadingHistorial] = useState(false)
  const [deleteHistorialTarget, setDeleteHistorialTarget] = useState(null)
  const [isDeletingHistorial, setIsDeletingHistorial] = useState(false)
  const [modalDetalles, setModalDetalles] = useState({
    open: false,
    historialId: null,
    initialTab: 'duplicates',
    cargaPreview: null,
  })

  const handleOpenDetalles = (carga, tab) => {
    setModalDetalles({
      open: true,
      historialId: carga.id,
      initialTab: tab,
      cargaPreview: carga,
    })
  }

  // Diálogos de confirmación para borrado y desasignación
  const [deleteSingleTarget, setDeleteSingleTarget] = useState(null)
  const [showDeleteBulkConfirm, setShowDeleteBulkConfirm] = useState(false)
  const [isDeleting, setIsDeleting] = useState(false)
  const [unassignTarget, setUnassignTarget] = useState(null)
  const [showUnassignBulkConfirm, setShowUnassignBulkConfirm] = useState(false)
  const [isUnassigning, setIsUnassigning] = useState(false)

  // Columnas visibles y reordenables
  const [visibleCols, setVisibleCols] = useState(loadHistCols)
  const [showColMenu, setShowColMenu] = useState(false)
  const colMenuRef = useRef(null)

  const toggleCol = (key) => {
    setVisibleCols(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key); else next.add(key)
      localStorage.setItem(HIST_STORAGE_KEY, JSON.stringify([...next]))
      return next
    })
  }

  useEffect(() => {
    if (!showColMenu) return
    const handler = (e) => { if (colMenuRef.current && !colMenuRef.current.contains(e.target)) setShowColMenu(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [showColMenu])

  const show = (key) => visibleCols.has(key)

  // Saved views
  const [columnsOrder, setColumnsOrder] = useState(() => {
    try {
      const raw = localStorage.getItem('hist_columns_order_v5')
      if (raw) return JSON.parse(raw)
    } catch { /* ignore */ }
    return []
  })

  const currentViewState = useMemo(() => ({
    filters: {
      search: search || '',
      selectedMes: selectedMes || 'todos',
      filterProyecto: filterProyecto || '',
      filterCanal: filterCanal || '',
      filterEstado: filterEstado || '',
      filterAsesor: filterAsesor || '',
    },
    sort: [],
    columns_order: columnsOrder,
    visible_columns: [...visibleCols].sort(),
  }), [search, selectedMes, filterProyecto, filterCanal, filterEstado, filterAsesor, columnsOrder, visibleCols])

  const {
    views, activeView, activeViewId, setActiveViewId, isDirty, isMutating,
    createView, updateView, saveCurrentToActive, deleteView, setDefault, duplicateView,
  } = useSavedViews({ scope: 'historicos', currentState: currentViewState })

  const [viewModal, setViewModal] = useState(null)
  const [confirmDeleteView, setConfirmDeleteView] = useState(null)

  const applyView = useCallback((view) => {
    if (!view) {
      setSearchInput('')
      setSearch('')
      setSelectedMes('todos')
      setFilterProyecto('')
      setFilterCanal('')
      setFilterEstado('')
      setFilterAsesor('')
      setVisibleCols(new Set(HIST_COLUMNS.map(c => c.key)))
      setColumnsOrder([])
      try { localStorage.setItem(HIST_STORAGE_KEY, JSON.stringify(HIST_COLUMNS.map(c => c.key))) } catch { /* ignore */ }
      setActiveViewId(null)
      setPage(1)
      return
    }
    const f = view.filters || {}
    setSearchInput(f.search || '')
    setSearch(f.search || '')
    setSelectedMes(f.selectedMes || 'todos')
    setFilterProyecto(f.filterProyecto || '')
    setFilterCanal(f.filterCanal || '')
    setFilterEstado(f.filterEstado || '')
    setFilterAsesor(f.filterAsesor || '')
    if (Array.isArray(view.visible_columns) && view.visible_columns.length > 0) {
      const vc = new Set(view.visible_columns)
      setVisibleCols(vc)
      try { localStorage.setItem(HIST_STORAGE_KEY, JSON.stringify([...vc])) } catch { /* ignore */ }
    }
    setColumnsOrder(Array.isArray(view.columns_order) ? view.columns_order : [])
    setActiveViewId(view.id)
    setPage(1)
  }, [setActiveViewId])

  // Cargar catálogos
  useEffect(() => {
    loadCatalogs()
    api.get('/api/campanas?activos=true')
      .then(res => setCampanas(res.data || []))
      .catch(() => { })
  }, [loadCatalogs])

  const fetchHistorialCargas = useCallback(async () => {
    setIsLoadingHistorial(true)
    try {
      const res = await api.get('/api/historicos/cargas-historial')
      setHistorialCargas(res.data.items || [])
    } catch {
      // ignore
    } finally {
      setIsLoadingHistorial(false)
    }
  }, [])

  const fetchAuxData = useCallback(() => {
    api.get('/api/historicos/meses')
      .then(res => setMeses(res.data.meses || []))
      .catch(() => { })
    api.get('/api/historicos/filtros')
      .then(res => setFiltros(res.data))
      .catch(() => { })
    api.get('/api/historicos/stats')
      .then(res => setStats(res.data))
      .catch(() => { })
    api.get('/auth/users')
      .then(res => {
        const list = (res.data || [])
          .filter(u => u.is_active !== false && (u.role === 'asesor' || u.role === 'supervisor' || u.role === 'admin'))
          .map(u => ({
            ...u,
            nombre_completo: [u.first_name, u.last_name].filter(Boolean).join(' ') || u.email,
          }))
        setAsesores(list)
      })
      .catch(() => { })
    fetchHistorialCargas()
  }, [fetchHistorialCargas])

  const handleConfirmDeleteHistorial = async () => {
    if (!deleteHistorialTarget) return
    setIsDeletingHistorial(true)
    try {
      await api.delete(`/api/historicos/cargas-historial/${deleteHistorialTarget.id}`)
      setDeleteHistorialTarget(null)
      fetchHistorialCargas()
    } catch (err) {
      alert(formatApiError(err, 'Error al eliminar registro del historial'))
    } finally {
      setIsDeletingHistorial(false)
    }
  }

  useEffect(() => { fetchAuxData() }, [fetchAuxData])

  // Cargar registros paginados
  const fetchData = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams({
        tab: activeTab,
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
      })
      if (search) params.set('search', search)
      if (selectedMes && selectedMes !== 'todos') params.set('mes', selectedMes)
      if (filterProyecto) params.set('proyecto', filterProyecto)
      if (filterCanal) params.set('canal', filterCanal)
      if (filterEstado) params.set('estado', filterEstado)
      if (filterAsesor) params.set('asesor_id', filterAsesor)

      const res = await api.get(`/api/historicos?${params}`)
      setItems(res.data.items || [])
      setTotal(res.data.total || 0)
    } catch (err) {
      setError(formatApiError(err, 'Error al cargar leads históricos'))
    } finally {
      setIsLoading(false)
    }
  }, [activeTab, page, search, selectedMes, filterProyecto, filterCanal, filterEstado, filterAsesor])

  useEffect(() => { fetchData() }, [fetchData])

  // Debounce búsqueda
  useEffect(() => {
    const t = setTimeout(() => { setSearch(searchInput.trim()); setPage(1) }, 350)
    return () => clearTimeout(t)
  }, [searchInput])

  // Atajo "/"
  useEffect(() => {
    const handler = (e) => {
      if (e.key === '/' && !['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName)) {
        e.preventDefault(); searchRef.current?.focus()
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  const totalPages = Math.ceil(total / PAGE_SIZE)
  const hasActiveFilters = filterProyecto || filterCanal || filterEstado || filterAsesor || (selectedMes && selectedMes !== 'todos')

  const clearFilters = () => {
    setSelectedMes('todos')
    setFilterProyecto('')
    setFilterCanal('')
    setFilterEstado('')
    setFilterAsesor('')
    setSearchInput('')
    setSearch('')
    setPage(1)
  }

  // Exportar a Excel
  const handleExport = async () => {
    setIsExporting(true)
    try {
      const params = new URLSearchParams()
      if (search) params.set('search', search)
      if (selectedMes && selectedMes !== 'todos') params.set('mes', selectedMes)
      if (filterProyecto) params.set('proyecto', filterProyecto)
      if (filterCanal) params.set('canal', filterCanal)
      if (filterEstado) params.set('estado', filterEstado)
      if (filterAsesor) params.set('asesor_id', filterAsesor)

      const res = await api.get(`/api/historicos/exportar?${params.toString()}`, {
        responseType: 'blob',
      })
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `historicos_${new Date().toISOString().slice(0, 10)}.xlsx`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      alert(formatApiError(err, 'Error al exportar histórico.'))
    } finally {
      setIsExporting(false)
    }
  }

  // Reasignación masiva y promoción a /leads con chequeo de duplicados
  const handleBulkReassign = async () => {
    if (selectedIds.size === 0 || !bulkAsesorId) return
    setIsReassigning(true)
    try {
      const res = await api.post('/api/historicos/reasignar', {
        lead_ids: Array.from(selectedIds),
        asesor_id: bulkAsesorId,
      })
      if (res.data?.duplicates && res.data.duplicates.length > 0) {
        setDuplicatesModal({
          open: true,
          duplicates: res.data.duplicates,
          promotedCount: res.data.promoted || 0,
          asesorNombre: res.data.asesor_nombre || '',
        })
      } else {
        setActionSuccessMsg(res.data.message || 'Leads reasignados correctamente')
        setTimeout(() => setActionSuccessMsg(''), 5000)
      }
      setSelectedIds(new Set())
      setBulkAsesorId('')
      fetchData()
      fetchAuxData()
    } catch (err) {
      alert(formatApiError(err, 'Error al reasignar leads históricos'))
    } finally {
      setIsReassigning(false)
    }
  }

  // Reasignación individual con chequeo de duplicados
  const handleSingleReassign = async (leadId, asesorId) => {
    try {
      const res = await api.post('/api/historicos/reasignar', {
        lead_ids: [leadId],
        asesor_id: asesorId,
      })
      setSingleReassignTarget(null)
      if (res.data?.duplicates && res.data.duplicates.length > 0) {
        setDuplicatesModal({
          open: true,
          duplicates: res.data.duplicates,
          promotedCount: res.data.promoted || 0,
          asesorNombre: res.data.asesor_nombre || '',
        })
      } else {
        setActionSuccessMsg(res.data.message || 'Lead reasignado correctamente')
        setTimeout(() => setActionSuccessMsg(''), 5000)
      }
      fetchData()
      fetchAuxData()
    } catch (err) {
      alert(formatApiError(err, 'Error al reasignar lead'))
    }
  }

  // Quitar asignación individual
  const handleConfirmUnassignSingle = async () => {
    if (!unassignTarget) return
    setIsUnassigning(true)
    try {
      const res = await api.post('/api/historicos/reasignar', {
        lead_ids: [unassignTarget.id],
        asesor_id: 'unassign',
      })
      setActionSuccessMsg(res.data.message || 'Asignación removida. El lead queda esperando reasignación.')
      setTimeout(() => setActionSuccessMsg(''), 5000)
      setUnassignTarget(null)
      fetchData()
      fetchAuxData()
    } catch (err) {
      alert(formatApiError(err, 'Error al quitar la asignación del lead'))
    } finally {
      setIsUnassigning(false)
    }
  }

  // Quitar asignación masiva
  const handleConfirmUnassignBulk = async () => {
    if (selectedIds.size === 0) return
    setIsUnassigning(true)
    try {
      const res = await api.post('/api/historicos/reasignar', {
        lead_ids: Array.from(selectedIds),
        asesor_id: 'unassign',
      })
      setActionSuccessMsg(res.data.message || 'Asignaciones removidas. Los leads seleccionados quedan esperando reasignación.')
      setTimeout(() => setActionSuccessMsg(''), 5000)
      setShowUnassignBulkConfirm(false)
      setSelectedIds(new Set())
      setBulkAsesorId('')
      fetchData()
      fetchAuxData()
    } catch (err) {
      alert(formatApiError(err, 'Error al quitar las asignaciones en lote'))
    } finally {
      setIsUnassigning(false)
    }
  }

  // Eliminación individual
  const handleConfirmDeleteSingle = async () => {
    if (!deleteSingleTarget) return
    setIsDeleting(true)
    try {
      await api.delete(`/api/historicos/${deleteSingleTarget.id}`)
      setActionSuccessMsg('Lead histórico eliminado exitosamente.')
      setTimeout(() => setActionSuccessMsg(''), 4000)
      setDeleteSingleTarget(null)
      setSelectedIds(prev => {
        const next = new Set(prev)
        next.delete(deleteSingleTarget.id)
        return next
      })
      fetchData()
      fetchAuxData()
    } catch (err) {
      alert(formatApiError(err, 'Error al eliminar el lead histórico.'))
    } finally {
      setIsDeleting(false)
    }
  }

  // Eliminación masiva
  const handleConfirmDeleteBulk = async () => {
    if (selectedIds.size === 0) return
    setIsDeleting(true)
    try {
      const res = await api.delete('/api/historicos', {
        data: { lead_ids: Array.from(selectedIds) },
      })
      setActionSuccessMsg(res.data.message || 'Leads históricos eliminados.')
      setTimeout(() => setActionSuccessMsg(''), 4000)
      setShowDeleteBulkConfirm(false)
      setSelectedIds(new Set())
      fetchData()
      fetchAuxData()
    } catch (err) {
      alert(formatApiError(err, 'Error al eliminar los leads históricos seleccionados.'))
    } finally {
      setIsDeleting(false)
    }
  }

  // Checkbox global
  const allPageSelected = items.length > 0 && items.every(it => selectedIds.has(it.id))
  const toggleSelectAll = () => {
    if (allPageSelected) {
      setSelectedIds(prev => {
        const next = new Set(prev)
        items.forEach(it => next.delete(it.id))
        return next
      })
    } else {
      setSelectedIds(prev => {
        const next = new Set(prev)
        items.forEach(it => next.add(it.id))
        return next
      })
    }
  }

  const toggleSelectOne = (id) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id); else next.add(id)
      return next
    })
  }

  return (
    <div className="space-y-4 pb-16">
      {/* Encabezado */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-white p-5 rounded-2xl border border-slate-200/80 shadow-sm">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="w-10 h-10 rounded-xl bg-indigo-50 border border-indigo-100 flex items-center justify-center text-indigo-600 shadow-sm">
              <Archive size={20} />
            </div>
            <div>
              <h1 className="text-xl font-bold text-slate-900 flex items-center gap-2">
                Histórico de Leads
                <Badge variant="outline" className="text-[11px] font-semibold text-indigo-700 bg-indigo-50 border-indigo-200">
                  Solo Admin
                </Badge>
              </h1>
              <p className="text-xs text-slate-500 mt-0.5">
                Carga aislada de leads de fechas pasadas (hasta 5,000 filas), control de duplicados y reasignación directa al pipeline activo de Leads.
              </p>
            </div>
          </div>
        </div>

        {/* Acciones principales */}
        <div className="flex items-center gap-2 flex-wrap">
          <Button
            size="sm"
            onClick={() => setShowCreateModal(true)}
            className="bg-indigo-600 hover:bg-indigo-700 text-white gap-1.5 shadow-sm font-medium"
          >
            <Plus size={15} />
            Nuevo Lead
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowUploadModal(true)}
            className="gap-1.5 border-slate-200 hover:bg-slate-50 text-slate-700 font-medium"
          >
            <Upload size={15} className="text-indigo-600" />
            Carga Masiva (hasta 5,000)
          </Button>

          <Button
            variant="outline"
            size="sm"
            onClick={handleExport}
            disabled={isExporting || total === 0}
            className="gap-1.5 border-slate-200 hover:bg-slate-50 text-slate-700 font-medium"
            title="Exportar registros filtrados a Excel"
          >
            <Download size={14} />
            {isExporting ? 'Exportando…' : 'Excel'}
          </Button>
        </div>
      </div>

      {/* V105 — 3 Pestañas Principales: Sin Asignar, Asignados, Duplicados */}
      <div className="bg-white p-2 rounded-2xl border border-slate-200/80 shadow-sm flex items-center gap-2 overflow-x-auto">
        <button
          type="button"
          onClick={() => {
            setActiveTab('sin_asignar')
            setPage(1)
            setSelectedIds(new Set())
          }}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-semibold transition-all shrink-0 cursor-pointer ${
            activeTab === 'sin_asignar'
              ? 'bg-indigo-600 text-white shadow-md'
              : 'bg-slate-50 hover:bg-slate-100 text-slate-700 dark:bg-slate-800/40 dark:hover:bg-slate-800'
          }`}
        >
          <Clock size={15} />
          <span>Sin Asignar</span>
          <span className={`px-2 py-0.5 rounded-full text-[11px] font-bold ${
            activeTab === 'sin_asignar' ? 'bg-indigo-700/80 text-white' : 'bg-slate-200 text-slate-700'
          }`}>
            {(stats?.sin_asignar ?? 0).toLocaleString()}
          </span>
        </button>

        <button
          type="button"
          onClick={() => {
            setActiveTab('asignados')
            setPage(1)
            setSelectedIds(new Set())
          }}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-semibold transition-all shrink-0 cursor-pointer ${
            activeTab === 'asignados'
              ? 'bg-emerald-600 text-white shadow-md'
              : 'bg-slate-50 hover:bg-slate-100 text-slate-700 dark:bg-slate-800/40 dark:hover:bg-slate-800'
          }`}
        >
          <UserCheck size={15} />
          <span>Asignados (en Leads)</span>
          <span className={`px-2 py-0.5 rounded-full text-[11px] font-bold ${
            activeTab === 'asignados' ? 'bg-emerald-700/80 text-white' : 'bg-slate-200 text-slate-700'
          }`}>
            {(stats?.asignados ?? 0).toLocaleString()}
          </span>
        </button>

        <button
          type="button"
          onClick={() => {
            setActiveTab('duplicados')
            setPage(1)
            setSelectedIds(new Set())
          }}
          className={`flex items-center gap-2 px-4 py-2.5 rounded-xl text-xs font-semibold transition-all shrink-0 cursor-pointer ${
            activeTab === 'duplicados'
              ? 'bg-amber-600 text-white shadow-md'
              : 'bg-slate-50 hover:bg-slate-100 text-slate-700 dark:bg-slate-800/40 dark:hover:bg-slate-800'
          }`}
        >
          <AlertTriangle size={15} />
          <span>Duplicados Detectados</span>
          <span className={`px-2 py-0.5 rounded-full text-[11px] font-bold ${
            activeTab === 'duplicados' ? 'bg-amber-700/80 text-white' : 'bg-amber-100 text-amber-800'
          }`}>
            {(stats?.duplicados ?? 0).toLocaleString()}
          </span>
        </button>
      </div>

      {/* Stats rápidas */}
      {stats && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="bg-white border border-slate-200/80 rounded-xl px-4 py-3 shadow-sm">
            <p className="text-xs text-slate-400 font-medium flex items-center gap-1.5">
              <Archive size={13} className="text-indigo-500" /> Total histórico
            </p>
            <p className="text-xl font-bold text-slate-900 mt-1">{(stats.total || 0).toLocaleString()}</p>
          </div>
          <div className="bg-white border border-slate-200/80 rounded-xl px-4 py-3 shadow-sm">
            <p className="text-xs text-slate-400 font-medium flex items-center gap-1.5">
              <Phone size={13} className="text-emerald-500" /> Teléfonos únicos
            </p>
            <p className="text-xl font-bold text-slate-900 mt-1">{(stats.telefonos_unicos || 0).toLocaleString()}</p>
          </div>
          <div className="bg-white border border-slate-200/80 rounded-xl px-4 py-3 shadow-sm">
            <p className="text-xs text-slate-400 font-medium flex items-center gap-1.5">
              <Building2 size={13} className="text-blue-500" /> Proyectos
            </p>
            <p className="text-xl font-bold text-slate-900 mt-1">{stats.proyectos || 0}</p>
          </div>
          <div className="bg-white border border-slate-200/80 rounded-xl px-4 py-3 shadow-sm">
            <p className="text-xs text-slate-400 font-medium flex items-center gap-1.5">
              <UserCheck size={13} className="text-amber-500" /> Leads asignados CRM
            </p>
            <p className="text-xl font-bold text-slate-900 mt-1">{(stats.asignados_crm || 0).toLocaleString()}</p>
          </div>
        </div>
      )}

      {/* Desglose por Meses (Pills) */}
      <div className="bg-white p-3.5 rounded-xl border border-slate-200/80 shadow-sm space-y-2">
        <div className="flex items-center justify-between text-xs font-semibold text-slate-600 px-1">
          <span className="flex items-center gap-1.5">
            <Calendar size={14} className="text-indigo-600" />
            Desglose por Meses (Fecha de Creación / Ingreso)
          </span>
          <span className="text-slate-400 font-normal">
            Filtra rápidamente por mes de ingreso de datos
          </span>
        </div>

        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 scrollbar-thin">
          <button
            onClick={() => { setSelectedMes('todos'); setPage(1) }}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium shrink-0 transition-all flex items-center gap-1.5 ${selectedMes === 'todos'
              ? 'bg-indigo-600 text-white shadow-sm font-semibold'
              : 'bg-slate-100 hover:bg-slate-200 text-slate-700'
              }`}
          >
            <span>Todos los meses</span>
            <span className={`px-1.5 py-0.2 rounded-full text-[10px] ${selectedMes === 'todos' ? 'bg-indigo-700/80 text-white' : 'bg-slate-200 text-slate-600'}`}>
              {(stats?.total || 0).toLocaleString()}
            </span>
          </button>

          {meses.map((m) => (
            <button
              key={m.mes}
              onClick={() => { setSelectedMes(m.mes); setPage(1) }}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium shrink-0 transition-all flex items-center gap-1.5 ${selectedMes === m.mes
                ? 'bg-indigo-600 text-white shadow-sm font-semibold'
                : 'bg-slate-100 hover:bg-slate-200 text-slate-700'
                }`}
            >
              <span>{m.label}</span>
              <span className={`px-1.5 py-0.2 rounded-full text-[10px] ${selectedMes === m.mes ? 'bg-indigo-700/80 text-white' : 'bg-slate-200 text-slate-600'}`}>
                {m.count.toLocaleString()}
              </span>
            </button>
          ))}
        </div>
      </div>

      {/* Toast de éxito */}
      {actionSuccessMsg && (
        <div className="flex items-center gap-2 bg-emerald-50 border border-emerald-200 text-emerald-800 text-sm px-4 py-3 rounded-xl shadow-sm animate-in fade-in">
          <CheckCircle2 size={16} className="text-emerald-600 shrink-0" />
          <span>{actionSuccessMsg}</span>
        </div>
      )}

      {/* Vistas Guardadas */}
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

      {/* Barra de búsqueda y filtros */}
      <div className="flex items-center gap-2.5 flex-wrap bg-white p-3 rounded-xl border border-slate-200/80 shadow-sm">
        <div className="relative flex-1 min-w-[220px] max-w-md">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            ref={searchRef}
            type="text"
            placeholder="Buscar por nombre, teléfono, DNI, asesor o email… (/)"
            value={searchInput}
            onChange={e => setSearchInput(e.target.value)}
            className="w-full pl-8 pr-8 py-1.5 text-xs bg-slate-50 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:bg-white transition-all"
          />
          {searchInput && (
            <button onClick={() => { setSearchInput(''); setSearch(''); setPage(1) }}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600">
              <X size={13} />
            </button>
          )}
        </div>

        {filtros && (
          <FilterBuilder
            fields={[
              {
                v: 'proyecto', label: 'Proyecto', type: 'select', icon: Building2,
                options: (filtros.proyectos || []).map(p => ({ value: p, label: p })),
                placeholder: 'Todos los proyectos', searchable: true
              },
              {
                v: 'canal', label: 'Canal', type: 'select', icon: Radio,
                options: (filtros.canales || []).map(c => ({ value: c, label: c })),
                placeholder: 'Todos los canales'
              },
              {
                v: 'estado', label: 'Estado', type: 'select', icon: Tag,
                options: (filtros.estados || []).map(e => ({ value: e, label: e })),
                placeholder: 'Todos los estados', searchable: true
              },
              {
                v: 'asesor', label: 'Asesor', type: 'select', icon: User,
                options: [
                  { value: 'sin_asesor', label: 'Sin Asesor' },
                  { value: 'asesor_no_registrado', label: '⚠️ Asesor No Registrado (Reasignar)' },
                  ...asesores.map(a => ({ value: a.id, label: `${a.nombre_completo} (${a.role})` })),
                ],
                placeholder: 'Todos los asesores', searchable: true
              },
            ]}
            values={{ proyecto: filterProyecto, canal: filterCanal, estado: filterEstado, asesor: filterAsesor }}
            onChange={(d) => {
              setFilterProyecto(d.proyecto || '')
              setFilterCanal(d.canal || '')
              setFilterEstado(d.estado || '')
              setFilterAsesor(d.asesor || '')
              setPage(1)
            }}
          />
        )}

        <div ref={colMenuRef} className="relative">
          <Button variant="outline" size="sm" onClick={() => setShowColMenu(v => !v)} className="gap-1.5 text-xs h-8">
            <List size={13} />
            Campos
          </Button>
          {showColMenu && (
            <div className="absolute right-0 z-30 mt-1 bg-white border border-slate-200 rounded-xl shadow-xl py-2 w-52 text-xs">
              <p className="px-3 py-1 font-semibold text-slate-400 uppercase text-[10px]">Columnas visibles</p>
              {HIST_COLUMNS.map(c => (
                <label key={c.key} className="flex items-center gap-2 px-3 py-1.5 hover:bg-slate-50 cursor-pointer text-slate-700">
                  <input type="checkbox" checked={visibleCols.has(c.key)} onChange={() => toggleCol(c.key)}
                    className="rounded border-slate-300 text-indigo-600 focus:ring-indigo-500" />
                  {c.label}
                </label>
              ))}
            </div>
          )}
        </div>

        {hasActiveFilters && (
          <button onClick={clearFilters} className="text-xs text-slate-500 hover:text-slate-700 flex items-center gap-1 font-medium bg-slate-100 hover:bg-slate-200 px-2.5 py-1.5 rounded-lg transition-colors">
            <X size={12} /> Limpiar filtros
          </button>
        )}

        {/* Paginación en barra */}
        {total > 0 && (
          <div className="inline-flex items-center gap-2 shrink-0 ml-auto whitespace-nowrap text-xs text-slate-500">
            <span>
              {((page - 1) * PAGE_SIZE + 1).toLocaleString()}–{Math.min(page * PAGE_SIZE, total).toLocaleString()} de {total.toLocaleString()}
            </span>
            <div className="inline-flex items-center gap-1">
              <button onClick={() => setPage(p => p - 1)} disabled={page <= 1}
                className="w-7 h-7 inline-flex items-center justify-center rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-100 disabled:opacity-30 disabled:cursor-not-allowed">
                <ChevronLeft size={14} />
              </button>
              <button onClick={() => setPage(p => p + 1)} disabled={page >= totalPages}
                className="w-7 h-7 inline-flex items-center justify-center rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-100 disabled:opacity-30 disabled:cursor-not-allowed">
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Error */}
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 rounded-xl px-4 py-3 text-sm flex items-center gap-2">
          <AlertCircle size={16} className="shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Tabla de registros */}
      {!error && (
        <HistoricosTable
          items={items}
          isLoading={isLoading}
          search={search}
          hasActiveFilters={hasActiveFilters}
          onClearFilters={clearFilters}
          show={show}
          selectedIds={selectedIds}
          onToggleSelectAll={toggleSelectAll}
          allPageSelected={allPageSelected}
          onToggleSelectOne={toggleSelectOne}
          onOpenSingleReassign={(lead) => setSingleReassignTarget(lead)}
          onUnassignSingle={(lead) => setUnassignTarget(lead)}
          onDeleteSingle={(lead) => setDeleteSingleTarget(lead)}
          onNavigateToLead={(leadCrmId) => navigate(`/leads/${leadCrmId}`)}
          controlledOrder={activeView ? (activeView.columns_order || null) : (columnsOrder.length > 0 ? columnsOrder : null)}
          onColumnOrderChange={(next) => setColumnsOrder(next)}
        />
      )}

      {/* Paginación inferior (máximo 50 registros por página) */}
      {!isLoading && totalPages > 1 && (
        <div className="flex items-center justify-between text-xs text-slate-500 bg-white px-4 py-3 rounded-xl border border-slate-200/80 shadow-sm">
          <span>Paginado fijo de 50 registros máx. (Total: {total.toLocaleString()} leads históricos)</span>
          <div className="flex items-center gap-2">
            <span>Página {page} de {totalPages}</span>
            <div className="flex gap-1">
              <button onClick={() => setPage(p => p - 1)} disabled={page <= 1}
                className="w-7 h-7 flex items-center justify-center rounded-lg border border-slate-200 hover:bg-slate-100 disabled:opacity-30 disabled:cursor-not-allowed">
                <ChevronLeft size={14} />
              </button>
              <button onClick={() => setPage(p => p + 1)} disabled={page >= totalPages}
                className="w-7 h-7 flex items-center justify-center rounded-lg border border-slate-200 hover:bg-slate-100 disabled:opacity-30 disabled:cursor-not-allowed">
                <ChevronRight size={14} />
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── Historial de cargas masivas de históricos ── */}
      <Card className="border border-slate-200/80 shadow-sm mt-6">
        <CardHeader className="pb-3 border-b border-slate-100 bg-slate-50/50">
          <div className="flex items-center justify-between">
            <CardTitle className="text-sm font-bold text-slate-800 flex items-center gap-2">
              <History size={16} className="text-indigo-600" />
              Historial de Cargas Masivas
              {historialCargas.length > 0 && (
                <Badge variant="secondary" className="text-xs bg-indigo-50 text-indigo-700 font-semibold">
                  {historialCargas.length}
                </Badge>
              )}
            </CardTitle>
            <Button
              variant="outline"
              size="sm"
              onClick={fetchHistorialCargas}
              disabled={isLoadingHistorial}
              className="text-xs h-7 gap-1 border-slate-200 text-slate-600 hover:bg-slate-100"
            >
              <RefreshCw size={12} className={isLoadingHistorial ? "animate-spin" : ""} />
              Actualizar
            </Button>
          </div>
        </CardHeader>
        <CardContent className="pt-3">
          {isLoadingHistorial ? (
            <div className="flex items-center gap-2 text-sm text-slate-500 py-6 justify-center">
              <span className="w-4 h-4 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
              Cargando historial de cargas…
            </div>
          ) : historialCargas.length === 0 ? (
            <div className="text-center py-6 text-xs text-slate-400">
              <History size={24} className="mx-auto text-slate-300 mb-1.5" />
              Aún no hay registros de cargas masivas realizadas en históricos.
            </div>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-slate-200">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-slate-50 border-b border-slate-200 text-slate-600">
                    <th className="px-3 py-2.5 text-left font-semibold">Fecha y Hora</th>
                    <th className="px-3 py-2.5 text-left font-semibold">Usuario</th>
                    <th className="px-3 py-2.5 text-left font-semibold">Archivo</th>
                    <th className="px-3 py-2.5 text-right font-semibold">Filas</th>
                    <th className="px-3 py-2.5 text-right font-semibold text-emerald-700">Importados</th>
                    <th className="px-3 py-2.5 text-right font-semibold text-amber-700">Duplicados</th>
                    <th className="px-3 py-2.5 text-right font-semibold text-indigo-700">Con Asesor CRM</th>
                    <th className="px-3 py-2.5 text-right font-semibold text-red-700">Errores</th>
                    <th className="px-3 py-2.5 w-10"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100">
                  {historialCargas.map(h => (
                    <tr key={h.id} className="hover:bg-slate-50/80 transition-colors">
                      <td className="px-3 py-2.5 text-slate-600 whitespace-nowrap font-medium">
                        {h.uploaded_at ? new Date(h.uploaded_at).toLocaleString('es-PE') : '—'}
                      </td>
                      <td className="px-3 py-2.5 text-slate-600 whitespace-nowrap">
                        {h.uploaded_by_nombre || '—'}
                      </td>
                      <td className="px-3 py-2.5 text-slate-700 max-w-[200px] truncate font-mono text-[11px]" title={h.filename}>
                        {h.filename}
                      </td>
                      <td className="px-3 py-2.5 text-right text-slate-700 font-semibold">{h.total_rows?.toLocaleString()}</td>
                      <td className="px-3 py-2.5 text-right text-emerald-700 font-bold">{h.inserted?.toLocaleString()}</td>
                      <td className="px-3 py-2.5 text-right">
                        {h.duplicates > 0 ? (
                          <button
                            type="button"
                            onClick={() => handleOpenDetalles(h, 'duplicates')}
                            className="inline-flex items-center justify-center font-bold text-amber-700 hover:text-amber-900 bg-amber-50 hover:bg-amber-100 px-2 py-0.5 rounded-md transition-colors cursor-pointer border border-amber-200/80 shadow-2xs hover:scale-105 active:scale-95"
                            title="Haga clic para ver el detalle de los leads duplicados"
                          >
                            {h.duplicates?.toLocaleString()}
                          </button>
                        ) : (
                          <span className="text-slate-400">0</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-right text-indigo-700 font-medium">{h.promoted_to_crm ? h.promoted_to_crm.toLocaleString() : '0'}</td>
                      <td className="px-3 py-2.5 text-right">
                        {h.errors > 0 ? (
                          <button
                            type="button"
                            onClick={() => handleOpenDetalles(h, 'errors')}
                            className="inline-flex items-center justify-center font-bold text-red-700 hover:text-red-900 bg-red-50 hover:bg-red-100 px-2 py-0.5 rounded-md transition-colors cursor-pointer border border-red-200/80 shadow-2xs hover:scale-105 active:scale-95"
                            title="Haga clic para ver el detalle de los errores"
                          >
                            {h.errors?.toLocaleString()}
                          </button>
                        ) : (
                          <span className="text-slate-400">0</span>
                        )}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <button
                          onClick={() => setDeleteHistorialTarget(h)}
                          className="text-slate-400 hover:text-red-600 transition-colors p-1 rounded"
                          title="Eliminar registro del historial"
                        >
                          <Trash2 size={13} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Barra flotante de Acciones en lote */}
      {selectedIds.size > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50 bg-slate-900 text-white px-5 py-3.5 rounded-2xl shadow-2xl border border-slate-700 flex items-center gap-4 animate-in slide-in-from-bottom-5">
          <div className="flex items-center gap-2">
            <Badge className="bg-indigo-500 text-white font-bold">{selectedIds.size}</Badge>
            <span className="text-xs font-medium text-slate-200">leads seleccionados</span>
          </div>

          <div className="h-4 w-px bg-slate-700" />

          {/* Reasignación */}
          <div className="flex items-center gap-2">
            <select
              value={bulkAsesorId}
              onChange={(e) => setBulkAsesorId(e.target.value)}
              className="bg-slate-800 text-xs text-white border border-slate-600 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="">Seleccionar asesor destino…</option>
              {asesores.map((a) => (
                <option key={a.id} value={a.id}>
                  {a.nombre_completo} ({a.role})
                </option>
              ))}
            </select>

            <Button
              size="sm"
              disabled={!bulkAsesorId || isReassigning}
              onClick={handleBulkReassign}
              className="bg-indigo-600 hover:bg-indigo-700 text-white text-xs gap-1.5 h-8 font-medium"
            >
              <UserCheck size={14} />
              {isReassigning ? 'Asignando a Leads…' : 'Asignar a Leads'}
            </Button>
          </div>

          <div className="h-4 w-px bg-slate-700" />

          {/* Quitar asignación en lote */}
          <Button
            size="sm"
            variant="outline"
            onClick={() => setShowUnassignBulkConfirm(true)}
            disabled={isUnassigning}
            className="text-xs gap-1.5 h-8 font-medium border-amber-500/40 text-amber-300 hover:bg-amber-500/20 hover:text-amber-200 bg-transparent"
            title="Quitar asignación y dejar esperando reasignación"
          >
            <UserX size={13} />
            Quitar Asignación ({selectedIds.size})
          </Button>

          <div className="h-4 w-px bg-slate-700" />

          {/* Eliminar en lote */}
          <Button
            size="sm"
            variant="destructive"
            onClick={() => setShowDeleteBulkConfirm(true)}
            className="text-xs gap-1.5 h-8 font-medium bg-red-600 hover:bg-red-700"
          >
            <Trash2 size={13} />
            Eliminar ({selectedIds.size})
          </Button>

          <button
            onClick={() => setSelectedIds(new Set())}
            className="text-xs text-slate-400 hover:text-white transition-colors ml-1"
          >
            Cancelar
          </button>
        </div>
      )}

      {/* Modal: Nuevo Lead */}
      {showCreateModal && (
        <ModalNuevoLeadIdentico
          estados={estados}
          fuentes={fuentes}
          asesores={asesores}
          campanas={campanas}
          onClose={() => setShowCreateModal(false)}
          onSuccess={(promotedId) => {
            setShowCreateModal(false)
            if (promotedId) {
              setActionSuccessMsg('Lead creado y agregado automáticamente a la página de Leads.')
            } else {
              setActionSuccessMsg('Lead histórico guardado exitosamente.')
            }
            setTimeout(() => setActionSuccessMsg(''), 5000)
            fetchData()
            fetchAuxData()
          }}
        />
      )}

      {/* Modal: Carga Masiva (hasta 5,000) */}
      {showUploadModal && (
        <ModalCargaMasivaIdentica
          asesores={asesores}
          onClose={() => setShowUploadModal(false)}
          onSuccess={() => {
            setShowUploadModal(false)
            fetchData()
            fetchAuxData()
          }}
        />
      )}

      {/* Modal: Reasignar Lead Individual */}
      {singleReassignTarget && (
        <ModalReasignarIndividual
          lead={singleReassignTarget}
          asesores={asesores}
          onClose={() => setSingleReassignTarget(null)}
          onConfirm={(asesorId) => handleSingleReassign(singleReassignTarget.id, asesorId)}
        />
      )}

      {/* Modal: Leads Duplicados Omitidos (V105) */}
      <ModalDuplicadosAsignacion
        open={duplicatesModal.open}
        duplicates={duplicatesModal.duplicates}
        promotedCount={duplicatesModal.promotedCount}
        asesorNombre={duplicatesModal.asesorNombre}
        onClose={() => setDuplicatesModal({ open: false, duplicates: [], promotedCount: 0, asesorNombre: '' })}
        onGoToDuplicatesTab={() => {
          setActiveTab('duplicados')
          setPage(1)
          setSelectedIds(new Set())
        }}
      />

      {/* ConfirmDialog: Quitar Asignación Lead Individual */}
      <ConfirmDialog
        open={!!unassignTarget}
        variant="warning"
        title="Quitar asignación del lead"
        confirmLabel={isUnassigning ? "Quitando…" : "Sí, quitar asignación"}
        cancelLabel="Cancelar"
        message={unassignTarget
          ? `¿Deseas quitar la asignación actual del lead "${unassignTarget.nombre || unassignTarget.telefono}"? El asesor asignado será removido y el lead quedará nuevamente esperando reasignación.`
          : ''}
        onConfirm={handleConfirmUnassignSingle}
        onCancel={() => setUnassignTarget(null)}
      />

      {/* ConfirmDialog: Quitar Asignación en Lote */}
      <ConfirmDialog
        open={showUnassignBulkConfirm}
        variant="warning"
        title="Quitar asignación en lote"
        confirmLabel={isUnassigning ? "Quitando…" : `Sí, quitar asignación (${selectedIds.size})`}
        cancelLabel="Cancelar"
        message={`¿Estás seguro de quitar la asignación a los ${selectedIds.size} leads seleccionados? Quedarán sin asesor asignado y volverán a estar esperando reasignación.`}
        onConfirm={handleConfirmUnassignBulk}
        onCancel={() => setShowUnassignBulkConfirm(false)}
      />

      {/* ConfirmDialog: Borrar Lead Individual */}
      <ConfirmDialog
        open={!!deleteSingleTarget}
        variant="danger"
        title="Eliminar lead histórico"
        confirmLabel={isDeleting ? "Eliminando…" : "Sí, eliminar"}
        cancelLabel="Cancelar"
        message={deleteSingleTarget
          ? `¿Estás seguro de eliminar el lead histórico "${deleteSingleTarget.nombre || deleteSingleTarget.telefono}"? Esta acción no se puede deshacer.`
          : ''}
        onConfirm={handleConfirmDeleteSingle}
        onCancel={() => setDeleteSingleTarget(null)}
      />

      {/* ConfirmDialog: Borrar Leads en Lote */}
      <ConfirmDialog
        open={showDeleteBulkConfirm}
        variant="danger"
        title="Eliminar leads históricos seleccionados"
        confirmLabel={isDeleting ? "Eliminando…" : `Sí, eliminar (${selectedIds.size})`}
        cancelLabel="Cancelar"
        message={`¿Estás seguro de eliminar los ${selectedIds.size} leads históricos seleccionados? Se borrarán permanentemente del repositorio histórico.`}
        onConfirm={handleConfirmDeleteBulk}
        onCancel={() => setShowDeleteBulkConfirm(false)}
      />

      {/* ConfirmDialog: Borrar Registro de Historial de Cargas */}
      <ConfirmDialog
        open={!!deleteHistorialTarget}
        variant="danger"
        title="Eliminar registro del historial de cargas"
        confirmLabel={isDeletingHistorial ? "Eliminando…" : "Sí, eliminar"}
        cancelLabel="Cancelar"
        message={deleteHistorialTarget
          ? `¿Estás seguro de eliminar el registro de la carga "${deleteHistorialTarget.filename}"? Los leads ya importados no se eliminarán, solo se borrará esta entrada del historial.`
          : ''}
        onConfirm={handleConfirmDeleteHistorial}
        onCancel={() => setDeleteHistorialTarget(null)}
      />

      {/* Modal de Detalle de Carga para Históricos */}
      <ModalDetalleCarga
        open={modalDetalles.open}
        onClose={() => setModalDetalles(prev => ({ ...prev, open: false }))}
        historialId={modalDetalles.historialId}
        endpoint="/api/historicos/cargas-historial"
        initialTab={modalDetalles.initialTab}
        cargaPreview={modalDetalles.cargaPreview}
      />

      {/* Modales de vistas guardadas */}
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

      <ConfirmDialog
        open={!!confirmDeleteView}
        variant="danger"
        title="Eliminar vista"
        confirmLabel="Sí, eliminar"
        cancelLabel="Cancelar"
        message={confirmDeleteView
          ? `Vas a eliminar la vista "${confirmDeleteView.name}". Los filtros y configuración guardada se perderán.`
          : ''}
        onConfirm={async () => {
          if (!confirmDeleteView) { setConfirmDeleteView(null); return }
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


// ── Componente de Tabla ──────────────────────────────────────────────────────

function HistoricosTable({
  items, isLoading, search, hasActiveFilters, onClearFilters,
  show, selectedIds, onToggleSelectAll, allPageSelected, onToggleSelectOne,
  onOpenSingleReassign, onUnassignSingle, onDeleteSingle, onNavigateToLead, controlledOrder, onColumnOrderChange
}) {
  const headers = [
    {
      key: '_select',
      label: (
        <button onClick={onToggleSelectAll} className="p-1 text-slate-400 hover:text-indigo-600 transition-colors">
          {allPageSelected && items.length > 0 ? (
            <CheckSquare size={16} className="text-indigo-600" />
          ) : (
            <Square size={16} />
          )}
        </button>
      ),
      className: 'w-10 text-center',
    },
    { key: 'nombre', label: 'Nombre y Documento', className: 'min-w-[170px]' },
    ...(show('contacto') ? [{ key: 'contacto', label: 'Contacto' }] : []),
    ...(show('proyecto') ? [{ key: 'proyecto', label: 'Proyecto / Campaña' }] : []),
    ...(show('canal') ? [{ key: 'canal', label: 'Canal / Fuente' }] : []),
    ...(show('estado') ? [{ key: 'estado', label: 'Estado del Lead' }] : []),
    ...(show('asesor') ? [{ key: 'asesor', label: 'Asesor' }] : []),
    ...(show('crm_status') ? [{ key: 'crm_status', label: 'Pipeline / Leads' }] : []),
    ...(show('fecha_creacion') ? [{ key: 'fecha_creacion', label: 'Creación' }] : []),
    ...(show('fecha_asignacion') ? [{ key: 'fecha_asignacion', label: 'Asignación' }] : []),
    ...(show('ultimo_contacto') ? [{ key: 'ultimo_contacto', label: 'Último Contacto' }] : []),
    ...(show('ciudad') ? [{ key: 'ciudad', label: 'Ciudad' }] : []),
    ...(show('observaciones') ? [{ key: 'observaciones', label: 'Observaciones' }] : []),
    { key: '_acciones', label: 'Acciones', className: 'w-24 text-center' },
  ]

  const renderCell = (h, key) => {
    switch (key) {
      case '_select':
        return (
          <div className="flex items-center justify-center">
            <button
              onClick={() => onToggleSelectOne(h.id)}
              className="p-1 text-slate-400 hover:text-indigo-600 transition-colors"
            >
              {selectedIds.has(h.id) ? (
                <CheckSquare size={16} className="text-indigo-600" />
              ) : (
                <Square size={16} />
              )}
            </button>
          </div>
        )
      case 'nombre':
        return (
          <div className="pii-cell">
            <p className="text-sm font-semibold text-slate-900 leading-tight">{h.nombre || 'Sin nombre'}</p>
            {h.dni && <p className="text-[11px] text-slate-400 mt-0.5">DNI: {h.dni}</p>}
          </div>
        )
      case 'contacto':
        return (
          <div className="pii-cell space-y-0.5">
            {h.telefono && (
              <p className="text-xs text-slate-700 font-medium flex items-center gap-1.5">
                <Phone size={11} className="text-slate-400" /> {h.telefono}
              </p>
            )}
            {h.email && (
              <p className="text-xs text-slate-500 flex items-center gap-1.5 truncate max-w-[180px]" title={h.email}>
                <Mail size={11} className="text-slate-400" /> {h.email}
              </p>
            )}
            {!h.telefono && !h.email && <span className="text-slate-300 text-xs">—</span>}
          </div>
        )
      case 'proyecto':
        return h.proyecto
          ? <Badge variant="secondary" className="text-xs bg-slate-100 text-slate-700 font-medium">{h.proyecto}</Badge>
          : <span className="text-slate-300 text-xs">—</span>
      case 'canal':
        return h.canal
          ? <span className="text-xs text-slate-600 capitalize bg-slate-50 px-2 py-0.5 rounded border border-slate-100">{h.canal}</span>
          : <span className="text-slate-300 text-xs">—</span>
      case 'estado':
        return h.estado
          ? <span className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium bg-slate-100 text-slate-700 border border-slate-200">{h.estado}</span>
          : <span className="text-slate-300 text-xs">—</span>
      case 'asesor':
        if (h.asesor_nombre && h.asesor_nombre !== '—') {
          if (h.asesor_id && (h.lead_crm_id && h.lead_crm_activo)) {
            return (
              <div className="flex flex-col gap-0.5">
                <span className="text-xs text-slate-800 font-medium flex items-center gap-1">
                  <User size={12} className="text-indigo-500" /> {h.asesor_nombre}
                </span>
                <span className="inline-flex items-center text-[10px] text-emerald-700 bg-emerald-50 border border-emerald-200 px-1.5 py-0.2 rounded w-fit font-medium">
                  Asignado CRM
                </span>
              </div>
            )
          } else if (h.asesor_id) {
            return (
              <div className="flex flex-col gap-0.5">
                <span className="text-xs text-slate-700 font-medium flex items-center gap-1">
                  <User size={12} className="text-slate-400" /> {h.asesor_nombre}
                </span>
                <span className="inline-flex items-center text-[10px] text-slate-600 bg-slate-100 border border-slate-200 px-1.5 py-0.2 rounded w-fit font-medium">
                  Solo en Histórico
                </span>
              </div>
            )
          } else {
            return (
              <div className="flex flex-col gap-0.5">
                <span className="text-xs text-amber-900 font-medium flex items-center gap-1">
                  <AlertTriangle size={12} className="text-amber-600 shrink-0" /> {h.asesor_nombre}
                </span>
                <span className="inline-flex items-center text-[10px] text-amber-800 bg-amber-50 border border-amber-300 px-1.5 py-0.2 rounded w-fit font-medium" title="Este asesor no existe en el CRM y se debe reasignar">
                  Esperando reasignación
                </span>
              </div>
            )
          }
        }
        return (
          <div className="flex flex-col gap-0.5">
            <span className="text-slate-400 italic text-xs">Sin asesor</span>
            <span className="inline-flex items-center text-[10px] text-slate-600 bg-slate-100 border border-slate-200 px-1.5 py-0.2 rounded w-fit font-medium">
              Esperando reasignación
            </span>
          </div>
        )
      case 'crm_status':
        if (h.es_duplicado) {
          return (
            <div className="flex flex-col gap-0.5">
              <span
                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-amber-50 text-amber-800 border border-amber-300 w-fit"
                title={h.duplicado_motivo || 'Detectado como duplicado con un lead existente en el CRM'}
              >
                <AlertTriangle size={11} className="text-amber-600" />
                <span>Duplicado</span>
              </span>
              {h.duplicado_con_lead_id && (
                <button
                  type="button"
                  onClick={() => onNavigateToLead(h.duplicado_con_lead_id)}
                  className="text-[10px] text-indigo-600 hover:underline flex items-center gap-0.5 w-fit"
                  title="Ver lead existente con el que colisiona"
                >
                  <span>Ver Lead #{h.duplicado_con_lead_id}</span>
                  <ExternalLink size={9} />
                </button>
              )}
            </div>
          )
        } else if (h.lead_crm_id && h.lead_crm_activo) {
          return (
            <button
              onClick={() => onNavigateToLead(h.lead_crm_id)}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200 hover:bg-emerald-100 transition-colors"
              title="Ver lead activo en la página de Leads"
            >
              <span>Activo en Leads</span>
              <ExternalLink size={10} />
            </button>
          )
        } else if (h.lead_crm_id && !h.lead_crm_activo) {
          return (
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-medium bg-slate-100 text-slate-500 border border-slate-200" title="El lead fue desactivado del CRM al quitar su asignación">
              Desactivado en Leads
            </span>
          )
        } else {
          return (
            <span className="text-slate-400 text-xs italic">Solo en Histórico</span>
          )
        }
      case 'fecha_creacion':
        return <span className="text-xs text-slate-600 font-medium whitespace-nowrap">{formatDate(h.fecha_creacion || h.fecha_ingreso)}</span>
      case 'fecha_asignacion':
        return <span className="text-xs text-slate-500 whitespace-nowrap">{formatDate(h.fecha_asignacion)}</span>
      case 'ultimo_contacto':
        return <span className="text-xs text-slate-500 whitespace-nowrap">{formatDate(h.fecha_ultimo_contacto)}</span>
      case 'ciudad':
        return h.ciudad
          ? <span className="text-xs text-slate-600">{h.ciudad}</span>
          : <span className="text-slate-300 text-xs">—</span>
      case 'observaciones':
        return h.observaciones
          ? <span className="text-xs text-slate-500 truncate max-w-[180px] inline-block" title={h.observaciones}>{h.observaciones}</span>
          : <span className="text-slate-300 text-xs">—</span>
      case '_acciones': {
        const isAssigned = Boolean(h.asesor_id || h.lead_crm_id || (h.asesor_nombre && h.asesor_nombre !== '—'))
        return (
          <div className="flex items-center justify-center gap-1">
            <button
              onClick={() => onOpenSingleReassign(h)}
              className="p-1.5 text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors"
              title="Asignar o reasignar a un asesor (se activa en /leads)"
            >
              <RefreshCw size={13} />
            </button>
            {isAssigned && (
              <button
                onClick={() => onUnassignSingle(h)}
                className="p-1.5 text-slate-400 hover:text-amber-600 hover:bg-amber-50 rounded-lg transition-colors"
                title="Quitar asignación y dejar esperando reasignación"
              >
                <UserX size={13} />
              </button>
            )}
            <button
              onClick={() => onDeleteSingle(h)}
              className="p-1.5 text-slate-400 hover:text-red-600 hover:bg-red-50 rounded-lg transition-colors"
              title="Eliminar del histórico"
            >
              <Trash2 size={13} />
            </button>
          </div>
        )
      }
      default:
        return <span className="text-slate-300 text-xs">—</span>
    }
  }

  return (
    <DataTable
      headers={headers}
      rows={items}
      renderCell={renderCell}
      isLoading={isLoading}
      maxHeight="calc(100vh - 380px)"
      columnOrderKey="hist_columns_order_v5"
      controlledOrder={controlledOrder && controlledOrder.length > 0 ? controlledOrder : null}
      onColumnOrderChange={onColumnOrderChange}
      emptyTitle={search || hasActiveFilters ? 'Sin resultados' : 'Sin registros históricos'}
      emptyDescription={search || hasActiveFilters
        ? 'Prueba ajustando los filtros o el mes seleccionado.'
        : 'Sube leads individuales o realiza una carga masiva en este módulo.'}
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


// ── Modal: Formulario de Nuevo Lead con Fechas Opcionales y Duplicados ───────

function ModalNuevoLeadIdentico({ estados, fuentes, asesores, campanas, onClose, onSuccess }) {
  const navigate = useNavigate()
  const [form, setForm] = useState({
    nombres: '', apellidos: '', telefono: '', email: '',
    tipo_documento: 'DNI',
    dni: '', campana: '', observaciones: '',
    ciudad: '', trabajo: '',
    fuente_id: '', estado_id: '', asesor_id: '', referido_por: '',
    codigo_convenio: '',
    fecha_creacion: new Date().toISOString().slice(0, 10),
    fecha_asignacion: '',
    fecha_ultimo_contacto: '',
  })
  const [phonePrefix, setPhonePrefix] = useState('+51')
  const [phoneLocal, setPhoneLocal] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [fieldErrors, setFieldErrors] = useState({})

  // Dedupe inline banner
  const [duplicateMatch, setDuplicateMatch] = useState(null)
  const [duplicateField, setDuplicateField] = useState(null)
  const [duplicateSource, setDuplicateSource] = useState(null)
  const [overrideActive, setOverrideActive] = useState(false)
  const [overrideReason, setOverrideReason] = useState('')
  const dupeCheckTimer = useRef(null)

  const checkDuplicate = (field, value) => {
    if (dupeCheckTimer.current) clearTimeout(dupeCheckTimer.current)
    const v = (value || '').trim()
    if (!v) {
      if (duplicateField === field) {
        setDuplicateMatch(null)
        setDuplicateField(null)
        setDuplicateSource(null)
        setOverrideActive(false)
      }
      return
    }
    dupeCheckTimer.current = setTimeout(() => {
      const params = new URLSearchParams()
      params.set(field, v)
      api.get(`/api/historicos/check-duplicate?${params.toString()}`)
        .then(res => {
          if (res.data?.match) {
            setDuplicateMatch(res.data.match)
            setDuplicateField(res.data.match_field)
            setDuplicateSource(res.data.match_source)
            setOverrideActive(false)
          } else if (duplicateField === field) {
            setDuplicateMatch(null)
            setDuplicateField(null)
            setDuplicateSource(null)
            setOverrideActive(false)
          }
        })
        .catch(() => { })
    }, 500)
  }

  useEffect(() => {
    if (estados.length > 0 && !form.estado_id) {
      setForm(p => ({ ...p, estado_id: String(estados[0].id) }))
    }
  }, [estados, form.estado_id])

  const isReferido = useMemo(() => {
    if (!form.fuente_id) return false
    const fuente = fuentes.find(x => String(x.id) === String(form.fuente_id))
    return fuente?.nombre?.toLowerCase().includes('referid') || false
  }, [form.fuente_id, fuentes])

  const isConvenio = useMemo(() => {
    if (!form.fuente_id) return false
    const fuente = fuentes.find(x => String(x.id) === String(form.fuente_id))
    return fuente?.nombre?.toLowerCase().includes('convenio') || false
  }, [form.fuente_id, fuentes])

  const validate = () => {
    const errors = {}
    if (!form.nombres.trim() && !form.apellidos.trim()) {
      errors.nombres = 'Se requiere al menos nombre o apellido.'
    }
    if (!form.telefono.trim()) {
      errors.telefono = 'El teléfono es requerido.'
    } else {
      const result = normalizePhonePE(form.telefono)
      if (!result.valid) errors.telefono = result.error || 'Número inválido.'
    }
    if (form.email.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim())) {
      errors.email = 'Formato de email inválido.'
    }
    if (form.dni.trim()) {
      const value = form.dni.trim().toUpperCase()
      if (form.tipo_documento === 'DNI' && !/^\d{8}$/.test(value)) errors.dni = 'DNI debe tener 8 dígitos.'
      else if (form.tipo_documento === 'CE' && !/^\d{9}$/.test(value)) errors.dni = 'CE debe tener 9 dígitos.'
      else if (form.tipo_documento === 'Pasaporte' && !/^[A-Z0-9]{6,12}$/.test(value)) errors.dni = 'Pasaporte inválido.'
    }
    if (!form.fuente_id) errors.fuente_id = 'La fuente es obligatoria.'
    if (isReferido && !form.referido_por.trim()) errors.referido_por = 'Campo obligatorio.'
    if (isConvenio && !form.codigo_convenio.trim()) errors.codigo_convenio = 'Campo obligatorio.'
    return errors
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    const errors = validate()
    if (Object.keys(errors).length > 0) { setFieldErrors(errors); return }
    setFieldErrors({})
    setIsSubmitting(true)
    setError(null)
    try {
      const res = await api.post('/api/historicos', {
        ...form,
        fuente_id: form.fuente_id ? parseInt(form.fuente_id) : null,
        estado_id: form.estado_id ? parseInt(form.estado_id) : undefined,
        asesor_id: form.asesor_id || null,
        referido_por: form.referido_por || null,
        codigo_convenio: form.codigo_convenio || null,
        fecha_creacion: form.fecha_creacion || null,
        fecha_asignacion: form.fecha_asignacion || null,
        fecha_ultimo_contacto: form.fecha_ultimo_contacto || null,
        allow_duplicate: overrideActive,
        duplicate_reason: overrideReason || null,
      })
      onSuccess(res.data?.promoted_to_crm_id)
    } catch (err) {
      if (err.response?.status === 409) {
        const detail = err.response.data?.detail
        if (detail?.existing_lead) {
          setDuplicateMatch(detail.existing_lead)
          setDuplicateField('telefono')
          setDuplicateSource(detail.match_source)
          setOverrideActive(false)
        } else {
          setError(formatApiError(err, 'Ya existe un lead con estos datos.'))
        }
      } else {
        setError(formatApiError(err, 'Error al crear el lead en históricos.'))
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  const f = (key) => ({ value: form[key], onChange: e => setForm(p => ({ ...p, [key]: e.target.value })) })

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/70 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-[#0f172a] text-slate-100 rounded-2xl shadow-2xl max-w-2xl w-full border border-slate-800 overflow-hidden animate-in zoom-in-95">
        <div className="px-6 py-4 border-b border-slate-800 flex items-center justify-between">
          <h2 className="text-base font-bold text-white">Datos del lead histórico</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white transition-colors">
            <X size={18} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-6 space-y-4 max-h-[82vh] overflow-y-auto">
          {/* Banner de Duplicado Detectado */}
          {duplicateMatch && (
            <div className="rounded-xl border border-amber-500/50 bg-amber-950/40 p-3.5 text-xs text-amber-200 animate-in fade-in">
              <div className="flex items-start gap-2.5">
                <AlertTriangle size={17} className="text-amber-400 shrink-0 mt-0.5" />
                <div className="flex-1 min-w-0 space-y-1">
                  <p className="font-bold text-amber-300 text-sm">
                    {duplicateSource === 'crm' ? '¡Lead existente en CRM Activo!' : '¡Lead existente en Histórico!'}
                  </p>
                  <p className="text-amber-100">
                    <span className="font-semibold">{[duplicateMatch.nombres, duplicateMatch.apellidos].filter(Boolean).join(' ') || 'Sin nombre'}</span>
                    {duplicateMatch.asesor_nombre && <> · asignado a <span className="font-semibold">{duplicateMatch.asesor_nombre}</span></>}
                    {duplicateMatch.estado_nombre && <> · estado <span className="font-semibold">{duplicateMatch.estado_nombre}</span></>}
                  </p>
                  {duplicateMatch.telefono && (
                    <p className="font-mono text-[11px] text-amber-300/80">{duplicateMatch.telefono}</p>
                  )}

                  <div className="flex items-center gap-2 pt-2 flex-wrap">
                    {duplicateSource === 'crm' && duplicateMatch.id && (
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="bg-slate-800 border-amber-500/40 text-amber-200 hover:bg-slate-700 text-xs h-7 gap-1"
                        onClick={() => navigate(`/leads/${duplicateMatch.id}`)}
                      >
                        <Eye size={12} /> Ver en Leads
                      </Button>
                    )}

                    {!overrideActive ? (
                      <button
                        type="button"
                        onClick={() => setOverrideActive(true)}
                        className="text-xs text-amber-300 hover:text-white underline underline-offset-2 font-medium"
                      >
                        Crear de todos modos
                      </button>
                    ) : (
                      <span className="text-emerald-400 font-semibold flex items-center gap-1">
                        ✓ Guardado forzado activo
                        <button type="button" onClick={() => setOverrideActive(false)} className="text-slate-400 hover:text-white ml-1.5 underline">
                          Cancelar
                        </button>
                      </span>
                    )}
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => { setDuplicateMatch(null); setOverrideActive(false) }}
                  className="text-amber-400 hover:text-white"
                >
                  <X size={15} />
                </button>
              </div>
            </div>
          )}

          {error && (
            <div className="bg-red-950/60 border border-red-800 text-red-300 text-xs px-3.5 py-2.5 rounded-xl flex items-center gap-2">
              <AlertCircle size={15} className="shrink-0 text-red-400" />
              <span>{error}</span>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3.5">
            <div>
              <Label className="text-xs text-slate-300">Nombres</Label>
              <Input
                {...f('nombres')}
                className={`mt-1 bg-slate-900/90 border-slate-700 text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 ${fieldErrors.nombres ? 'border-red-500' : ''}`}
              />
              {fieldErrors.nombres && <p className="text-xs text-red-400 mt-0.5">{fieldErrors.nombres}</p>}
            </div>
            <div>
              <Label className="text-xs text-slate-300">Apellidos</Label>
              <Input
                {...f('apellidos')}
                className="mt-1 bg-slate-900/90 border-slate-700 text-slate-100 placeholder:text-slate-500 focus:border-indigo-500"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3.5">
            <div>
              <Label className="text-xs text-slate-300">Teléfono <span className="text-red-400">*</span></Label>
              <div className="flex mt-1">
                <input
                  type="text"
                  value={phonePrefix}
                  onChange={e => {
                    let v = e.target.value.replace(/[^\d+]/g, '').slice(0, 4)
                    if (v && !v.startsWith('+')) v = '+' + v.replace(/\+/g, '')
                    setPhonePrefix(v)
                    const full = phoneLocal ? v + phoneLocal : ''
                    setForm(p => ({ ...p, telefono: full }))
                    checkDuplicate('telefono', full)
                  }}
                  className="w-16 text-center text-sm rounded-l-md border border-r-0 border-slate-700 bg-slate-800 text-slate-200 font-mono focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  title="Código de país"
                />
                <input
                  type="tel"
                  value={phoneLocal}
                  onChange={e => {
                    const maxDigits = phonePrefix === '+51' ? 9 : 11
                    const digits = e.target.value.replace(/\D/g, '').slice(0, maxDigits)
                    setPhoneLocal(digits)
                    const fullPhone = digits ? phonePrefix + digits : ''
                    setForm(p => ({ ...p, telefono: fullPhone }))
                    checkDuplicate('telefono', fullPhone)
                  }}
                  onBlur={() => checkDuplicate('telefono', form.telefono)}
                  placeholder={phonePrefix === '+51' ? '987 654 321' : 'Solo dígitos'}
                  maxLength={phonePrefix === '+51' ? 9 : 11}
                  className={`flex-1 min-w-0 border border-slate-700 bg-slate-900/90 text-slate-100 rounded-r-md px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-indigo-500 ${fieldErrors.telefono ? 'border-red-500' : ''}`}
                />
              </div>
              {fieldErrors.telefono && <p className="text-xs text-red-400 mt-0.5">{fieldErrors.telefono}</p>}
            </div>
            <div>
              <Label className="text-xs text-slate-300">Email</Label>
              <Input
                type="email"
                value={form.email}
                onChange={e => setForm(p => ({ ...p, email: e.target.value }))}
                onBlur={() => checkDuplicate('email', form.email)}
                placeholder="nombre@dominio.com"
                className={`mt-1 bg-slate-900/90 border-slate-700 text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 ${fieldErrors.email ? 'border-red-500' : ''}`}
              />
              {fieldErrors.email && <p className="text-xs text-red-400 mt-0.5">{fieldErrors.email}</p>}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3.5">
            <div>
              <Label className="text-xs text-slate-300">Documento</Label>
              <div className="flex mt-1">
                <select
                  value={form.tipo_documento}
                  onChange={e => setForm(p => ({ ...p, tipo_documento: e.target.value, dni: '' }))}
                  className="text-sm rounded-l-md border border-r-0 border-slate-700 bg-slate-800 text-slate-200 px-2 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                >
                  <option value="DNI">DNI</option>
                  <option value="CE">CE</option>
                  <option value="Pasaporte">Pasaporte</option>
                </select>
                <Input
                  value={form.dni}
                  inputMode={form.tipo_documento === 'Pasaporte' ? 'text' : 'numeric'}
                  maxLength={form.tipo_documento === 'DNI' ? 8 : form.tipo_documento === 'CE' ? 9 : 12}
                  placeholder={form.tipo_documento === 'DNI' ? '12345678' : form.tipo_documento === 'CE' ? '001234567' : 'AB123456'}
                  onChange={e => {
                    const raw = e.target.value
                    let cleaned
                    if (form.tipo_documento === 'Pasaporte') {
                      cleaned = raw.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 12)
                    } else if (form.tipo_documento === 'CE') {
                      cleaned = raw.replace(/\D/g, '').slice(0, 9)
                    } else {
                      cleaned = raw.replace(/\D/g, '').slice(0, 8)
                    }
                    setForm(p => ({ ...p, dni: cleaned }))
                  }}
                  onBlur={() => checkDuplicate('dni', form.dni)}
                  className={`flex-1 min-w-0 rounded-l-none rounded-r-md bg-slate-900/90 border-slate-700 text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 ${fieldErrors.dni ? 'border-red-500' : ''}`}
                />
              </div>
              {fieldErrors.dni && <p className="text-xs text-red-400 mt-0.5">{fieldErrors.dni}</p>}
            </div>
            <div>
              <Label className="text-xs text-slate-300">Campaña publicitaria</Label>
              {campanas.length > 0 ? (
                <select
                  value={form.campana}
                  onChange={e => setForm(p => ({ ...p, campana: e.target.value }))}
                  className="w-full mt-1 text-sm border border-slate-700 rounded-md px-2 py-1.5 bg-slate-900/90 text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                >
                  <option value="">— Sin campaña —</option>
                  {campanas.map(c => (
                    <option key={c.id} value={c.nombre}>{c.nombre}</option>
                  ))}
                </select>
              ) : (
                <Input
                  {...f('campana')}
                  placeholder="Carga campañas en Configuración → Campañas"
                  className="mt-1 bg-slate-900/90 border-slate-700 text-slate-100 placeholder:text-slate-500"
                  disabled
                />
              )}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3.5">
            <div>
              <Label className="text-xs text-slate-300">
                Fuente <span className="text-red-400">*</span>
              </Label>
              <select
                {...f('fuente_id')}
                className={`w-full mt-1 text-sm border rounded-md px-2 py-1.5 bg-slate-900/90 text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500 ${fieldErrors.fuente_id ? 'border-red-500' : 'border-slate-700'
                  }`}
              >
                <option value="">Seleccionar…</option>
                {fuentes.map(fu => (
                  <option key={fu.id} value={fu.id} className="capitalize">{fu.nombre}</option>
                ))}
              </select>
              {fieldErrors.fuente_id && (
                <p className="text-xs text-red-400 mt-0.5">{fieldErrors.fuente_id}</p>
              )}
            </div>
            <div>
              <Label className="text-xs text-slate-300">Estado del lead</Label>
              <select
                value={form.estado_id}
                onChange={e => setForm(p => ({ ...p, estado_id: e.target.value }))}
                className="w-full mt-1 text-sm border border-slate-700 rounded-md px-2 py-1.5 bg-slate-900/90 text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
              >
                {estados.map(es => <option key={es.id} value={es.id}>{es.nombre}</option>)}
              </select>
            </div>
          </div>

          {/* Fechas detalladas (Opcionales) */}
          <div className="border border-slate-800 bg-slate-900/50 rounded-xl p-3.5 space-y-3">
            <p className="text-[11px] font-semibold text-indigo-400 uppercase tracking-wider flex items-center gap-1.5">
              <CalendarDays size={13} /> Fechas del Lead (Opcionales)
            </p>
            <div className="grid grid-cols-3 gap-2.5">
              <div>
                <Label className="text-[11px] text-slate-300">Fecha Creación</Label>
                <Input
                  type="date"
                  {...f('fecha_creacion')}
                  className="mt-1 bg-slate-900 border-slate-700 text-slate-100 text-xs focus:border-indigo-500"
                />
              </div>
              <div>
                <Label className="text-[11px] text-slate-300">Fecha Asignación</Label>
                <Input
                  type="date"
                  {...f('fecha_asignacion')}
                  className="mt-1 bg-slate-900 border-slate-700 text-slate-100 text-xs focus:border-indigo-500"
                />
              </div>
              <div>
                <Label className="text-[11px] text-slate-300">Último Contacto</Label>
                <Input
                  type="date"
                  {...f('fecha_ultimo_contacto')}
                  className="mt-1 bg-slate-900 border-slate-700 text-slate-100 text-xs focus:border-indigo-500"
                />
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3.5">
            <div>
              <Label className="text-xs text-slate-300">
                Ciudad <span className="text-slate-500 font-normal">(opcional)</span>
              </Label>
              <Input
                {...f('ciudad')}
                placeholder="Ej: Arequipa"
                className="mt-1 bg-slate-900/90 border-slate-700 text-slate-100 placeholder:text-slate-500 focus:border-indigo-500"
              />
            </div>
            <div>
              <Label className="text-xs text-slate-300">
                Trabajo <span className="text-slate-500 font-normal">(opcional)</span>
              </Label>
              <Input
                {...f('trabajo')}
                placeholder="Ej: Ingeniero civil"
                className="mt-1 bg-slate-900/90 border-slate-700 text-slate-100 placeholder:text-slate-500 focus:border-indigo-500"
              />
            </div>
          </div>

          {isConvenio && (
            <div>
              <Label className="text-xs text-slate-300">
                Código de convenio <span className="text-red-400">*</span>
              </Label>
              <Input
                {...f('codigo_convenio')}
                placeholder="Ej: CONV-2026 / PNP / MINEDU"
                className={`mt-1 bg-slate-900/90 border-slate-700 text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 ${fieldErrors.codigo_convenio ? 'border-red-500' : ''}`}
              />
              {fieldErrors.codigo_convenio && (
                <p className="text-xs text-red-400 mt-0.5">{fieldErrors.codigo_convenio}</p>
              )}
            </div>
          )}

          <div>
            <Label className="text-xs text-slate-300">
              Referido por{' '}
              {isReferido
                ? <span className="text-red-400">*</span>
                : <span className="text-slate-500 font-normal">(opcional)</span>}
            </Label>
            <Input
              {...f('referido_por')}
              placeholder="Nombre de quien refirió al lead"
              className={`mt-1 bg-slate-900/90 border-slate-700 text-slate-100 placeholder:text-slate-500 focus:border-indigo-500 ${fieldErrors.referido_por ? 'border-red-500' : ''}`}
            />
            {fieldErrors.referido_por && (
              <p className="text-xs text-red-400 mt-0.5">{fieldErrors.referido_por}</p>
            )}
          </div>

          <div>
            <Label className="text-xs text-slate-300">Asignar a</Label>
            <select
              value={form.asesor_id}
              onChange={e => setForm(p => ({ ...p, asesor_id: e.target.value }))}
              className="w-full mt-1 text-sm border border-slate-700 rounded-md px-2 py-1.5 bg-slate-900/90 text-slate-100 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            >
              <option value="">Sin asignar (permanece solo en histórico)</option>
              {asesores.map(a => (
                <option key={a.id} value={a.id}>
                  {a.nombre_completo} ({a.role}) — Activa el lead en /leads
                </option>
              ))}
            </select>
            <p className="text-[10px] text-slate-400 mt-0.5">
              Al asignar un asesor registrado, el lead aparecerá automáticamente en la página activa de Leads.
            </p>
          </div>

          <div>
            <Label className="text-xs text-slate-300">Observaciones</Label>
            <textarea
              rows={3}
              {...f('observaciones')}
              className="w-full mt-1 text-xs border border-slate-700 rounded-md px-3 py-2 bg-slate-900/90 text-slate-100 placeholder:text-slate-500 focus:outline-none focus:ring-1 focus:ring-indigo-500"
            />
          </div>

          <div className="pt-3 border-t border-slate-800 flex items-center justify-end gap-2.5">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onClose}
              className="bg-transparent border-slate-700 text-slate-300 hover:bg-slate-800 hover:text-white"
            >
              Cancelar
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={isSubmitting}
              className="bg-red-600 hover:bg-red-700 text-white font-semibold gap-1.5 shadow-sm px-4"
            >
              <Save size={14} />
              {isSubmitting ? 'Creando…' : 'Crear Lead'}
            </Button>
          </div>
        </form>
      </div>
    </div>
  )
}


// ── Modal: Carga Masiva (hasta 5,000 registros y columnas extendidas) ───────

const EXPECTED_COLUMNS = [
  { key: 'nombres', label: 'Nombres', required: false },
  { key: 'apellidos', label: 'Apellidos', required: false },
  { key: 'telefono', label: 'Teléfono', required: true },
  { key: 'ciudad', label: 'Ciudad', required: false },
  { key: 'estado_lead', label: 'Estado del lead', required: false },
  { key: 'asesor', label: 'Asesor', required: false },
  { key: 'fuente', label: 'Fuente', required: true },
  { key: 'fecha_creacion', label: 'Creación (Fecha)', required: false },
  { key: 'fecha_asignacion', label: 'fecha_asign (Fecha)', required: false },
  { key: 'fecha_ultimo_contacto', label: 'fecha_ultimo (Fecha)', required: false },
  { key: 'email', label: 'Email', required: false },
  { key: 'dni', label: 'DNI / Doc', required: false },
  { key: 'campana', label: 'Campaña', required: false },
  { key: 'codigo_convenio', label: 'Código Convenio', required: false },
  { key: 'observaciones', label: 'Observaciones', required: false },
  { key: 'proyecto', label: 'Proyecto (legacy)', required: false },
  { key: 'estrategia', label: 'Estrategia (legacy)', required: false },
]

const COLUMN_ALIASES = {
  nombres: ['nombres', 'nombre', 'nombredelcliente', 'cliente', 'nombrecompleto'],
  apellidos: ['apellidos', 'apellido', 'apellidodelcliente'],
  telefono: ['telefono', 'celular', 'movil', 'numero', 'whatsapp', 'phone'],
  ciudad: ['ciudad', 'ubicacion', 'ubicaciongeografica', 'city'],
  estado_lead: ['estado_lead', 'estadolead', 'estadodellead', 'estado', 'calidad', 'status', 'clasificacion'],
  asesor: ['asesor', 'vendedor', 'responsable', 'advisor', 'agent'],
  fuente: ['fuente', 'origen', 'source', 'medio', 'canal'],
  fecha_creacion: ['creacion', 'creación', 'fechacreacion', 'fecha_creacion', 'fecha', 'fecharegistro', 'fechaingreso', 'date', 'created_at'],
  fecha_asignacion: ['fecha_asign', 'fechaasign', 'fechaasignacion', 'fecha_asignacion', 'asignacion', 'asignación', 'assigned_at', 'fechadeasignacion'],
  fecha_ultimo_contacto: ['fecha_ultimo', 'fechaultimo', 'fechaultimocontacto', 'fecha_ultimo_contacto', 'ultimocontacto', 'ultimo_contacto', 'último contacto', 'last_contact', 'contacto'],
  email: ['email', 'correo', 'correoelectronico', 'mail'],
  dni: ['dni', 'documento', 'doc'],
  campana: ['campana', 'campaña', 'campaign', 'nombrecampana', 'inmueble', 'desarrollo'],
  codigo_convenio: ['codigoconvenio', 'codigodeconvenio', 'convenio', 'codconvenio', 'codigo_convenio'],
  observaciones: ['observaciones', 'comentarios', 'comentario', 'notas', 'nota', 'observacion'],
  proyecto: ['proyecto'],
  estrategia: ['estrategia', 'strategy'],
}

const _normalizeHeader = (s) =>
  String(s || '')
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]/g, '')

function autoMapColumns(fileColumns) {
  const map = {}
  const normalizedFile = fileColumns.map(fc => ({ raw: fc, norm: _normalizeHeader(fc) }))
  for (const ec of EXPECTED_COLUMNS) {
    const aliases = COLUMN_ALIASES[ec.key] || [ec.key]
    const exact = normalizedFile.find(f => aliases.includes(f.norm))
    if (exact) { map[ec.key] = exact.raw; continue }
    const partial = normalizedFile.find(f =>
      aliases.some(a => f.norm.includes(a) || a.includes(f.norm))
    )
    if (partial) map[ec.key] = partial.raw
  }
  return map
}

function ModalCargaMasivaIdentica({ asesores, onClose, onSuccess }) {
  const [file, setFile] = useState(null)
  const [preview, setPreview] = useState(null)
  const [totalRows, setTotalRows] = useState(0)
  const [columnMap, setColumnMap] = useState({})
  const [targetAsesor, setTargetAsesor] = useState('')
  const [isParsing, setIsParsing] = useState(false)
  const [isImporting, setIsImporting] = useState(false)
  const [isDownloading, setIsDownloading] = useState(false)
  const [isDownloadingErrors, setIsDownloadingErrors] = useState(false)
  const [parseError, setParseError] = useState(null)
  const [importResult, setImportResult] = useState(null)

  // Dry-run
  const [validated, setValidated] = useState(null)
  const [isValidating, setIsValidating] = useState(false)
  const [validationError, setValidationError] = useState(null)
  const [validatedFilter, setValidatedFilter] = useState('all')

  const inputRef = useRef(null)

  const handleDownloadTemplate = async () => {
    setIsDownloading(true)
    try {
      const res = await api.get('/api/historicos/plantilla', { responseType: 'blob' })
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = 'plantilla_leads_historico.xlsx'
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      alert('No se pudo descargar la plantilla.')
    } finally {
      setIsDownloading(false)
    }
  }

  const handleFile = async (selectedFile) => {
    if (!selectedFile) return
    const validExts = /\.(xlsx|xls|csv)$/i
    if (!validExts.test(selectedFile.name)) {
      setParseError('Formato no soportado. Usa .xlsx, .xls o .csv')
      return
    }
    if (selectedFile.size > 15 * 1024 * 1024) {
      setParseError('El archivo supera el límite de 15 MB.')
      return
    }

    setFile(selectedFile)
    setParseError(null)
    setImportResult(null)
    setPreview(null)
    setColumnMap({})
    setValidated(null)
    setValidationError(null)
    setIsParsing(true)

    try {
      const formData = new FormData()
      formData.append('file', selectedFile)
      const res = await api.post('/api/historicos/preview', formData)
      const { columns, preview: rows, total_rows } = res.data
      setPreview(rows || [])
      setTotalRows(total_rows || 0)
      setColumnMap(autoMapColumns(columns || []))
    } catch (err) {
      setParseError(formatApiError(err, 'Error al procesar el archivo.'))
    } finally {
      setIsParsing(false)
    }
  }

  const runValidation = async () => {
    if (!file || !columnMap?.telefono) {
      setValidationError('Debes mapear al menos la columna "Teléfono".')
      return
    }
    setIsValidating(true)
    setValidationError(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('column_map', JSON.stringify(columnMap))
      const res = await api.post('/api/historicos/preview-validated', fd)
      setValidated(res.data)
      setValidatedFilter('all')
    } catch (err) {
      setValidationError(formatApiError(err, 'Error al analizar el archivo.'))
    } finally {
      setIsValidating(false)
    }
  }

  const handleDownloadErrors = async () => {
    if (!file || !columnMap?.telefono) return
    setIsDownloadingErrors(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('column_map', JSON.stringify(columnMap))
      const res = await api.post('/api/historicos/download-errors', fd, { responseType: 'blob' })
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = 'problemas_historicos.xlsx'
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      alert(formatApiError(err, 'Error al descargar archivo de problemas.'))
    } finally {
      setIsDownloadingErrors(false)
    }
  }

  const handleImport = async () => {
    if (!columnMap.telefono) {
      setParseError('Debes mapear la columna "Teléfono" para continuar.')
      return
    }
    setIsImporting(true)
    setParseError(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('column_map', JSON.stringify(columnMap))
      formData.append('target_asesor_id', targetAsesor || '')
      const res = await api.post('/api/historicos/carga-masiva', formData)
      setImportResult(res.data)
      setPreview(null)
      setFile(null)
    } catch (err) {
      setParseError(formatApiError(err, 'Error durante la importación.'))
    } finally {
      setIsImporting(false)
    }
  }

  const filteredValidatedRows = useMemo(() => {
    if (!validated?.rows) return []
    if (validatedFilter === 'all') return validated.rows
    return validated.rows.filter(r => r.status === validatedFilter)
  }, [validated, validatedFilter])

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/70 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-4xl w-full border border-slate-200 overflow-hidden animate-in zoom-in-95">
        <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-indigo-50 flex items-center justify-center text-indigo-600">
              <FileSpreadsheet size={16} />
            </div>
            <div>
              <h2 className="text-base font-bold text-slate-900">Carga Masiva de Leads Históricos (Hasta 5,000)</h2>
              <p className="text-xs text-slate-400">Columnas ampliadas: Creación, Asignación, Último Contacto, Estado y Asesor libre</p>
            </div>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
            <X size={18} />
          </button>
        </div>

        <div className="p-6 space-y-4 max-h-[82vh] overflow-y-auto text-xs">
          {parseError && (
            <div className="bg-red-50 border border-red-200 text-red-700 p-3 rounded-xl flex items-center gap-2">
              <AlertCircle size={15} className="shrink-0" />
              <span>{parseError}</span>
            </div>
          )}

          {/* Resultado final */}
          {importResult ? (
            <div className="space-y-4">
              <div className="bg-emerald-50 border border-emerald-200 text-emerald-800 p-4 rounded-xl space-y-2">
                <div className="flex items-center gap-2 font-bold text-sm">
                  <CheckCircle2 size={18} className="text-emerald-600" />
                  <span>Importación completada</span>
                </div>
                <p className="text-xs">{importResult.message}</p>
                {importResult.duplicates > 0 && (
                  <p className="text-xs text-amber-700">
                    {importResult.duplicates} duplicados (en CRM o Histórico) fueron omitidos.
                  </p>
                )}
                {importResult.errors > 0 && (
                  <p className="text-xs text-red-700">
                    {importResult.errors} filas con error no fueron importadas.
                  </p>
                )}
              </div>

              {importResult.error_rows && importResult.error_rows.length > 0 && (
                <div className="border border-slate-200 rounded-xl p-3 bg-slate-50 max-h-40 overflow-y-auto space-y-1">
                  <p className="font-semibold text-slate-700">Detalle de errores:</p>
                  {importResult.error_rows.map((er, i) => (
                    <p key={i} className="text-[11px] text-slate-500">
                      Fila {er.row}: {er.error}
                    </p>
                  ))}
                </div>
              )}

              <div className="flex justify-end pt-3">
                <Button onClick={onSuccess} className="bg-indigo-600 hover:bg-indigo-700 text-white text-xs">
                  Listo y Ver Histórico
                </Button>
              </div>
            </div>
          ) : (
            <>
              {/* Paso 1: Dropzone y Descarga de plantilla */}
              {!file && (
                <div className="space-y-4">
                  <div
                    onClick={() => inputRef.current?.click()}
                    className="border-2 border-dashed border-slate-300 hover:border-indigo-400 bg-slate-50 hover:bg-indigo-50/30 rounded-2xl p-8 text-center cursor-pointer transition-all"
                  >
                    <input
                      ref={inputRef}
                      type="file"
                      accept=".xlsx,.xls,.csv"
                      onChange={(e) => handleFile(e.target.files[0])}
                      className="hidden"
                    />
                    <FileSpreadsheet size={36} className="text-slate-400 mx-auto mb-2.5" />
                    <p className="text-sm font-bold text-slate-800">Arrastra tu archivo Excel o CSV aquí</p>
                    <p className="text-xs text-slate-400 mt-1">Formatos soportados: .xlsx, .xls, .csv — máx. 15 MB — hasta 5,000 filas</p>
                    <Button size="sm" variant="outline" className="mt-3 pointer-events-none text-xs">
                      <Upload size={13} className="mr-1.5" /> Seleccionar archivo
                    </Button>
                  </div>

                  <div className="bg-slate-50 border border-slate-200 rounded-xl p-3.5 flex items-center justify-between">
                    <div>
                      <p className="font-semibold text-slate-800">Descargar plantilla oficial ampliada</p>
                      <p className="text-slate-500 text-[11px]">Incluye columnas para Estado del lead, Creación, Asignación, Último contacto y Asesor.</p>
                    </div>
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={handleDownloadTemplate}
                      disabled={isDownloading}
                      className="gap-1.5 text-xs bg-white"
                    >
                      <DownloadCloud size={14} className="text-indigo-600" />
                      {isDownloading ? 'Descargando…' : 'Descargar plantilla'}
                    </Button>
                  </div>
                </div>
              )}

              {/* Paso 2: Configuración, Mapeo y Dry-Run */}
              {file && (
                <div className="space-y-4">
                  <div className="flex items-center justify-between bg-slate-50 p-3 rounded-xl border border-slate-200">
                    <div className="flex items-center gap-2.5">
                      <FileSpreadsheet size={18} className="text-indigo-600" />
                      <div>
                        <p className="font-bold text-slate-900">{file.name}</p>
                        <p className="text-[11px] text-slate-500">{totalRows} filas detectadas</p>
                      </div>
                    </div>
                    <Button variant="ghost" size="sm" onClick={() => { setFile(null); setValidated(null) }} className="text-slate-400 hover:text-slate-600 text-xs">
                      Cambiar archivo
                    </Button>
                  </div>

                  {/* Asignación predeterminada */}
                  <div>
                    <label className="block text-xs font-semibold text-slate-700 mb-1">
                      Asignar por defecto a asesor registrado (los leads permanecerán en Históricos hasta su reasignación):
                    </label>
                    <select
                      value={targetAsesor}
                      onChange={(e) => setTargetAsesor(e.target.value)}
                      className="w-full px-3 py-2 text-xs border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    >
                      <option value="">— Usar asesor de cada fila o dejar libre para reasignar —</option>
                      {asesores.map(a => (
                        <option key={a.id} value={a.id}>
                          {a.nombre_completo} ({a.role})
                        </option>
                      ))}
                    </select>
                  </div>

                  {/* Mapeo de columnas */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <p className="font-semibold text-slate-800">Mapeo de Columnas:</p>
                      <Button
                        size="sm"
                        variant="outline"
                        onClick={runValidation}
                        disabled={isValidating}
                        className="text-xs h-7 gap-1 border-indigo-200 text-indigo-700 bg-indigo-50 hover:bg-indigo-100"
                      >
                        <RefreshCw size={12} className={isValidating ? "animate-spin" : ""} />
                        {isValidating ? 'Analizando…' : 'Analizar archivo'}
                      </Button>
                    </div>

                    <div className="grid grid-cols-2 gap-2 bg-slate-50 p-3 rounded-xl border border-slate-200 max-h-56 overflow-y-auto">
                      {EXPECTED_COLUMNS.filter(c => !c.key.includes('legacy')).map(f => (
                        <div key={f.key} className="flex items-center justify-between gap-2">
                          <span className="text-slate-600 text-[11px] truncate">
                            {f.label} {f.required && <span className="text-red-500">*</span>}:
                          </span>
                          <select
                            value={columnMap[f.key] || ''}
                            onChange={(e) => setColumnMap(cm => ({ ...cm, [f.key]: e.target.value }))}
                            className="text-[11px] border border-slate-200 rounded px-2 py-1 bg-white max-w-[140px]"
                          >
                            <option value="">(Ignorar)</option>
                            {Object.keys(preview?.[0] || {}).map(c => (
                              <option key={c} value={c}>{c}</option>
                            ))}
                          </select>
                        </div>
                      ))}
                    </div>
                  </div>

                  {/* Resultados del análisis / Dry-run */}
                  {validationError && (
                    <div className="bg-red-50 border border-red-200 text-red-700 p-3 rounded-xl text-xs flex items-center gap-2">
                      <AlertCircle size={14} className="shrink-0" />
                      <span>{validationError}</span>
                    </div>
                  )}

                  {validated && (
                    <div className="space-y-2.5 bg-slate-50 p-3.5 rounded-xl border border-slate-200">
                      <div className="flex items-center justify-between">
                        <p className="font-semibold text-slate-800">Resultado del análisis previo:</p>
                        {(validated.summary.errors > 0 || validated.summary.duplicates_file > 0 || validated.summary.duplicates_crm > 0 || validated.summary.duplicates_historico > 0) && (
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={handleDownloadErrors}
                            disabled={isDownloadingErrors}
                            className="text-[11px] h-7 gap-1 border-amber-300 text-amber-800 bg-amber-50 hover:bg-amber-100"
                          >
                            <FileDown size={13} />
                            {isDownloadingErrors ? 'Generando…' : 'Descargar filas con problemas'}
                          </Button>
                        )}
                      </div>

                      <div className="grid grid-cols-5 gap-1.5 text-center">
                        <button
                          onClick={() => setValidatedFilter('valid')}
                          className={`p-1.5 rounded-lg border transition-all ${validatedFilter === 'valid' ? 'bg-emerald-100 border-emerald-300' : 'bg-white border-slate-200'}`}
                        >
                          <p className="text-[9px] text-slate-500 font-medium">Listos</p>
                          <p className="text-sm font-bold text-emerald-600">{validated.summary.valid}</p>
                        </button>
                        <button
                          onClick={() => setValidatedFilter('duplicate_file')}
                          className={`p-1.5 rounded-lg border transition-all ${validatedFilter === 'duplicate_file' ? 'bg-amber-100 border-amber-300' : 'bg-white border-slate-200'}`}
                        >
                          <p className="text-[9px] text-slate-500 font-medium">Dupl. archivo</p>
                          <p className="text-sm font-bold text-amber-600">{validated.summary.duplicates_file}</p>
                        </button>
                        <button
                          onClick={() => setValidatedFilter('duplicate_crm')}
                          className={`p-1.5 rounded-lg border transition-all ${validatedFilter === 'duplicate_crm' ? 'bg-amber-100 border-amber-300' : 'bg-white border-slate-200'}`}
                        >
                          <p className="text-[9px] text-slate-500 font-medium">Dupl. CRM</p>
                          <p className="text-sm font-bold text-amber-600">{validated.summary.duplicates_crm || 0}</p>
                        </button>
                        <button
                          onClick={() => setValidatedFilter('duplicate_historico')}
                          className={`p-1.5 rounded-lg border transition-all ${validatedFilter === 'duplicate_historico' ? 'bg-amber-100 border-amber-300' : 'bg-white border-slate-200'}`}
                        >
                          <p className="text-[9px] text-slate-500 font-medium">Dupl. Histórico</p>
                          <p className="text-sm font-bold text-amber-600">{validated.summary.duplicates_historico || 0}</p>
                        </button>
                        <button
                          onClick={() => setValidatedFilter('error')}
                          className={`p-1.5 rounded-lg border transition-all ${validatedFilter === 'error' ? 'bg-red-100 border-red-300' : 'bg-white border-slate-200'}`}
                        >
                          <p className="text-[9px] text-slate-500 font-medium">Con error</p>
                          <p className="text-sm font-bold text-red-600">{validated.summary.errors}</p>
                        </button>
                      </div>

                      {/* Vista previa de filas */}
                      <div className="max-h-40 overflow-y-auto border border-slate-200 rounded-lg bg-white">
                        <table className="w-full text-[11px] text-left">
                          <thead className="bg-slate-100 text-slate-600 sticky top-0">
                            <tr>
                              <th className="p-1.5">Fila</th>
                              <th className="p-1.5">Nombre</th>
                              <th className="p-1.5">Teléfono</th>
                              <th className="p-1.5">Estado Lead</th>
                              <th className="p-1.5">Asesor</th>
                              <th className="p-1.5">Resultado</th>
                              <th className="p-1.5">Detalle</th>
                            </tr>
                          </thead>
                          <tbody>
                            {filteredValidatedRows.slice(0, 40).map((r, i) => (
                              <tr key={i} className="border-t border-slate-100 hover:bg-slate-50">
                                <td className="p-1.5 text-slate-400 font-mono">{r.row}</td>
                                <td className="p-1.5 font-medium text-slate-800">{r.nombres} {r.apellidos || ''}</td>
                                <td className="p-1.5 text-slate-600">{r.telefono}</td>
                                <td className="p-1.5 text-slate-600">{r.estado_lead || '—'}</td>
                                <td className="p-1.5 text-slate-600">{r.asesor || '—'}</td>
                                <td className="p-1.5">
                                  {r.status === 'valid' && <Badge className="bg-emerald-100 text-emerald-700 text-[10px] font-normal">Listo</Badge>}
                                  {r.status === 'duplicate_file' && <Badge className="bg-amber-100 text-amber-700 text-[10px] font-normal">Duplicado archivo</Badge>}
                                  {r.status === 'duplicate_crm' && <Badge className="bg-amber-100 text-amber-700 text-[10px] font-normal">Duplicado CRM</Badge>}
                                  {r.status === 'duplicate_historico' && <Badge className="bg-amber-100 text-amber-700 text-[10px] font-normal">Duplicado Histórico</Badge>}
                                  {r.status === 'error' && <Badge className="bg-red-100 text-red-700 text-[10px] font-normal">Error</Badge>}
                                </td>
                                <td className="p-1.5 text-slate-500 text-[10px]">
                                  {(r.errors || []).join('; ') || '—'}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>
                    </div>
                  )}

                  <div className="pt-3 border-t border-slate-100 flex items-center justify-end gap-2">
                    <Button variant="outline" size="sm" onClick={onClose}>Cancelar</Button>
                    <Button
                      size="sm"
                      disabled={isImporting || isParsing}
                      onClick={handleImport}
                      className="bg-indigo-600 hover:bg-indigo-700 text-white font-medium gap-1.5"
                    >
                      <Upload size={14} />
                      {isImporting ? 'Importando registros…' : `Importar ${totalRows} Registros`}
                    </Button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </div>
  )
}


// ── Modal: Reasignación Individual ───────────────────────────────────────────

function ModalReasignarIndividual({ lead, asesores, onClose, onConfirm }) {
  const [selectedAsesor, setSelectedAsesor] = useState(lead.asesor_id || '')
  const [isSubmitting, setIsSubmitting] = useState(false)

  const handleSubmit = async (e) => {
    e.preventDefault()
    setIsSubmitting(true)
    await onConfirm(selectedAsesor || 'unassign')
    setIsSubmitting(false)
  }

  const handleUnassignDirect = async () => {
    setIsSubmitting(true)
    await onConfirm('unassign')
    setIsSubmitting(false)
  }

  const isCurrentlyAssigned = Boolean(lead.asesor_id || lead.lead_crm_id || (lead.asesor_nombre && lead.asesor_nombre !== '—'))

  return (
    <div className="fixed inset-0 z-50 bg-slate-900/60 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl max-w-sm w-full border border-slate-200 overflow-hidden animate-in zoom-in-95">
        <div className="px-5 py-4 border-b border-slate-100 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <UserCheck size={16} className="text-indigo-600" />
            <h3 className="text-sm font-bold text-slate-900">Reasignar y Activar Lead</h3>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
            <X size={16} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="p-5 space-y-4 text-xs">
          <div>
            <p className="text-slate-500">Lead seleccionado:</p>
            <p className="font-bold text-slate-800 text-sm mt-0.5">{lead.nombre || 'Sin nombre'}</p>
            <p className="text-slate-400">{lead.telefono} · {formatDate(lead.fecha_creacion || lead.fecha_ingreso)}</p>
            {lead.asesor_nombre && lead.asesor_nombre !== '—' && (
              <p className="text-[11px] text-indigo-700 bg-indigo-50 border border-indigo-100 rounded-md px-2 py-1 mt-1.5 flex items-center gap-1.5 font-medium">
                <User size={12} /> Asesor actual: <span className="font-bold">{lead.asesor_nombre}</span>
              </p>
            )}
          </div>

          <div>
            <label className="block font-semibold text-slate-700 mb-1">Asesor Destino:</label>
            <select
              value={selectedAsesor}
              onChange={(e) => setSelectedAsesor(e.target.value)}
              className="w-full px-3 py-2 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 text-xs"
            >
              <option value="">— Sin Asesor (dejar esperando reasignación) —</option>
              {asesores.map(a => (
                <option key={a.id} value={a.id}>{a.nombre_completo} ({a.role})</option>
              ))}
            </select>
            <p className="text-[10px] text-slate-400 mt-1">
              Al asignar un asesor registrado, este lead se activará inmediatamente en la página general de Leads para su seguimiento comercial.
            </p>
          </div>

          <div className="pt-2 flex items-center justify-between gap-2 border-t border-slate-100">
            {isCurrentlyAssigned ? (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={isSubmitting}
                onClick={handleUnassignDirect}
                className="text-amber-700 border-amber-300 hover:bg-amber-50 gap-1 text-xs"
                title="Quitar asignación y dejar esperando reasignación"
              >
                <UserX size={13} />
                Quitar asignación
              </Button>
            ) : <div />}
            <div className="flex items-center gap-2">
              <Button type="button" variant="outline" size="sm" onClick={onClose}>Cancelar</Button>
              <Button type="submit" size="sm" disabled={isSubmitting} className="bg-indigo-600 hover:bg-indigo-700 text-white font-medium">
                {isSubmitting ? 'Guardando…' : 'Guardar y Activar'}
              </Button>
            </div>
          </div>
        </form>
      </div>
    </div>
  )
}
