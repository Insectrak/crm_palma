import React, { useState, useEffect, useMemo, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  ShieldCheck,
  AlertTriangle,
  Clock,
  PhoneCall,
  Users,
  UserX,
  UserCheck,
  BarChart3,
  Flame,
  Zap,
  CheckCircle2,
  ExternalLink,
  RefreshCw,
  Search,
  Layers,
  Calendar,
  ArrowRightLeft,
  TrendingUp,
  X,
} from 'lucide-react'
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  Legend,
  CartesianGrid,
} from 'recharts'
import api from '@/lib/api'
import SeguimientoCitasTab from '@/components/dashboard/SeguimientoCitasTab'
import EvolucionCitasTab from '@/components/dashboard/EvolucionCitasTab'

// Helper para formato de minutos/segundos
function formatSegundos(seg) {
  if (!seg || seg <= 0) return '0s'
  const m = Math.floor(seg / 60)
  const s = seg % 60
  if (m === 0) return `${s}s`
  if (s === 0) return `${m}m`
  return `${m}m ${s}s`
}

// Helper para formato de tiempo de respuesta en minutos (min / h / d)
function formatMinutos(min) {
  if (min === null || min === undefined || Number.isNaN(Number(min)) || Number(min) <= 0) return '0m'
  const totalMin = Math.round(Number(min) * 10) / 10
  if (totalMin < 60) return `${totalMin}m`
  const horas = Math.floor(totalMin / 60)
  const remMin = Math.round(totalMin % 60)
  if (horas < 24) return remMin > 0 ? `${horas}h ${remMin}m` : `${horas}h`
  const dias = Math.floor(horas / 24)
  const remH = horas % 24
  return remH > 0 ? `${dias}d ${remH}h` : `${dias}d`
}

export default function DashboardSupervisionControl() {
  const navigate = useNavigate()

  // Estados de control
  const [periodo, setPeriodo] = useState('hoy') // 'hoy' | 'ayer' | 'semana' | 'mes' | '30dias' | 'custom'
  const [fechaInicio, setFechaInicio] = useState('')
  const [fechaFin, setFechaFin] = useState('')
  const [customOpen, setCustomOpen] = useState(false)
  const [draftInicio, setDraftInicio] = useState(() => new Date().toLocaleDateString('en-CA'))
  const [draftFin, setDraftFin] = useState(() => new Date().toLocaleDateString('en-CA'))
  const popoverRef = useRef(null)
  const customBtnRef = useRef(null)

  const [sedeId, setSedeId] = useState('')
  const [supervisorId, setSupervisorId] = useState('')
  const [asesorId, setAsesorId] = useState('')
  const [searchAsesor, setSearchAsesor] = useState('')
  const [filtroEstadoAsesor, setFiltroEstadoAsesor] = useState('todos') // 'todos' | 'activos' | 'inactivos' | 'pendientes'

  // Cerrar popover al hacer clic fuera o presionar Escape
  useEffect(() => {
    if (!customOpen) return undefined
    const handleMouseDown = (e) => {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target) &&
        customBtnRef.current &&
        !customBtnRef.current.contains(e.target)
      ) {
        setCustomOpen(false)
      }
    }
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') setCustomOpen(false)
    }
    document.addEventListener('mousedown', handleMouseDown)
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('mousedown', handleMouseDown)
      document.removeEventListener('keydown', handleKeyDown)
    }
  }, [customOpen])

  // Datos
  const [activeTab, setActiveTab] = useState('control') // 'control' | 'seguimiento_citas' | 'evolucion_citas'
  const [citasTabCount, setCitasTabCount] = useState(null)
  const [evolucionTabCount, setEvolucionTabCount] = useState(null)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [autoRefresh, setAutoRefresh] = useState(false)

  // Catálogos
  const [sedesList, setSedesList] = useState([])
  const [supervisoresList, setSupervisoresList] = useState([])
  const [asesoresList, setAsesoresList] = useState([])

  // Cargar catálogos
  useEffect(() => {
    async function loadCatalogs() {
      try {
        const [resSedes, resUsers] = await Promise.all([
          api.get('/api/sedes/lookup?only_active=true').catch(() => ({ data: [] })),
          api.get('/auth/users').catch(() => ({ data: [] })),
        ])
        setSedesList(resSedes.data || [])
        const allUsers = resUsers.data || []
        setSupervisoresList(allUsers.filter((u) => u.role === 'supervisor' && u.is_active !== false))
        setAsesoresList(
          allUsers
            .filter((u) => (u.role === 'asesor' || u.role === 'supervisor') && u.is_active !== false)
            .sort((a, b) =>
              `${a.first_name || ''} ${a.last_name || ''}`.localeCompare(
                `${b.first_name || ''} ${b.last_name || ''}`,
                'es'
              )
            )
        )
      } catch (err) {
        console.error('Error cargando catálogos:', err)
      }
    }
    loadCatalogs()
  }, [])

  // Cargar métricas del dashboard de supervisión y control
  const [refreshTick, setRefreshTick] = useState(0)
  const refreshNow = () => setRefreshTick((t) => t + 1)

  useEffect(() => {
    let cancelled = false
    const run = async () => {
      setLoading(true)
      setError(null)
      try {
        const params = new URLSearchParams()
        params.append('periodo', periodo)
        if (periodo === 'custom' && fechaInicio && fechaFin) {
          params.append('fecha_inicio', fechaInicio)
          params.append('fecha_fin', fechaFin)
        }
        if (sedeId) params.append('sede_id', sedeId)
        if (supervisorId) params.append('supervisor_id', supervisorId)
        if (asesorId) params.append('asesor_id', asesorId)

        const res = await api.get(`/api/dashboard/supervision-control/resumen?${params.toString()}`)
        if (!cancelled) setData(res.data)
      } catch (err) {
        if (!cancelled) {
          setError(err.response?.data?.detail || 'No se pudo cargar el dashboard de supervisión y control.')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    run()
    return () => {
      cancelled = true
    }
  }, [periodo, fechaInicio, fechaFin, sedeId, supervisorId, asesorId, refreshTick])

  // Auto-refresco cada 30 segundos si está activo
  useEffect(() => {
    if (!autoRefresh) return undefined
    const id = setInterval(() => {
      refreshNow()
    }, 30000)
    return () => clearInterval(id)
  }, [autoRefresh])

  // Desestructuración segura de datos
  const kpis = data?.kpis_operativos || {}
  const leadsPendientes = kpis.leads_pendientes_atender || {}
  const asesoresAct = kpis.asesores_actividad || {}
  const cruzadosNoGest = kpis.leads_cruzados_no_gestionados || {}
  const llamadasAvance = kpis.avance_llamadas || {}
  const tiempoPrimerContacto = kpis.tiempo_primer_contacto || {}
  const trasladosBolsas = kpis.traslados_bolsas || {}
  const citasResumen = kpis.citas_resumen || {}
  const controlOperativo = kpis.control_operativo || {}
  const desgloseGestion = controlOperativo.desglose_gestion || {}
  const desgloseExcluidos = controlOperativo.desglose_excluidos || {}
  const distribucionHoras = data?.distribucion_horaria_llamadas || []
  const fuentesDesempeno = data?.fuentes_desempeno || []
  const equipos = data?.equipos_desempeno || []
  const asesores = useMemo(() => data?.asesores_detalle || [], [data])
  const focoCritico = data?.foco_critico || {}

  const contadoresEstadoAsesor = useMemo(() => {
    let activos = 0
    let sinActividad = 0
    let pendientes = 0
    for (const a of asesores) {
      if (a.estado_actividad === 'activo') activos += 1
      else sinActividad += 1
      if ((a.leads_pendientes || 0) > 0) pendientes += 1
    }
    return { activos, sinActividad, pendientes }
  }, [asesores])

  // Filtrado de la tabla de asesores
  const asesoresFiltrados = useMemo(() => {
    return asesores.filter((a) => {
      const matchSearch =
        !searchAsesor ||
        a.asesor_nombre.toLowerCase().includes(searchAsesor.toLowerCase()) ||
        a.asesor_email.toLowerCase().includes(searchAsesor.toLowerCase()) ||
        (a.supervisor_nombre && a.supervisor_nombre.toLowerCase().includes(searchAsesor.toLowerCase()))

      if (!matchSearch) return false

      if (filtroEstadoAsesor === 'activos') {
        return a.estado_actividad === 'activo'
      }
      if (filtroEstadoAsesor === 'inactivos') {
        return a.estado_actividad === 'sin_actividad' || a.estado_actividad === 'pausa'
      }
      if (filtroEstadoAsesor === 'pendientes') {
        return a.leads_pendientes > 0
      }
      return true
    })
  }, [asesores, searchAsesor, filtroEstadoAsesor])

  return (
    <div className="p-6 max-w-[1680px] mx-auto space-y-6 animate-fadeIn text-slate-900 dark:text-slate-100">
      {/* ─────────────────────────────────────────────────────────────
          ENCABEZADO DE ALTA DIRECCIÓN + CONTROLES
          ───────────────────────────────────────────────────────────── */}
      <div className="flex flex-col xl:flex-row xl:items-center justify-between gap-4 bg-white dark:bg-[#121a29] p-5 rounded-2xl shadow-sm border border-slate-200 dark:border-slate-800">
        <div>
          <div className="flex items-center gap-2.5">
            <span className="p-2.5 bg-[#df2029]/10 text-[#df2029] dark:bg-[#df2029]/20 dark:text-[#ff6b72] rounded-xl border border-[#df2029]/20">
              <ShieldCheck size={26} />
            </span>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-xl font-bold text-slate-900 dark:text-white">
                  Dashboard de Supervisión y Control
                </h1>
                <span className="text-[11px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-slate-900 text-white dark:bg-slate-800 dark:text-amber-400 border border-slate-700">
                  Alta Dirección
                </span>
              </div>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5 flex flex-wrap items-center gap-1.5">
                <span>Seguimiento comercial exhaustivo por equipo e individual · Visibilidad operativa en tiempo real</span>
                {data?.rango_fechas?.fecha_inicio && data?.rango_fechas?.fecha_fin && (
                  <span className="inline-flex items-center gap-1 font-semibold text-slate-700 dark:text-slate-300 bg-slate-100 dark:bg-slate-800 px-2 py-0.5 rounded-md text-[11px] border border-slate-200 dark:border-slate-700">
                    <Clock size={11} className="text-[#df2029]" />
                    {data.rango_fechas.fecha_inicio} al {data.rango_fechas.fecha_fin}
                    {data.rango_fechas.dias > 1 && ` (${data.rango_fechas.dias} días)`}
                  </span>
                )}
              </p>
            </div>
          </div>
        </div>

        {/* Filtros Operativos */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Selector de Período */}
          <div className="relative inline-flex bg-slate-100 dark:bg-slate-800/80 p-1 rounded-xl text-xs font-semibold items-center">
            {[
              { key: 'hoy', label: 'Hoy' },
              { key: 'ayer', label: 'Ayer' },
              { key: 'semana', label: 'Esta Semana' },
              { key: 'mes', label: 'Este Mes' },
              { key: '30dias', label: 'Últimos 30d' },
            ].map((p) => (
              <button
                key={p.key}
                type="button"
                onClick={() => {
                  setPeriodo(p.key)
                  setCustomOpen(false)
                }}
                className={`px-3 py-1.5 rounded-lg transition-all cursor-pointer ${
                  periodo === p.key
                    ? 'bg-white dark:bg-[#0c121d] text-[#df2029] dark:text-[#ff6b72] shadow-sm font-bold'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                }`}
              >
                {p.label}
              </button>
            ))}

            {/* Opción Personalizado con Popover */}
            <div className="relative">
              <button
                ref={customBtnRef}
                type="button"
                onClick={() => setCustomOpen((o) => !o)}
                className={`px-3 py-1.5 rounded-lg transition-all cursor-pointer flex items-center gap-1.5 ${
                  periodo === 'custom'
                    ? 'bg-white dark:bg-[#0c121d] text-[#df2029] dark:text-[#ff6b72] shadow-sm font-bold'
                    : 'text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-white'
                }`}
                title="Seleccionar rango de fechas personalizado"
              >
                <Calendar size={13} className={periodo === 'custom' ? 'text-[#df2029] dark:text-[#ff6b72]' : 'text-slate-500'} />
                <span>
                  {periodo === 'custom' && fechaInicio && fechaFin
                    ? `${fechaInicio} al ${fechaFin}`
                    : 'Personalizado'}
                </span>
              </button>

              {customOpen && (
                <div
                  ref={popoverRef}
                  className="absolute right-0 top-full mt-2 z-50 bg-white dark:bg-[#121a29] border border-slate-200 dark:border-slate-700 rounded-2xl shadow-2xl p-4 w-72 text-slate-800 dark:text-slate-100 animate-in fade-in zoom-in-95 duration-150"
                >
                  <div className="flex items-center justify-between pb-2.5 mb-3 border-b border-slate-100 dark:border-slate-800">
                    <div className="flex items-center gap-1.5">
                      <Calendar size={14} className="text-[#df2029]" />
                      <h4 className="text-xs font-bold text-slate-800 dark:text-slate-100">
                        Rango personalizado
                      </h4>
                    </div>
                    <button
                      type="button"
                      onClick={() => setCustomOpen(false)}
                      className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 p-1 rounded-lg cursor-pointer"
                    >
                      <X size={14} />
                    </button>
                  </div>

                  <div className="space-y-2.5">
                    <div>
                      <label className="block text-[11px] font-semibold text-slate-600 dark:text-slate-400 mb-1">
                        Desde:
                      </label>
                      <input
                        type="date"
                        value={draftInicio}
                        max={draftFin || undefined}
                        onChange={(e) => setDraftInicio(e.target.value)}
                        className="w-full text-xs bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 rounded-xl px-3 py-2 text-slate-800 dark:text-slate-100 outline-none focus:ring-2 focus:ring-[#df2029]/30"
                      />
                    </div>

                    <div>
                      <label className="block text-[11px] font-semibold text-slate-600 dark:text-slate-400 mb-1">
                        Hasta:
                      </label>
                      <input
                        type="date"
                        value={draftFin}
                        min={draftInicio || undefined}
                        onChange={(e) => setDraftFin(e.target.value)}
                        className="w-full text-xs bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 rounded-xl px-3 py-2 text-slate-800 dark:text-slate-100 outline-none focus:ring-2 focus:ring-[#df2029]/30"
                      />
                    </div>
                  </div>

                  <div className="flex items-center justify-end gap-2 mt-4 pt-3 border-t border-slate-100 dark:border-slate-800">
                    <button
                      type="button"
                      onClick={() => setCustomOpen(false)}
                      className="px-3 py-1.5 rounded-lg text-xs font-semibold text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-800 cursor-pointer"
                    >
                      Cancelar
                    </button>
                    <button
                      type="button"
                      disabled={!draftInicio || !draftFin || draftInicio > draftFin}
                      onClick={() => {
                        setFechaInicio(draftInicio)
                        setFechaFin(draftFin)
                        setPeriodo('custom')
                        setCustomOpen(false)
                      }}
                      className="px-3.5 py-1.5 rounded-lg text-xs font-bold text-white bg-[#df2029] hover:bg-[#c91b23] disabled:opacity-50 disabled:cursor-not-allowed shadow-sm transition-all cursor-pointer"
                    >
                      Aplicar
                    </button>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Sede */}
          <select
            value={sedeId}
            onChange={(e) => setSedeId(e.target.value)}
            className="text-xs font-medium bg-white dark:bg-[#0f1624] border border-slate-200 dark:border-slate-800 rounded-xl px-3 py-2 text-slate-700 dark:text-slate-300 outline-none focus:ring-2 focus:ring-[#df2029]/30"
          >
            <option value="">Todas las Sedes</option>
            {sedesList.map((s) => (
              <option key={s.id} value={s.id}>
                {s.nombre}
              </option>
            ))}
          </select>

          {/* Supervisor */}
          <select
            value={supervisorId}
            onChange={(e) => {
              setSupervisorId(e.target.value)
              setAsesorId('')
            }}
            aria-label="Filtrar por equipo o supervisor"
            className="text-xs font-medium bg-white dark:bg-[#0f1624] border border-slate-200 dark:border-slate-800 rounded-xl px-3 py-2 text-slate-700 dark:text-slate-300 outline-none focus:ring-2 focus:ring-[#df2029]/30"
          >
            <option value="">Todos los Equipos</option>
            {supervisoresList.map((sup) => (
              <option key={sup.id} value={sup.id}>
                {sup.first_name} {sup.last_name}
              </option>
            ))}
          </select>

          {/* Asesor / Supervisor */}
          <select
            value={asesorId}
            onChange={(e) => setAsesorId(e.target.value)}
            aria-label="Filtrar por asesor o supervisor"
            className="text-xs font-medium bg-white dark:bg-[#0f1624] border border-slate-200 dark:border-slate-800 rounded-xl px-3 py-2 text-slate-700 dark:text-slate-300 outline-none focus:ring-2 focus:ring-[#df2029]/30"
          >
            <option value="">Todos (Asesores y Sup.)</option>
            {asesoresList.map((as) => (
              <option key={as.id} value={as.id}>
                {as.first_name} {as.last_name}{as.role === 'supervisor' ? ' (Supervisor)' : ''}
              </option>
            ))}
          </select>

          {/* Toggle Auto-Refresh */}
          <button
            type="button"
            onClick={() => setAutoRefresh(!autoRefresh)}
            className={`px-3 py-1.5 rounded-xl text-xs font-semibold flex items-center gap-1.5 border transition-all cursor-pointer ${
              autoRefresh
                ? 'bg-emerald-50 text-emerald-700 border-emerald-300 dark:bg-emerald-950/50 dark:text-emerald-300 dark:border-emerald-800'
                : 'bg-white dark:bg-[#0f1624] text-slate-600 dark:text-slate-400 border-slate-200 dark:border-slate-800'
            }`}
            title="Actualización automática cada 30 segundos"
          >
            <Zap size={13} className={autoRefresh ? 'animate-pulse text-emerald-500' : ''} />
            <span>{autoRefresh ? 'En vivo (30s)' : 'Auto-refresco'}</span>
          </button>

          {/* Botón Refrescar */}
          <button
            type="button"
            onClick={refreshNow}
            disabled={loading}
            className="p-2 bg-white dark:bg-[#0f1624] hover:bg-slate-100 dark:hover:bg-slate-800 border border-slate-200 dark:border-slate-800 text-slate-600 dark:text-slate-300 rounded-xl transition-all cursor-pointer disabled:opacity-50"
            title="Actualizar datos ahora"
          >
            <RefreshCw size={16} className={loading ? 'animate-spin text-[#df2029]' : ''} />
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 p-4 rounded-xl text-sm flex items-center gap-2">
          <AlertTriangle size={18} />
          <span>{error}</span>
        </div>
      )}

      {/* ─────────────────────────────────────────────────────────────
          PESTAÑAS PRINCIPALES DE SUPERVISIÓN Y CONTROL
          ───────────────────────────────────────────────────────────── */}
      <div className="flex items-center gap-2 border-b border-slate-200 dark:border-slate-800 pb-1">
        <button
          type="button"
          onClick={() => setActiveTab('control')}
          className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer ${
            activeTab === 'control'
              ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900 shadow-sm'
              : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'
          }`}
        >
          <ShieldCheck size={15} />
          <span>Control Operativo</span>
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('seguimiento_citas')}
          className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer ${
            activeTab === 'seguimiento_citas'
              ? 'bg-indigo-600 text-white shadow-sm'
              : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'
          }`}
        >
          <Calendar size={15} />
          <span>Seguimiento a Citas</span>
          {citasTabCount !== null && (
            <span
              className={`px-1.5 py-0.5 rounded-full text-[10px] font-extrabold ${
                activeTab === 'seguimiento_citas'
                  ? 'bg-white/20 text-white'
                  : 'bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300'
              }`}
            >
              {citasTabCount}
            </span>
          )}
        </button>

        <button
          type="button"
          onClick={() => setActiveTab('evolucion_citas')}
          className={`inline-flex items-center gap-2 px-4 py-2 rounded-xl text-xs font-bold transition-all cursor-pointer ${
            activeTab === 'evolucion_citas'
              ? 'bg-purple-600 text-white shadow-sm'
              : 'text-slate-600 dark:text-slate-400 hover:bg-slate-100 dark:hover:bg-slate-800'
          }`}
        >
          <TrendingUp size={15} />
          <span>Evolución de Citas (Cohortes)</span>
          {evolucionTabCount !== null && (
            <span
              className={`px-1.5 py-0.5 rounded-full text-[10px] font-extrabold ${
                activeTab === 'evolucion_citas'
                  ? 'bg-white/20 text-white'
                  : 'bg-purple-100 text-purple-700 dark:bg-purple-950 dark:text-purple-300'
              }`}
            >
              {evolucionTabCount} recup.
            </span>
          )}
        </button>
      </div>

      {activeTab === 'seguimiento_citas' ? (
        <SeguimientoCitasTab
          periodo={periodo}
          fechaInicio={fechaInicio}
          fechaFin={fechaFin}
          sedeId={sedeId}
          supervisorId={supervisorId}
          asesorId={asesorId}
          refreshTick={refreshTick}
          onCountChange={setCitasTabCount}
        />
      ) : activeTab === 'evolucion_citas' ? (
        <EvolucionCitasTab
          periodo={periodo}
          fechaInicio={fechaInicio}
          fechaFin={fechaFin}
          sedeId={sedeId}
          supervisorId={supervisorId}
          asesorId={asesorId}
          refreshTick={refreshTick}
          onCountChange={setEvolucionTabCount}
        />
      ) : (
        <>

      {/* ─────────────────────────────────────────────────────────────
          BLOQUE 1: VISIBILIDAD OPERATIVA INMEDIATA (4 PILARES)
          ───────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {/* PILAR 1: LEADS PENDIENTES POR ATENDER */}
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm relative overflow-hidden">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
              Leads Pendientes por Atender
            </span>
            <span
              className={`p-2 rounded-xl ${
                leadsPendientes.criticos_gt_15m > 0
                  ? 'bg-red-50 text-red-600 dark:bg-red-950/60 dark:text-red-400'
                  : 'bg-emerald-50 text-emerald-600 dark:bg-emerald-950/60 dark:text-emerald-400'
              }`}
            >
              <Clock size={20} />
            </span>
          </div>

          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-slate-900 dark:text-white">
              {leadsPendientes.total_pendientes ?? 0}
            </span>
            <span className="text-xs text-slate-500">sin gestión inicial</span>
          </div>

          <div className="mt-3 pt-3 border-t border-slate-100 dark:border-slate-800/80 space-y-1 text-xs">
            <div className="flex items-center justify-between">
              <span className="text-slate-500">Críticos &gt; 15 min:</span>
              <span
                className={`font-bold ${
                  leadsPendientes.criticos_gt_15m > 0 ? 'text-red-600 dark:text-red-400' : 'text-slate-600 dark:text-slate-400'
                }`}
              >
                {leadsPendientes.criticos_gt_15m ?? 0}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-500">Sin atender &gt; 2 horas:</span>
              <span
                className={`font-bold ${
                  leadsPendientes.criticos_gt_2h > 0 ? 'text-rose-700 dark:text-rose-400' : 'text-slate-600 dark:text-slate-400'
                }`}
              >
                {leadsPendientes.criticos_gt_2h ?? 0}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-500">Sin asesor (huérfanos):</span>
              <span
                className={`font-bold ${
                  leadsPendientes.sin_asignar_huerfanos > 0 ? 'text-amber-600 dark:text-amber-400' : 'text-slate-600 dark:text-slate-400'
                }`}
              >
                {leadsPendientes.sin_asignar_huerfanos ?? 0}
              </span>
            </div>
          </div>
        </div>

        {/* PILAR 2: ASESORES SIN ACTIVIDAD */}
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm relative overflow-hidden">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
              Asesores Sin Actividad
            </span>
            <span
              className={`p-2 rounded-xl ${
                asesoresAct.sin_actividad_hoy > 0
                  ? 'bg-amber-50 text-amber-600 dark:bg-amber-950/60 dark:text-amber-400'
                  : 'bg-emerald-50 text-emerald-600 dark:bg-emerald-950/60 dark:text-emerald-400'
              }`}
            >
              <UserX size={20} />
            </span>
          </div>

          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-amber-600 dark:text-amber-400">
              {asesoresAct.sin_actividad_hoy ?? 0}
            </span>
            <span className="text-xs text-slate-500">
              de {asesoresAct.total_asesores ?? 0} asesores totales
            </span>
          </div>

          <div className="mt-3 pt-3 border-t border-slate-100 dark:border-slate-800/80 space-y-1 text-xs">
            <div className="flex items-center justify-between">
              <span className="text-slate-500">Asesores activos hoy:</span>
              <span className="font-bold text-emerald-600 dark:text-emerald-400">
                {asesoresAct.activos_hoy ?? 0}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-500">Inactivos &gt; 2 horas:</span>
              <span className="font-bold text-amber-600 dark:text-amber-400">
                {asesoresAct.inactivos_gt_2h ?? 0}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-500">Tasa de activación:</span>
              <span className="font-bold text-slate-700 dark:text-slate-300">
                {asesoresAct.total_asesores > 0
                  ? `${Math.round(((asesoresAct.activos_hoy || 0) / asesoresAct.total_asesores) * 100)}%`
                  : '0%'}
              </span>
            </div>
          </div>
        </div>

        {/* PILAR 3: LEADS CRUZADOS O NO GESTIONADOS */}
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm relative overflow-hidden">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
              Cruzados y No Gestionados
            </span>
            <span className="p-2 rounded-xl bg-purple-50 text-purple-600 dark:bg-purple-950/60 dark:text-purple-400">
              <Layers size={20} />
            </span>
          </div>

          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-slate-900 dark:text-white">
              {cruzadosNoGest.no_gestionados_gt_24h ?? 0}
            </span>
            <span className="text-xs text-slate-500">&gt; 24h sin gestión</span>
          </div>

          <div className="mt-3 pt-3 border-t border-slate-100 dark:border-slate-800/80 space-y-1 text-xs">
            <div className="flex items-center justify-between">
              <span className="text-slate-500">Leads cruzados / duplicados:</span>
              <span
                className={`font-bold ${
                  cruzadosNoGest.total_leads_cruzados > 0
                    ? 'text-purple-600 dark:text-purple-400'
                    : 'text-slate-600 dark:text-slate-400'
                }`}
              >
                {cruzadosNoGest.total_leads_cruzados ?? 0}
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-500">Números compartidos:</span>
              <span className="font-bold text-slate-700 dark:text-slate-300">
                {cruzadosNoGest.telefonos_cruzados ?? 0} teléfonos
              </span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-slate-500">Candidatos a revisión:</span>
              <span className="font-bold text-indigo-600 dark:text-indigo-400">
                {(cruzadosNoGest.no_gestionados_gt_24h || 0) + (cruzadosNoGest.total_leads_cruzados || 0)}
              </span>
            </div>
          </div>
        </div>

        {/* PILAR 4: AVANCE DIARIO DE LLAMADAS VS LEADS ÚNICOS */}
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm relative overflow-hidden">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
              Llamadas vs Leads Únicos
            </span>
            <span style={{ backgroundColor: 'rgba(223, 32, 41, 0.1)', color: '#df2029' }} className="p-2 rounded-xl">
              <PhoneCall size={20} />
            </span>
          </div>

          <div className="mt-3 flex items-baseline gap-2 flex-wrap">
            <span className="text-3xl font-extrabold text-[#df2029]">
              {llamadasAvance.total_llamadas_y_wa ?? llamadasAvance.total_llamadas ?? 0}
            </span>
            <span className="text-xs text-slate-500">
              {llamadasAvance.total_llamadas ?? 0} app
              {(llamadasAvance.llamadas_manuales_periodo || 0) > 0 ? ` · ${llamadasAvance.llamadas_manuales_periodo} man.` : ''}
              {(llamadasAvance.whatsapp_periodo || 0) > 0 ? ` · ${llamadasAvance.whatsapp_periodo} WA` : ''}
              {` (${llamadasAvance.contestadas ?? 0} contestadas)`}
            </span>
          </div>

          <div className="mt-2 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-indigo-50 dark:bg-indigo-950/50 border border-indigo-200/70 dark:border-indigo-900/70 text-[11px] font-bold text-indigo-700 dark:text-indigo-300">
            <span>{llamadasAvance.leads_unicos_contactados ?? 0} leads únicos contactados</span>
            <span className="text-indigo-400">·</span>
            <span className="font-medium">{llamadasAvance.promedio_intentos_por_lead ?? 0} int/lead</span>
          </div>

          {/* Barra de progreso frente a meta comercial */}
          <div className="mt-3 pt-3 border-t border-slate-100 dark:border-slate-800/80 space-y-1.5 text-xs">
            <div className="flex items-center justify-between">
              <span className="text-slate-500">Meta comercial equipo:</span>
              <span className="font-bold text-slate-700 dark:text-slate-300">
                {llamadasAvance.meta_diaria_estimada ?? 0} ({llamadasAvance.porcentaje_cumplimiento ?? 0}%)
              </span>
            </div>
            <div className="w-full bg-slate-100 dark:bg-slate-800 h-2 rounded-full overflow-hidden">
              <div
                style={{
                  width: `${Math.min(100, Math.max(0, llamadasAvance.porcentaje_cumplimiento || 0))}%`,
                  backgroundColor: '#df2029',
                }}
                className="h-full rounded-full transition-all duration-500"
              />
            </div>
            <div className="flex items-center justify-between text-[11px] text-slate-400">
              <span>Únicos llamados: {llamadasAvance.leads_unicos_llamados ?? 0}</span>
              <span>Prom: {formatSegundos(llamadasAvance.duracion_promedio_segundos || 0)}</span>
            </div>
          </div>
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          BLOQUE 1A: TIEMPOS DE CONTACTO, TRASLADOS Y PROMEDIOS DEL PERÍODO
          ───────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {/* Tiempo al 1er Contacto */}
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
              Tiempo al 1er Contacto
            </span>
            <span className="p-2 rounded-xl bg-sky-50 text-sky-600 dark:bg-sky-950/60 dark:text-sky-400">
              <Clock size={18} />
            </span>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-2xl font-extrabold text-sky-600 dark:text-sky-400">
              {formatMinutos(tiempoPrimerContacto.tiempo_promedio_min)}
            </span>
            <span className="text-xs text-slate-500">promedio</span>
          </div>
          <div className="mt-2 pt-2 border-t border-slate-100 dark:border-slate-800/80 flex items-center justify-between text-[11px] text-slate-500">
            <span>
              Mediana: <strong className="text-slate-700 dark:text-slate-300">{formatMinutos(tiempoPrimerContacto.tiempo_mediana_min)}</strong>
            </span>
            <span>
              {tiempoPrimerContacto.con_primer_contacto ?? 0}/{tiempoPrimerContacto.leads_periodo ?? 0} leads
            </span>
          </div>
        </div>

        {/* Leads Trasladados entre Bolsas (Reasignaciones entre asesores/equipos) */}
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
              Leads Trasladados
            </span>
            <span className="p-2 rounded-xl bg-violet-50 text-violet-600 dark:bg-violet-950/60 dark:text-violet-400">
              <ArrowRightLeft size={18} />
            </span>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-2xl font-extrabold text-violet-600 dark:text-violet-400">
              {trasladosBolsas.total_traslados ?? 0}
            </span>
            <span className="text-xs text-slate-500">
              reasignaciones ({trasladosBolsas.leads_unicos_trasladados ?? 0} leads)
            </span>
          </div>
          <div className="mt-2 pt-2 border-t border-slate-100 dark:border-slate-800/80 flex items-center justify-between text-[11px] text-slate-500">
            <span>
              Entre equipos: <strong className="text-slate-700 dark:text-slate-300">{trasladosBolsas.entre_equipos ?? 0}</strong>
            </span>
            <span>
              Mismo eq.: <strong className="text-slate-700 dark:text-slate-300">{trasladosBolsas.mismo_equipo ?? 0}</strong>
            </span>
          </div>
        </div>

        {/* Tiempo Promedio de Llamada */}
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
              Tiempo Prom. de Llamada
            </span>
            <span className="p-2 rounded-xl bg-emerald-50 text-emerald-600 dark:bg-emerald-950/60 dark:text-emerald-400">
              <PhoneCall size={18} />
            </span>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-2xl font-extrabold text-emerald-600 dark:text-emerald-400">
              {formatSegundos(llamadasAvance.duracion_promedio_segundos || 0)}
            </span>
            <span className="text-xs text-slate-500">por llamada contestada</span>
          </div>
          <div className="mt-2 pt-2 border-t border-slate-100 dark:border-slate-800/80 flex items-center justify-between text-[11px] text-slate-500">
            <span>
              Contestadas: <strong className="text-slate-700 dark:text-slate-300">{llamadasAvance.contestadas ?? 0}</strong>
            </span>
            <span>
              Total: <strong className="text-slate-700 dark:text-slate-300">{Math.round((llamadasAvance.duracion_total_segundos || 0) / 60)} min</strong>
            </span>
          </div>
        </div>

        {/* Llamadas Promedio por Lead */}
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
              Llamadas Prom. por Lead
            </span>
            <span className="p-2 rounded-xl bg-amber-50 text-amber-600 dark:bg-amber-950/60 dark:text-amber-400">
              <Layers size={18} />
            </span>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-2xl font-extrabold text-amber-600 dark:text-amber-400">
              {llamadasAvance.llamadas_promedio_por_lead ?? 0}
            </span>
            <span className="text-xs text-slate-500">llamadas / lead del período</span>
          </div>
          <div className="mt-2 pt-2 border-t border-slate-100 dark:border-slate-800/80 flex items-center justify-between text-[11px] text-slate-500">
            <span>
              App + manuales: <strong className="text-slate-700 dark:text-slate-300">{llamadasAvance.total_llamadas_incl_manuales ?? 0}</strong>
            </span>
            <span>
              Leads: <strong className="text-slate-700 dark:text-slate-300">{tiempoPrimerContacto.leads_periodo ?? 0}</strong>
            </span>
          </div>
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          BLOQUE 1B: CONTROL OPERATIVO — PRIMERAS CITAS Y LEADS EN GESTIÓN
          ───────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 xl:grid-cols-12 gap-4">
        {/* Card A: Diferenciación de Primeras Citas vs Reprogramaciones / Previas */}
        <div className="xl:col-span-5 bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm flex flex-col justify-between gap-4">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <span className="p-2.5 rounded-xl bg-emerald-50 text-emerald-600 dark:bg-emerald-950/60 dark:text-emerald-400">
                <Calendar size={20} />
              </span>
              <div>
                <h2 className="text-sm font-bold text-slate-900 dark:text-white">
                  Agendados (Primeras Citas) vs Reprogramaciones
                </h2>
                <p className="text-xs text-slate-500">
                  No contabiliza como nueva cita a leads ya agendados en meses o días previos
                </p>
              </div>
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <div className="p-3.5 rounded-xl bg-emerald-50/70 dark:bg-emerald-950/25 border border-emerald-200/80 dark:border-emerald-900/60">
              <span className="text-[11px] font-bold uppercase tracking-wider text-emerald-700 dark:text-emerald-400 block">
                Agendados (1ra vez)
              </span>
              <div className="mt-1 flex items-baseline gap-1.5">
                <span className="text-3xl font-extrabold text-emerald-700 dark:text-emerald-300">
                  {citasResumen.agendados_primeras_citas ?? 0}
                </span>
                <span className="text-xs text-emerald-600/80 dark:text-emerald-400/80">
                  leads nuevos
                </span>
              </div>
            </div>

            <div className="p-3.5 rounded-xl bg-amber-50/70 dark:bg-amber-950/25 border border-amber-200/80 dark:border-amber-900/60">
              <span className="text-[11px] font-bold uppercase tracking-wider text-amber-700 dark:text-amber-400 block">
                Reprogramaciones / Previas
              </span>
              <div className="mt-1 flex items-baseline gap-1.5">
                <span className="text-3xl font-extrabold text-amber-700 dark:text-amber-300">
                  {citasResumen.citas_reprogramadas_previas ?? 0}
                </span>
                <span className="text-xs text-amber-600/80 dark:text-amber-400/80">
                  ({citasResumen.leads_con_reprogramacion_previa ?? 0} leads)
                </span>
              </div>
            </div>
          </div>

          <div className="flex items-center justify-between text-[11px] text-slate-500 pt-2 border-t border-slate-100 dark:border-slate-800">
            <span>Total citas activas del período: <strong className="text-slate-700 dark:text-slate-200">{citasResumen.total_citas_activas_periodo ?? 0}</strong></span>
            <span>Canceladas: <strong className="text-slate-700 dark:text-slate-200">{citasResumen.citas_canceladas ?? 0}</strong></span>
          </div>
        </div>

        {/* Card B: Leads en Gestión vs Exclusiones (Criterio Operativo Exacto) */}
        <div className="xl:col-span-7 bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <div>
              <h2 className="text-sm font-bold text-slate-900 dark:text-white">
                Control Operativo: Leads en Gestión
              </h2>
              <p className="text-xs text-slate-500">
                Suma únicamente estados de gestión operativa y deja fuera nuevos, erróneos, cierres, perdidos y citas existentes
              </p>
            </div>
            <div className="flex items-baseline gap-2 shrink-0 bg-indigo-50 dark:bg-indigo-950/50 border border-indigo-200/80 dark:border-indigo-900 px-3.5 py-2 rounded-xl">
              <span className="text-2xl font-extrabold text-indigo-700 dark:text-indigo-300">
                {controlOperativo.leads_en_gestion ?? 0}
              </span>
              <span className="text-xs font-semibold text-indigo-600 dark:text-indigo-400">
                en gestión / {controlOperativo.total_leads_activos ?? 0} activos
              </span>
            </div>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
            {/* Incluidos */}
            <div className="p-3 rounded-xl bg-emerald-50/50 dark:bg-emerald-950/20 border border-emerald-200/70 dark:border-emerald-900/50 space-y-2">
              <div className="flex items-center justify-between font-bold text-emerald-800 dark:text-emerald-300">
                <span>Estados incluidos en Gestión</span>
                <span>{controlOperativo.leads_en_gestion ?? 0}</span>
              </div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
                <div className="flex justify-between">
                  <span className="text-slate-600 dark:text-slate-400">No contesta 1, 2 y 3</span>
                  <strong className="text-slate-900 dark:text-slate-100">{desgloseGestion.no_contesta_123 ?? 0}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-600 dark:text-slate-400">Bolsa de reciclaje</span>
                  <strong className="text-slate-900 dark:text-slate-100">{desgloseGestion.bolsa_reciclaje ?? 0}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-600 dark:text-slate-400">Contactado</span>
                  <strong className="text-slate-900 dark:text-slate-100">{desgloseGestion.contactado ?? 0}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-600 dark:text-slate-400">Oportunidad futura</span>
                  <strong className="text-slate-900 dark:text-slate-100">{desgloseGestion.oportunidad_futura ?? 0}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-600 dark:text-slate-400">En seguimiento</span>
                  <strong className="text-slate-900 dark:text-slate-100">{desgloseGestion.en_seguimiento ?? 0}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-600 dark:text-slate-400">Nuevas citas (1ra vez)</span>
                  <strong className="text-emerald-700 dark:text-emerald-300">{desgloseGestion.nuevas_citas ?? 0}</strong>
                </div>
              </div>
            </div>

            {/* Excluidos */}
            <div className="p-3 rounded-xl bg-slate-50 dark:bg-[#0c121d] border border-slate-200/80 dark:border-slate-800 space-y-2">
              <div className="flex items-center justify-between font-bold text-slate-700 dark:text-slate-300">
                <span>Estados excluidos del control</span>
                <span>{controlOperativo.leads_excluidos ?? 0}</span>
              </div>
              <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[11px]">
                <div className="flex justify-between">
                  <span className="text-slate-500">Nuevos</span>
                  <strong className="text-slate-700 dark:text-slate-300">{desgloseExcluidos.nuevos ?? 0}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Equivoc. / Inexist.</span>
                  <strong className="text-slate-700 dark:text-slate-300">{desgloseExcluidos.equivocados_inexistentes ?? 0}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Ventas / Separaciones</span>
                  <strong className="text-slate-700 dark:text-slate-300">{desgloseExcluidos.matriculas ?? 0}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Perdidos</span>
                  <strong className="text-slate-700 dark:text-slate-300">{desgloseExcluidos.perdidos ?? 0}</strong>
                </div>
                <div className="flex justify-between">
                  <span className="text-slate-500">Citas ya existentes</span>
                  <strong className="text-slate-700 dark:text-slate-300">{desgloseExcluidos.citas_ya_existentes ?? 0}</strong>
                </div>
                {(desgloseExcluidos.otros || 0) > 0 && (
                  <div className="flex justify-between">
                    <span className="text-slate-500">Otros estados</span>
                    <strong className="text-slate-700 dark:text-slate-300">{desgloseExcluidos.otros}</strong>
                  </div>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          BLOQUE 2: RITMO COMERCIAL (DISTRIBUCIÓN HORARIA DE LLAMADAS)
          ───────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Gráfico de Avance Horario de Llamadas */}
        <div className="xl:col-span-2 bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <span className="p-2 bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400 rounded-xl">
                <BarChart3 size={18} />
              </span>
              <div>
                <h2 className="text-sm font-bold text-slate-900 dark:text-white">
                  Ritmo y Actividad Horaria de Llamadas (08:00 – 20:00)
                </h2>
                <p className="text-xs text-slate-500">
                  Monitoreo de horas pico y volumen de llamadas contestadas vs realizadas
                </p>
              </div>
            </div>
            <span className="text-xs font-semibold px-2.5 py-1 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300">
              {llamadasAvance.total_llamadas || 0} llamadas en el período
            </span>
          </div>

          <div className="h-64 w-full min-w-0">
            <ResponsiveContainer width="100%" height={256} minWidth={0}>
              <BarChart data={distribucionHoras} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" opacity={0.15} />
                <XAxis dataKey="hora_label" tick={{ fontSize: 11 }} />
                <YAxis tick={{ fontSize: 11 }} />
                <Tooltip
                  formatter={(value, name) => [
                    `${value} llamadas`,
                    name === 'total' ? 'Llamadas Realizadas' : 'Llamadas Contestadas',
                  ]}
                  contentStyle={{ backgroundColor: '#0f172a', borderRadius: '12px', color: '#fff', fontSize: '12px' }}
                />
                <Legend wrapperStyle={{ fontSize: '11px' }} />
                <Bar dataKey="total" name="Total Llamadas" fill="#6366F1" radius={[4, 4, 0, 0]} />
                <Bar dataKey="contestadas" name="Contestadas" fill="#10B981" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Resumen Comercial por Equipo de Supervisión */}
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="p-2 bg-emerald-50 dark:bg-emerald-950/60 text-emerald-600 dark:text-emerald-400 rounded-xl">
                <Users size={18} />
              </span>
              <div>
                <h2 className="text-sm font-bold text-slate-900 dark:text-white">
                  Desempeño por Equipo
                </h2>
                <p className="text-xs text-slate-500">Control por Supervisor a cargo</p>
              </div>
            </div>
            <span className="text-xs text-slate-400">{equipos.length} equipos</span>
          </div>

          <div className="space-y-3 overflow-y-auto max-h-[240px] pr-1">
            {equipos.map((eq) => (
              <div
                key={eq.supervisor_id}
                className="p-3 rounded-xl bg-slate-50 dark:bg-[#0c121d] border border-slate-200/80 dark:border-slate-800 space-y-2 text-xs"
              >
                <div className="flex items-center justify-between font-bold">
                  <span className="text-slate-800 dark:text-slate-200">{eq.supervisor_nombre}</span>
                  <span className="text-[11px] px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-300">
                    {eq.asesores_activos ?? 0}/{eq.total_asesores} operando
                  </span>
                </div>
                <div className="grid grid-cols-5 gap-1.5 text-center pt-1.5 border-t border-slate-200 dark:border-slate-800 text-[11px]">
                  <div>
                    <span className="text-slate-400 block">En Gestión</span>
                    <span className="font-bold text-slate-800 dark:text-slate-100">{eq.leads_en_gestion ?? 0}</span>
                  </div>
                  <div>
                    <span className="text-slate-400 block">Llamadas</span>
                    <span className="font-bold text-indigo-600 dark:text-indigo-400">{eq.llamadas_total ?? 0}</span>
                  </div>
                  <div>
                    <span className="text-slate-400 block">Únicos</span>
                    <span className="font-bold text-sky-600 dark:text-sky-400">{eq.leads_unicos_contactados ?? 0}</span>
                  </div>
                  <div>
                    <span className="text-slate-400 block">Agendados</span>
                    <span className="font-bold text-emerald-600 dark:text-emerald-400">{eq.agendados_primeras_citas ?? 0}</span>
                  </div>
                  <div>
                    <span className="text-slate-400 block">Cierres</span>
                    <span className="font-bold text-emerald-700 dark:text-emerald-300">{eq.matriculas ?? 0}</span>
                  </div>
                </div>
              </div>
            ))}
            {equipos.length === 0 && (
              <p className="text-xs text-slate-400 text-center py-6">No hay equipos registrados.</p>
            )}
          </div>
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          BLOQUE 2B: DESEMPEÑO POR FUENTE (1ER CONTACTO Y LLAMADAS / LEAD)
          ───────────────────────────────────────────────────────────── */}
      <div className="bg-white dark:bg-[#121a29] rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden">
        <div className="p-5 border-b border-slate-200 dark:border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <span className="p-2 bg-sky-50 dark:bg-sky-950/60 text-sky-600 dark:text-sky-400 rounded-xl">
              <Layers size={18} />
            </span>
            <div>
              <h2 className="text-sm font-bold text-slate-900 dark:text-white">
                Indicadores por Fuente del Período
              </h2>
              <p className="text-xs text-slate-500">
                Tiempo entre creación del lead y primer contacto, más llamadas promedio (app + manuales) por lead del período
              </p>
            </div>
          </div>
          <span className="text-xs text-slate-400">{fuentesDesempeno.length} fuentes</span>
        </div>

        <div className="overflow-x-auto max-h-80 overflow-y-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 dark:bg-[#0b101b] text-slate-500 font-semibold border-b border-slate-200 dark:border-slate-800 sticky top-0">
              <tr>
                <th className="py-2.5 px-4">Fuente</th>
                <th className="py-2.5 px-3 text-center">Leads Período</th>
                <th className="py-2.5 px-3 text-center">Con 1er Contacto</th>
                <th className="py-2.5 px-3 text-center">Tiempo Prom. 1er Contacto</th>
                <th className="py-2.5 px-3 text-center">Mediana 1er Contacto</th>
                <th className="py-2.5 px-3 text-center">Llamadas (App + Man.)</th>
                <th className="py-2.5 px-4 text-center">Llamadas Prom. / Lead</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60 font-medium">
              {fuentesDesempeno.map((f) => (
                <tr key={`${f.fuente_id}-${f.fuente_nombre}`} className="hover:bg-slate-50/70 dark:hover:bg-slate-800/30">
                  <td className="py-2.5 px-4 font-bold text-slate-800 dark:text-slate-200">
                    {f.fuente_nombre}
                  </td>
                  <td className="py-2.5 px-3 text-center font-bold text-slate-700 dark:text-slate-300">
                    {f.leads_periodo ?? 0}
                  </td>
                  <td className="py-2.5 px-3 text-center text-slate-600 dark:text-slate-400">
                    {f.con_primer_contacto ?? 0}
                  </td>
                  <td className="py-2.5 px-3 text-center font-bold text-sky-600 dark:text-sky-400">
                    {(f.con_primer_contacto || 0) > 0 ? formatMinutos(f.tiempo_promedio_min) : '—'}
                  </td>
                  <td className="py-2.5 px-3 text-center font-semibold text-slate-700 dark:text-slate-300">
                    {(f.con_primer_contacto || 0) > 0 ? formatMinutos(f.tiempo_mediana_min) : '—'}
                  </td>
                  <td className="py-2.5 px-3 text-center">
                    <span className="font-bold text-indigo-600 dark:text-indigo-400">{f.llamadas_totales ?? 0}</span>
                    <span className="text-[10px] text-slate-400 ml-1">
                      ({f.llamadas_app ?? 0} app · {f.llamadas_manuales ?? 0} man.)
                    </span>
                  </td>
                  <td className="py-2.5 px-4 text-center font-extrabold text-amber-600 dark:text-amber-400">
                    {(f.leads_periodo || 0) > 0 ? (f.llamadas_promedio_por_lead ?? 0) : '—'}
                  </td>
                </tr>
              ))}
              {fuentesDesempeno.length === 0 && (
                <tr>
                  <td colSpan={7} className="py-6 text-center text-slate-400">
                    Sin fuentes registradas para el período seleccionado.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          BLOQUE 3: TABLA DE SEGUIMIENTO EXHAUSTIVO POR ASESOR INDIVIDUAL
          ───────────────────────────────────────────────────────────── */}
      <div className="bg-white dark:bg-[#121a29] rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden">
        <div className="p-5 border-b border-slate-200 dark:border-slate-800 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <span className="p-2 bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400 rounded-xl">
                <UserCheck size={18} />
              </span>
              <div>
                <h2 className="text-sm font-bold text-slate-900 dark:text-white">
                  Seguimiento Exhaustivo Individual (Asesores y Supervisores)
                </h2>
                <p className="text-xs text-slate-500">
                  Actividad comercial, leads pendientes, llamadas y estado de conexión
                </p>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            {/* Buscador */}
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={searchAsesor}
                onChange={(e) => setSearchAsesor(e.target.value)}
                placeholder="Buscar asesor o supervisor..."
                className="pl-8 pr-3 py-1.5 text-xs rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-[#0c121d] text-slate-800 dark:text-slate-100 outline-none focus:ring-2 focus:ring-[#df2029]/30"
              />
            </div>

            {/* Filtros de Estado */}
            <div className="inline-flex bg-slate-100 dark:bg-slate-800/80 p-0.5 rounded-xl text-xs font-semibold">
              <button
                type="button"
                onClick={() => setFiltroEstadoAsesor('todos')}
                className={`px-2.5 py-1 rounded-lg transition-colors cursor-pointer ${
                  filtroEstadoAsesor === 'todos'
                    ? 'bg-white dark:bg-[#0c121d] text-slate-900 dark:text-white shadow-xs'
                    : 'text-slate-500'
                }`}
              >
                Todos ({asesores.length})
              </button>
              <button
                type="button"
                onClick={() => setFiltroEstadoAsesor('activos')}
                className={`px-2.5 py-1 rounded-lg transition-colors cursor-pointer ${
                  filtroEstadoAsesor === 'activos'
                    ? 'bg-white dark:bg-[#0c121d] text-emerald-600 shadow-xs'
                    : 'text-slate-500'
                }`}
              >
                Operando ({contadoresEstadoAsesor.activos})
              </button>
              <button
                type="button"
                onClick={() => setFiltroEstadoAsesor('inactivos')}
                className={`px-2.5 py-1 rounded-lg transition-colors cursor-pointer ${
                  filtroEstadoAsesor === 'inactivos'
                    ? 'bg-white dark:bg-[#0c121d] text-red-600 shadow-xs'
                    : 'text-slate-500'
                }`}
              >
                Sin gestión ({contadoresEstadoAsesor.sinActividad})
              </button>
              <button
                type="button"
                onClick={() => setFiltroEstadoAsesor('pendientes')}
                className={`px-2.5 py-1 rounded-lg transition-colors cursor-pointer ${
                  filtroEstadoAsesor === 'pendientes'
                    ? 'bg-white dark:bg-[#0c121d] text-amber-600 shadow-xs'
                    : 'text-slate-500'
                }`}
              >
                Con Pendientes ({contadoresEstadoAsesor.pendientes})
              </button>
            </div>
          </div>
        </div>

        {/* Tabla Detallada */}
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 dark:bg-[#0b101b] text-slate-500 font-semibold border-b border-slate-200 dark:border-slate-800">
              <tr>
                <th className="py-3 px-4">Asesor / Supervisor</th>
                <th className="py-3 px-3">Equipo / Sede</th>
                <th className="py-3 px-3 text-center">Estado Actividad</th>
                <th className="py-3 px-3 text-center">Última Gestión</th>
                <th className="py-3 px-3 text-center">En Gestión</th>
                <th className="py-3 px-3 text-center">Pendientes</th>
                <th className="py-3 px-3 text-center">&gt; 24h Sin Gestión</th>
                <th className="py-3 px-3 text-center">{periodo === 'hoy' ? 'Llamadas Hoy' : 'Llamadas'}</th>
                <th className="py-3 px-3 text-center">Agendados</th>
                <th className="py-3 px-3 text-center">Leads Únicos</th>
                <th className="py-3 px-3 text-center">Contestadas</th>
                <th className="py-3 px-3 text-center">Minutos</th>
                <th className="py-3 px-3 text-center">Prom. Llamada</th>
                <th className="py-3 px-3 text-center">Llam. / Lead</th>
                <th className="py-3 px-3 text-center">Ventas / Cierres</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60 font-medium">
              {asesoresFiltrados.map((a) => {
                const esActivo = a.estado_actividad === 'activo'
                const esPausa = a.estado_actividad === 'pausa'

                return (
                  <tr
                    key={a.asesor_id}
                    className="hover:bg-slate-50/70 dark:hover:bg-slate-800/30 transition-colors"
                  >
                    <td className="py-3 px-4">
                      <div className="font-bold text-slate-900 dark:text-white flex items-center gap-1.5 flex-wrap">
                        <span
                          className={`w-2 h-2 rounded-full ${
                            esActivo ? 'bg-emerald-500' : esPausa ? 'bg-amber-500' : 'bg-red-500'
                          }`}
                        />
                        <span>{a.asesor_nombre}</span>
                        {a.rol === 'supervisor' && (
                          <span className="px-1.5 py-0.5 rounded bg-indigo-50 text-indigo-700 border border-indigo-200 dark:bg-indigo-950/60 dark:text-indigo-300 dark:border-indigo-800 text-[10px] font-bold">
                            Supervisor
                          </span>
                        )}
                      </div>
                      <div className="text-[11px] text-slate-400">{a.asesor_email}</div>
                    </td>

                    <td className="py-3 px-3 text-slate-600 dark:text-slate-400">
                      <div className="font-semibold text-slate-700 dark:text-slate-300">
                        {a.supervisor_nombre || (a.rol === 'supervisor' ? 'Supervisor de equipo' : 'Sin supervisor')}
                      </div>
                      <div className="text-[10px] text-slate-400">{a.sede_nombre}</div>
                    </td>

                    <td className="py-3 px-3 text-center">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-bold ${
                          esActivo
                            ? 'bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-950/60 dark:text-emerald-400 dark:border-emerald-800'
                            : esPausa
                            ? 'bg-amber-50 text-amber-700 border border-amber-200 dark:bg-amber-950/60 dark:text-amber-400 dark:border-amber-800'
                            : 'bg-red-50 text-red-700 border border-red-200 dark:bg-red-950/60 dark:text-red-400 dark:border-red-800'
                        }`}
                      >
                        {esActivo ? 'Operando' : esPausa ? 'En pausa' : 'Sin gestión'}
                      </span>
                    </td>

                    <td className="py-3 px-3 text-center text-[11px]">
                      {a.minutos_inactivo !== null ? (
                        <span
                          className={`font-semibold ${
                            a.minutos_inactivo <= 30
                              ? 'text-emerald-600 dark:text-emerald-400'
                              : a.minutos_inactivo <= 120
                              ? 'text-amber-600 dark:text-amber-400'
                              : 'text-red-600 dark:text-red-400'
                          }`}
                        >
                          hace {a.minutos_inactivo < 60 ? `${a.minutos_inactivo}m` : `${Math.floor(a.minutos_inactivo / 60)}h ${a.minutos_inactivo % 60}m`}
                        </span>
                      ) : (
                        <span className="text-slate-400">Sin registro</span>
                      )}
                    </td>

                    <td className="py-3 px-3 text-center font-bold text-slate-800 dark:text-slate-200">
                      <div>{a.leads_en_gestion ?? 0}</div>
                      <div className="text-[10px] font-normal text-slate-400">
                        +{a.leads_asignados_periodo ?? 0} asig.
                      </div>
                    </td>

                    <td className="py-3 px-3 text-center">
                      {a.leads_pendientes > 0 ? (
                        <span className="px-2 py-0.5 rounded-full bg-red-100 text-red-700 dark:bg-red-950/60 dark:text-red-300 font-bold">
                          {a.leads_pendientes}
                        </span>
                      ) : (
                        <span className="text-slate-400">0</span>
                      )}
                    </td>

                    <td className="py-3 px-3 text-center">
                      {a.no_gestionados_24h > 0 ? (
                        <span className="px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300 font-bold">
                          {a.no_gestionados_24h}
                        </span>
                      ) : (
                        <span className="text-slate-400">0</span>
                      )}
                    </td>

                    <td className="py-3 px-3 text-center font-bold text-indigo-600 dark:text-indigo-400">
                      <div>
                        {a.gestiones_periodo ?? ((a.llamadas_periodo ?? 0) + (a.contactos_periodo ?? 0))}
                      </div>
                      {(a.gestiones_periodo ?? ((a.llamadas_periodo ?? 0) + (a.contactos_periodo ?? 0))) > 0 && (
                        <div className="text-[10px] font-normal text-slate-400 whitespace-nowrap">
                          {[
                            `${a.llamadas_periodo ?? 0} app`,
                            (a.llamadas_manuales_periodo || 0) > 0 ? `${a.llamadas_manuales_periodo} man.` : null,
                            (a.whatsapp_periodo || 0) > 0 ? `${a.whatsapp_periodo} WA` : null,
                          ]
                            .filter(Boolean)
                            .join(' · ')}
                        </div>
                      )}
                    </td>

                    <td className="py-3 px-3 text-center font-bold text-emerald-700 dark:text-emerald-400">
                      <div>{a.agendados_primeras_citas ?? 0}</div>
                      {(a.citas_reprogramadas_previas || 0) > 0 && (
                        <div className="text-[10px] font-normal text-amber-600 dark:text-amber-400">
                          +{a.citas_reprogramadas_previas} reprog.
                        </div>
                      )}
                    </td>

                    <td className="py-3 px-3 text-center font-bold text-sky-600 dark:text-sky-400">
                      <div>{a.leads_unicos_contactados ?? 0}</div>
                      <div className="text-[10px] font-normal text-slate-400">
                        {a.leads_unicos_llamados ?? 0} llam.
                      </div>
                    </td>

                    <td className="py-3 px-3 text-center text-emerald-600 font-bold">
                      {a.llamadas_contestadas ?? 0}
                    </td>

                    <td className="py-3 px-3 text-center text-slate-700 dark:text-slate-300">
                      {a.minutos_llamadas} min
                    </td>

                    <td className="py-3 px-3 text-center font-semibold text-emerald-700 dark:text-emerald-400">
                      {formatSegundos(a.duracion_promedio_segundos || 0)}
                    </td>

                    <td className="py-3 px-3 text-center font-bold text-amber-600 dark:text-amber-400">
                      <div>{(a.leads_asignados_periodo || 0) > 0 ? (a.llamadas_promedio_por_lead ?? 0) : '—'}</div>
                      <div className="text-[10px] font-normal text-slate-400">
                        {a.llamadas_totales_periodo ?? ((a.llamadas_periodo ?? 0) + (a.llamadas_manuales_periodo ?? 0))} llam.
                      </div>
                    </td>

                    <td className="py-3 px-3 text-center font-bold text-emerald-600 dark:text-emerald-400">
                      {a.matriculas_periodo ?? 0}
                    </td>
                  </tr>
                )
              })}
              {asesoresFiltrados.length === 0 && (
                <tr>
                  <td colSpan={15} className="py-8 text-center text-slate-400">
                    No se encontraron asesores que coincidan con los filtros aplicados.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          BLOQUE 4: ACCIÓN INMEDIATA - FOCO CRÍTICO PARA ALTA DIRECCIÓN
          ───────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {/* Leads Más Urgentes Esperando Atención */}
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-red-200 dark:border-red-900/60 shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="p-2 bg-red-100 text-red-700 dark:bg-red-950/60 dark:text-red-400 rounded-xl">
                <AlertTriangle size={18} />
              </span>
              <div>
                <h3 className="text-sm font-bold text-red-950 dark:text-red-300">
                  Leads Críticos con Mayor Tiempo de Espera
                </h3>
                <p className="text-xs text-red-700/80 dark:text-red-400">
                  Leads activos que aún no han recibido ningún contacto comercial
                </p>
              </div>
            </div>
            <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-red-100 text-red-700 dark:bg-red-950 dark:text-red-300">
              Acción Prioritaria
            </span>
          </div>

          <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
            {focoCritico?.leads_urgentes?.map((l) => (
              <div
                key={l.id}
                className="p-3 rounded-xl bg-red-50/50 dark:bg-red-950/20 border border-red-100 dark:border-red-900/40 flex items-center justify-between gap-3 text-xs"
              >
                <div>
                  <div className="font-bold text-slate-900 dark:text-white flex items-center gap-2">
                    <span>{l.nombre}</span>
                    <span className="text-[10px] font-normal text-slate-400 font-mono">
                      {l.telefono}
                    </span>
                  </div>
                  <div className="text-[11px] text-slate-500 mt-0.5">
                    Asesor: <strong className="text-slate-700 dark:text-slate-300">{l.asesor_nombre || 'Sin Asignar'}</strong> · Fuente: {l.fuente_nombre}
                  </div>
                </div>

                <div className="flex items-center gap-2 shrink-0">
                  <span className="font-bold text-red-600 dark:text-red-400 px-2 py-0.5 rounded-md bg-white dark:bg-slate-800 shadow-xs">
                    {l.minutos_espera > 60
                      ? `${Math.floor(l.minutos_espera / 60)}h ${l.minutos_espera % 60}m`
                      : `${l.minutos_espera}m`}
                  </span>
                  <button
                    type="button"
                    onClick={() => navigate(`/leads/${l.id}`)}
                    className="p-1.5 rounded-lg bg-white dark:bg-slate-800 text-slate-600 hover:text-indigo-600 dark:text-slate-300 dark:hover:text-white transition-colors cursor-pointer"
                    title="Abrir lead en CRM"
                  >
                    <ExternalLink size={14} />
                  </button>
                </div>
              </div>
            ))}
            {(!focoCritico?.leads_urgentes || focoCritico.leads_urgentes.length === 0) && (
              <div className="py-8 text-center text-xs text-emerald-600 dark:text-emerald-400 flex flex-col items-center gap-1.5">
                <CheckCircle2 size={24} />
                <span>¡Excelente! No hay leads pendientes sin atender en este momento.</span>
              </div>
            )}
          </div>
        </div>

        {/* Asesores en Alerta Roja (Sin actividad hoy) */}
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-amber-200 dark:border-amber-900/60 shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="p-2 bg-amber-100 text-amber-700 dark:bg-amber-950/60 dark:text-amber-400 rounded-xl">
                <Flame size={18} />
              </span>
              <div>
                <h3 className="text-sm font-bold text-amber-950 dark:text-amber-300">
                  Asesores en Alerta de Inactividad
                </h3>
                <p className="text-xs text-amber-700/80 dark:text-amber-400">
                  Asesores sin llamadas (App o CRM) ni mensajes de WhatsApp en el período
                </p>
              </div>
            </div>
            <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300">
              {focoCritico?.asesores_sin_actividad?.length || 0} en alerta
            </span>
          </div>

          <div className="space-y-2 max-h-72 overflow-y-auto pr-1">
            {focoCritico?.asesores_sin_actividad?.map((a) => (
              <div
                key={a.asesor_id}
                className="p-3 rounded-xl bg-amber-50/50 dark:bg-amber-950/20 border border-amber-100 dark:border-amber-900/40 flex items-center justify-between gap-3 text-xs"
              >
                <div>
                  <div className="font-bold text-slate-900 dark:text-white">
                    {a.asesor_nombre}
                  </div>
                  <div className="text-[11px] text-slate-500 mt-0.5">
                    Supervisor: {a.supervisor_nombre || 'Sin asignar'} · Sede: {a.sede_nombre}
                  </div>
                </div>

                <div className="text-right shrink-0">
                  <span className="inline-block px-2 py-0.5 rounded-full bg-amber-100 dark:bg-amber-950 text-amber-800 dark:text-amber-300 font-bold text-[11px]">
                    {a.gestiones_periodo ?? 0} llam. / WA
                  </span>
                  <div className="text-[10px] text-slate-400 mt-0.5">
                    {a.leads_pendientes} pendientes · {a.leads_en_gestion ?? 0} en gestión
                  </div>
                </div>
              </div>
            ))}
            {(!focoCritico?.asesores_sin_actividad || focoCritico.asesores_sin_actividad.length === 0) && (
              <div className="py-8 text-center text-xs text-emerald-600 dark:text-emerald-400 flex flex-col items-center gap-1.5">
                <CheckCircle2 size={24} />
                <span>¡Todos los asesores se encuentran activos y gestionando llamadas hoy!</span>
              </div>
            )}
          </div>
        </div>
      </div>
        </>
      )}
    </div>
  )
}
