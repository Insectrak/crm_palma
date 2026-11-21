import { useState, useEffect, useMemo, useCallback } from 'react'
import {
  X,
  Search,
  ExternalLink,
  Award,
  Phone,
  PhoneCall,
  UserCheck,
  Briefcase,
  AlertCircle,
  Clock,
  Users,
  Copy,
  Check,
  MessageCircle,
} from 'lucide-react'
import api from '@/lib/api'

function getMetricIcon(tipo) {
  switch ((tipo || '').toLowerCase()) {
    case 'matriculas':
    case 'matricula':
    case 'ganados':
    case 'ganado':
      return <Award size={20} className="text-emerald-600" />
    case 'perdidos':
    case 'perdido':
      return <AlertCircle size={20} className="text-red-500" />
    case 'contactados':
    case 'contactado':
      return <Phone size={20} className="text-blue-600" />
    case 'calificados':
    case 'calificado':
      return <UserCheck size={20} className="text-violet-600" />
    case 'negociacion':
    case 'en_negociacion':
      return <Briefcase size={20} className="text-pink-600" />
    case 'sin_contactar':
    case 'nuevos':
      return <Clock size={20} className="text-amber-600" />
    default:
      return <Users size={20} className="text-indigo-600" />
  }
}

function getAvatarColor(name = '') {
  const colors = [
    'bg-indigo-100 text-indigo-700',
    'bg-purple-100 text-purple-700',
    'bg-blue-100 text-blue-700',
    'bg-emerald-100 text-emerald-700',
    'bg-amber-100 text-amber-800',
    'bg-pink-100 text-pink-700',
    'bg-cyan-100 text-cyan-700',
  ]
  let sum = 0
  for (let i = 0; i < name.length; i++) sum += name.charCodeAt(i)
  return colors[sum % colors.length]
}

function formatFecha(iso) {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    if (isNaN(d.getTime())) return '—'
    const dd = String(d.getDate()).padStart(2, '0')
    const mm = String(d.getMonth() + 1).padStart(2, '0')
    const yy = String(d.getFullYear()).slice(-2)
    const hh = String(d.getHours()).padStart(2, '0')
    const mi = String(d.getMinutes()).padStart(2, '0')
    return `${dd}/${mm}/${yy} ${hh}:${mi}`
  } catch {
    return '—'
  }
}

function cleanPhoneForWa(phone) {
  if (!phone) return ''
  const digits = phone.replace(/\D/g, '')
  if (digits.length === 9) return `51${digits}`
  return digits
}

export default function LeadsDetalleModal({ open, onClose, context }) {
  const [leads, setLeads] = useState([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)
  const [searchInput, setSearchInput] = useState('')
  const [copiedPhones, setCopiedPhones] = useState(false)

  const {
    tipo_metrica = 'total',
    metricaLabel = 'Leads',
    asesor_id,
    asesor_nombre,
    supervisor_id,
    supervisor_nombre,
    fuente,
    fuente_excluida,
    campana,
    estado_id,
    fecha_desde,
    fecha_hasta,
  } = context || {}

  const fetchLeads = useCallback(async (searchQuery = '') => {
    if (!open) return
    setIsLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      params.set('tipo_metrica', tipo_metrica)
      if (fecha_desde) params.set('fecha_desde', fecha_desde)
      if (fecha_hasta) params.set('fecha_hasta', fecha_hasta)
      if (asesor_id) params.set('asesor_id', asesor_id)
      if (supervisor_id) params.set('supervisor_id', supervisor_id)
      if (fuente) params.set('fuente', fuente)
      if (fuente_excluida) params.set('fuente_excluida', fuente_excluida)
      if (campana) params.set('campana', campana)
      if (estado_id != null) params.set('estado_id', String(estado_id))
      if (searchQuery.trim()) params.set('search', searchQuery.trim())
      params.set('limit', '500')

      const res = await api.get(`/api/reportes/leads-detalle?${params.toString()}`)
      setLeads(res.data?.items || [])
      setTotal(res.data?.total || 0)
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al cargar el detalle de leads.')
    } finally {
      setIsLoading(false)
    }
  }, [open, tipo_metrica, fecha_desde, fecha_hasta, asesor_id, supervisor_id, fuente, fuente_excluida, campana, estado_id])

  useEffect(() => {
    if (open) {
      setSearchInput('')
      fetchLeads('')
    } else {
      setLeads([])
      setTotal(0)
    }
  }, [open, fetchLeads])

  // Debounced search
  useEffect(() => {
    if (!open) return
    const timer = setTimeout(() => {
      fetchLeads(searchInput)
    }, 350)
    return () => clearTimeout(timer)
  }, [searchInput, open, fetchLeads])

  // Escape key listener
  useEffect(() => {
    if (!open) return
    const handleKeyDown = (e) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [open, onClose])

  const copyAllPhones = () => {
    const phones = leads
      .map(l => l.telefono)
      .filter(Boolean)
      .join('\n')
    if (!phones) return
    navigator.clipboard.writeText(phones)
    setCopiedPhones(true)
    setTimeout(() => setCopiedPhones(false), 2000)
  }

  const modalTitle = useMemo(() => {
    const parts = [metricaLabel]
    if (asesor_nombre) parts.push(asesor_nombre)
    else if (supervisor_nombre) parts.push(`Equipo de ${supervisor_nombre}`)
    else if (fuente) parts.push(fuente)
    else if (campana) parts.push(campana)
    return parts.join(' — ')
  }, [metricaLabel, asesor_nombre, supervisor_nombre, fuente, campana])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 overflow-y-auto">
      {/* Backdrop */}
      <div
        className="fixed inset-0 bg-slate-900/60 backdrop-blur-sm transition-opacity animate-in fade-in duration-200"
        onClick={onClose}
      />

      {/* Modal Container */}
      <div className="relative bg-white rounded-2xl shadow-2xl border border-slate-200 w-full max-w-5xl max-h-[90vh] flex flex-col z-10 overflow-hidden animate-in fade-in zoom-in-95 duration-200">
        {/* Modal Header */}
        <div className="px-6 py-4 border-b border-slate-100 flex items-center justify-between bg-gradient-to-r from-slate-50 to-white">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-white shadow-sm border border-slate-200/80 flex items-center justify-center shrink-0">
              {getMetricIcon(tipo_metrica)}
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h2 className="text-lg font-bold text-slate-800 tracking-tight">
                  {modalTitle}
                </h2>
                <span className="px-2 py-0.5 rounded-full text-xs font-bold bg-indigo-50 text-indigo-700 border border-indigo-200">
                  {total} {total === 1 ? 'lead' : 'leads'}
                </span>
                {fuente && (
                  <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-blue-50 text-blue-700 border border-blue-200">
                    Fuente: {fuente}
                  </span>
                )}
                {fuente_excluida && (
                  <span className="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-rose-50 text-rose-700 border border-rose-200" title="Fuentes excluidas">
                    🚫 Sin: {fuente_excluida}
                  </span>
                )}
              </div>
              <p className="text-xs text-slate-500 mt-0.5">
                Período: <span className="font-medium text-slate-700">{fecha_desde}</span> al{' '}
                <span className="font-medium text-slate-700">{fecha_hasta}</span>
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {leads.length > 0 && (
              <button
                onClick={copyAllPhones}
                className="hidden sm:inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-slate-200 text-xs font-medium text-slate-600 hover:bg-slate-50 hover:text-slate-900 transition-colors cursor-pointer"
                title="Copiar números de teléfono de la lista"
              >
                {copiedPhones ? (
                  <>
                    <Check size={14} className="text-emerald-600" />
                    <span className="text-emerald-600 font-semibold">Copiados</span>
                  </>
                ) : (
                  <>
                    <Copy size={14} />
                    <span>Copiar Celulares</span>
                  </>
                )}
              </button>
            )}
            <button
              onClick={onClose}
              className="p-2 rounded-xl text-slate-400 hover:text-slate-700 hover:bg-slate-100 transition-colors cursor-pointer"
              title="Cerrar modal (Esc)"
            >
              <X size={20} />
            </button>
          </div>
        </div>

        {/* Toolbar & Search */}
        <div className="px-6 py-3 border-b border-slate-100 bg-slate-50/50 flex flex-col sm:flex-row items-center justify-between gap-3">
          <div className="relative w-full sm:w-80">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              placeholder="Buscar por nombre, celular o DNI..."
              className="w-full pl-9 pr-8 py-1.5 bg-white border border-slate-200 rounded-lg text-xs text-slate-800 placeholder-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all shadow-sm"
            />
            {searchInput && (
              <button
                onClick={() => setSearchInput('')}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 cursor-pointer"
              >
                <X size={13} />
              </button>
            )}
          </div>

          <div className="flex items-center gap-2 text-xs text-slate-500 w-full sm:w-auto justify-end">
            <span>Mostrando {leads.length} de {total} registros</span>
          </div>
        </div>

        {/* Modal Body / Table */}
        <div className="flex-1 overflow-y-auto min-h-[300px]">
          {isLoading && (
            <div className="flex flex-col items-center justify-center py-20 text-slate-400 gap-3">
              <div className="w-8 h-8 border-2 border-indigo-600 border-t-transparent rounded-full animate-spin" />
              <span className="text-xs font-medium text-slate-500">Cargando leads del reporte...</span>
            </div>
          )}

          {!isLoading && error && (
            <div className="p-8 text-center">
              <AlertCircle size={32} className="mx-auto text-red-500 mb-2" />
              <p className="text-sm font-semibold text-slate-800">Error al consultar leads</p>
              <p className="text-xs text-slate-500 mt-1">{error}</p>
            </div>
          )}

          {!isLoading && !error && leads.length === 0 && (
            <div className="py-20 text-center px-4">
              <div className="w-12 h-12 rounded-full bg-slate-100 text-slate-400 flex items-center justify-center mx-auto mb-3">
                <Search size={20} />
              </div>
              <p className="text-sm font-semibold text-slate-700">No se encontraron leads</p>
              <p className="text-xs text-slate-400 mt-1 max-w-sm mx-auto">
                No hay registros coincidentes con los filtros y fechas seleccionadas.
              </p>
            </div>
          )}

          {!isLoading && !error && leads.length > 0 && (
            <table className="w-full text-left text-xs">
              <thead className="sticky top-0 bg-slate-100/90 backdrop-blur-sm text-slate-600 font-semibold border-b border-slate-200 z-10">
                <tr>
                  <th className="py-2.5 px-4">Lead</th>
                  <th className="py-2.5 px-3">Contacto</th>
                  <th className="py-2.5 px-3">Estado</th>
                  <th className="py-2.5 px-3">Detalle Cierre / Motivo</th>
                  <th className="py-2.5 px-3">Fuente / Campaña</th>
                  <th className="py-2.5 px-3">Asesor</th>
                  <th className="py-2.5 px-3 text-center">Fecha Ingreso</th>
                  <th className="py-2.5 px-3 text-center">Acciones</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {leads.map((l) => {
                  const leadName = l.nombre_completo || 'Sin nombre'
                  const initials = leadName
                    .split(' ')
                    .filter(Boolean)
                    .slice(0, 2)
                    .map((n) => n[0])
                    .join('')
                    .toUpperCase()
                  const waNumber = cleanPhoneForWa(l.telefono)

                  return (
                    <tr key={l.id} className="hover:bg-indigo-50/40 transition-colors group">
                      {/* Lead Name */}
                      <td className="py-3 px-4">
                        <div className="flex items-center gap-2.5">
                          <div className={`w-8 h-8 rounded-full flex items-center justify-center font-bold text-xs shrink-0 ${getAvatarColor(leadName)}`}>
                            {initials || 'L'}
                          </div>
                          <div className="min-w-0">
                            <a
                              href={`/leads/${l.id}`}
                              target="_blank"
                              rel="noreferrer"
                              className="font-semibold text-slate-800 hover:text-indigo-600 transition-colors flex items-center gap-1 group-hover:underline"
                            >
                              <span className="truncate">{leadName}</span>
                            </a>
                            {l.dni && (
                              <span className="text-[10px] text-slate-400 block font-mono">DNI: {l.dni}</span>
                            )}
                          </div>
                        </div>
                      </td>

                      {/* Contacto & WhatsApp */}
                      <td className="py-3 px-3">
                        <div className="space-y-0.5">
                          {l.telefono ? (
                            <div className="flex items-center gap-1.5">
                              <span className="font-mono text-slate-700 font-medium">{l.telefono}</span>
                              {waNumber && (
                                <a
                                  href={`https://wa.me/${waNumber}`}
                                  target="_blank"
                                  rel="noreferrer"
                                  className="text-emerald-600 hover:text-emerald-700 hover:bg-emerald-50 p-1 rounded transition-colors"
                                  title="Enviar WhatsApp"
                                >
                                  <MessageCircle size={14} />
                                </a>
                              )}
                            </div>
                          ) : (
                            <span className="text-slate-300">—</span>
                          )}
                          {l.email && (
                            <span className="text-[11px] text-slate-400 block truncate max-w-[150px]" title={l.email}>
                              {l.email}
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Estado */}
                      <td className="py-3 px-3 whitespace-nowrap">
                        <span
                          className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] font-semibold border"
                          style={{
                            backgroundColor: (l.estado_color || '#6b7280') + '15',
                            color: l.estado_color || '#4b5563',
                            borderColor: (l.estado_color || '#6b7280') + '35',
                          }}
                        >
                          <span
                            className="w-1.5 h-1.5 rounded-full shrink-0"
                            style={{ backgroundColor: l.estado_color || '#6b7280' }}
                          />
                          {l.estado_nombre || 'Sin estado'}
                        </span>
                      </td>

                      {/* Detalle Cierre / Motivo */}
                      <td className="py-3 px-3">
                        {l.tipo_cierre ? (
                          <div className="space-y-0.5">
                            <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-50 text-emerald-700 border border-emerald-200">
                              {l.tipo_cierre}
                            </span>
                            {l.segunda_voz && (
                              <span className="text-[10px] text-slate-500 block">
                                2da voz: <strong className="text-slate-700">{l.segunda_voz}</strong>
                              </span>
                            )}
                          </div>
                        ) : l.motivo_perdida ? (
                          <div className="space-y-0.5">
                            <span className="inline-block px-1.5 py-0.5 rounded text-[10px] font-medium bg-red-50 text-red-700 border border-red-200">
                              {l.motivo_perdida}
                            </span>
                            {l.motivo_perdida_otro && (
                              <span className="text-[10px] text-slate-500 block truncate max-w-[140px]" title={l.motivo_perdida_otro}>
                                {l.motivo_perdida_otro}
                              </span>
                            )}
                          </div>
                        ) : (
                          <span className="text-slate-300">—</span>
                        )}
                      </td>

                      {/* Fuente & Campaña */}
                      <td className="py-3 px-3">
                        <div className="space-y-0.5">
                          <span className="font-medium text-slate-700 block">
                            {l.fuente_nombre || l.origen || 'Directo'}
                          </span>
                          {l.campana && (
                            <span className="text-[10px] text-slate-400 block truncate max-w-[140px]" title={l.campana}>
                              {l.campana}
                            </span>
                          )}
                        </div>
                      </td>

                      {/* Asesor */}
                      <td className="py-3 px-3 whitespace-nowrap">
                        <span className="font-medium text-slate-700">
                          {l.asesor_nombre || <span className="text-slate-400 italic">Sin asesor</span>}
                        </span>
                      </td>

                      {/* Fecha Ingreso */}
                      <td className="py-3 px-3 text-center whitespace-nowrap font-mono text-[11px] text-slate-500">
                        {formatFecha(l.fecha_ingreso)}
                      </td>

                      {/* Acciones */}
                      <td className="py-3 px-3 text-center">
                        <a
                          href={`/leads/${l.id}`}
                          target="_blank"
                          rel="noreferrer"
                          className="inline-flex items-center gap-1 px-2.5 py-1 rounded-lg border border-slate-200 text-slate-600 hover:text-indigo-600 hover:border-indigo-300 hover:bg-indigo-50/50 transition-all font-semibold text-[11px]"
                          title="Abrir detalle del lead en nueva pestaña"
                        >
                          <span>Ver</span>
                          <ExternalLink size={12} />
                        </a>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </div>

        {/* Modal Footer */}
        <div className="px-6 py-3 border-t border-slate-100 bg-slate-50 flex items-center justify-between text-xs text-slate-500">
          <span>Haga clic en <strong>Ver</strong> para acceder a la gestión completa del lead.</span>
          <button
            onClick={onClose}
            className="px-4 py-1.5 rounded-lg bg-white border border-slate-200 text-slate-700 font-semibold hover:bg-slate-100 transition-colors cursor-pointer"
          >
            Cerrar
          </button>
        </div>
      </div>
    </div>
  )
}
