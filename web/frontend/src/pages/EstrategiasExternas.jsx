import React, { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Compass,
  CalendarCheck,
  Award,
  Users,
  Search,
  Download,
  RefreshCw,
  ExternalLink,
  Filter,
  ChevronLeft,
  ChevronRight,
  Info,
  CheckCircle2,
  XCircle,
  Clock,
  Sparkles,
  AlertTriangle,
} from 'lucide-react'
import api from '@/lib/api'

function formatDateTimeLima(iso) {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return '—'
    return d.toLocaleString('es-PE', {
      timeZone: 'America/Lima',
      day: '2-digit',
      month: '2-digit',
      year: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return '—'
  }
}

function formatDateLima(iso) {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return '—'
    return d.toLocaleDateString('es-PE', {
      timeZone: 'America/Lima',
      day: '2-digit',
      month: '2-digit',
      year: '2-digit',
    })
  } catch {
    return '—'
  }
}

function getConsideracionStyle(codigo) {
  switch (codigo) {
    case 'considerado_venta':
      return 'bg-emerald-100 text-emerald-800 border-emerald-300 dark:bg-emerald-950/60 dark:text-emerald-300 dark:border-emerald-800'
    case 'considerado_cita':
      return 'bg-sky-100 text-sky-800 border-sky-300 dark:bg-sky-950/60 dark:text-sky-300 dark:border-sky-800'
    case 'considerado_gestion':
      return 'bg-indigo-100 text-indigo-800 border-indigo-300 dark:bg-indigo-950/60 dark:text-indigo-300 dark:border-indigo-800'
    case 'considerado_nuevo':
      return 'bg-amber-100 text-amber-800 border-amber-300 dark:bg-amber-950/60 dark:text-amber-300 dark:border-amber-800'
    case 'excluido_invalido':
      return 'bg-rose-100 text-rose-800 border-rose-300 dark:bg-rose-950/60 dark:text-rose-300 dark:border-rose-800'
    case 'excluido_perdido':
      return 'bg-slate-200 text-slate-700 border-slate-300 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700'
    case 'excluido_bolsa':
      return 'bg-purple-100 text-purple-800 border-purple-300 dark:bg-purple-950/60 dark:text-purple-300 dark:border-purple-800'
    default:
      return 'bg-slate-100 text-slate-600 border-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:border-slate-700'
  }
}

export default function EstrategiasExternas() {
  const [resumenData, setResumenData] = useState(null)
  const [leadsData, setLeadsData] = useState({ items: [], total: 0, page: 1, pages: 1, resumen_filtrado: {} })
  const [loadingResumen, setLoadingResumen] = useState(true)
  const [loadingLeads, setLoadingLeads] = useState(true)
  const [error, setError] = useState(null)
  const [exporting, setExporting] = useState(false)

  // Filtros globales
  const [fechaDesde, setFechaDesde] = useState('')
  const [fechaHasta, setFechaHasta] = useState('')
  const [supervisorId, setSupervisorId] = useState('')
  const [asesorId, setAsesorId] = useState('')
  const [incluirWhatsapp, setIncluirWhatsapp] = useState(false)
  const [incluirSinFuente, setIncluirSinFuente] = useState(false)
  const [showCriteriosInfo, setShowCriteriosInfo] = useState(false)

  // Filtros del desglose de leads por fuente
  const [selectedFuente, setSelectedFuente] = useState('')
  const [estadoId, setEstadoId] = useState('')
  const [consideracion, setConsideracion] = useState('')
  const [soloConCita, setSoloConCita] = useState(false)
  const [soloConVenta, setSoloConVenta] = useState(false)
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(1)

  const buildCommonParams = useCallback(() => {
    const p = new URLSearchParams()
    if (fechaDesde) p.append('fecha_desde', fechaDesde)
    if (fechaHasta) p.append('fecha_hasta', fechaHasta)
    if (supervisorId) p.append('supervisor_id', supervisorId)
    if (asesorId) p.append('asesor_id', asesorId)
    if (incluirWhatsapp) p.append('incluir_whatsapp', 'true')
    if (incluirSinFuente) p.append('incluir_sin_fuente', 'true')
    return p
  }, [fechaDesde, fechaHasta, supervisorId, asesorId, incluirWhatsapp, incluirSinFuente])

  const fetchResumen = useCallback(async () => {
    setLoadingResumen(true)
    setError(null)
    try {
      const p = buildCommonParams()
      const res = await api.get(`/api/estrategias-externas/resumen?${p.toString()}`)
      setResumenData(res.data)
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo cargar el resumen de Estrategias Externas.')
    } finally {
      setLoadingResumen(false)
    }
  }, [buildCommonParams])

  const fetchLeads = useCallback(async () => {
    setLoadingLeads(true)
    try {
      const p = buildCommonParams()
      if (selectedFuente) p.append('fuente_nombre', selectedFuente)
      if (estadoId) p.append('estado_id', estadoId)
      if (consideracion) p.append('consideracion', consideracion)
      if (soloConCita) p.append('solo_con_cita', 'true')
      if (soloConVenta) p.append('solo_con_venta', 'true')
      if (search.trim()) p.append('search', search.trim())
      p.append('page', String(page))
      p.append('limit', '50')
      const res = await api.get(`/api/estrategias-externas/leads?${p.toString()}`)
      setLeadsData(res.data || { items: [], total: 0, page: 1, pages: 1, resumen_filtrado: {} })
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo cargar el desglose de leads.')
    } finally {
      setLoadingLeads(false)
    }
  }, [buildCommonParams, selectedFuente, estadoId, consideracion, soloConCita, soloConVenta, search, page])

  useEffect(() => {
    fetchResumen()
  }, [fetchResumen])

  useEffect(() => {
    fetchLeads()
  }, [fetchLeads])

  const handleSelectFuente = (nombre) => {
    setSelectedFuente((prev) => (prev === nombre ? '' : nombre))
    setPage(1)
    const el = document.getElementById('desglose-leads-externos')
    if (el) {
      setTimeout(() => el.scrollIntoView({ behavior: 'smooth', block: 'start' }), 60)
    }
  }

  const handleExportExcel = async () => {
    setExporting(true)
    try {
      const p = buildCommonParams()
      if (selectedFuente) p.append('fuente_nombre', selectedFuente)
      if (estadoId) p.append('estado_id', estadoId)
      if (consideracion) p.append('consideracion', consideracion)
      if (soloConCita) p.append('solo_con_cita', 'true')
      if (soloConVenta) p.append('solo_con_venta', 'true')
      if (search.trim()) p.append('search', search.trim())
      const res = await api.get(`/api/estrategias-externas/export?${p.toString()}`, { responseType: 'blob' })
      const url = window.URL.createObjectURL(new Blob([res.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `estrategias_externas_${selectedFuente || 'todas'}.xlsx`)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch {
      setError('No se pudo exportar el archivo Excel.')
    } finally {
      setExporting(false)
    }
  }

  const kpis = resumenData?.kpis || {}
  const fuentes = resumenData?.fuentes || []
  const catalogos = resumenData?.catalogos || {}
  const criterios = resumenData?.criterios_consideracion || []
  const redesExcluidas = resumenData?.redes_excluidas || []

  const topFuente = useMemo(() => {
    if (!fuentes.length) return null
    return fuentes[0]
  }, [fuentes])

  return (
    <div className="p-6 max-w-[1720px] mx-auto space-y-6 animate-fadeIn text-slate-900 dark:text-slate-100">
      {/* Header Principal */}
      <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm space-y-4">
        <div className="flex flex-col xl:flex-row xl:items-center justify-between gap-4">
          <div className="flex items-start gap-3">
            <span className="p-2.5 bg-[#1F1D5C]/10 text-[#1F1D5C] dark:bg-[#1F1D5C]/40 dark:text-indigo-300 rounded-xl border border-[#1F1D5C]/20">
              <Compass size={24} />
            </span>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="text-xl font-bold text-slate-900 dark:text-white">
                  Estrategias Externas
                </h1>
                <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-[#1F1D5C] text-white">
                  Fuentes fuera de Redes Sociales
                </span>
              </div>
              <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
                Efectividad por fuente externa (excluye {redesExcluidas.join(', ')}): citas obtenidas, ventas concretadas y seguimiento completo de leads.
              </p>
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => setShowCriteriosInfo((v) => !v)}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold bg-indigo-50 text-indigo-700 border border-indigo-200 dark:bg-indigo-950/40 dark:text-indigo-300 dark:border-indigo-800 hover:bg-indigo-100 cursor-pointer"
            >
              <Info size={14} />
              <span>¿Qué leads se consideran?</span>
            </button>

            <button
              type="button"
              onClick={handleExportExcel}
              disabled={exporting}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold bg-white dark:bg-[#0f1624] border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800 cursor-pointer disabled:opacity-60"
            >
              <Download size={14} className="text-emerald-600" />
              <span>{exporting ? 'Exportando…' : 'Exportar .xlsx'}</span>
            </button>

            <button
              type="button"
              onClick={() => {
                fetchResumen()
                fetchLeads()
              }}
              className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-bold bg-[#1F1D5C] hover:bg-[#161444] text-white shadow-sm cursor-pointer"
            >
              <RefreshCw size={14} className={loadingResumen || loadingLeads ? 'animate-spin' : ''} />
              <span>Actualizar</span>
            </button>
          </div>
        </div>

        {/* Filtros globales */}
        <div className="flex flex-wrap items-center gap-2.5 pt-3 border-t border-slate-100 dark:border-slate-800 text-xs">
          <div className="flex items-center gap-1.5 text-slate-500 font-semibold">
            <Filter size={13} />
            <span>Filtros globales:</span>
          </div>

          <label className="flex items-center gap-1.5 text-slate-500">
            <span>Desde:</span>
            <input
              type="date"
              value={fechaDesde}
              onChange={(e) => {
                setFechaDesde(e.target.value)
                setPage(1)
              }}
              className="px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d] text-slate-800 dark:text-slate-100"
            />
          </label>

          <label className="flex items-center gap-1.5 text-slate-500">
            <span>Hasta:</span>
            <input
              type="date"
              value={fechaHasta}
              onChange={(e) => {
                setFechaHasta(e.target.value)
                setPage(1)
              }}
              className="px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d] text-slate-800 dark:text-slate-100"
            />
          </label>

          <select
            value={supervisorId}
            onChange={(e) => {
              setSupervisorId(e.target.value)
              setPage(1)
            }}
            className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
          >
            <option value="">Todos los supervisores</option>
            {(catalogos.supervisores || []).map((s) => (
              <option key={s.id} value={s.id}>{s.nombre}</option>
            ))}
          </select>

          <select
            value={asesorId}
            onChange={(e) => {
              setAsesorId(e.target.value)
              setPage(1)
            }}
            className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
          >
            <option value="">Todos los asesores</option>
            {(catalogos.asesores || []).map((a) => (
              <option key={a.id} value={a.id}>{a.nombre}</option>
            ))}
          </select>

          <label className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d] cursor-pointer">
            <input
              type="checkbox"
              checked={incluirWhatsapp}
              onChange={(e) => {
                setIncluirWhatsapp(e.target.checked)
                setPage(1)
              }}
            />
            <span>Incluir WhatsApp</span>
          </label>

          <label className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d] cursor-pointer">
            <input
              type="checkbox"
              checked={incluirSinFuente}
              onChange={(e) => {
                setIncluirSinFuente(e.target.checked)
                setPage(1)
              }}
            />
            <span>Incluir sin fuente</span>
          </label>

          {(fechaDesde || fechaHasta || supervisorId || asesorId || incluirWhatsapp || incluirSinFuente) && (
            <button
              type="button"
              onClick={() => {
                setFechaDesde('')
                setFechaHasta('')
                setSupervisorId('')
                setAsesorId('')
                setIncluirWhatsapp(false)
                setIncluirSinFuente(false)
                setPage(1)
              }}
              className="text-indigo-600 font-semibold hover:underline px-2 cursor-pointer"
            >
              Limpiar globales
            </button>
          )}
        </div>
      </div>

      {/* Panel explicativo de Criterios: ¿Qué leads se consideran? */}
      {showCriteriosInfo && (
        <div className="bg-indigo-50/70 dark:bg-indigo-950/30 border border-indigo-200 dark:border-indigo-800 rounded-2xl p-4 space-y-3 text-xs">
          <div className="flex items-center justify-between">
            <h3 className="font-bold text-indigo-950 dark:text-indigo-100 flex items-center gap-1.5">
              <Sparkles size={15} className="text-indigo-600" />
              Criterio de la columna especial: ¿Qué leads se consideran?
            </h3>
            <button
              type="button"
              onClick={() => setShowCriteriosInfo(false)}
              className="text-indigo-700 font-bold hover:underline cursor-pointer"
            >
              Ocultar
            </button>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2.5">
            {criterios.map((c) => (
              <div
                key={c.codigo}
                className="p-2.5 rounded-xl bg-white dark:bg-[#121a29] border border-slate-200 dark:border-slate-800 space-y-1"
              >
                <div className="flex items-center gap-1.5">
                  {c.es_considerado ? (
                    <CheckCircle2 size={13} className="text-emerald-600 shrink-0" />
                  ) : (
                    <XCircle size={13} className="text-rose-500 shrink-0" />
                  )}
                  <span className="font-bold text-slate-900 dark:text-white">{c.label}</span>
                </div>
                <p className="text-[11px] text-slate-500 dark:text-slate-400">{c.descripcion}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 p-4 rounded-xl text-sm flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <AlertTriangle size={18} />
            <span>{error}</span>
          </div>
          <button type="button" onClick={() => setError(null)} className="text-xs font-bold underline cursor-pointer">
            Cerrar
          </button>
        </div>
      )}

      {/* KPIs Principales */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
            <span>Leads Externos</span>
            <Users size={16} className="text-[#1F1D5C] dark:text-indigo-400" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-slate-900 dark:text-white">
              {kpis.total_leads ?? 0}
            </span>
            <span className="text-xs text-slate-500">en {kpis.total_fuentes ?? 0} fuentes</span>
          </div>
          <div className="mt-2 flex items-center gap-2 text-[11px] font-semibold">
            <span className="px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300">
              Considerados: {kpis.leads_considerados ?? 0}
            </span>
            <span className="px-2 py-0.5 rounded bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300">
              Excluidos: {kpis.leads_no_considerados ?? 0}
            </span>
          </div>
        </div>

        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
            <span>Efectividad de Citas</span>
            <CalendarCheck size={16} className="text-sky-600" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-sky-700 dark:text-sky-400">
              {kpis.con_cita ?? 0}
            </span>
            <span className="text-xs font-bold text-sky-600">
              ({kpis.tasa_cita_pct ?? 0}% del total)
            </span>
          </div>
          <p className="mt-2 text-[11px] text-slate-500">
            Leads que tuvieron cita o visita programada/realizada
          </p>
        </div>

        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
            <span>Ventas Concretadas</span>
            <Award size={16} className="text-emerald-600" />
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-emerald-700 dark:text-emerald-400">
              {kpis.con_venta ?? 0}
            </span>
            <span className="text-xs font-bold text-emerald-600">
              ({kpis.tasa_venta_pct ?? 0}% total · {kpis.tasa_venta_considerados_pct ?? 0}% consid.)
            </span>
          </div>
          <div className="mt-2 flex items-center gap-2 text-[11px] text-slate-500">
            <span>Cierre desde cita: <strong>{kpis.conversion_cita_venta_pct ?? 0}%</strong></span>
            <span>·</span>
            <span>Reservas: <strong>{kpis.con_reserva ?? 0}</strong></span>
          </div>
        </div>

        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center justify-between text-xs font-bold text-slate-500 uppercase tracking-wider">
            <span>Fuente Líder Externa</span>
            <Sparkles size={16} className="text-amber-500" />
          </div>
          {topFuente ? (
            <>
              <div className="mt-2 text-lg font-extrabold text-slate-900 dark:text-white truncate" title={topFuente.fuente_nombre}>
                {topFuente.fuente_nombre}
              </div>
              <div className="mt-1 text-xs text-slate-500 space-x-2">
                <span><strong>{topFuente.con_venta}</strong> ventas</span>
                <span>·</span>
                <span><strong>{topFuente.con_cita}</strong> citas</span>
                <span>·</span>
                <span><strong>{topFuente.total_leads}</strong> leads</span>
              </div>
            </>
          ) : (
            <div className="mt-3 text-xs text-slate-400">Sin datos disponibles</div>
          )}
        </div>
      </div>

      {/* PANEL 1: Efectividad por Fuente Externa */}
      <div className="bg-white dark:bg-[#121a29] rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-200 dark:border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
          <div>
            <h2 className="text-sm font-bold text-slate-900 dark:text-white">
              Efectividad por Fuente de Estrategia Externa
            </h2>
            <p className="text-xs text-slate-500">
              Haz clic en cualquier fuente para filtrar su desglose completo de leads en la tabla inferior.
            </p>
          </div>
          {selectedFuente && (
            <button
              type="button"
              onClick={() => {
                setSelectedFuente('')
                setPage(1)
              }}
              className="text-xs font-bold px-3 py-1.5 rounded-lg bg-indigo-50 text-indigo-700 hover:bg-indigo-100 cursor-pointer self-start"
            >
              Mostrando fuente: {selectedFuente} × (Ver todas)
            </button>
          )}
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead className="bg-slate-50 dark:bg-[#0e1522] text-slate-600 dark:text-slate-300 border-b border-slate-200 dark:border-slate-800">
              <tr>
                <th className="px-4 py-3 font-bold">Fuente Externa</th>
                <th className="px-3 py-3 font-bold text-center">Total Leads</th>
                <th className="px-3 py-3 font-bold text-center">Considerados</th>
                <th className="px-3 py-3 font-bold text-center">Excluidos</th>
                <th className="px-3 py-3 font-bold text-center">Con Cita</th>
                <th className="px-3 py-3 font-bold text-center">% Efect. Cita</th>
                <th className="px-3 py-3 font-bold text-center">Ventas Concretadas</th>
                <th className="px-3 py-3 font-bold text-center">% Efect. Venta</th>
                <th className="px-3 py-3 font-bold text-center">% Cita → Venta</th>
                <th className="px-3 py-3 font-bold text-center">Reservas</th>
                <th className="px-4 py-3 font-bold text-right">Desglose</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {loadingResumen ? (
                <tr>
                  <td colSpan={11} className="p-8 text-center text-slate-500">Calculando efectividad por fuente...</td>
                </tr>
              ) : fuentes.length === 0 ? (
                <tr>
                  <td colSpan={11} className="p-8 text-center text-slate-400">No se encontraron fuentes externas para los filtros actuales.</td>
                </tr>
              ) : (
                fuentes.map((f) => {
                  const isSel = selectedFuente === f.fuente_nombre
                  return (
                    <tr
                      key={`${f.fuente_id}-${f.fuente_nombre}`}
                      onClick={() => handleSelectFuente(f.fuente_nombre)}
                      className={`cursor-pointer transition-colors ${
                        isSel
                          ? 'bg-indigo-50/90 dark:bg-indigo-950/40'
                          : 'hover:bg-slate-50/80 dark:hover:bg-slate-800/30'
                      }`}
                    >
                      <td className="px-4 py-3 font-bold text-slate-900 dark:text-white whitespace-nowrap">
                        <div className="flex items-center gap-2">
                          <span className={`w-2 h-2 rounded-full ${f.con_venta > 0 ? 'bg-emerald-500' : f.con_cita > 0 ? 'bg-sky-500' : 'bg-slate-300'}`} />
                          <span>{f.fuente_nombre}</span>
                        </div>
                      </td>
                      <td className="px-3 py-3 text-center font-bold">{f.total_leads}</td>
                      <td className="px-3 py-3 text-center">
                        <span className="px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300 font-bold">
                          {f.leads_considerados}
                        </span>
                      </td>
                      <td className="px-3 py-3 text-center text-slate-500">{f.leads_no_considerados}</td>
                      <td className="px-3 py-3 text-center font-bold text-sky-700 dark:text-sky-400">{f.con_cita}</td>
                      <td className="px-3 py-3 text-center">
                        <div className="inline-flex items-center gap-1.5">
                          <div className="w-12 h-1.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                            <div className="h-full bg-sky-500" style={{ width: `${Math.min(100, f.tasa_cita_pct)}%` }} />
                          </div>
                          <span className="font-semibold text-sky-700 dark:text-sky-300">{f.tasa_cita_pct}%</span>
                        </div>
                      </td>
                      <td className="px-3 py-3 text-center font-extrabold text-emerald-700 dark:text-emerald-400">{f.con_venta}</td>
                      <td className="px-3 py-3 text-center">
                        <div className="inline-flex items-center gap-1.5">
                          <div className="w-12 h-1.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                            <div className="h-full bg-emerald-500" style={{ width: `${Math.min(100, f.tasa_venta_pct * 3)}%` }} />
                          </div>
                          <span className="font-bold text-emerald-700 dark:text-emerald-300">{f.tasa_venta_pct}%</span>
                        </div>
                      </td>
                      <td className="px-3 py-3 text-center font-semibold text-slate-700 dark:text-slate-300">
                        {f.conversion_cita_venta_pct}%
                      </td>
                      <td className="px-3 py-3 text-center font-semibold text-amber-700 dark:text-amber-400">
                        {f.con_reserva}
                      </td>
                      <td className="px-4 py-3 text-right whitespace-nowrap">
                        <span className="text-[11px] font-bold text-[#1F1D5C] dark:text-indigo-300 hover:underline">
                          {isSel ? 'Filtrando ✓' : `Ver ${f.total_leads} leads ↓`}
                        </span>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* PANEL 2: Desglose Completo de Leads */}
      <div
        id="desglose-leads-externos"
        className="bg-white dark:bg-[#121a29] rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden"
      >
        <div className="p-5 border-b border-slate-200 dark:border-slate-800 space-y-3">
          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
            <div>
              <h2 className="text-sm font-bold text-slate-900 dark:text-white">
                Desglose Completo de Leads {selectedFuente ? `— Fuente: ${selectedFuente}` : '— Todas las Fuentes Externas'}
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">
                Mostrando {leadsData.total ?? 0} leads ({leadsData.resumen_filtrado?.considerados ?? 0} considerados ·{' '}
                {leadsData.resumen_filtrado?.con_cita ?? 0} con cita · {leadsData.resumen_filtrado?.con_venta ?? 0} ventas concretadas)
              </p>
            </div>

            <div className="relative min-w-[260px] flex-1 max-w-sm">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={search}
                onChange={(e) => {
                  setSearch(e.target.value)
                  setPage(1)
                }}
                placeholder="Buscar lead, teléfono, campaña, asesor..."
                className="w-full pl-9 pr-3 py-2 text-xs rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
              />
            </div>
          </div>

          <div className="flex flex-wrap items-center gap-2 text-xs">
            <select
              value={selectedFuente}
              onChange={(e) => {
                setSelectedFuente(e.target.value)
                setPage(1)
              }}
              className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
            >
              <option value="">Todas las fuentes externas</option>
              {fuentes.map((f) => (
                <option key={f.fuente_nombre} value={f.fuente_nombre}>
                  {f.fuente_nombre} ({f.total_leads})
                </option>
              ))}
            </select>

            <select
              value={estadoId}
              onChange={(e) => {
                setEstadoId(e.target.value)
                setPage(1)
              }}
              className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
            >
              <option value="">Todos los estados</option>
              {(catalogos.estados || []).map((est) => (
                <option key={est.id} value={est.id}>{est.nombre}</option>
              ))}
            </select>

            <select
              value={consideracion}
              onChange={(e) => {
                setConsideracion(e.target.value)
                setPage(1)
              }}
              className="px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
            >
              <option value="">¿Qué leads se consideran? (Todos)</option>
              <option value="considerados">Solo Considerados (Válidos)</option>
              <option value="no_considerados">Solo No Considerados (Excluidos)</option>
              {criterios.map((c) => (
                <option key={c.codigo} value={c.codigo}>{c.label}</option>
              ))}
            </select>

            <label className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d] cursor-pointer">
              <input
                type="checkbox"
                checked={soloConCita}
                onChange={(e) => {
                  setSoloConCita(e.target.checked)
                  setPage(1)
                }}
              />
              <span>Solo con cita</span>
            </label>

            <label className="inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d] cursor-pointer">
              <input
                type="checkbox"
                checked={soloConVenta}
                onChange={(e) => {
                  setSoloConVenta(e.target.checked)
                  setPage(1)
                }}
              />
              <span>Solo ventas concretadas</span>
            </label>

            {(selectedFuente || estadoId || consideracion || soloConCita || soloConVenta || search) && (
              <button
                type="button"
                onClick={() => {
                  setSelectedFuente('')
                  setEstadoId('')
                  setConsideracion('')
                  setSoloConCita(false)
                  setSoloConVenta(false)
                  setSearch('')
                  setPage(1)
                }}
                className="text-indigo-600 font-semibold hover:underline px-2 cursor-pointer"
              >
                Limpiar tabla
              </button>
            )}
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead className="bg-slate-50 dark:bg-[#0e1522] text-slate-600 dark:text-slate-300 border-b border-slate-200 dark:border-slate-800">
              <tr>
                <th className="px-3 py-3 font-bold">Lead</th>
                <th className="px-3 py-3 font-bold">Fuente Externa</th>
                <th className="px-3 py-3 font-bold">Estado</th>
                <th className="px-3 py-3 font-bold">Asesor</th>
                <th className="px-3 py-3 font-bold">Supervisor</th>
                <th className="px-3 py-3 font-bold">Fecha Creación</th>
                <th className="px-3 py-3 font-bold">Último Contacto</th>
                <th className="px-3 py-3 font-bold">Última Actividad</th>
                <th className="px-3 py-3 font-bold">Próxima Acción</th>
                <th className="px-3 py-3 font-bold">¿Qué leads se consideran?</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {loadingLeads ? (
                <tr>
                  <td colSpan={10} className="p-10 text-center text-slate-500">Cargando leads externos...</td>
                </tr>
              ) : (leadsData.items || []).length === 0 ? (
                <tr>
                  <td colSpan={10} className="p-10 text-center text-slate-400">No hay leads para los filtros seleccionados.</td>
                </tr>
              ) : (
                leadsData.items.map((r) => (
                  <tr key={r.id} className="hover:bg-slate-50/70 dark:hover:bg-slate-800/30 transition-colors">
                    <td className="px-3 py-2.5 min-w-[180px]">
                      <Link
                        to={`/leads/${r.id}`}
                        className="font-bold text-[#1F1D5C] dark:text-indigo-300 hover:underline inline-flex items-center gap-1"
                      >
                        <span>{r.nombre_completo || `Lead #${r.id}`}</span>
                        <ExternalLink size={11} />
                      </Link>
                      <div className="text-[11px] text-slate-500 font-mono">{r.telefono || 'Sin teléfono'}</div>
                      {(r.campana || r.proyecto) && (
                        <div className="text-[10px] text-slate-400 truncate max-w-[190px]">
                          {[r.proyecto, r.campana].filter(Boolean).join(' · ')}
                        </div>
                      )}
                    </td>

                    <td className="px-3 py-2.5 whitespace-nowrap font-semibold text-slate-800 dark:text-slate-200">
                      {r.fuente_nombre}
                    </td>

                    <td className="px-3 py-2.5 whitespace-nowrap">
                      <div className="flex flex-col gap-1 items-start">
                        <span
                          className="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-bold border"
                          style={{
                            borderColor: `${r.estado_color}55`,
                            backgroundColor: `${r.estado_color}18`,
                            color: r.estado_color,
                          }}
                        >
                          {r.estado_nombre}
                        </span>
                        <div className="flex items-center gap-1">
                          {r.tuvo_cita && (
                            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-sky-100 text-sky-800 dark:bg-sky-950/60 dark:text-sky-300">
                              Cita{r.total_citas > 1 ? ` (${r.total_citas})` : ''}
                            </span>
                          )}
                          {r.concreto_venta && (
                            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800 dark:bg-emerald-950/60 dark:text-emerald-300">
                              Venta ✓
                            </span>
                          )}
                        </div>
                      </div>
                    </td>

                    <td className="px-3 py-2.5 whitespace-nowrap text-slate-700 dark:text-slate-200">
                      {r.asesor_nombre || <span className="text-slate-400 italic">Sin asignar</span>}
                    </td>

                    <td className="px-3 py-2.5 whitespace-nowrap text-slate-600 dark:text-slate-300">
                      {r.supervisor_nombre || <span className="text-slate-400">—</span>}
                    </td>

                    <td className="px-3 py-2.5 whitespace-nowrap font-mono text-[11px] text-slate-600 dark:text-slate-300">
                      {formatDateTimeLima(r.fecha_creacion)}
                    </td>

                    <td className="px-3 py-2.5 min-w-[140px]">
                      {r.ultimo_contacto_at ? (
                        <div>
                          <div className="font-mono text-[11px] text-slate-800 dark:text-slate-200">
                            {formatDateTimeLima(r.ultimo_contacto_at)}
                          </div>
                          <div className="text-[10px] text-slate-500 truncate max-w-[155px]" title={r.ultimo_contacto_resultado || ''}>
                            {[r.ultimo_contacto_tipo, r.ultimo_contacto_resultado].filter(Boolean).join(' · ')}
                          </div>
                        </div>
                      ) : (
                        <span className="text-[11px] text-amber-600 font-semibold">Sin contacto</span>
                      )}
                    </td>

                    <td className="px-3 py-2.5 min-w-[150px]">
                      <div className="font-mono text-[11px] text-slate-800 dark:text-slate-200">
                        {formatDateTimeLima(r.ultima_actividad_at)}
                      </div>
                      <div className="text-[10px] text-slate-500 truncate max-w-[165px]" title={r.ultima_actividad_detalle || ''}>
                        {r.ultima_actividad_detalle || '—'}
                      </div>
                    </td>

                    <td className="px-3 py-2.5 min-w-[150px]">
                      {r.proxima_accion || r.fecha_proxima_accion ? (
                        <div className="space-y-0.5">
                          <div className="font-semibold text-slate-800 dark:text-slate-200 truncate max-w-[170px]" title={r.proxima_accion || ''}>
                            {r.proxima_accion || 'Seguimiento'}
                          </div>
                          {r.fecha_proxima_accion && (
                            <div className="text-[10px] font-mono text-indigo-600 dark:text-indigo-400 inline-flex items-center gap-1">
                              <Clock size={10} />
                              <span>{formatDateLima(r.fecha_proxima_accion)}</span>
                            </div>
                          )}
                        </div>
                      ) : (
                        <span className="text-slate-400">—</span>
                      )}
                    </td>

                    {/* COLUMNA ESPECIAL: ¿Qué leads se consideran? */}
                    <td className="px-3 py-2.5 min-w-[195px]">
                      <div
                        className={`inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[10px] font-bold border ${getConsideracionStyle(
                          r.consideracion_codigo,
                        )}`}
                        title={r.consideracion_motivo}
                      >
                        {r.es_considerado ? <CheckCircle2 size={11} /> : <XCircle size={11} />}
                        <span>{r.consideracion_label}</span>
                      </div>
                      <div className="text-[10px] text-slate-400 mt-0.5 truncate max-w-[205px]" title={r.consideracion_motivo}>
                        {r.consideracion_motivo}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Paginación */}
        <div className="px-5 py-3 border-t border-slate-200 dark:border-slate-800 flex items-center justify-between text-xs bg-slate-50/70 dark:bg-[#0e1522]">
          <span className="text-slate-500">
            Página <strong>{leadsData.page ?? 1}</strong> de <strong>{leadsData.pages ?? 1}</strong> · {leadsData.total ?? 0} registros
          </span>
          <div className="flex items-center gap-2">
            <button
              type="button"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-[#121a29] disabled:opacity-40 cursor-pointer"
            >
              <ChevronLeft size={14} /> Anterior
            </button>
            <button
              type="button"
              disabled={page >= (leadsData.pages || 1)}
              onClick={() => setPage((p) => p + 1)}
              className="inline-flex items-center gap-1 px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-white dark:bg-[#121a29] disabled:opacity-40 cursor-pointer"
            >
              Siguiente <ChevronRight size={14} />
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
