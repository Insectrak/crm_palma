import { useState, useEffect, useMemo, useCallback } from 'react'
import { Link } from 'react-router-dom'
import {
  Sparkles, Users, UserCheck, RotateCcw, ArrowRightLeft,
  Inbox, Trophy, Search, Filter, Download, RefreshCw,
  Calendar, ExternalLink, ChevronLeft, ChevronRight,
  TrendingUp, AlertCircle, Phone, Mail, CheckCircle2,
  PieChart as PieChartIcon, BarChart3, Layers, Building2,
  X, Check, Info, ShieldAlert,
} from 'lucide-react'
import {
  ResponsiveContainer, PieChart, Pie, Cell, Tooltip as RechartsTooltip,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Legend,
} from 'recharts'
import api from '@/lib/api'
import useAuthStore from '@/store/authStore'
import { cn } from '@/lib/utils'

// Paleta de colores armónica para gráficos y estados
const CHART_COLORS = [
  '#3b82f6', '#10b981', '#f59e0b', '#8b5cf6', '#ec4899',
  '#06b6d4', '#14b8a6', '#f97316', '#6366f1', '#64748b',
]

const UBICACION_COLORS = {
  mismo_equipo: '#10b981', // Verde esmeralda
  bolsa_tmk: '#f97316',    // Naranja
  otro_asesor: '#8b5cf6',  // Púrpura
  en_cola: '#64748b',      // Slate / Gris
  inactivo: '#ef4444',     // Rojo
}

const PERIODOS_PRESET = [
  { id: 'todos', label: 'Todo el historial' },
  { id: 'hoy', label: 'Hoy' },
  { id: 'semana', label: 'Esta semana' },
  { id: 'mes', label: 'Este mes' },
  { id: '30dias', label: 'Últimos 30 días' },
  { id: 'anio', label: 'Este año' },
  { id: 'custom', label: 'Personalizado' },
]

export default function ReportesEspeciales() {
  const { user } = useAuthStore()
  const role = user?.role || 'asesor'
  const isAdmin = role === 'admin'

  // Sub-tabs dentro de Reportería Especial (preparado para futuros desarrollos)
  const [activeTab, setActiveTab] = useState('historico_supervisor')

  // Catálogo de supervisores
  const [supervisores, setSupervisores] = useState([])
  const [selectedSupId, setSelectedSupId] = useState('')
  const [loadingSupervisores, setLoadingSupervisores] = useState(true)

  // Filtros
  const [periodo, setPeriodo] = useState('todos')
  const [fechaDesde, setFechaDesde] = useState('')
  const [fechaHasta, setFechaHasta] = useState('')
  const [ubicacionFilter, setUbicacionFilter] = useState('')
  const [searchTerm, setSearchTerm] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')

  // Datos
  const [resumen, setResumen] = useState(null)
  const [comparativa, setComparativa] = useState([])
  const [leadsData, setLeadsData] = useState({ items: [], total: 0, page: 1, limit: 50, pages: 1 })
  const [loadingResumen, setLoadingResumen] = useState(false)
  const [loadingLeads, setLoadingLeads] = useState(false)
  const [loadingExport, setLoadingExport] = useState(false)
  const [errorMsg, setErrorMsg] = useState('')

  // Debounce search
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(searchTerm), 400)
    return () => clearTimeout(timer)
  }, [searchTerm])

  // Carga inicial de supervisores
  useEffect(() => {
    setLoadingSupervisores(true)
    api.get('/api/reportes-especiales/supervisores')
      .then(res => {
        const list = res.data || []
        setSupervisores(list)
        if (list.length > 0) {
          // Si el usuario actual es supervisor, autoseleccionarse; si es admin, el primero de la lista
          const selfSup = list.find(s => String(s.id) === String(user?.user_id))
          setSelectedSupId(selfSup ? selfSup.id : list[0].id)
        }
      })
      .catch(err => {
        setErrorMsg(err?.response?.data?.detail || 'Error cargando supervisores permitidos.')
      })
      .finally(() => setLoadingSupervisores(false))
  }, [user?.user_id])

  // Calcular fechas efectivas según preset de período
  const effectiveDates = useMemo(() => {
    if (periodo === 'todos') return { desde: '', hasta: '' }
    if (periodo === 'custom') return { desde: fechaDesde, hasta: fechaHasta }

    const now = new Date()
    const fmt = (d) => d.toISOString().split('T')[0]

    if (periodo === 'hoy') {
      const todayStr = fmt(now)
      return { desde: todayStr, hasta: todayStr }
    }
    if (periodo === 'semana') {
      const day = now.getDay() || 7
      const monday = new Date(now)
      monday.setDate(now.getDate() - day + 1)
      return { desde: fmt(monday), hasta: fmt(now) }
    }
    if (periodo === 'mes') {
      const firstDay = new Date(now.getFullYear(), now.getMonth(), 1)
      return { desde: fmt(firstDay), hasta: fmt(now) }
    }
    if (periodo === '30dias') {
      const past30 = new Date(now)
      past30.setDate(now.getDate() - 30)
      return { desde: fmt(past30), hasta: fmt(now) }
    }
    if (periodo === 'anio') {
      const firstDayYear = new Date(now.getFullYear(), 0, 1)
      return { desde: fmt(firstDayYear), hasta: fmt(now) }
    }
    return { desde: '', hasta: '' }
  }, [periodo, fechaDesde, fechaHasta])

  // Cargar resumen de métricas
  const fetchResumen = useCallback(() => {
    if (!selectedSupId) return
    setLoadingResumen(true)
    setErrorMsg('')

    const params = new URLSearchParams()
    params.set('supervisor_id', selectedSupId)
    if (effectiveDates.desde) params.set('fecha_desde', effectiveDates.desde)
    if (effectiveDates.hasta) params.set('fecha_hasta', effectiveDates.hasta)
    if (ubicacionFilter) params.set('ubicacion_actual', ubicacionFilter)

    api.get(`/api/reportes-especiales/leads-historicos-supervisor/resumen?${params.toString()}`)
      .then(res => setResumen(res.data))
      .catch(err => {
        setErrorMsg(err?.response?.data?.detail || 'Error obteniendo resumen del supervisor.')
      })
      .finally(() => setLoadingResumen(false))
  }, [selectedSupId, effectiveDates, ubicacionFilter])

  // Cargar leads paginados
  const fetchLeads = useCallback((page = 1) => {
    if (!selectedSupId) return
    setLoadingLeads(true)

    const params = new URLSearchParams()
    params.set('supervisor_id', selectedSupId)
    params.set('page', String(page))
    params.set('limit', '50')
    if (effectiveDates.desde) params.set('fecha_desde', effectiveDates.desde)
    if (effectiveDates.hasta) params.set('fecha_hasta', effectiveDates.hasta)
    if (ubicacionFilter) params.set('ubicacion_actual', ubicacionFilter)
    if (debouncedSearch) params.set('search', debouncedSearch)

    api.get(`/api/reportes-especiales/leads-historicos-supervisor/detalle?${params.toString()}`)
      .then(res => setLeadsData(res.data || { items: [], total: 0, page: 1, limit: 50, pages: 1 }))
      .catch(() => {})
      .finally(() => setLoadingLeads(false))
  }, [selectedSupId, effectiveDates, ubicacionFilter, debouncedSearch])

  // Cargar comparativa si es admin
  const fetchComparativa = useCallback(() => {
    if (!isAdmin) return
    const params = new URLSearchParams()
    if (effectiveDates.desde) params.set('fecha_desde', effectiveDates.desde)
    if (effectiveDates.hasta) params.set('fecha_hasta', effectiveDates.hasta)

    api.get(`/api/reportes-especiales/leads-historicos-supervisor/comparativa?${params.toString()}`)
      .then(res => setComparativa(res.data || []))
      .catch(() => {})
  }, [isAdmin, effectiveDates])

  // Disparar recargas cuando cambian filtros primarios
  useEffect(() => {
    fetchResumen()
    fetchLeads(1)
    fetchComparativa()
  }, [fetchResumen, fetchLeads, fetchComparativa])

  // Exportar CSV
  const handleExportCSV = async () => {
    if (!selectedSupId) return
    setLoadingExport(true)
    try {
      const params = new URLSearchParams()
      params.set('supervisor_id', selectedSupId)
      if (effectiveDates.desde) params.set('fecha_desde', effectiveDates.desde)
      if (effectiveDates.hasta) params.set('fecha_hasta', effectiveDates.hasta)
      if (ubicacionFilter) params.set('ubicacion_actual', ubicacionFilter)
      if (debouncedSearch) params.set('search', debouncedSearch)

      const response = await api.get(`/api/reportes-especiales/leads-historicos-supervisor/exportar?${params.toString()}`, {
        responseType: 'blob',
      })
      const url = window.URL.createObjectURL(new Blob([response.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `leads_historicos_${selectedSupId}_${new Date().toISOString().slice(0, 10)}.csv`)
      document.body.appendChild(link)
      link.click()
      link.remove()
    } catch (err) {
      alert('Error descargando el archivo CSV: ' + (err.message || 'Desconocido'))
    } finally {
      setLoadingExport(false)
    }
  }

  // Prepara datos para los gráficos
  const chartDataUbicacion = useMemo(() => {
    if (!resumen?.desglose_ubicacion) return []
    return resumen.desglose_ubicacion.map(u => ({
      name: u.label,
      value: u.total,
      percentage: u.porcentaje,
      color: UBICACION_COLORS[u.key] || '#64748b',
    }))
  }, [resumen])

  const chartDataFuentes = useMemo(() => {
    if (!resumen?.desglose_fuentes) return []
    return resumen.desglose_fuentes.slice(0, 6).map((f, i) => ({
      name: f.nombre,
      value: f.total,
      percentage: f.porcentaje,
      color: CHART_COLORS[i % CHART_COLORS.length],
    }))
  }, [resumen])

  const chartDataOrigenes = useMemo(() => {
    if (!resumen?.desglose_origenes) return []
    return resumen.desglose_origenes.slice(0, 6).map(o => ({
      name: o.nombre.length > 20 ? o.nombre.slice(0, 18) + '…' : o.nombre,
      fullName: o.nombre,
      total: o.total,
      percentage: o.porcentaje,
    }))
  }, [resumen])

  const selectedSupervisorObj = supervisores.find(s => String(s.id) === String(selectedSupId))

  return (
    <div className="space-y-6 max-w-[1600px] mx-auto pb-12">
      {/* ── Header Principal ── */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-gradient-to-r from-slate-900 via-slate-800 to-indigo-950 p-6 rounded-2xl text-white shadow-xl">
        <div className="space-y-1">
          <div className="flex items-center gap-2">
            <span className="p-2 bg-indigo-500/20 text-indigo-400 rounded-xl border border-indigo-400/30">
              <Sparkles size={20} className="animate-pulse" />
            </span>
            <span className="text-xs uppercase tracking-widest text-indigo-300 font-semibold px-2 py-0.5 rounded-full bg-indigo-500/10 border border-indigo-500/20">
              Reportería Especial
            </span>
          </div>
          <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-white">
            Auditoría Histórica de Leads por Supervisor
          </h1>
          <p className="text-sm text-slate-300 max-w-2xl leading-relaxed">
            Consulte con exactitud todos los leads recibidos de forma histórica, incluyendo los que fueron movidos a la <strong>Bolsa TMK</strong> o reasignados a otros asesores, identificando su fuente original, campaña y dónde están ubicados hoy.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <button
            onClick={() => { fetchResumen(); fetchLeads(leadsData.page); fetchComparativa(); }}
            className="flex items-center gap-2 px-3.5 py-2 rounded-xl bg-white/10 hover:bg-white/20 text-white text-xs font-medium transition backdrop-blur-sm border border-white/10"
            title="Refrescar datos"
          >
            <RefreshCw size={14} className={loadingResumen ? 'animate-spin' : ''} />
            <span>Actualizar</span>
          </button>
          <button
            onClick={handleExportCSV}
            disabled={loadingExport || !leadsData.total}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-medium shadow-lg shadow-indigo-600/30 transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Download size={14} />
            <span>{loadingExport ? 'Generando CSV...' : 'Exportar CSV'}</span>
          </button>
        </div>
      </div>

      {/* ── Sub-navegación por tabs ── */}
      <div className="flex items-center gap-2 border-b border-gray-200 dark:border-slate-800 pb-2">
        <button
          onClick={() => setActiveTab('historico_supervisor')}
          className={cn(
            'flex items-center gap-2 px-4 py-2 rounded-xl text-sm font-semibold transition',
            activeTab === 'historico_supervisor'
              ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/20'
              : 'text-gray-600 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-800'
          )}
        >
          <Layers size={16} />
          <span>Leads Históricos por Supervisor</span>
          <span className="text-[10px] uppercase tracking-wider px-1.5 py-0.5 rounded-full bg-white/20 ml-1">
            Primer Desarrollo
          </span>
        </button>
      </div>

      {errorMsg && (
        <div className="flex items-center gap-3 bg-red-50 dark:bg-red-950/30 border border-red-200 dark:border-red-800/50 text-red-700 dark:text-red-300 text-sm rounded-xl p-4">
          <ShieldAlert size={18} className="shrink-0 text-red-600" />
          <span>{errorMsg}</span>
        </div>
      )}

      {/* ── Barra de Controles y Filtros ── */}
      <div className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-2xl p-4 sm:p-5 shadow-sm space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Selector de Supervisor */}
          <div>
            <label className="block text-xs font-semibold text-gray-700 dark:text-slate-300 uppercase tracking-wider mb-1.5">
              Supervisor Seleccionado
            </label>
            <div className="relative">
              <select
                value={selectedSupId}
                onChange={e => setSelectedSupId(e.target.value)}
                disabled={loadingSupervisores || supervisores.length <= 1}
                className="w-full bg-gray-50 dark:bg-slate-800/80 border border-gray-200 dark:border-slate-700 rounded-xl px-3.5 py-2.5 text-sm font-medium text-gray-900 dark:text-slate-100 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500 disabled:opacity-80"
              >
                {supervisores.map(s => (
                  <option key={s.id} value={s.id}>
                    {s.nombre} {s.asesores_activos > 0 ? `(${s.asesores_activos} asesores)` : ''}
                  </option>
                ))}
              </select>
              {loadingSupervisores && (
                <div className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-slate-400">
                  Cargando...
                </div>
              )}
            </div>
          </div>

          {/* Filtro Ubicación Actual ("¿En dónde están ahora?") */}
          <div>
            <label className="block text-xs font-semibold text-gray-700 dark:text-slate-300 uppercase tracking-wider mb-1.5">
              ¿En dónde están ahora?
            </label>
            <select
              value={ubicacionFilter}
              onChange={e => setUbicacionFilter(e.target.value)}
              className="w-full bg-gray-50 dark:bg-slate-800/80 border border-gray-200 dark:border-slate-700 rounded-xl px-3.5 py-2.5 text-sm font-medium text-gray-900 dark:text-slate-100 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
            >
              <option value="">Todas las ubicaciones</option>
              <option value="mismo_equipo">🟢 En su equipo (activos)</option>
              <option value="bolsa_tmk">🟠 En Bolsa TMK (reciclaje)</option>
              <option value="otro_asesor">🟣 Reasignados a otros asesores</option>
              <option value="en_cola">⚪ En cola (Sin asesor)</option>
              <option value="inactivo">⚫ Inactivos / Papelera</option>
            </select>
          </div>

          {/* Búsqueda rápida */}
          <div className="lg:col-span-2">
            <label className="block text-xs font-semibold text-gray-700 dark:text-slate-300 uppercase tracking-wider mb-1.5">
              Búsqueda en leads del supervisor
            </label>
            <div className="relative">
              <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                placeholder="Buscar por nombre, teléfono, email, campaña..."
                value={searchTerm}
                onChange={e => setSearchTerm(e.target.value)}
                className="w-full pl-10 pr-10 py-2.5 bg-gray-50 dark:bg-slate-800/80 border border-gray-200 dark:border-slate-700 rounded-xl text-sm text-gray-900 dark:text-slate-100 focus:ring-2 focus:ring-indigo-500 focus:border-indigo-500"
              />
              {searchTerm && (
                <button
                  onClick={() => setSearchTerm('')}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-slate-200"
                >
                  <X size={16} />
                </button>
              )}
            </div>
          </div>
        </div>

        {/* Preset de Período y Fechas */}
        <div className="pt-2 border-t border-gray-100 dark:border-slate-800 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-1.5">
            <span className="text-xs text-gray-500 dark:text-slate-400 mr-1 flex items-center gap-1 font-medium">
              <Calendar size={13} />
              <span>Período de ingreso:</span>
            </span>
            {PERIODOS_PRESET.map(p => (
              <button
                key={p.id}
                onClick={() => setPeriodo(p.id)}
                className={cn(
                  'px-3 py-1 rounded-lg text-xs font-medium transition',
                  periodo === p.id
                    ? 'bg-indigo-600 text-white shadow-sm'
                    : 'bg-gray-100 dark:bg-slate-800 text-gray-700 dark:text-slate-300 hover:bg-gray-200 dark:hover:bg-slate-700'
                )}
              >
                {p.label}
              </button>
            ))}
          </div>

          {periodo === 'custom' && (
            <div className="flex items-center gap-2 bg-indigo-50 dark:bg-indigo-950/40 p-1.5 rounded-xl border border-indigo-200 dark:border-indigo-800/40 text-xs">
              <input
                type="date"
                value={fechaDesde}
                onChange={e => setFechaDesde(e.target.value)}
                className="bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg px-2 py-1 text-xs"
              />
              <span className="text-slate-500">hasta</span>
              <input
                type="date"
                value={fechaHasta}
                onChange={e => setFechaHasta(e.target.value)}
                className="bg-white dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg px-2 py-1 text-xs"
              />
            </div>
          )}

          {ubicacionFilter && (
            <button
              onClick={() => setUbicacionFilter('')}
              className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline flex items-center gap-1"
            >
              <X size={12} />
              <span>Limpiar filtro de ubicación</span>
            </button>
          )}
        </div>
      </div>

      {/* ── Métricas Principales (KPI Cards) ── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3.5 sm:gap-4">
        {/* Card 1: Total Leads Recibidos Histórico */}
        <div className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-2xl p-4 sm:p-5 shadow-sm relative overflow-hidden group hover:border-indigo-400 transition-all">
          <div className="flex items-center justify-between text-slate-500 dark:text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Total Recibidos</span>
            <span className="p-2 bg-blue-50 dark:bg-blue-950/40 text-blue-600 dark:text-blue-400 rounded-xl">
              <Inbox size={18} />
            </span>
          </div>
          <div className="text-2xl sm:text-3xl font-extrabold text-gray-900 dark:text-white">
            {loadingResumen ? '...' : (resumen?.kpis?.total_recibidos || 0).toLocaleString()}
          </div>
          <p className="text-[11px] text-gray-500 dark:text-slate-400 mt-1">
            Histórico total ingresado a su bandeja
          </p>
          <div className="absolute top-0 right-0 h-1 w-full bg-blue-500" />
        </div>

        {/* Card 2: En su Equipo Actual */}
        <div
          onClick={() => setUbicacionFilter(ubicacionFilter === 'mismo_equipo' ? '' : 'mismo_equipo')}
          className={cn(
            'bg-white dark:bg-slate-900 border rounded-2xl p-4 sm:p-5 shadow-sm relative overflow-hidden cursor-pointer transition-all',
            ubicacionFilter === 'mismo_equipo'
              ? 'border-emerald-500 ring-2 ring-emerald-500/20 shadow-md'
              : 'border-gray-200 dark:border-slate-800 hover:border-emerald-400'
          )}
        >
          <div className="flex items-center justify-between text-slate-500 dark:text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">En su equipo</span>
            <span className="p-2 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 rounded-xl">
              <UserCheck size={18} />
            </span>
          </div>
          <div className="text-2xl sm:text-3xl font-extrabold text-emerald-600 dark:text-emerald-400">
            {loadingResumen ? '...' : (resumen?.kpis?.en_equipo_actual || 0).toLocaleString()}
          </div>
          <p className="text-[11px] text-gray-500 dark:text-slate-400 mt-1">
            Activos bajo su supervisión directa
          </p>
          <div className="absolute top-0 right-0 h-1 w-full bg-emerald-500" />
        </div>

        {/* Card 3: En Bolsa TMK */}
        <div
          onClick={() => setUbicacionFilter(ubicacionFilter === 'bolsa_tmk' ? '' : 'bolsa_tmk')}
          className={cn(
            'bg-white dark:bg-slate-900 border rounded-2xl p-4 sm:p-5 shadow-sm relative overflow-hidden cursor-pointer transition-all',
            ubicacionFilter === 'bolsa_tmk'
              ? 'border-orange-500 ring-2 ring-orange-500/20 shadow-md'
              : 'border-gray-200 dark:border-slate-800 hover:border-orange-400'
          )}
        >
          <div className="flex items-center justify-between text-slate-500 dark:text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">En Bolsa TMK</span>
            <span className="p-2 bg-orange-50 dark:bg-orange-950/40 text-orange-600 dark:text-orange-400 rounded-xl">
              <RotateCcw size={18} />
            </span>
          </div>
          <div className="text-2xl sm:text-3xl font-extrabold text-orange-600 dark:text-orange-400">
            {loadingResumen ? '...' : (resumen?.kpis?.en_bolsa_tmk || 0).toLocaleString()}
          </div>
          <p className="text-[11px] text-gray-500 dark:text-slate-400 mt-1">
            Movidos o reciclados a Telemarketing
          </p>
          <div className="absolute top-0 right-0 h-1 w-full bg-orange-500" />
        </div>

        {/* Card 4: Reasignados a otros asesores */}
        <div
          onClick={() => setUbicacionFilter(ubicacionFilter === 'otro_asesor' ? '' : 'otro_asesor')}
          className={cn(
            'bg-white dark:bg-slate-900 border rounded-2xl p-4 sm:p-5 shadow-sm relative overflow-hidden cursor-pointer transition-all',
            ubicacionFilter === 'otro_asesor'
              ? 'border-purple-500 ring-2 ring-purple-500/20 shadow-md'
              : 'border-gray-200 dark:border-slate-800 hover:border-purple-400'
          )}
        >
          <div className="flex items-center justify-between text-slate-500 dark:text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Reasignados fuera</span>
            <span className="p-2 bg-purple-50 dark:bg-purple-950/40 text-purple-600 dark:text-purple-400 rounded-xl">
              <ArrowRightLeft size={18} />
            </span>
          </div>
          <div className="text-2xl sm:text-3xl font-extrabold text-purple-600 dark:text-purple-400">
            {loadingResumen ? '...' : (resumen?.kpis?.reasignados_otro_equipo || 0).toLocaleString()}
          </div>
          <p className="text-[11px] text-gray-500 dark:text-slate-400 mt-1">
            Derivados a otros supervisores/equipos
          </p>
          <div className="absolute top-0 right-0 h-1 w-full bg-purple-500" />
        </div>

        {/* Card 5: Matriculados / Ventas */}
        <div className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-2xl p-4 sm:p-5 shadow-sm relative overflow-hidden col-span-2 sm:col-span-1 hover:border-emerald-400 transition-all">
          <div className="flex items-center justify-between text-slate-500 dark:text-slate-400 mb-2">
            <span className="text-xs font-semibold uppercase tracking-wider">Matriculados</span>
            <span className="p-2 bg-emerald-50 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400 rounded-xl">
              <Trophy size={18} />
            </span>
          </div>
          <div className="text-2xl sm:text-3xl font-extrabold text-emerald-600 dark:text-emerald-400">
            {loadingResumen ? '...' : (resumen?.kpis?.matriculados || 0).toLocaleString()}
          </div>
          <p className="text-[11px] text-gray-500 dark:text-slate-400 mt-1">
            Leads ganados / convertidos
          </p>
          <div className="absolute top-0 right-0 h-1 w-full bg-emerald-500" />
        </div>
      </div>

      {/* ── Paneles Analíticos (Grid de 3 columnas) ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Panel 1: ¿En Dónde Están Ahora? */}
        <div className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between border-b border-gray-100 dark:border-slate-800 pb-3">
            <div className="flex items-center gap-2">
              <PieChartIcon size={18} className="text-indigo-500" />
              <h2 className="text-sm font-bold text-gray-900 dark:text-white uppercase tracking-wider">
                ¿En Dónde Están Ahora?
              </h2>
            </div>
            <span className="text-xs text-gray-500">Trazabilidad actual</span>
          </div>

          <div className="h-52">
            {chartDataUbicacion.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={chartDataUbicacion}
                    cx="50%"
                    cy="50%"
                    innerRadius={52}
                    outerRadius={80}
                    paddingAngle={3}
                    dataKey="value"
                  >
                    {chartDataUbicacion.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                  <RechartsTooltip
                    formatter={(val, name, props) => [`${val} leads (${props.payload.percentage}%)`, name]}
                    contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', borderRadius: '12px', color: '#fff', fontSize: '12px' }}
                  />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex items-center justify-center h-full text-xs text-slate-400">
                Sin datos de ubicación
              </div>
            )}
          </div>

          <div className="space-y-2 pt-2 border-t border-gray-100 dark:border-slate-800">
            {resumen?.desglose_ubicacion?.map(u => (
              <div
                key={u.key}
                onClick={() => setUbicacionFilter(ubicacionFilter === u.key ? '' : u.key)}
                className={cn(
                  'flex items-center justify-between p-2 rounded-xl text-xs cursor-pointer transition',
                  ubicacionFilter === u.key
                    ? 'bg-indigo-50 dark:bg-indigo-950/50 border border-indigo-200 dark:border-indigo-800 font-semibold'
                    : 'hover:bg-gray-50 dark:hover:bg-slate-800/60'
                )}
              >
                <div className="flex items-center gap-2.5">
                  <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: UBICACION_COLORS[u.key] || '#64748b' }} />
                  <span className="text-gray-800 dark:text-slate-200">{u.label}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="font-bold text-gray-900 dark:text-white">{u.total.toLocaleString()}</span>
                  <span className="text-gray-400 text-[11px]">({u.porcentaje}%)</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Panel 2: Distribución por Fuente Original */}
        <div className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between border-b border-gray-100 dark:border-slate-800 pb-3">
            <div className="flex items-center gap-2">
              <Filter size={18} className="text-blue-500" />
              <h2 className="text-sm font-bold text-gray-900 dark:text-white uppercase tracking-wider">
                Fuente Original
              </h2>
            </div>
            <span className="text-xs text-gray-500">Canal de captura inicial</span>
          </div>

          <div className="h-52">
            {chartDataFuentes.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={chartDataFuentes}
                    cx="50%"
                    cy="50%"
                    outerRadius={80}
                    dataKey="value"
                  >
                    {chartDataFuentes.map((entry, index) => (
                      <Cell key={`source-cell-${index}`} fill={entry.color} />
                    ))}
                  </Pie>
                  <RechartsTooltip
                    formatter={(val, name, props) => [`${val} leads (${props.payload.percentage}%)`, name]}
                    contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', borderRadius: '12px', color: '#fff', fontSize: '12px' }}
                  />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex items-center justify-center h-full text-xs text-slate-400">
                Sin datos de fuentes
              </div>
            )}
          </div>

          <div className="space-y-2 pt-2 border-t border-gray-100 dark:border-slate-800">
            {resumen?.desglose_fuentes?.slice(0, 5).map((f, i) => (
              <div key={f.id || i} className="flex items-center justify-between p-1.5 text-xs">
                <div className="flex items-center gap-2">
                  <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: CHART_COLORS[i % CHART_COLORS.length] }} />
                  <span className="text-gray-800 dark:text-slate-200 truncate max-w-[170px]">{f.nombre}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="font-bold text-gray-900 dark:text-white">{f.total.toLocaleString()}</span>
                  <span className="text-gray-400 text-[11px]">({f.porcentaje}%)</span>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* Panel 3: Origen y Campañas */}
        <div className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between border-b border-gray-100 dark:border-slate-800 pb-3">
            <div className="flex items-center gap-2">
              <BarChart3 size={18} className="text-emerald-500" />
              <h2 className="text-sm font-bold text-gray-900 dark:text-white uppercase tracking-wider">
                Campaña / Origen
              </h2>
            </div>
            <span className="text-xs text-gray-500">Top campañas</span>
          </div>

          <div className="h-52">
            {chartDataOrigenes.length > 0 ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartDataOrigenes} layout="vertical" margin={{ left: 10, right: 20 }}>
                  <CartesianGrid strokeDasharray="3 3" opacity={0.15} horizontal={false} />
                  <XAxis type="number" hide />
                  <YAxis type="category" dataKey="name" tick={{ fontSize: 10, fill: '#94a3b8' }} width={90} />
                  <RechartsTooltip
                    formatter={(val, name, props) => [`${val} leads (${props.payload.percentage}%)`, props.payload.fullName]}
                    contentStyle={{ backgroundColor: '#0f172a', borderColor: '#1e293b', borderRadius: '12px', color: '#fff', fontSize: '12px' }}
                  />
                  <Bar dataKey="total" fill="#10b981" radius={[0, 6, 6, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : (
              <div className="flex items-center justify-center h-full text-xs text-slate-400">
                Sin datos de campañas
              </div>
            )}
          </div>

          <div className="space-y-1.5 pt-2 border-t border-gray-100 dark:border-slate-800 max-h-40 overflow-y-auto pr-1">
            {resumen?.desglose_origenes?.slice(0, 5).map((o, idx) => (
              <div key={idx} className="flex items-center justify-between p-1 text-xs">
                <span className="text-gray-700 dark:text-slate-300 truncate max-w-[190px]" title={o.nombre}>
                  {o.nombre}
                </span>
                <span className="font-semibold text-gray-900 dark:text-white shrink-0">
                  {o.total} <span className="text-[10px] text-gray-400 font-normal">({o.porcentaje}%)</span>
                </span>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* ── Comparativa entre Supervisores (Visible para Admin / Jefatura) ── */}
      {isAdmin && comparativa.length > 1 && (
        <div className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-2xl p-5 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <div>
              <h2 className="text-base font-bold text-gray-900 dark:text-white flex items-center gap-2">
                <Building2 size={18} className="text-indigo-600" />
                <span>Comparativa Global de Supervisores</span>
              </h2>
              <p className="text-xs text-gray-500 mt-0.5">
                Volumen histórico total recibido por cada supervisor y estado actual de su cartera
              </p>
            </div>
            <span className="text-xs bg-indigo-50 dark:bg-indigo-950/60 text-indigo-700 dark:text-indigo-300 px-2.5 py-1 rounded-full font-medium">
              {comparativa.length} supervisores
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-gray-50 dark:bg-slate-800/60 text-gray-600 dark:text-slate-400 uppercase tracking-wider font-semibold">
                <tr>
                  <th className="py-3 px-4 rounded-l-xl">Supervisor</th>
                  <th className="py-3 px-4 text-center">Total Recibidos</th>
                  <th className="py-3 px-4 text-center">En su Equipo</th>
                  <th className="py-3 px-4 text-center">En Bolsa TMK</th>
                  <th className="py-3 px-4 text-center">Reasignados Fuera</th>
                  <th className="py-3 px-4 text-center">En Cola</th>
                  <th className="py-3 px-4 text-center">Matriculados</th>
                  <th className="py-3 px-4 text-right rounded-r-xl">Acción</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-slate-800">
                {comparativa.map(s => {
                  const isSelected = String(s.id) === String(selectedSupId)
                  return (
                    <tr
                      key={s.id}
                      className={cn(
                        'transition-colors',
                        isSelected
                          ? 'bg-indigo-50/70 dark:bg-indigo-950/30 font-semibold'
                          : 'hover:bg-gray-50 dark:hover:bg-slate-800/40'
                      )}
                    >
                      <td className="py-3 px-4">
                        <div className="font-semibold text-gray-900 dark:text-white">{s.nombre}</div>
                        <div className="text-[11px] text-gray-400">{s.email}</div>
                      </td>
                      <td className="py-3 px-4 text-center font-bold text-gray-900 dark:text-white text-sm">
                        {s.total_recibidos.toLocaleString()}
                      </td>
                      <td className="py-3 px-4 text-center text-emerald-600 font-semibold">
                        {s.en_equipo.toLocaleString()}
                      </td>
                      <td className="py-3 px-4 text-center text-orange-600 font-semibold">
                        {s.en_bolsa_tmk.toLocaleString()}
                      </td>
                      <td className="py-3 px-4 text-center text-purple-600 font-semibold">
                        {s.reasignados_otro_equipo.toLocaleString()}
                      </td>
                      <td className="py-3 px-4 text-center text-slate-500 font-semibold">
                        {s.en_cola.toLocaleString()}
                      </td>
                      <td className="py-3 px-4 text-center text-emerald-700 font-bold">
                        {s.matriculados.toLocaleString()}
                      </td>
                      <td className="py-3 px-4 text-right">
                        <button
                          onClick={() => setSelectedSupId(s.id)}
                          className={cn(
                            'px-3 py-1 rounded-lg text-xs font-medium transition',
                            isSelected
                              ? 'bg-indigo-600 text-white'
                              : 'bg-gray-100 dark:bg-slate-800 text-gray-700 dark:text-slate-300 hover:bg-gray-200 dark:hover:bg-slate-700'
                          )}
                        >
                          {isSelected ? 'Consultando' : 'Ver detalle'}
                        </button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ── Tabla Detallada de Leads ── */}
      <div className="bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800 rounded-2xl shadow-sm overflow-hidden">
        <div className="p-4 sm:p-5 border-b border-gray-100 dark:border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-bold text-gray-900 dark:text-white flex items-center gap-2">
              <span>Listado de Leads Históricos</span>
              {selectedSupervisorObj && (
                <span className="text-xs bg-gray-100 dark:bg-slate-800 text-gray-700 dark:text-slate-300 px-2.5 py-0.5 rounded-full font-medium">
                  {selectedSupervisorObj.nombre}
                </span>
              )}
            </h2>
            <p className="text-xs text-gray-500 mt-0.5">
              Mostrando {leadsData.items.length} de {leadsData.total.toLocaleString()} leads encontrados
            </p>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-xs text-gray-400">
              Página {leadsData.page} de {leadsData.pages}
            </span>
            <button
              onClick={() => fetchLeads(leadsData.page - 1)}
              disabled={leadsData.page <= 1 || loadingLeads}
              className="p-1.5 rounded-lg border border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-800 disabled:opacity-30"
            >
              <ChevronLeft size={16} />
            </button>
            <button
              onClick={() => fetchLeads(leadsData.page + 1)}
              disabled={leadsData.page >= leadsData.pages || loadingLeads}
              className="p-1.5 rounded-lg border border-gray-200 dark:border-slate-700 text-gray-600 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-800 disabled:opacity-30"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-gray-50 dark:bg-slate-800/60 text-gray-600 dark:text-slate-400 uppercase tracking-wider font-semibold">
              <tr>
                <th className="py-3 px-4">Lead</th>
                <th className="py-3 px-4">Fecha Ingreso</th>
                <th className="py-3 px-4">Fuente Original</th>
                <th className="py-3 px-4">Origen / Campaña</th>
                <th className="py-3 px-4">¿Dónde está ahora?</th>
                <th className="py-3 px-4">Asesor Actual</th>
                <th className="py-3 px-4">Estado Pipeline</th>
                <th className="py-3 px-4 text-right">Detalle</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-slate-800">
              {loadingLeads ? (
                <tr>
                  <td colSpan={8} className="py-12 text-center text-gray-400">
                    <RefreshCw size={24} className="animate-spin mx-auto mb-2 opacity-40" />
                    <span>Cargando leads históricos...</span>
                  </td>
                </tr>
              ) : leadsData.items.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-12 text-center text-gray-400">
                    <Inbox size={32} className="mx-auto mb-2 opacity-30" />
                    <span>No se encontraron leads históricos con los filtros aplicados.</span>
                  </td>
                </tr>
              ) : (
                leadsData.items.map(lead => (
                  <tr key={lead.id} className="hover:bg-gray-50 dark:hover:bg-slate-800/40 transition-colors">
                    {/* Nombre y Contacto */}
                    <td className="py-3 px-4">
                      <div className="font-semibold text-gray-900 dark:text-white">
                        {lead.nombre_completo || 'Sin nombre'}
                      </div>
                      <div className="flex items-center gap-2 text-[11px] text-gray-500 dark:text-slate-400 mt-0.5">
                        {lead.telefono && <span>📞 {lead.telefono}</span>}
                        {lead.email && <span className="truncate max-w-[140px]" title={lead.email}>✉️ {lead.email}</span>}
                      </div>
                    </td>

                    {/* Fecha de ingreso */}
                    <td className="py-3 px-4 text-gray-600 dark:text-slate-300">
                      {lead.fecha_ingreso ? new Date(lead.fecha_ingreso).toLocaleDateString('es-PE', { day: '2-digit', month: 'short', year: 'numeric' }) : '-'}
                      <div className="text-[10px] text-gray-400">
                        {lead.fecha_ingreso ? new Date(lead.fecha_ingreso).toLocaleTimeString('es-PE', { hour: '2-digit', minute: '2-digit' }) : ''}
                      </div>
                    </td>

                    {/* Fuente original */}
                    <td className="py-3 px-4">
                      <span className="font-medium text-gray-800 dark:text-slate-200">
                        {lead.fuente_original_nombre}
                      </span>
                      {lead.fuente_actual_nombre && lead.fuente_actual_nombre !== lead.fuente_original_nombre && (
                        <div className="text-[10px] text-orange-600 dark:text-orange-400">
                          Actual: {lead.fuente_actual_nombre}
                        </div>
                      )}
                    </td>

                    {/* Origen / Campaña */}
                    <td className="py-3 px-4 text-gray-700 dark:text-slate-300">
                      <div className="font-medium truncate max-w-[180px]" title={lead.origen_nombre}>
                        {lead.origen_nombre}
                      </div>
                      {lead.anuncio && (
                        <div className="text-[10px] text-gray-400 truncate max-w-[180px]" title={lead.anuncio}>
                          Anuncio: {lead.anuncio}
                        </div>
                      )}
                    </td>

                    {/* ¿Dónde está ahora? */}
                    <td className="py-3 px-4">
                      {lead.tipo_ubicacion === 'mismo_equipo' && (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-emerald-50 dark:bg-emerald-950/50 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800">
                          <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                          <span>En su equipo</span>
                        </span>
                      )}
                      {lead.tipo_ubicacion === 'bolsa_tmk' && (
                        <div>
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-orange-50 dark:bg-orange-950/50 text-orange-700 dark:text-orange-300 border border-orange-200 dark:border-orange-800">
                            <span className="w-1.5 h-1.5 rounded-full bg-orange-500" />
                            <span>Bolsa TMK</span>
                          </span>
                          {lead.origen_reciclaje && (
                            <div className="text-[10px] text-orange-600/80 dark:text-orange-400/80 mt-0.5 ml-1">
                              {lead.origen_reciclaje}
                            </div>
                          )}
                        </div>
                      )}
                      {lead.tipo_ubicacion === 'otro_asesor' && (
                        <div>
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-purple-50 dark:bg-purple-950/50 text-purple-700 dark:text-purple-300 border border-purple-200 dark:border-purple-800">
                            <span className="w-1.5 h-1.5 rounded-full bg-purple-500" />
                            <span>Reasignado fuera</span>
                          </span>
                          {lead.supervisor_actual_nombre && (
                            <div className="text-[10px] text-purple-600/80 dark:text-purple-400/80 mt-0.5 ml-1">
                              Sup: {lead.supervisor_actual_nombre}
                            </div>
                          )}
                        </div>
                      )}
                      {lead.tipo_ubicacion === 'en_cola' && (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-gray-100 dark:bg-slate-800 text-gray-700 dark:text-slate-300 border border-gray-200 dark:border-slate-700">
                          <span className="w-1.5 h-1.5 rounded-full bg-gray-400" />
                          <span>En cola (Sin asesor)</span>
                        </span>
                      )}
                      {lead.tipo_ubicacion === 'inactivo' && (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-semibold bg-red-50 dark:bg-red-950/50 text-red-700 dark:text-red-300 border border-red-200 dark:border-red-800">
                          <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
                          <span>Inactivo / Papelera</span>
                        </span>
                      )}
                    </td>

                    {/* Asesor Actual */}
                    <td className="py-3 px-4">
                      {lead.asesor_actual_nombre ? (
                        <span className="font-medium text-gray-900 dark:text-white">
                          {lead.asesor_actual_nombre}
                        </span>
                      ) : (
                        <span className="text-gray-400 italic">Sin asesor</span>
                      )}
                    </td>

                    {/* Estado del pipeline comercial */}
                    <td className="py-3 px-4">
                      <div className="flex items-center gap-1.5">
                        <span
                          className="w-2 h-2 rounded-full shrink-0"
                          style={{ backgroundColor: lead.estado_color || '#64748b' }}
                        />
                        <span className="text-gray-800 dark:text-slate-200 font-medium">
                          {lead.estado_nombre || 'Sin estado'}
                        </span>
                      </div>
                    </td>

                    {/* Enlace al detalle del lead */}
                    <td className="py-3 px-4 text-right">
                      <Link
                        to={`/leads/${lead.id}`}
                        className="inline-flex items-center gap-1 px-2.5 py-1 bg-gray-100 dark:bg-slate-800 hover:bg-indigo-50 dark:hover:bg-indigo-950/40 text-gray-700 dark:text-slate-300 hover:text-indigo-600 rounded-lg text-xs font-medium transition"
                        title="Ver ficha completa del lead"
                      >
                        <span>#{lead.id}</span>
                        <ExternalLink size={12} />
                      </Link>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Paginación footer */}
        <div className="p-4 border-t border-gray-100 dark:border-slate-800 flex items-center justify-between text-xs text-gray-500 dark:text-slate-400">
          <span>Mostrando página {leadsData.page} de {leadsData.pages} ({leadsData.total} registros totales)</span>
          <div className="flex items-center gap-1">
            <button
              onClick={() => fetchLeads(leadsData.page - 1)}
              disabled={leadsData.page <= 1 || loadingLeads}
              className="px-3 py-1.5 rounded-lg border border-gray-200 dark:border-slate-700 hover:bg-gray-100 dark:hover:bg-slate-800 disabled:opacity-30 font-medium"
            >
              Anterior
            </button>
            <button
              onClick={() => fetchLeads(leadsData.page + 1)}
              disabled={leadsData.page >= leadsData.pages || loadingLeads}
              className="px-3 py-1.5 rounded-lg border border-gray-200 dark:border-slate-700 hover:bg-gray-100 dark:hover:bg-slate-800 disabled:opacity-30 font-medium"
            >
              Siguiente
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
