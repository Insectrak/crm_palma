/**
 * ReportesV2.jsx — 5 reportes profesionales de clase mundial.
 * V070.103
 *
 * Tabs (role-aware):
 *   - Llamadas (asesor+)
 *   - Leadtime (asesor+)
 *   - Embudo (supervisor+)
 *   - Control (supervisor+)
 *   - Estrategico (admin)
 *
 * Cada tab es un sub-componente que recibe data + isLoading.
 * El fetch lazy se hace al entrar al tab (no se piden todos al cargar).
 */
import { useState, useEffect, useCallback, useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts'
import {
  Phone, Clock, TrendingUp, AlertTriangle, Star, AlertCircle,
  RefreshCw, ChevronDown, Gauge, Grid3X3,
} from 'lucide-react'
import useAuthStore from '@/store/authStore'
import {
  fetchEficienciaLlamadas, fetchLeadtime, fetchFunnel,
  fetchControl, fetchEstrategico, fetchStageVelocity, fetchCohortMensual,
} from '@/lib/reportesV2'

/* ── Utilidades ──────────────────────────────────────────────────────────── */

const PERIODS = [
  { label: '7 dias',   dias: 7  },
  { label: '30 dias',  dias: 30 },
  { label: '90 dias',  dias: 90 },
]

function daysAgo(n) {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}
const today = () => new Date().toISOString().slice(0, 10)

function fmtSeg(seg) {
  const n = Math.round(Number(seg) || 0)
  const min = Math.floor(n / 60)
  const sec = n % 60
  return `${min}:${String(sec).padStart(2, '0')}`
}

function PctBadge({ value }) {
  if (value == null) return <span className="text-gray-400 text-xs">—</span>
  const v = parseFloat(value)
  const cls = v >= 70 ? 'bg-green-100 text-green-700'
            : v >= 40 ? 'bg-amber-100 text-amber-700'
                      : 'bg-red-100 text-red-700'
  return <span className={`px-2 py-0.5 rounded text-xs font-semibold ${cls} tabular-nums`}>{v.toFixed(1)}%</span>
}

function KpiCard({ label, value, sub, icon: Icon, tone = 'indigo' }) {
  const tones = {
    indigo: 'from-indigo-500/10 text-indigo-700 border-indigo-100',
    green:  'from-green-500/10  text-green-700  border-green-100',
    amber:  'from-amber-500/10  text-amber-700  border-amber-100',
    red:    'from-red-500/10    text-red-700    border-red-100',
    blue:   'from-blue-500/10   text-blue-700   border-blue-100',
  }
  return (
    <div className={`p-4 rounded-xl border bg-gradient-to-br to-white ${tones[tone] || tones.indigo}`}>
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs uppercase tracking-wide opacity-70">{label}</span>
        {Icon && <Icon size={16} className="opacity-60" />}
      </div>
      <div className="text-2xl font-bold tabular-nums">{value}</div>
      {sub && <div className="text-xs opacity-60 mt-1">{sub}</div>}
    </div>
  )
}

/* ── Reportes ─────────────────────────────────────────────────────────────── */

function ReporteLlamadas({ data }) {
  if (!data) return null
  const { kpis = {}, por_asesor = [], por_calidad = [] } = data
  const CALIDAD_COLORS = { CALIENTE: '#DC2626', TIBIO: '#D97706', FRIO: '#2563EB', SIN_CLASIFICAR: '#6B7280' }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Llamadas" value={kpis.total_llamadas ?? 0} icon={Phone} tone="indigo" />
        <KpiCard label="Dur. promedio" value={fmtSeg(kpis.duracion_prom_seg)} icon={Clock} tone="blue" />
        <KpiCard label="% Efectivas" value={`${kpis.pct_efectivas ?? 0}%`} icon={TrendingUp} tone="green" />
        <KpiCard label="% Cortas" value={`${kpis.pct_cortas ?? 0}%`} icon={AlertTriangle} tone="amber" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {por_calidad.length > 0 && (
          <div className="bg-white border border-gray-100 rounded-2xl p-4">
            <h3 className="font-semibold text-gray-800 mb-3">Por calidad de lead</h3>
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie
                  data={por_calidad}
                  dataKey="llamadas"
                  nameKey="calidad"
                  cx="50%" cy="50%"
                  innerRadius={50} outerRadius={80}
                  label={(d) => `${d.calidad}: ${d.llamadas}`}
                >
                  {por_calidad.map((c, i) => (
                    <Cell key={i} fill={CALIDAD_COLORS[c.calidad] || '#6B7280'} />
                  ))}
                </Pie>
                <Tooltip />
                <Legend />
              </PieChart>
            </ResponsiveContainer>
          </div>
        )}

        <div className="bg-white border border-gray-100 rounded-2xl p-4">
          <h3 className="font-semibold text-gray-800 mb-3">Ranking de asesores</h3>
          {por_asesor.length === 0 ? (
            <p className="text-sm text-gray-400">Sin datos</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-xs text-gray-500 uppercase border-b">
                  <tr>
                    <th className="text-left py-2">Asesor</th>
                    <th className="text-right">Llamadas</th>
                    <th className="text-right">Dur.</th>
                    <th className="text-right">Efect.</th>
                  </tr>
                </thead>
                <tbody>
                  {por_asesor.map(a => (
                    <tr key={a.asesor_id} className="border-b last:border-0">
                      <td className="py-2 truncate max-w-[200px]">{a.asesor}</td>
                      <td className="text-right tabular-nums">{a.total_llamadas}</td>
                      <td className="text-right tabular-nums">{fmtSeg(a.duracion_prom_seg)}</td>
                      <td className="text-right"><PctBadge value={a.pct_efectivas} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// V095.2 — Semaforo SLA de clase mundial: <60min verde, 60-480min amarillo, >480min rojo.
// Aplicamos al P50 del asesor (mediana), no al promedio. La mediana es el SLA real.
function slaColor(minutos) {
  if (minutos == null) return { bg: 'bg-gray-100', dot: 'bg-gray-300', text: 'text-gray-500', label: 'Sin datos' }
  if (minutos < 60)    return { bg: 'bg-emerald-50', dot: 'bg-emerald-500', text: 'text-emerald-700', label: 'En SLA' }
  if (minutos < 480)   return { bg: 'bg-amber-50',   dot: 'bg-amber-500',   text: 'text-amber-700',   label: 'Tarde' }
  return { bg: 'bg-rose-50', dot: 'bg-rose-500', text: 'text-rose-700', label: 'Crítico' }
}

function ReporteLeadtime({ data }) {
  if (!data) return null
  const { distribucion = {}, por_asesor = [] } = data
  const tot = distribucion.total || 1
  const buckets = [
    { label: '< 5 min',   value: distribucion.menos_5min,    color: '#16A34A' },
    { label: '5-30 min',  value: distribucion.entre_5_30min, color: '#22C55E' },
    { label: '30-60 min', value: distribucion.entre_30_60min, color: '#D97706' },
    { label: '> 60 min',  value: distribucion.mas_60min,     color: '#DC2626' },
  ]
  // V095.2 — semaforo global basado en P50 (no en promedio).
  const semaforoGlobal = slaColor(distribucion.minutos_p50_global)

  return (
    <div className="space-y-4">
      {/* V095.2 — Banner SLA al tope: el supervisor lo ve apenas entra.
          Es el primer dato que un manager mira cada manana — patron estandar
          de la industria. */}
      <div className={`${semaforoGlobal.bg} border border-gray-100 rounded-2xl p-4 flex items-center gap-4`}>
        <div className={`w-3 h-3 rounded-full ${semaforoGlobal.dot} shadow-sm shrink-0`} />
        <div className="flex-1">
          <div className={`text-sm font-semibold ${semaforoGlobal.text}`}>
            SLA — Tiempo a primer contacto · {semaforoGlobal.label}
          </div>
          <div className="text-xs text-gray-500 mt-0.5">
            Umbrales: &lt;60 min verde · 60-480 min amarillo · &gt;480 min rojo. Calculado sobre el P50 (mediana real, no promedio).
          </div>
        </div>
        <div className="flex items-center gap-4 text-right">
          <div>
            <div className="text-[11px] text-gray-500 uppercase tracking-wide">Mediana</div>
            <div className="text-lg font-bold text-gray-800 tabular-nums">{distribucion.minutos_p50_global ?? 0}<span className="text-sm font-normal text-gray-500">m</span></div>
          </div>
          <div>
            <div className="text-[11px] text-gray-500 uppercase tracking-wide">P90</div>
            <div className="text-lg font-bold text-gray-800 tabular-nums">{distribucion.minutos_p90_global ?? 0}<span className="text-sm font-normal text-gray-500">m</span></div>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Mediana (P50)" value={`${distribucion.minutos_p50_global ?? 0} min`} icon={Clock} tone="indigo" />
        <KpiCard label="P90 (los lentos)" value={`${distribucion.minutos_p90_global ?? 0} min`} icon={Clock} tone="amber" />
        <KpiCard label="Leads medidos" value={distribucion.total ?? 0} icon={TrendingUp} tone="blue" />
        <KpiCard
          label="% en <5 min"
          value={`${Math.round(100 * (distribucion.menos_5min || 0) / tot)}%`}
          icon={Star} tone="green"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-white border border-gray-100 rounded-2xl p-4">
          <h3 className="font-semibold text-gray-800 mb-3">Distribucion por rangos</h3>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={buckets} layout="vertical" margin={{ left: 20 }}>
              <XAxis type="number" />
              <YAxis dataKey="label" type="category" />
              <Tooltip />
              <Bar dataKey="value" radius={[0, 6, 6, 0]}>
                {buckets.map((b, i) => <Cell key={i} fill={b.color} />)}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="bg-white border border-gray-100 rounded-2xl p-4">
          <h3 className="font-semibold text-gray-800 mb-3">Por asesor (mas rapido primero)</h3>
          {por_asesor.length === 0 ? (
            <p className="text-sm text-gray-400">Sin datos</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-xs text-gray-500 uppercase border-b">
                <tr>
                  <th className="text-left py-2">SLA</th>
                  <th className="text-left">Asesor</th>
                  <th className="text-right">Leads</th>
                  <th className="text-right" title="Mediana — 50% de sus leads se contactan más rápido que este tiempo.">P50</th>
                  <th className="text-right" title="P90 — el 90% se contacta en este tiempo o menos. El 10% más lento se queda fuera.">P90</th>
                  <th className="text-right">Prom.</th>
                </tr>
              </thead>
              <tbody>
                {por_asesor.map(a => {
                  const sla = slaColor(a.minutos_p50)
                  return (
                    <tr key={a.asesor_id} className="border-b last:border-0">
                      <td className="py-2">
                        <span className={`inline-flex w-2.5 h-2.5 rounded-full ${sla.dot}`} title={sla.label} />
                      </td>
                      <td className="truncate max-w-[140px]">{a.asesor}</td>
                      <td className="text-right tabular-nums">{a.leads_asignados}</td>
                      <td className={`text-right tabular-nums font-semibold ${sla.text}`}>{a.minutos_p50 ?? 0}m</td>
                      <td className="text-right tabular-nums text-gray-500">{a.minutos_p90 ?? 0}m</td>
                      <td className="text-right tabular-nums text-gray-400">{a.minutos_prom}m</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

function ReporteFunnel({ data }) {
  if (!data) return null
  const { etapas_funnel = [], total_perdidos = 0, tasa_global_pct = 0, por_canal = [] } = data
  const max = etapas_funnel[0]?.total || 1

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <KpiCard label="Tasa global" value={`${tasa_global_pct}%`} icon={TrendingUp} tone="green" />
        <KpiCard label="Total leads" value={max} icon={TrendingUp} tone="indigo" />
        <KpiCard label="Perdidos" value={total_perdidos} icon={AlertTriangle} tone="red" />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-white border border-gray-100 rounded-2xl p-4">
          <h3 className="font-semibold text-gray-800 mb-4">Embudo de conversión</h3>
          {/* V070.108 — patrón estándar: nombre del estado SIEMPRE visible
              en columna fija a la izquierda. La barra ocupa el espacio
              restante y NO se corta el texto del estado aunque el valor
              sea chico. Patron usado en reportes profesionales del mercado. */}
          <div className="space-y-2">
            {etapas_funnel.map((e, idx) => {
              const widthPct = Math.max(4, 100 * e.total / max)
              return (
                <div key={e.id} className="flex items-center gap-3">
                  {/* Columna fija: nombre del estado (140px) */}
                  <div className="w-32 flex-shrink-0 text-sm font-medium text-gray-700 text-right truncate" title={e.nombre}>
                    {e.nombre}
                  </div>
                  {/* Barra proporcional al valor con número adentro */}
                  <div className="flex-1 min-w-0">
                    <div
                      className="rounded-md text-white px-3 py-2 text-sm font-bold tabular-nums shadow-sm"
                      style={{ width: `${widthPct}%`, backgroundColor: e.color_hex || '#6366F1' }}
                    >
                      {e.total}
                    </div>
                  </div>
                  {/* Tasa de conversión vs etapa anterior */}
                  <div className="w-24 flex-shrink-0 text-right">
                    {idx > 0 && (
                      <span className="text-xs text-gray-500 whitespace-nowrap tabular-nums">
                        {e.tasa_conversion}%
                      </span>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>

        <div className="bg-white border border-gray-100 rounded-2xl p-4">
          {/* V095.3 — Source ROI ampliado. CRMs profesionales muestran 3
              tasas porque la sola "tasa de cierre" enganha cuando el
              volumen es bajo. El gerente decide la pauta del mes mirando
              estas 3 columnas juntas. */}
          <h3 className="font-semibold text-gray-800 mb-1">ROI por canal</h3>
          <p className="text-xs text-gray-500 mb-3">
            Contacto → Calificación → Cierre. Las 3 tasas juntas revelan
            si el canal trae volumen muerto o interés real.
          </p>
          {por_canal.length === 0 ? (
            <p className="text-sm text-gray-400">Sin datos</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-xs text-gray-500 uppercase border-b">
                <tr>
                  <th className="text-left py-2">Canal</th>
                  <th className="text-right">Total</th>
                  <th className="text-right" title="% de leads con al menos 1 contacto real. Mide si el teléfono/email es válido.">Contacto</th>
                  <th className="text-right" title="% de leads que avanzaron a un estado de calidad (orden ≥ 3, no perdidos). Mide interés real.">Calificación</th>
                  <th className="text-right" title="% de leads matriculados (cerrados).">Cierre</th>
                </tr>
              </thead>
              <tbody>
                {por_canal.map((c, i) => (
                  <tr key={i} className="border-b last:border-0">
                    <td className="py-2">{c.fuente}</td>
                    <td className="text-right tabular-nums">{c.total}</td>
                    <td className="text-right"><PctBadge value={c.tasa_contacto_pct} /></td>
                    <td className="text-right"><PctBadge value={c.tasa_calificacion_pct} /></td>
                    <td className="text-right"><PctBadge value={c.tasa_cierre_pct} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>
    </div>
  )
}

function HeatmapWeb({ data }) {
  const DIAS = ['Dom', 'Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab']
  const matrix = Array.from({ length: 24 }, () => Array(7).fill(0))
  let max = 0
  data.forEach(({ dia_semana, hora, total }) => {
    if (hora >= 0 && hora < 24 && dia_semana >= 0 && dia_semana <= 6) {
      matrix[hora][dia_semana] = total
      if (total > max) max = total
    }
  })
  max = max || 1

  return (
    <div className="overflow-x-auto">
      <div className="inline-block min-w-full">
        <div className="grid grid-cols-8 gap-0.5 text-[10px]">
          <div />
          {DIAS.map(d => <div key={d} className="text-center text-gray-500 font-semibold">{d}</div>)}
          {matrix.map((row, h) => (
            <>
              <div key={`h${h}`} className="text-right text-gray-400 pr-1">{h}:00</div>
              {row.map((val, d) => {
                const opacity = val === 0 ? 0.05 : 0.15 + 0.85 * (val / max)
                return (
                  <div
                    key={`${h}-${d}`}
                    className="aspect-square rounded-sm flex items-center justify-center"
                    style={{ backgroundColor: `rgba(99, 102, 241, ${opacity})` }}
                    title={`${DIAS[d]} ${h}:00 - ${val} contactos`}
                  >
                    {val > 0 && <span className="text-white text-[9px] font-bold">{val}</span>}
                  </div>
                )
              })}
            </>
          ))}
        </div>
      </div>
    </div>
  )
}

function ReporteControl({ data }) {
  if (!data) return null
  const { leads_sin_contactar = 0, dias_sin_contacto = 7, ranking = [], heatmap = [], por_campana = [] } = data

  return (
    <div className="space-y-4">
      {leads_sin_contactar > 0 && (
        <div className="bg-red-50 border border-red-200 rounded-xl p-4 flex items-center gap-3">
          <AlertCircle size={24} className="text-red-600 flex-shrink-0" />
          <div>
            <div className="font-semibold text-red-800">
              {leads_sin_contactar} leads sin contactar hace mas de {dias_sin_contacto} dias
            </div>
            <div className="text-sm text-red-600">Revisar inmediatamente para evitar fuga</div>
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-white border border-gray-100 rounded-2xl p-4">
          <h3 className="font-semibold text-gray-800 mb-3">Ranking asesores (por matrículas)</h3>
          {ranking.length === 0 ? (
            <p className="text-sm text-gray-400">Sin datos</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-xs text-gray-500 uppercase border-b">
                <tr>
                  <th className="text-left py-2">Asesor</th>
                  <th className="text-right">Leads</th>
                  <th className="text-right">Matrículas</th>
                  <th className="text-right">Tasa</th>
                </tr>
              </thead>
              <tbody>
                {ranking.map(r => (
                  <tr key={r.asesor_id} className="border-b last:border-0">
                    <td className="py-2 truncate max-w-[150px]">{r.asesor}</td>
                    <td className="text-right tabular-nums">{r.total_leads}</td>
                    <td className="text-right tabular-nums">{r.cerrados}</td>
                    <td className="text-right"><PctBadge value={r.tasa_conversion_pct} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="bg-white border border-gray-100 rounded-2xl p-4">
          <h3 className="font-semibold text-gray-800 mb-3">Actividad por dia y hora</h3>
          {heatmap.length === 0 ? (
            <p className="text-sm text-gray-400">Sin datos</p>
          ) : (
            <HeatmapWeb data={heatmap} />
          )}
        </div>
      </div>

      {por_campana.length > 0 && (
        <div className="bg-white border border-gray-100 rounded-2xl p-4">
          <h3 className="font-semibold text-gray-800 mb-3">Performance por campana</h3>
          <table className="w-full text-sm">
            <thead className="text-xs text-gray-500 uppercase border-b">
              <tr>
                <th className="text-left py-2">Campana</th>
                <th className="text-right">Leads</th>
                <th className="text-right">Matrículas</th>
                <th className="text-right">Calidad</th>
                <th className="text-right">Tasa</th>
              </tr>
            </thead>
            <tbody>
              {por_campana.map((c, i) => (
                <tr key={i} className="border-b last:border-0">
                  <td className="py-2 truncate max-w-[250px]">{c.campana}</td>
                  <td className="text-right tabular-nums">{c.total}</td>
                  <td className="text-right tabular-nums">{c.cerrados}</td>
                  <td className="text-right tabular-nums">{c.calidad_score}</td>
                  <td className="text-right"><PctBadge value={c.tasa_cierre_pct} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function ReporteEstrategico({ data }) {
  if (!data) return null
  const { top_asesores = [], leads_fuga = {}, tiempo_muerto = [], mejores_horarios = [] } = data
  const DIAS = ['Dom', 'Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab']

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-white border border-gray-100 rounded-2xl p-4">
          <h3 className="font-semibold text-gray-800 mb-3 flex items-center gap-2">
            <Star size={18} className="text-amber-500" /> Top asesores del periodo
          </h3>
          {top_asesores.length === 0 ? (
            <p className="text-sm text-gray-400">Sin datos</p>
          ) : (
            <div className="space-y-2">
              {top_asesores.map((a, i) => {
                const medal = i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : `${i + 1}.`
                return (
                  <div key={a.asesor_id} className="flex items-center gap-3 py-2 border-b last:border-0">
                    <span className="text-lg w-8 text-center">{medal}</span>
                    <div className="flex-1">
                      <div className="font-medium">{a.asesor}</div>
                      <div className="text-xs text-gray-500">{a.total_leads} leads · {a.cerrados} cerrados</div>
                    </div>
                    <PctBadge value={a.tasa_cierre_pct} />
                  </div>
                )
              })}
            </div>
          )}
        </div>

        <div className="bg-white border-2 border-red-200 rounded-2xl p-4">
          <h3 className="font-semibold text-red-700 mb-1 flex items-center gap-2">
            <AlertTriangle size={18} /> Leads fuga ({leads_fuga.total ?? 0})
          </h3>
          <p className="text-xs text-gray-500 mb-3">Leads que nunca fueron contactados</p>
          {!leads_fuga.muestra || leads_fuga.muestra.length === 0 ? (
            <p className="text-sm text-gray-400">No hay leads fuga 🎉</p>
          ) : (
            <table className="w-full text-sm">
              <tbody>
                {(leads_fuga.muestra || []).slice(0, 10).map(l => (
                  <tr key={l.lead_id} className="border-b last:border-0">
                    <td className="py-2">
                      <div className="font-medium">{l.nombre}</div>
                      <div className="text-xs text-gray-500">{l.asesor} · {l.fuente}</div>
                    </td>
                    <td className="text-right">
                      <span className="text-sm font-bold text-red-600 tabular-nums">{l.dias_antiguedad}d</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-white border border-gray-100 rounded-2xl p-4">
          <h3 className="font-semibold text-gray-800 mb-3 flex items-center gap-2">
            <Clock size={18} className="text-indigo-500" /> Tiempo muerto entre contactos
          </h3>
          {tiempo_muerto.length === 0 ? (
            <p className="text-sm text-gray-400">Sin datos</p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-xs text-gray-500 uppercase border-b">
                <tr>
                  <th className="text-left py-2">Asesor</th>
                  <th className="text-right">Gap prom.</th>
                  <th className="text-right">Maximo</th>
                  <th className="text-right">Contactos</th>
                </tr>
              </thead>
              <tbody>
                {tiempo_muerto.slice(0, 10).map(t => (
                  <tr key={t.asesor_id} className="border-b last:border-0">
                    <td className="py-2 truncate max-w-[150px]">{t.asesor}</td>
                    <td className="text-right tabular-nums">{t.horas_gap_prom}h</td>
                    <td className="text-right tabular-nums">{Math.round(t.gap_maximo_h)}h</td>
                    <td className="text-right tabular-nums">{t.contactos_total}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        <div className="bg-white border border-gray-100 rounded-2xl p-4">
          <h3 className="font-semibold text-gray-800 mb-3 flex items-center gap-2">
            <TrendingUp size={18} className="text-green-500" /> Mejores horarios para cerrar
          </h3>
          {mejores_horarios.length === 0 ? (
            <p className="text-sm text-gray-400">Sin datos</p>
          ) : (
            <div className="space-y-2">
              {mejores_horarios.map((h, i) => (
                <div key={i} className="flex items-center gap-3 py-2 border-b last:border-0">
                  <div className="text-2xl">{['🥇', '🥈', '🥉', '4.', '5.'][i]}</div>
                  <div className="flex-1">
                    <div className="font-medium">{DIAS[h.dia_semana]} {h.hora}:00 - {h.hora + 1}:00</div>
                    <div className="text-xs text-gray-500">
                      {h.total_contactos} contactos · {h.cierres} cierres
                    </div>
                  </div>
                  <PctBadge value={h.tasa_cierre_pct} />
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

/* ── Pantalla principal ──────────────────────────────────────────────────── */

const TABS_CONFIG = [
  { key: 'llamadas',    label: 'Llamadas',    icon: Phone,         roles: ['asesor', 'supervisor', 'admin'] },
  { key: 'leadtime',    label: 'Leadtime',    icon: Clock,         roles: ['asesor', 'supervisor', 'admin'] },
  { key: 'funnel',      label: 'Embudo',      icon: TrendingUp,    roles: ['supervisor', 'admin'] },
  { key: 'velocity',    label: 'Velocidad',   icon: Gauge,         roles: ['supervisor', 'admin'] },
  { key: 'control',     label: 'Control',     icon: AlertTriangle, roles: ['supervisor', 'admin'] },
  { key: 'cohort',      label: 'Cohorts',     icon: Grid3X3,       roles: ['supervisor', 'admin'] },
  { key: 'estrategico', label: 'Estrategico', icon: Star,          roles: ['admin'] },
]

export default function ReportesV2() {
  const { user } = useAuthStore()
  const role = user?.role || 'asesor'

  const availableTabs = useMemo(
    () => TABS_CONFIG.filter(t => t.roles.includes(role)),
    [role]
  )

  // V095.7 — el catalogo de reportes (ReportesHome) navega con ?tab=<key>
  // hacia esta pagina. Sin esto, todas las cards aterrizaban en la pestana
  // default (llamadas) sin importar a cual hizo click el user.
  const [searchParams, setSearchParams] = useSearchParams()
  const tabFromUrl = searchParams.get('tab')
  const initialTab = (tabFromUrl && availableTabs.some(t => t.key === tabFromUrl))
    ? tabFromUrl
    : (availableTabs[0]?.key || 'llamadas')

  const [tab, setTab] = useState(initialTab)

  // Sincronizar ?tab= cuando el user cambia de pestana — URL shareable.
  useEffect(() => {
    const current = searchParams.get('tab')
    if (current !== tab) {
      const next = new URLSearchParams(searchParams)
      next.set('tab', tab)
      setSearchParams(next, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])
  const [periodIdx, setPeriodIdx] = useState(1) // default 30d
  const [data, setData] = useState({})
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const dateRange = useMemo(() => {
    const d = PERIODS[periodIdx].dias
    return { fecha_desde: daysAgo(d), fecha_hasta: today() }
  }, [periodIdx])

  const FETCHERS = useMemo(() => ({
    llamadas:    fetchEficienciaLlamadas,
    leadtime:    fetchLeadtime,
    funnel:      fetchFunnel,
    control:     fetchControl,
    estrategico: fetchEstrategico,
    velocity:    fetchStageVelocity,
    cohort:      fetchCohortMensual,
  }), [])

  const load = useCallback(async () => {
    const fn = FETCHERS[tab]
    if (!fn) return
    setError('')
    setLoading(true)
    try {
      const result = await fn(dateRange)
      setData(prev => ({ ...prev, [tab]: result }))
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || 'No se pudo cargar el reporte')
    } finally {
      setLoading(false)
    }
  }, [tab, dateRange, FETCHERS])

  useEffect(() => { load() }, [load])

  const TabIcon = TABS_CONFIG.find(t => t.key === tab)?.icon || Phone

  return (
    <div className="space-y-5 max-w-7xl">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-xl font-bold text-gray-900">Reportes Analytics</h1>
          <p className="text-sm text-gray-500">Eficiencia · Leadtime · Embudo · Control · Estratégico</p>
        </div>

        <div className="flex items-center gap-2">
          {PERIODS.map((p, i) => (
            <button
              key={p.label}
              onClick={() => setPeriodIdx(i)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium transition ${
                periodIdx === i
                  ? 'bg-indigo-600 text-white'
                  : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'
              }`}
            >
              {p.label}
            </button>
          ))}
          <button
            onClick={load}
            disabled={loading}
            className="p-2 rounded-lg bg-white border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50"
            title="Refrescar"
          >
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-gray-200 overflow-x-auto">
        {availableTabs.map(t => {
          const Icon = t.icon
          const active = tab === t.key
          return (
            <button
              key={t.key}
              onClick={() => setTab(t.key)}
              className={`flex items-center gap-2 px-4 py-2.5 text-sm font-medium border-b-2 transition whitespace-nowrap ${
                active
                  ? 'border-indigo-600 text-indigo-600'
                  : 'border-transparent text-gray-500 hover:text-gray-800'
              }`}
            >
              <Icon size={15} /> {t.label}
            </button>
          )
        })}
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-3 flex items-center gap-2">
          <AlertCircle size={16} /> {error}
        </div>
      )}

      {loading && !data[tab] ? (
        <div className="bg-white border border-gray-100 rounded-2xl p-12 text-center text-gray-400">
          <TabIcon size={40} className="mx-auto mb-3 opacity-30" />
          <p>Cargando reporte...</p>
        </div>
      ) : (
        <>
          {tab === 'llamadas'    && <ReporteLlamadas    data={data.llamadas} />}
          {tab === 'leadtime'    && <ReporteLeadtime    data={data.leadtime} />}
          {tab === 'funnel'      && <ReporteFunnel      data={data.funnel} />}
          {tab === 'velocity'    && <ReporteVelocity    data={data.velocity} />}
          {tab === 'control'     && <ReporteControl     data={data.control} />}
          {tab === 'cohort'      && <ReporteCohort      data={data.cohort} />}
          {tab === 'estrategico' && <ReporteEstrategico data={data.estrategico} />}
        </>
      )}
    </div>
  )
}

/* ── V095.4 — Stage Velocity (tiempo en cada etapa del funnel) ─────────── */
function ReporteVelocity({ data }) {
  if (!data) return null
  const { etapas = [] } = data
  // Color del badge segun stage aging — heuristica conservadora:
  // <7d verde, 7-30d amarillo, >30d rojo. El cliente puede ajustar.
  const ageColor = (dias) => {
    if (dias == null) return { bg: 'bg-gray-50', text: 'text-gray-400' }
    if (dias < 7)     return { bg: 'bg-emerald-50', text: 'text-emerald-700' }
    if (dias < 30)    return { bg: 'bg-amber-50',   text: 'text-amber-700' }
    return { bg: 'bg-rose-50', text: 'text-rose-700' }
  }
  const totalLeads = etapas.reduce((s, e) => s + (e.total_leads || 0), 0)
  return (
    <div className="space-y-4">
      <div className="bg-indigo-50 border border-indigo-100 rounded-2xl p-4 flex items-start gap-3">
        <Gauge className="text-indigo-600 mt-0.5 shrink-0" size={18} />
        <div className="text-sm text-indigo-900">
          <div className="font-semibold mb-0.5">Tiempo en cada etapa del pipeline</div>
          <div className="text-xs text-indigo-700">
            Días promedio que llevan los leads en su estado actual. Los estados con mayor antigüedad
            son tus cuellos de botella — ahí se está atascando el pipeline.
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiCard label="Leads en pipeline" value={totalLeads.toLocaleString()} icon={TrendingUp} tone="indigo" />
        <KpiCard label="Etapas activas" value={etapas.length} icon={Gauge} tone="blue" />
        <KpiCard
          label="Etapa más sticky"
          value={
            etapas.length === 0
              ? '—'
              : etapas.reduce((max, e) => (e.dias_promedio > (max?.dias_promedio || 0) ? e : max), etapas[0])?.nombre || '—'
          }
          icon={AlertTriangle} tone="amber"
        />
        <KpiCard
          label="Antigüedad máxima"
          value={`${Math.max(...etapas.map(e => e.dias_max || 0), 0)} d`}
          icon={Clock} tone="red"
        />
      </div>

      <div className="bg-white border border-gray-100 rounded-2xl p-4">
        <h3 className="font-semibold text-gray-800 mb-3">Tiempo en etapa</h3>
        {etapas.length === 0 ? (
          <p className="text-sm text-gray-400">Sin datos</p>
        ) : (
          <table className="w-full text-sm">
            <thead className="text-xs text-gray-500 uppercase border-b">
              <tr>
                <th className="text-left py-2">Etapa</th>
                <th className="text-right">Leads</th>
                <th className="text-right" title="Días promedio que llevan los leads en esta etapa.">Días prom.</th>
                <th className="text-right" title="Mediana (50% de los leads tienen menos días que esto).">P50</th>
                <th className="text-right" title="El lead más antiguo en esta etapa.">Máx.</th>
              </tr>
            </thead>
            <tbody>
              {etapas.map(e => {
                const c = ageColor(e.dias_promedio)
                return (
                  <tr key={e.id} className="border-b last:border-0">
                    <td className="py-2">
                      <div className="flex items-center gap-2">
                        <span
                          className="w-2.5 h-2.5 rounded-full shrink-0"
                          style={{ background: e.color_hex || '#94a3b8' }}
                        />
                        <span className="font-medium text-gray-800">{e.nombre}</span>
                      </div>
                    </td>
                    <td className="text-right tabular-nums">{e.total_leads}</td>
                    <td className="text-right">
                      <span className={`px-2 py-0.5 rounded-md tabular-nums font-semibold ${c.bg} ${c.text}`}>
                        {e.dias_promedio} d
                      </span>
                    </td>
                    <td className="text-right tabular-nums text-gray-600">{e.dias_p50} d</td>
                    <td className="text-right tabular-nums text-gray-400">{e.dias_max} d</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  )
}

/* ── V095.5 — Cohort heatmap mensual ───────────────────────────────────── */
function ReporteCohort({ data }) {
  if (!data) return null
  const { estados = [], celdas = [] } = data
  // Indexar celdas por (mes, estado_id) y calcular total por mes para %.
  const byMes = {}
  const totalPorMes = {}
  celdas.forEach(c => {
    const key = c.mes
    if (!byMes[key]) byMes[key] = {}
    byMes[key][c.estado_id] = c.total
    totalPorMes[key] = (totalPorMes[key] || 0) + c.total
  })
  const meses = Object.keys(byMes).sort().reverse()  // mas recientes arriba

  // Escala de intensidad: relativa al maximo del periodo, no por mes,
  // para que el ojo compare absolutamente.
  const maxAbs = Math.max(...celdas.map(c => c.total), 1)
  const cellColor = (n) => {
    if (!n) return 'bg-gray-50 text-gray-300'
    const intensity = Math.min(1, n / maxAbs)
    if (intensity > 0.66) return 'bg-indigo-500 text-white font-semibold'
    if (intensity > 0.33) return 'bg-indigo-300 text-indigo-900'
    return 'bg-indigo-100 text-indigo-700'
  }

  const fmtMes = (iso) => {
    if (!iso) return ''
    const [y, m] = iso.split('-')
    const NOMBRES = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
    return `${NOMBRES[parseInt(m, 10) - 1]} ${y.slice(2)}`
  }

  return (
    <div className="space-y-4">
      <div className="bg-emerald-50 border border-emerald-100 rounded-2xl p-4 flex items-start gap-3">
        <Grid3X3 className="text-emerald-600 mt-0.5 shrink-0" size={18} />
        <div className="text-sm text-emerald-900">
          <div className="font-semibold mb-0.5">Análisis de cohortes mensuales</div>
          <div className="text-xs text-emerald-700">
            Filas = mes en que ingresaron los leads. Columnas = en qué estado están HOY.
            Lectura: "Los leads que entraron en marzo, dónde están ahora?"
          </div>
        </div>
      </div>

      {meses.length === 0 ? (
        <div className="bg-white border border-gray-100 rounded-2xl p-12 text-center text-gray-400">
          Sin datos en el periodo seleccionado.
        </div>
      ) : (
        <div className="bg-white border border-gray-100 rounded-2xl p-4 overflow-x-auto">
          <table className="w-full text-sm border-separate" style={{ borderSpacing: 2 }}>
            <thead>
              <tr>
                <th className="text-left text-xs text-gray-500 uppercase pr-3 pb-2 font-medium">Mes ingreso</th>
                {estados.map(e => (
                  <th key={e.id} className="text-center text-[11px] font-medium text-gray-600 pb-2 px-1 min-w-[68px]"
                      title={e.nombre}>
                    <div className="flex flex-col items-center gap-0.5">
                      <span className="w-2 h-2 rounded-full" style={{ background: e.color_hex || '#94a3b8' }} />
                      <span className="truncate max-w-[70px]">{e.nombre}</span>
                    </div>
                  </th>
                ))}
                <th className="text-center text-[11px] font-medium text-gray-600 pb-2 px-1">Total</th>
              </tr>
            </thead>
            <tbody>
              {meses.map(m => (
                <tr key={m}>
                  <td className="pr-3 py-1.5 font-medium text-gray-800 whitespace-nowrap">{fmtMes(m)}</td>
                  {estados.map(e => {
                    const n = byMes[m]?.[e.id] || 0
                    const pct = totalPorMes[m] ? Math.round(100 * n / totalPorMes[m]) : 0
                    return (
                      <td key={e.id} className="px-1 py-1.5 text-center">
                        <div
                          className={`rounded-md py-2 text-sm tabular-nums ${cellColor(n)}`}
                          title={n > 0 ? `${n} leads (${pct}% del mes)` : 'Sin leads'}
                        >
                          {n || ''}
                        </div>
                      </td>
                    )
                  })}
                  <td className="px-1 py-1.5 text-center text-xs text-gray-500 font-semibold tabular-nums">
                    {totalPorMes[m] || 0}
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
