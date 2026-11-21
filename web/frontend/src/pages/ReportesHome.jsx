/**
 * ReportesHome.jsx — V070.109 — Landing page de reportes.
 *
 * Reemplaza los 2 menus separados (Operativos / Analytics) por UN solo
 * "Reportes" con cards organizadas por categoria + busqueda + role-aware.
 *
 * Cada card al click navega al reporte especifico (la pagina existente).
 */
import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Users, TrendingUp, Filter, Calendar, Phone, Clock,
  GitMerge, AlertTriangle, Star, Search, BarChart3, Gauge, Grid3X3,
  Megaphone,
} from 'lucide-react'
import api from '@/lib/api'
import LoadingSpinner from '@/components/shared/LoadingSpinner'

const ICONS = {
  users:           Users,
  'trending-up':   TrendingUp,
  filter:          Filter,
  calendar:        Calendar,
  phone:           Phone,
  clock:           Clock,
  'git-merge':     GitMerge,
  'alert-triangle': AlertTriangle,
  star:            Star,
  // V095.7 — iconos para los nuevos reportes Velocidad + Cohorts.
  gauge:           Gauge,
  grid:            Grid3X3,
  // V095.9 — icono del reporte Por Campaña.
  megaphone:       Megaphone,
}

const CATEGORY_STYLES = {
  operativos: {
    accent: 'border-l-blue-500 hover:border-l-blue-600',
    badge:  'bg-blue-50 text-blue-700',
    badgeLabel: 'Operativo',
  },
  analytics: {
    accent: 'border-l-indigo-500 hover:border-l-indigo-600',
    badge:  'bg-indigo-50 text-indigo-700',
    badgeLabel: 'Analytics',
  },
}

function ReportCard({ report, onClick }) {
  const Icon = ICONS[report.icon] || BarChart3
  const style = CATEGORY_STYLES[report.category] || CATEGORY_STYLES.operativos
  return (
    <button
      onClick={onClick}
      className={`text-left bg-white border border-gray-100 ${style.accent} border-l-4 rounded-2xl p-5 hover:shadow-md transition-all group`}
    >
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="w-10 h-10 rounded-lg bg-gray-50 flex items-center justify-center text-gray-700 group-hover:bg-gray-100">
          <Icon size={20} />
        </div>
        <span className={`text-xs px-2 py-0.5 rounded font-medium ${style.badge}`}>
          {style.badgeLabel}
        </span>
      </div>
      <h3 className="font-semibold text-gray-900 mb-1">{report.name}</h3>
      <p className="text-sm text-gray-500 leading-relaxed">{report.description}</p>
    </button>
  )
}

export default function ReportesHome() {
  const navigate = useNavigate()
  const [data, setData] = useState({ reports: [], categories: [] })
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')

  useEffect(() => {
    setLoading(true)
    api.get('/api/reportes/v2/catalog')
      .then(res => setData(res.data || { reports: [], categories: [] }))
      .catch(err => setError(err?.response?.data?.detail || err.message || 'Error al cargar catalogo'))
      .finally(() => setLoading(false))
  }, [])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return data.reports
    return data.reports.filter(r =>
      r.name.toLowerCase().includes(q) ||
      r.description.toLowerCase().includes(q),
    )
  }, [data.reports, search])

  const byCategory = useMemo(() => {
    const grouped = {}
    filtered.forEach(r => {
      if (!grouped[r.category]) grouped[r.category] = []
      grouped[r.category].push(r)
    })
    return grouped
  }, [filtered])

  if (loading) return <LoadingSpinner />

  return (
    <div className="space-y-6 max-w-7xl">
      {/* Header */}
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Reportes</h1>
          <p className="text-sm text-gray-500">Analitica y vistas operativas del CRM</p>
        </div>
        {/* Search */}
        <div className="relative w-full sm:w-80">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="search"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Buscar reporte..."
            className="w-full pl-9 pr-3 py-2 bg-white border border-gray-200 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-200 focus:border-indigo-400"
          />
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-3">
          {error}
        </div>
      )}

      {/* Empty state busqueda */}
      {filtered.length === 0 && (
        <div className="bg-white border border-gray-100 rounded-2xl p-12 text-center text-gray-400">
          <Search size={32} className="mx-auto mb-3 opacity-30" />
          <p>No se encontraron reportes con "{search}"</p>
        </div>
      )}

      {/* Categorias */}
      {data.categories.map(cat => {
        const reportsInCat = byCategory[cat.key] || []
        if (reportsInCat.length === 0) return null
        return (
          <section key={cat.key}>
            <div className="mb-3">
              <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wider">
                {cat.name}
              </h2>
              <p className="text-xs text-gray-500">{cat.description}</p>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {reportsInCat.map(r => (
                <ReportCard
                  key={r.key}
                  report={r}
                  onClick={() => navigate(r.path_web)}
                />
              ))}
            </div>
          </section>
        )
      })}
    </div>
  )
}
