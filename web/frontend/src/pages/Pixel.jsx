import { useEffect, useMemo, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Activity, CheckCircle2, AlertTriangle, ArrowRight, RefreshCw,
  TrendingUp, Users, DollarSign, MousePointer, Eye, Percent, Sparkles,
  ChevronRight, Info,
} from 'lucide-react'
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import api from '@/lib/api'
import LoadingSpinner from '@/components/shared/LoadingSpinner'

const PERIODS = [
  { label: 'Hoy',     dias: 1  },
  { label: '7 días',  dias: 7  },
  { label: '30 días', dias: 30 },
  { label: '90 días', dias: 90 },
]

function daysAgo(n) {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d.toISOString().slice(0, 10)
}

const today = () => new Date().toISOString().slice(0, 10)

function KpiCard({ label, value, sub, icon: Icon, tone = 'indigo' }) {
  const tones = {
    indigo: 'from-indigo-500/10 text-indigo-700 border-indigo-100 dark:border-indigo-900/50',
    green:  'from-green-500/10  text-green-700  border-green-100 dark:border-green-900/50',
    amber:  'from-amber-500/10  text-amber-700  border-amber-100 dark:border-amber-900/50',
    red:    'from-red-500/10    text-red-700    border-red-100 dark:border-red-900/50',
    blue:   'from-blue-500/10   text-blue-700   border-blue-100 dark:border-blue-900/50',
    slate:  'from-slate-500/10  text-slate-700  border-slate-100 dark:border-slate-900/50',
  }
  return (
    <div className={`p-5 rounded-2xl border bg-gradient-to-br to-white hover:shadow-md transition-all duration-200 group ${tones[tone] || tones.indigo}`}>
      <div className="flex items-center justify-between mb-3">
        <span className="text-xs uppercase tracking-wider font-semibold opacity-80">{label}</span>
        {Icon && <Icon size={18} className="opacity-70 group-hover:scale-110 transition-transform duration-200" />}
      </div>
      <div className="text-3xl font-bold tabular-nums tracking-tight">{value}</div>
      {sub && <div className="text-xs opacity-85 mt-2 font-medium">{sub}</div>}
    </div>
  )
}

export default function Pixel() {
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState('meta')
  const [periodIdx, setPeriodIdx] = useState(2) // Default 30 días
  const [customDesde, setCustomDesde] = useState(daysAgo(30))
  const [customHasta, setCustomHasta] = useState(today())
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [data, setData] = useState(null)

  const dateRange = useMemo(() => ({
    fecha_desde: customDesde,
    fecha_hasta: customHasta,
  }), [customDesde, customHasta])

  const handlePeriodChange = (i) => {
    setPeriodIdx(i)
    setCustomDesde(daysAgo(PERIODS[i].dias))
    setCustomHasta(today())
  }

  const handleCustomDesdeChange = (e) => {
    setCustomDesde(e.target.value)
    setPeriodIdx(-1)
  }

  const handleCustomHastaChange = (e) => {
    setCustomHasta(e.target.value)
    setPeriodIdx(-1)
  }

  const loadData = useCallback(async () => {
    setError('')
    setLoading(true)
    try {
      const res = await api.get('/api/integrations/pixel/metrics', {
        params: dateRange
      })
      setData(res.data)
    } catch (err) {
      setError(err?.response?.data?.detail || err.message || 'Error al cargar métricas de píxel')
    } finally {
      setLoading(false)
    }
  }, [dateRange])

  useEffect(() => {
    loadData()
  }, [loadData])

  const currentTabInfo = useMemo(() => {
    if (!data) return null
    return data[activeTab]
  }, [data, activeTab])

  const [selectedCampaigns, setSelectedCampaigns] = useState([])

  // Resetear filtro al cambiar de pestaña
  useEffect(() => {
    setSelectedCampaigns([])
  }, [activeTab])

  const filteredTabInfo = useMemo(() => {
    if (!currentTabInfo) return null
    if (selectedCampaigns.length === 0) return currentTabInfo

    const filteredCampaigns = currentTabInfo.campaigns.filter(c =>
      selectedCampaigns.includes(c.name)
    )

    let spend = 0
    let conversions = 0
    let closed_won = 0
    let impressions = 0
    let clicks = 0

    filteredCampaigns.forEach(c => {
      spend += c.spend || 0
      conversions += c.leads || c.conversions || 0
      closed_won += c.sales || 0
      impressions += c.impressions || ((c.leads || c.conversions || 0) * 120)
      clicks += c.clicks || Math.round((c.leads || c.conversions || 0) * 8.5)
    })

    const roundNumber = (num, decimals = 2) => {
      return Math.round((num + Number.EPSILON) * Math.pow(10, decimals)) / Math.pow(10, decimals)
    }

    const conversion_rate = conversions > 0 ? roundNumber((closed_won / conversions) * 100, 1) : 0
    const ctr = impressions > 0 ? roundNumber((clicks / impressions) * 100, 2) : 0
    const cpl = conversions > 0 ? roundNumber(spend / conversions, 2) : 0
    const cpc = clicks > 0 ? roundNumber(spend / clicks, 2) : 0

    const totalConversions = currentTabInfo.metrics.conversions || 1
    const ratio = conversions / totalConversions
    const filteredTrend = currentTabInfo.trend.map(t => ({
      ...t,
      leads: Math.round(t.leads * ratio),
      conversions: Math.round(t.conversions * ratio),
      ventas: Math.round(t.ventas * ratio)
    }))

    return {
      ...currentTabInfo,
      metrics: {
        ...currentTabInfo.metrics,
        spend,
        conversions,
        leads: conversions,
        closed_won,
        conversion_rate,
        impressions,
        clicks,
        ctr,
        cpl,
        cpc,
      },
      campaigns: filteredCampaigns,
      trend: filteredTrend
    }
  }, [currentTabInfo, selectedCampaigns])

  if (loading && !data) {
    return <LoadingSpinner />
  }

  const formatCurrency = (val) => {
    return new Intl.NumberFormat('es-PE', { style: 'currency', currency: 'PEN' }).format(val)
  }

  return (
    <div className="space-y-6 max-w-7xl">
      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 tracking-tight">Rendimiento de Ads</h1>
          <p className="text-sm text-gray-500">Métricas de conversión y rendimiento de campañas publicitarias</p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-1.5 bg-gray-50 p-1 border border-gray-100 rounded-xl">
              {PERIODS.map((p, i) => (
                <button
                  key={p.label}
                  onClick={() => handlePeriodChange(i)}
                  className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all duration-150 ${
                    periodIdx === i ? 'bg-indigo-600 text-white shadow-sm' : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
            <button
              onClick={loadData}
              disabled={loading}
              className="p-2.5 rounded-xl bg-white border border-gray-200 text-gray-600 hover:bg-gray-50 disabled:opacity-50 transition-all shadow-sm"
              title="Refrescar"
            >
              <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            </button>
          </div>

          <div className="flex items-center gap-2 text-xs">
            <span className="text-gray-400 font-medium">Desde:</span>
            <input
              type="date"
              value={customDesde}
              onChange={handleCustomDesdeChange}
              max={customHasta}
              className="px-2.5 py-1 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white text-gray-700 shadow-sm font-medium"
            />
            <span className="text-gray-400 font-medium">Hasta:</span>
            <input
              type="date"
              value={customHasta}
              onChange={handleCustomHastaChange}
              min={customDesde}
              max={today()}
              className="px-2.5 py-1 border border-gray-200 rounded-lg text-xs focus:outline-none focus:ring-1 focus:ring-indigo-500 bg-white text-gray-700 shadow-sm font-medium"
            />
          </div>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-4 py-3 flex items-center gap-2">
          <AlertTriangle size={16} />
          {error}
        </div>
      )}

      {/* Tabs */}
      <div className="border-b border-gray-200">
        <div className="flex gap-6">
          <button
            onClick={() => setActiveTab('meta')}
            className={`pb-3 text-sm font-semibold tracking-wide border-b-2 transition-all relative ${
              activeTab === 'meta'
                ? 'border-indigo-600 text-indigo-600'
                : 'border-transparent text-gray-500 hover:text-gray-900'
            }`}
          >
            Meta Pixel
            {data?.meta?.connected && (
              <span className="absolute top-0 -right-2.5 w-1.5 h-1.5 rounded-full bg-emerald-500" />
            )}
          </button>
          <button
            onClick={() => setActiveTab('tiktok')}
            className={`pb-3 text-sm font-semibold tracking-wide border-b-2 transition-all relative ${
              activeTab === 'tiktok'
                ? 'border-indigo-600 text-indigo-600'
                : 'border-transparent text-gray-500 hover:text-gray-900'
            }`}
          >
            TikTok Pixel
            {data?.tiktok?.connected && (
              <span className="absolute top-0 -right-2.5 w-1.5 h-1.5 rounded-full bg-emerald-500" />
            )}
          </button>
        </div>
      </div>

      {currentTabInfo && (
        <div className="space-y-6">
          {/* Status banner */}
          <div className="flex items-center justify-between gap-4 p-4 bg-white border border-gray-100 rounded-2xl shadow-sm flex-wrap">
            <div className="flex items-center gap-3">
              <div className={`w-10 h-10 rounded-xl flex items-center justify-center ${
                currentTabInfo.connected ? 'bg-emerald-50 text-emerald-600' : 'bg-gray-100 text-gray-400'
              }`}>
                <Activity size={20} />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-gray-900 capitalize">{activeTab} Pixel</span>
                  {currentTabInfo.connected ? (
                    <span className="bg-emerald-100 text-emerald-800 text-[10px] font-bold px-2 py-0.5 rounded-full flex items-center gap-1">
                      <CheckCircle2 size={10} /> Conectado
                    </span>
                  ) : (
                    <span className="bg-gray-100 text-gray-600 text-[10px] font-bold px-2 py-0.5 rounded-full">
                      Desconectado
                    </span>
                  )}
                </div>
                <p className="text-xs text-gray-500 mt-0.5">
                  {currentTabInfo.connected
                    ? `ID del Píxel: ${currentTabInfo.pixel_id.slice(0, 4)}***${currentTabInfo.pixel_id.slice(-4)}`
                    : 'Permite medir conversiones en tus formularios web'}
                </p>
              </div>
            </div>
            {currentTabInfo.connected && currentTabInfo.metrics?.is_mocked && (
              <div className="bg-indigo-50 border border-indigo-100 rounded-xl px-4 py-2 flex items-center gap-2 text-indigo-700 text-xs font-semibold">
                <Sparkles size={14} className="shrink-0" />
                Modo Demostración — Mostrando métricas de ejemplo para el diseño
              </div>
            )}
          </div>

          {!currentTabInfo.connected ? (
            /* Disconnected state */
            <div className="bg-gradient-to-br from-indigo-50/40 via-white to-slate-50/50 border border-gray-100 rounded-3xl p-12 text-center shadow-sm">
              <div className="w-16 h-16 bg-indigo-50 rounded-2xl flex items-center justify-center text-indigo-600 mx-auto mb-5 shadow-inner">
                <Activity size={32} />
              </div>
              <h3 className="text-xl font-bold text-gray-900 mb-2">El Píxel de {activeTab === 'meta' ? 'Meta' : 'TikTok'} no está conectado</h3>
              <p className="text-sm text-gray-500 max-w-md mx-auto mb-6 leading-relaxed">
                Conecta tu Píxel en la sección de integraciones para rastrear visitas, conversiones en tus formularios públicos y calcular el ROI publicitario de forma automática.
              </p>
              <button
                onClick={() => navigate('/integraciones')}
                className="inline-flex items-center gap-2 px-5 py-2.5 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold rounded-xl shadow-md transition-all duration-150 hover:-translate-y-0.5"
              >
                Configurar Integración <ArrowRight size={16} />
              </button>
            </div>
          ) : (
            /* Connected metrics */
            <div className="space-y-6">
              {/* Campaign Selector */}
              {currentTabInfo.campaigns && currentTabInfo.campaigns.length > 0 && (
                <div className="bg-white border border-gray-100 rounded-2xl p-5 shadow-sm space-y-3">
                  <div className="flex items-center justify-between flex-wrap gap-2">
                    <div>
                      <h4 className="text-sm font-bold text-gray-800">Filtrar por Campaña</h4>
                      <p className="text-xs text-gray-500">Selecciona una o más campañas para ver sus datos específicos en el dashboard</p>
                    </div>
                    {selectedCampaigns.length > 0 && (
                      <button
                        onClick={() => setSelectedCampaigns([])}
                        className="text-xs font-semibold text-indigo-600 hover:text-indigo-800 transition-colors"
                      >
                        Limpiar filtros (Mostrar todas)
                      </button>
                    )}
                  </div>
                  <div className="flex flex-wrap gap-2 pt-1">
                    <button
                      onClick={() => setSelectedCampaigns([])}
                      className={`px-3.5 py-1.5 rounded-xl text-xs font-semibold transition-all duration-150 border ${
                        selectedCampaigns.length === 0
                          ? 'bg-indigo-600 border-indigo-600 text-white shadow-sm font-semibold'
                          : 'bg-gray-50 border-gray-100 text-gray-600 hover:bg-gray-100 hover:text-gray-900'
                      }`}
                    >
                      Todas las campañas ({currentTabInfo.campaigns.length})
                    </button>
                    {currentTabInfo.campaigns.map((camp) => {
                      const isSelected = selectedCampaigns.includes(camp.name)
                      return (
                        <button
                          key={camp.name}
                          onClick={() => {
                            if (isSelected) {
                              setSelectedCampaigns(selectedCampaigns.filter(name => name !== camp.name))
                            } else {
                              setSelectedCampaigns([...selectedCampaigns, camp.name])
                            }
                          }}
                          className={`px-3.5 py-1.5 rounded-xl text-xs font-medium border transition-all duration-150 max-w-[280px] truncate ${
                            isSelected
                              ? 'bg-indigo-600 border-indigo-600 text-white shadow-sm font-semibold'
                              : 'bg-white border-gray-200 text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                          }`}
                          title={camp.name}
                        >
                          {camp.name}
                        </button>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* KPIs Grid */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <KpiCard
                  label="Inversión Estimada"
                  value={formatCurrency(filteredTabInfo.metrics.spend)}
                  sub="Inversión total en anuncios"
                  icon={DollarSign}
                  tone="slate"
                />
                <KpiCard
                  label="Conversiones (Pixel)"
                  value={filteredTabInfo.metrics.conversions}
                  sub="Leads capturados por el píxel"
                  icon={Users}
                  tone="indigo"
                />
                <KpiCard
                  label="Ventas Concretadas"
                  value={filteredTabInfo.metrics.closed_won}
                  sub={`Conversión final de ventas`}
                  icon={TrendingUp}
                  tone="green"
                />
                <KpiCard
                  label="Tasa de Cierre"
                  value={`${filteredTabInfo.metrics.conversion_rate}%`}
                  sub="Porcentaje de leads ganados"
                  icon={Percent}
                  tone="amber"
                />
              </div>

              {/* Secondary KPIs */}
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
                <div className="p-4 bg-white border border-gray-100 rounded-xl flex items-center justify-between shadow-sm">
                  <div>
                    <span className="text-[10px] uppercase font-bold text-gray-400 tracking-wider">Impresiones</span>
                    <p className="text-xl font-bold text-gray-800 tabular-nums mt-1">{filteredTabInfo.metrics.impressions.toLocaleString()}</p>
                  </div>
                  <Eye size={18} className="text-gray-400" />
                </div>
                <div className="p-4 bg-white border border-gray-100 rounded-xl flex items-center justify-between shadow-sm">
                  <div>
                    <span className="text-[10px] uppercase font-bold text-gray-400 tracking-wider">Clics</span>
                    <p className="text-xl font-bold text-gray-800 tabular-nums mt-1">{filteredTabInfo.metrics.clicks.toLocaleString()}</p>
                  </div>
                  <MousePointer size={18} className="text-gray-400" />
                </div>
                <div className="p-4 bg-white border border-gray-100 rounded-xl flex items-center justify-between shadow-sm">
                  <div>
                    <span className="text-[10px] uppercase font-bold text-gray-400 tracking-wider">CTR Promedio</span>
                    <p className="text-xl font-bold text-gray-800 tabular-nums mt-1">{filteredTabInfo.metrics.ctr}%</p>
                  </div>
                  <Percent size={18} className="text-gray-400" />
                </div>
                <div className="p-4 bg-white border border-gray-100 rounded-xl flex items-center justify-between shadow-sm">
                  <div>
                    <span className="text-[10px] uppercase font-bold text-gray-400 tracking-wider">Costo por Lead (CPL)</span>
                    <p className="text-xl font-bold text-gray-800 tabular-nums mt-1">{formatCurrency(filteredTabInfo.metrics.cpl)}</p>
                  </div>
                  <DollarSign size={18} className="text-gray-400" />
                </div>
              </div>

              {/* Chart & Campaigns breakdown */}
              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Trend Chart */}
                <div className="bg-white border border-gray-100 rounded-2xl p-5 shadow-sm lg:col-span-2">
                  <div className="mb-4">
                    <h3 className="font-bold text-gray-800">Tendencia de Rendimiento</h3>
                    <p className="text-xs text-gray-500">Historial diario de conversiones y ventas concretadas</p>
                  </div>
                  {filteredTabInfo.trend.length === 0 ? (
                    <div className="h-64 flex items-center justify-center text-gray-400 text-sm">
                      Sin datos en el rango seleccionado
                    </div>
                  ) : (
                    <ResponsiveContainer width="100%" height={260}>
                      <AreaChart data={filteredTabInfo.trend} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                        <defs>
                          <linearGradient id="colorConv" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#6366F1" stopOpacity={0.2}/>
                            <stop offset="95%" stopColor="#6366F1" stopOpacity={0}/>
                          </linearGradient>
                          <linearGradient id="colorSales" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="5%" stopColor="#10B981" stopOpacity={0.2}/>
                            <stop offset="95%" stopColor="#10B981" stopOpacity={0}/>
                          </linearGradient>
                        </defs>
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#F3F4F6" />
                        <XAxis dataKey="fecha" stroke="#9CA3AF" fontSize={10} tickLine={false} />
                        <YAxis stroke="#9CA3AF" fontSize={10} tickLine={false} axisLine={false} />
                        <Tooltip />
                        <Area type="monotone" dataKey="conversions" name="Conversiones" stroke="#6366F1" strokeWidth={2} fillOpacity={1} fill="url(#colorConv)" />
                        <Area type="monotone" dataKey="ventas" name="Ventas" stroke="#10B981" strokeWidth={2} fillOpacity={1} fill="url(#colorSales)" />
                      </AreaChart>
                    </ResponsiveContainer>
                  )}
                </div>

                {/* Campaigns side list */}
                <div className="bg-white border border-gray-100 rounded-2xl p-5 shadow-sm flex flex-col justify-between">
                  <div>
                    <div className="mb-4">
                      <h3 className="font-bold text-gray-800">Campaña Principal</h3>
                      <p className="text-xs text-gray-500">Distribución por campaña publicitaria</p>
                    </div>
                    {filteredTabInfo.campaigns.length === 0 ? (
                      <div className="text-center py-12 text-gray-400 text-sm">
                        No hay campañas registradas
                      </div>
                    ) : (
                      <div className="space-y-4">
                        {filteredTabInfo.campaigns.slice(0, 3).map((camp, idx) => (
                          <div key={idx} className="p-3 bg-gray-50 border border-gray-100 rounded-xl">
                            <div className="flex items-start justify-between gap-2">
                              <span className="text-xs font-bold text-gray-900 truncate max-w-[170px]" title={camp.name}>
                                {camp.name}
                              </span>
                              <span className="text-[10px] bg-indigo-100 text-indigo-800 font-extrabold px-1.5 py-0.5 rounded">
                                {camp.leads} leads
                              </span>
                            </div>
                            <div className="grid grid-cols-3 gap-2 mt-3 pt-2 border-t border-gray-100/50 text-[10px] text-gray-500 font-medium">
                              <div>
                                <span className="block text-[8px] uppercase text-gray-400">Inversión</span>
                                <span className="font-bold text-gray-700">{formatCurrency(camp.spend)}</span>
                              </div>
                              <div>
                                <span className="block text-[8px] uppercase text-gray-400">Ventas</span>
                                <span className="font-bold text-gray-700">{camp.sales}</span>
                              </div>
                              <div>
                                <span className="block text-[8px] uppercase text-gray-400">Conversión</span>
                                <span className="font-bold text-emerald-600">{camp.conversion_rate}%</span>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                  {filteredTabInfo.campaigns.length > 3 && (
                    <div className="text-xs text-gray-400 text-center flex items-center justify-center gap-1 cursor-pointer hover:text-indigo-600 pt-3 border-t border-gray-100 font-semibold">
                      Ver todas las campañas <ChevronRight size={14} />
                    </div>
                  )}
                </div>
              </div>

              {/* Table of campaigns detailed breakdown */}
              {filteredTabInfo.campaigns.length > 0 && (
                <div className="bg-white border border-gray-100 rounded-2xl shadow-sm overflow-hidden md:overflow-visible">
                  <div className="p-5 border-b border-gray-100">
                    <h3 className="font-bold text-gray-800">Desglose de Campañas</h3>
                    <p className="text-xs text-gray-500">Métricas analíticas por campaña</p>
                  </div>
                  <div className="overflow-x-auto md:overflow-x-visible">
                    <table className="w-full text-sm">
                      <thead className="bg-gray-50 text-[10px] text-gray-400 uppercase font-bold border-b border-gray-100">
                        <tr>
                          <th className="text-left py-3 px-5 whitespace-nowrap">
                            Campaña
                            <Info size={12} title="Nombre de la campaña publicitaria según la plataforma de anuncios." className="text-gray-400 hover:text-gray-600 cursor-help inline-block ml-1 align-middle" />
                          </th>
                          <th className="text-right py-3 px-5 whitespace-nowrap">
                            Leads
                            <Info size={12} title="Total de prospectos capturados (Resultados oficiales de la API de anuncios)." className="text-gray-400 hover:text-gray-600 cursor-help inline-block ml-1 align-middle" />
                          </th>
                          <th className="text-right py-3 px-5 whitespace-nowrap">
                            Ventas
                            <Info size={12} title="Cantidad de clientes potenciales que han sido marcados como concretados/ganados en tu CRM." className="text-gray-400 hover:text-gray-600 cursor-help inline-block ml-1 align-middle" />
                          </th>
                          <th className="text-right py-3 px-5 whitespace-nowrap">
                            Inversión
                            <Info size={12} title="Gasto real total reportado por la plataforma de anuncios." className="text-gray-400 hover:text-gray-600 cursor-help inline-block ml-1 align-middle" />
                          </th>
                          <th className="text-right py-3 px-5 whitespace-nowrap">
                            Costo/Res (API)
                            <Info size={12} title="Costo promedio por cada resultado oficial obtenido de la API de anuncios (Inversión / Resultados)." className="text-gray-400 hover:text-gray-600 cursor-help inline-block ml-1 align-middle" />
                          </th>
                          <th className="text-right py-3 px-5 whitespace-nowrap">
                            CPM (API)
                            <Info size={12} title="Costo promedio por cada mil impresiones de los anuncios." className="text-gray-400 hover:text-gray-600 cursor-help inline-block ml-1 align-middle" />
                          </th>
                          <th className="text-right py-3 px-5 whitespace-nowrap">
                            CPL (CRM)
                            <Info size={12} title="Costo promedio por cada lead ingresado en tu base de datos local del CRM (Inversión / Leads locales)." className="text-gray-400 hover:text-gray-600 cursor-help inline-block ml-1 align-middle" />
                          </th>
                          <th className="text-right py-3 px-5 whitespace-nowrap">
                            Tasa Cierre
                            <Info size={12} title="Porcentaje de leads recibidos que lograste convertir en ventas ganadas (Ventas / Leads del CRM)." className="text-gray-400 hover:text-gray-600 cursor-help inline-block ml-1 align-middle" />
                          </th>
                        </tr>
                      </thead>
                      <tbody className="divide-y divide-gray-100">
                        {filteredTabInfo.campaigns.map((camp, idx) => (
                          <tr key={idx} className="hover:bg-gray-50/50 transition-colors">
                            <td className="py-3.5 px-5 font-semibold text-gray-800 max-w-xs truncate">{camp.name}</td>
                            <td className="text-right py-3.5 px-5 font-medium tabular-nums">{camp.leads}</td>
                            <td className="text-right py-3.5 px-5 font-medium tabular-nums">{camp.sales}</td>
                            <td className="text-right py-3.5 px-5 font-bold text-gray-700 tabular-nums">{formatCurrency(camp.spend)}</td>
                            <td className="text-right py-3.5 px-5 font-bold text-gray-600 tabular-nums">{formatCurrency(camp.api_cpr)}</td>
                            <td className="text-right py-3.5 px-5 font-bold text-gray-600 tabular-nums">{formatCurrency(camp.api_cpm)}</td>
                            <td className="text-right py-3.5 px-5 font-bold text-gray-600 tabular-nums">{formatCurrency(camp.cpl)}</td>
                            <td className="text-right py-3.5 px-5 font-semibold text-emerald-600 tabular-nums">{camp.conversion_rate}%</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
