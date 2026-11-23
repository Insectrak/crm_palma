import { useEffect, useState, useMemo, useCallback } from 'react'
import {
  History, Search, RefreshCw, User, Tag, ArrowRight, Clock,
  Shield, Bot, FileText, CheckCircle2, AlertCircle, Filter,
  Phone, Mail, MapPin, IdCard, Briefcase, Sparkles, SlidersHorizontal,
  Layers, Megaphone, Check, GitMerge, ShieldCheck, Calendar,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import LoadingSpinner from '@/components/shared/LoadingSpinner'
import LeadSummaryPopover from '@/components/leads/LeadSummaryPopover'
import api from '@/lib/api'

/**
 * Formatea fecha ISO a formato local de Perú.
 */
function formatDateTime(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('es-PE', {
    timeZone: 'America/Lima',
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/**
 * Calcula tiempo relativo legible en español.
 */
function formatRelativeTime(iso) {
  if (!iso) return ''
  const ms = new Date(iso).getTime()
  if (Number.isNaN(ms)) return ''
  const diffSec = Math.floor((Date.now() - ms) / 1000)
  if (diffSec < 60) return 'hace un momento'
  const diffMin = Math.floor(diffSec / 60)
  if (diffMin < 60) return `hace ${diffMin} ${diffMin === 1 ? 'minuto' : 'minutos'}`
  const diffHours = Math.floor(diffMin / 60)
  if (diffHours < 24) return `hace ${diffHours} ${diffHours === 1 ? 'hora' : 'horas'}`
  const diffDays = Math.floor(diffHours / 24)
  if (diffDays === 1) return 'ayer'
  if (diffDays < 30) return `hace ${diffDays} días`
  const diffMonths = Math.floor(diffDays / 30)
  if (diffMonths < 12) return `hace ${diffMonths} ${diffMonths === 1 ? 'mes' : 'meses'}`
  return `hace ${Math.floor(diffDays / 365)} años`
}

/**
 * Ícono y color representativo según el campo modificado.
 */
function getFieldIcon(campo) {
  const norm = String(campo || '').toLowerCase()
  if (norm.includes('fusion')) return { Icon: GitMerge, color: 'text-purple-600', bg: 'bg-purple-50 border-purple-200' }
  if (norm.includes('telefono')) return { Icon: Phone, color: 'text-indigo-600', bg: 'bg-indigo-50 border-indigo-200' }
  if (norm.includes('email')) return { Icon: Mail, color: 'text-sky-600', bg: 'bg-sky-50 border-sky-200' }
  if (norm.includes('nombre') || norm.includes('apellido')) return { Icon: User, color: 'text-violet-600', bg: 'bg-violet-50 border-violet-200' }
  if (norm.includes('dni') || norm.includes('documento')) return { Icon: IdCard, color: 'text-slate-700', bg: 'bg-slate-100 border-slate-200' }
  if (norm.includes('ciudad')) return { Icon: MapPin, color: 'text-emerald-600', bg: 'bg-emerald-50 border-emerald-200' }
  if (norm.includes('trabajo')) return { Icon: Briefcase, color: 'text-amber-700', bg: 'bg-amber-50 border-amber-200' }
  if (norm.includes('cita')) return { Icon: Calendar, color: 'text-indigo-600', bg: 'bg-indigo-50 border-indigo-200' }
  if (norm.includes('estado')) return { Icon: Tag, color: 'text-amber-600', bg: 'bg-amber-50 border-amber-200' }
  if (norm.includes('fuente')) return { Icon: Megaphone, color: 'text-teal-600', bg: 'bg-teal-50 border-teal-200' }
  if (norm.includes('asesor') || norm.includes('supervisor')) return { Icon: User, color: 'text-blue-600', bg: 'bg-blue-50 border-blue-200' }
  if (norm.includes('ficha_tecnica')) return { Icon: FileText, color: 'text-purple-600', bg: 'bg-purple-50 border-purple-200' }
  if (norm.includes('calidad')) return { Icon: Sparkles, color: 'text-orange-600', bg: 'bg-orange-50 border-orange-200' }
  return { Icon: FileText, color: 'text-gray-600', bg: 'bg-gray-50 border-gray-200' }
}

/**
 * Categoría para filtros rápidos.
 */
function getFieldCategory(campo) {
  const norm = String(campo || '').toLowerCase()
  if (norm.includes('fusion')) return 'fusion'
  if (norm.startsWith('ficha_tecnica')) return 'ficha_tecnica'
  if (['telefono', 'nombres', 'apellidos', 'email', 'dni', 'tipo_documento', 'ciudad', 'trabajo'].includes(norm)) {
    return 'contacto'
  }
  if (['estado_id', 'motivo_perdida', 'motivo_perdida_otro', 'tipo_cierre', 'segunda_voz', 'fecha_proxima_gestion', 'accion_proxima_gestion', 'cita_evento', 'cita_estado_id', 'fecha_cita', 'tipo_cita'].includes(norm)) {
    return 'estado'
  }
  if (['asesor_id', 'supervisor_id'].includes(norm)) {
    return 'asignacion'
  }
  if (['fuente_id', 'campana', 'calidad', 'sede_id', 'referido_por', 'codigo_convenio', 'observaciones'].includes(norm)) {
    return 'comercial'
  }
  return 'otros'
}

/**
 * Mapeo de etiqueta y estilo del origen del cambio.
 */
function getOrigenMeta(origen) {
  const norm = String(origen || '').toLowerCase()
  if (norm.includes('fusion')) {
    return { label: 'Fusión de leads', color: 'bg-purple-50 text-purple-700 border-purple-200' }
  }
  if (norm.includes('ficha_tecnica')) {
    return { label: 'Ficha técnica', color: 'bg-purple-50 text-purple-700 border-purple-200' }
  }
  if (norm.includes('cita')) {
    return { label: 'Agenda / Cita', color: 'bg-indigo-50 text-indigo-700 border-indigo-200' }
  }
  if (norm.includes('estado')) {
    return { label: 'Cambio de estado', color: 'bg-amber-50 text-amber-700 border-amber-200' }
  }
  if (norm.includes('reasignacion')) {
    return { label: 'Reasignación', color: 'bg-blue-50 text-blue-700 border-blue-200' }
  }
  if (norm.includes('fuente')) {
    return { label: 'Cambio de fuente', color: 'bg-teal-50 text-teal-700 border-teal-200' }
  }
  if (norm.includes('masivo')) {
    return { label: 'Acción masiva', color: 'bg-indigo-50 text-indigo-700 border-indigo-200' }
  }
  if (norm.includes('sistema')) {
    return { label: 'Sistema / Automático', color: 'bg-slate-100 text-slate-700 border-slate-200' }
  }
  return { label: 'Edición de ficha', color: 'bg-gray-100 text-gray-700 border-gray-200' }
}

export default function LeadHistorialCambios({ leadId, onCountUpdate }) {
  const [items, setItems] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [isRefreshing, setIsRefreshing] = useState(false)
  const [error, setError] = useState(null)
  const [searchTerm, setSearchTerm] = useState('')
  const [selectedCategory, setSelectedCategory] = useState('todos')

  const fetchHistory = useCallback(async (isRefresh = false) => {
    if (!leadId) return
    if (isRefresh) setIsRefreshing(true)
    else setIsLoading(true)
    setError(null)

    try {
      const res = await api.get(`/api/leads/${leadId}/historial-cambios?limit=300`)
      const fetchedItems = res.data?.items || []
      setItems(fetchedItems)
      if (onCountUpdate) {
        onCountUpdate(fetchedItems.length)
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo cargar el historial de cambios.')
    } finally {
      setIsLoading(false)
      setIsRefreshing(false)
    }
  }, [leadId, onCountUpdate])

  useEffect(() => {
    fetchHistory()
  }, [fetchHistory])

  // Filtrado reactivo en cliente (búsqueda + categoría)
  const filteredItems = useMemo(() => {
    return items.filter((item) => {
      // Filtro por categoría
      if (selectedCategory !== 'todos') {
        const cat = getFieldCategory(item.campo)
        if (cat !== selectedCategory) return false
      }

      // Filtro por término de búsqueda
      if (!searchTerm.trim()) return true
      const term = searchTerm.toLowerCase().trim()
      const matchLabel = String(item.campo_label || '').toLowerCase().includes(term)
      const matchCampo = String(item.campo || '').toLowerCase().includes(term)
      const matchUser = String(item.usuario_nombre || '').toLowerCase().includes(term)
      const matchOld = String(item.valor_anterior || '').toLowerCase().includes(term)
      const matchNew = String(item.valor_nuevo || '').toLowerCase().includes(term)
      const matchOrigen = String(item.origen || '').toLowerCase().includes(term)

      return matchLabel || matchCampo || matchUser || matchOld || matchNew || matchOrigen
    })
  }, [items, selectedCategory, searchTerm])

  // Conteo por categoría para los badges
  const categoryCounts = useMemo(() => {
    const counts = {
      todos: items.length,
      contacto: 0,
      estado: 0,
      asignacion: 0,
      comercial: 0,
      ficha_tecnica: 0,
      fusion: 0,
    }
    items.forEach((it) => {
      const cat = getFieldCategory(it.campo)
      if (counts[cat] !== undefined) {
        counts[cat] += 1
      }
    })
    return counts
  }, [items])

  if (isLoading) {
    return (
      <Card className="border-gray-200 shadow-xs">
        <CardContent className="p-8 flex flex-col items-center justify-center min-h-[300px]">
          <LoadingSpinner />
          <p className="text-sm text-gray-500 mt-3 font-medium">Cargando historial de cambios del lead...</p>
        </CardContent>
      </Card>
    )
  }

  if (error) {
    return (
      <Card className="border-red-200 bg-red-50/40">
        <CardContent className="p-8 text-center">
          <AlertCircle size={36} className="text-red-500 mx-auto mb-2" />
          <p className="text-sm font-semibold text-red-800">{error}</p>
          <Button
            variant="outline"
            size="sm"
            onClick={() => fetchHistory()}
            className="mt-4 gap-1.5 border-red-300 text-red-700 hover:bg-red-100"
          >
            <RefreshCw size={13} /> Reintentar
          </Button>
        </CardContent>
      </Card>
    )
  }

  return (
    <div className="space-y-4">
      {/* Barra de cabecera del historial */}
      <Card className="border-gray-200/80 shadow-xs bg-white dark:bg-slate-900">
        <CardHeader className="pb-3 pt-4 px-4 sm:px-6 border-b border-gray-100 dark:border-slate-800">
          <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
            <div className="flex items-center gap-2.5">
              <div className="w-8 h-8 rounded-lg bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400 flex items-center justify-center shrink-0 border border-indigo-100 dark:border-indigo-900/60">
                <History size={16} />
              </div>
              <div>
                <CardTitle className="text-base font-bold text-gray-900 dark:text-slate-100 flex items-center gap-2">
                  Historial de Cambios
                  <span className="inline-flex items-center text-xs font-semibold px-2 py-0.5 rounded-full bg-indigo-100 dark:bg-indigo-900/70 text-indigo-700 dark:text-indigo-300 border border-indigo-200 dark:border-indigo-800">
                    {items.length} {items.length === 1 ? 'registro' : 'registros'}
                  </span>
                </CardTitle>
                <p className="text-xs text-gray-500 dark:text-slate-400 mt-0.5">
                  Registro de auditoría detallado de todos los datos modificados en este lead.
                </p>
              </div>
            </div>

            <Button
              variant="outline"
              size="sm"
              onClick={() => fetchHistory(true)}
              disabled={isRefreshing}
              className="gap-1.5 text-xs h-8 border-gray-200 hover:bg-gray-50 dark:border-slate-700 dark:hover:bg-slate-800 shrink-0"
              title="Actualizar historial de cambios"
            >
              <RefreshCw size={12} className={isRefreshing ? 'animate-spin text-indigo-600' : ''} />
              {isRefreshing ? 'Actualizando…' : 'Actualizar'}
            </Button>
          </div>

          {/* Filtros rápidos por categoría */}
          <div className="flex items-center gap-1.5 overflow-x-auto pt-3 pb-1 no-scrollbar text-xs">
            <button
              onClick={() => setSelectedCategory('todos')}
              className={`px-2.5 py-1 rounded-full font-medium transition-all shrink-0 border ${
                selectedCategory === 'todos'
                  ? 'bg-indigo-600 text-white border-indigo-600 shadow-2xs'
                  : 'bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700'
              }`}
            >
              Todos ({categoryCounts.todos})
            </button>
            <button
              onClick={() => setSelectedCategory('contacto')}
              className={`px-2.5 py-1 rounded-full font-medium transition-all shrink-0 border ${
                selectedCategory === 'contacto'
                  ? 'bg-indigo-600 text-white border-indigo-600 shadow-2xs'
                  : 'bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700'
              }`}
            >
              Contacto ({categoryCounts.contacto})
            </button>
            <button
              onClick={() => setSelectedCategory('estado')}
              className={`px-2.5 py-1 rounded-full font-medium transition-all shrink-0 border ${
                selectedCategory === 'estado'
                  ? 'bg-indigo-600 text-white border-indigo-600 shadow-2xs'
                  : 'bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700'
              }`}
            >
              Estado & Pipeline ({categoryCounts.estado})
            </button>
            <button
              onClick={() => setSelectedCategory('asignacion')}
              className={`px-2.5 py-1 rounded-full font-medium transition-all shrink-0 border ${
                selectedCategory === 'asignacion'
                  ? 'bg-indigo-600 text-white border-indigo-600 shadow-2xs'
                  : 'bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700'
              }`}
            >
              Asignación ({categoryCounts.asignacion})
            </button>
            <button
              onClick={() => setSelectedCategory('comercial')}
              className={`px-2.5 py-1 rounded-full font-medium transition-all shrink-0 border ${
                selectedCategory === 'comercial'
                  ? 'bg-indigo-600 text-white border-indigo-600 shadow-2xs'
                  : 'bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700'
              }`}
            >
              Comercial & Fuente ({categoryCounts.comercial})
            </button>
            {categoryCounts.ficha_tecnica > 0 && (
              <button
                onClick={() => setSelectedCategory('ficha_tecnica')}
                className={`px-2.5 py-1 rounded-full font-medium transition-all shrink-0 border ${
                  selectedCategory === 'ficha_tecnica'
                    ? 'bg-indigo-600 text-white border-indigo-600 shadow-2xs'
                    : 'bg-gray-50 text-gray-600 border-gray-200 hover:bg-gray-100 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700'
                }`}
              >
                Ficha Técnica ({categoryCounts.ficha_tecnica})
              </button>
            )}
            {categoryCounts.fusion > 0 && (
              <button
                onClick={() => setSelectedCategory('fusion')}
                className={`px-2.5 py-1 rounded-full font-medium transition-all shrink-0 border ${
                  selectedCategory === 'fusion'
                    ? 'bg-purple-600 text-white border-purple-600 shadow-2xs'
                    : 'bg-purple-50 text-purple-700 border-purple-200 hover:bg-purple-100 dark:bg-purple-950/60 dark:text-purple-300 dark:border-purple-800'
                }`}
              >
                Fusiones ({categoryCounts.fusion})
              </button>
            )}
          </div>
        </CardHeader>

        {/* Buscador interno */}
        <div className="p-3 sm:px-6 bg-gray-50/70 dark:bg-slate-800/40 border-b border-gray-100 dark:border-slate-800">
          <div className="relative">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
            <Input
              type="text"
              placeholder="Buscar por campo (ej: teléfono, estado, fuente) o usuario..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="pl-9 h-8.5 text-xs bg-white dark:bg-slate-900 border-gray-200 dark:border-slate-700 rounded-lg"
            />
            {searchTerm && (
              <button
                onClick={() => setSearchTerm('')}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 text-xs px-1"
              >
                ✕
              </button>
            )}
          </div>
        </div>

        {/* Lista de cambios */}
        <CardContent className="p-4 sm:p-6">
          {filteredItems.length === 0 ? (
            <div className="text-center py-12">
              <History size={36} className="text-gray-300 dark:text-slate-600 mx-auto mb-2.5" />
              <h3 className="text-sm font-semibold text-gray-700 dark:text-slate-300">
                {items.length === 0
                  ? 'No hay cambios registrados en este lead aún'
                  : 'No se encontraron cambios con los filtros aplicados'}
              </h3>
              <p className="text-xs text-gray-400 dark:text-slate-500 mt-1 max-w-sm mx-auto">
                {items.length === 0
                  ? 'Cualquier modificación futura de teléfono, nombres, fuente, estado o ficha técnica quedará registrada aquí automáticamente.'
                  : 'Intenta limpiar el buscador o seleccionar otra categoría.'}
              </p>
              {searchTerm && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => { setSearchTerm(''); setSelectedCategory('todos') }}
                  className="mt-3 text-xs h-7"
                >
                  Restablecer filtros
                </Button>
              )}
            </div>
          ) : (
            <div className="space-y-3">
              {filteredItems.map((change) => {
                const { Icon, color, bg } = getFieldIcon(change.campo)
                const origenMeta = getOrigenMeta(change.origen)
                const isSystem = !change.usuario_id || (change.usuario_rol && change.usuario_rol.toLowerCase() === 'sistema') || (change.usuario_nombre && change.usuario_nombre.toLowerCase() === 'sistema')

                return (
                  <div
                    key={change.id}
                    className="group border border-gray-200/80 dark:border-slate-800 rounded-xl p-3.5 bg-white dark:bg-slate-900/90 hover:border-indigo-300 dark:hover:border-indigo-700/60 transition-all shadow-2xs hover:shadow-xs"
                  >
                    {/* Fila superior: Ícono + Campo + Origen + Fecha */}
                    <div className="flex items-start justify-between gap-3 mb-2 flex-wrap">
                      <div className="flex items-center gap-2.5 min-w-0">
                        <div className={`w-7 h-7 rounded-lg border flex items-center justify-center shrink-0 ${bg}`}>
                          <Icon size={14} className={color} />
                        </div>
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="text-xs font-bold text-gray-900 dark:text-slate-100 truncate">
                              {change.campo_label || change.campo}
                            </span>
                            <span className={`inline-flex items-center px-2 py-0.5 text-[10px] font-semibold rounded-full border ${origenMeta.color}`}>
                              {origenMeta.label}
                            </span>
                          </div>
                        </div>
                      </div>

                      {/* Timestamp y relativo */}
                      <div className="text-right shrink-0">
                        <span className="text-xs font-medium text-gray-600 dark:text-slate-300 flex items-center justify-end gap-1">
                          <Clock size={11} className="text-gray-400" />
                          {formatDateTime(change.created_at)}
                        </span>
                        <span className="text-[11px] text-gray-400 dark:text-slate-500 block">
                          {formatRelativeTime(change.created_at)}
                        </span>
                      </div>
                    </div>

                    {/* Si es un evento de fusión de leads */}
                    {change.origen === 'fusion' || change.campo === 'fusion_leads' ? (
                      <div className="mt-2.5 p-3 rounded-xl bg-gradient-to-r from-purple-50/70 via-indigo-50/50 to-purple-50/40 dark:from-purple-950/40 dark:via-indigo-950/30 dark:to-purple-950/20 border border-purple-200 dark:border-purple-800/60 space-y-2.5 text-xs">
                        <div className="grid grid-cols-1 md:grid-cols-2 gap-2.5">
                          {/* Lead Principal */}
                          <div className="p-2.5 rounded-lg bg-white/95 dark:bg-slate-900/90 border border-purple-100 dark:border-purple-900/50 shadow-2xs">
                            <span className="text-[10px] font-bold uppercase tracking-wider text-purple-700 dark:text-purple-300 block mb-1">
                              Lead Principal {change.datos_extra?.master_lead?.id ? `· ID #${change.datos_extra.master_lead.id}` : ''}
                            </span>
                            <div className="flex items-center justify-between gap-2">
                              <LeadSummaryPopover
                                lead={change.datos_extra?.master_lead}
                                titlePrefix="Lead Principal"
                              >
                                <span className="font-bold text-gray-900 dark:text-slate-100 hover:text-purple-700 dark:hover:text-purple-300 underline decoration-dotted decoration-purple-400 cursor-help transition-colors">
                                  {change.datos_extra?.master_lead?.nombre || 'Lead Principal'}
                                </span>
                              </LeadSummaryPopover>
                              <span className="text-[11px] text-gray-500 dark:text-slate-400 truncate max-w-[130px]">
                                {change.datos_extra?.master_lead?.asesor_nombre ? `Dueño: ${change.datos_extra.master_lead.asesor_nombre}` : ''}
                              </span>
                            </div>
                            <p className="text-[10px] text-gray-400 dark:text-slate-500 mt-1">
                              Pasa el cursor sobre el nombre para ver su resumen previo
                            </p>
                          </div>

                          {/* Lead Fusionado */}
                          <div className="p-2.5 rounded-lg bg-white/95 dark:bg-slate-900/90 border border-indigo-100 dark:border-indigo-900/50 shadow-2xs">
                            <span className="text-[10px] font-bold uppercase tracking-wider text-indigo-700 dark:text-indigo-300 block mb-1">
                              Lead Fusionado {change.datos_extra?.secondary_lead?.id ? `· ID #${change.datos_extra.secondary_lead.id}` : ''}
                            </span>
                            <div className="flex items-center justify-between gap-2">
                              <LeadSummaryPopover
                                lead={change.datos_extra?.secondary_lead}
                                titlePrefix="Lead Fusionado"
                              >
                                <span className="font-bold text-gray-900 dark:text-slate-100 hover:text-indigo-700 dark:hover:text-indigo-300 underline decoration-dotted decoration-indigo-400 cursor-help transition-colors">
                                  {change.datos_extra?.secondary_lead?.nombre || 'Lead Fusionado'}
                                </span>
                              </LeadSummaryPopover>
                              <span className="text-[11px] text-gray-500 dark:text-slate-400 truncate max-w-[130px]">
                                {change.datos_extra?.secondary_lead?.asesor_nombre ? `Dueño: ${change.datos_extra.secondary_lead.asesor_nombre}` : ''}
                              </span>
                            </div>
                            <p className="text-[10px] text-gray-400 dark:text-slate-500 mt-1">
                              Pasa el cursor sobre el nombre para ver su resumen previo
                            </p>
                          </div>
                        </div>

                        {/* Metadatos de autoridad y conteos */}
                        <div className="flex flex-wrap items-center justify-between gap-2 pt-1 border-t border-purple-200/60 dark:border-purple-800/60 text-[11px]">
                          <span className="font-medium text-purple-900 dark:text-purple-200 flex items-center gap-1.5">
                            <ShieldCheck size={13} className="text-purple-600 dark:text-purple-400" />
                            Dueño con autoridad elegido:{' '}
                            <strong className="text-purple-950 dark:text-purple-100 font-bold">
                              {change.datos_extra?.chosen_owner_name || '—'}
                            </strong>
                          </span>
                          {(change.datos_extra?.contactos_migrated > 0 || change.datos_extra?.llamadas_migrated > 0) && (
                            <span className="text-emerald-700 dark:text-emerald-400 font-medium">
                              ✓ {change.datos_extra.contactos_migrated || 0} interacciones y {change.datos_extra.llamadas_migrated || 0} llamadas unificadas
                            </span>
                          )}
                        </div>
                      </div>
                    ) : (
                      /* Comparativa normal: Antes vs Después */
                      <div className="mt-2.5 grid grid-cols-1 md:grid-cols-2 gap-2 bg-gray-50/70 dark:bg-slate-800/40 p-2.5 rounded-lg border border-gray-100 dark:border-slate-800/70 text-xs">
                        {/* Valor anterior */}
                        <div className="flex items-start gap-2 min-w-0">
                          <span className="text-[10px] font-bold uppercase tracking-wider text-rose-600 dark:text-rose-400 shrink-0 pt-0.5">
                            Antes:
                          </span>
                          <div className="text-gray-600 dark:text-slate-400 line-through break-words font-mono text-[11px] bg-rose-50/80 dark:bg-rose-950/40 border border-rose-200/60 dark:border-rose-900/40 rounded px-2 py-1 flex-1">
                            {change.valor_anterior || '— (Vacío)'}
                          </div>
                        </div>

                        {/* Valor nuevo */}
                        <div className="flex items-start gap-2 min-w-0">
                          <span className="text-[10px] font-bold uppercase tracking-wider text-emerald-600 dark:text-emerald-400 shrink-0 pt-0.5 flex items-center gap-0.5">
                            <ArrowRight size={10} className="hidden md:inline mr-0.5 text-gray-400" />
                            Nuevo:
                          </span>
                          <div className="text-emerald-950 dark:text-emerald-100 font-semibold break-words font-mono text-[11px] bg-emerald-50/90 dark:bg-emerald-950/50 border border-emerald-200/80 dark:border-emerald-800/60 rounded px-2 py-1 flex-1 shadow-2xs">
                            {change.valor_nuevo || '— (Eliminado)'}
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Fila inferior: Actor del cambio */}
                    <div className="mt-2.5 pt-2 border-t border-gray-100 dark:border-slate-800/60 flex items-center justify-between text-xs text-gray-500 dark:text-slate-400">
                      <div className="flex items-center gap-1.5">
                        <div className="w-5 h-5 rounded-full bg-gray-100 dark:bg-slate-800 flex items-center justify-center text-gray-600 dark:text-slate-300 shrink-0 text-[10px] font-bold">
                          {isSystem ? <Bot size={11} className="text-purple-600" /> : <User size={11} />}
                        </div>
                        <span className="font-medium text-gray-800 dark:text-slate-200">
                          {change.usuario_nombre || 'Sistema'}
                        </span>
                        {change.usuario_rol && (
                          <span className="text-[10px] text-gray-400 uppercase tracking-wider font-semibold px-1.5 py-0.2 bg-gray-100 dark:bg-slate-800 rounded">
                            {change.usuario_rol}
                          </span>
                        )}
                      </div>

                      <span className="text-[10px] text-gray-400 font-mono">
                        ID #{change.id}
                      </span>
                    </div>
                  </div>
                )
              })}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

