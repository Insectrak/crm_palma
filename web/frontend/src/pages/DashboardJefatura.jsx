import React, { useState, useEffect } from 'react'
import {
  Users, Clock, Calendar, CheckCircle2, AlertTriangle, AlertOctagon,
  TrendingUp, Award, Building2, UserCheck, ShieldAlert, BarChart3,
  RefreshCw, Filter, ChevronRight, UserX, PhoneCall, ShieldCheck, Lock
} from 'lucide-react'
import {
  ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip,
  PieChart, Pie, Cell, Legend
} from 'recharts'
import api from '@/lib/api'

const COLORS = ['#6366F1', '#EC4899', '#F59E0B', '#10B981', '#3B82F6', '#8B5CF6', '#EF4444', '#64748B']

export default function DashboardJefatura() {
  const [periodo, setPeriodo] = useState('mes')
  const [sedeId, setSedeId] = useState('')
  const [supervisorId, setSupervisorId] = useState('')
  const [asesorId, setAsesorId] = useState('')
  const [loading, setLoading] = useState(true)
  const [data, setData] = useState(null)
  const [accesoDenegado, setAccesoDenegado] = useState(false)

  const [sedesList, setSedesList] = useState([])
  const [supervisoresList, setSupervisoresList] = useState([])
  const [asesoresList, setAsesoresList] = useState([])

  // Cargar catálogos de filtro
  useEffect(() => {
    async function loadCatalogs() {
      try {
        const [resSedes, resUsers] = await Promise.all([
          api.get('/api/sedes/lookup?only_active=true').catch(() => ({ data: [] })),
          api.get('/auth/users').catch(() => ({ data: [] })),
        ])
        setSedesList(resSedes.data || [])
        const allUsers = resUsers.data || []
        setSupervisoresList(allUsers.filter(u => u.role === 'supervisor' && u.is_active !== false))
        setAsesoresList(allUsers.filter(u => u.role === 'asesor' && u.is_active !== false))
      } catch (err) {
        console.error('Error cargando filtros:', err)
      }
    }
    loadCatalogs()
  }, [])

  // Cargar métricas del dashboard
  const fetchMetrics = async () => {
    setLoading(true)
    setAccesoDenegado(false)
    try {
      const params = new URLSearchParams()
      params.append('periodo', periodo)
      if (sedeId) params.append('sede_id', sedeId)
      if (supervisorId) params.append('supervisor_id', supervisorId)
      if (asesorId) params.append('asesor_id', asesorId)

      const res = await api.get(`/api/dashboard/jefatura/resumen?${params.toString()}`)
      console.log('Dashboard Jefatura data:', res.data)
      setData(res.data)
    } catch (err) {
      if (err.response?.status === 403) {
        setAccesoDenegado(true)
      }
      console.error('Error al obtener métricas de jefatura:', err)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchMetrics()
  }, [periodo, sedeId, supervisorId, asesorId])

  if (accesoDenegado) {
    return (
      <div className="p-8 max-w-xl mx-auto mt-16 text-center bg-white rounded-3xl border border-slate-100 shadow-sm space-y-4 animate-fadeIn">
        <div className="w-16 h-16 bg-rose-50 text-rose-500 rounded-full flex items-center justify-center mx-auto">
          <Lock size={32} />
        </div>
        <h2 className="text-xl font-bold text-slate-800">Acceso Restringido al Panel de Jefatura</h2>
        <p className="text-sm text-slate-500">
          Este panel está reservado para la Jefatura de Ventas y Supervisores autorizados. Si necesitas acceso, solicita a un administrador que habilite tu usuario en el módulo de <strong>Configuración &gt; Panel Jefatura</strong>.
        </p>
      </div>
    )
  }

  const m = data?.metricas || {}
  const sla = m.sla || {}
  const seg = m.seguimientos || {}
  const cit = m.citas || {}
  const mat = m.matriculas || {}
  const per = m.perdidos || {}

  return (
    <div className="p-6 max-w-[1600px] mx-auto space-y-6 animate-fadeIn">
      {/* Header y Filtros */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-white p-5 rounded-2xl shadow-sm border border-slate-100">
        <div>
          <div className="flex items-center gap-2">
            <span className="p-2 bg-indigo-50 text-indigo-600 rounded-xl">
              <BarChart3 size={24} />
            </span>
            <div>
              <h1 className="text-xl font-bold text-slate-800">Panel de Control de Jefatura y Supervisión</h1>
              <p className="text-xs text-slate-500">Métricas consolidadas de tiempos de gestión (SLA), conversión y seguimiento</p>
            </div>
          </div>
        </div>

        {/* Controles de Filtro */}
        <div className="flex flex-wrap items-center gap-2">
          {/* Selector Período */}
          <div className="inline-flex bg-slate-100 p-1 rounded-xl text-xs font-semibold">
            {[
              { key: 'dia', label: 'Hoy' },
              { key: 'semana', label: 'Esta Semana' },
              { key: 'mes', label: 'Este Mes' },
              { key: '30dias', label: 'Últimos 30d' },
              { key: 'todos', label: 'Histórico' },
            ].map(p => (
              <button
                key={p.key}
                onClick={() => setPeriodo(p.key)}
                className={`px-3 py-1.5 rounded-lg transition-all ${
                  periodo === p.key ? 'bg-white text-indigo-600 shadow-sm' : 'text-slate-600 hover:text-slate-900'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>

          {/* Sede */}
          <select
            value={sedeId}
            onChange={e => setSedeId(e.target.value)}
            className="text-xs font-medium bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 text-slate-700 outline-none focus:ring-2 focus:ring-indigo-500/20"
          >
            <option value="">Todas las Sedes</option>
            {sedesList.map(s => (
              <option key={s.id} value={s.id}>{s.nombre}</option>
            ))}
          </select>

          {/* Supervisor */}
          <select
            value={supervisorId}
            onChange={e => setSupervisorId(e.target.value)}
            className="text-xs font-medium bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 text-slate-700 outline-none focus:ring-2 focus:ring-indigo-500/20"
          >
            <option value="">Todos los Supervisores</option>
            {supervisoresList.map(sup => (
              <option key={sup.id} value={sup.id}>{sup.first_name} {sup.last_name}</option>
            ))}
          </select>

          {/* Asesor */}
          <select
            value={asesorId}
            onChange={e => setAsesorId(e.target.value)}
            className="text-xs font-medium bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 text-slate-700 outline-none focus:ring-2 focus:ring-indigo-500/20"
          >
            <option value="">Todos los Asesores</option>
            {asesoresList.map(a => (
              <option key={a.id} value={a.id}>{a.first_name} {a.last_name}</option>
            ))}
          </select>

          <button
            onClick={fetchMetrics}
            disabled={loading}
            className="p-2 bg-slate-50 hover:bg-slate-100 border border-slate-200 text-slate-600 rounded-xl transition-all"
            title="Refrescar datos"
          >
            <RefreshCw size={16} className={loading ? 'animate-spin text-indigo-600' : ''} />
          </button>
        </div>
      </div>

      {/* Grid de KPIs Principales */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* 1. Leads Nuevos */}
        <div className="bg-white p-5 rounded-2xl border border-slate-100 shadow-sm flex items-center justify-between">
          <div>
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Leads Nuevos</span>
            <div className="text-2xl font-bold text-slate-800 mt-1">{m.leads_nuevos ?? 0}</div>
            <span className="text-[11px] text-slate-500">
              {periodo === 'todos' ? 'Total histórico' : 'Ingresados en período'}
            </span>
          </div>
          <div className="p-3 bg-blue-50 text-blue-600 rounded-2xl">
            <Users size={24} />
          </div>
        </div>

        {/* 2. SLA Primer Contacto (<= 15 min) */}
        <div className="bg-white p-5 rounded-2xl border border-slate-100 shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between">
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">SLA Primer Contacto</span>
            <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${
              (sla.cumplimiento_pct ?? 100) >= 80 ? 'bg-emerald-50 text-emerald-600' : 'bg-amber-50 text-amber-600'
            }`}>
              {sla.cumplimiento_pct ?? 100}%
            </span>
          </div>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-2xl font-bold text-slate-800">{sla.gestionados_le_15m ?? 0}</span>
            <span className="text-xs text-slate-500">en &le; 15m / <strong className="text-rose-500">{sla.sin_gestion_gt_15m ?? 0}</strong> &gt; 15m</span>
          </div>
          {/* Progress bar */}
          <div className="w-full bg-slate-100 h-1.5 rounded-full mt-3 overflow-hidden">
            <div
              className="bg-indigo-600 h-full rounded-full transition-all duration-500"
              style={{ width: `${Math.min(100, Math.max(0, sla.cumplimiento_pct ?? 0))}%` }}
            />
          </div>
        </div>

        {/* 3. Seguimientos (Hoy vs Vencidos) */}
        <div className="bg-white p-5 rounded-2xl border border-slate-100 shadow-sm flex items-center justify-between">
          <div>
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              {periodo === 'dia' ? 'Seguimientos Hoy' : 'Seguimientos'}
            </span>
            <div className="flex items-baseline gap-2 mt-1">
              <span className="text-2xl font-bold text-slate-800">{seg.hoy ?? 0}</span>
              <span className="text-xs text-slate-500">{periodo === 'dia' ? 'para hoy' : 'programados'}</span>
            </div>
            <div className="text-[11px] font-semibold text-rose-500 mt-0.5">
              {seg.vencidos ?? 0} seguimientos vencidos
            </div>
          </div>
          <div className={`p-3 rounded-2xl ${seg.vencidos > 0 ? 'bg-rose-50 text-rose-600' : 'bg-emerald-50 text-emerald-600'}`}>
            <Clock size={24} />
          </div>
        </div>

        {/* 4. Citas del Día / Período */}
        <div className="bg-white p-5 rounded-2xl border border-slate-100 shadow-sm flex items-center justify-between">
          <div>
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
              {periodo === 'dia' ? 'Citas de Hoy' : (periodo === 'todos' ? 'Citas Totales' : 'Citas del Período')}
            </span>
            <div className="text-2xl font-bold text-slate-800 mt-1">{cit.hoy ?? 0}</div>
            <span className="text-[11px] text-emerald-600 font-semibold">{cit.atendidas_hoy ?? 0} atendidas</span>
          </div>
          <div className="p-3 bg-purple-50 text-purple-600 rounded-2xl">
            <Calendar size={24} />
          </div>
        </div>
      </div>

      {/* Segunda fila de KPIs */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* COD (Cierre / Compromiso) */}
        <div className="bg-white p-5 rounded-2xl border border-slate-100 shadow-sm">
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">COD / Compromisos</span>
          <div className="text-2xl font-bold text-indigo-600 mt-1">{m.cod ?? 0}</div>
          <span className="text-[11px] text-slate-500">
            {periodo === 'todos' ? 'Total en compromiso' : 'En compromiso en período'}
          </span>
        </div>

        {/* Matrículas y Verificadas */}
        <div className="bg-white p-5 rounded-2xl border border-slate-100 shadow-sm">
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
            {periodo === 'todos' ? 'Matrículas Totales' : 'Matrículas del Período'}
          </span>
          <div className="flex items-baseline gap-2 mt-1">
            <span className="text-2xl font-bold text-emerald-600">{mat.total ?? 0}</span>
            <span className="text-xs text-slate-500">({mat.verificadas ?? 0} con 2da voz)</span>
          </div>
          <span className="text-[11px] text-slate-500">
            {periodo === 'todos' ? 'Cierres confirmados históricos' : 'Cierres en período'}
          </span>
        </div>

        {/* Total Perdidos */}
        <div className="bg-white p-5 rounded-2xl border border-slate-100 shadow-sm">
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">
            {periodo === 'todos' ? 'Total Perdidos' : 'Perdidos en Período'}
          </span>
          <div className="text-2xl font-bold text-slate-700 mt-1">{per.total ?? 0}</div>
          <span className="text-[11px] text-slate-500">
            {periodo === 'todos' ? 'Leads sin conversión históricos' : 'Leads sin conversión en período'}
          </span>
        </div>

        {/* Estancados > 30 días */}
        <div className="bg-white p-5 rounded-2xl border border-slate-100 shadow-sm">
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Estancados &gt; 30 días</span>
          <div className="text-2xl font-bold text-amber-600 mt-1">{m.estancados_30d ?? 0}</div>
          <span className="text-[11px] text-slate-500">Candidatos a Bolsa TMK</span>
        </div>
      </div>

      {/* Gráficos y Desglose */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Motivos de Pérdida (Dona/Pie) */}
        <div className="bg-white p-5 rounded-2xl border border-slate-100 shadow-sm">
          <h2 className="text-sm font-bold text-slate-800 mb-4 flex items-center gap-2">
            <AlertOctagon size={18} className="text-rose-500" />
            Desglose por Motivos de Pérdida
          </h2>
          {per.desglose_motivos?.length > 0 ? (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <PieChart>
                  <Pie
                    data={per.desglose_motivos}
                    dataKey="total"
                    nameKey="motivo"
                    cx="50%"
                    cy="50%"
                    outerRadius={80}
                    innerRadius={45}
                    paddingAngle={3}
                  >
                    {per.desglose_motivos.map((entry, index) => (
                      <Cell key={`cell-${index}`} fill={COLORS[index % COLORS.length]} />
                    ))}
                  </Pie>
                  <Tooltip formatter={(value, name) => [`${value} leads`, name]} />
                  <Legend layout="horizontal" verticalAlign="bottom" align="center" wrapperStyle={{ fontSize: '11px' }} />
                </PieChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="h-64 flex items-center justify-center text-xs text-slate-400">
              No hay leads perdidos registrados en el período.
            </div>
          )}
        </div>

        {/* Desglose por Sedes */}
        <div className="bg-white p-5 rounded-2xl border border-slate-100 shadow-sm lg:col-span-2">
          <h2 className="text-sm font-bold text-slate-800 mb-4 flex items-center gap-2">
            <Building2 size={18} className="text-indigo-600" />
            Rendimiento por Sedes
          </h2>
          {data?.sedes?.length > 0 ? (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={data.sedes} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                  <XAxis dataKey="sede_nombre" tick={{ fontSize: 11 }} />
                  <YAxis tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Legend wrapperStyle={{ fontSize: '11px' }} />
                  <Bar
                    dataKey={periodo === 'todos' ? 'total_leads' : 'leads_periodo'}
                    name={periodo === 'todos' ? 'Total Leads' : 'Leads Período'}
                    fill="#6366F1"
                    radius={[4, 4, 0, 0]}
                  />
                  <Bar dataKey="matriculas" name="Matrículas" fill="#10B981" radius={[4, 4, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          ) : (
            <div className="h-64 flex items-center justify-center text-xs text-slate-400">
              Sin sedes configuradas o sin datos en el sistema.
            </div>
          )}
        </div>
      </div>

      {/* Tabla de Rendimiento por Asesor Individual */}
      <div className="bg-white rounded-2xl border border-slate-100 shadow-sm overflow-hidden">
        <div className="p-5 border-b border-slate-100 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <UserCheck size={18} className="text-indigo-600" />
            <h2 className="text-sm font-bold text-slate-800">Desempeño y Seguimientos por Asesor</h2>
          </div>
          <span className="text-xs text-slate-500 font-medium">
            {data?.asesores?.length || 0} asesores evaluados
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-slate-50 text-slate-500 font-semibold border-b border-slate-100">
              <tr>
                <th className="py-3 px-4">Asesor</th>
                <th className="py-3 px-3 text-center">Leads Período</th>
                <th className="py-3 px-3 text-center">SLA &le; 15m</th>
                <th className="py-3 px-3 text-center">En Seguimiento</th>
                <th className="py-3 px-3 text-center">Seg. Vencidos</th>
                <th className="py-3 px-3 text-center">Matrículas</th>
                <th className="py-3 px-3 text-center">Perdidos</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 text-slate-700 font-medium">
              {data?.asesores?.map(a => (
                <tr key={a.asesor_id} className="hover:bg-slate-50/70 transition-colors">
                  <td className="py-3 px-4">
                    <div className="font-bold text-slate-800">{a.asesor_nombre}</div>
                    <div className="text-[10px] text-slate-400">{a.asesor_email}</div>
                  </td>
                  <td className="py-3 px-3 text-center font-bold text-slate-800">
                    {a.leads_nuevos ?? 0}
                  </td>
                  <td className="py-3 px-3 text-center">
                    <span className={`px-2 py-0.5 rounded-full font-bold text-[11px] ${
                      (a.sla_cumplido_count ?? 0) > 0 ? 'bg-emerald-50 text-emerald-600' : 'bg-slate-100 text-slate-500'
                    }`}>
                      {a.sla_cumplido_count ?? 0}
                    </span>
                  </td>
                  <td className="py-3 px-3 text-center text-indigo-600 font-bold">
                    {a.seguimientos_hoy ?? 0}
                  </td>
                  <td className="py-3 px-3 text-center">
                    {a.seguimientos_vencidos > 0 ? (
                      <span className="px-2 py-0.5 bg-rose-50 text-rose-600 font-bold rounded-full">
                        {a.seguimientos_vencidos}
                      </span>
                    ) : (
                      <span className="text-slate-400">0</span>
                    )}
                  </td>
                  <td className="py-3 px-3 text-center font-bold text-emerald-600">
                    {a.matriculas ?? 0}
                  </td>
                  <td className="py-3 px-3 text-center text-slate-500">
                    {a.perdidos ?? 0}
                  </td>
                </tr>
              ))}
              {(!data?.asesores || data.asesores.length === 0) && (
                <tr>
                  <td colSpan={7} className="py-8 text-center text-slate-400">
                    No se encontraron asesores activos registrados en el sistema.
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
