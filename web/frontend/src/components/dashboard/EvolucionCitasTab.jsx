import React, { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  TrendingUp,
  History,
  Clock,
  Users,
  CalendarCheck,
  Award,
  PhoneCall,
  Search,
  ExternalLink,
  AlertTriangle,
  RefreshCw,
  Filter,
  Sparkles,
} from 'lucide-react'
import api from '@/lib/api'

function formatDias(dias) {
  if (dias === null || dias === undefined || Number.isNaN(Number(dias))) return '—'
  const n = Math.round(Number(dias) * 10) / 10
  return `${n} d`
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

export default function EvolucionCitasTab({
  periodo,
  fechaInicio,
  fechaFin,
  sedeId,
  supervisorId,
  asesorId,
  refreshTick,
  onCountChange,
}) {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const [subTab, setSubTab] = useState('recuperados') // 'recuperados' | 'cartera' | 'embudo'
  const [cohorteFilter, setCohorteFilter] = useState('')
  const [asesorRowFilter, setAsesorRowFilter] = useState('')
  const [search, setSearch] = useState('')

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

        const res = await api.get(
          `/api/dashboard/supervision-control/evolucion-citas?${params.toString()}`
        )
        if (!cancelled) {
          setData(res.data)
          const r = res.data?.resumen || {}
          onCountChange?.((r.citas_visitas_mes_anterior ?? 0) + (r.cierres_mes_anterior ?? 0))
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.response?.data?.detail || 'No se pudo cargar la evolución de citas y cohortes.')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    run()
    return () => {
      cancelled = true
    }
  }, [periodo, fechaInicio, fechaFin, sedeId, supervisorId, asesorId, refreshTick, onCountChange])

  const resumen = data?.resumen || {}
  const embudo = data?.embudo || []
  const porCohorte = data?.por_cohorte_mes || []
  const porAsesor = data?.por_asesor || []
  const leadsRecuperados = useMemo(() => data?.leads_recuperados || [], [data])
  const leadsCartera = useMemo(() => data?.leads_cartera_antigua || [], [data])
  const leadsEmbudo = useMemo(() => data?.leads_embudo || [], [data])

  const activeList = useMemo(() => {
    const base =
      subTab === 'recuperados'
        ? leadsRecuperados
        : subTab === 'cartera'
          ? leadsCartera
          : leadsEmbudo

    const q = search.trim().toLowerCase()
    return base.filter((l) => {
      if (cohorteFilter && l.cohorte_mes !== cohorteFilter) return false
      if (asesorRowFilter && (l.asesor_id || 'sin_asignar') !== asesorRowFilter) return false
      if (q) {
        const hay = [l.nombre, l.telefono, l.asesor_nombre, l.supervisor_nombre, l.fuente_nombre, l.cohorte_label]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
        if (!hay.includes(q)) return false
      }
      return true
    })
  }, [subTab, leadsRecuperados, leadsCartera, leadsEmbudo, cohorteFilter, asesorRowFilter, search])

  const maxEmbudo = useMemo(
    () => Math.max(...embudo.map((e) => e.total || 0), 1),
    [embudo]
  )

  return (
    <div className="space-y-6">
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 p-4 rounded-xl text-sm flex items-center gap-2">
          <AlertTriangle size={18} />
          <span>{error}</span>
        </div>
      )}

      {/* Nota informativa de cohorte */}
      <div className="bg-gradient-to-r from-indigo-50 via-white to-emerald-50 dark:from-indigo-950/30 dark:via-[#121a29] dark:to-emerald-950/20 border border-indigo-200/70 dark:border-indigo-900/50 rounded-2xl px-4 py-3 flex flex-col sm:flex-row sm:items-center justify-between gap-2 text-xs">
        <div className="flex items-center gap-2 text-slate-700 dark:text-slate-300">
          <Sparkles size={16} className="text-indigo-600 dark:text-indigo-400 shrink-0" />
          <span>
            <strong>Corte de cohorte ({data?.cohorte_corte_mes || '—'}):</strong> leads ingresados antes del 1° de{' '}
            <strong>{data?.cohorte_corte_mes || 'mes actual'}</strong> se contabilizan como{' '}
            <strong className="text-purple-700 dark:text-purple-300">recuperación de meses anteriores</strong>; los ingresados desde ese mes son{' '}
            <strong className="text-sky-700 dark:text-sky-300">mes actual</strong>.
          </span>
        </div>
        {(periodo === 'hoy' || periodo === 'ayer') && (
          <span className="text-[11px] font-semibold text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-950/40 px-2.5 py-1 rounded-lg border border-amber-200 dark:border-amber-800 shrink-0">
            Tip: usa &quot;Este Mes&quot; o &quot;Últimos 30d&quot; para ver cohortes mensuales
          </span>
        )}
      </div>

      {/* 4 KPIs Principales */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {/* KPI 1: Citas y Visitas del Período */}
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
              Citas / Visitas del Período
            </span>
            <span className="p-2 rounded-xl bg-indigo-50 text-indigo-600 dark:bg-indigo-950/60 dark:text-indigo-400">
              <CalendarCheck size={20} />
            </span>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-slate-900 dark:text-white">
              {loading && !data ? '…' : (resumen.total_citas_visitas_periodo ?? 0)}
            </span>
            <span className="text-xs font-bold text-purple-600 dark:text-purple-400">
              {resumen.pct_citas_mes_anterior ?? 0}% de meses prev.
            </span>
          </div>
          <div className="mt-3 grid grid-cols-2 gap-2 text-[11px]">
            <div className="px-2.5 py-1.5 rounded-lg bg-sky-50 dark:bg-sky-950/40 text-sky-800 dark:text-sky-300">
              <span className="block text-[10px] opacity-80">Mes actual</span>
              <strong>{resumen.citas_visitas_mismo_mes ?? 0}</strong>
            </div>
            <div className="px-2.5 py-1.5 rounded-lg bg-purple-50 dark:bg-purple-950/40 text-purple-800 dark:text-purple-300">
              <span className="block text-[10px] opacity-80">Meses anteriores</span>
              <strong>{resumen.citas_visitas_mes_anterior ?? 0}</strong>
            </div>
          </div>
        </div>

        {/* KPI 2: Separaciones y Ventas del Período (Mismo Mes vs Anteriores) */}
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border-2 border-emerald-200/80 dark:border-emerald-900/50 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-emerald-700 dark:text-emerald-300 uppercase tracking-wider">
              Separaciones y Ventas
            </span>
            <span className="p-2 rounded-xl bg-emerald-50 text-emerald-600 dark:bg-emerald-950/60 dark:text-emerald-400">
              <Award size={20} />
            </span>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-emerald-600 dark:text-emerald-400">
              {loading && !data ? '…' : (resumen.total_cierres_periodo ?? 0)}
            </span>
            <span className="text-xs font-bold text-purple-600 dark:text-purple-400">
              {resumen.cierres_mes_anterior ?? 0} recuperados ({resumen.pct_cierres_mes_anterior ?? 0}%)
            </span>
          </div>
          <div className="mt-3 space-y-1 text-[11px] text-slate-600 dark:text-slate-300">
            <div className="flex items-center justify-between">
              <span>Separaciones (Mes / Prev.):</span>
              <strong>
                {resumen.separaciones_mismo_mes ?? 0} /{' '}
                <span className="text-purple-600 dark:text-purple-400">{resumen.separaciones_mes_anterior ?? 0}</span>
              </strong>
            </div>
            <div className="flex items-center justify-between">
              <span>Ventas Concr. (Mes / Prev.):</span>
              <strong>
                {resumen.ventas_mismo_mes ?? 0} /{' '}
                <span className="text-purple-600 dark:text-purple-400">{resumen.ventas_mes_anterior ?? 0}</span>
              </strong>
            </div>
          </div>
        </div>

        {/* KPI 3: Maduración y Recuperación de Tropiezos */}
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
              Maduración y Recupero
            </span>
            <span className="p-2 rounded-xl bg-amber-50 text-amber-600 dark:bg-amber-950/60 dark:text-amber-400">
              <RefreshCw size={20} />
            </span>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-amber-600 dark:text-amber-400">
              {loading && !data ? '…' : `${resumen.pct_recuperacion_tropiezo ?? 0}%`}
            </span>
            <span className="text-xs text-slate-500">recuperadas tras tropiezo</span>
          </div>
          <div className="mt-3 space-y-1 text-[11px] text-slate-600 dark:text-slate-300">
            <div className="flex items-center justify-between">
              <span>Ingreso → 1ra Cita (prom / med):</span>
              <strong>
                {formatDias(resumen.maduracion_cita_promedio_dias)} / {formatDias(resumen.maduracion_cita_mediana_dias)}
              </strong>
            </div>
            <div className="flex items-center justify-between">
              <span>Ingreso → Cierre (prom / med):</span>
              <strong>
                {formatDias(resumen.maduracion_cierre_promedio_dias)} / {formatDias(resumen.maduracion_cierre_mediana_dias)}
              </strong>
            </div>
          </div>
        </div>

        {/* KPI 4: Cartera Antigua Interesada */}
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
              Cartera Antigua Interesada
            </span>
            <span className="p-2 rounded-xl bg-sky-50 text-sky-600 dark:bg-sky-950/60 dark:text-sky-400">
              <PhoneCall size={20} />
            </span>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-sky-600 dark:text-sky-400">
              {loading && !data ? '…' : (resumen.cartera_antigua_total ?? 0)}
            </span>
            <span className="text-xs text-slate-500">leads meses prev. vivos</span>
          </div>
          <div className="mt-3 space-y-1 text-[11px] text-slate-600 dark:text-slate-300">
            <div className="flex items-center justify-between">
              <span>Con llamadas/gestión en período:</span>
              <strong className="text-sky-600 dark:text-sky-400">
                {resumen.cartera_antigua_con_gestion_reciente ?? 0}
              </strong>
            </div>
            <div className="flex items-center justify-between">
              <span>Con intento previo de cita:</span>
              <strong>{resumen.cartera_antigua_con_intento_cita ?? 0}</strong>
            </div>
          </div>
        </div>
      </div>

      {/* Embudo de Evolución + Matriz por Cohorte (Mes de ingreso) */}
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        {/* Embudo de Evolución de Citas */}
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <TrendingUp size={17} className="text-indigo-500" />
              <div>
                <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                  Embudo de Evolución de Citas y Visitas
                </h3>
                <p className="text-xs text-slate-500">
                  Mide tropiezos (reprogramación / no asistió), recuperación y desenlace
                </p>
              </div>
            </div>
          </div>

          <div className="space-y-3">
            {embudo.map((et) => {
              const widthPct = Math.max(Math.round(((et.total || 0) / maxEmbudo) * 100), et.total > 0 ? 6 : 0)
              return (
                <div key={et.codigo} className="space-y-1">
                  <div className="flex items-center justify-between text-xs">
                    <span className="font-semibold text-slate-700 dark:text-slate-300">{et.label}</span>
                    <span className="font-extrabold text-slate-900 dark:text-white">{et.total ?? 0}</span>
                  </div>
                  <div className="w-full h-2.5 rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all duration-300"
                      style={{ width: `${widthPct}%`, backgroundColor: et.color }}
                    />
                  </div>
                </div>
              )
            })}
            {!loading && embudo.length === 0 && (
              <p className="text-xs text-slate-400 py-4 text-center">Sin datos de embudo para este período.</p>
            )}
          </div>
        </div>

        {/* Tabla por Cohorte (Mes de Ingreso del Lead) */}
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <History size={17} className="text-purple-500" />
              <div>
                <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                  Logros del Período según Mes de Ingreso (Cohorte)
                </h3>
                <p className="text-xs text-slate-500">
                  Clic en un mes origen para filtrar la tabla inferior
                </p>
              </div>
            </div>
            {cohorteFilter && (
              <button
                type="button"
                onClick={() => setCohorteFilter('')}
                className="text-xs font-semibold text-indigo-600 hover:underline cursor-pointer"
              >
                Todos los meses
              </button>
            )}
          </div>

          <div className="max-h-72 overflow-y-auto border border-slate-100 dark:border-slate-800 rounded-xl">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 dark:bg-[#0b101b] text-slate-500 font-semibold sticky top-0">
                <tr>
                  <th className="py-2.5 px-3">Mes Ingreso</th>
                  <th className="py-2.5 px-2 text-center">Citas/Visitas</th>
                  <th className="py-2.5 px-2 text-center">Separac.</th>
                  <th className="py-2.5 px-2 text-center">Ventas</th>
                  <th className="py-2.5 px-2 text-center">Recup./Trop.</th>
                  <th className="py-2.5 px-2 text-center">Cartera Viva</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
                {porCohorte.map((c) => {
                  const selected = cohorteFilter === c.cohorte_mes
                  return (
                    <tr
                      key={c.cohorte_mes}
                      onClick={() => setCohorteFilter(selected ? '' : c.cohorte_mes)}
                      className={`cursor-pointer transition-colors ${
                        selected
                          ? 'bg-purple-50 dark:bg-purple-950/40'
                          : 'hover:bg-slate-50 dark:hover:bg-slate-800/30'
                      }`}
                    >
                      <td className="py-2 px-3 font-semibold text-slate-800 dark:text-slate-200">
                        <div className="flex items-center gap-1.5">
                          <span>{c.cohorte_label}</span>
                          {c.es_mes_anterior && (
                            <span className="text-[9px] font-bold px-1.5 py-0.5 rounded bg-purple-100 text-purple-700 dark:bg-purple-950 dark:text-purple-300">
                              Ant.
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="py-2 px-2 text-center font-bold text-indigo-600 dark:text-indigo-400">
                        {c.citas_visitas_periodo}
                      </td>
                      <td className="py-2 px-2 text-center font-bold text-teal-600 dark:text-teal-400">
                        {c.separaciones_periodo}
                      </td>
                      <td className="py-2 px-2 text-center font-bold text-emerald-600 dark:text-emerald-400">
                        {c.ventas_periodo}
                      </td>
                      <td className="py-2 px-2 text-center text-slate-600 dark:text-slate-300">
                        {c.recuperadas}/{c.tropiezos}
                      </td>
                      <td className="py-2 px-2 text-center font-semibold text-sky-600 dark:text-sky-400">
                        {c.cartera_antigua_activa}
                      </td>
                    </tr>
                  )
                })}
                {!loading && porCohorte.length === 0 && (
                  <tr>
                    <td colSpan={6} className="py-6 text-center text-slate-400">
                      Sin cohortes registradas en este rango.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* Ranking por Asesor */}
      <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm space-y-3">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Users size={17} className="text-indigo-500" />
            <div>
              <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                Recuperación y Evolución de Citas por Asesor
              </h3>
              <p className="text-xs text-slate-500">
                Compara logros de leads del mes actual vs recuperados de meses anteriores y seguimiento de cartera antigua
              </p>
            </div>
          </div>
          {asesorRowFilter && (
            <button
              type="button"
              onClick={() => setAsesorRowFilter('')}
              className="text-xs font-semibold text-indigo-600 hover:underline cursor-pointer"
            >
              Todos los asesores
            </button>
          )}
        </div>

        <div className="overflow-x-auto border border-slate-100 dark:border-slate-800 rounded-xl">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 dark:bg-[#0b101b] text-slate-500 font-semibold">
              <tr>
                <th className="py-2.5 px-3">Asesor</th>
                <th className="py-2.5 px-2 text-center">Citas/Visitas (Mes / Prev.)</th>
                <th className="py-2.5 px-2 text-center">Separac. (Mes / Prev.)</th>
                <th className="py-2.5 px-2 text-center">Ventas (Mes / Prev.)</th>
                <th className="py-2.5 px-2 text-center">Recup. Tropiezos</th>
                <th className="py-2.5 px-2 text-center">Cartera Ant. Gest.</th>
                <th className="py-2.5 px-2 text-center">% Aporte Prev.</th>
                <th className="py-2.5 px-3 text-center">Madur. Prom.</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
              {porAsesor.map((a) => {
                const key = a.asesor_id || 'sin_asignar'
                const selected = asesorRowFilter === key
                return (
                  <tr
                    key={key}
                    onClick={() => setAsesorRowFilter(selected ? '' : key)}
                    className={`cursor-pointer transition-colors ${
                      selected
                        ? 'bg-indigo-50 dark:bg-indigo-950/40'
                        : 'hover:bg-slate-50 dark:hover:bg-slate-800/30'
                    }`}
                  >
                    <td className="py-2.5 px-3 font-semibold text-slate-800 dark:text-slate-200">
                      <div>{a.asesor_nombre}</div>
                      <div className="text-[10px] font-normal text-slate-400">{a.supervisor_nombre}</div>
                    </td>
                    <td className="py-2.5 px-2 text-center font-semibold">
                      {a.citas_mes_actual} /{' '}
                      <span className="text-purple-600 dark:text-purple-400 font-bold">{a.citas_meses_anteriores}</span>
                    </td>
                    <td className="py-2.5 px-2 text-center font-semibold">
                      {a.separaciones_mes_actual} /{' '}
                      <span className="text-purple-600 dark:text-purple-400 font-bold">{a.separaciones_meses_anteriores}</span>
                    </td>
                    <td className="py-2.5 px-2 text-center font-semibold">
                      {a.ventas_mes_actual} /{' '}
                      <span className="text-emerald-600 dark:text-emerald-400 font-bold">{a.ventas_meses_anteriores}</span>
                    </td>
                    <td className="py-2.5 px-2 text-center">
                      <span className="font-bold text-amber-600 dark:text-amber-400">
                        {a.recuperadas_tropiezo}/{a.tropiezos}
                      </span>{' '}
                      <span className="text-[10px] text-slate-400">({a.pct_recuperacion_tropiezo}%)</span>
                    </td>
                    <td className="py-2.5 px-2 text-center font-bold text-sky-600 dark:text-sky-400">
                      {a.cartera_antigua_gestionada}
                    </td>
                    <td className="py-2.5 px-2 text-center font-bold text-purple-600 dark:text-purple-400">
                      {a.pct_aporte_meses_anteriores}%
                    </td>
                    <td className="py-2.5 px-3 text-center text-slate-600 dark:text-slate-300">
                      {formatDias(a.maduracion_promedio_dias)}
                    </td>
                  </tr>
                )
              })}
              {!loading && porAsesor.length === 0 && (
                <tr>
                  <td colSpan={8} className="py-6 text-center text-slate-400">
                    Sin datos de asesores en este período.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Tabla Detalle de Leads */}
      <div className="bg-white dark:bg-[#121a29] rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden">
        <div className="p-5 border-b border-slate-100 dark:border-slate-800 flex flex-col lg:flex-row lg:items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-bold text-slate-900 dark:text-white flex items-center gap-2">
              <Clock size={18} className="text-purple-500" />
              <span>Detalle de Evolución y Recuperación de Leads</span>
              <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-purple-50 text-purple-700 dark:bg-purple-950/60 dark:text-purple-300">
                {activeList.length}
              </span>
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Inspecciona leads recuperados de meses anteriores, cartera antigua aún interesada o todo el flujo
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Buscar lead, tel., asesor o mes..."
                className="pl-8 pr-3 py-1.5 text-xs bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 rounded-xl outline-none focus:ring-2 focus:ring-purple-500/30 w-56"
              />
            </div>

            <div className="inline-flex bg-slate-100 dark:bg-slate-800 p-1 rounded-xl text-xs font-semibold">
              {[
                { id: 'recuperados', label: `Recuperados prev. (${leadsRecuperados.length})` },
                { id: 'cartera', label: `Cartera interesada (${leadsCartera.length})` },
                { id: 'embudo', label: `Todo el flujo (${leadsEmbudo.length})` },
              ].map((t) => (
                <button
                  key={t.id}
                  type="button"
                  onClick={() => setSubTab(t.id)}
                  className={`px-2.5 py-1 rounded-lg transition-colors cursor-pointer ${
                    subTab === t.id
                      ? 'bg-white dark:bg-[#0c121d] text-purple-600 shadow-2xs'
                      : 'text-slate-500 hover:text-slate-800'
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {(cohorteFilter || asesorRowFilter || search) && (
              <button
                type="button"
                onClick={() => {
                  setCohorteFilter('')
                  setAsesorRowFilter('')
                  setSearch('')
                }}
                className="inline-flex items-center gap-1 px-2.5 py-1.5 rounded-xl text-xs font-semibold text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800 cursor-pointer"
              >
                <Filter size={12} />
                Limpiar
              </button>
            )}
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 dark:bg-[#0b101b] text-slate-500 font-semibold border-b border-slate-200 dark:border-slate-800">
              <tr>
                <th className="py-3 px-4">Lead</th>
                <th className="py-3 px-3">Mes Ingreso</th>
                <th className="py-3 px-3">Asesor</th>
                <th className="py-3 px-3">Estado Actual</th>
                <th className="py-3 px-3">
                  {subTab === 'cartera' ? 'Gestiones en Período' : 'Evolución / Tropiezos'}
                </th>
                <th className="py-3 px-3 text-center">
                  {subTab === 'cartera' ? 'Antigüedad' : 'Maduración'}
                </th>
                <th className="py-3 px-3 text-right">Ficha</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60 font-medium">
              {activeList.map((l) => (
                <tr key={`${subTab}-${l.id}`} className="hover:bg-slate-50/80 dark:hover:bg-slate-800/30">
                  <td className="py-3 px-4">
                    <div className="font-bold text-slate-900 dark:text-white">
                      {l.nombre || `Lead #${l.id}`}
                    </div>
                    <div className="text-[11px] text-slate-400 font-mono">
                      {l.telefono || 'Sin teléfono'} · {l.fuente_nombre}
                    </div>
                  </td>

                  <td className="py-3 px-3">
                    <span
                      className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-bold border ${
                        l.es_mes_anterior || subTab === 'cartera'
                          ? 'bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-950/40 dark:text-purple-300 dark:border-purple-800'
                          : 'bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950/40 dark:text-sky-300 dark:border-sky-800'
                      }`}
                    >
                      {l.cohorte_label || l.cohorte_mes}
                    </span>
                    <div className="text-[10px] text-slate-400 mt-0.5">
                      Ing: {formatDateLima(l.created_at)}
                    </div>
                  </td>

                  <td className="py-3 px-3">
                    <div className="font-semibold text-slate-700 dark:text-slate-300">
                      {l.asesor_nombre || 'Sin asignar'}
                    </div>
                    <div className="text-[10px] text-slate-400">
                      {l.supervisor_nombre || 'Sin supervisor'}
                    </div>
                  </td>

                  <td className="py-3 px-3">
                    <span
                      className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-bold border"
                      style={{
                        backgroundColor: `${l.estado_color}18`,
                        borderColor: `${l.estado_color}50`,
                        color: l.estado_color,
                      }}
                    >
                      {l.estado_nombre}
                    </span>
                  </td>

                  <td className="py-3 px-3">
                    {subTab === 'cartera' ? (
                      <div className="space-y-0.5">
                        <div className="font-semibold text-sky-700 dark:text-sky-300">
                          {l.gestiones_periodo ?? 0} gestiones ({l.llamadas_periodo ?? 0} llam. / {l.contactos_periodo ?? 0} cont.)
                        </div>
                        <div className="text-[10px] text-slate-400">
                          {l.tuvo_intento_cita ? 'Tuvo intento de cita previo' : 'Aún sin cita agendada'}
                          {l.fecha_proxima_gestion ? ` · Próx: ${formatDateLima(l.fecha_proxima_gestion)}` : ''}
                        </div>
                      </div>
                    ) : (
                      <div className="flex flex-wrap items-center gap-1">
                        {l.cierre_en_periodo && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200 dark:bg-emerald-950/50 dark:text-emerald-300 dark:border-emerald-800">
                            Cierre en período
                          </span>
                        )}
                        {l.cita_visita_en_periodo && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-indigo-50 text-indigo-700 border border-indigo-200 dark:bg-indigo-950/50 dark:text-indigo-300 dark:border-indigo-800">
                            Cita/Visita período
                          </span>
                        )}
                        {l.tuvo_tropiezo && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-amber-50 text-amber-700 border border-amber-200 dark:bg-amber-950/50 dark:text-amber-300 dark:border-amber-800">
                            {l.recuperada_tropiezo ? 'Recuperada tras tropiezo' : 'Tuvo reprogramación/tropiezo'}
                          </span>
                        )}
                      </div>
                    )}
                  </td>

                  <td className="py-3 px-3 text-center font-bold text-slate-700 dark:text-slate-300">
                    {subTab === 'cartera'
                      ? formatDias(l.dias_antiguedad)
                      : formatDias(l.dias_hasta_cierre ?? l.dias_hasta_cita)}
                  </td>

                  <td className="py-3 px-3 text-right">
                    <button
                      type="button"
                      onClick={() => navigate(`/leads/${l.id}`)}
                      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-slate-100 hover:bg-purple-50 text-slate-700 hover:text-purple-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-purple-950/60 text-xs font-semibold transition-colors cursor-pointer"
                    >
                      <span>Ver</span>
                      <ExternalLink size={12} />
                    </button>
                  </td>
                </tr>
              ))}
              {!loading && activeList.length === 0 && (
                <tr>
                  <td colSpan={7} className="py-10 text-center text-slate-400">
                    No se encontraron leads en esta categoría para los filtros seleccionados.
                  </td>
                </tr>
              )}
              {loading && activeList.length === 0 && (
                <tr>
                  <td colSpan={7} className="py-10 text-center text-slate-400">
                    Cargando evolución de citas…
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
