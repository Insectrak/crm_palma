/**
 * Dashboards.jsx — V070.109 — Vistas combinadas patrón estándar.
 *
 * Lista de dashboards predefinidos + viewer que carga TODA la data del
 * dashboard de una sola vez (reutiliza endpoints de reportes_v2).
 *
 * Cada dashboard combina N components (KPI cards, rankings, heatmaps,
 * funnels) en una vista coherente para un rol especifico.
 */
import { useEffect, useMemo, useState, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell,
} from 'recharts'
import {
  Users, Star, AlertTriangle, TrendingUp, Clock, Phone,
  RefreshCw, ChevronLeft,
} from 'lucide-react'
import api from '@/lib/api'
import {
  fetchControl, fetchFunnel, fetchEstrategico, fetchLeadtime, fetchEficienciaLlamadas,
} from '@/lib/reportesV2'

const PERIODS = [
  // V094.4 — agregado "Hoy" para consistencia con el selector del /inicio
  // (V096) y para que el supervisor pueda ver el dia de operacion sin
  // entrar a otra pantalla. Default sigue siendo 30 dias (mas significativo).
  { label: 'Hoy',     dias: 1  },
  { label: '7 dias',  dias: 7  },
  { label: '30 dias', dias: 30 },
  { label: '90 dias', dias: 90 },
]
function daysAgo(n) { const d = new Date(); d.setDate(d.getDate() - n); return d.toISOString().slice(0, 10) }
const today = () => new Date().toISOString().slice(0, 10)

const ICONS = { users: Users, star: Star }

const SOURCE_FETCHERS = {
  control:     fetchControl,
  funnel:      fetchFunnel,
  estrategico: fetchEstrategico,
  leadtime:    fetchLeadtime,
  llamadas:    fetchEficienciaLlamadas,
}

function PctBadge({ value }) {
  if (value == null) return <span className="text-gray-400 text-xs">—</span>
  const v = parseFloat(value)
  const cls = v >= 70 ? 'bg-green-100 text-green-700'
            : v >= 40 ? 'bg-amber-100 text-amber-700'
                      : 'bg-red-100 text-red-700'
  return <span className={`px-2 py-0.5 rounded text-xs font-semibold ${cls} tabular-nums`}>{v.toFixed(1)}%</span>
}

function KpiTile({ label, value, tone = 'indigo' }) {
  const tones = {
    indigo: 'from-indigo-500/10 text-indigo-700 border-indigo-100',
    success: 'from-green-500/10 text-green-700 border-green-100',
    danger:  'from-red-500/10 text-red-700 border-red-100',
  }
  return (
    <div className={`p-5 rounded-2xl border bg-gradient-to-br to-white ${tones[tone] || tones.indigo}`}>
      <div className="text-xs uppercase tracking-wide opacity-70 mb-2">{label}</div>
      <div className="text-3xl font-bold tabular-nums">{value}</div>
    </div>
  )
}

function FunnelChart({ etapas }) {
  if (!etapas?.length) return <p className="text-sm text-gray-400">Sin datos</p>
  // V094.4 — fix overflow visual: la base debe ser el MAX de TODAS las
  // etapas, no solo etapas[0] (Nuevo). Antes: si Contactado (11) > Nuevo (7),
  // widthPct = 100*11/7 = 157% → barra naranja desbordaba el contenedor.
  // Ahora: la etapa con mas leads ocupa 100%, las otras proporcional.
  // Min 4% para que etapas con 0 leads aun sean visibles como "linea fina".
  const max = Math.max(...etapas.map(e => e.total || 0), 1)
  return (
    <div className="space-y-2">
      {etapas.map((e, idx) => {
        const widthPct = Math.min(100, Math.max(4, 100 * e.total / max))
        return (
          <div key={e.id} className="flex items-center gap-3">
            <div className="w-32 flex-shrink-0 text-sm font-medium text-gray-700 text-right truncate" title={e.nombre}>
              {e.nombre}
            </div>
            <div className="flex-1 min-w-0">
              <div
                className="rounded-md text-white px-3 py-2 text-sm font-bold tabular-nums shadow-sm"
                style={{ width: `${widthPct}%`, backgroundColor: e.color_hex || '#6366F1' }}
              >
                {e.total}
              </div>
            </div>
            <div className="w-16 flex-shrink-0 text-right">
              {idx > 0 && (
                <span className="text-xs text-gray-500 whitespace-nowrap tabular-nums">{e.tasa_conversion}%</span>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

function HeatmapWeb({ data }) {
  if (!data?.length) return <p className="text-sm text-gray-400">Sin datos</p>
  const DIAS = ['D', 'L', 'M', 'M', 'J', 'V', 'S']
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
      <div className="grid grid-cols-8 gap-0.5 text-[10px] min-w-[280px]">
        <div />
        {DIAS.map((d, i) => <div key={i} className="text-center text-gray-500 font-semibold">{d}</div>)}
        {matrix.map((row, h) => (
          <>
            <div key={`h${h}`} className="text-right text-gray-400 pr-1">{h}h</div>
            {row.map((val, d) => {
              const opacity = val === 0 ? 0.05 : 0.15 + 0.85 * (val / max)
              return (
                <div
                  key={`${h}-${d}`}
                  className="aspect-square rounded-sm flex items-center justify-center"
                  style={{ backgroundColor: `rgba(99, 102, 241, ${opacity})` }}
                  title={`${DIAS[d]} ${h}h: ${val}`}
                >
                  {val > 0 && val < 10 && <span className="text-white text-[8px] font-bold">{val}</span>}
                </div>
              )
            })}
          </>
        ))}
      </div>
    </div>
  )
}

function RankingList({ items }) {
  if (!items?.length) return <p className="text-sm text-gray-400">Sin datos</p>
  return (
    <div className="space-y-2">
      {items.slice(0, 10).map((r, i) => (
        <div key={r.asesor_id || i} className="flex items-center gap-3 py-1.5 border-b last:border-0">
          <span className="text-sm font-bold text-gray-400 w-6 text-right tabular-nums">{i + 1}</span>
          <div className="flex-1 truncate">
            <div className="text-sm font-medium text-gray-800 truncate">{r.asesor}</div>
            <div className="text-xs text-gray-500">{r.total_leads ?? r.total ?? 0} leads · {r.cerrados ?? 0} cerrados</div>
          </div>
          <PctBadge value={r.tasa_conversion_pct ?? r.tasa_cierre_pct} />
        </div>
      ))}
    </div>
  )
}

function FugaList({ data }) {
  if (!data?.muestra?.length) {
    return (
      <div className="text-center py-6">
        <div className="text-3xl mb-2">🎉</div>
        <p className="text-sm text-gray-500">No hay leads fuga</p>
      </div>
    )
  }
  return (
    <div className="space-y-1">
      {data.muestra.slice(0, 8).map(l => (
        <div key={l.lead_id} className="flex items-center gap-2 py-1.5 border-b last:border-0">
          <div className="flex-1 truncate">
            <div className="text-sm font-medium text-gray-800 truncate">{l.nombre}</div>
            <div className="text-xs text-gray-500 truncate">{l.asesor} · {l.fuente}</div>
          </div>
          <span className="text-sm font-bold text-red-600 tabular-nums">{l.dias_antiguedad}d</span>
        </div>
      ))}
      {data.total > 8 && (
        <div className="text-xs text-gray-500 text-center pt-2">
          + {data.total - 8} más
        </div>
      )}
    </div>
  )
}

function ChannelsList({ items }) {
  if (!items?.length) return <p className="text-sm text-gray-400">Sin datos</p>
  return (
    <table className="w-full text-sm">
      <thead className="text-xs text-gray-500 uppercase border-b">
        <tr>
          <th className="text-left py-2">Canal</th>
          <th className="text-right">Total</th>
          <th className="text-right">Cerrados</th>
          <th className="text-right">Tasa</th>
        </tr>
      </thead>
      <tbody>
        {items.slice(0, 10).map((c, i) => (
          <tr key={i} className="border-b last:border-0">
            <td className="py-1.5">{c.fuente}</td>
            <td className="text-right tabular-nums">{c.total}</td>
            <td className="text-right tabular-nums">{c.cerrados}</td>
            <td className="text-right"><PctBadge value={c.tasa_cierre_pct} /></td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}

function HorariosList({ items }) {
  const DIAS = ['Dom', 'Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab']
  if (!items?.length) return <p className="text-sm text-gray-400">Sin datos</p>
  return (
    <div className="space-y-1.5">
      {items.map((h, i) => (
        <div key={i} className="flex items-center gap-3 py-1.5 border-b last:border-0">
          <span className="text-base">{['🥇', '🥈', '🥉', '4.', '5.'][i]}</span>
          <div className="flex-1">
            <div className="text-sm font-medium">{DIAS[h.dia_semana]} {h.hora}:00 - {h.hora + 1}:00</div>
            <div className="text-xs text-gray-500">{h.total_contactos} contactos · {h.cierres} cierres</div>
          </div>
          <PctBadge value={h.tasa_cierre_pct} />
        </div>
      ))}
    </div>
  )
}

function DashboardCard({ component, data }) {
  const sourceData = data?.[component.source]
  const fieldValue = sourceData?.[component.field]
  const boxCls = 'bg-white border border-gray-100 rounded-2xl p-4'
  const boxDanger = 'bg-white border-2 border-red-200 rounded-2xl p-4'
  const h3Cls = 'font-semibold mb-3 text-gray-800'
  const h3Danger = 'font-semibold mb-3 text-red-700'

  switch (component.type) {
    case 'kpi': {
      const display = component.field.includes('pct') ? `${fieldValue ?? 0}%` : (fieldValue ?? 0)
      return <KpiTile label={component.label} value={display} tone={component.tone} />
    }
    case 'ranking':
    case 'top':
      return <div className={boxCls}><h3 className={h3Cls}>{component.label}</h3><RankingList items={fieldValue} /></div>
    case 'funnel':
      return <div className={boxCls}><h3 className={h3Cls}>{component.label}</h3><FunnelChart etapas={fieldValue} /></div>
    case 'heatmap':
      return <div className={boxCls}><h3 className={h3Cls}>{component.label}</h3><HeatmapWeb data={fieldValue} /></div>
    case 'fuga':
      return <div className={boxDanger}><h3 className={h3Danger}>{component.label}</h3><FugaList data={fieldValue} /></div>
    case 'channels':
      return <div className={boxCls}><h3 className={h3Cls}>{component.label}</h3><ChannelsList items={fieldValue} /></div>
    case 'horarios':
      return <div className={boxCls}><h3 className={h3Cls}>{component.label}</h3><HorariosList items={fieldValue} /></div>
    default:
      return null
  }
}

function DashboardView({ dashboard, onBack }) {
  const [periodIdx, setPeriodIdx] = useState(1)
  const [data, setData] = useState({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const dateRange = useMemo(() => ({
    fecha_desde: daysAgo(PERIODS[periodIdx].dias),
    fecha_hasta: today(),
  }), [periodIdx])

  const load = useCallback(async () => {
    setError('')
    setLoading(true)
    // Determinar que sources necesitamos cargar (unicos)
    const sources = [...new Set(dashboard.components.map(c => c.source))]
    try {
      const results = await Promise.all(
        sources.map(s => {
          const fn = SOURCE_FETCHERS[s]
          return fn ? fn(dateRange).catch(() => null) : null
        })
      )
      const newData = {}
      sources.forEach((s, i) => { newData[s] = results[i] })
      setData(newData)
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Error al cargar dashboard')
    } finally {
      setLoading(false)
    }
  }, [dashboard, dateRange])

  useEffect(() => { load() }, [load])

  // Separar KPIs (top) de los demas components (grid abajo)
  const kpis = dashboard.components.filter(c => c.type === 'kpi')
  const others = dashboard.components.filter(c => c.type !== 'kpi')

  return (
    <div className="space-y-5 max-w-7xl">
      <div className="flex items-center gap-4 flex-wrap">
        <button onClick={onBack} className="p-2 rounded-lg hover:bg-gray-100" title="Volver">
          <ChevronLeft size={18} />
        </button>
        <div className="flex-1">
          <h1 className="text-xl font-bold text-gray-900">{dashboard.name}</h1>
          <p className="text-sm text-gray-500">{dashboard.description}</p>
        </div>
        <div className="flex items-center gap-2">
          {PERIODS.map((p, i) => (
            <button
              key={p.label}
              onClick={() => setPeriodIdx(i)}
              className={`px-3 py-1.5 rounded-lg text-sm font-medium ${
                periodIdx === i ? 'bg-indigo-600 text-white' : 'bg-white border border-gray-200 text-gray-600 hover:bg-gray-50'
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

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-3">
          {error}
        </div>
      )}

      {loading && Object.keys(data).length === 0 ? (
        <div className="bg-white border border-gray-100 rounded-2xl p-12 text-center text-gray-400">
          <RefreshCw size={32} className="mx-auto mb-3 opacity-30 animate-spin" />
          <p>Cargando dashboard...</p>
        </div>
      ) : (
        <>
          {/* KPIs row */}
          {kpis.length > 0 && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {kpis.map((c, i) => <DashboardCard key={i} component={c} data={data} />)}
            </div>
          )}
          {/* Components grid */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {others.map((c, i) => <DashboardCard key={i} component={c} data={data} />)}
          </div>
        </>
      )}
    </div>
  )
}

export default function Dashboards() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [dashboards, setDashboards] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const selectedId = searchParams.get('id')

  useEffect(() => {
    setLoading(true)
    api.get('/api/reportes/v2/dashboards-catalog')
      .then(res => setDashboards(res.data?.dashboards || []))
      .catch(err => setError(err?.response?.data?.detail || err.message || 'Error al cargar dashboards'))
      .finally(() => setLoading(false))
  }, [])

  const selected = useMemo(
    () => dashboards.find(d => d.id === selectedId),
    [dashboards, selectedId]
  )

  if (loading) return <div className="text-center py-12 text-gray-400">Cargando...</div>

  if (selected) {
    return <DashboardView dashboard={selected} onBack={() => setSearchParams({})} />
  }

  return (
    <div className="space-y-5 max-w-7xl">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Dashboards</h1>
        <p className="text-sm text-gray-500">Vistas combinadas para tomar decisiones rapidas</p>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-3">
          {error}
        </div>
      )}

      {dashboards.length === 0 ? (
        <div className="bg-white border border-gray-100 rounded-2xl p-12 text-center text-gray-400">
          <Star size={32} className="mx-auto mb-3 opacity-30" />
          <p>No hay dashboards disponibles para tu rol</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {dashboards.map(d => {
            const Icon = ICONS[d.icon] || Star
            return (
              <button
                key={d.id}
                onClick={() => setSearchParams({ id: d.id })}
                className="text-left bg-white border border-gray-100 border-l-4 border-l-indigo-500 hover:border-l-indigo-600 rounded-2xl p-5 hover:shadow-md transition-all"
              >
                <div className="w-10 h-10 rounded-lg bg-indigo-50 flex items-center justify-center text-indigo-700 mb-3">
                  <Icon size={20} />
                </div>
                <h3 className="font-semibold text-gray-900 mb-1">{d.name}</h3>
                <p className="text-sm text-gray-500 leading-relaxed">{d.description}</p>
                <div className="text-xs text-gray-400 mt-2">{d.components.length} componentes</div>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
