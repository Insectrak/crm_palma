import { useEffect, useState, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
  Download, RefreshCw, BarChart2, TrendingUp, Users, Target, Award,
  AlertCircle, Clock, Filter, Activity, Megaphone, AlertTriangle,
  Phone, Calendar, Trophy, CheckCircle2, XCircle, Timer, X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import LoadingSpinner from '@/components/shared/LoadingSpinner'
import LeadsDetalleModal from '@/components/reportes/LeadsDetalleModal'
import useAuthStore from '@/store/authStore'
import useCrmStore from '@/store/crmStore'
import api from '@/lib/api'

/* ────────────────────────────── helpers ────────────────────────────── */

function Avatar({ name }) {
  const initials = name
    ? name.split(' ').slice(0, 2).map(n => n[0]).join('').toUpperCase()
    : '?'
  const COLORS = [
    'bg-indigo-100 text-indigo-700',
    'bg-emerald-100 text-emerald-700',
    'bg-amber-100 text-amber-700',
    'bg-purple-100 text-purple-700',
    'bg-blue-100 text-blue-700',
    'bg-rose-100 text-rose-700',
  ]
  const idx = name ? name.charCodeAt(0) % COLORS.length : 0
  return (
    <span className={`inline-flex items-center justify-center w-7 h-7 rounded-full text-xs font-bold flex-shrink-0 ${COLORS[idx]}`}>
      {initials}
    </span>
  )
}

function KpiCard({ label, value, icon: Icon, gradient, subtitle, onClick }) {
  const isClickable = Boolean(onClick)
  return (
    <div
      onClick={onClick}
      className={`rounded-xl p-4 ${gradient} text-white flex items-start gap-3 ${isClickable ? 'cursor-pointer hover:shadow-lg hover:scale-[1.02] transition-all' : ''
        }`}
      title={isClickable ? 'Clic para ver detalle de leads' : undefined}
    >
      <div className="mt-0.5 p-2 rounded-lg bg-white/20 flex-shrink-0">
        <Icon size={18} />
      </div>
      <div className="min-w-0">
        <p className="text-xs font-medium text-white/75 truncate">{label}</p>
        <p className="text-2xl font-bold mt-0.5 leading-none">{value}</p>
        {subtitle && <p className="text-xs text-white/60 mt-1 truncate">{subtitle}</p>}
      </div>
    </div>
  )
}

function MiniBar({ value, max, onClick }) {
  const pct = max > 0 ? Math.min(100, Math.round((value / max) * 100)) : 0
  return (
    <div className="flex items-center gap-2">
      {onClick && value > 0 ? (
        <button
          onClick={onClick}
          className="text-sm font-semibold text-gray-800 w-8 text-right flex-shrink-0 hover:text-indigo-600 hover:underline cursor-pointer"
          title="Ver todos los leads"
        >
          {value}
        </button>
      ) : (
        <span className="text-sm font-semibold text-gray-800 w-8 text-right flex-shrink-0">{value}</span>
      )}
      <div className="flex-1 bg-gray-100 rounded-full h-1.5 min-w-[40px]">
        <div className="bg-indigo-400 h-1.5 rounded-full transition-all" style={{ width: `${pct}%` }} />
      </div>
    </div>
  )
}

function PctBadge({ value }) {
  if (value == null) return <span className="text-gray-300 text-sm">—</span>
  const v = parseFloat(value)
  const cls =
    v >= 30 ? 'bg-emerald-50 text-emerald-700 ring-emerald-100' :
      v >= 10 ? 'bg-amber-50 text-amber-700 ring-amber-100' :
        'bg-red-50 text-red-600 ring-red-100'
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-semibold ring-1 ${cls}`}>
      {v.toFixed(1)}%
    </span>
  )
}

function Num({ value, warn, onClick }) {
  if (!value || value === 0) return <span className="text-gray-300 text-sm">0</span>
  const cls = warn === 'green' ? 'text-emerald-600 font-semibold' :
    warn === 'red' ? 'text-red-500 font-semibold' :
      warn === 'amber' ? 'text-amber-600 font-semibold' :
        'text-gray-700 font-medium'
  if (onClick) {
    return (
      <button
        onClick={onClick}
        className={`text-sm ${cls} hover:underline hover:scale-110 px-1.5 py-0.5 rounded hover:bg-indigo-50/70 transition-all cursor-pointer inline-flex items-center justify-center font-bold`}
        title="Ver lista de leads"
      >
        {value}
      </button>
    )
  }
  return <span className={`text-sm ${cls}`}>{value}</span>
}

const SOURCE_META = {
  'facebook': { label: 'Facebook', cls: 'bg-blue-100 text-blue-700' },
  'fb': { label: 'Facebook', cls: 'bg-blue-100 text-blue-700' },
  'instagram': { label: 'Instagram', cls: 'bg-pink-100 text-pink-700' },
  'ig': { label: 'Instagram', cls: 'bg-pink-100 text-pink-700' },
  'tiktok': { label: 'TikTok', cls: 'bg-gray-800 text-white' },
  'tt': { label: 'TikTok', cls: 'bg-gray-800 text-white' },
  'tt mensaje': { label: 'TikTok', cls: 'bg-gray-800 text-white' },
  'whatsapp': { label: 'WhatsApp', cls: 'bg-green-100 text-green-700' },
  'wa': { label: 'WhatsApp', cls: 'bg-green-100 text-green-700' },
  'wa mensaje': { label: 'WhatsApp', cls: 'bg-green-100 text-green-700' },
  'web': { label: 'Web', cls: 'bg-indigo-100 text-indigo-700' },
  'referido': { label: 'Referido', cls: 'bg-amber-100 text-amber-800' },
  'manual': { label: 'Manual', cls: 'bg-gray-100 text-gray-700' },
  'historico': { label: 'Histórico', cls: 'bg-indigo-100 text-indigo-700' },
  'histórico': { label: 'Histórico', cls: 'bg-indigo-100 text-indigo-700' },
  'sin fuente': { label: 'Sin fuente', cls: 'bg-gray-50 text-gray-400 ring-1 ring-gray-200' },
}

function SourceBadge({ name }) {
  const key = (name || '').toLowerCase()
  const meta = SOURCE_META[key] || { label: name || 'Otro', cls: 'bg-gray-100 text-gray-600' }
  return (
    <span className={`inline-block px-2.5 py-0.5 rounded-full text-xs font-semibold ${meta.cls}`}>
      {meta.label}
    </span>
  )
}

function HoursBadge({ value }) {
  if (value == null) return <span className="text-gray-300 text-sm">—</span>
  const v = parseFloat(value)
  const cls =
    v <= 1 ? 'bg-emerald-50 text-emerald-700 ring-emerald-100' :
      v <= 24 ? 'bg-amber-50 text-amber-700 ring-amber-100' :
        'bg-red-50 text-red-600 ring-red-100'
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-semibold ring-1 ${cls}`}>
      {v < 1 ? `${Math.round(v * 60)}min` : `${v.toFixed(1)}h`}
    </span>
  )
}

function DaysBadge({ value }) {
  if (value == null) return <span className="text-gray-300 text-sm">—</span>
  const v = parseInt(value)
  const cls =
    v <= 3 ? 'bg-amber-50 text-amber-700 ring-amber-100' :
      v <= 7 ? 'bg-orange-50 text-orange-700 ring-orange-100' :
        'bg-red-50 text-red-700 ring-red-100'
  return (
    <span className={`inline-block px-2 py-0.5 rounded-full text-xs font-semibold ring-1 ${cls}`}>
      {v}d
    </span>
  )
}

function StateBadge({ nombre, colorHex }) {
  const bg = colorHex ? `${colorHex}20` : '#f3f4f6'
  const text = colorHex || '#6b7280'
  return (
    <span
      className="inline-block px-2.5 py-0.5 rounded-full text-xs font-semibold"
      style={{ backgroundColor: bg, color: text }}
    >
      {nombre}
    </span>
  )
}

/* ── SVG Line Chart — Actividad Diaria ── */
/* ── Funnel Chart (HTML layout: label left, proportional bar, drop-off right) ── */
function FunnelChart({ etapas }) {
  if (!etapas || etapas.length === 0) return null
  const maxTotal = Math.max(...etapas.map(e => e.total), 1)
  const totalLeads = etapas[0]?.total || 0

  return (
    <div className="space-y-2">
      {etapas.map((e, i) => {
        const widthPct = Math.max((e.total / maxTotal) * 100, 2)
        const color = e.color_hex || '#6366f1'
        const shareOfTotal = totalLeads > 0 ? Math.round((e.total / totalLeads) * 1000) / 10 : 0
        const conv = e.conversion_desde_anterior
        const convColor = conv == null ? '#9ca3af'
          : conv >= 50 ? '#059669'
            : conv >= 20 ? '#d97706'
              : '#dc2626'

        return (
          <div key={e.estado} className="flex items-center gap-3">
            {/* Etiqueta fija a la izquierda */}
            <div className="w-32 shrink-0 text-right">
              <div className="text-sm font-semibold text-gray-800 truncate" title={e.estado}>
                {e.estado}
              </div>
              <div className="text-[11px] text-gray-400">
                {shareOfTotal}% del total
              </div>
            </div>

            {/* V041.5 — barra proporcional sin borderRight 3px solido.
                Antes esa "raya" caia encima del numero/texto cuando la
                barra era angosta (ej Calificado con 1 lead = ~3% width)
                y dificultaba leer los valores. Ahora barra con gradiente
                limpio y un minimo de 4% de width para que un solo lead
                siga siendo visible sin tapar nada. */}
            <div className="flex-1 relative h-10 bg-gray-50 rounded-md border border-gray-100 overflow-hidden">
              <div
                className="absolute left-0 top-0 bottom-0 transition-all duration-500"
                style={{
                  width: `${Math.max(widthPct, 4)}%`,
                  background: `linear-gradient(90deg, ${color}45, ${color}15)`,
                }}
              />
              <div className="relative h-full flex items-center px-3">
                <span className="text-base font-bold" style={{ color }}>
                  {e.total.toLocaleString('es-PE')}
                </span>
                {i > 0 && e.total > 0 && (
                  <span className="ml-2 text-[11px] text-gray-500 font-medium">
                    lead{e.total !== 1 ? 's' : ''}
                  </span>
                )}
              </div>
            </div>

            {/* Drop-off a la derecha */}
            <div className="w-24 shrink-0 text-left">
              {conv != null ? (
                <>
                  <div className="text-sm font-bold" style={{ color: convColor }}>
                    {conv}%
                  </div>
                  <div className="text-[10px] text-gray-400 leading-tight">
                    del anterior
                  </div>
                </>
              ) : (
                <div className="text-[11px] text-gray-300 italic">inicio</div>
              )}
            </div>
          </div>
        )
      })}
    </div>
  )
}

const today = new Date().toISOString().slice(0, 10)
function daysAgo(n) {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}

/* ──────────────────────────── main page ────────────────────────────── */

// V070.107 / V070.108 — Limpieza completa de tabs duplicados.
// Operativos = vistas crudas / listados / KPIs simples (qué pasó).
// Analytics  = analisis calculados + insights (qué significa).
//
// Tabs quitados de Operativos:
//   - leadtime, tiempo-respuesta -> Analytics Leadtime
//   - heatmap, estancados, campanas -> Analytics Control
//   - funnel -> Analytics Embudo
//   - tiempo-muerto -> Analytics Estratégico
//   - llamadas -> Analytics Llamadas (eficiencia agregada) Y la pantalla
//                 principal /llamadas del sidebar (registro detallado)
const TABS = [
  { key: 'asesores', label: 'Por Asesor', icon: Users, teamOnly: true },
  { key: 'ranking', label: 'Ranking', icon: TrendingUp, teamOnly: true },
  { key: 'fuentes', label: 'Por Fuente', icon: TrendingUp, teamOnly: false },
  // V095.9 — Reactivamos la tab "Por Campaña". El render ya existia
  // (KpiCards + tabla con % Contact / % Calif / % Ganados + 1er Contacto)
  // pero estaba huerfano: alguien removio la entrada de TABS asi que la UI
  // no la mostraba. Endpoint /api/reportes/campanas devolvia data pero
  // nadie podia abrirlo.
  { key: 'campanas', label: 'Por Campaña', icon: Megaphone, teamOnly: true },
  { key: 'citas', label: 'Citas', icon: Calendar, teamOnly: true },
]

// Tabs donde el filtro por asesor está habilitado.
// - En 'asesores', 'citas', 'ranking': filtrado client-side (las filas contienen asesor_id/id).
// - En 'fuentes', 'campanas': filtrado server-side vía query param `asesor_id`.
const TABS_FILTRABLES_POR_ASESOR = new Set([
  'asesores', 'citas', 'ranking', 'fuentes', 'campanas',
])

export default function Reportes() {
  const { user } = useAuthStore()
  const role = user?.role || 'asesor'
  const canSeeTeam = role === 'admin' || role === 'supervisor'

  const visibleTabs = TABS.filter(t => !t.teamOnly || canSeeTeam)
  const defaultTab = canSeeTeam ? 'asesores' : 'fuentes'

  // V095.7 — el catalogo de reportes (ReportesHome) navega con ?tab=<key>
  // hacia esta pagina. Sin esto, todas las cards aterrizaban en la pestana
  // default (asesores) sin importar a cual hizo click el user.
  const [searchParams, setSearchParams] = useSearchParams()
  const tabFromUrl = searchParams.get('tab')
  const initialTab = (tabFromUrl && visibleTabs.some(t => t.key === tabFromUrl))
    ? tabFromUrl
    : defaultTab

  const [activeTab, setActiveTab] = useState(initialTab)

  // Sincronizar ?tab= cuando el user cambia de pestana clickeando — asi el
  // URL siempre refleja la vista actual y es shareable / bookmarkable.
  useEffect(() => {
    const current = searchParams.get('tab')
    if (current !== activeTab) {
      const next = new URLSearchParams(searchParams)
      next.set('tab', activeTab)
      setSearchParams(next, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab])
  const [data, setData] = useState(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)
  const [isExporting, setIsExporting] = useState(false)
  const [fechaDesde, setFechaDesde] = useState(daysAgo(30))
  const [fechaHasta, setFechaHasta] = useState(today)
  const [diasEstancados, setDiasEstancados] = useState(7)
  // Filtro por rol — compartido entre tabs Por Asesor y Ranking.
  // Opciones: 'asesor' | 'supervisor' | 'equipo' | 'all'
  // 'equipo' es solo valido en Ranking — agrupa por supervisor + asesores.
  const [roleFilter, setRoleFilter] = useState('asesor')
  // Métrica del Ranking — 'matriculas' | 'contactabilidad' | 'conversion' | 'citas' | 'llamadas'
  const [rankingMetrica, setRankingMetrica] = useState('matriculas')
  // Filtro de fuentes para el Ranking — '' (todas) | nombre de fuente | 'Sin fuente'
  const [selectedFuente, setSelectedFuente] = useState('')
  // Regla de excepción: fuentes excluidas para el ranking
  const [fuentesExcluidas, setFuentesExcluidas] = useState([])

  // Catálogos (fuentes) desde crmStore
  const { fuentes, loadCatalogs } = useCrmStore()
  useEffect(() => {
    loadCatalogs()
  }, [loadCatalogs])

  // Filtro global por equipo y asesor
  const [asesoresList, setAsesoresList] = useState([])
  const [selectedAsesor, setSelectedAsesor] = useState('')
  const [equiposList, setEquiposList] = useState([])
  const [selectedEquipo, setSelectedEquipo] = useState('')

  // Modal de lista detallada de leads al hacer clic en cualquier métrica
  const [leadsModal, setLeadsModal] = useState({ open: false, context: null })

  const handleOpenLeadsModal = useCallback((params) => {
    setLeadsModal({
      open: true,
      context: {
        fecha_desde: fechaDesde,
        fecha_hasta: fechaHasta,
        ...params,
      },
    })
  }, [fechaDesde, fechaHasta])

  useEffect(() => {
    let cancelled = false
    api.get('/auth/users')
      .then(r => {
        if (cancelled) return
        const users = r.data || []
        const list = users
          .filter(u => u.is_active !== false && (u.role === 'asesor' || u.role === 'supervisor'))
          .map(u => ({
            id: u.id,
            nombre: [u.first_name, u.last_name].filter(Boolean).join(' ') || u.email,
            role: u.role,
          }))
          .sort((a, b) => a.nombre.localeCompare(b.nombre))
        setAsesoresList(list)

        const sups = users
          .filter(u => u.is_active !== false && u.role === 'supervisor')
          .map(u => ({
            supervisor_id: u.id,
            supervisor_nombre: [u.first_name, u.last_name].filter(Boolean).join(' ') || u.email,
          }))
          .sort((a, b) => a.supervisor_nombre.localeCompare(b.supervisor_nombre))
        setEquiposList(sups)
      })
      .catch(() => { /* silencioso: sin lista, el dropdown queda con default */ })
    return () => { cancelled = true }
  }, [])

  const fetchReport = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      let endpoint = ''
      const asesorQueryParam = selectedAsesor ? `&asesor_id=${selectedAsesor}` : ''
      const equipoQueryParam = selectedEquipo ? `&supervisor_id=${selectedEquipo}` : ''

      if (activeTab === 'asesores') {
        endpoint = `/api/reportes/por-asesor?fecha_desde=${fechaDesde}&fecha_hasta=${fechaHasta}${equipoQueryParam}`
      } else if (activeTab === 'fuentes') {
        endpoint = `/api/reportes/por-fuente?fecha_desde=${fechaDesde}&fecha_hasta=${fechaHasta}${asesorQueryParam}${equipoQueryParam}`
      } else if (activeTab === 'tiempo-respuesta') {
        endpoint = `/api/reportes/tiempo-respuesta?fecha_desde=${fechaDesde}&fecha_hasta=${fechaHasta}${equipoQueryParam}`
      } else if (activeTab === 'funnel') {
        endpoint = `/api/reportes/funnel?fecha_desde=${fechaDesde}&fecha_hasta=${fechaHasta}${equipoQueryParam}`
      } else if (activeTab === 'estancados') {
        endpoint = `/api/reportes/estancados?dias=${diasEstancados}${equipoQueryParam}`
      } else if (activeTab === 'campanas') {
        endpoint = `/api/reportes/campanas?fecha_desde=${fechaDesde}&fecha_hasta=${fechaHasta}${asesorQueryParam}${equipoQueryParam}`
      } else if (activeTab === 'llamadas') {
        endpoint = `/api/reportes/llamadas?fecha_desde=${fechaDesde}&fecha_hasta=${fechaHasta}${equipoQueryParam}`
      } else if (activeTab === 'citas') {
        endpoint = `/api/reportes/citas?fecha_desde=${fechaDesde}&fecha_hasta=${fechaHasta}${equipoQueryParam}`
      } else if (activeTab === 'ranking') {
        const path = roleFilter === 'equipo' ? 'ranking-equipos' : 'ranking'
        const fuenteQueryParam = selectedFuente ? `&fuente=${encodeURIComponent(selectedFuente)}` : ''
        const fuenteExcluidaParam = fuentesExcluidas.length > 0 ? `&fuente_excluida=${encodeURIComponent(fuentesExcluidas.join(','))}` : ''
        endpoint = `/api/reportes/${path}?fecha_desde=${fechaDesde}&fecha_hasta=${fechaHasta}&metrica=${rankingMetrica}${equipoQueryParam}${fuenteQueryParam}${fuenteExcluidaParam}`
      } else if (activeTab === 'leadtime') {
        endpoint = `/api/reportes/leadtime?fecha_desde=${fechaDesde}&fecha_hasta=${fechaHasta}${equipoQueryParam}`
      } else if (activeTab === 'heatmap') {
        endpoint = `/api/reportes/heatmap?fecha_desde=${fechaDesde}&fecha_hasta=${fechaHasta}&metrica=contactos${equipoQueryParam}`
      } else if (activeTab === 'tiempo-muerto') {
        endpoint = `/api/reportes/tiempo-muerto?dias=${diasEstancados}${equipoQueryParam}`
      }
      const res = await api.get(endpoint)
      setData(res.data)
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al cargar el reporte.')
    } finally {
      setIsLoading(false)
    }
  }, [activeTab, fechaDesde, fechaHasta, diasEstancados, roleFilter, rankingMetrica, selectedAsesor, selectedEquipo, selectedFuente, fuentesExcluidas])

  useEffect(() => { fetchReport() }, [fetchReport])

  const exportTypeMap = {
    'asesores': 'asesores',
    'fuentes': 'fuentes',
    'tiempo-respuesta': 'tiempo_respuesta',
    'funnel': 'funnel',
    'estancados': 'estancados',
    'campanas': 'campanas',
    'ranking': 'ranking',
  }

  const handleExport = async () => {
    setIsExporting(true)
    try {
      const tipo = exportTypeMap[activeTab] || 'asesores'
      const diasParam = activeTab === 'estancados' ? `&dias=${diasEstancados}` : ''
      const asesorParam = selectedAsesor ? `&asesor_id=${selectedAsesor}` : ''
      const equipoParam = selectedEquipo ? `&supervisor_id=${selectedEquipo}` : ''
      const rankingParams = activeTab === 'ranking' ? `&metrica=${rankingMetrica}&role_filter=${roleFilter}${selectedFuente ? `&fuente=${encodeURIComponent(selectedFuente)}` : ''}${fuentesExcluidas.length > 0 ? `&fuente_excluida=${encodeURIComponent(fuentesExcluidas.join(','))}` : ''}` : ''
      const res = await api.get(
        `/api/reportes/exportar?tipo=${tipo}&fecha_desde=${fechaDesde}&fecha_hasta=${fechaHasta}${diasParam}${asesorParam}${equipoParam}${rankingParams}`,
        { responseType: 'blob' },
      )
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `reporte_${tipo}_${fechaDesde}_${fechaHasta}.xlsx`
      a.click()
      URL.revokeObjectURL(url)
    } catch { /* silent */ }
    finally { setIsExporting(false) }
  }

  const rawRows = data?.rows || data?.etapas || data?.asesores || data?.ranking || []
  // Filtro client-side por asesor: aplica a tabs donde las filas contienen asesor_id.
  // Para 'fuentes' y 'campanas', el backend ya filtra la consulta por asesor_id a nivel SQL.
  const TABS_CLIENT_FILTER = new Set(['asesores', 'citas', 'ranking'])
  const rows = (selectedAsesor && TABS_CLIENT_FILTER.has(activeTab) && (activeTab !== 'ranking' || roleFilter !== 'equipo'))
    ? rawRows.filter(r => String(r.asesor_id || r.id || '') === String(selectedAsesor))
    : rawRows
  const resumen = data?.resumen || data?.totales || {}
  const filtroAplica = TABS_FILTRABLES_POR_ASESOR.has(activeTab)

  // Algunos tabs usan estructuras distintas a `rows` (heatmap.matriz,
  // llamadas.por_calidad). Sin esto, el empty state genérico se muestra
  // ENCIMA del contenido real → contradice al usuario ("dice que no hay
  // datos pero veo el grid lleno"). Centralizamos la decisión aquí.
  const tabHasContent = (() => {
    if (rows.length > 0) return true
    if (activeTab === 'heatmap') {
      return Array.isArray(data?.matriz)
        && data.matriz.some(row => Array.isArray(row) && row.some(v => v > 0))
    }
    if (activeTab === 'llamadas') {
      return Array.isArray(data?.por_calidad) && data.por_calidad.length > 0
    }
    return false
  })()
  const maxLeads = rows.length > 0 ? Math.max(...rows.map(r => r.total_leads || r.total || r.total_llamadas || r.total_citas || 0)) : 1

  /* ── KPI Cards adaptadas por tab ── */
  function renderKpis() {
    if (!data) return null
    if (activeTab === 'asesores') return (
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <KpiCard
          label="Total Leads"
          value={(resumen.total_leads || 0).toLocaleString('es-PE')}
          icon={Users}
          gradient="bg-gradient-to-br from-indigo-500 to-indigo-600"
          subtitle={`${data.periodo?.desde} → ${data.periodo?.hasta}`}
          onClick={() => handleOpenLeadsModal({ tipo_metrica: 'total', metricaLabel: 'Total Leads', asesor_id: selectedAsesor || undefined })}
        />
        <KpiCard
          label="Ventas"
          value={(resumen.total_ganados || 0).toLocaleString('es-PE')}
          icon={Award}
          gradient="bg-gradient-to-br from-emerald-500 to-emerald-600"
          subtitle="Ventas en el período"
          onClick={() => handleOpenLeadsModal({ tipo_metrica: 'matriculas', metricaLabel: 'Leads Venta', asesor_id: selectedAsesor || undefined })}
        />
        <KpiCard label="Tasa Conversión" value={`${resumen.tasa_conversion || 0}%`} icon={Target} gradient="bg-gradient-to-br from-amber-500 to-amber-600" subtitle="Leads → Ventas" />
        <KpiCard label="Asesores Activos" value={resumen.asesores_activos || 0} icon={BarChart2} gradient="bg-gradient-to-br from-purple-500 to-purple-600" subtitle="Con leads en el período" />
      </div>
    )
    if (activeTab === 'fuentes') return (
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <KpiCard
          label="Total Leads"
          value={(resumen.total_leads || 0).toLocaleString('es-PE')}
          icon={Users}
          gradient="bg-gradient-to-br from-indigo-500 to-indigo-600"
          subtitle={`${data.periodo?.desde} → ${data.periodo?.hasta}`}
          onClick={() => handleOpenLeadsModal({ tipo_metrica: 'total', metricaLabel: 'Total Leads', asesor_id: selectedAsesor || undefined })}
        />
        <KpiCard
          label="Ventas"
          value={(resumen.total_ganados || 0).toLocaleString('es-PE')}
          icon={Award}
          gradient="bg-gradient-to-br from-emerald-500 to-emerald-600"
          subtitle="Ventas en el período"
          onClick={() => handleOpenLeadsModal({ tipo_metrica: 'matriculas', metricaLabel: 'Leads Venta', asesor_id: selectedAsesor || undefined })}
        />
        <KpiCard label="Tasa Conversión" value={`${resumen.tasa_conversion || 0}%`} icon={Target} gradient="bg-gradient-to-br from-amber-500 to-amber-600" subtitle="Leads → Ventas" />
        <KpiCard label="Mejor Fuente" value={resumen.mejor_fuente || '—'} icon={TrendingUp} gradient="bg-gradient-to-br from-purple-500 to-purple-600" subtitle={`${resumen.fuentes_activas || 0} fuentes activas`} />
      </div>
    )
    if (activeTab === 'tiempo-respuesta') return (
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <KpiCard label="Leads con Contacto" value={(resumen.total_con_contacto || 0).toLocaleString('es-PE')} icon={Users} gradient="bg-gradient-to-br from-indigo-500 to-indigo-600" subtitle="Con primer contacto registrado" />
        <KpiCard label="SLA < 1h (equipo)" value={`${resumen.pct_equipo_1h || 0}%`} icon={Clock} gradient="bg-gradient-to-br from-emerald-500 to-emerald-600" subtitle="Respondidos en menos de 1 hora" />
        <KpiCard label="SLA < 24h (equipo)" value={`${resumen.pct_equipo_24h || 0}%`} icon={Target} gradient="bg-gradient-to-br from-amber-500 to-amber-600" subtitle="Respondidos en menos de 24 horas" />
      </div>
    )
    if (activeTab === 'funnel') return (
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <KpiCard
          label="Total Leads"
          value={(resumen.total_leads || 0).toLocaleString('es-PE')}
          icon={Users}
          gradient="bg-gradient-to-br from-indigo-500 to-indigo-600"
          subtitle={`${data.periodo?.desde} → ${data.periodo?.hasta}`}
          onClick={() => handleOpenLeadsModal({ tipo_metrica: 'total', metricaLabel: 'Total Leads', asesor_id: selectedAsesor || undefined })}
        />
        <KpiCard
          label="Ventas"
          value={(resumen.ganados || 0).toLocaleString('es-PE')}
          icon={Award}
          gradient="bg-gradient-to-br from-emerald-500 to-emerald-600"
          subtitle="Cierres confirmados"
          onClick={() => handleOpenLeadsModal({ tipo_metrica: 'matriculas', metricaLabel: 'Leads Venta', asesor_id: selectedAsesor || undefined })}
        />
        <KpiCard
          label="Leads Perdidos"
          value={(resumen.perdidos || 0).toLocaleString('es-PE')}
          icon={AlertCircle}
          gradient="bg-gradient-to-br from-red-500 to-red-600"
          subtitle="No interesado + Perdido"
          onClick={() => handleOpenLeadsModal({ tipo_metrica: 'perdidos', metricaLabel: 'Leads Perdidos', asesor_id: selectedAsesor || undefined })}
        />
      </div>
    )
    if (activeTab === 'estancados') return (
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
        <KpiCard label="Leads Estancados" value={(resumen.total_estancados || 0).toLocaleString('es-PE')} icon={AlertTriangle} gradient="bg-gradient-to-br from-red-500 to-red-600" subtitle={`Sin contacto real > ${resumen.dias_umbral || diasEstancados} días`} />
        <KpiCard label="Asesor con más" value={data.resumen_por_asesor?.[0]?.asesor || '—'} icon={Users} gradient="bg-gradient-to-br from-amber-500 to-amber-600" subtitle={`${data.resumen_por_asesor?.[0]?.cantidad || 0} leads estancados`} />
        <KpiCard label="Umbral activo" value={`${diasEstancados} días`} icon={Clock} gradient="bg-gradient-to-br from-purple-500 to-purple-600" subtitle="Ajustable en el filtro" />
      </div>
    )
    if (activeTab === 'campanas') return (
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <KpiCard label="Campañas activas" value={resumen.total_campanas || 0} icon={Megaphone} gradient="bg-gradient-to-br from-indigo-500 to-indigo-600" subtitle={`${data.periodo?.desde} → ${data.periodo?.hasta}`} />
        <KpiCard
          label="Total Leads"
          value={(resumen.total_leads || 0).toLocaleString('es-PE')}
          icon={Users}
          gradient="bg-gradient-to-br from-purple-500 to-purple-600"
          subtitle="En el período"
          onClick={() => handleOpenLeadsModal({ tipo_metrica: 'total', metricaLabel: 'Total Leads', asesor_id: selectedAsesor || undefined })}
        />
        <KpiCard
          label="Ventas"
          value={(resumen.total_ganados || 0).toLocaleString('es-PE')}
          icon={Award}
          gradient="bg-gradient-to-br from-emerald-500 to-emerald-600"
          subtitle="Ventas totales"
          onClick={() => handleOpenLeadsModal({ tipo_metrica: 'matriculas', metricaLabel: 'Leads Venta', asesor_id: selectedAsesor || undefined })}
        />
        <KpiCard label="Mejor Campaña" value={resumen.mejor_campana || '—'} icon={TrendingUp} gradient="bg-gradient-to-br from-amber-500 to-amber-600" subtitle="Por volumen de leads" />
      </div>
    )
    return null
  }

  /* ── render ── */
  return (
    <div className="space-y-5">

      {/* ── Header ── */}
      <div className="flex items-start justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Reportes</h1>
          <p className="text-sm text-gray-500 mt-0.5">Análisis de gestión y conversión de leads</p>
        </div>

        <div className="flex items-center gap-2 flex-wrap">
          {/* Filtro global por equipo y asesor */}
          {canSeeTeam && (
            <>
              <label className="text-xs text-gray-400">Equipo</label>
              <select
                value={selectedEquipo}
                onChange={e => setSelectedEquipo(e.target.value)}
                title="Filtrar métricas por equipo de supervisor"
                className="border border-gray-200 rounded-md px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 max-w-[190px]"
              >
                <option value="">Todos los equipos</option>
                {equiposList.map(eq => (
                  <option key={eq.supervisor_id} value={eq.supervisor_id}>
                    Equipo {eq.supervisor_nombre}
                  </option>
                ))}
              </select>

              <label className="text-xs text-gray-400">Asesor</label>
              <select
                value={selectedAsesor}
                onChange={e => setSelectedAsesor(e.target.value)}
                disabled={!filtroAplica}
                title={filtroAplica ? 'Filtrar tabla por asesor' : 'Este reporte no es por asesor'}
                className="border border-gray-200 rounded-md px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:bg-gray-50 disabled:text-gray-400 max-w-[180px]"
              >
                <option value="">Todos</option>
                {asesoresList.map(a => (
                  <option key={a.id} value={a.id}>{a.nombre}</option>
                ))}
              </select>
            </>
          )}
          {activeTab === 'estancados' ? (
            <>
              <label className="text-xs text-gray-400">Sin contacto &gt;</label>
              <select
                value={diasEstancados}
                onChange={e => setDiasEstancados(Number(e.target.value))}
                className="border border-gray-200 rounded-md px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              >
                {[3, 7, 14, 30].map(d => <option key={d} value={d}>{d} días</option>)}
              </select>
            </>
          ) : (
            <>
              <label className="text-xs text-gray-400">Desde</label>
              <input
                type="date" value={fechaDesde} max={fechaHasta}
                onChange={e => setFechaDesde(e.target.value)}
                className="border border-gray-200 rounded-md px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              <label className="text-xs text-gray-400">Hasta</label>
              <input
                type="date" value={fechaHasta} min={fechaDesde} max={today}
                onChange={e => setFechaHasta(e.target.value)}
                className="border border-gray-200 rounded-md px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </>
          )}
          <Button variant="outline" size="sm" onClick={fetchReport} disabled={isLoading} className="gap-1.5">
            <RefreshCw size={13} className={isLoading ? 'animate-spin' : ''} />
            Actualizar
          </Button>
          <Button variant="outline" size="sm" onClick={handleExport} disabled={isExporting || rows.length === 0} className="gap-1.5">
            <Download size={13} />
            {isExporting ? 'Exportando…' : 'Excel'}
          </Button>
        </div>
      </div>

      {/* ── KPI Cards ── */}
      {isLoading ? (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="h-20 bg-gray-100 rounded-xl animate-pulse" />
          ))}
        </div>
      ) : renderKpis()}

      {/* ── Tabs (wrap + sticky) ── */}
      {/* Patron patrón estándar Reports / panel profesional: tabs envuelven en filas
          cuando exceden el ancho, y quedan pegados arriba al hacer scroll
          (sticky). El bg slate-50 coincide con el del layout para que no
          se vea un parche blanco al scrollear. */}
      <div className="flex flex-wrap border-b border-gray-200 gap-y-1 sticky top-0 bg-slate-50 z-10 -mx-4 px-4 py-1">
        {visibleTabs.map(tab => {
          const Icon = tab.icon
          return (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`flex items-center gap-1.5 px-3 py-2 text-sm font-medium border-b-2 transition-colors -mb-px whitespace-nowrap ${activeTab === tab.key
                  ? 'border-indigo-600 text-indigo-600'
                  : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
                }`}
            >
              <Icon size={14} /> {tab.label}
            </button>
          )
        })}
      </div>

      {/* ── Content card ── */}
      <div className="bg-white rounded-xl border border-gray-100 shadow-sm overflow-hidden">

        {isLoading && (
          <div className="p-10 flex justify-center">
            <LoadingSpinner />
          </div>
        )}

        {!isLoading && error && (
          <div className="flex items-center gap-2 text-red-600 text-sm p-6">
            <AlertCircle size={16} className="flex-shrink-0" /> {error}
          </div>
        )}

        {!isLoading && !error && !tabHasContent && (
          <div className="py-16 text-center space-y-3 px-6">
            {/* Empty state premium: icono grande + mensaje principal +
                sub-mensaje contextual segun el tab. Patron patrón premium / patrón premium. */}
            <div className="w-14 h-14 mx-auto rounded-full bg-gray-100 flex items-center justify-center">
              <BarChart2 size={26} className="text-gray-400" />
            </div>
            <p className="text-base font-medium text-gray-700">
              {selectedAsesor && filtroAplica && rawRows.length > 0
                ? 'Este asesor no tiene datos en el período seleccionado'
                : 'Sin datos para el período seleccionado'}
            </p>
            {selectedAsesor && filtroAplica && rawRows.length > 0 && (
              <button
                onClick={() => setSelectedAsesor('')}
                className="text-xs text-indigo-600 hover:text-indigo-700 underline"
              >
                Quitar filtro de asesor
              </button>
            )}
            {activeTab === 'tiempo-respuesta' && (
              <p className="text-xs text-gray-500 max-w-lg mx-auto leading-relaxed">
                Este reporte requiere <strong>contactos reales registrados</strong>
                {' '}(llamada, WhatsApp, email, presencial) en el detalle del lead.
                Si el equipo solo cambia el estado de los leads sin registrar
                contacto, este reporte queda vacío. Decile a tus asesores que
                clickeen <em>Registrar contacto</em> en el detalle del lead.
              </p>
            )}
            {activeTab === 'funnel' && (
              <p className="text-xs text-gray-500 max-w-lg mx-auto leading-relaxed">
                El embudo necesita leads creados en el período seleccionado
                que hayan pasado por al menos un estado.
              </p>
            )}
            {activeTab === 'llamadas' && (
              <p className="text-xs text-gray-500 max-w-lg mx-auto leading-relaxed">
                No hay llamadas sincronizadas en el período. La APK sube
                las llamadas cada 30 min (configurable en
                <em> Configuración → Sincronización móvil</em>).
              </p>
            )}
            {activeTab === 'ranking' && (
              <p className="text-xs text-gray-500 max-w-lg mx-auto leading-relaxed">
                El ranking necesita asesores con leads en el período. Si
                acaban de empezar, ampliá el rango de fechas arriba.
              </p>
            )}
            {activeTab === 'heatmap' && (
              <p className="text-xs text-gray-500 max-w-lg mx-auto leading-relaxed">
                El heatmap usa contactos reales (llamada / WhatsApp / email)
                no cambios de estado. Si el equipo no los registra, el grid
                queda vacío.
              </p>
            )}
          </div>
        )}

        {/* ── Tab: Por Asesor ── */}
        {!isLoading && !error && rows.length > 0 && activeTab === 'asesores' && (() => {
          // Filtro client-side por rol — usa el mismo state que Ranking.
          // 'equipo' no aplica aqui (es agrupacion); se trata como 'all'.
          const effectiveFilter = roleFilter === 'equipo' ? 'all' : roleFilter
          const filteredRows = rows.filter(r =>
            effectiveFilter === 'all' ? true : (r.rol || 'asesor') === effectiveFilter
          )
          return (
            <div>
              {/* Toggle filtro por rol — mismo state que Ranking */}
              <div className="px-4 pt-4 flex items-center gap-2 flex-wrap">
                <span className="text-xs text-gray-500">Mostrar:</span>
                {[
                  { v: 'asesor', label: 'Asesores', color: 'indigo' },
                  { v: 'supervisor', label: 'Supervisores', color: 'purple' },
                  { v: 'all', label: 'Todos', color: 'gray' },
                ].map(opt => {
                  const active = effectiveFilter === opt.v
                  const colorMap = {
                    indigo: 'bg-indigo-50 text-indigo-700 border-indigo-300 ring-indigo-200',
                    purple: 'bg-purple-50 text-purple-700 border-purple-300 ring-purple-200',
                    gray: 'bg-gray-100 text-gray-700 border-gray-300 ring-gray-200',
                  }
                  return (
                    <button
                      key={opt.v}
                      onClick={() => setRoleFilter(opt.v)}
                      className={`text-xs px-3 py-1 rounded-full border font-medium transition ${active ? `${colorMap[opt.color]} ring-1` : 'bg-white text-gray-500 border-gray-200 hover:border-gray-300'
                        }`}
                    >
                      {opt.label}
                    </button>
                  )
                })}
                <span className="text-[11px] text-gray-400 ml-auto">
                  {filteredRows.length} {filteredRows.length === 1 ? 'persona' : 'personas'}
                </span>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-gray-50 border-b border-gray-100">
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide sticky left-0 bg-gray-50">Asesor</th>
                      <th className="text-left px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide min-w-[120px]">Total</th>
                      <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Contactados</th>
                      <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Calificados</th>
                      <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Negociación</th>
                      <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Ventas</th>
                      <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Perdidos</th>
                      <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Sin contactar</th>
                      <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Conversión</th>
                      <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Contactabilidad</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {filteredRows.map((row, i) => (
                      <tr key={i} className="hover:bg-indigo-50/30 transition-colors">
                        <td className="px-4 py-3 sticky left-0 bg-white">
                          <div className="flex items-center gap-2.5">
                            <Avatar name={row.nombre_completo} />
                            <span className="font-medium text-gray-800 whitespace-nowrap">{row.nombre_completo}</span>
                            {row.rol === 'supervisor' && (
                              <span className="text-[9px] bg-purple-50 text-purple-700 border border-purple-200 px-1 rounded font-semibold">SUPERVISOR</span>
                            )}
                          </div>
                        </td>
                        <td className="px-3 py-3">
                          <MiniBar
                            value={row.total_leads || 0}
                            max={maxLeads}
                            onClick={() => handleOpenLeadsModal({ tipo_metrica: 'total', metricaLabel: 'Total Leads', asesor_id: row.asesor_id, asesor_nombre: row.nombre_completo })}
                          />
                        </td>
                        <td className="px-3 py-3 text-center">
                          <Num
                            value={row.leads_contactados}
                            onClick={row.leads_contactados > 0 ? () => handleOpenLeadsModal({ tipo_metrica: 'contactados', metricaLabel: 'Leads Contactados', asesor_id: row.asesor_id, asesor_nombre: row.nombre_completo }) : null}
                          />
                        </td>
                        <td className="px-3 py-3 text-center">
                          <Num
                            value={row.leads_calificados}
                            onClick={row.leads_calificados > 0 ? () => handleOpenLeadsModal({ tipo_metrica: 'calificados', metricaLabel: 'Leads Calificados', asesor_id: row.asesor_id, asesor_nombre: row.nombre_completo }) : null}
                          />
                        </td>
                        <td className="px-3 py-3 text-center">
                          <Num
                            value={row.leads_en_negociacion}
                            onClick={row.leads_en_negociacion > 0 ? () => handleOpenLeadsModal({ tipo_metrica: 'negociacion', metricaLabel: 'Leads en Negociación', asesor_id: row.asesor_id, asesor_nombre: row.nombre_completo }) : null}
                          />
                        </td>
                        <td className="px-3 py-3 text-center">
                          <Num
                            value={row.leads_ganados}
                            warn={row.leads_ganados > 0 ? 'green' : null}
                            onClick={row.leads_ganados > 0 ? () => handleOpenLeadsModal({ tipo_metrica: 'matriculas', metricaLabel: 'Leads Venta', asesor_id: row.asesor_id, asesor_nombre: row.nombre_completo }) : null}
                          />
                        </td>
                        <td className="px-3 py-3 text-center">
                          <Num
                            value={row.leads_perdidos}
                            warn={row.leads_perdidos > 0 ? 'red' : null}
                            onClick={row.leads_perdidos > 0 ? () => handleOpenLeadsModal({ tipo_metrica: 'perdidos', metricaLabel: 'Leads Perdidos', asesor_id: row.asesor_id, asesor_nombre: row.nombre_completo }) : null}
                          />
                        </td>
                        <td className="px-3 py-3 text-center">
                          <Num
                            value={row.leads_sin_contactar}
                            warn={row.leads_sin_contactar > 0 ? 'amber' : null}
                            onClick={row.leads_sin_contactar > 0 ? () => handleOpenLeadsModal({ tipo_metrica: 'sin_contactar', metricaLabel: 'Leads Sin Contactar', asesor_id: row.asesor_id, asesor_nombre: row.nombre_completo }) : null}
                          />
                        </td>
                        <td className="px-3 py-3 text-center"><PctBadge value={row.tasa_conversion_pct} /></td>
                        <td className="px-3 py-3 text-center"><PctBadge value={row.tasa_contactabilidad_pct} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )
        })()}

        {/* ── Tab: Por Fuente ── */}
        {!isLoading && !error && rows.length > 0 && activeTab === 'fuentes' && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-100">
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Fuente</th>
                  <th className="text-left px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide min-w-[120px]">Total</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Contactados</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Calificados</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Negociación</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Ventas</th>
                  <th className="text-center px-3 py-3 text-center py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Perdidos</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Conversión</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Contactabilidad</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {rows.map((row, i) => (
                  <tr key={i} className="hover:bg-indigo-50/30 transition-colors">
                    <td className="px-4 py-3"><SourceBadge name={row.fuente} /></td>
                    <td className="px-3 py-3">
                      <MiniBar
                        value={row.total_leads || 0}
                        max={maxLeads}
                        onClick={() => handleOpenLeadsModal({ tipo_metrica: 'total', metricaLabel: 'Total Leads', fuente: row.fuente, asesor_id: selectedAsesor || undefined })}
                      />
                    </td>
                    <td className="px-3 py-3 text-center">
                      <Num
                        value={row.leads_contactados}
                        onClick={row.leads_contactados > 0 ? () => handleOpenLeadsModal({ tipo_metrica: 'contactados', metricaLabel: 'Leads Contactados', fuente: row.fuente, asesor_id: selectedAsesor || undefined }) : null}
                      />
                    </td>
                    <td className="px-3 py-3 text-center">
                      <Num
                        value={row.leads_calificados}
                        onClick={row.leads_calificados > 0 ? () => handleOpenLeadsModal({ tipo_metrica: 'calificados', metricaLabel: 'Leads Calificados', fuente: row.fuente, asesor_id: selectedAsesor || undefined }) : null}
                      />
                    </td>
                    <td className="px-3 py-3 text-center">
                      <Num
                        value={row.leads_en_negociacion}
                        onClick={row.leads_en_negociacion > 0 ? () => handleOpenLeadsModal({ tipo_metrica: 'negociacion', metricaLabel: 'Leads en Negociación', fuente: row.fuente, asesor_id: selectedAsesor || undefined }) : null}
                      />
                    </td>
                    <td className="px-3 py-3 text-center">
                      <Num
                        value={row.leads_ganados}
                        warn={row.leads_ganados > 0 ? 'green' : null}
                        onClick={row.leads_ganados > 0 ? () => handleOpenLeadsModal({ tipo_metrica: 'matriculas', metricaLabel: 'Leads Venta', fuente: row.fuente, asesor_id: selectedAsesor || undefined }) : null}
                      />
                    </td>
                    <td className="px-3 py-3 text-center">
                      <Num
                        value={row.leads_perdidos}
                        warn={row.leads_perdidos > 0 ? 'red' : null}
                        onClick={row.leads_perdidos > 0 ? () => handleOpenLeadsModal({ tipo_metrica: 'perdidos', metricaLabel: 'Leads Perdidos', fuente: row.fuente, asesor_id: selectedAsesor || undefined }) : null}
                      />
                    </td>
                    <td className="px-3 py-3 text-center"><PctBadge value={row.tasa_conversion_pct} /></td>
                    <td className="px-3 py-3 text-center"><PctBadge value={row.tasa_contactabilidad_pct} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* ── Tab: Tiempo Respuesta ── */}
        {!isLoading && !error && rows.length > 0 && activeTab === 'tiempo-respuesta' && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-100">
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide sticky left-0 bg-gray-50">Asesor</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Leads medidos</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Promedio</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Mediana</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">P90</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Dentro 1h</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">% &lt; 1h</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Dentro 24h</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">% &lt; 24h</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {rows.map((row, i) => (
                  <tr key={i} className="hover:bg-indigo-50/30 transition-colors">
                    <td className="px-4 py-3 sticky left-0 bg-white">
                      <div className="flex items-center gap-2.5">
                        <Avatar name={row.nombre_completo} />
                        <span className="font-medium text-gray-800 whitespace-nowrap">{row.nombre_completo}</span>
                      </div>
                    </td>
                    <td className="px-3 py-3 text-center"><Num value={row.leads_con_contacto} /></td>
                    <td className="px-3 py-3 text-center"><HoursBadge value={row.promedio_horas} /></td>
                    <td className="px-3 py-3 text-center"><HoursBadge value={row.mediana_horas} /></td>
                    <td className="px-3 py-3 text-center"><HoursBadge value={row.p90_horas} /></td>
                    <td className="px-3 py-3 text-center"><Num value={row.dentro_1h} warn={row.dentro_1h > 0 ? 'green' : null} /></td>
                    <td className="px-3 py-3 text-center"><PctBadge value={row.pct_dentro_1h} /></td>
                    <td className="px-3 py-3 text-center"><Num value={row.dentro_24h} /></td>
                    <td className="px-3 py-3 text-center"><PctBadge value={row.pct_dentro_24h} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-xs text-gray-400 px-4 py-2 border-t border-gray-50">
              Verde: respuesta en menos de 1h. Amarillo: menos de 24h. Rojo: más de 24h.
            </p>
          </div>
        )}

        {/* ── Tab: Funnel ── */}
        {!isLoading && !error && activeTab === 'funnel' && data?.etapas?.length > 0 && (
          <div className="p-6 flex flex-col md:flex-row gap-8 items-start">
            <div className="flex-1 min-w-0">
              <FunnelChart etapas={data.etapas} />
            </div>
            <div className="w-full md:w-64 flex-shrink-0">
              <p className="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-3">Detalle por etapa</p>
              <div className="space-y-2">
                {data.etapas.map((e, i) => (
                  <div key={i} className="flex items-center justify-between py-1.5 border-b border-gray-50 last:border-0">
                    <StateBadge nombre={e.estado} colorHex={e.color_hex} />
                    <div className="flex items-center gap-3">
                      <span className="text-sm font-bold text-gray-800">{e.total.toLocaleString('es-PE')}</span>
                      <span className="text-xs text-gray-400 w-10 text-right">{e.pct_total}%</span>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ── Tab: Estancados ── */}
        {!isLoading && !error && rows.length > 0 && activeTab === 'estancados' && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-100">
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Lead</th>
                  <th className="text-left px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Estado</th>
                  <th className="text-left px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Fuente</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Ingreso</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Últ. Contacto</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Inactividad</th>
                  <th className="text-left px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Asesor</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {rows.map((row, i) => (
                  <tr key={i} className="hover:bg-red-50/20 transition-colors">
                    <td className="px-4 py-3">
                      <div>
                        <p className="font-medium text-gray-800">{row.nombre_lead}</p>
                        <p className="text-xs text-gray-400">{row.telefono || '—'}</p>
                      </div>
                    </td>
                    <td className="px-3 py-3"><StateBadge nombre={row.estado} colorHex={row.color_hex} /></td>
                    <td className="px-3 py-3"><SourceBadge name={row.fuente} /></td>
                    <td className="px-3 py-3 text-center text-xs text-gray-500">{row.fecha_ingreso || '—'}</td>
                    <td className="px-3 py-3 text-center text-xs text-gray-500">{row.fecha_ultimo_contacto || <span className="text-red-400 font-medium">Nunca</span>}</td>
                    <td className="px-3 py-3 text-center"><DaysBadge value={row.dias_inactivo} /></td>
                    <td className="px-3 py-3">
                      <div className="flex items-center gap-2">
                        <Avatar name={row.asesor_nombre} />
                        <span className="text-sm text-gray-700 whitespace-nowrap">{row.asesor_nombre || 'Sin asignar'}</span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {rows.length >= 200 && (
              <p className="text-xs text-gray-400 px-4 py-2 border-t border-gray-50">
                Mostrando los 200 leads más antiguos sin contacto. Exporta a Excel para el listado completo.
              </p>
            )}
          </div>
        )}

        {/* ── Tab: Campañas ── */}
        {!isLoading && !error && rows.length > 0 && activeTab === 'campanas' && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-100">
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Campaña</th>
                  <th className="text-left px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Fuente</th>
                  <th className="text-left px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide min-w-[100px]">Leads</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Contactados</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Calificados</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Ventas</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">% Contact.</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">% Calif.</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">% Ventas</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">1er Contacto</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {rows.map((row, i) => {
                  const maxL = Math.max(...rows.map(r => r.total_leads || 0))
                  return (
                    <tr key={i} className="hover:bg-indigo-50/30 transition-colors">
                      <td className="px-4 py-3">
                        <span className="font-medium text-gray-800 text-sm">{row.campana}</span>
                      </td>
                      <td className="px-3 py-3"><SourceBadge name={row.fuente} /></td>
                      <td className="px-3 py-3">
                        <MiniBar
                          value={row.total_leads || 0}
                          max={maxL}
                          onClick={() => handleOpenLeadsModal({ tipo_metrica: 'total', metricaLabel: 'Total Leads', campana: row.campana, fuente: row.fuente, asesor_id: selectedAsesor || undefined })}
                        />
                      </td>
                      <td className="px-3 py-3 text-center">
                        <Num
                          value={row.leads_contactados}
                          onClick={row.leads_contactados > 0 ? () => handleOpenLeadsModal({ tipo_metrica: 'contactados', metricaLabel: 'Leads Contactados', campana: row.campana, fuente: row.fuente, asesor_id: selectedAsesor || undefined }) : null}
                        />
                      </td>
                      <td className="px-3 py-3 text-center">
                        <Num
                          value={row.leads_calificados}
                          onClick={row.leads_calificados > 0 ? () => handleOpenLeadsModal({ tipo_metrica: 'calificados', metricaLabel: 'Leads Calificados', campana: row.campana, fuente: row.fuente, asesor_id: selectedAsesor || undefined }) : null}
                        />
                      </td>
                      <td className="px-3 py-3 text-center">
                        <Num
                          value={row.leads_ganados}
                          warn={row.leads_ganados > 0 ? 'green' : null}
                          onClick={row.leads_ganados > 0 ? () => handleOpenLeadsModal({ tipo_metrica: 'matriculas', metricaLabel: 'Leads Venta', campana: row.campana, fuente: row.fuente, asesor_id: selectedAsesor || undefined }) : null}
                        />
                      </td>
                      <td className="px-3 py-3 text-center"><PctBadge value={row.pct_contactados} /></td>
                      <td className="px-3 py-3 text-center"><PctBadge value={row.pct_calificados} /></td>
                      <td className="px-3 py-3 text-center"><PctBadge value={row.pct_ganados} /></td>
                      <td className="px-3 py-3 text-center"><HoursBadge value={row.horas_primer_contacto} /></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            <p className="text-xs text-gray-400 px-4 py-2 border-t border-gray-50">
              Solo campañas con 5 o más leads. "1er Contacto": promedio de horas hasta el primer contacto real.
            </p>
          </div>
        )}

        {/* ── Tab: Llamadas ── (Sprint 1) */}
        {!isLoading && !error && rows.length > 0 && activeTab === 'llamadas' && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-100">
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Asesor</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Total llamadas</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Duración promedio</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-emerald-600 uppercase tracking-wide" title="Llamadas ≥ 2 minutos (efectivas)">Efectivas</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-red-600 uppercase tracking-wide" title="Llamadas < 30 segundos (cortas)">Cortas</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Sin respuesta</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-emerald-600 uppercase tracking-wide">% efectivas</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-red-600 uppercase tracking-wide">% cortas</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {rows.map((r, i) => {
                  const m = Math.floor((r.duracion_promedio_seg || 0) / 60)
                  const s = (r.duracion_promedio_seg || 0) % 60
                  const llApp = r.llamadas_app || 0
                  const llManual = r.llamadas_manual || 0
                  const llConDur = r.llamadas_con_duracion || 0
                  const total = r.total_llamadas || 0
                  const sinDur = total - llConDur
                  const promApp = r.duracion_promedio_app_seg || 0
                  const promManual = r.duracion_promedio_manual_seg || 0
                  const fmtMs = (sec) => {
                    const mm = Math.floor(sec / 60)
                    const ss = sec % 60
                    return `${mm}m ${String(ss).padStart(2, '0')}s`
                  }
                  // Senal de inflacion: el promedio manual >5x el de app.
                  const inflado = promApp > 0 && promManual > promApp * 5
                  // Bajo ratio de cobertura: <50% de llamadas tiene duracion real.
                  const coberturaBaja = total > 0 && llConDur / total < 0.5
                  return (
                    <tr key={i} className="hover:bg-indigo-50/30">
                      <td className="px-4 py-3"><div className="flex items-center gap-2.5"><Avatar name={r.nombre_completo} /><span className="font-medium text-gray-800">{r.nombre_completo}</span></div></td>
                      <td className="px-3 py-3 text-center">
                        <div className="flex flex-col items-center">
                          <Num value={r.total_llamadas} />
                          {(llApp > 0 || llManual > 0) && (
                            <div className="text-[10px] text-gray-400 mt-0.5 inline-flex items-center gap-1.5">
                              {llApp > 0 && (
                                <span title={`${llApp} desde la app móvil (call log Android)`}>
                                  📱 {llApp}
                                </span>
                              )}
                              {llApp > 0 && llManual > 0 && <span className="text-gray-300">·</span>}
                              {llManual > 0 && (
                                <span title={`${llManual} registradas manualmente desde la web`}>
                                  ✍️ {llManual}
                                </span>
                              )}
                            </div>
                          )}
                        </div>
                      </td>
                      <td className="px-3 py-3 text-center">
                        <div className="flex flex-col items-center">
                          {llConDur > 0 ? (
                            <>
                              <span className="font-mono text-sm">{m}m {String(s).padStart(2, '0')}s</span>
                              <div className={`text-[10px] mt-0.5 ${coberturaBaja ? 'text-amber-600 font-medium' : 'text-gray-400'}`}
                                title={`Promedio calculado solo sobre las ${llConDur} llamada${llConDur === 1 ? '' : 's'} con duración registrada${sinDur > 0 ? ` (${sinDur} sin duración fueron excluidas)` : ''}`}>
                                {coberturaBaja && '⚠ '}
                                {llConDur === total
                                  ? <span>de {total} llamada{total === 1 ? '' : 's'}</span>
                                  : <span>de <strong>{llConDur}</strong>/{total} con duración</span>}
                              </div>
                              {(llApp > 0 && llManual > 0) && (
                                <div className="text-[10px] text-gray-400 mt-1 inline-flex items-center gap-1.5">
                                  {promApp > 0 && (
                                    <span className="font-mono" title={`Promedio solo del cel (${llApp} llamada${llApp === 1 ? '' : 's'})`}>📱 {fmtMs(promApp)}</span>
                                  )}
                                  {promApp > 0 && promManual > 0 && <span className="text-gray-300">·</span>}
                                  {promManual > 0 && (
                                    <span className={`font-mono ${inflado ? 'text-amber-600 font-semibold' : ''}`} title={inflado ? '⚠ Promedio manual muy alto vs cel — posible inflación' : 'Promedio solo de llamadas manuales con duración'}>
                                      ✍️ {fmtMs(promManual)}{inflado && ' ⚠'}
                                    </span>
                                  )}
                                </div>
                              )}
                            </>
                          ) : (
                            <span className="text-xs text-gray-400 italic" title="Ninguna llamada tiene duración registrada">
                              — sin datos —
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-3 py-3 text-center"><Num value={r.llamadas_efectivas} warn={r.llamadas_efectivas > 0 ? 'green' : null} /></td>
                      <td className="px-3 py-3 text-center"><Num value={r.llamadas_cortas} warn={r.llamadas_cortas > 0 ? 'red' : null} /></td>
                      <td className="px-3 py-3 text-center text-gray-400"><Num value={r.llamadas_sin_respuesta} /></td>
                      <td className="px-3 py-3 text-center"><PctBadge value={r.pct_efectivas} /></td>
                      <td className="px-3 py-3 text-center"><PctBadge value={r.pct_cortas} inverse /></td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            <div className="text-xs text-gray-400 px-4 py-2 border-t border-gray-50 space-y-1">
              <p>
                <strong>Efectivas</strong>: ≥ 2 minutos. <strong>Cortas</strong>: &lt; 30 segundos. Benchmark inmobiliario: &gt;40% efectivas, &lt;20% cortas.
              </p>
              <p>
                <span className="inline-flex items-center gap-2">
                  <span>📱 = sincronizado del celular (App Android, duración exacta)</span>
                  <span>·</span>
                  <span>✍️ = registrado manualmente desde la web (duración opcional)</span>
                </span>
              </p>
              <p className="text-amber-600">
                ⚠ <strong>Cuando la cobertura es baja</strong> (menos del 50% de las llamadas tiene duración registrada), el promedio puede ser engañoso. Los asesores deben llenar el campo "Duración (min)" al registrar manualmente cada llamada.
              </p>
            </div>
          </div>
        )}

        {/* ── Llamadas: desglose por calidad de lead (frio / tibio / caliente) ──
            Pedido explicito de Marketing. RENDER INDEPENDIENTE del bloque
            por-asesor — si la tabla principal viene vacia pero hay calidades,
            igual se muestra. */}
        {!isLoading && !error && activeTab === 'llamadas'
          && Array.isArray(data?.por_calidad) && data.por_calidad.length > 0 && (
            <div className={rows.length > 0 ? "border-t border-gray-100 pt-5 px-4 pb-5" : "pt-5 px-4 pb-5"}>
              <h3 className="text-sm font-semibold text-gray-700 mb-3">
                Eficiencia por tipo de lead
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
                {data.por_calidad.map((c) => {
                  const m = Math.floor((c.duracion_promedio_seg || 0) / 60)
                  const s = (c.duracion_promedio_seg || 0) % 60
                  return (
                    <div
                      key={c.calidad}
                      className="border border-gray-100 rounded-lg p-3 bg-white"
                      style={{ borderLeft: `4px solid ${c.color_hex}` }}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <span className="font-semibold text-gray-800 text-sm">
                          {c.nombre}
                        </span>
                        <span className="text-xs text-gray-400">
                          {c.total_llamadas} llamada{c.total_llamadas === 1 ? '' : 's'}
                        </span>
                      </div>
                      <div className="space-y-1.5 text-xs">
                        <div className="flex justify-between">
                          <span className="text-gray-500">Duración prom.</span>
                          <span className="font-mono text-gray-700">
                            {m}m {String(s).padStart(2, '0')}s
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-gray-500">% efectivas</span>
                          <span className="font-semibold text-emerald-600">
                            {c.pct_efectivas != null ? `${c.pct_efectivas}%` : '—'}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-gray-500">% cortas</span>
                          <span className="font-semibold text-red-600">
                            {c.pct_cortas != null ? `${c.pct_cortas}%` : '—'}
                          </span>
                        </div>
                      </div>
                    </div>
                  )
                })}
              </div>
              <p className="text-xs text-gray-400 mt-3">
                Si los leads calientes muestran &lt; 60% efectivas, hay un problema
                de calidad de pitch en los cierres. Si los fríos muestran &gt; 50%
                cortas, el asesor está descartando rápido — verificar que sea por
                pitch corto y no por desinterés justificado.
              </p>
            </div>
          )}

        {/* ── Tab: Citas ── (Sprint 1, V042) */}
        {!isLoading && !error && rows.length > 0 && activeTab === 'citas' && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-100">
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Asesor</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Total citas</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-blue-600 uppercase tracking-wide">Pendientes</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-emerald-600 uppercase tracking-wide">Completadas</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-amber-600 uppercase tracking-wide">Reprogramadas</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Canceladas</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-red-600 uppercase tracking-wide">No asistió</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-emerald-600 uppercase tracking-wide" title="Completadas / Total citas">% efectividad</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {rows.map((r, i) => (
                  <tr key={i} className="hover:bg-indigo-50/30">
                    <td className="px-4 py-3"><div className="flex items-center gap-2.5"><Avatar name={r.nombre_completo} /><span className="font-medium text-gray-800">{r.nombre_completo}</span></div></td>
                    <td className="px-3 py-3 text-center"><Num value={r.total_citas} /></td>
                    <td className="px-3 py-3 text-center"><Num value={r.pendientes} /></td>
                    <td className="px-3 py-3 text-center"><Num value={r.completadas} warn={r.completadas > 0 ? 'green' : null} /></td>
                    <td className="px-3 py-3 text-center"><Num value={r.reprogramadas} warn={r.reprogramadas > 0 ? 'amber' : null} /></td>
                    <td className="px-3 py-3 text-center text-gray-500"><Num value={r.canceladas} /></td>
                    <td className="px-3 py-3 text-center"><Num value={r.no_asistio} warn={r.no_asistio > 0 ? 'red' : null} /></td>
                    <td className="px-3 py-3 text-center"><PctBadge value={r.tasa_efectividad} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-xs text-gray-400 px-4 py-2 border-t border-gray-50">
              <strong>% efectividad</strong> = Completadas / Total citas. Refleja cuántas citas agendadas terminaron en visita real.
            </p>
          </div>
        )}

        {/* ── Tab: Ranking ── (Sprint 1) */}
        {!isLoading && !error && rows.length > 0 && activeTab === 'ranking' && (() => {
          // Si el filtro es 'equipo', el backend ya devolvio rows agrupadas por
          // supervisor — render distinto. Sino, filtra por rol normal.
          const isEquipoMode = roleFilter === 'equipo'
          const filtered = isEquipoMode
            ? rows
            : rows.filter(r => roleFilter === 'all' ? true : (r.rol || 'asesor') === roleFilter)
          const conActividad = filtered.filter(r => (r.total_leads || 0) > 0 || (r.total_llamadas || 0) > 0 || (r.total_citas || 0) > 0)
          const sinActividad = filtered.filter(r => (r.total_leads || 0) === 0 && (r.total_llamadas || 0) === 0 && (r.total_citas || 0) === 0)
          const labelTipo = isEquipoMode
            ? (filtered.length === 1 ? 'equipo' : 'equipos')
            : (filtered.length === 1 ? 'persona' : 'personas')
          return (
            <div className="p-4 space-y-4">
              {/* Selector de Métrica, Filtro de Fuente y Agrupación */}
              <div className="flex flex-col xl:flex-row xl:items-center justify-between gap-3 pb-3 border-b border-gray-100">
                {/* Métricas de Ranking */}
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span className="text-xs font-semibold text-gray-500 mr-1">Métrica:</span>
                  {[
                    { v: 'matriculas', label: '🏆 Ventas' },
                    { v: 'contactabilidad', label: '📞 Contactabilidad' },
                    { v: 'conversion', label: '🎯 % Conversión' },
                    { v: 'citas', label: '📅 Citas' },
                    { v: 'llamadas', label: '📱 Llamadas' },
                  ].map(m => {
                    const active = rankingMetrica === m.v
                    return (
                      <button
                        key={m.v}
                        onClick={() => setRankingMetrica(m.v)}
                        className={`text-xs px-3 py-1.5 rounded-lg font-medium transition ${
                          active
                            ? 'bg-indigo-600 text-white shadow-sm'
                            : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                        }`}
                      >
                        {m.label}
                      </button>
                    )
                  })}
                </div>

                {/* Filtro de Fuente, Reglas de Excepción y Agrupación por Rol / Equipo */}
                <div className="flex flex-col gap-2.5">
                  <div className="flex items-center gap-3 flex-wrap">
                    {/* Filtro de Fuente para el Ranking */}
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs text-gray-500 font-semibold mr-0.5">Fuente:</span>
                      <div className="relative inline-flex items-center">
                        <select
                          value={selectedFuente}
                          onChange={e => {
                            const val = e.target.value
                            setSelectedFuente(val)
                            if (val && fuentesExcluidas.includes(val)) {
                              setFuentesExcluidas(prev => prev.filter(f => f !== val))
                            }
                          }}
                          title="Filtrar ranking solo por esta fuente"
                          className={`text-xs rounded-lg pl-2.5 pr-7 py-1.5 font-medium border transition-colors shadow-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 max-w-[170px] truncate ${
                            selectedFuente
                              ? 'bg-indigo-50 border-indigo-300 text-indigo-700 font-semibold'
                              : 'bg-white border-gray-200 text-gray-700 hover:border-gray-300'
                          }`}
                        >
                          <option value="">Todas las fuentes</option>
                          {fuentes && fuentes.map(f => (
                            <option key={f.id} value={f.nombre}>
                              {f.nombre}
                            </option>
                          ))}
                          <option value="Sin fuente">Sin fuente</option>
                        </select>
                        {selectedFuente && (
                          <button
                            type="button"
                            onClick={() => setSelectedFuente('')}
                            title="Limpiar filtro de fuente"
                            className="absolute right-1.5 text-indigo-400 hover:text-indigo-700 p-0.5 rounded-full"
                          >
                            <X size={12} />
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Regla de excepción: Excluir / Quitar fuente del Ranking */}
                    <div className="flex items-center gap-1.5">
                      <span className="text-xs text-rose-600 font-semibold mr-0.5">Excluir:</span>
                      <div className="relative inline-flex items-center">
                        <select
                          value=""
                          onChange={e => {
                            const val = e.target.value
                            if (val && !fuentesExcluidas.includes(val)) {
                              setFuentesExcluidas(prev => [...prev, val])
                              if (selectedFuente === val) setSelectedFuente('')
                            }
                          }}
                          title="Agregar regla de excepción: quitar fuente del ranking"
                          className="text-xs rounded-lg pl-2.5 pr-6 py-1.5 font-medium border border-rose-200 bg-rose-50/60 text-rose-700 hover:bg-rose-100/60 transition-colors shadow-sm focus:outline-none focus:ring-2 focus:ring-rose-500/20 max-w-[180px] cursor-pointer"
                        >
                          <option value="" disabled>+ Quitar fuente...</option>
                          {fuentes && fuentes
                            .filter(f => !fuentesExcluidas.includes(f.nombre))
                            .map(f => (
                              <option key={f.id} value={f.nombre}>
                                Excluir: {f.nombre}
                              </option>
                            ))}
                          {!fuentesExcluidas.includes('Sin fuente') && (
                            <option value="Sin fuente">Excluir: Sin fuente</option>
                          )}
                        </select>
                      </div>
                    </div>

                    {/* Agrupación por Rol / Equipo */}
                    <div className="flex items-center gap-1.5 flex-wrap sm:ml-auto">
                      <span className="text-xs text-gray-500 mr-1">Agrupar por:</span>
                      {[
                        { v: 'equipo', label: 'Equipos', color: 'emerald' },
                        { v: 'asesor', label: 'Asesores', color: 'indigo' },
                        { v: 'supervisor', label: 'Supervisores', color: 'purple' },
                        { v: 'all', label: 'Todos', color: 'gray' },
                      ].map(opt => {
                        const active = roleFilter === opt.v
                        const colorMap = {
                          indigo: 'bg-indigo-50 text-indigo-700 border-indigo-300 ring-indigo-200',
                          purple: 'bg-purple-50 text-purple-700 border-purple-300 ring-purple-200',
                          emerald: 'bg-emerald-50 text-emerald-700 border-emerald-300 ring-emerald-200',
                          gray: 'bg-gray-100 text-gray-700 border-gray-300 ring-gray-200',
                        }
                        return (
                          <button
                            key={opt.v}
                            onClick={() => setRoleFilter(opt.v)}
                            className={`text-xs px-2.5 py-1 rounded-full border font-medium transition ${
                              active
                                ? `${colorMap[opt.color]} ring-1`
                                : 'bg-white text-gray-500 border-gray-200 hover:border-gray-300'
                            }`}
                          >
                            {opt.label}
                          </button>
                        )
                      })}
                      <span className="text-[11px] text-gray-400 ml-2">
                        {filtered.length} {labelTipo}
                      </span>
                    </div>
                  </div>

                  {/* Chips / Pills de Reglas de Excepción Activas */}
                  {fuentesExcluidas.length > 0 && (
                    <div className="flex items-center gap-1.5 flex-wrap px-3 py-2 rounded-lg bg-rose-50/70 border border-rose-200">
                      <span className="text-[11px] font-bold text-rose-700 uppercase tracking-wider mr-1">
                        Reglas de Excepción:
                      </span>
                      {fuentesExcluidas.map(fName => (
                        <span
                          key={fName}
                          className="inline-flex items-center gap-1.5 pl-2.5 pr-1.5 py-0.5 rounded-full text-xs font-semibold bg-rose-100 text-rose-800 border border-rose-300 shadow-2xs"
                        >
                          <span>🚫 Sin {fName}</span>
                          <button
                            type="button"
                            onClick={() => setFuentesExcluidas(prev => prev.filter(x => x !== fName))}
                            title={`Quitar regla de excepción para ${fName}`}
                            className="hover:bg-rose-200 text-rose-700 hover:text-rose-900 rounded-full p-0.5 transition-colors cursor-pointer"
                          >
                            <X size={12} />
                          </button>
                        </span>
                      ))}
                      <button
                        type="button"
                        onClick={() => setFuentesExcluidas([])}
                        className="text-xs text-rose-600 hover:text-rose-800 underline font-medium ml-2 cursor-pointer"
                      >
                        Restablecer todas
                      </button>
                    </div>
                  )}
                </div>
              </div>

              {/* Banner de Aviso de Regla de Excepción Activa */}
              {fuentesExcluidas.length > 0 && (
                <div className="flex items-center justify-between gap-3 px-4 py-2.5 rounded-xl bg-amber-50/80 border border-amber-200/90 text-xs text-amber-900 shadow-xs">
                  <div className="flex items-center gap-2">
                    <span className="font-bold text-amber-700">⚡ Regla de excepción activa:</span>
                    <span>
                      Se excluyen los leads de <strong>{fuentesExcluidas.join(', ')}</strong> del cálculo del ranking.
                    </span>
                  </div>
                  <button
                    type="button"
                    onClick={() => setFuentesExcluidas([])}
                    className="text-xs font-semibold text-amber-800 hover:text-amber-950 underline shrink-0 cursor-pointer"
                  >
                    Quitar filtro de excepción
                  </button>
                </div>
              )}

              {/* Lista de Ranking */}
              <div className="space-y-3">
                {conActividad.slice(0, 30).map((r, i) => {
                  const isTop3 = i < 3
                  const medal = i === 0 ? '🥇' : i === 1 ? '🥈' : i === 2 ? '🥉' : null
                  const rowKey = isEquipoMode ? `eq-${r.supervisor_id}` : r.asesor_id
                  const nombre = isEquipoMode
                    ? `Equipo de ${r.supervisor_nombre || '—'}`
                    : r.nombre_completo

                  return (
                    <div
                      key={rowKey}
                      className={`flex items-center gap-4 p-4 rounded-xl border transition-all ${
                        isTop3
                          ? 'bg-gradient-to-r from-amber-50/60 via-white to-amber-50/30 border-amber-200 shadow-sm'
                          : 'bg-white border-gray-100 hover:border-gray-200'
                      }`}
                    >
                      {/* Posición / Medalla */}
                      <div
                        className={`w-12 h-12 rounded-full flex items-center justify-center font-bold text-lg shrink-0 ${
                          isTop3 ? 'bg-amber-100 text-amber-700 shadow-inner' : 'bg-gray-100 text-gray-600'
                        }`}
                      >
                        {medal || `#${r.posicion || i + 1}`}
                      </div>

                      {/* Avatar o Ícono de Equipo */}
                      {isEquipoMode ? (
                        <div className="w-12 h-12 rounded-full bg-emerald-100 text-emerald-600 flex items-center justify-center shrink-0">
                          <Users size={22} />
                        </div>
                      ) : (
                        <Avatar name={r.nombre_completo} size="lg" />
                      )}

                      {/* Información Principal */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <p className="font-semibold text-gray-900 truncate text-base">
                            {nombre}
                          </p>
                          {!isEquipoMode && r.rol === 'supervisor' && (
                            <span className="text-[10px] bg-purple-50 text-purple-700 border border-purple-200 px-1.5 py-0.5 rounded font-semibold">
                              SUPERVISOR
                            </span>
                          )}
                          {isEquipoMode && (
                            <span className="text-[11px] text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-full font-medium">
                              {r.num_asesores} {r.num_asesores === 1 ? 'asesor' : 'asesores'}
                            </span>
                          )}
                        </div>

                        {/* Etiquetas métricas clickeables */}
                        <div className="flex items-center gap-2 text-xs text-gray-500 mt-1.5 flex-wrap">
                          <button
                            onClick={() => handleOpenLeadsModal({
                              tipo_metrica: 'total',
                              metricaLabel: 'Total Leads',
                              asesor_id: isEquipoMode ? undefined : r.asesor_id,
                              supervisor_id: isEquipoMode ? r.supervisor_id : undefined,
                              asesor_nombre: isEquipoMode ? undefined : r.nombre_completo,
                              supervisor_nombre: isEquipoMode ? r.supervisor_nombre : undefined,
                              fuente: selectedFuente || undefined,
                              fuente_excluida: fuentesExcluidas.length > 0 ? fuentesExcluidas.join(',') : undefined,
                            })}
                            className="hover:underline hover:text-indigo-600 font-medium cursor-pointer"
                          >
                            {r.total_leads || 0} leads
                          </button>
                          <span>·</span>
                          <button
                            onClick={() => handleOpenLeadsModal({
                              tipo_metrica: 'contactados',
                              metricaLabel: 'Leads Contactados',
                              asesor_id: isEquipoMode ? undefined : r.asesor_id,
                              supervisor_id: isEquipoMode ? r.supervisor_id : undefined,
                              asesor_nombre: isEquipoMode ? undefined : r.nombre_completo,
                              supervisor_nombre: isEquipoMode ? r.supervisor_nombre : undefined,
                              fuente: selectedFuente || undefined,
                              fuente_excluida: fuentesExcluidas.length > 0 ? fuentesExcluidas.join(',') : undefined,
                            })}
                            className="hover:underline hover:text-blue-600 font-medium text-blue-600 cursor-pointer"
                          >
                            {r.leads_contactados || 0} contactados
                          </button>
                          <span>·</span>
                          <button
                            onClick={() => handleOpenLeadsModal({
                              tipo_metrica: 'matriculas',
                              metricaLabel: 'Leads Venta',
                              asesor_id: isEquipoMode ? undefined : r.asesor_id,
                              supervisor_id: isEquipoMode ? r.supervisor_id : undefined,
                              asesor_nombre: isEquipoMode ? undefined : r.nombre_completo,
                              supervisor_nombre: isEquipoMode ? r.supervisor_nombre : undefined,
                              fuente: selectedFuente || undefined,
                              fuente_excluida: fuentesExcluidas.length > 0 ? fuentesExcluidas.join(',') : undefined,
                            })}
                            className="hover:underline hover:text-emerald-600 font-semibold text-emerald-600 cursor-pointer"
                          >
                            {r.leads_ganados || 0} ventas
                          </button>
                          <span>·</span>
                          <button
                            onClick={() => handleOpenLeadsModal({
                              tipo_metrica: 'calificados',
                              metricaLabel: 'Leads Calificados',
                              asesor_id: isEquipoMode ? undefined : r.asesor_id,
                              supervisor_id: isEquipoMode ? r.supervisor_id : undefined,
                              asesor_nombre: isEquipoMode ? undefined : r.nombre_completo,
                              supervisor_nombre: isEquipoMode ? r.supervisor_nombre : undefined,
                              fuente: selectedFuente || undefined,
                              fuente_excluida: fuentesExcluidas.length > 0 ? fuentesExcluidas.join(',') : undefined,
                            })}
                            className="hover:underline hover:text-purple-600 font-medium cursor-pointer"
                          >
                            {r.leads_calificados || 0} calificados
                          </button>
                        </div>
                      </div>

                      {/* Desempeño / KPI Principal a la derecha */}
                      <div className="text-right flex-shrink-0 min-w-[120px]">
                        {rankingMetrica === 'contactabilidad' ? (
                          <div>
                            <div className="text-2xl font-extrabold text-indigo-600">
                              {r.tasa_contactabilidad_pct || 0}%
                            </div>
                            <div className="text-[10px] text-gray-400 uppercase tracking-wide font-semibold">
                              Contactabilidad
                            </div>
                            <div className="text-[11px] text-gray-500 mt-0.5">
                              {r.leads_contactados || 0} de {r.total_leads || 0} leads
                            </div>
                          </div>
                        ) : rankingMetrica === 'conversion' ? (
                          <div>
                            <div className="text-2xl font-extrabold text-purple-600">
                              {r.tasa_conversion_pct || 0}%
                            </div>
                            <div className="text-[10px] text-gray-400 uppercase tracking-wide font-semibold">
                              Conversión
                            </div>
                            <div className="text-[11px] text-gray-500 mt-0.5">
                              {r.leads_ganados || 0} ventas
                            </div>
                          </div>
                        ) : rankingMetrica === 'citas' ? (
                          <div>
                            <div className="text-2xl font-extrabold text-blue-600">
                              {r.total_citas != null && r.total_citas > 0
                                ? r.total_citas
                                : ((r.leads_calificados || 0) + (r.leads_en_negociacion || 0))}
                            </div>
                            <div className="text-[10px] text-gray-400 uppercase tracking-wide font-semibold">
                              Citas Agendadas
                            </div>
                            <div className="text-[11px] text-gray-500 mt-0.5">
                              {r.citas_completadas != null && r.citas_completadas > 0
                                ? `${r.citas_completadas} completadas`
                                : `${r.leads_ganados || 0} ventas`}
                            </div>
                          </div>
                        ) : rankingMetrica === 'llamadas' ? (
                          <div>
                            <div className="text-2xl font-extrabold text-amber-600">
                              {r.total_llamadas || 0}
                            </div>
                            <div className="text-[10px] text-gray-400 uppercase tracking-wide font-semibold">
                              Llamadas
                            </div>
                            <div className="text-[11px] text-gray-500 mt-0.5">
                              {r.pct_efectivas != null ? `${r.pct_efectivas}% efectivas` : '—'}
                            </div>
                          </div>
                        ) : (
                          <div>
                            <div className="text-2xl font-extrabold text-emerald-600">
                              {r.leads_ganados || 0}
                            </div>
                            <div className="text-[10px] text-gray-400 uppercase tracking-wide font-semibold">
                              Ventas
                            </div>
                            <div className="text-[11px] text-gray-500 mt-0.5">
                              {r.tasa_conversion_pct || 0}% conv.
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>

              {/* Sin actividad en el período (asesores o equipos) */}
              {sinActividad.length > 0 && (
                <details className="mt-4 group">
                  <summary className="cursor-pointer text-xs text-gray-500 hover:text-gray-700 px-2 py-1 select-none">
                    <span className="inline-flex items-center gap-1.5">
                      Sin actividad en el período ({sinActividad.length})
                      <span className="text-gray-400 group-open:hidden">▸ click para expandir</span>
                    </span>
                  </summary>
                  <div className="mt-2 space-y-1.5 pl-4">
                    {sinActividad.map(r => (
                      <div key={isEquipoMode ? `eq-${r.supervisor_id}` : r.asesor_id} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-gray-50/50 border border-gray-100 opacity-70">
                        <div className="w-7 h-7 rounded-full bg-gray-200 text-gray-500 flex items-center justify-center text-xs font-medium shrink-0">
                          —
                        </div>
                        <span className="text-sm text-gray-600 flex-1 truncate">
                          {isEquipoMode ? `Equipo de ${r.supervisor_nombre || '—'}` : r.nombre_completo}
                        </span>
                        {!isEquipoMode && r.rol === 'supervisor' && (
                          <span className="text-[9px] bg-purple-50 text-purple-600 border border-purple-200 px-1 rounded">supervisor</span>
                        )}
                        <span className="text-[10px] text-gray-400">0 leads</span>
                      </div>
                    ))}
                  </div>
                </details>
              )}

              {/* Mensaje si nadie tiene actividad */}
              {conActividad.length === 0 && (
                <div className="text-center py-8">
                  <p className="text-sm text-gray-500">
                    {selectedFuente
                      ? `${isEquipoMode ? 'Ningún equipo' : 'Ningún asesor'} tiene leads de la fuente "${selectedFuente}" en el período seleccionado.`
                      : fuentesExcluidas.length > 0
                        ? `${isEquipoMode ? 'Ningún equipo' : 'Ningún asesor'} tiene leads tras excluir "${fuentesExcluidas.join(', ')}" en el período seleccionado.`
                        : `${isEquipoMode ? 'Ningún equipo' : 'Ningún asesor'} tiene leads en el período seleccionado.`}
                  </p>
                  {selectedFuente || fuentesExcluidas.length > 0 ? (
                    <div className="mt-2.5 flex items-center justify-center gap-3 flex-wrap">
                      {selectedFuente && (
                        <button
                          type="button"
                          onClick={() => setSelectedFuente('')}
                          className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 hover:underline cursor-pointer"
                        >
                          Ver todas las fuentes
                        </button>
                      )}
                      {fuentesExcluidas.length > 0 && (
                        <button
                          type="button"
                          onClick={() => setFuentesExcluidas([])}
                          className="text-xs font-semibold text-rose-600 hover:text-rose-800 hover:underline cursor-pointer"
                        >
                          Quitar reglas de excepción ({fuentesExcluidas.join(', ')})
                        </button>
                      )}
                    </div>
                  ) : (
                    <p className="text-xs text-gray-400 mt-1">Amplía el rango de fechas arriba para ver actividad histórica.</p>
                  )}
                </div>
              )}
            </div>
          )
        })()}

        {/* ── Tab: Leadtime ── (Sprint 2) */}
        {!isLoading && !error && rows.length > 0 && activeTab === 'leadtime' && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-100">
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Asesor</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Leads</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Promedio</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Mediana</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-emerald-600 uppercase tracking-wide" title="Speed-to-Lead (MIT)">&lt; 5 min</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-emerald-500 uppercase tracking-wide">5-30 min</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-amber-600 uppercase tracking-wide">30-60 min</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-orange-600 uppercase tracking-wide">1h-24h</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-red-600 uppercase tracking-wide">&gt; 24h</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {rows.map((r, i) => (
                  <tr key={i} className="hover:bg-indigo-50/30">
                    <td className="px-4 py-3"><div className="flex items-center gap-2.5"><Avatar name={r.nombre_completo} /><span className="font-medium text-gray-800">{r.nombre_completo}</span></div></td>
                    <td className="px-3 py-3 text-center"><Num value={r.total_leads} /></td>
                    <td className="px-3 py-3 text-center font-mono text-sm">{r.tiempo_promedio_min || '—'} min</td>
                    <td className="px-3 py-3 text-center font-mono text-sm">{r.mediana_min ?? '—'} min</td>
                    <td className="px-3 py-3 text-center"><Num value={r.bucket_menos_5min} warn={r.bucket_menos_5min > 0 ? 'green' : null} /></td>
                    <td className="px-3 py-3 text-center"><Num value={r.bucket_5_30min} /></td>
                    <td className="px-3 py-3 text-center"><Num value={r.bucket_30_60min} warn={r.bucket_30_60min > 0 ? 'amber' : null} /></td>
                    <td className="px-3 py-3 text-center"><Num value={r.bucket_1h_24h} warn={r.bucket_1h_24h > 0 ? 'amber' : null} /></td>
                    <td className="px-3 py-3 text-center"><Num value={r.bucket_mas_24h} warn={r.bucket_mas_24h > 0 ? 'red' : null} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-xs text-gray-400 px-4 py-2 border-t border-gray-50">
              <strong>Speed-to-Lead</strong>: contactar en &lt; 5 min es 21x más efectivo que &gt; 30 min (estudio MIT). Apunta a mediana &lt; 5 min.
            </p>
          </div>
        )}

        {/* ── Tab: Heatmap ── (Sprint 2) */}
        {/* Render solo si HAY datos reales (matriz con al menos un slot >0).
            Si toda la matriz esta en 0, el empty state ya cubre el mensaje. */}
        {!isLoading && !error && activeTab === 'heatmap' && tabHasContent && (
          <div className="p-4">
            <HeatmapGrid matriz={data.matriz} max={data.max} />
            <p className="text-xs text-gray-400 mt-3 text-center">
              Hora local Lima (UTC-5). Los slots más oscuros son los de mayor actividad. Útil para optimizar staffing y prospección.
            </p>
          </div>
        )}

        {/* ── Tab: Tiempo Muerto ── (Sprint 2) */}
        {!isLoading && !error && rows.length > 0 && activeTab === 'tiempo-muerto' && (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-100">
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Asesor</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-red-600 uppercase tracking-wide">Leads estancados</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-amber-600 uppercase tracking-wide">Días promedio inactivos</th>
                  <th className="text-center px-3 py-3 text-xs font-semibold text-red-600 uppercase tracking-wide">Máx días inactivos</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {rows.map((r, i) => (
                  <tr key={i} className="hover:bg-red-50/30">
                    <td className="px-4 py-3"><div className="flex items-center gap-2.5"><Avatar name={r.nombre_completo} /><span className="font-medium text-gray-800">{r.nombre_completo}</span></div></td>
                    <td className="px-3 py-3 text-center"><Num value={r.leads_estancados} warn={r.leads_estancados > 0 ? 'red' : null} /></td>
                    <td className="px-3 py-3 text-center font-mono text-sm">{r.dias_promedio_inactivos} d</td>
                    <td className="px-3 py-3 text-center font-mono text-sm text-red-600">{r.max_dias_inactivos} d</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-xs text-gray-400 px-4 py-2 border-t border-gray-50">
              Leads activos no terminales sin contacto en &gt; {data?.umbral_dias || 7} días, agrupados por asesor. Identifica quién necesita apoyo del supervisor.
            </p>
          </div>
        )}

        {/* ── Modal de Detalle de Leads ── */}
        <LeadsDetalleModal
          open={leadsModal.open}
          onClose={() => setLeadsModal({ open: false, context: null })}
          context={leadsModal.context}
        />

      </div>
    </div>
  )
}

/* ────────────────────────────────────────────────────────────────────────── */
/* HeatmapGrid — Sprint 2: matriz 7×24 (días × horas)                         */
/* ────────────────────────────────────────────────────────────────────────── */
function HeatmapGrid({ matriz = [], max = 0 }) {
  const dias = ['Dom', 'Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb']
  return (
    <div className="overflow-x-auto">
      <table className="border-separate border-spacing-1">
        <thead>
          <tr>
            <th className="text-[10px] text-gray-400 px-1"></th>
            {Array.from({ length: 24 }, (_, h) => (
              <th key={h} className="text-[10px] text-gray-400 font-normal w-7 text-center">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {dias.map((dia, di) => (
            <tr key={di}>
              <td className="text-xs text-gray-500 font-medium pr-2">{dia}</td>
              {(matriz[di] || []).map((v, hi) => {
                const intensity = max > 0 ? v / max : 0
                const bg = v === 0
                  ? '#F3F4F6'
                  : `rgba(99, 102, 241, ${0.2 + intensity * 0.8})`
                return (
                  <td
                    key={hi}
                    className="w-7 h-7 rounded text-center text-[10px] font-medium align-middle"
                    style={{ backgroundColor: bg, color: intensity > 0.5 ? '#fff' : '#374151' }}
                    title={`${dia} ${hi}:00 — ${v} actividades`}
                  >
                    {v > 0 ? v : ''}
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
