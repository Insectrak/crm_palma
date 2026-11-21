import React, { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Calendar,
  CalendarCheck,
  History,
  Search,
  ExternalLink,
  AlertTriangle,
  Users,
  Clock,
  Filter,
  Layers,
  CheckCircle2,
  XCircle,
} from 'lucide-react'
import api from '@/lib/api'

function formatDateTimeLima(iso) {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return '—'
    const fecha = d.toLocaleDateString('es-PE', {
      timeZone: 'America/Lima',
      day: '2-digit',
      month: '2-digit',
      year: '2-digit',
    })
    const hora = d.toLocaleTimeString('es-PE', {
      timeZone: 'America/Lima',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    })
    return `${fecha} ${hora}`
  } catch {
    return '—'
  }
}

export default function SeguimientoCitasTab({
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

  const [soloPeriodo, setSoloPeriodo] = useState(true)
  const [situacionFilter, setSituacionFilter] = useState('todos') // 'todos' | 'actual' | 'historico'
  const [estadoFilter, setEstadoFilter] = useState('')
  const [asesorRowFilter, setAsesorRowFilter] = useState('')
  const [fuenteFilter, setFuenteFilter] = useState('')
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
        params.append('solo_periodo', soloPeriodo ? 'true' : 'false')

        const res = await api.get(
          `/api/dashboard/supervision-control/seguimiento-citas?${params.toString()}`
        )
        if (!cancelled) {
          setData(res.data)
          onCountChange?.(res.data?.resumen?.total_leads_citas ?? null)
        }
      } catch (err) {
        if (!cancelled) {
          setError(err.response?.data?.detail || 'No se pudo cargar el seguimiento de citas.')
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    run()
    return () => {
      cancelled = true
    }
  }, [periodo, fechaInicio, fechaFin, sedeId, supervisorId, asesorId, soloPeriodo, refreshTick, onCountChange])

  const resumen = data?.resumen || {}
  const porEstadoActual = data?.por_estado_actual || []
  const porEstadoCita = data?.por_estado_cita || []
  const porAsesor = data?.por_asesor || []
  const porFuente = data?.por_fuente || []
  const leads = useMemo(() => data?.leads || [], [data])

  const filteredLeads = useMemo(() => {
    const q = search.trim().toLowerCase()
    return leads.filter((l) => {
      if (situacionFilter !== 'todos' && l.situacion_cita !== situacionFilter) return false
      if (estadoFilter && l.estado_nombre !== estadoFilter) return false
      if (asesorRowFilter && (l.asesor_id || 'sin_asignar') !== asesorRowFilter) return false
      if (fuenteFilter && (l.fuente_nombre || 'Sin fuente') !== fuenteFilter) return false
      if (q) {
        const hay = [l.nombre, l.telefono, l.asesor_nombre, l.supervisor_nombre, l.fuente_nombre]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
        if (!hay.includes(q)) return false
      }
      return true
    })
  }, [leads, situacionFilter, estadoFilter, asesorRowFilter, fuenteFilter, search])

  return (
    <div className="space-y-6">
      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 p-4 rounded-xl text-sm flex items-center gap-2">
          <AlertTriangle size={18} />
          <span>{error}</span>
        </div>
      )}

      {/* ─────────────────────────────────────────────────────────────
          CONTADOR PRINCIPAL Y DESGLOSE DE SEGUIMIENTO A CITAS
          ───────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        {/* KPI 1: Contador Total (Tienen o tuvieron estado de citas) */}
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border-2 border-indigo-200 dark:border-indigo-900/60 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-indigo-700 dark:text-indigo-300 uppercase tracking-wider">
              Leads con Cita (Total)
            </span>
            <span className="p-2 rounded-xl bg-indigo-50 text-indigo-600 dark:bg-indigo-950/60 dark:text-indigo-400">
              <Calendar size={20} />
            </span>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-slate-900 dark:text-white">
              {loading && !data ? '…' : (resumen.total_leads_citas ?? 0)}
            </span>
            <span className="text-xs text-slate-500">leads únicos</span>
          </div>
          <p className="mt-2 text-[11px] text-slate-500 dark:text-slate-400">
            Incluye leads que <strong>tienen</strong> hoy el estado de citas y los que <strong>lo tuvieron</strong> en su historial.
          </p>
        </div>

        {/* KPI 2: Actualmente en estado citas */}
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
              Estado Actual: Citas
            </span>
            <span className="p-2 rounded-xl bg-sky-50 text-sky-600 dark:bg-sky-950/60 dark:text-sky-400">
              <CalendarCheck size={20} />
            </span>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-sky-600 dark:text-sky-400">
              {loading && !data ? '…' : (resumen.con_estado_cita_actual ?? 0)}
            </span>
            <span className="text-xs text-slate-500">en estado activo de cita</span>
          </div>
          <p className="mt-2 text-[11px] text-slate-500 dark:text-slate-400">
            Leads cuyo estado actual sigue siendo de cita / agendado.
          </p>
        </div>

        {/* KPI 3: Tuvieron estado citas antes */}
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
              Tuvieron Estado Citas
            </span>
            <span className="p-2 rounded-xl bg-purple-50 text-purple-600 dark:bg-purple-950/60 dark:text-purple-400">
              <History size={20} />
            </span>
          </div>
          <div className="mt-3 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-purple-600 dark:text-purple-400">
              {loading && !data ? '…' : (resumen.tuvieron_estado_cita_antes ?? 0)}
            </span>
            <span className="text-xs text-slate-500">avanzaron a otro estado</span>
          </div>
          <p className="mt-2 text-[11px] text-slate-500 dark:text-slate-400">
            Pasaron por cita antes y hoy tienen otro estado (Venta, Separación, Seguimiento, Perdido, etc.).
          </p>
        </div>

        {/* KPI 4: Alcance de fechas (Cita registrada en el período vs Histórico total) */}
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm flex flex-col justify-between">
          <div>
            <div className="flex items-center justify-between">
              <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
                {soloPeriodo ? 'Histórico Total (Citas)' : 'Citas del Período'}
              </span>
              <span className="p-2 rounded-xl bg-emerald-50 text-emerald-600 dark:bg-emerald-950/60 dark:text-emerald-400">
                <Clock size={20} />
              </span>
            </div>
            <div className="mt-3 flex items-baseline gap-2">
              <span className="text-3xl font-extrabold text-emerald-600 dark:text-emerald-400">
                {loading && !data
                  ? '…'
                  : soloPeriodo
                    ? (resumen.total_historico_sin_filtro_periodo ?? 0)
                    : (resumen.en_periodo ?? 0)}
              </span>
              <span className="text-xs text-slate-500">
                {soloPeriodo ? 'en todo el historial' : 'con cita en el rango'}
              </span>
            </div>
            <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
              {soloPeriodo
                ? 'Filtrando por fecha en que se registró la cita o pasó a estado Cita.'
                : 'Mostrando todo el historial sin restricción de fechas.'}
            </p>
          </div>

          <div className="mt-3 pt-2.5 border-t border-slate-100 dark:border-slate-800 flex items-center justify-between gap-2">
            <span className="text-[11px] text-slate-500">Filtro de fechas:</span>
            <div className="inline-flex bg-slate-100 dark:bg-slate-800 p-0.5 rounded-lg text-[11px] font-semibold">
              <button
                type="button"
                onClick={() => setSoloPeriodo(true)}
                className={`px-2 py-1 rounded-md cursor-pointer transition-colors ${
                  soloPeriodo
                    ? 'bg-white dark:bg-[#0c121d] text-emerald-600 shadow-2xs'
                    : 'text-slate-500'
                }`}
              >
                Por fecha de cita
              </button>
              <button
                type="button"
                onClick={() => setSoloPeriodo(false)}
                className={`px-2 py-1 rounded-md cursor-pointer transition-colors ${
                  !soloPeriodo
                    ? 'bg-white dark:bg-[#0c121d] text-slate-900 dark:text-white shadow-2xs'
                    : 'text-slate-500'
                }`}
              >
                Todo historial
              </button>
            </div>
          </div>
        </div>
      </div>

      {/* Tasas de Conversión desde Cita (% Venta/Reserva y % Perdido) */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-white dark:bg-[#121a29] px-5 py-4 rounded-2xl border border-emerald-200/80 dark:border-emerald-900/50 shadow-sm flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="p-2.5 rounded-xl bg-emerald-50 text-emerald-600 dark:bg-emerald-950/60 dark:text-emerald-400">
              <CheckCircle2 size={20} />
            </span>
            <div>
              <span className="text-xs font-bold text-slate-500 uppercase tracking-wider block">
                Conversión Cita → Venta / Reserva
              </span>
              <p className="text-[11px] text-slate-500 dark:text-slate-400">
                {resumen.matriculas_desde_cita ?? 0} de {resumen.total_leads_citas ?? 0} leads con cita llegaron a venta o reserva
              </p>
            </div>
          </div>
          <span className="text-2xl font-extrabold text-emerald-600 dark:text-emerald-400 shrink-0">
            {loading && !data ? '…' : `${resumen.pct_cita_a_matricula ?? 0}%`}
          </span>
        </div>

        <div className="bg-white dark:bg-[#121a29] px-5 py-4 rounded-2xl border border-rose-200/80 dark:border-rose-900/50 shadow-sm flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <span className="p-2.5 rounded-xl bg-rose-50 text-rose-600 dark:bg-rose-950/60 dark:text-rose-400">
              <XCircle size={20} />
            </span>
            <div>
              <span className="text-xs font-bold text-slate-500 uppercase tracking-wider block">
                Caída Cita → Perdido
              </span>
              <p className="text-[11px] text-slate-500 dark:text-slate-400">
                {resumen.perdidos_desde_cita ?? 0} de {resumen.total_leads_citas ?? 0} leads con cita pasaron a perdido
              </p>
            </div>
          </div>
          <span className="text-2xl font-extrabold text-rose-600 dark:text-rose-400 shrink-0">
            {loading && !data ? '…' : `${resumen.pct_cita_a_perdido ?? 0}%`}
          </span>
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          DESGLOSES RÁPIDOS (POR ESTADO ACTUAL, POR FUENTE Y POR ASESOR)
          ───────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-6">
        {/* Desglose por Estado Actual del Lead */}
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <div>
              <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                Estado Actual de los Leads con Cita
              </h3>
              <p className="text-xs text-slate-500">
                Clic en un estado para filtrar la tabla inferior
              </p>
            </div>
            {estadoFilter && (
              <button
                type="button"
                onClick={() => setEstadoFilter('')}
                className="text-xs font-semibold text-indigo-600 hover:underline cursor-pointer"
              >
                Ver todos
              </button>
            )}
          </div>

          <div className="flex flex-wrap gap-2">
            {porEstadoActual.map((est) => {
              const active = estadoFilter === est.estado_nombre
              return (
                <button
                  key={est.estado_nombre}
                  type="button"
                  onClick={() => setEstadoFilter(active ? '' : est.estado_nombre)}
                  className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-xl text-xs font-semibold border transition-all cursor-pointer ${
                    active
                      ? 'ring-2 ring-indigo-500 shadow-xs'
                      : 'hover:bg-slate-50 dark:hover:bg-slate-800/50'
                  }`}
                  style={{
                    borderColor: `${est.estado_color}55`,
                    backgroundColor: active ? `${est.estado_color}22` : `${est.estado_color}10`,
                    color: est.estado_color,
                  }}
                >
                  <span
                    className="w-2 h-2 rounded-full shrink-0"
                    style={{ backgroundColor: est.estado_color }}
                  />
                  <span>{est.estado_nombre}</span>
                  <span className="px-1.5 py-0.5 rounded-md bg-white/80 dark:bg-slate-900/70 text-slate-800 dark:text-slate-100 font-bold text-[11px]">
                    {est.total}
                  </span>
                </button>
              )
            })}
            {!loading && porEstadoActual.length === 0 && (
              <p className="text-xs text-slate-400">Sin datos para mostrar.</p>
            )}
          </div>

          {porEstadoCita.length > 0 && (
            <div className="pt-3 border-t border-slate-100 dark:border-slate-800">
              <p className="text-[11px] font-semibold text-slate-500 uppercase tracking-wider mb-2">
                Último resultado de cita registrado
              </p>
              <div className="flex flex-wrap gap-2">
                {porEstadoCita.map((ce) => (
                  <span
                    key={ce.nombre}
                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-[11px] font-semibold border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-800/40"
                  >
                    <span
                      className="w-2 h-2 rounded-full"
                      style={{ backgroundColor: ce.color }}
                    />
                    <span className="text-slate-700 dark:text-slate-200">{ce.nombre}:</span>
                    <strong className="text-slate-900 dark:text-white">{ce.total}</strong>
                  </span>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* Desglose por Fuente */}
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Layers size={16} className="text-emerald-500" />
              <div>
                <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                  Conteo por Fuente
                </h3>
                <p className="text-xs text-slate-500">
                  Clic en una fuente para filtrar la tabla
                </p>
              </div>
            </div>
            {fuenteFilter && (
              <button
                type="button"
                onClick={() => setFuenteFilter('')}
                className="text-xs font-semibold text-indigo-600 hover:underline cursor-pointer"
              >
                Todas las fuentes
              </button>
            )}
          </div>

          <div className="max-h-52 overflow-y-auto border border-slate-100 dark:border-slate-800 rounded-xl">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 dark:bg-[#0b101b] text-slate-500 font-semibold sticky top-0">
                <tr>
                  <th className="py-2 px-3">Fuente</th>
                  <th className="py-2 px-1.5 text-center">Cita</th>
                  <th className="py-2 px-1.5 text-center">Antes</th>
                  <th className="py-2 px-1.5 text-center">Total</th>
                  <th className="py-2 px-1.5 text-center">% Venta</th>
                  <th className="py-2 px-2 text-center">% Perd.</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
                {porFuente.map((f) => {
                  const selected = fuenteFilter === f.fuente_nombre
                  const pct = resumen.total_leads_citas > 0
                    ? Math.round((f.total / resumen.total_leads_citas) * 100)
                    : 0
                  return (
                    <tr
                      key={f.fuente_nombre}
                      onClick={() => setFuenteFilter(selected ? '' : f.fuente_nombre)}
                      className={`cursor-pointer transition-colors ${
                        selected
                          ? 'bg-emerald-50 dark:bg-emerald-950/40'
                          : 'hover:bg-slate-50 dark:hover:bg-slate-800/30'
                      }`}
                    >
                      <td className="py-2 px-3 font-semibold text-slate-800 dark:text-slate-200">
                        <div>{f.fuente_nombre}</div>
                        <div className="text-[10px] font-normal text-slate-400">
                          {pct}% del total
                        </div>
                      </td>
                      <td className="py-2 px-1.5 text-center font-bold text-sky-600 dark:text-sky-400">
                        {f.con_estado_actual}
                      </td>
                      <td className="py-2 px-1.5 text-center font-bold text-purple-600 dark:text-purple-400">
                        {f.tuvieron_antes}
                      </td>
                      <td className="py-2 px-1.5 text-center font-extrabold text-slate-900 dark:text-white">
                        {f.total}
                      </td>
                      <td className="py-2 px-1.5 text-center font-bold text-emerald-600 dark:text-emerald-400">
                        <div>{f.pct_matricula ?? 0}%</div>
                        <div className="text-[10px] font-normal text-slate-400">{f.matriculas ?? 0}</div>
                      </td>
                      <td className="py-2 px-2 text-center font-bold text-rose-600 dark:text-rose-400">
                        <div>{f.pct_perdido ?? 0}%</div>
                        <div className="text-[10px] font-normal text-slate-400">{f.perdidos ?? 0}</div>
                      </td>
                    </tr>
                  )
                })}
                {!loading && porFuente.length === 0 && (
                  <tr>
                    <td colSpan={6} className="py-6 text-center text-slate-400">
                      Sin fuentes con leads en citas.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Desglose por Asesor */}
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Users size={16} className="text-indigo-500" />
              <div>
                <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                  Conteo por Asesor
                </h3>
                <p className="text-xs text-slate-500">
                  Clic en una fila para filtrar sus leads
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

          <div className="max-h-52 overflow-y-auto border border-slate-100 dark:border-slate-800 rounded-xl">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 dark:bg-[#0b101b] text-slate-500 font-semibold sticky top-0">
                <tr>
                  <th className="py-2 px-3">Asesor</th>
                  <th className="py-2 px-1.5 text-center">Cita</th>
                  <th className="py-2 px-1.5 text-center">Antes</th>
                  <th className="py-2 px-1.5 text-center">Total</th>
                  <th className="py-2 px-1.5 text-center">% Venta</th>
                  <th className="py-2 px-2 text-center">% Perd.</th>
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
                      <td className="py-2 px-3 font-semibold text-slate-800 dark:text-slate-200">
                        <div>{a.asesor_nombre}</div>
                        <div className="text-[10px] font-normal text-slate-400">
                          {a.supervisor_nombre}
                        </div>
                      </td>
                      <td className="py-2 px-1.5 text-center font-bold text-sky-600 dark:text-sky-400">
                        {a.con_estado_actual}
                      </td>
                      <td className="py-2 px-1.5 text-center font-bold text-purple-600 dark:text-purple-400">
                        {a.tuvieron_antes}
                      </td>
                      <td className="py-2 px-1.5 text-center font-extrabold text-slate-900 dark:text-white">
                        {a.total}
                      </td>
                      <td className="py-2 px-1.5 text-center font-bold text-emerald-600 dark:text-emerald-400">
                        <div>{a.pct_matricula ?? 0}%</div>
                        <div className="text-[10px] font-normal text-slate-400">{a.matriculas ?? 0}</div>
                      </td>
                      <td className="py-2 px-2 text-center font-bold text-rose-600 dark:text-rose-400">
                        <div>{a.pct_perdido ?? 0}%</div>
                        <div className="text-[10px] font-normal text-slate-400">{a.perdidos ?? 0}</div>
                      </td>
                    </tr>
                  )
                })}
                {!loading && porAsesor.length === 0 && (
                  <tr>
                    <td colSpan={6} className="py-6 text-center text-slate-400">
                      Sin asesores con leads en citas.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>

      {/* ─────────────────────────────────────────────────────────────
          TABLA LIMPIA DE LEADS CON SEGUIMIENTO DE CITAS
          ───────────────────────────────────────────────────────────── */}
      <div className="bg-white dark:bg-[#121a29] rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden">
        <div className="p-5 border-b border-slate-100 dark:border-slate-800 flex flex-col lg:flex-row lg:items-center justify-between gap-3">
          <div>
            <h2 className="text-base font-bold text-slate-900 dark:text-white flex items-center gap-2">
              <Calendar size={18} className="text-indigo-500" />
              <span>Detalle de Leads en Seguimiento a Citas</span>
              <span className="text-xs font-bold px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 dark:bg-indigo-950/60 dark:text-indigo-300">
                {filteredLeads.length}
              </span>
            </h2>
            <p className="text-xs text-slate-500 mt-0.5">
              Vista limpia de leads que tienen actualmente o tuvieron previamente el estado de citas
            </p>
          </div>

          <div className="flex flex-wrap items-center gap-2">
            {/* Buscador */}
            <div className="relative">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Buscar lead, tel. o asesor..."
                className="pl-8 pr-3 py-1.5 text-xs bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 rounded-xl outline-none focus:ring-2 focus:ring-indigo-500/30 w-56"
              />
            </div>

            {/* Pills situación */}
            <div className="inline-flex bg-slate-100 dark:bg-slate-800 p-1 rounded-xl text-xs font-semibold">
              {[
                { id: 'todos', label: `Todos (${leads.length})` },
                { id: 'actual', label: `Estado cita (${resumen.con_estado_cita_actual ?? 0})` },
                { id: 'historico', label: `Tuvieron cita (${resumen.tuvieron_estado_cita_antes ?? 0})` },
              ].map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setSituacionFilter(tab.id)}
                  className={`px-2.5 py-1 rounded-lg transition-colors cursor-pointer ${
                    situacionFilter === tab.id
                      ? 'bg-white dark:bg-[#0c121d] text-indigo-600 shadow-2xs'
                      : 'text-slate-500 hover:text-slate-800'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {(estadoFilter || asesorRowFilter || fuenteFilter || situacionFilter !== 'todos' || search) && (
              <button
                type="button"
                onClick={() => {
                  setEstadoFilter('')
                  setAsesorRowFilter('')
                  setFuenteFilter('')
                  setSituacionFilter('todos')
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
                <th className="py-3 px-3">Asesor / Equipo</th>
                <th className="py-3 px-3">Situación Cita</th>
                <th className="py-3 px-3">Estado Actual</th>
                <th className="py-3 px-3">Última Cita Programada</th>
                <th className="py-3 px-3 text-center">Citas Reg.</th>
                <th className="py-3 px-3">1ra Vez en Cita</th>
                <th className="py-3 px-3 text-right">Ficha</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60 font-medium">
              {filteredLeads.map((l) => {
                const esActual = l.situacion_cita === 'actual'
                return (
                  <tr
                    key={l.id}
                    className="hover:bg-slate-50/80 dark:hover:bg-slate-800/30 transition-colors"
                  >
                    <td className="py-3 px-4">
                      <div className="font-bold text-slate-900 dark:text-white">
                        {l.nombre || `Lead #${l.id}`}
                      </div>
                      <div className="text-[11px] text-slate-400 font-mono">
                        {l.telefono || 'Sin teléfono'} · {l.fuente_nombre}
                      </div>
                    </td>

                    <td className="py-3 px-3">
                      <div className="font-semibold text-slate-700 dark:text-slate-300">
                        {l.asesor_nombre || 'Sin asignar'}
                      </div>
                      <div className="text-[10px] text-slate-400">
                        {l.supervisor_nombre || 'Sin supervisor'} · {l.sede_nombre}
                      </div>
                    </td>

                    <td className="py-3 px-3">
                      <span
                        className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-bold border ${
                          esActual
                            ? 'bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950/50 dark:text-sky-300 dark:border-sky-800'
                            : 'bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-950/50 dark:text-purple-300 dark:border-purple-800'
                        }`}
                      >
                        {esActual ? 'Tiene estado cita' : 'Tuvo estado cita'}
                      </span>
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
                      {l.ultima_fecha_cita ? (
                        <div>
                          <div className="font-semibold text-slate-800 dark:text-slate-200">
                            {formatDateTimeLima(l.ultima_fecha_cita)}
                          </div>
                          <div className="flex items-center gap-1.5 mt-0.5">
                            {l.tipo_cita && (
                              <span className="text-[10px] text-slate-400">{l.tipo_cita}</span>
                            )}
                            {l.cita_estado_nombre && (
                              <span
                                className="text-[10px] font-bold px-1.5 py-0.2 rounded"
                                style={{
                                  backgroundColor: `${l.cita_estado_color || '#3B82F6'}20`,
                                  color: l.cita_estado_color || '#3B82F6',
                                }}
                              >
                                {l.cita_estado_nombre}
                              </span>
                            )}
                          </div>
                        </div>
                      ) : (
                        <span className="text-slate-400">Sin fecha registrada</span>
                      )}
                    </td>

                    <td className="py-3 px-3 text-center font-bold text-slate-700 dark:text-slate-300">
                      {l.total_citas_registradas ?? 0}
                    </td>

                    <td className="py-3 px-3 text-[11px] text-slate-500">
                      {formatDateTimeLima(l.primera_vez_cita_at)}
                    </td>

                    <td className="py-3 px-3 text-right">
                      <button
                        type="button"
                        onClick={() => navigate(`/leads/${l.id}`)}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg bg-slate-100 hover:bg-indigo-50 text-slate-700 hover:text-indigo-700 dark:bg-slate-800 dark:text-slate-200 dark:hover:bg-indigo-950/60 text-xs font-semibold transition-colors cursor-pointer"
                        title="Abrir ficha del lead"
                      >
                        <span>Ver</span>
                        <ExternalLink size={12} />
                      </button>
                    </td>
                  </tr>
                )
              })}
              {!loading && filteredLeads.length === 0 && (
                <tr>
                  <td colSpan={8} className="py-10 text-center text-slate-400">
                    No se encontraron leads con estado de cita (actual o histórico) para los filtros seleccionados.
                  </td>
                </tr>
              )}
              {loading && filteredLeads.length === 0 && (
                <tr>
                  <td colSpan={8} className="py-10 text-center text-slate-400">
                    Cargando seguimiento de citas…
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
