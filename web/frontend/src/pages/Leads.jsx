import { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { Plus, Search, Filter, Download, X, ChevronDown, Eye, ChevronLeft, ChevronRight, UserPlus, List, Plug, Archive, MapPin, RotateCcw, Clock, AlertCircle, UserCheck, Calendar, Sparkles, Shield, ClipboardList, CheckCircle2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Card } from '@/components/ui/card'
import DataTable from '@/components/shared/DataTable'
import ConfirmDialog from '@/components/shared/ConfirmDialog'
import InfoDialog from '@/components/shared/InfoDialog'
import EstadoPills from '@/components/leads/EstadoPills'
import RecontactosBanner from '@/components/leads/RecontactosBanner'
import FilterPanel from '@/components/leads/FilterPanel'
import AdvancedFilters from '@/components/leads/AdvancedFilters'
import SortMenu from '@/components/leads/SortMenu'
import BulkReassignBar from '@/components/leads/BulkReassignBar'
import ViewsBar from '@/components/shared/views/ViewsBar'
import SaveViewModal from '@/components/shared/views/SaveViewModal'
import CambioEstadoModal, { requiresFormularioEspecifico, normalizeEstadoNombre, getSubestadosForEstado } from '@/components/leads/CambioEstadoModal'
import useSavedViews from '@/hooks/useSavedViews'
import useCopyProtection from '@/hooks/useCopyProtection'
import useAuthStore from '@/store/authStore'
import useCrmStore from '@/store/crmStore'
import api from '@/lib/api'
import { buildTeamGroups, flattenGroups } from '@/lib/teamGroups'
import { fireAssignmentChanged } from '@/lib/events'
import { hasPermission } from '@/lib/permissions'
import { getTodayDateString } from '@/lib/utils'
import { getFichaTecnicaStats } from '@/lib/fichaTecnica'

const PAGE_SIZE = 50

function formatDateParts(iso) {
  if (!iso) return null
  const d = new Date(iso)
  const dd = String(d.getDate()).padStart(2, '0')
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const yy = String(d.getFullYear()).slice(-2)
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return { date: `${dd}/${mm}/${yy}`, time: `${hh}:${mi}` }
}

function DateCell({ iso }) {
  const parts = formatDateParts(iso)
  if (!parts) return <span className="text-gray-400">—</span>
  return (
    <span className="text-xs text-gray-600 whitespace-nowrap">
      {parts.date} <span className="text-gray-400">{parts.time}</span>
    </span>
  )
}

/** Badge de estado con dropdown para cambio rápido */
/**
 * V050: Dropdown inline para cambiar la calidad del lead (frio/tibio/caliente)
 * sin entrar al detalle. Estilo igual a EstadoDropdown para consistencia.
 *
 * El backend espera el codigo en mayusculas (FRIO|TIBIO|CALIENTE) o null
 * para "sin clasificar". El catalogo viene del store.
 */
function CalidadDropdown({ lead, calidades, onChangeCalidad }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const codigoActual = (lead.calidad_codigo || '').toUpperCase()
  const calidad = calidades.find(c => (c.codigo || '').toUpperCase() === codigoActual)

  useEffect(() => {
    if (!open) return
    const handleClick = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  const color = calidad?.color_hex || '#9ca3af'   // gris para sin clasificar
  const nombre = calidad?.nombre || 'Sin clasificar'

  return (
    <div ref={ref} className="relative inline-block">
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(!open) }}
        className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold border hover:opacity-80 transition-opacity cursor-pointer"
        style={{
          backgroundColor: color + '20',
          color,
          borderColor: color + '40',
        }}
        title="Cambiar calidad del lead"
      >
        {nombre}
        <ChevronDown size={9} />
      </button>
      {open && (
        <div className="absolute z-30 top-full left-0 mt-1 bg-white border border-gray-200 rounded-xl shadow-xl py-1.5 min-w-[160px]">
          <button
            onClick={(ev) => { ev.stopPropagation(); onChangeCalidad(lead.id, null); setOpen(false) }}
            className={`w-full text-left px-3 py-2 text-xs hover:bg-gray-50 flex items-center gap-2 transition-colors ${!codigoActual ? 'font-semibold bg-gray-50' : ''
              }`}
          >
            <span className="w-2 h-2 rounded-full shrink-0 bg-gray-400" />
            Sin clasificar
          </button>
          {calidades.map(c => (
            <button
              key={c.codigo || c.id}
              onClick={(ev) => { ev.stopPropagation(); onChangeCalidad(lead.id, c.codigo); setOpen(false) }}
              className={`w-full text-left px-3 py-2 text-xs hover:bg-gray-50 flex items-center gap-2 transition-colors ${(c.codigo || '').toUpperCase() === codigoActual ? 'font-semibold bg-gray-50' : ''
                }`}
            >
              <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: c.color_hex }} />
              {c.nombre}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/**
 * SedeDropdown — V065: dropdown inline para asignar/cambiar la sede del
 * lead desde la tabla. Mismo patron visual que CalidadDropdown.
 *
 * Si no hay sedes en el catalogo (single-sede), no se monta — el caller
 * (Leads.jsx) condiciona el render.
 */
function SedeDropdown({ lead, sedes, onChangeSede }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const sedeActualId = lead.sede_id || null
  const sedeActual = sedes.find(s => String(s.id) === String(sedeActualId))

  useEffect(() => {
    if (!open) return
    const handleClick = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  const color = sedeActual?.color_hex || lead.sede_color || '#9ca3af'
  const nombre = sedeActual?.nombre || lead.sede_nombre || 'Sin sede'

  return (
    <div ref={ref} className="relative inline-block">
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(!open) }}
        className="inline-flex items-center gap-1 rounded px-2 py-0.5 text-xs font-medium border hover:opacity-80 transition-opacity cursor-pointer max-w-[140px]"
        style={{
          backgroundColor: color + (sedeActualId ? '14' : '10'),
          color: sedeActualId ? color : '#6b7280',
          borderColor: color + '40',
        }}
        title="Cambiar sede del lead"
      >
        <MapPin size={10} className="shrink-0" />
        <span className="truncate">{nombre}</span>
        <ChevronDown size={9} className="shrink-0" />
      </button>
      {open && (
        <div className="absolute z-30 top-full left-0 mt-1 bg-white border border-gray-200 rounded-xl shadow-xl py-1.5 min-w-[200px] max-h-[280px] overflow-y-auto">
          <button
            onClick={(ev) => { ev.stopPropagation(); onChangeSede(lead.id, null); setOpen(false) }}
            className={`w-full text-left px-3 py-2 text-xs hover:bg-gray-50 flex items-center gap-2 transition-colors ${!sedeActualId ? 'font-semibold bg-gray-50' : ''
              }`}
          >
            <span className="w-2 h-2 rounded-full shrink-0 bg-gray-400" />
            Sin sede
          </button>
          {sedes.map(s => (
            <button
              key={s.id}
              onClick={(ev) => { ev.stopPropagation(); onChangeSede(lead.id, s.id); setOpen(false) }}
              className={`w-full text-left px-3 py-2 text-xs hover:bg-gray-50 flex items-center gap-2 transition-colors ${String(s.id) === String(sedeActualId) ? 'font-semibold bg-gray-50' : ''
                }`}
            >
              <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: s.color_hex || '#9ca3af' }} />
              <span className="truncate">{s.nombre}</span>
              {s.ciudad && <span className="text-[10px] text-gray-400 ml-auto truncate">{s.ciudad}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}


const SUBESTADO_MAP = {
  'Precio / falta de capacidad económica': 'Precio / Capacidad',
  'Horarios / no se ajusta a sus tiempos': 'Horarios',
  'Prefiere a la competencia': 'Competencia',
  'Postergación indefinida': 'Postergación',
  'No se ajusta a la metodología': 'Metodología',
  'Pérdida temporal': 'Pérdida temporal',
  'Oportunidad futura': 'Oportunidad futura',
  'Llamar para coordinar visita / cierre': 'Llamar (cierre)',
  'Llamar para coordinar matrícula / inicio': 'Llamar (cierre)',
  'Contactar por WhatsApp con promoción / bono': 'WhatsApp (promo)',
  'Contactar por WhatsApp con promoción / descuento': 'WhatsApp (promo)',
  'Volver a contactar en nueva etapa / lanzamiento': 'Recontactar etapa',
  'Volver a contactar en nueva convocatoria / fecha': 'Recontactar fecha',
  'Reevaluar interés y capacidad de financiamiento': 'Reevaluar interés',
  'Reevaluar interés y disponibilidad económica': 'Reevaluar interés',
  'Enviar información actualizada / catálogo': 'Enviar catálogo',
  'No califica para financiamiento / crédito': 'Sin financiamiento',
  'Ubicación / proyecto no se ajusta': 'Ubicación / Proyecto',
}

function formatSubestadoText(text, maxChars = 20) {
  if (!text) return ''
  const trimmed = text.trim()
  if (SUBESTADO_MAP[trimmed]) return SUBESTADO_MAP[trimmed]
  if (trimmed.length > maxChars) {
    return trimmed.slice(0, maxChars - 1).trim() + '…'
  }
  return trimmed
}

export function EstadoSubinfo({ lead, estadoNombre }) {
  if (!lead) return null

  const adminBadge = lead.gestion_especial_admin ? (
    <div className="mt-1 max-w-[130px] min-w-0 overflow-hidden">
      <span
        className="inline-flex items-center gap-1 text-[9px] font-semibold text-amber-800 dark:text-amber-300 bg-amber-50 dark:bg-amber-950/50 border border-amber-300 dark:border-amber-700/60 rounded px-1.5 py-0.5 max-w-[130px] min-w-0 overflow-hidden"
        title="Gestión especial por Administración (cambio automático apagado)"
      >
        <Shield size={9} className="shrink-0 text-amber-600" />
        <span className="truncate min-w-0">Admin Especial</span>
      </span>
    </div>
  ) : null

  const renderContent = () => {
    const norm = normalizeEstadoNombre(estadoNombre || lead.estado_nombre || '')

  // 1. Oportunidad Futura
  if (norm.includes('oportunidad') || (norm.includes('futur') && !norm.includes('pasad'))) {
    const hasAccion = !!lead.accion_proxima_gestion
    const parts = formatDateParts(lead.fecha_proxima_gestion)
    if (!hasAccion && !parts) return null
    return (
      <div className="flex flex-col gap-0.5 mt-1 max-w-[130px] min-w-0 overflow-hidden">
        {hasAccion && (
          <span
            className="inline-flex items-center gap-1 text-[10px] text-purple-700 dark:text-purple-300 font-medium bg-purple-50 dark:bg-purple-950/40 border border-purple-200/80 dark:border-purple-800/50 rounded px-1.5 py-0.5 max-w-[130px] min-w-0 overflow-hidden"
            title={`Acción: ${lead.accion_proxima_gestion}`}
          >
            <Sparkles size={10} className="shrink-0 text-purple-500" />
            <span className="truncate min-w-0">{formatSubestadoText(lead.accion_proxima_gestion, 18)}</span>
          </span>
        )}
        {parts && (
          <span
            className="inline-flex items-center gap-1 text-[10px] text-purple-700 dark:text-purple-300 font-normal px-0.5 max-w-[130px] truncate"
            title={`Fecha de acción: ${parts.date} ${parts.time}`}
          >
            <Calendar size={9} className="shrink-0 text-purple-500" />
            <span className="truncate">{parts.date} {parts.time}</span>
          </span>
        )}
      </div>
    )
  }

  // 2. Perdido / No interesado / Desistió
  if (norm.includes('perdid') || norm.includes('no interesado') || norm.includes('desist') || norm.includes('descart')) {
    const motivo = lead.motivo_perdida
    if (!motivo) return null
    const detalle = (motivo === 'Otro' && lead.motivo_perdida_otro)
      ? lead.motivo_perdida_otro
      : motivo
    return (
      <div className="mt-1 max-w-[130px] min-w-0 overflow-hidden">
        <span
          className="inline-flex items-center gap-1 text-[10px] text-rose-700 dark:text-rose-300 font-medium bg-rose-50 dark:bg-rose-950/40 border border-rose-200/80 dark:border-rose-800/50 rounded px-1.5 py-0.5 max-w-[130px] min-w-0 overflow-hidden"
          title={`Motivo: ${detalle}`}
        >
          <AlertCircle size={10} className="shrink-0 text-rose-500" />
          <span className="truncate min-w-0">{formatSubestadoText(detalle, 18)}</span>
        </span>
      </div>
    )
  }

  // 3. Venta / Ganado / Cierre
  if (norm.includes('matr') || norm.includes('ganad') || norm.includes('cierr') || norm.includes('venta concretad')) {
    const tipo = lead.tipo_cierre
    const segVoz = lead.segunda_voz
    if (!tipo && !segVoz) return null
    const texto = (tipo === 'Con segunda voz' && segVoz)
      ? `2da voz: ${segVoz}`
      : (tipo || segVoz)
    return (
      <div className="mt-1 max-w-[130px] min-w-0 overflow-hidden">
        <span
          className="inline-flex items-center gap-1 text-[10px] text-emerald-700 dark:text-emerald-300 font-medium bg-emerald-50 dark:bg-emerald-950/40 border border-emerald-200/80 dark:border-emerald-800/50 rounded px-1.5 py-0.5 max-w-[130px] min-w-0 overflow-hidden"
          title={`Cierre: ${texto}`}
        >
          <UserCheck size={10} className="shrink-0 text-emerald-600" />
          <span className="truncate min-w-0">{formatSubestadoText(texto, 18)}</span>
        </span>
      </div>
    )
  }

  // 4. En seguimiento / En negociación / Visita a Proyecto
  if (norm.includes('seguimiento') || norm.includes('negociacion') || norm.includes('visita')) {
    const parts = formatDateParts(lead.fecha_proxima_gestion)
    if (!parts) return null
    return (
      <div className="mt-1 max-w-[130px] min-w-0 overflow-hidden">
        <span
          className="inline-flex items-center gap-1 text-[10px] text-blue-700 dark:text-blue-300 font-medium bg-blue-50 dark:bg-blue-950/40 border border-blue-200/80 dark:border-blue-800/50 rounded px-1.5 py-0.5 max-w-[130px] min-w-0 overflow-hidden"
          title={`Próx. gestión: ${parts.date} ${parts.time}`}
        >
          <Calendar size={10} className="shrink-0 text-blue-500" />
          <span className="truncate">{parts.date} {parts.time}</span>
        </span>
      </div>
    )
  }

  // 5. Cita agendada
  if (norm.includes('cita') || norm.includes('agendad')) {
    const rawFecha = lead.fecha_cita || lead.fecha_proxima_gestion
    const parts = formatDateParts(rawFecha)
    const estadoNombre = lead.cita_estado_nombre
    const estadoCodigo = (lead.cita_estado_codigo || '').toLowerCase()
    const isAtendida = ['completada', 'asistio', 'realizada', 'atendida'].includes(estadoCodigo)
    const isNoAsistio = estadoCodigo === 'no_asistio'
    const isReprog = estadoCodigo === 'reprogramada'

    if (!parts && !estadoNombre) return null
    return (
      <div className="flex flex-col gap-0.5 mt-1 max-w-[130px] min-w-0 overflow-hidden">
        {estadoNombre && (
          <span
            className={`inline-flex items-center gap-1 text-[10px] font-medium rounded px-1.5 py-0.5 max-w-[130px] min-w-0 overflow-hidden border ${
              isAtendida
                ? 'bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 border-emerald-200/80 dark:border-emerald-800/50'
                : isNoAsistio
                  ? 'bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 border-rose-200/80 dark:border-rose-800/50'
                  : isReprog
                    ? 'bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 border-amber-200/80 dark:border-amber-800/50'
                    : 'bg-blue-50 dark:bg-blue-950/40 text-blue-700 dark:text-blue-300 border-blue-200/80 dark:border-blue-800/50'
            }`}
            title={`Atención: ${estadoNombre}`}
          >
            {isAtendida ? (
              <CheckCircle2 size={10} className="shrink-0 text-emerald-600" />
            ) : isNoAsistio ? (
              <AlertCircle size={10} className="shrink-0 text-rose-500" />
            ) : (
              <Clock size={10} className="shrink-0 text-blue-500" />
            )}
            <span className="truncate min-w-0">{estadoNombre}</span>
          </span>
        )}
        {parts && (
          <span
            className="inline-flex items-center gap-1 text-[10px] text-indigo-700 dark:text-indigo-300 font-normal px-0.5 max-w-[130px] truncate"
            title={`Fecha de cita: ${parts.date} ${parts.time}`}
          >
            <Calendar size={9} className="shrink-0 text-indigo-500" />
            <span className="truncate">{parts.date} {parts.time}</span>
          </span>
        )}
      </div>
    )
  }

  // 6. Fallback si hay sub-información en cualquier otro estado
  if (lead.motivo_perdida || lead.tipo_cierre || lead.accion_proxima_gestion || lead.fecha_proxima_gestion) {
    const texto = lead.accion_proxima_gestion || lead.motivo_perdida || lead.tipo_cierre
    const parts = formatDateParts(lead.fecha_proxima_gestion)
    return (
      <div className="flex flex-col gap-0.5 mt-1 max-w-[130px] min-w-0 overflow-hidden">
        {texto && (
          <span
            className="inline-flex items-center gap-1 text-[10px] text-gray-700 dark:text-gray-300 font-medium bg-gray-50 dark:bg-gray-800 border border-gray-200 dark:border-gray-700 rounded px-1.5 py-0.5 max-w-[130px] min-w-0 overflow-hidden"
            title={texto}
          >
            <Clock size={9} className="shrink-0 text-gray-500" />
            <span className="truncate min-w-0">{formatSubestadoText(texto, 18)}</span>
          </span>
        )}
        {parts && (
          <span className="text-[10px] text-gray-500 px-0.5 max-w-[130px] truncate">
            {parts.date} {parts.time}
          </span>
        )}
      </div>
    )
  }

  }

  const content = renderContent()
  if (!content && !adminBadge) return null
  return (
    <>
      {content}
      {adminBadge}
    </>
  )
}


function EstadoDropdown({ lead, estados, onChangeEstado, onOpenCambioEstadoModal }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)
  const estado = estados.find(e => e.id === lead.estado_id)

  useEffect(() => {
    if (!open) return
    const handleClick = (e) => {
      if (ref.current && !ref.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [open])

  const handleSelectEstado = (targetEstado) => {
    setOpen(false)
    if (targetEstado.id === lead.estado_id) return
    if (requiresFormularioEspecifico(targetEstado.nombre) && onOpenCambioEstadoModal) {
      onOpenCambioEstadoModal(lead, targetEstado)
    } else {
      onChangeEstado(lead.id, targetEstado.id)
    }
  }

  return (
    <div ref={ref} className="relative flex flex-col items-start max-w-[140px] min-w-0">
      <button
        onClick={(e) => { e.stopPropagation(); setOpen(!open) }}
        className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold border hover:opacity-80 transition-opacity cursor-pointer"
        style={{
          backgroundColor: (estado?.color_hex || '#6b7280') + '20',
          color: estado?.color_hex || '#6b7280',
          borderColor: (estado?.color_hex || '#6b7280') + '40',
        }}
        title="Cambiar estado"
      >
        {estado?.nombre || '—'}
        <ChevronDown size={9} />
      </button>

      <EstadoSubinfo lead={lead} estadoNombre={estado?.nombre} />

      {open && (
        <div className="absolute z-30 top-full left-0 mt-1 bg-white border border-gray-200 rounded-xl shadow-xl py-1.5 min-w-[160px]">
          {estados.map(e => (
            <button
              key={e.id}
              onClick={(ev) => { ev.stopPropagation(); handleSelectEstado(e) }}
              className={`w-full text-left px-3 py-2 text-xs hover:bg-gray-50 flex items-center gap-2 transition-colors ${e.id === lead.estado_id ? 'font-semibold bg-gray-50' : ''
                }`}
            >
              <span className="w-2 h-2 rounded-full shrink-0" style={{ backgroundColor: e.color_hex }} />
              {e.nombre}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

const BASE_HEADERS = [
  { key: 'nombre_completo', label: 'Nombre', className: 'min-w-[130px]' },
  { key: 'telefono', label: 'Celular', className: 'min-w-[110px]' },
  { key: 'origen', label: 'Origen', className: 'min-w-[125px]' },
  { key: 'fuente_nombre', label: 'Fuente' },
  { key: 'campana', label: 'Campaña' },
  { key: 'form_nombre', label: 'Formulario' },
  { key: 'estado_id', label: 'Estado', className: 'min-w-[145px]' },
  { key: 'ficha_tecnica', label: 'Ficha Técnica', className: 'min-w-[135px]' },
  { key: 'calidad', label: 'Calidad', className: 'min-w-[120px]' },
  { key: 'intentos_contacto', label: 'Contactos', className: 'w-14 text-center' },
  { key: 'supervisor_nombre', label: 'Supervisor', className: 'min-w-[140px]' },
  { key: 'asesor_nombre', label: 'Asesor' },
  { key: 'fecha_ingreso', label: 'Creación' },
  { key: 'fecha_asignacion', label: 'Asignación' },
  { key: 'fecha_primer_contacto', label: '1er Contacto' },
  { key: 'fecha_ultimo_contacto', label: 'Últ. Contacto' },
  { key: 'ultima_actividad', label: 'Última Actividad', className: 'min-w-[140px]' },
  { key: 'fecha_proxima_gestion', label: 'Próx. Acción', className: 'min-w-[135px]' },
  // V093 — visibilidad explicita de recontactos. Antes el manager tenia que
  // filtrar para verlos; ahora son visibles directo en la lista (badge + fecha).
  { key: 'fecha_ultimo_recontacto', label: 'Recontactado', className: 'min-w-[120px]' },
  // V062: columna unica para proveedor (activo o legacy). Off por default —
  // solo admin/supervisor que gestionan integraciones la activan.
  { key: 'proveedor', label: 'Proveedor', className: 'min-w-[130px]' },
  // V065: columna sede de destino. Off por default — solo aparece util en
  // clientes multi-sede.
  { key: 'sede', label: 'Sede', className: 'min-w-[120px]' },
  { key: '_acciones', label: '', className: 'w-10' },
]

// Columnas que el usuario puede ocultar/mostrar. Las no listadas aquí son fijas.
const TOGGLEABLE_KEYS = [
  'telefono', 'fuente_nombre', 'campana', 'form_nombre', 'ficha_tecnica', 'calidad',
  'intentos_contacto', 'supervisor_nombre', 'asesor_nombre', 'fecha_ingreso', 'fecha_asignacion',
  'fecha_primer_contacto', 'fecha_ultimo_contacto', 'ultima_actividad', 'fecha_proxima_gestion',
  'fecha_ultimo_recontacto',
  'proveedor',
  'sede',
]
// Columnas visibles por default cuando el user no tiene preferencia guardada.
// proveedor y sede quedan fuera — solo aparecen utiles en clientes que las
// usan. El user las activa en el menu Campos.
const DEFAULT_VISIBLE_KEYS = TOGGLEABLE_KEYS.filter(k => !['proveedor', 'sede'].includes(k))
const STORAGE_KEY = 'leads_visible_cols'
function loadVisibleCols() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw) {
      const set = new Set(JSON.parse(raw))
      if (!localStorage.getItem('leads_has_v_ultima_actividad')) {
        set.add('ultima_actividad')
        localStorage.setItem(STORAGE_KEY, JSON.stringify([...set]))
        localStorage.setItem('leads_has_v_ultima_actividad', '1')
      }
      return set
    }
  } catch { /* ignore */ }
  return new Set(DEFAULT_VISIBLE_KEYS)
}

const EMPTY_FILTERS = { estado_cola: '', filtro_alerta: '', ficha_tecnica_estado: '', filtro_fecha_gestion: '', filtro_fecha_cita: '', filtro_cita_atendida: '', subestado: '', origen: '', fuente_id: '', asesor_id: '', asesor_historico_id: '', supervisor_id: '', api_client_id: '', api_client_legacy_slug: '', sede_id: '', campana: '', calidad: '', fecha_desde: '', fecha_hasta: '', fecha_asig_desde: '', fecha_asig_hasta: '', fecha_actividad_desde: '', fecha_actividad_hasta: '', con_antecedentes: false, recontacto_campana: '', recontacto_anuncio: '', recontacto_conjunto: '', recontacto_fuente_id: '', recontacto_desde: '', recontacto_hasta: '', recontacto_api_client_id: '', tocado_por_api_client_id: '', recontacto_sin_atender: false, recontacto_recientes_horas: '' }

export default function Leads() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { user } = useAuthStore()
  const { estados, fuentes, calidades, loadCatalogs } = useCrmStore()
  const role = user?.role || 'asesor'
  const canFilterByAsesor = role === 'admin' || role === 'supervisor' || user?.role_id != null
  const canAssign = role === 'admin' || role === 'supervisor' || hasPermission(user, 'asignacion.manage')
  const canCreate = hasPermission(user, 'leads.create')
  const canEdit = hasPermission(user, 'leads.edit')
  const canDelete = hasPermission(user, 'leads.delete')
  // Export a Excel: cualquier rol con el permiso `reportes.export`.
  // Backend ya gatea el endpoint con check_permission("reportes.export", "supervisor")
  // y audita cada descarga. Permite habilitar export a roles custom
  // (ej. marketing_proveedor) desde Configuracion → Roles sin tocar codigo.
  const canExport = hasPermission(user, 'reportes.export')

  // Protección anti-copy-paste
  useCopyProtection(true, 'leads')

  const [visibleCols, setVisibleCols] = useState(loadVisibleCols)
  const [showColMenu, setShowColMenu] = useState(false)
  const colMenuRef = useRef(null)
  const toggleCol = (key) => {
    setVisibleCols(prev => {
      const next = new Set(prev)
      if (next.has(key)) next.delete(key); else next.add(key)
      localStorage.setItem(STORAGE_KEY, JSON.stringify([...next]))
      return next
    })
  }
  useEffect(() => {
    if (!showColMenu) return
    const handler = (e) => { if (colMenuRef.current && !colMenuRef.current.contains(e.target)) setShowColMenu(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [showColMenu])

  const [leads, setLeads] = useState([])
  const [total, setTotal] = useState(0)
  const [estadoCounts, setEstadoCounts] = useState({})
  const [totalGlobal, setTotalGlobal] = useState(0)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)
  const [page, setPage] = useState(1)
  const [searchInput, setSearchInput] = useState('')
  const [search, setSearch] = useState('')
  const [estadoFilter, setEstadoFilter] = useState('')
  // V061: si la URL trae ?api_client_id=X (deep-link desde el modal Stats
  // de ApiClients), pre-seteamos el filtro para mostrar solo esos leads.
  const [filters, setFilters] = useState(() => {
    const initial = { ...EMPTY_FILTERS }
    const hoyFromUrl = searchParams.get('hoy') || searchParams.get('leads_hoy')
    if (hoyFromUrl === 'true' || hoyFromUrl === '1') {
      const today = getTodayDateString()
      initial.fecha_desde = today
      initial.fecha_hasta = today
    } else {
      const fechaDesdeFromUrl = searchParams.get('fecha_desde')
      if (fechaDesdeFromUrl) initial.fecha_desde = fechaDesdeFromUrl
      const fechaHastaFromUrl = searchParams.get('fecha_hasta')
      if (fechaHastaFromUrl) initial.fecha_hasta = fechaHastaFromUrl
    }
    const origenFromUrl = searchParams.get('origen')
    if (origenFromUrl) initial.origen = origenFromUrl
    const apiClientFromUrl = searchParams.get('api_client_id')
    if (apiClientFromUrl) initial.api_client_id = apiClientFromUrl
    // V062: deep-link por proveedor original (post-unlink)
    const legacyFromUrl = searchParams.get('api_client_legacy_slug')
    if (legacyFromUrl) initial.api_client_legacy_slug = legacyFromUrl
    const supervisorFromUrl = searchParams.get('supervisor_id')
    if (supervisorFromUrl) initial.supervisor_id = supervisorFromUrl
    const estadoColaFromUrl = searchParams.get('estado_cola')
    if (estadoColaFromUrl) initial.estado_cola = estadoColaFromUrl
    const alertaFromUrl = searchParams.get('alerta') || searchParams.get('filtro_alerta')
    if (alertaFromUrl) initial.filtro_alerta = alertaFromUrl
    const fechaGestionFromUrl = searchParams.get('filtro_fecha_gestion') || searchParams.get('fecha_gestion')
    if (fechaGestionFromUrl) initial.filtro_fecha_gestion = fechaGestionFromUrl
    const fechaCitaFromUrl = searchParams.get('filtro_fecha_cita') || searchParams.get('fecha_cita')
    if (fechaCitaFromUrl) initial.filtro_fecha_cita = fechaCitaFromUrl
    const citaAtendidaFromUrl = searchParams.get('filtro_cita_atendida') || searchParams.get('cita_atendida')
    if (citaAtendidaFromUrl) initial.filtro_cita_atendida = citaAtendidaFromUrl
    return initial
  })

  const todayDateStr = getTodayDateString()
  const isLeadsHoyActive = Boolean(
    filters.fecha_desde &&
    filters.fecha_hasta &&
    filters.fecha_desde === filters.fecha_hasta &&
    filters.fecha_desde === todayDateStr
  )

  const handleToggleLeadsHoy = useCallback(() => {
    const today = getTodayDateString()
    if (isLeadsHoyActive) {
      setFilters(prev => ({
        ...prev,
        fecha_desde: '',
        fecha_hasta: '',
      }))
      setSearchParams(prev => {
        const next = new URLSearchParams(prev)
        next.delete('fecha_desde')
        next.delete('fecha_hasta')
        next.delete('hoy')
        next.delete('leads_hoy')
        return next
      })
    } else {
      setFilters(prev => ({
        ...prev,
        fecha_desde: today,
        fecha_hasta: today,
        estado_cola: '',
        filtro_alerta: '',
        recontacto_sin_atender: false,
      }))
      setSearch('')
      setSearchInput('')
      setEstadoFilter('')
      setSearchParams(prev => {
        const next = new URLSearchParams(prev)
        next.set('fecha_desde', today)
        next.set('fecha_hasta', today)
        next.delete('estado_cola')
        next.delete('alerta')
        next.delete('filtro_alerta')
        next.delete('hoy')
        next.delete('leads_hoy')
        return next
      })
    }
  }, [isLeadsHoyActive, setSearchParams])
  // showFilters: ya no se usa con AdvancedFilters builder, lo dejamos solo
  // como toggle del FilterPanel legacy (que esta oculto en este flujo).
  const [showFilters] = useState(false)
  // V094 — contador de recontactos sin atender para el RecontactosBanner.
  // Refresh cada vez que se monta la pagina + cada 60s (similar al alerta
  // de urgentes). Es snapshot operacional, no responde a filtros del usuario.
  // V094.1 — escalacion: tracking separado de amber (<48h) y red (>=48h)
  // + oldest_days para texto urgente.
  const [recontactosSummary, setRecontactosSummary] = useState({
    sin_atender: 0, sin_atender_amber: 0, sin_atender_red: 0, mas_viejo_dias: 0,
  })
  const [colaSummary, setColaSummary] = useState({
    estancados: 0, pendientes: 0, total_cola: 0,
  })
  const [alertasSummary, setAlertasSummary] = useState({
    urgentes_48h: 0, sla_15m: 0, pendientes_seguimiento: 0,
  })
  const [gestionSummary, setGestionSummary] = useState({
    vencidas: 0, sin_fecha: 0, hoy: 0, al_dia: 0, total: 0,
  })
  const [citasSummary, setCitasSummary] = useState({
    vencidas: 0, sin_fecha: 0, hoy: 0, al_dia: 0,
    atendidas: 0, no_atendidas: 0, no_asistio: 0, total: 0,
  })

  const fetchGestionSummary = useCallback(() => {
    const params = new URLSearchParams()
    if (search) params.set('search', search)
    if (estadoFilter) params.set('estado_id', estadoFilter)
    if (filters.subestado) params.set('subestado', filters.subestado)
    if (filters.origen) params.set('origen', filters.origen)
    if (filters.fuente_id) params.set('fuente_id', filters.fuente_id)
    if (filters.asesor_id) params.set('asesor_id', filters.asesor_id)
    if (filters.asesor_historico_id) params.set('asesor_historico_id', filters.asesor_historico_id)
    if (filters.supervisor_id) params.set('supervisor_id', filters.supervisor_id)
    if (filters.api_client_id) params.set('api_client_id', filters.api_client_id)
    if (filters.campana) params.set('campana', filters.campana)
    if (filters.calidad) params.set('calidad', filters.calidad)
    if (filters.sede_id) params.set('sede_id', filters.sede_id)
    if (filters.fecha_desde) params.set('fecha_desde', filters.fecha_desde)
    if (filters.fecha_hasta) params.set('fecha_hasta', filters.fecha_hasta)
    if (filters.con_antecedentes) params.set('con_antecedentes', 'true')
    const qs = params.toString()
    api.get(`/api/dashboard/gestion-summary${qs ? `?${qs}` : ''}`)
      .then(res => setGestionSummary(res.data || { vencidas: 0, sin_fecha: 0, hoy: 0, al_dia: 0, total: 0 }))
      .catch(() => { })
  }, [search, estadoFilter, filters.subestado, filters.origen, filters.fuente_id, filters.asesor_id, filters.asesor_historico_id, filters.supervisor_id, filters.api_client_id, filters.campana, filters.calidad, filters.sede_id, filters.fecha_desde, filters.fecha_hasta, filters.con_antecedentes])

  useEffect(() => {
    fetchGestionSummary()
  }, [fetchGestionSummary])

  const fetchCitasSummary = useCallback(() => {
    const params = new URLSearchParams()
    if (search) params.set('search', search)
    if (estadoFilter) params.set('estado_id', estadoFilter)
    if (filters.subestado) params.set('subestado', filters.subestado)
    if (filters.origen) params.set('origen', filters.origen)
    if (filters.fuente_id) params.set('fuente_id', filters.fuente_id)
    if (filters.asesor_id) params.set('asesor_id', filters.asesor_id)
    if (filters.asesor_historico_id) params.set('asesor_historico_id', filters.asesor_historico_id)
    if (filters.supervisor_id) params.set('supervisor_id', filters.supervisor_id)
    if (filters.api_client_id) params.set('api_client_id', filters.api_client_id)
    if (filters.campana) params.set('campana', filters.campana)
    if (filters.calidad) params.set('calidad', filters.calidad)
    if (filters.sede_id) params.set('sede_id', filters.sede_id)
    if (filters.fecha_desde) params.set('fecha_desde', filters.fecha_desde)
    if (filters.fecha_hasta) params.set('fecha_hasta', filters.fecha_hasta)
    if (filters.con_antecedentes) params.set('con_antecedentes', 'true')
    const qs = params.toString()
    api.get(`/api/dashboard/citas-summary${qs ? `?${qs}` : ''}`)
      .then(res => setCitasSummary(res.data || {
        vencidas: 0, sin_fecha: 0, hoy: 0, al_dia: 0,
        atendidas: 0, no_atendidas: 0, no_asistio: 0, total: 0,
      }))
      .catch(() => { })
  }, [search, estadoFilter, filters.subestado, filters.origen, filters.fuente_id, filters.asesor_id, filters.asesor_historico_id, filters.supervisor_id, filters.api_client_id, filters.campana, filters.calidad, filters.sede_id, filters.fecha_desde, filters.fecha_hasta, filters.con_antecedentes])

  useEffect(() => {
    fetchCitasSummary()
  }, [fetchCitasSummary])

  useEffect(() => {
    let alive = true
    const fetchSummary = () => {
      api.get('/api/dashboard/recontactos-summary')
        .then(res => { if (alive) setRecontactosSummary(res.data || { sin_atender: 0 }) })
        .catch(() => { /* silencioso — el banner simplemente no aparece */ })
      api.get('/api/dashboard/cola-summary')
        .then(res => { if (alive) setColaSummary(res.data || { estancados: 0, pendientes: 0, total_cola: 0 }) })
        .catch(() => { /* silencioso */ })
      api.get('/api/dashboard/alertas-summary')
        .then(res => { if (alive) setAlertasSummary(res.data || { urgentes_48h: 0, sla_15m: 0, pendientes_seguimiento: 0 }) })
        .catch(() => { /* silencioso */ })
    }
    fetchSummary()
    const id = setInterval(fetchSummary, 60_000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  // V052: ordenacion multi-campo estilo patrón premium. [{field, dir}]
  const [sorts, setSorts] = useState(() => {
    try {
      const cached = localStorage.getItem('leads_sorts')
      return cached ? JSON.parse(cached) : []
    } catch { return [] }
  })
  useEffect(() => {
    try { localStorage.setItem('leads_sorts', JSON.stringify(sorts)) } catch { /* ignore */ }
  }, [sorts])

  // V063 — Saved views. El estado actual (filtros + sort + columnas visibles
  // + orden de columnas) se compara contra la vista activa para detectar
  // "modificada". Cuando se selecciona una vista, se restauran los 4 campos.
  const [columnsOrder, setColumnsOrder] = useState(() => {
    try {
      const raw = localStorage.getItem('leads_columns_order')
      if (raw) return JSON.parse(raw)
    } catch { /* ignore */ }
    return []
  })
  const currentViewState = useMemo(() => ({
    filters: { ...filters, _estadoFilter: estadoFilter || '' },
    sort: sorts,
    columns_order: columnsOrder,
    visible_columns: [...visibleCols].sort(),
  }), [filters, estadoFilter, sorts, columnsOrder, visibleCols])

  const {
    views, activeView, activeViewId, setActiveViewId, isDirty, isMutating,
    createView, updateView, saveCurrentToActive, deleteView, setDefault, duplicateView,
  } = useSavedViews({ scope: 'leads', currentState: currentViewState })

  // Modal "guardar como vista" / "renombrar"
  const [viewModal, setViewModal] = useState(null)  // null | { mode: 'create'|'rename', initial }
  // Confirmacion destructiva para eliminar vista (reemplaza window.confirm
  // nativo por el ConfirmDialog premium del CRM).
  const [confirmDeleteView, setConfirmDeleteView] = useState(null)  // null | view

  /** Restaura el estado completo a partir del JSON de una vista. Si view
   *  es null, vuelve a "Todos" (filtros vacios, sin sort, columnas default). */
  const applyView = useCallback((view) => {
    if (!view) {
      setFilters(EMPTY_FILTERS)
      setEstadoFilter('')
      setSorts([])
      setVisibleCols(new Set(DEFAULT_VISIBLE_KEYS))
      setColumnsOrder([])  // DataTable cae al default del header
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify(DEFAULT_VISIBLE_KEYS)) } catch { /* ignore */ }
      setActiveViewId(null)
      setPage(1)
      return
    }
    const { _estadoFilter, ...rest } = view.filters || {}
    setFilters({ ...EMPTY_FILTERS, ...rest })
    setEstadoFilter(_estadoFilter || '')
    setSorts(Array.isArray(view.sort) ? view.sort : [])
    if (Array.isArray(view.visible_columns) && view.visible_columns.length > 0) {
      const vc = new Set(view.visible_columns)
      setVisibleCols(vc)
      try { localStorage.setItem(STORAGE_KEY, JSON.stringify([...vc])) } catch { /* ignore */ }
    }
    setColumnsOrder(Array.isArray(view.columns_order) ? view.columns_order : [])
    setActiveViewId(view.id)
    setPage(1)
  }, [setActiveViewId])

  // Auto-aplicar vista de default al cargar las vistas la primera vez,
  // siempre que no haya filtros activos via URL (?api_client_id=... etc).
  const [defaultApplied, setDefaultApplied] = useState(false)
  useEffect(() => {
    if (defaultApplied || views.length === 0) return
    const hasUrlFilter = searchParams.has('api_client_id') || searchParams.has('api_client_legacy_slug') || searchParams.has('view')
    const urlViewId = searchParams.get('view')
    if (urlViewId) {
      const target = views.find(v => v.id === urlViewId)
      if (target) applyView(target)
    } else if (!hasUrlFilter) {
      const def = views.find(v => v.is_default)
      if (def) applyView(def)
    }
    setDefaultApplied(true)
  }, [views, defaultApplied, searchParams, applyView])

  // URL sync — cuando cambia la vista activa, refleja en ?view=
  useEffect(() => {
    setSearchParams(prev => {
      const next = new URLSearchParams(prev)
      if (activeViewId) next.set('view', activeViewId)
      else next.delete('view')
      return next
    }, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeViewId])

  const [asesores, setAsesores] = useState([])
  const [supervisores, setSupervisores] = useState([])
  // Grupos por equipo (estructura unificada con Asignación) — el dropdown
  // de la bulk bar los renderiza con optgroups "Equipo: X" / "Otros supervisores".
  const [teamGroups, setTeamGroups] = useState([])
  const [campanas, setCampanas] = useState([])
  const [isExporting, setIsExporting] = useState(false)
  // Export con confirmacion cuando la seleccion excede el umbral amigable.
  // Almacena null | {count: number} — si es no-null, el modal aparece.
  const [pendingExport, setPendingExport] = useState(null)
  const [selectedLeads, setSelectedLeads] = useState(new Set())
  const [isBulkAssigning, setIsBulkAssigning] = useState(false)
  const [isBulkChangingEstado, setIsBulkChangingEstado] = useState(false)
  const [isBulkChangingFuente, setIsBulkChangingFuente] = useState(false)
  const [isBulkDeleting, setIsBulkDeleting] = useState(false)
  const [confirmBulkDelete, setConfirmBulkDelete] = useState(false)
  // Reasignación pendiente de confirmación: {toAsesorId, breakdown, count, asesorNombre}
  const [pendingReassign, setPendingReassign] = useState(null)
  // Cambio de estado pendiente: {estadoId, estadoNombre, count}
  const [pendingEstadoChange, setPendingEstadoChange] = useState(null)
  // Cambio de fuente pendiente: {fuenteId, fuenteNombre, count}
  const [pendingFuenteChange, setPendingFuenteChange] = useState(null)
  const [isBulkRevertingTmk, setIsBulkRevertingTmk] = useState(false)
  const [confirmBulkRevertTmk, setConfirmBulkRevertTmk] = useState(null)
  const [isBulkDevolviendoHistoricos, setIsBulkDevolviendoHistoricos] = useState(false)
  const [confirmBulkDevolverHistoricos, setConfirmBulkDevolverHistoricos] = useState(null)
  // Dialog de resultado/info que reemplaza window.alert(). Estructura:
  // null  | { variant: 'success'|'warning'|'error'|'info', title, message }
  const [infoDialog, setInfoDialog] = useState(null)
  const [newLeadsCount, setNewLeadsCount] = useState(0)
  const [cambioEstadoModal, setCambioEstadoModal] = useState({ open: false, lead: null, targetEstado: null })
  const [allUsersList, setAllUsersList] = useState([])
  const searchRef = useRef(null)
  const knownTotalRef = useRef(null)

  const [historicosSinFuente, setHistoricosSinFuente] = useState({ count: 0, leads: [] })
  const [showHistoricosModal, setShowHistoricosModal] = useState(false)
  const [isFixingHistoricos, setIsFixingHistoricos] = useState(false)
  const [modalHistoricosPage, setModalHistoricosPage] = useState(1)
  const [modalHistoricosSearch, setModalHistoricosSearch] = useState('')
  const MODAL_PAGE_SIZE = 10

  const filteredModalLeads = useMemo(() => {
    if (!historicosSinFuente.leads) return []
    const q = modalHistoricosSearch.trim().toLowerCase()
    if (!q) return historicosSinFuente.leads
    const qDigits = q.replace(/\D/g, '')
    return historicosSinFuente.leads.filter(l => {
      const telDigits = (l.telefono || '').replace(/\D/g, '')
      const phoneMatch = qDigits.length >= 4 && telDigits.includes(qDigits.slice(-9))
      return (
        phoneMatch ||
        String(l.id).includes(q) ||
        (l.nombre_completo && l.nombre_completo.toLowerCase().includes(q)) ||
        (l.telefono && l.telefono.toLowerCase().includes(q)) ||
        (l.email && l.email.toLowerCase().includes(q)) ||
        (l.asesor_nombre && l.asesor_nombre.toLowerCase().includes(q)) ||
        (l.fuente_actual && l.fuente_actual.toLowerCase().includes(q))
      )
    })
  }, [historicosSinFuente.leads, modalHistoricosSearch])

  const totalModalPages = Math.max(1, Math.ceil(filteredModalLeads.length / MODAL_PAGE_SIZE))

  const paginatedModalLeads = useMemo(() => {
    const start = (modalHistoricosPage - 1) * MODAL_PAGE_SIZE
    return filteredModalLeads.slice(start, start + MODAL_PAGE_SIZE)
  }, [filteredModalLeads, modalHistoricosPage])

  const checkHistoricosSinFuente = useCallback(() => {
    if (role !== 'admin') return
    api.get('/api/leads/mantenimiento/historicos-sin-fuente')
      .then(res => {
        setHistoricosSinFuente(res.data || { count: 0, leads: [] })
      })
      .catch(() => { })
  }, [role])

  useEffect(() => {
    checkHistoricosSinFuente()
  }, [checkHistoricosSinFuente])

  useEffect(() => {
    api.get('/auth/users').then(res => setAllUsersList(res.data || [])).catch(() => { })
  }, [])

  useEffect(() => {
    loadCatalogs()
    api.get('/api/leads/campanas')
      .then(r => setCampanas(r.data || []))
      .catch(() => { })
  }, [])

  // Conteos por estado (resumen visual en pills) — respetan los filtros
  // activos salvo la propia pestaña de estado seleccionada.
  const fetchCounts = useCallback(() => {
    const params = new URLSearchParams()
    if (search) params.set('search', search)
    if (filters.origen) params.set('origen', filters.origen)
    if (filters.fuente_id) params.set('fuente_id', filters.fuente_id)
    if (filters.asesor_id) params.set('asesor_id', filters.asesor_id)
    if (filters.asesor_historico_id) params.set('asesor_historico_id', filters.asesor_historico_id)
    if (filters.supervisor_id) params.set('supervisor_id', filters.supervisor_id)
    if (filters.api_client_id) params.set('api_client_id', filters.api_client_id)
    if (filters.api_client_legacy_slug) params.set('api_client_legacy_slug', filters.api_client_legacy_slug)
    if (filters.sede_id) params.set('sede_id', filters.sede_id)
    if (filters.campana) params.set('campana', filters.campana)
    if (filters.fecha_desde) params.set('fecha_desde', filters.fecha_desde)
    if (filters.fecha_hasta) params.set('fecha_hasta', filters.fecha_hasta)
    if (filters.fecha_asig_desde) params.set('fecha_asig_desde', filters.fecha_asig_desde)
    if (filters.fecha_asig_hasta) params.set('fecha_asig_hasta', filters.fecha_asig_hasta)
    if (filters.fecha_actividad_desde) params.set('fecha_actividad_desde', filters.fecha_actividad_desde)
    if (filters.fecha_actividad_hasta) params.set('fecha_actividad_hasta', filters.fecha_actividad_hasta)
    if (filters.con_antecedentes) params.set('con_antecedentes', 'true')
    if (filters.calidad) params.set('calidad', filters.calidad)
    if (filters.recontacto_campana) params.set('recontacto_campana', filters.recontacto_campana)
    if (filters.recontacto_anuncio) params.set('recontacto_anuncio', filters.recontacto_anuncio)
    if (filters.recontacto_conjunto) params.set('recontacto_conjunto', filters.recontacto_conjunto)
    if (filters.recontacto_fuente_id) params.set('recontacto_fuente_id', filters.recontacto_fuente_id)
    if (filters.recontacto_desde) params.set('recontacto_desde', filters.recontacto_desde)
    if (filters.recontacto_hasta) params.set('recontacto_hasta', filters.recontacto_hasta)
    if (filters.recontacto_api_client_id) params.set('recontacto_api_client_id', filters.recontacto_api_client_id)
    if (filters.tocado_por_api_client_id) params.set('tocado_por_api_client_id', filters.tocado_por_api_client_id)
    // V094 — re-engagement workflow filters
    if (filters.recontacto_sin_atender) params.set('recontacto_sin_atender', 'true')
    if (filters.recontacto_recientes_horas) params.set('recontacto_recientes_horas', String(filters.recontacto_recientes_horas))
    if (filters.estado_cola) params.set('estado_cola', filters.estado_cola)
    if (filters.filtro_alerta) params.set('filtro_alerta', filters.filtro_alerta)
    if (filters.filtro_fecha_gestion) params.set('filtro_fecha_gestion', filters.filtro_fecha_gestion)
    if (filters.filtro_fecha_cita) params.set('filtro_fecha_cita', filters.filtro_fecha_cita)
    if (filters.filtro_cita_atendida) params.set('filtro_cita_atendida', filters.filtro_cita_atendida)
    const qs = params.toString()
    api.get(`/api/dashboard/leads-por-estado${qs ? `?${qs}` : ''}`)
      .then(res => {
        const data = res.data || []
        const counts = {}
        let tot = 0
        data.forEach(d => {
          counts[d.estado_id] = d.count
          tot += d.count
        })
        setEstadoCounts(counts)
        setTotalGlobal(tot)
      })
      .catch(() => { })
  }, [search, filters])

  useEffect(() => { fetchCounts() }, [fetchCounts])

  useEffect(() => {
    if (!canFilterByAsesor && !canAssign) return
    Promise.all([
      api.get('/auth/users'),
      api.get('/api/equipos'),
    ])
      .then(([usersRes, equiposRes]) => {
        const allUsers = usersRes.data || []
        // Estructura unificada con Asignación: agrupado por equipo y alcance de asignación.
        const asignacionScope = user?.permissions?.['asignacion.scope'] || (role === 'admin' ? 'global' : 'equipo')
        const allowedUserIds = user?.permissions?.['asignacion.allowed_users'] || []
        const { groups } = buildTeamGroups({
          users: allUsers,
          equipos: equiposRes.data || [],
          role,
          currentUserId: user?.user_id,
          asignacionScope,
          allowedUserIds,
        })
        setTeamGroups(groups)
        // Lista plana para FilterPanel y lookups por id (confirmaciones).
        setAsesores(flattenGroups(groups))

        // Supervisores activos para el filtro por supervisor
        const sups = allUsers
          .filter(u => u.role === 'supervisor' && u.is_active !== false)
          .map(u => ({
            ...u,
            nombre_completo: [u.first_name, u.last_name].filter(Boolean).join(' ') || u.email,
          }))
          .sort((a, b) => (a.nombre_completo || '').localeCompare(b.nombre_completo || ''))
        setSupervisores(sups)
      })
      .catch(() => { })
  }, [canFilterByAsesor, canAssign, role, user?.user_id, user?.permissions])

  // V062: catalogo de proveedores para poblar el dropdown del filtro
  // "Proveedor" + slugs legacy en uso. Endpoint publico /api/api-clients/lookup
  // (cualquier rol autenticado), sustituye al call admin que solo veian
  // admin/supervisor. Se carga una sola vez al montar.
  const [apiClients, setApiClients] = useState([])
  const [apiClientsLegacy, setApiClientsLegacy] = useState([])
  useEffect(() => {
    api.get('/api/api-clients/lookup')
      .then(res => {
        setApiClients(res.data?.clients || [])
        setApiClientsLegacy(res.data?.legacy || [])
      })
      .catch(() => { })
  }, [])

  // V065: catalogo de sedes activas para poblar el filtro "Sede" y la
  // columna opcional en la tabla. /api/sedes/lookup es publico para
  // cualquier rol autenticado.
  const [sedes, setSedes] = useState([])
  useEffect(() => {
    api.get('/api/sedes/lookup?only_active=true')
      .then(res => setSedes(res.data || []))
      .catch(() => { })
  }, [])

  // Nombre del proveedor (activo o legacy) para mostrarlo en el chip
  // indicador del deep-link. Derivado, sin fetch extra.
  // Map id -> nombre para resolver el badge "Proveedor" de cada fila sin
  // tener que devolver `proveedor_nombre` desde el listado (ahorra un JOIN
  // por query).
  const apiClientNameById = useMemo(() => {
    const m = new Map()
    apiClients.forEach(c => m.set(c.id, c.nombre))
    return m
  }, [apiClients])

  const apiClientName = useMemo(() => {
    if (filters.api_client_id) {
      const found = apiClients.find(c => c.id === filters.api_client_id)
      return found?.nombre || filters.api_client_id.slice(0, 8)
    }
    if (filters.api_client_legacy_slug) {
      const found = apiClientsLegacy.find(l => l.slug === filters.api_client_legacy_slug)
      return found?.nombre || filters.api_client_legacy_slug
    }
    return ''
  }, [filters.api_client_id, filters.api_client_legacy_slug, apiClients, apiClientsLegacy])

  // Búsqueda en tiempo real con debounce 400ms
  useEffect(() => {
    const timer = setTimeout(() => {
      setSearch(searchInput.trim())
      setPage(1)
    }, 400)
    return () => clearTimeout(timer)
  }, [searchInput])

  // Atajo de teclado: "/" para buscar, Esc para limpiar
  useEffect(() => {
    const handleKey = (e) => {
      if (e.key === '/' && document.activeElement?.tagName !== 'INPUT' && document.activeElement?.tagName !== 'TEXTAREA') {
        e.preventDefault()
        searchRef.current?.focus()
      }
      if (e.key === 'Escape' && document.activeElement === searchRef.current) {
        setSearchInput('')
        searchRef.current?.blur()
      }
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [])

  // Acepta opcion `silent` para no togglear el spinner durante polls de
  // background — evita el flicker al refrescar cada 45s.
  const fetchLeads = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setIsLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      params.set('limit', PAGE_SIZE)
      params.set('offset', (page - 1) * PAGE_SIZE)
      if (search) params.set('search', search)
      if (estadoFilter) params.set('estado_id', estadoFilter)
      if (filters.subestado) params.set('subestado', filters.subestado)
      if (filters.origen) params.set('origen', filters.origen)
      if (filters.fuente_id) params.set('fuente_id', filters.fuente_id)
      if (filters.asesor_id) params.set('asesor_id', filters.asesor_id)
      if (filters.asesor_historico_id) params.set('asesor_historico_id', filters.asesor_historico_id)
      if (filters.supervisor_id) params.set('supervisor_id', filters.supervisor_id)
      if (filters.api_client_id) params.set('api_client_id', filters.api_client_id)
      if (filters.campana) params.set('campana', filters.campana)
      if (filters.fecha_desde) params.set('fecha_desde', filters.fecha_desde)
      if (filters.fecha_hasta) params.set('fecha_hasta', filters.fecha_hasta)
      if (filters.fecha_asig_desde) params.set('fecha_asig_desde', filters.fecha_asig_desde)
      if (filters.fecha_asig_hasta) params.set('fecha_asig_hasta', filters.fecha_asig_hasta)
      if (filters.fecha_actividad_desde) params.set('fecha_actividad_desde', filters.fecha_actividad_desde)
      if (filters.fecha_actividad_hasta) params.set('fecha_actividad_hasta', filters.fecha_actividad_hasta)
      if (filters.con_antecedentes) params.set('con_antecedentes', 'true')
      if (filters.calidad) params.set('calidad', filters.calidad)
      if (filters.recontacto_campana) params.set('recontacto_campana', filters.recontacto_campana)
      if (filters.recontacto_anuncio) params.set('recontacto_anuncio', filters.recontacto_anuncio)
      if (filters.recontacto_conjunto) params.set('recontacto_conjunto', filters.recontacto_conjunto)
      if (filters.recontacto_fuente_id) params.set('recontacto_fuente_id', filters.recontacto_fuente_id)
      if (filters.recontacto_desde) params.set('recontacto_desde', filters.recontacto_desde)
      if (filters.recontacto_hasta) params.set('recontacto_hasta', filters.recontacto_hasta)
      if (filters.recontacto_api_client_id) params.set('recontacto_api_client_id', filters.recontacto_api_client_id)
      if (filters.tocado_por_api_client_id) params.set('tocado_por_api_client_id', filters.tocado_por_api_client_id)
      // V094 — re-engagement workflow filters
      if (filters.recontacto_sin_atender) params.set('recontacto_sin_atender', 'true')
      if (filters.recontacto_recientes_horas) params.set('recontacto_recientes_horas', String(filters.recontacto_recientes_horas))
      if (filters.estado_cola) params.set('estado_cola', filters.estado_cola)
      if (filters.filtro_alerta) params.set('filtro_alerta', filters.filtro_alerta)
      if (filters.ficha_tecnica_estado) params.set('ficha_tecnica_estado', filters.ficha_tecnica_estado)
      if (filters.filtro_fecha_gestion) params.set('filtro_fecha_gestion', filters.filtro_fecha_gestion)
      if (filters.filtro_fecha_cita) params.set('filtro_fecha_cita', filters.filtro_fecha_cita)
      if (filters.filtro_cita_atendida) params.set('filtro_cita_atendida', filters.filtro_cita_atendida)
      // V052: ordenacion multi-campo (sort=fecha:desc,nombre:asc)
      if (sorts && sorts.length > 0) {
        params.set('sort', sorts.map(s => `${s.field}:${s.dir}`).join(','))
      }

      const res = await api.get(`/api/leads?${params.toString()}`)
      setLeads(res.data.items || [])
      setTotal(res.data.total || 0)
    } catch (err) {
      if (!silent) setError(err.response?.data?.detail || 'Error al cargar los leads.')
    } finally {
      if (!silent) setIsLoading(false)
    }
  }, [page, search, estadoFilter, filters, sorts])

  useEffect(() => { fetchLeads() }, [fetchLeads])

  // V070.77 — UX fix: refresh SOLO al volver de background.
  //
  // Antes habia un polling silencioso cada 30s que hacia fetchLeads
  // automatico. Esto rompia la UX del banner "X leads nuevos":
  //
  //   - El usuario veia el lead aparecer en la lista (refresh silent),
  //     y RECIEN DESPUES aparecia el banner "1 nuevo". Click al banner
  //     no hacia nada visible porque ya estaba viendo el lead.
  //   - Peor: la lista se reordenaba sola mientras el usuario scrolleaba
  //     o seleccionaba leads para asignar — perdia su contexto.
  //
  // Patron patrón estándar/correo profesional/Twitter: la lista NO se reordena sola; el
  // sistema avisa con un banner y el usuario decide cuando refrescar.
  // El refresh ocurre via:
  //   1. handleRefreshNewLeads (click en el banner) → ver fn abajo
  //   2. Visibilitychange al volver a la pestaña (caso normal: el
  //      usuario estaba en otra tab y vuelve esperando ver todo al dia).
  //   3. Acciones manuales del usuario (cambio de pagina, filtros, etc).
  useEffect(() => {
    const handleVisibility = () => {
      if (document.visibilityState === 'visible') {
        // Al volver de background, refrescar todo + resetear baseline
        // del banner para que no quede colgado un "X nuevos" desactualizado.
        fetchLeads({ silent: true })
        api.get('/api/leads?limit=1&offset=0')
          .then(res => { knownTotalRef.current = res.data.total || 0 })
          .catch(() => { })
        setNewLeadsCount(0)
      }
    }
    document.addEventListener('visibilitychange', handleVisibility)
    return () => document.removeEventListener('visibilitychange', handleVisibility)
  }, [fetchLeads])

  // V067.1 — La baseline para detectar leads nuevos viene SOLO del fetch
  // dedicado sin filtros (init + refresh). El effect previo tomaba
  // `total` (count de la tabla filtrada) como baseline cuando creia que
  // no habia filtros, pero el check `hasFilters` ignoraba dimensiones
  // como vistas guardadas, sede_id, calidad, campana, con_antecedentes,
  // api_client_id, sin_asesor — produciendo baselines erroneas (ej. 36)
  // y banners con numeros absurdos (ej. "5935 nuevos leads") cuando en
  // realidad solo eran leads ya existentes fuera de la vista activa.
  //
  // Mantenemos la baseline estable durante toda la sesion: se inicia en
  // mount, se reinicia al hacer click en el banner de refresh. Punto.

  // Inicializar knownTotalRef al montar — fetch rápido del total global
  // sin filtros para tener la baseline incluso si el usuario entra con
  // filtros activos desde la URL.
  useEffect(() => {
    let active = true
    api.get('/api/leads?limit=1&offset=0')
      .then(res => {
        if (active && knownTotalRef.current === null) {
          knownTotalRef.current = res.data.total || 0
        }
      })
      .catch(() => { })
    return () => { active = false }
  }, [])

  // V070.63 — Polling cada 10s (antes 30s) para detectar leads nuevos.
  // El usuario reporto: lead llego a las 20:15, banner aparecio recien
  // 20:16. Patron patrón estándar/patrón estándar: notif de nuevos leads en lista
  // viva debe sentirse near-real-time (≤10s). Con 15 usuarios
  // concurrentes = 90 req/min — despreciable (el endpoint es ligero,
  // solo cuenta filas con LIMIT 1).
  //
  // Solo corre cuando la pestaña está visible — al volver de background
  // hace refresh inmediato gracias al handler de visibilitychange del
  // polling principal de arriba.
  //
  // El request usa el endpoint mas ligero posible: GET /api/leads con
  // limit=1 trae UNA fila pero devuelve el total global en el header
  // de la respuesta. Comparamos contra knownTotalRef para detectar diff.
  useEffect(() => {
    const interval = setInterval(async () => {
      if (document.visibilityState !== 'visible') return  // pause off-tab
      try {
        const res = await api.get('/api/leads?limit=1&offset=0')
        const serverTotal = res.data.total || 0
        if (knownTotalRef.current !== null && serverTotal > knownTotalRef.current) {
          setNewLeadsCount(serverTotal - knownTotalRef.current)
        }
      } catch { /* silencioso */ }
    }, 10_000)
    return () => clearInterval(interval)
  }, [])

  const handleRefreshNewLeads = async () => {
    setNewLeadsCount(0)
    fetchLeads()
    fetchCounts()
    // Resincronizar la baseline global para que el próximo polling
    // no vuelva a mostrar el banner con los mismos leads.
    try {
      const res = await api.get('/api/leads?limit=1&offset=0')
      knownTotalRef.current = res.data.total || 0
    } catch { /* silent */ }
  }

  useEffect(() => { setPage(1) }, [estadoFilter, filters])

  const handleEstadoChange = useCallback(async (leadId, estadoIdOrPayload) => {
    const isObj = typeof estadoIdOrPayload === 'object' && estadoIdOrPayload !== null
    const payload = isObj ? estadoIdOrPayload : { estado_id: estadoIdOrPayload }
    const estadoId = payload.estado_id
    const prevLeads = leads
    // Optimistic update
    setLeads(prev => prev.map(l => l.id === leadId ? {
      ...l,
      estado_id: estadoId,
      fecha_proxima_gestion: payload.fecha_proxima_gestion !== undefined ? payload.fecha_proxima_gestion : l.fecha_proxima_gestion,
      accion_proxima_gestion: payload.accion_proxima_gestion !== undefined ? payload.accion_proxima_gestion : l.accion_proxima_gestion,
      motivo_perdida: payload.motivo_perdida !== undefined ? payload.motivo_perdida : l.motivo_perdida,
      motivo_perdida_otro: payload.motivo_perdida_otro !== undefined ? payload.motivo_perdida_otro : l.motivo_perdida_otro,
      tipo_cierre: payload.tipo_cierre !== undefined ? payload.tipo_cierre : l.tipo_cierre,
      segunda_voz: payload.segunda_voz !== undefined ? payload.segunda_voz : l.segunda_voz,
    } : l))
    try {
      await api.patch(`/api/leads/${leadId}/estado`, payload)
      fetchCounts()
    } catch (err) {
      // Revertir si falla
      setLeads(prevLeads)
      throw err
    }
  }, [leads, fetchCounts])

  // V050: cambia la calidad del lead (frio/tibio/caliente). Optimistic update.
  // codigo puede ser null (limpia clasificacion) o uno del catalogo.
  const handleCalidadChange = useCallback(async (leadId, codigo) => {
    const prev = leads
    const cal = codigo ? calidades.find(c => (c.codigo || '').toUpperCase() === codigo.toUpperCase()) : null
    setLeads(p => p.map(l => l.id === leadId
      ? {
        ...l,
        calidad_codigo: codigo,
        calidad_nombre: cal?.nombre || null,
        calidad_color: cal?.color_hex || null,
      }
      : l))
    try {
      await api.patch(`/api/leads/${leadId}`, { calidad: codigo })
    } catch (err) {
      setLeads(prev)
      alert(err.response?.data?.detail || 'No se pudo actualizar la calidad.')
    }
  }, [leads, calidades])

  // V065: cambia la sede del lead. Optimistic update + rollback en error.
  // sedeId puede ser null (limpia la sede) o el uuid de una sede activa.
  const handleSedeChange = useCallback(async (leadId, sedeId) => {
    const prev = leads
    const sede = sedeId ? sedes.find(s => String(s.id) === String(sedeId)) : null
    setLeads(p => p.map(l => l.id === leadId
      ? {
        ...l,
        sede_id: sedeId,
        sede_codigo: sede?.codigo || null,
        sede_nombre: sede?.nombre || null,
        sede_color: sede?.color_hex || null,
      }
      : l))
    try {
      // Importante: PATCH /api/leads soporta sede_id=null para limpiar.
      // El backend acepta None explicito (V065/db91135).
      await api.patch(`/api/leads/${leadId}`, { sede_id: sedeId })
    } catch (err) {
      setLeads(prev)
      alert(err.response?.data?.detail || 'No se pudo actualizar la sede.')
    }
  }, [leads, sedes])

  const clearFilters = () => {
    setFilters(EMPTY_FILTERS)
    setEstadoFilter('')
    setSearchInput('')
    setSearch('')
    setPage(1)
  }

  const toggleLeadSelect = useCallback((id) => {
    setSelectedLeads(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }, [])

  // Selección como array de objetos completos: la BulkBar necesita conocer
  // qué leads ya tienen asesor para mostrar el desglose y exigir confirmación.
  const selectedRowsArray = useMemo(
    () => leads.filter(l => selectedLeads.has(l.id)),
    [leads, selectedLeads],
  )

  // Ejecuta la reasignación contra el endpoint bulk. Idempotente: el backend
  // ignora los que ya están en el destino. UAT v3.1: agregar resumen claro
  // post-asignación con cuántos cambiaron vs cuántos quedaron skipped (ya
  // estaban asignados al mismo asesor, o el supervisor no tenía permiso).
  const executeBulkReassign = async (toAsesorId) => {
    setIsBulkAssigning(true)
    try {
      const ids = [...selectedLeads]
        .map(id => parseInt(id, 10))
        .filter(n => Number.isInteger(n) && n > 0)
      if (!ids.length) throw new Error('No hay leads válidos seleccionados.')
      const isUnassign = toAsesorId === null || toAsesorId === '__unassigned__'
      const finalAsesorId = isUnassign ? null : toAsesorId
      const payload = { ids, asesor_id: finalAsesorId }
      const res = await api.patch('/api/leads/bulk/asesor', payload)
      const { changed = 0, skipped = 0 } = res.data || {}
      // V070.79 — notificar al Sidebar badge "Asignacion" en <500ms.
      if (changed > 0) fireAssignmentChanged()
      // Resumen del resultado en modal premium (antes window.alert).
      if (skipped > 0) {
        const reason = isUnassign
          ? 'algunos ya estaban sin asesor'
          : 'algunos ya estaban con ese asesor o no eran tuyos para reasignar'
        setInfoDialog({
          variant: changed > 0 ? 'warning' : 'info',
          title: isUnassign ? 'Desasignación parcial' : 'Reasignación parcial',
          message: [
            `${changed} lead${changed === 1 ? '' : 's'} ${isUnassign ? 'desasignado' : 'reasignado'}${changed === 1 ? '' : 's'}.`,
            `${skipped} omitido${skipped === 1 ? '' : 's'} — ${reason}.`,
          ],
        })
      } else if (changed > 0) {
        // Caso feliz: no abrimos modal, el refresh de la tabla ya
        // muestra el cambio. Evita interrumpir el flujo del usuario.
      } else {
        setInfoDialog({
          variant: 'info',
          title: 'Sin cambios',
          message: isUnassign
            ? 'Ningún lead se desasignó (es posible que ya estuvieran sin asignar).'
            : 'Ningún lead se reasignó. Verifica la selección.',
        })
      }
    } catch (err) {
      if (err instanceof Error && !err.response) {
        setInfoDialog({ variant: 'error', title: 'Error', message: err.message })
      } else {
        const detail = err.response?.data?.detail
        let msg = toAsesorId === null ? 'Error al desasignar los leads.' : 'Error al reasignar los leads.'
        if (typeof detail === 'string') msg = detail
        else if (Array.isArray(detail)) msg = detail.map(d => d.msg || JSON.stringify(d)).join(', ')
        else if (detail) msg = JSON.stringify(detail)
        setInfoDialog({ variant: 'error', title: toAsesorId === null ? 'Error al desasignar' : 'Error al reasignar', message: msg })
      }
    } finally {
      setSelectedLeads(new Set())
      setIsBulkAssigning(false)
      fetchLeads()
      fetchCounts()
    }
  }

  // La BulkBar nos invoca con el flag `needsConfirm` que ella misma calcula
  // (umbral, cruce de supervisores, o presencia de leads ya asignados). Aquí
  // solo decidimos si abrimos el modal o ejecutamos directo.
  const handleBulkReassign = (toAsesorId, opts = {}) => {
    if (selectedLeads.size === 0 || toAsesorId === undefined || toAsesorId === '') return
    const isUnassign = toAsesorId === null || opts.isUnassign
    if (opts.needsConfirm) {
      const asesor = !isUnassign ? asesores.find(a => a.id === toAsesorId) : null
      setPendingReassign({
        toAsesorId,
        breakdown: opts.breakdown || {},
        count: selectedLeads.size,
        isUnassign,
        asesorNombre: isUnassign
          ? 'Sin asignar'
          : (asesor?.nombre_completo || asesor?.email || '—'),
      })
      return
    }
    executeBulkReassign(toAsesorId)
  }

  const handleConfirmReassign = () => {
    if (!pendingReassign) return
    const { toAsesorId } = pendingReassign
    setPendingReassign(null)
    executeBulkReassign(toAsesorId)
  }

  const handleBulkRevertTmk = () => {
    const recycledRows = selectedRowsArray.filter(r =>
      r.es_reciclado ||
      r.lote_reciclaje_id ||
      (r.origen_reciclaje && String(r.origen_reciclaje).toLowerCase().includes('tmk')) ||
      (r.fuente_nombre && String(r.fuente_nombre).toLowerCase().includes('bolsa tmk'))
    )
    if (!recycledRows.length) return
    setConfirmBulkRevertTmk({
      count: recycledRows.length,
      ids: recycledRows.map(r => r.id),
    })
  }

  const handleConfirmRevertTmk = async () => {
    if (!confirmBulkRevertTmk) return
    const { ids } = confirmBulkRevertTmk
    setConfirmBulkRevertTmk(null)
    setIsBulkRevertingTmk(true)
    try {
      const res = await api.post('/api/tmk/revertir', { ids })
      setInfoDialog({
        variant: 'success',
        title: 'Reversión exitosa',
        message: res.data?.message || `Se revirtieron ${ids.length} lead(s) correctamente a su asignación previa.`,
      })
      setSelectedLeads(new Set())
      fireAssignmentChanged()
      fetchLeads()
      fetchCounts()
    } catch (err) {
      setInfoDialog({
        variant: 'error',
        title: 'Error al revertir TMK',
        message: err.response?.data?.detail || 'No se pudo revertir la asignación de TMK.',
      })
    } finally {
      setIsBulkRevertingTmk(false)
    }
  }

  const handleBulkDevolverHistoricos = () => {
    const historicosRows = selectedRowsArray.filter(r =>
      r.es_historico ||
      (r.fuente_nombre && String(r.fuente_nombre).toLowerCase().includes('hist')) ||
      (r.origen && String(r.origen).toLowerCase().includes('hist'))
    )
    if (!historicosRows.length) return
    setConfirmBulkDevolverHistoricos({
      count: historicosRows.length,
      ids: historicosRows.map(r => r.id),
    })
  }

  const handleConfirmDevolverHistoricos = async () => {
    if (!confirmBulkDevolverHistoricos) return
    const { ids } = confirmBulkDevolverHistoricos
    setConfirmBulkDevolverHistoricos(null)
    setIsBulkDevolviendoHistoricos(true)
    try {
      const res = await api.post('/api/historicos/devolver-leads', { lead_ids: ids })
      setInfoDialog({
        variant: 'success',
        title: 'Devolución a Históricos exitosa',
        message: res.data?.message || `Se devolvieron ${ids.length} lead(s) a Históricos correctamente. Se quitaron sus asesores/supervisores y salieron de la lista activa.`,
      })
      setSelectedLeads(new Set())
      fireAssignmentChanged()
      fetchLeads()
      fetchCounts()
    } catch (err) {
      setInfoDialog({
        variant: 'error',
        title: 'Error al devolver a Históricos',
        message: err.response?.data?.detail || 'No se pudieron devolver los leads a Históricos.',
      })
    } finally {
      setIsBulkDevolviendoHistoricos(false)
    }
  }

  // Cambio masivo de estado — una sola request al endpoint bulk
  // (transaccional, auditado y con filtro de rol server-side).
  const executeBulkEstadoChange = async (estadoId) => {
    setIsBulkChangingEstado(true)
    try {
      const ids = [...selectedLeads]
        .map(id => parseInt(id, 10))
        .filter(n => Number.isInteger(n) && n > 0)
      const estadoIdInt = parseInt(estadoId, 10)
      if (!ids.length) throw new Error('No hay leads válidos seleccionados.')
      if (!Number.isInteger(estadoIdInt) || estadoIdInt <= 0)
        throw new Error('Estado inválido.')
      await api.patch('/api/leads/bulk/estado', { ids, estado_id: estadoIdInt })
    } catch (err) {
      if (err instanceof Error && !err.response) {
        setInfoDialog({ variant: 'error', title: 'Error', message: err.message })
      } else {
        const detail = err.response?.data?.detail
        let msg = 'Error al cambiar el estado.'
        if (typeof detail === 'string') msg = detail
        else if (Array.isArray(detail)) msg = detail.map(d => d.msg || JSON.stringify(d)).join(', ')
        else if (detail) msg = JSON.stringify(detail)
        setInfoDialog({ variant: 'error', title: 'Error al cambiar estado', message: msg })
      }
    } finally {
      setSelectedLeads(new Set())
      setIsBulkChangingEstado(false)
      fetchLeads()
      fetchCounts()
    }
  }

  const handleBulkEstadoChange = (estadoId, opts = {}) => {
    if (selectedLeads.size === 0 || !estadoId) return
    if (opts.needsConfirm) {
      setPendingEstadoChange({
        estadoId,
        estadoNombre: opts.estadoNombre || '',
        count: selectedLeads.size,
      })
      return
    }
    executeBulkEstadoChange(estadoId)
  }

  const handleConfirmEstadoChange = () => {
    if (!pendingEstadoChange) return
    const { estadoId } = pendingEstadoChange
    setPendingEstadoChange(null)
    executeBulkEstadoChange(estadoId)
  }

  // Cambio masivo de fuente (solo admin)
  const executeBulkFuenteChange = async (fuenteId) => {
    setIsBulkChangingFuente(true)
    try {
      const ids = [...selectedLeads]
        .map(id => parseInt(id, 10))
        .filter(n => Number.isInteger(n) && n > 0)
      const fuenteIdInt = parseInt(fuenteId, 10)
      if (!ids.length) throw new Error('No hay leads válidos seleccionados.')
      if (!Number.isInteger(fuenteIdInt) || fuenteIdInt <= 0)
        throw new Error('Fuente inválida.')
      await api.patch('/api/leads/bulk/fuente', { ids, fuente_id: fuenteIdInt })
    } catch (err) {
      if (err instanceof Error && !err.response) {
        setInfoDialog({ variant: 'error', title: 'Error', message: err.message })
      } else {
        const detail = err.response?.data?.detail
        let msg = 'Error al cambiar la fuente.'
        if (typeof detail === 'string') msg = detail
        else if (Array.isArray(detail)) msg = detail.map(d => d.msg || JSON.stringify(d)).join(', ')
        else if (detail) msg = JSON.stringify(detail)
        setInfoDialog({ variant: 'error', title: 'Error al cambiar fuente', message: msg })
      }
    } finally {
      setSelectedLeads(new Set())
      setIsBulkChangingFuente(false)
      fetchLeads()
      fetchCounts()
    }
  }

  const handleBulkFuenteChange = (fuenteId, opts = {}) => {
    if (selectedLeads.size === 0 || !fuenteId) return
    if (opts.needsConfirm) {
      setPendingFuenteChange({
        fuenteId,
        fuenteNombre: opts.fuenteNombre || '',
        count: selectedLeads.size,
      })
      return
    }
    executeBulkFuenteChange(fuenteId)
  }

  const handleConfirmFuenteChange = () => {
    if (!pendingFuenteChange) return
    const { fuenteId } = pendingFuenteChange
    setPendingFuenteChange(null)
    executeBulkFuenteChange(fuenteId)
  }

  const handleBulkDeleteConfirm = async () => {
    setConfirmBulkDelete(false)
    setIsBulkDeleting(true)
    try {
      await api.delete('/api/leads/bulk', { data: { ids: [...selectedLeads].map(Number).filter(n => Number.isInteger(n) && n > 0) } })
      setSelectedLeads(new Set())
      // V070.79 — eliminar leads sin asesor afecta el badge del Sidebar.
      fireAssignmentChanged()
      fetchLeads()
      fetchCounts()
    } catch (err) {
      setInfoDialog({
        variant: 'error',
        title: 'Error al eliminar',
        message: err.response?.data?.detail || 'Error al eliminar los leads.',
      })
    } finally {
      setIsBulkDeleting(false)
    }
  }

  // Headers dinámicos: filtra por columnas visibles + checkbox para admin/supervisor
  const headers = useMemo(() => {
    const filtered = BASE_HEADERS.filter(h =>
      !TOGGLEABLE_KEYS.includes(h.key) || visibleCols.has(h.key)
    )
    if (!canAssign) return filtered
    const selectHeader = {
      key: '_select',
      label: (
        <input
          type="checkbox"
          checked={leads.length > 0 && selectedLeads.size === leads.length}
          onChange={() => {
            setSelectedLeads(prev =>
              prev.size === leads.length ? new Set() : new Set(leads.map(l => l.id))
            )
          }}
          className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
        />
      ),
      className: 'w-10',
    }
    return [selectHeader, ...filtered]
  }, [canAssign, leads, selectedLeads, visibleCols])

  // Umbral de confirmacion amigable: por encima de esto pedimos al usuario
  // que confirme antes de lanzar la descarga. No es un hard limit (el hard
  // limit de 10k lo aplica el backend), solo fricción para evitar clicks
  // accidentales sobre filtros amplios.
  const EXPORT_CONFIRM_THRESHOLD = 2000

  // Lanza realmente la descarga. Separado de handleExport para poder ser
  // invocado tanto desde el click directo (cuando el total es pequeño) como
  // desde la confirmación del modal.
  const executeExport = async () => {
    setIsExporting(true)
    try {
      const params = new URLSearchParams()
      if (search) params.set('search', search)
      if (estadoFilter) params.set('estado_id', estadoFilter)
      if (filters.origen) params.set('origen', filters.origen)
      if (filters.fuente_id) params.set('fuente_id', filters.fuente_id)
      if (filters.asesor_id) params.set('asesor_id', filters.asesor_id)
      if (filters.supervisor_id) params.set('supervisor_id', filters.supervisor_id)
      if (filters.api_client_id) params.set('api_client_id', filters.api_client_id)
      if (filters.campana) params.set('campana', filters.campana)
      if (filters.fecha_desde) params.set('fecha_desde', filters.fecha_desde)
      if (filters.fecha_hasta) params.set('fecha_hasta', filters.fecha_hasta)
      if (filters.fecha_asig_desde) params.set('fecha_asig_desde', filters.fecha_asig_desde)
      if (filters.fecha_asig_hasta) params.set('fecha_asig_hasta', filters.fecha_asig_hasta)
      if (filters.fecha_actividad_desde) params.set('fecha_actividad_desde', filters.fecha_actividad_desde)
      if (filters.fecha_actividad_hasta) params.set('fecha_actividad_hasta', filters.fecha_actividad_hasta)
      if (filters.con_antecedentes) params.set('con_antecedentes', 'true')
      if (filters.calidad) params.set('calidad', filters.calidad)
      if (filters.recontacto_campana) params.set('recontacto_campana', filters.recontacto_campana)
      if (filters.recontacto_anuncio) params.set('recontacto_anuncio', filters.recontacto_anuncio)
      if (filters.recontacto_conjunto) params.set('recontacto_conjunto', filters.recontacto_conjunto)
      if (filters.recontacto_fuente_id) params.set('recontacto_fuente_id', filters.recontacto_fuente_id)
      if (filters.recontacto_desde) params.set('recontacto_desde', filters.recontacto_desde)
      if (filters.recontacto_hasta) params.set('recontacto_hasta', filters.recontacto_hasta)
      if (filters.recontacto_api_client_id) params.set('recontacto_api_client_id', filters.recontacto_api_client_id)
      if (filters.tocado_por_api_client_id) params.set('tocado_por_api_client_id', filters.tocado_por_api_client_id)
      // V094 — re-engagement workflow filters
      if (filters.recontacto_sin_atender) params.set('recontacto_sin_atender', 'true')
      if (filters.recontacto_recientes_horas) params.set('recontacto_recientes_horas', String(filters.recontacto_recientes_horas))
      if (filters.estado_cola) params.set('estado_cola', filters.estado_cola)
      if (filters.filtro_alerta) params.set('filtro_alerta', filters.filtro_alerta)
      if (filters.ficha_tecnica_estado) params.set('ficha_tecnica_estado', filters.ficha_tecnica_estado)
      params.set('limit', 5000)
      params.set('offset', 0)

      const res = await api.get(`/api/leads/exportar?${params.toString()}`, { responseType: 'blob' })
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = `leads_${new Date().toISOString().slice(0, 10)}.xlsx`
      a.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      // El backend aplica rate limit (3/5min). Cuando se excede devuelve
      // 429 — mostramos un mensaje claro en vez de fallar en silencio.
      if (err?.response?.status === 429) {
        setInfoDialog({
          variant: 'warning',
          title: 'Límite de descargas alcanzado',
          message: 'Has alcanzado el límite de descargas (3 cada 5 minutos). Espera unos minutos antes de intentar de nuevo.',
        })
      }
      /* otros fallos: se reinicia el estado en finally */
    }
    finally { setIsExporting(false) }
  }

  // Punto de entrada del botón "Excel". Si el total filtrado es grande,
  // abrimos el modal de confirmación; si no, descargamos directo.
  const handleExport = () => {
    if (total > EXPORT_CONFIRM_THRESHOLD) {
      setPendingExport({ count: total })
      return
    }
    executeExport()
  }

  const handleConfirmExport = () => {
    setPendingExport(null)
    executeExport()
  }

  const extraFilterCount = Object.values(filters).filter(Boolean).length
  const totalPages = Math.ceil(total / PAGE_SIZE)

  const renderCell = (row, key) => {
    switch (key) {
      case 'nombre_completo': {
        const nombre = [row.nombres, row.apellidos].filter(Boolean).join(' ') || '—'
        const fichaStats = getFichaTecnicaStats(row.ficha_tecnica)
        return (
          <div className="pii-cell">
            <div className="flex items-center gap-1.5 flex-wrap">
              <p className="font-medium text-gray-900 leading-tight">{nombre}</p>
              {!fichaStats.isComplete ? (
                <span
                  className="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-bold bg-amber-50 text-amber-800 dark:bg-amber-950/60 dark:text-amber-200 border border-amber-300 dark:border-amber-800/60 cursor-help"
                  title={
                    fichaStats.completedCount === 0
                      ? `Ficha técnica pendiente: 0/${fichaStats.total} preguntas completadas`
                      : `Ficha técnica incompleta: ${fichaStats.completedCount}/${fichaStats.total} preguntas completadas`
                  }
                >
                  📋 Ficha {fichaStats.completedCount > 0 ? `${fichaStats.completedCount}/${fichaStats.total}` : 'pendiente'}
                </span>
              ) : (
                <span
                  className="inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-medium bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-800/50"
                  title={`Ficha técnica completa (${fichaStats.total}/${fichaStats.total} preguntas respondidas)`}
                >
                  ✓ Ficha
                </span>
              )}
              {row.is_urgente_48h && (
                <span
                  className="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-bold bg-red-100 text-red-700 dark:bg-red-950/60 dark:text-red-300 border border-red-200 dark:border-red-900/50"
                  title="Lead urgente: más de 48 horas sin ninguna llamada ni contacto registrado"
                >
                  🚨 +48h sin llamada
                </span>
              )}
              {row.is_sla_15m_vencido && !row.is_urgente_48h && (
                <span
                  className="inline-flex items-center gap-1 rounded-full px-1.5 py-0.5 text-[10px] font-bold bg-rose-100 text-rose-700 dark:bg-rose-950/60 dark:text-rose-300 border border-rose-200 dark:border-rose-900/50"
                  title="SLA Vencido: esperando primera llamada/contacto (>15 min hábiles)"
                >
                  ⏱️ SLA Vencido
                </span>
              )}
              {row.es_recontacto && (
                <span
                  className="inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium bg-amber-50 text-amber-700 border border-amber-200"
                  title="Este cliente ya figura en el histórico del sistema anterior o fue lead previamente."
                >
                  Antec.
                </span>
              )}
              {row.total_recontactos > 0 && (
                <span
                  className="inline-flex items-center gap-0.5 rounded-full px-1.5 py-0.5 text-[10px] font-medium bg-violet-50 text-violet-700 border border-violet-200 cursor-help"
                  title={(() => {
                    // V068.4 — tooltip con detalle: muestra cuantas veces y
                    // cuando fue el ultimo recontacto para que el asesor
                    // pueda verificar visualmente que el conteo es real.
                    const n = row.total_recontactos
                    const ultimo = row.ultimo_recontacto_at
                      ? new Date(row.ultimo_recontacto_at).toLocaleDateString('es-PE',
                        { day: '2-digit', month: '2-digit', year: '2-digit' })
                      : null
                    return [
                      `Reactivaciones reales: ${n}.`,
                      ultimo ? `Último: ${ultimo}.` : null,
                      `Cuenta solo cuando el cliente llena el formulario en un día distinto al de su creación.`,
                    ].filter(Boolean).join('\n')
                  })()}
                >
                  ↻ {row.total_recontactos > 9 ? '9+' : row.total_recontactos}
                </span>
              )}
            </div>
            {row.email && <p className="text-xs text-gray-400 mt-0.5 truncate max-w-[180px]">{row.email}</p>}
          </div>
        )
      }
      case 'telefono': {
        if (!row.telefono) return <span className="text-gray-400">—</span>
        return (
          <div className="pii-cell">
            <span className="font-mono text-sm">{row.telefono}</span>
          </div>
        )
      }
      case 'origen': {
        const fuenteName = (row.fuente_nombre || row.fuente || '').trim().toLowerCase()
        const apiSlug = (row.api_client_legacy_slug || '').toLowerCase()
        const apiNombre = (row.api_client_legacy_nombre || '').toLowerCase()
        const formStr = (row.form_nombre || row.form_id || '').toLowerCase()
        const campStr = (row.campana_nombre || row.campana || '').toLowerCase()
        const extId = String(row.fuente_externa_id || '').trim()
        const formId = String(row.form_id || '').trim()
        const campId = String(row.campana || '').trim()

        const allLeadData = [
          fuenteName,
          row.fuente,
          apiNombre,
          apiSlug,
          campStr,
          formStr,
          row.campana,
          row.campana_nombre,
          row.form_id,
          row.form_nombre,
          row.fuente_externa_id,
          row.anuncio,
          row.conjunto,
        ].filter(Boolean).join(' ').toLowerCase()

        // Rastro técnico de ingesta por API/Webhook
        const hasExternalId = Boolean(row.fuente_externa_id)
        const hasFormId = Boolean(row.form_id)
        const isVerifiedAPI = hasExternalId || hasFormId || Boolean(row.api_client_id)

        const tooltipTrace = [
          isVerifiedAPI ? '✓ Lead Verificado por API / Webhook' : 'Lead registrado manualmente / genérico',
          row.fuente_externa_id ? `ID Lead (Meta/TikTok): ${row.fuente_externa_id}` : null,
          row.form_nombre || row.form_id ? `Formulario: ${row.form_nombre || row.form_id}` : null,
          row.campana_nombre || row.campana ? `Campaña: ${row.campana_nombre || row.campana}` : null,
        ].filter(Boolean).join('\n')

        // 0. Histórico: lead proveniente de la base histórica de clientes
        const isHistorico = Boolean(row.es_historico) || fuenteName === 'historico' || fuenteName === 'histórico'

        // 0.1 Bolsa TMK: lead proveniente o reasignado desde la bolsa de reciclaje TMK
        const isBolsaTmk = (
          fuenteName === 'bolsa tmk' ||
          fuenteName === 'bolsa de reciclaje tmk' ||
          fuenteName === 'reciclaje tmk' ||
          fuenteName === 'tmk' ||
          (row.origen_reciclaje && String(row.origen_reciclaje).toLowerCase().includes('bolsa tmk')) ||
          (Boolean(row.es_reciclado) && (row.origen_reciclaje || '').toLowerCase().includes('tmk'))
        )

        // 1. Meta / Facebook: detecta por prefijo 1202..., 12..., perfilado, virtual ii, agosto 1 o firmas de Facebook/Meta
        const isMeta = (
          !isHistorico && !isBolsaTmk && (
            campId.startsWith('1202') ||
            formId.startsWith('1202') ||
            extId.startsWith('1202') ||
            campId.startsWith('12') ||
            campStr.includes('perfilado') ||
            campStr.includes('virtual ii') ||
            campStr.includes('agosto 1') ||
            (campStr.includes('campaña presencial') && !campStr.includes('sur')) ||
            allLeadData.includes('facebook') ||
            allLeadData.includes('fb') ||
            allLeadData.includes('meta') ||
            apiSlug === 'meta' ||
            apiSlug === 'facebook' ||
            Boolean(row.leadgen_id)
          )
        )
        const isFacebook = isMeta

        // 2. TikTok: detecta por firmas específicas de TikTok (campañas 1870..., 1851..., formularios 75..., o mención a tiktok/tt)
        const isTikTok = (
          !isHistorico && !isBolsaTmk && !isMeta && (
            campId.startsWith('1870') ||
            campId.startsWith('1851') ||
            campId.startsWith('75') ||
            formId.startsWith('75') ||
            campStr.includes('presencial campaña sur') ||
            campStr.includes('virtual 3') ||
            allLeadData.includes('1870980440674690') ||
            allLeadData.includes('1851867757416658') ||
            allLeadData.includes('7597158266313146641') ||
            allLeadData.includes('7579679801816940817') ||
            allLeadData.includes('tiktok') ||
            allLeadData.includes('tt mensaje') ||
            allLeadData.includes('tt') ||
            /\b75\d{16,18}\b/.test(allLeadData) ||
            apiSlug === 'tiktok'
          )
        )

        // 3. Instagram: detecta por fuente, slug o mención a IG
        const isInstagram = (
          !isHistorico && !isBolsaTmk && !isMeta && !isTikTok && (
            allLeadData.includes('instagram') ||
            allLeadData.includes('ig') ||
            apiSlug === 'instagram'
          )
        )

        // 4. WhatsApp: detecta por fuente, canal, slug o número WhatsApp real (ignora texto de observaciones)
        const isWhatsApp = (
          !isHistorico && !isBolsaTmk && !isMeta && !isTikTok && !isInstagram && (
            allLeadData.includes('whatsapp') ||
            /\bwa\b/.test(allLeadData) ||
            Boolean(row.origen_wa_numero) ||
            apiSlug === 'whatsapp'
          )
        )

        if (isHistorico) {
          return (
            <span
              className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-indigo-50 text-indigo-700 border border-indigo-200 shadow-2xs cursor-help"
              title={tooltipTrace || 'Lead originado desde Histórico'}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-indigo-500"></span>
              Histórico
            </span>
          )
        }
        if (isBolsaTmk) {
          return (
            <span
              className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-rose-50 text-rose-700 border border-rose-200 shadow-2xs cursor-help"
              title={tooltipTrace || (row.origen_reciclaje ? `Reciclado TMK: ${row.origen_reciclaje}` : 'Lead proveniente de Bolsa TMK')}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-rose-500"></span>
              Bolsa TMK
            </span>
          )
        }
        if (isTikTok) {
          return (
            <span
              className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-bold bg-gray-900 text-white border border-gray-700 shadow-2xs cursor-help"
              title={tooltipTrace}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-cyan-400 animate-pulse"></span>
              TikTok
            </span>
          )
        }
        if (isInstagram) {
          return (
            <span
              className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-gradient-to-r from-pink-50 to-purple-50 text-pink-700 border border-pink-200 cursor-help"
              title={tooltipTrace}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-pink-500"></span>
              Instagram
            </span>
          )
        }
        if (isFacebook) {
          return (
            <span
              className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-blue-50 text-blue-700 border border-blue-200 cursor-help"
              title={tooltipTrace}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-blue-600"></span>
              Facebook
            </span>
          )
        }
        if (isWhatsApp) {
          return (
            <span
              className="inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200 cursor-help"
              title={tooltipTrace}
            >
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
              WhatsApp
            </span>
          )
        }
        if (row.fuente_nombre) {
          return (
            <span
              className="inline-flex items-center gap-1 text-xs font-medium text-gray-700 bg-gray-100 px-2 py-0.5 rounded-full border border-gray-200 capitalize cursor-help"
              title={tooltipTrace}
            >
              {row.fuente_nombre}
            </span>
          )
        }
        return <span className="text-gray-400 text-xs italic">—</span>
      }
      case 'fuente_nombre':
        return row.fuente_nombre
          ? <Badge variant="secondary" className="capitalize text-xs">{row.fuente_nombre}</Badge>
          : <span className="text-gray-400">—</span>
      case 'campana': {
        // Muestra el nombre resuelto (Graph API cache) y el ID crudo debajo
        // — los asesores leen el nombre, marketing sigue pudiendo copiar el
        // ID para reportes externos. Si aún no hay nombre cacheado, cae al ID.
        if (!row.campana) return <span className="text-gray-400">—</span>
        const tooltip = row.campana_nombre
          ? `${row.campana_nombre}\nID: ${row.campana}`
          : row.campana
        return (
          <div className="leading-tight max-w-[160px]" title={tooltip}>
            <span className="text-xs font-medium text-gray-800 truncate block">
              {row.campana_nombre || row.campana}
            </span>
            {row.campana_nombre && (
              <span className="text-[10px] text-gray-400 font-mono truncate block">
                {row.campana}
              </span>
            )}
          </div>
        )
      }
      case 'form_nombre':
        return (row.form_nombre || row.form_id)
          ? (
            <div className="leading-tight max-w-[160px]" title={row.form_nombre || row.form_id}>
              <span className="text-xs text-gray-700 truncate block">
                {row.form_nombre || row.form_id}
              </span>
              {row.form_nombre && row.form_id && (
                <span className="text-[10px] text-gray-400 font-mono truncate block">
                  {row.form_id}
                </span>
              )}
            </div>
          )
          : <span className="text-gray-400">—</span>
      case 'estado_id':
        return (
          <EstadoDropdown
            lead={row}
            estados={estados}
            onChangeEstado={handleEstadoChange}
            onOpenCambioEstadoModal={(l, target) => setCambioEstadoModal({ open: true, lead: l, targetEstado: target })}
          />
        )
      case 'calidad':
        return (
          <CalidadDropdown
            lead={row}
            calidades={calidades}
            onChangeCalidad={handleCalidadChange}
          />
        )
      case 'ficha_tecnica': {
        const stats = getFichaTecnicaStats(row.ficha_tecnica)
        if (stats.isComplete) {
          return (
            <span
              className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200"
              title={`Ficha técnica completada (${stats.total}/${stats.total})`}
            >
              ✓ Completa ({stats.total}/{stats.total})
            </span>
          )
        }
        if (stats.completedCount > 0) {
          return (
            <span
              className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-800 border border-amber-300"
              title={`Ficha técnica incompleta: ${stats.completedCount} de ${stats.total} preguntas`}
            >
              ⚠️ Incompleta ({stats.completedCount}/{stats.total})
            </span>
          )
        }
        return (
          <span
            className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-50 text-amber-700 border border-amber-200"
            title={`Ficha técnica sin rellenar (0/${stats.total})`}
          >
            ⚠️ Pendiente (0/{stats.total})
          </span>
        )
      }
      case 'intentos_contacto': {
        const n = row.intentos_contacto || 0
        return (
          <span
            className={`inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold ${n > 0 ? 'bg-indigo-100 text-indigo-700' : 'bg-gray-100 text-gray-400'
              }`}
            title={`${n} intento${n !== 1 ? 's' : ''} de contacto`}
          >
            {n}
          </span>
        )
      }
      case 'asesor_nombre': {
        // V041.2: si el "asesor" es en realidad un supervisor, el lead esta
        // en SU cola — el supervisor todavia no lo delego a un asesor real.
        // Renderizamos como "En cola · Diego" en vez de solo "Diego" para
        // que se vea claro que el lead aun necesita gestion humana.
        const isSupervisorAsesor = row.asesor_role === 'supervisor'
        // V091.1 — Badge "Heredado de X" PERMANENTE hasta próxima reasignación.
        // Cuando Paola reasigna el lead a otro asesor, reassigned_at se actualiza
        // y el badge cambia para reflejar la transferencia más reciente. Una sola
        // fuente de verdad — sin lógica de tiempo arbitraria.
        const inheritedBadge = (() => {
          if (!row.reassigned_at || !row.previous_asesor_nombre) return null
          const reassignedMs = new Date(row.reassigned_at).getTime()
          if (Number.isNaN(reassignedMs)) return null
          const diasDesde = (Date.now() - reassignedMs) / 86400000
          // Label adaptativo: días → meses → años. Tooltip con fecha exacta
          // para auditoría rápida.
          const diasLabel = diasDesde < 1
            ? 'hoy'
            : diasDesde < 2
              ? 'ayer'
              : diasDesde < 30
                ? `hace ${Math.floor(diasDesde)} días`
                : diasDesde < 365
                  ? `hace ${Math.floor(diasDesde / 30)} ${Math.floor(diasDesde / 30) === 1 ? 'mes' : 'meses'}`
                  : `hace ${Math.floor(diasDesde / 365)} ${Math.floor(diasDesde / 365) === 1 ? 'año' : 'años'}`
          const fechaIso = new Date(reassignedMs).toLocaleDateString('es-PE', {
            day: '2-digit', month: '2-digit', year: 'numeric',
          })
          return (
            <span
              className="inline-flex items-center gap-1 mt-0.5 text-[10px] italic text-violet-700 bg-violet-50 border border-violet-200 rounded px-1.5 py-0.5"
              title={`Heredado de ${row.previous_asesor_nombre} el ${fechaIso} (${diasLabel}). El badge se actualiza solo cuando el lead se vuelva a reasignar.`}
            >
              ↪ Heredado de {row.previous_asesor_nombre} · {diasLabel}
            </span>
          )
        })()
        const respaldoSupervisionBadge = row.is_respaldo_supervision ? (
          <span
            className="inline-flex items-center gap-1 mt-0.5 text-[10px] font-medium text-emerald-800 bg-emerald-50 border border-emerald-200 rounded px-1.5 py-0.5"
            title="Respaldo de supervisión: Venta histórica conservada para la supervisión tras la salida o reasignación del asesor."
          >
            🛡️ Respaldo supervisión
          </span>
        ) : null
        if (row.asesor_nombre && !isSupervisorAsesor) {
          return (
            <div className="flex flex-col items-start">
              <span className="text-sm text-gray-700 pii-cell">{row.asesor_nombre}</span>
              {respaldoSupervisionBadge}
              {inheritedBadge}
            </div>
          )
        }
        // En cola: lead asignado a un supervisor (cola directa, V041) o
        // sin asesor pero con supervisor_id (cola V035).
        const queueName = isSupervisorAsesor ? row.asesor_nombre : row.supervisor_nombre
        if (queueName) {
          const stale = row.cola_estancada
          return (
            <div className="flex flex-col items-start">
              <span
                className={
                  'inline-flex items-center gap-1 text-xs italic px-2 py-0.5 rounded-full ' +
                  (stale
                    ? 'bg-amber-100 text-amber-800'
                    : 'bg-gray-100 text-gray-600')
                }
                title={
                  (stale
                    ? 'Más de 24h pendiente sin asignar. '
                    : 'Pendiente de asignación al asesor. ') +
                  `Supervisor: ${queueName}`
                }
              >
                {stale ? '⚠ Estancado' : 'Pendiente'} · {queueName}
              </span>
              {respaldoSupervisionBadge}
              {inheritedBadge}
            </div>
          )
        }
        // Sin asignar: igual mostramos el badge "heredado" si aplica,
        // porque es justo el caso típico tras una reasignación a "unassign".
        if (inheritedBadge) {
          return (
            <div className="flex flex-col items-start">
              <span className="text-gray-400 text-xs italic">Sin asignar</span>
              {inheritedBadge}
            </div>
          )
        }
        return <span className="text-gray-400 text-xs italic">Sin asignar</span>
      }
      case 'supervisor_nombre':
      case 'supervisor_jefe_nombre':
        return (row.supervisor_nombre || row.supervisor_jefe_nombre) ? (
          <span className="inline-flex items-center text-xs font-semibold text-purple-800 bg-purple-100/80 border border-purple-200 px-2 py-0.5 rounded-full truncate max-w-[150px]">
            {row.supervisor_nombre || row.supervisor_jefe_nombre}
          </span>
        ) : (
          <span className="text-gray-400 text-xs italic">—</span>
        )
      case 'fecha_ingreso':
        return <DateCell iso={row.fecha_ingreso} />
      case 'fecha_asignacion':
        return <DateCell iso={row.fecha_asignacion} />
      case 'fecha_primer_contacto':
        return <DateCell iso={row.fecha_primer_contacto} />
      case 'fecha_ultimo_contacto':
        return <DateCell iso={row.fecha_ultimo_contacto} />
      case 'ultima_actividad':
        return <DateCell iso={row.ultima_actividad} />
      case 'fecha_proxima_gestion': {
        const rawDate = row.fecha_proxima_gestion || row.fecha_cita
        if (!rawDate) return <span className="text-gray-400">—</span>
        const parts = formatDateParts(rawDate)
        if (!parts) return <span className="text-gray-400">—</span>

        const d = new Date(rawDate)
        const now = new Date()
        const diffMinutes = (d.getTime() - now.getTime()) / 60000
        const isImminent = diffMinutes > 0 && diffMinutes <= 60
        const isOverdue = diffMinutes <= 0 && diffMinutes >= -120
        const isCita = Boolean(row.fecha_cita && !row.fecha_proxima_gestion)

        return (
          <div className="flex flex-col gap-0.5">
            <span
              className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded font-medium ${isImminent
                ? 'bg-amber-50 text-amber-800 border border-amber-300 font-semibold'
                : isOverdue
                  ? 'bg-rose-50 text-rose-700 border border-rose-200'
                  : isCita
                    ? 'bg-indigo-50 text-indigo-700 border border-indigo-200'
                    : 'bg-blue-50 text-blue-700 border border-blue-200'
                }`}
              title={
                row.accion_proxima_gestion
                  ? `Acción: ${row.accion_proxima_gestion} — ${parts.date} ${parts.time}`
                  : row.fecha_cita
                    ? `Cita agendada: ${parts.date} ${parts.time}`
                    : isImminent
                      ? `Acción inminente en ~${Math.round(diffMinutes)} minutos`
                      : isOverdue
                        ? `Acción vencida hace ${Math.abs(Math.round(diffMinutes))} minutos`
                        : `Próxima gestión: ${parts.date} ${parts.time}`
              }
            >
              <Clock size={11} className={isImminent ? 'text-amber-600 animate-pulse' : ''} />
              <span>{parts.date} {parts.time}</span>
            </span>
            {row.accion_proxima_gestion && (
              <span className="text-[10px] text-purple-700 dark:text-purple-300 font-medium truncate max-w-[140px]" title={row.accion_proxima_gestion}>
                {row.accion_proxima_gestion}
              </span>
            )}
            {!row.accion_proxima_gestion && row.cita_estado_nombre && (
              <span className="text-[10px] text-gray-500 font-medium truncate max-w-[140px]" title={`Estado de cita: ${row.cita_estado_nombre}`}>
                {row.cita_estado_nombre}
              </span>
            )}
          </div>
        )
      }
      case 'fecha_ultimo_recontacto': {
        // V093 — visibilidad de recontactos sin tener que filtrar manualmente.
        // Si el lead fue recontactado, mostramos la fecha + indicador "Recontacto"
        // amarillo. Si no, el habitual "—".
        if (!row.fecha_ultimo_recontacto) {
          return <span className="text-gray-400">—</span>
        }
        const daysAgo = Math.floor((Date.now() - new Date(row.fecha_ultimo_recontacto).getTime()) / 86400000)
        const recent = daysAgo <= 7
        return (
          <div className="flex flex-col gap-0.5">
            <DateCell iso={row.fecha_ultimo_recontacto} />
            <span
              className={`inline-flex items-center gap-0.5 text-[10px] font-semibold ${recent ? 'text-amber-700' : 'text-gray-500'
                }`}
              title={`Recontactado hace ${daysAgo} día${daysAgo !== 1 ? 's' : ''}`}
            >
              {recent ? '🔥 Recontacto' : '↻ Recontacto'}
            </span>
          </div>
        )
      }
      case 'proveedor': {
        // V062: una sola columna con dos estados visuales. Activo (verde,
        // icono enchufe) tiene precedencia sobre legacy (ambar, icono
        // archivo). Si no hay nada, "—".
        if (row.api_client_id) {
          const name = apiClientNameById.get(row.api_client_id)
            || `${row.api_client_id.slice(0, 8)}…`
          return (
            <span
              className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200 max-w-[140px]"
              title={`Proveedor activo: ${name}`}
            >
              <Plug size={10} className="shrink-0" />
              <span className="truncate">{name}</span>
            </span>
          )
        }
        if (row.api_client_legacy_nombre || row.api_client_legacy_slug) {
          const name = row.api_client_legacy_nombre || row.api_client_legacy_slug
          return (
            <span
              className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200 max-w-[140px]"
              title="Proveedor desvinculado — snapshot preservado para trazabilidad"
            >
              <Archive size={10} className="shrink-0" />
              <span className="truncate">{name}</span>
            </span>
          )
        }
        return <span className="text-gray-400">—</span>
      }
      case 'sede': {
        // V065: dropdown inline editable con la lista de sedes activas
        // (mismo patron que Estado / Calidad). Si no hay sedes en el
        // catalogo (single-sede), no se muestra ni el dropdown ni el
        // dash — la columna queda vacia y la deberian ocultar desde el
        // menu Campos. Si hay sedes pero el lead no tiene asignada,
        // el dropdown muestra "Sin sede" como opcion default.
        if (sedes.length === 0) return <span className="text-gray-300">—</span>
        return (
          <SedeDropdown
            lead={row}
            sedes={sedes}
            onChangeSede={handleSedeChange}
          />
        )
      }
      case '_select':
        return (
          <input
            type="checkbox"
            checked={selectedLeads.has(row.id)}
            onChange={() => toggleLeadSelect(row.id)}
            onClick={e => e.stopPropagation()}
            className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
          />
        )
      case '_acciones':
        return (
          <button
            onClick={(e) => { e.stopPropagation(); navigate(`/leads/${row.id}`) }}
            className="p-1.5 rounded-lg text-gray-400 hover:text-indigo-600 hover:bg-indigo-50 dark:text-slate-400 dark:hover:text-indigo-400 dark:hover:bg-slate-800 transition-colors cursor-pointer"
            title="Ver detalle"
          >
            <Eye size={15} />
          </button>
        )
      default:
        return row[key] ?? '—'
    }
  }

  return (
    <div className="space-y-4">
      {/* Encabezado */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Leads</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {total.toLocaleString()} lead{total !== 1 ? 's' : ''}
            {isLeadsHoyActive ? ' de hoy' : ((search || estadoFilter || extraFilterCount > 0) && ' filtrados')}
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Button
            variant={isLeadsHoyActive ? 'default' : 'outline'}
            size="sm"
            onClick={handleToggleLeadsHoy}
            className={`gap-1.5 transition-all cursor-pointer font-medium ${
              isLeadsHoyActive
                ? 'bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm ring-2 ring-indigo-300 dark:ring-indigo-700'
                : 'text-gray-700 hover:text-indigo-600 border-gray-300 bg-white hover:bg-indigo-50/50'
            }`}
            title={isLeadsHoyActive ? 'Desactivar filtro y ver todos los leads' : 'Ver únicamente los leads ingresados el día de hoy'}
          >
            <Calendar size={14} className={isLeadsHoyActive ? 'text-white' : 'text-indigo-600'} />
            <span>Leads de hoy</span>
            {isLeadsHoyActive && (
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse ml-0.5" />
            )}
          </Button>
          {canExport && (
            <Button variant="outline" size="sm" onClick={handleExport} disabled={isExporting} className="gap-1.5">
              <Download size={14} />
              {isExporting ? 'Exportando…' : 'Excel'}
            </Button>
          )}
          {canAssign && (
            <Button variant="outline" size="sm" onClick={() => navigate('/asignacion')} className="gap-1.5">
              <UserPlus size={14} />
              Asignar
            </Button>
          )}
          {canCreate && (
            <Button size="sm" onClick={() => navigate('/leads/nuevo')} className="gap-1.5">
              <Plus size={14} />
              Nuevo Lead
            </Button>
          )}
        </div>
      </div>

      {/* V094 — Re-engagement workflow banner. V094.1: escalacion de
          severidad. Aparece amber si hay recontactos en ultimas 48h sin
          atender, ROJO si hay alguno con >=48h sin atender. Si hay ambos,
          el rojo predomina con conteo amber como contexto. Click activa
          filtro recontacto_sin_atender (devuelve AMBOS tiers, sin cap). */}
      <RecontactosBanner
        amber={recontactosSummary.sin_atender_amber}
        red={recontactosSummary.sin_atender_red}
        oldestDays={recontactosSummary.mas_viejo_dias}
        isLoading={false}
        onActivateFilter={() => {
          setFilters({
            ...EMPTY_FILTERS,
            recontacto_sin_atender: true,
          })
          setSearch('')
          setSearchInput('')
          setEstadoFilter('')
          setPage(1)
        }}
      />

      {/* Banner de leads históricos sin fuente correcta (solo admin) */}
      {historicosSinFuente.count > 0 && role === 'admin' && (
        <div className="bg-amber-50/90 border border-amber-200/80 rounded-xl p-3.5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-3 text-amber-900 shadow-sm animate-fadeIn">
          <div className="flex items-start sm:items-center gap-3">
            <div className="p-2 bg-amber-100/90 rounded-lg text-amber-700 shrink-0 mt-0.5 sm:mt-0">
              <RotateCcw size={16} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <span className="text-xs font-bold text-amber-950">
                  {historicosSinFuente.count} {historicosSinFuente.count === 1 ? 'lead asignado' : 'leads asignados'} desde Históricos sin fuente
                </span>
                <span className="text-[10px] font-bold px-1.5 py-0.5 rounded-full bg-amber-200 text-amber-900">
                  Mantenimiento
                </span>
              </div>
              <p className="text-[11px] text-amber-800 mt-0.5">
                Su última asignación provino del módulo de Históricos, pero actualmente no tienen la fuente "Historico" asignada.
              </p>
            </div>
          </div>
          <button
            onClick={() => {
              setModalHistoricosPage(1)
              setModalHistoricosSearch('')
              setShowHistoricosModal(true)
            }}
            className="px-3.5 py-1.5 bg-amber-600 hover:bg-amber-700 active:bg-amber-800 text-white font-semibold text-xs rounded-lg transition-colors shadow-sm flex items-center gap-1.5 shrink-0 self-end sm:self-center cursor-pointer"
          >
            <RotateCcw size={13} />
            Corregir a "Historico"
          </button>
        </div>
      )}

      {/* V063: barra de vistas guardadas (patrón premium style). Si la
          lista está vacía solo aparece el "+ Vista" — los users la
          descubren al primer click. */}
      <ViewsBar
        views={views}
        activeViewId={activeViewId}
        isDirty={isDirty}
        isMutating={isMutating}
        onSelect={(id) => applyView(id ? views.find(v => v.id === id) : null)}
        onCreate={() => setViewModal({ mode: 'create', initial: null })}
        onSaveChanges={() => saveCurrentToActive()}
        onDiscardChanges={() => activeView && applyView(activeView)}
        onRename={(v) => setViewModal({ mode: 'rename', initial: v })}
        onDuplicate={async (v) => {
          const copy = await duplicateView({
            ...v,
            filters: currentViewState.filters,
            sort: currentViewState.sort,
            columns_order: currentViewState.columns_order,
            visible_columns: currentViewState.visible_columns,
          })
          if (copy) setActiveViewId(copy.id)
        }}
        onSetDefault={(v) => setDefault(v.id)}
        onDelete={(v) => setConfirmDeleteView(v)}
      />

      {viewModal && (
        <SaveViewModal
          mode={viewModal.mode}
          initial={viewModal.initial}
          onClose={() => setViewModal(null)}
          onSave={async (payload) => {
            if (viewModal.mode === 'rename' && viewModal.initial) {
              await updateView(viewModal.initial.id, payload)
            } else {
              await createView(payload)
            }
            setViewModal(null)
          }}
        />
      )}

      {/* Búsqueda en tiempo real */}
      <div className="flex items-center gap-2">
        <div className="relative flex-1 max-w-sm">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            ref={searchRef}
            type="text"
            name="leads-search"
            autoComplete="off"
            placeholder="Buscar nombre, celular, email… (presiona /)"
            value={searchInput == null || searchInput === 'null' ? '' : searchInput}
            onChange={e => {
              const v = e.target.value
              setSearchInput(v === 'null' ? '' : v)
            }}
            className="w-full pl-8 pr-8 h-9 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 bg-white"
          />
          {searchInput && (
            <button
              onClick={() => { setSearchInput(''); searchRef.current?.focus() }}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
            >
              <X size={13} />
            </button>
          )}
        </div>
        {/* V061: chip indicador del filtro por proveedor (deep-link desde
            ApiClients Stats). Click ✕ limpia y vuelve a la lista completa. */}
        {filters.api_client_id && (
          <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-50 border border-emerald-200 text-xs text-emerald-700 font-medium">
            <span className="text-[10px] uppercase tracking-wide text-emerald-600">Proveedor:</span>
            <span>{apiClientName || '…'}</span>
            <button
              onClick={() => {
                setFilters(prev => ({ ...prev, api_client_id: '' }))
                setSearchParams(prev => {
                  const next = new URLSearchParams(prev)
                  next.delete('api_client_id')
                  return next
                })
                setPage(1)
              }}
              className="ml-1 hover:text-emerald-900"
              title="Quitar filtro de proveedor"
              type="button"
            >
              <X size={11} />
            </button>
          </div>
        )}
        {/* V062: chip indicador del filtro por proveedor original (legacy,
            post-unlink). Color amber para diferenciar visualmente del
            proveedor activo (emerald). */}
        {filters.api_client_legacy_slug && (
          <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-amber-50 border border-amber-200 text-xs text-amber-700 font-medium">
            <span className="text-[10px] uppercase tracking-wide text-amber-600">Proveedor original:</span>
            <span>{apiClientName || filters.api_client_legacy_slug}</span>
            <button
              onClick={() => {
                setFilters(prev => ({ ...prev, api_client_legacy_slug: '' }))
                setSearchParams(prev => {
                  const next = new URLSearchParams(prev)
                  next.delete('api_client_legacy_slug')
                  return next
                })
                setPage(1)
              }}
              className="ml-1 hover:text-amber-900"
              title="Quitar filtro de proveedor original"
              type="button"
            >
              <X size={11} />
            </button>
          </div>
        )}
        {/* Chip indicador del filtro de estado_cola */}
        {filters.estado_cola && (
          <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${filters.estado_cola === 'estancados'
              ? 'bg-amber-50 border-amber-300 text-amber-800'
              : filters.estado_cola === 'pendientes'
                ? 'bg-blue-50 border-blue-200 text-blue-700'
                : 'bg-gray-100 border-gray-300 text-gray-700'
            }`}>
            <span className="text-[10px] uppercase tracking-wide font-semibold opacity-75">Cola:</span>
            <span>
              {filters.estado_cola === 'estancados'
                ? '⚠️ Estancados (>24h)'
                : filters.estado_cola === 'pendientes'
                  ? '⏳ Pendientes (<24h)'
                  : filters.estado_cola === 'en_cola'
                    ? '📥 Todos en cola'
                    : '👤 Asignados a asesor'}
            </span>
            <button
              onClick={() => {
                setFilters(prev => ({ ...prev, estado_cola: '' }))
                setSearchParams(prev => {
                  const next = new URLSearchParams(prev)
                  next.delete('estado_cola')
                  return next
                })
                setPage(1)
              }}
              className="ml-1 hover:opacity-75"
              title="Quitar filtro de cola"
              type="button"
            >
              <X size={11} />
            </button>
          </div>
        )}
        {/* Chip indicador del filtro de alerta operacional */}
        {filters.filtro_alerta && (
          <div className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${filters.filtro_alerta === 'urgentes' || filters.filtro_alerta === 'sin_contacto_48h'
              ? 'bg-red-50 border-red-300 text-red-800 dark:bg-red-950/50 dark:border-red-800 dark:text-red-300'
              : 'bg-rose-50 border-rose-300 text-rose-800 dark:bg-rose-950/50 dark:border-rose-800 dark:text-rose-300'
            }`}>
            <span className="text-[10px] uppercase tracking-wide font-semibold opacity-75">Alerta:</span>
            <span>
              {filters.filtro_alerta === 'urgentes' || filters.filtro_alerta === 'sin_contacto_48h'
                ? '🚨 Sin llamada (+48h)'
                : '⏱️ SLA 15m vencido'}
            </span>
            <button
              onClick={() => {
                setFilters(prev => ({ ...prev, filtro_alerta: '' }))
                setSearchParams(prev => {
                  const next = new URLSearchParams(prev)
                  next.delete('alerta')
                  next.delete('filtro_alerta')
                  return next
                })
                setPage(1)
              }}
              className="ml-1 hover:opacity-75 cursor-pointer"
              title="Quitar filtro de alerta"
              type="button"
            >
              <X size={11} />
            </button>
          </div>
        )}
        {/* Chip indicador del filtro de próxima gestión */}
        {filters.filtro_fecha_gestion && (
          <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border bg-purple-50 border-purple-200 text-purple-800 animate-fadeIn">
            <Clock size={12} className="text-purple-600" />
            <span className="text-[10px] uppercase tracking-wide text-purple-600 font-semibold">Gestión:</span>
            <span>
              {filters.filtro_fecha_gestion === 'vencidas'
                ? '⚠️ Vencidas'
                : filters.filtro_fecha_gestion === 'sin_fecha'
                  ? '❓ Sin fecha'
                  : filters.filtro_fecha_gestion === 'hoy'
                    ? '📅 Para hoy'
                    : '✅ Al día'}
            </span>
            <button
              onClick={() => {
                setFilters(prev => ({ ...prev, filtro_fecha_gestion: '' }))
                setPage(1)
              }}
              className="ml-1 hover:text-purple-900 cursor-pointer"
              title="Quitar filtro de próxima gestión"
              type="button"
            >
              <X size={11} />
            </button>
          </div>
        )}
        {/* Chip indicador del filtro de fecha de cita */}
        {filters.filtro_fecha_cita && (
          <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border bg-indigo-50 border-indigo-200 text-indigo-800 animate-fadeIn">
            <Calendar size={12} className="text-indigo-600" />
            <span className="text-[10px] uppercase tracking-wide text-indigo-600 font-semibold">Cita:</span>
            <span>
              {filters.filtro_fecha_cita === 'vencidas'
                ? '⚠️ Vencidas'
                : filters.filtro_fecha_cita === 'sin_fecha'
                  ? '❓ Sin fecha'
                  : filters.filtro_fecha_cita === 'hoy'
                    ? '📅 Para hoy'
                    : '✅ Al día'}
            </span>
            <button
              onClick={() => {
                setFilters(prev => ({ ...prev, filtro_fecha_cita: '' }))
                setPage(1)
              }}
              className="ml-1 hover:text-indigo-900 cursor-pointer"
              title="Quitar filtro de fecha de cita"
              type="button"
            >
              <X size={11} />
            </button>
          </div>
        )}
        {/* Chip indicador del filtro de atención de cita */}
        {filters.filtro_cita_atendida && (
          <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border bg-emerald-50 border-emerald-200 text-emerald-800 animate-fadeIn">
            <CheckCircle2 size={12} className="text-emerald-600" />
            <span className="text-[10px] uppercase tracking-wide text-emerald-600 font-semibold">Atención:</span>
            <span>
              {filters.filtro_cita_atendida === 'atendidas'
                ? '✅ Atendidas'
                : filters.filtro_cita_atendida === 'no_asistio'
                  ? '❌ No asistió'
                  : '⏳ No atendidas'}
            </span>
            <button
              onClick={() => {
                setFilters(prev => ({ ...prev, filtro_cita_atendida: '' }))
                setPage(1)
              }}
              className="ml-1 hover:text-emerald-900 cursor-pointer"
              title="Quitar filtro de atención de cita"
              type="button"
            >
              <X size={11} />
            </button>
          </div>
        )}
        {/* Chip indicador del filtro Leads de hoy */}
        {isLeadsHoyActive && (
          <div className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-indigo-50 border border-indigo-200 text-xs text-indigo-700 font-medium animate-fadeIn">
            <Calendar size={12} className="text-indigo-600" />
            <span className="text-[10px] uppercase tracking-wide text-indigo-600 font-semibold">Filtro:</span>
            <span>Leads de hoy</span>
            <button
              onClick={handleToggleLeadsHoy}
              className="ml-1 hover:text-indigo-900 cursor-pointer"
              title="Quitar filtro de leads de hoy"
              type="button"
            >
              <X size={11} />
            </button>
          </div>
        )}
        {/* V052: filtros avanzados estilo patrón premium (builder dinamico) */}
        <AdvancedFilters
          estados={estados}
          fuentes={fuentes}
          asesores={asesores}
          supervisores={supervisores}
          campanas={campanas}
          calidades={calidades}
          apiClients={apiClients}
          apiClientsLegacy={apiClientsLegacy}
          sedes={sedes}
          canFilterByAsesor={canFilterByAsesor}
          canFilterBySupervisor={canFilterByAsesor}
          values={filters}
          estadoFilter={estadoFilter}
          onChange={(dict) => { setFilters(dict); setPage(1) }}
          onChangeEstado={(v) => { setEstadoFilter(v); setPage(1) }}
        />
        {/* V052: ordenar estilo patrón premium */}
        <SortMenu
          sorts={sorts}
          onChange={(next) => { setSorts(next); setPage(1) }}
        />
        {/* Selector de campos */}
        <div ref={colMenuRef} className="relative shrink-0">
          <Button variant="outline" size="sm" onClick={() => setShowColMenu(v => !v)} className="gap-1.5">
            <List size={14} />
            Campos
          </Button>
          {showColMenu && (
            <div className="absolute right-0 z-30 mt-1 bg-white border border-gray-200 rounded-xl shadow-xl py-2 w-52">
              {BASE_HEADERS.filter(h => TOGGLEABLE_KEYS.includes(h.key)).map(h => (
                <label
                  key={h.key}
                  className="flex items-center gap-2 px-3 py-1.5 hover:bg-gray-50 cursor-pointer text-sm text-gray-700"
                >
                  <input
                    type="checkbox"
                    checked={visibleCols.has(h.key)}
                    onChange={() => toggleCol(h.key)}
                    className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                  />
                  {h.label}
                </label>
              ))}
            </div>
          )}
        </div>

        {/* V067: paginacion estilo correo profesional — SIEMPRE visible (no solo
            cuando hay >1 pagina), flechas deshabilitadas si no aplica.
            Antes solo aparecia con total_pages > 1, ahora muestra
            '1-7 de 7' incluso con poca data. ml-auto la empuja a la
            derecha. */}
        {total > 0 && (
          <div className="inline-flex items-center gap-2 shrink-0 whitespace-nowrap ml-auto">
            <span className="text-sm text-gray-500 select-none leading-none">
              {((page - 1) * PAGE_SIZE + 1).toLocaleString()}–{Math.min(page * PAGE_SIZE, total).toLocaleString()} de {total.toLocaleString()}
            </span>
            <div className="inline-flex items-center gap-1 shrink-0">
              <button
                onClick={() => setPage(p => p - 1)}
                disabled={page <= 1 || isLoading}
                className="w-8 h-8 inline-flex items-center justify-center rounded-full border border-gray-200 text-gray-500 hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                <ChevronLeft size={16} />
              </button>
              <button
                onClick={() => setPage(p => p + 1)}
                disabled={page >= totalPages || isLoading}
                className="w-8 h-8 inline-flex items-center justify-center rounded-full border border-gray-200 text-gray-500 hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                <ChevronRight size={16} />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* V067: pills de estado en su propia fila (la paginacion subio a
          la fila del search, patron correo profesional).
          V094: extra pills para Estancados, Pendientes y Recontactos. */}
      <EstadoPills
        estados={estados}
        selected={estadoFilter}
        onSelect={(newEstadoId) => {
          setEstadoFilter(newEstadoId)
          setFilters(prev => ({
            ...prev,
            subestado: '',
            filtro_fecha_gestion: '',
            filtro_fecha_cita: '',
            filtro_cita_atendida: '',
          }))
          setPage(1)
        }}
        counts={estadoCounts}
        total={totalGlobal || total}
        extraPill={
          <div className="flex items-center gap-1.5 flex-wrap">
            {/* Pill de Estancados */}
            <button
              onClick={() => {
                setFilters(prev => {
                  const activating = prev.estado_cola !== 'estancados'
                  return {
                    ...prev,
                    estado_cola: activating ? 'estancados' : '',
                  }
                })
                setPage(1)
              }}
              className={`shrink-0 flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold transition-all border cursor-pointer ${filters.estado_cola === 'estancados'
                  ? 'bg-amber-600 text-white border-amber-600 shadow-xs'
                  : 'bg-amber-50/80 text-amber-800 border-amber-300/80 hover:bg-amber-100/90'
                }`}
              title="Leads en cola estancados con más de 24h sin asignar a un asesor"
            >
              <span>⚠️ Estancados</span>
              {colaSummary.estancados > 0 && (
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${filters.estado_cola === 'estancados' ? 'bg-white/25 text-white' : 'bg-amber-200 text-amber-900'
                  }`}>
                  {colaSummary.estancados.toLocaleString()}
                </span>
              )}
            </button>

            {/* Pill de Pendientes */}
            <button
              onClick={() => {
                setFilters(prev => {
                  const activating = prev.estado_cola !== 'pendientes'
                  return {
                    ...prev,
                    estado_cola: activating ? 'pendientes' : '',
                  }
                })
                setPage(1)
              }}
              className={`shrink-0 flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold transition-all border cursor-pointer ${filters.estado_cola === 'pendientes'
                  ? 'bg-slate-700 text-white border-slate-700 shadow-xs'
                  : 'bg-slate-100 text-slate-700 border-slate-300 hover:bg-slate-200'
                }`}
              title="Leads en cola pendientes de asignación (<24h)"
            >
              <span>⏳ Pendientes</span>
              {colaSummary.pendientes > 0 && (
                <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${filters.estado_cola === 'pendientes' ? 'bg-white/25 text-white' : 'bg-slate-200 text-slate-800'
                  }`}>
                  {colaSummary.pendientes.toLocaleString()}
                </span>
              )}
            </button>

            {/* Pill de Recontactos */}
            {(recontactosSummary.sin_atender > 0 || filters.recontacto_sin_atender) && (
              <button
                onClick={() => {
                  setFilters(prev => {
                    const activating = !prev.recontacto_sin_atender
                    if (activating) {
                      return {
                        ...EMPTY_FILTERS,
                        recontacto_sin_atender: true,
                      }
                    }
                    return {
                      ...prev,
                      recontacto_sin_atender: false,
                    }
                  })
                  if (!filters.recontacto_sin_atender) {
                    setSearch('')
                    setSearchInput('')
                    setEstadoFilter('')
                  }
                  setPage(1)
                }}
                className={`shrink-0 flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold transition-all border cursor-pointer ${filters.recontacto_sin_atender
                    ? 'bg-rose-600 text-white border-rose-600 shadow-xs'
                    : 'bg-rose-50 text-rose-700 border-rose-300 hover:bg-rose-100'
                  }`}
                title="Leads con recontacto pendientes de respuesta sin contacto posterior"
              >
                <span>🔥 Recontactos</span>
                {recontactosSummary.sin_atender > 0 && (
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${filters.recontacto_sin_atender ? 'bg-white/25 text-white' : 'bg-rose-200 text-rose-900'
                    }`}>
                    {recontactosSummary.sin_atender.toLocaleString()}
                  </span>
                )}
              </button>
            )}

            {/* Pill de Urgentes (+48h) */}
            {(alertasSummary.urgentes_48h > 0 || filters.filtro_alerta === 'urgentes') && (
              <button
                onClick={() => {
                  setFilters(prev => {
                    const activating = prev.filtro_alerta !== 'urgentes'
                    return {
                      ...prev,
                      filtro_alerta: activating ? 'urgentes' : '',
                    }
                  })
                  setPage(1)
                }}
                className={`shrink-0 flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold transition-all border cursor-pointer ${filters.filtro_alerta === 'urgentes'
                    ? 'bg-red-600 text-white border-red-600 shadow-xs'
                    : 'bg-red-50 text-red-700 border-red-300 hover:bg-red-100'
                  }`}
                title="Leads activos con más de 48 horas sin ninguna llamada ni contacto"
              >
                <span>🚨 Sin llamada (+48h)</span>
                {alertasSummary.urgentes_48h > 0 && (
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${filters.filtro_alerta === 'urgentes' ? 'bg-white/25 text-white' : 'bg-red-200 text-red-900'
                    }`}>
                    {alertasSummary.urgentes_48h.toLocaleString()}
                  </span>
                )}
              </button>
            )}

            {/* Pill de SLA 15m */}
            {(alertasSummary.sla_15m > 0 || filters.filtro_alerta === 'sla_15m') && (
              <button
                onClick={() => {
                  setFilters(prev => {
                    const activating = prev.filtro_alerta !== 'sla_15m'
                    return {
                      ...prev,
                      filtro_alerta: activating ? 'sla_15m' : '',
                    }
                  })
                  setPage(1)
                }}
                className={`shrink-0 flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold transition-all border cursor-pointer ${filters.filtro_alerta === 'sla_15m'
                    ? 'bg-rose-700 text-white border-rose-700 shadow-xs'
                    : 'bg-rose-50 text-rose-800 border-rose-300 hover:bg-rose-100'
                  }`}
                title="Leads con SLA de 15m vencido sin primera llamada o contacto"
              >
                <span>⏱️ SLA 15m</span>
                {alertasSummary.sla_15m > 0 && (
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${filters.filtro_alerta === 'sla_15m' ? 'bg-white/25 text-white' : 'bg-rose-200 text-rose-900'
                    }`}>
                    {alertasSummary.sla_15m.toLocaleString()}
                  </span>
                )}
              </button>
            )}

            {/* Pill de Pendientes de Seguimiento (Mi Día / >48h sin contacto o Caliente >24h) */}
            {(alertasSummary.pendientes_seguimiento > 0 || filters.filtro_alerta === 'pendientes') && (
              <button
                onClick={() => {
                  setFilters(prev => {
                    const activating = prev.filtro_alerta !== 'pendientes'
                    return {
                      ...prev,
                      filtro_alerta: activating ? 'pendientes' : '',
                    }
                  })
                  setPage(1)
                }}
                className={`shrink-0 flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-semibold transition-all border cursor-pointer ${filters.filtro_alerta === 'pendientes'
                    ? 'bg-amber-600 text-white border-amber-600 shadow-xs'
                    : 'bg-amber-50 text-amber-800 border-amber-300 hover:bg-amber-100'
                  }`}
                title="Leads activos pendientes de seguimiento (>48h sin contacto o Calientes >24h)"
              >
                <span>⌛ Pendientes seguimiento</span>
                {alertasSummary.pendientes_seguimiento > 0 && (
                  <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${filters.filtro_alerta === 'pendientes' ? 'bg-white/25 text-white' : 'bg-amber-200 text-amber-900'
                    }`}>
                    {alertasSummary.pendientes_seguimiento.toLocaleString()}
                  </span>
                )}
              </button>
            )}
          </div>
        }
      />

      {/* Sub-pills de Próxima Gestión (Vencidas, Sin fecha, Hoy, Al día) */}
      {(() => {
        const activeEstadoObj = estados.find(e => String(e.id) === String(estadoFilter))
        const norm = normalizeEstadoNombre(activeEstadoObj?.nombre || '')
        const isRelevantState = norm.includes('seguim') || norm.includes('oportunidad') || norm.includes('futur') || Boolean(filters.filtro_fecha_gestion)
        if (!isRelevantState) return null

        return (
          <div className="flex items-center gap-1.5 overflow-x-auto pb-1 pl-1 flex-wrap animate-in fade-in">
            <span className="text-[11px] font-semibold text-gray-500 flex items-center gap-1 shrink-0">
              <Calendar size={12} className="text-gray-400" />
              ↳ Próx. gestión:
            </span>
            <button
              onClick={() => {
                setFilters(prev => ({ ...prev, filtro_fecha_gestion: '' }))
                setPage(1)
              }}
              className={`px-2.5 py-0.5 rounded-full text-xs font-medium transition-all border shrink-0 flex items-center gap-1.5 cursor-pointer ${!filters.filtro_fecha_gestion
                ? 'bg-slate-800 text-white border-slate-800 shadow-2xs font-semibold'
                : 'bg-white text-gray-600 border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                }`}
            >
              <span>Todas</span>
              {gestionSummary.total > 0 && (
                <span className={`text-[10px] px-1.5 py-0.2 rounded-full ${!filters.filtro_fecha_gestion ? 'bg-white/20 text-white' : 'bg-gray-100 text-gray-600'}`}>
                  {gestionSummary.total.toLocaleString()}
                </span>
              )}
            </button>

            {/* Vencidas */}
            <button
              onClick={() => {
                setFilters(prev => ({ ...prev, filtro_fecha_gestion: prev.filtro_fecha_gestion === 'vencidas' ? '' : 'vencidas' }))
                setPage(1)
              }}
              className={`px-2.5 py-0.5 rounded-full text-xs font-medium transition-all border shrink-0 flex items-center gap-1.5 cursor-pointer ${filters.filtro_fecha_gestion === 'vencidas'
                ? 'bg-rose-600 text-white border-rose-600 shadow-2xs font-semibold'
                : 'bg-rose-50 text-rose-800 border-rose-200 hover:bg-rose-100'
                }`}
              title="Leads cuya fecha programada ya pasó"
            >
              <span>⚠️ Vencidas</span>
              {gestionSummary.vencidas > 0 && (
                <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded-full ${filters.filtro_fecha_gestion === 'vencidas' ? 'bg-white/25 text-white' : 'bg-rose-200 text-rose-900'}`}>
                  {gestionSummary.vencidas.toLocaleString()}
                </span>
              )}
            </button>

            {/* Sin fecha */}
            <button
              onClick={() => {
                setFilters(prev => ({ ...prev, filtro_fecha_gestion: prev.filtro_fecha_gestion === 'sin_fecha' ? '' : 'sin_fecha' }))
                setPage(1)
              }}
              className={`px-2.5 py-0.5 rounded-full text-xs font-medium transition-all border shrink-0 flex items-center gap-1.5 cursor-pointer ${filters.filtro_fecha_gestion === 'sin_fecha'
                ? 'bg-amber-600 text-white border-amber-600 shadow-2xs font-semibold'
                : 'bg-amber-50 text-amber-800 border-amber-300 hover:bg-amber-100'
                }`}
              title="Leads sin fecha de próxima acción programada"
            >
              <span>❓ Sin fecha</span>
              {gestionSummary.sin_fecha > 0 && (
                <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded-full ${filters.filtro_fecha_gestion === 'sin_fecha' ? 'bg-white/25 text-white' : 'bg-amber-200 text-amber-900'}`}>
                  {gestionSummary.sin_fecha.toLocaleString()}
                </span>
              )}
            </button>

            {/* Hoy */}
            <button
              onClick={() => {
                setFilters(prev => ({ ...prev, filtro_fecha_gestion: prev.filtro_fecha_gestion === 'hoy' ? '' : 'hoy' }))
                setPage(1)
              }}
              className={`px-2.5 py-0.5 rounded-full text-xs font-medium transition-all border shrink-0 flex items-center gap-1.5 cursor-pointer ${filters.filtro_fecha_gestion === 'hoy'
                ? 'bg-blue-600 text-white border-blue-600 shadow-2xs font-semibold'
                : 'bg-blue-50 text-blue-800 border-blue-200 hover:bg-blue-100'
                }`}
              title="Leads con próxima acción para hoy"
            >
              <span>📅 Hoy</span>
              {gestionSummary.hoy > 0 && (
                <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded-full ${filters.filtro_fecha_gestion === 'hoy' ? 'bg-white/25 text-white' : 'bg-blue-200 text-blue-900'}`}>
                  {gestionSummary.hoy.toLocaleString()}
                </span>
              )}
            </button>

            {/* Al día / Futuras */}
            <button
              onClick={() => {
                setFilters(prev => ({ ...prev, filtro_fecha_gestion: prev.filtro_fecha_gestion === 'al_dia' ? '' : 'al_dia' }))
                setPage(1)
              }}
              className={`px-2.5 py-0.5 rounded-full text-xs font-medium transition-all border shrink-0 flex items-center gap-1.5 cursor-pointer ${filters.filtro_fecha_gestion === 'al_dia'
                ? 'bg-emerald-600 text-white border-emerald-600 shadow-2xs font-semibold'
                : 'bg-emerald-50 text-emerald-800 border-emerald-200 hover:bg-emerald-100'
                }`}
              title="Leads con próxima acción programada a futuro"
            >
              <span>✅ Al día</span>
              {gestionSummary.al_dia > 0 && (
                <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded-full ${filters.filtro_fecha_gestion === 'al_dia' ? 'bg-white/25 text-white' : 'bg-emerald-200 text-emerald-900'}`}>
                  {gestionSummary.al_dia.toLocaleString()}
                </span>
              )}
            </button>
          </div>
        )
      })()}

      {/* Sub-pills de Citas Agendadas (Fecha de Cita y Estado de Atención) */}
      {(() => {
        const activeEstadoObj = estados.find(e => String(e.id) === String(estadoFilter))
        const norm = normalizeEstadoNombre(activeEstadoObj?.nombre || '')
        const isCitaState = norm.includes('cita') || norm.includes('agendad') || Boolean(filters.filtro_fecha_cita) || Boolean(filters.filtro_cita_atendida)
        if (!isCitaState) return null

        return (
          <div className="flex flex-col gap-1.5 pb-1 pl-1 animate-in fade-in">
            {/* Fila 1: Filtro por Fecha de Cita */}
            <div className="flex items-center gap-1.5 overflow-x-auto flex-wrap">
              <span className="text-[11px] font-semibold text-gray-500 flex items-center gap-1 shrink-0">
                <Calendar size={12} className="text-gray-400" />
                ↳ Fecha cita:
              </span>
              <button
                onClick={() => {
                  setFilters(prev => ({ ...prev, filtro_fecha_cita: '' }))
                  setPage(1)
                }}
                className={`px-2.5 py-0.5 rounded-full text-xs font-medium transition-all border shrink-0 flex items-center gap-1.5 cursor-pointer ${!filters.filtro_fecha_cita
                  ? 'bg-slate-800 text-white border-slate-800 shadow-2xs font-semibold'
                  : 'bg-white text-gray-600 border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                  }`}
              >
                <span>Todas</span>
                {citasSummary.total > 0 && (
                  <span className={`text-[10px] px-1.5 py-0.2 rounded-full ${!filters.filtro_fecha_cita ? 'bg-white/20 text-white' : 'bg-gray-100 text-gray-600'}`}>
                    {citasSummary.total.toLocaleString()}
                  </span>
                )}
              </button>

              {/* Vencidas */}
              <button
                onClick={() => {
                  setFilters(prev => ({ ...prev, filtro_fecha_cita: prev.filtro_fecha_cita === 'vencidas' ? '' : 'vencidas' }))
                  setPage(1)
                }}
                className={`px-2.5 py-0.5 rounded-full text-xs font-medium transition-all border shrink-0 flex items-center gap-1.5 cursor-pointer ${filters.filtro_fecha_cita === 'vencidas'
                  ? 'bg-rose-600 text-white border-rose-600 shadow-2xs font-semibold'
                  : 'bg-rose-50 text-rose-800 border-rose-200 hover:bg-rose-100'
                  }`}
                title="Citas agendadas cuya fecha programada ya pasó"
              >
                <span>⚠️ Vencidas</span>
                {citasSummary.vencidas > 0 && (
                  <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded-full ${filters.filtro_fecha_cita === 'vencidas' ? 'bg-white/25 text-white' : 'bg-rose-200 text-rose-900'}`}>
                    {citasSummary.vencidas.toLocaleString()}
                  </span>
                )}
              </button>

              {/* Sin fecha */}
              <button
                onClick={() => {
                  setFilters(prev => ({ ...prev, filtro_fecha_cita: prev.filtro_fecha_cita === 'sin_fecha' ? '' : 'sin_fecha' }))
                  setPage(1)
                }}
                className={`px-2.5 py-0.5 rounded-full text-xs font-medium transition-all border shrink-0 flex items-center gap-1.5 cursor-pointer ${filters.filtro_fecha_cita === 'sin_fecha'
                  ? 'bg-amber-600 text-white border-amber-600 shadow-2xs font-semibold'
                  : 'bg-amber-50 text-amber-800 border-amber-300 hover:bg-amber-100'
                  }`}
                title="Leads en estado de cita agendada sin fecha programada"
              >
                <span>❓ Sin fecha</span>
                {citasSummary.sin_fecha > 0 && (
                  <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded-full ${filters.filtro_fecha_cita === 'sin_fecha' ? 'bg-white/25 text-white' : 'bg-amber-200 text-amber-900'}`}>
                    {citasSummary.sin_fecha.toLocaleString()}
                  </span>
                )}
              </button>

              {/* Hoy */}
              <button
                onClick={() => {
                  setFilters(prev => ({ ...prev, filtro_fecha_cita: prev.filtro_fecha_cita === 'hoy' ? '' : 'hoy' }))
                  setPage(1)
                }}
                className={`px-2.5 py-0.5 rounded-full text-xs font-medium transition-all border shrink-0 flex items-center gap-1.5 cursor-pointer ${filters.filtro_fecha_cita === 'hoy'
                  ? 'bg-blue-600 text-white border-blue-600 shadow-2xs font-semibold'
                  : 'bg-blue-50 text-blue-800 border-blue-200 hover:bg-blue-100'
                  }`}
                title="Citas agendadas programadas para hoy"
              >
                <span>📅 Hoy</span>
                {citasSummary.hoy > 0 && (
                  <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded-full ${filters.filtro_fecha_cita === 'hoy' ? 'bg-white/25 text-white' : 'bg-blue-200 text-blue-900'}`}>
                    {citasSummary.hoy.toLocaleString()}
                  </span>
                )}
              </button>

              {/* Al día / Próximas */}
              <button
                onClick={() => {
                  setFilters(prev => ({ ...prev, filtro_fecha_cita: prev.filtro_fecha_cita === 'al_dia' ? '' : 'al_dia' }))
                  setPage(1)
                }}
                className={`px-2.5 py-0.5 rounded-full text-xs font-medium transition-all border shrink-0 flex items-center gap-1.5 cursor-pointer ${filters.filtro_fecha_cita === 'al_dia'
                  ? 'bg-emerald-600 text-white border-emerald-600 shadow-2xs font-semibold'
                  : 'bg-emerald-50 text-emerald-800 border-emerald-200 hover:bg-emerald-100'
                  }`}
                title="Citas agendadas programadas a futuro"
              >
                <span>✅ Al día</span>
                {citasSummary.al_dia > 0 && (
                  <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded-full ${filters.filtro_fecha_cita === 'al_dia' ? 'bg-white/25 text-white' : 'bg-emerald-200 text-emerald-900'}`}>
                    {citasSummary.al_dia.toLocaleString()}
                  </span>
                )}
              </button>
            </div>

            {/* Fila 2: Filtro por Atención (Atendida o No) */}
            <div className="flex items-center gap-1.5 overflow-x-auto flex-wrap">
              <span className="text-[11px] font-semibold text-gray-500 flex items-center gap-1 shrink-0">
                <CheckCircle2 size={12} className="text-gray-400" />
                ↳ Atención:
              </span>
              <button
                onClick={() => {
                  setFilters(prev => ({ ...prev, filtro_cita_atendida: '' }))
                  setPage(1)
                }}
                className={`px-2.5 py-0.5 rounded-full text-xs font-medium transition-all border shrink-0 flex items-center gap-1.5 cursor-pointer ${!filters.filtro_cita_atendida
                  ? 'bg-slate-800 text-white border-slate-800 shadow-2xs font-semibold'
                  : 'bg-white text-gray-600 border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                  }`}
              >
                <span>Todas</span>
                {citasSummary.total > 0 && (
                  <span className={`text-[10px] px-1.5 py-0.2 rounded-full ${!filters.filtro_cita_atendida ? 'bg-white/20 text-white' : 'bg-gray-100 text-gray-600'}`}>
                    {citasSummary.total.toLocaleString()}
                  </span>
                )}
              </button>

              {/* No atendidas / Pendientes */}
              <button
                onClick={() => {
                  setFilters(prev => ({ ...prev, filtro_cita_atendida: prev.filtro_cita_atendida === 'no_atendidas' ? '' : 'no_atendidas' }))
                  setPage(1)
                }}
                className={`px-2.5 py-0.5 rounded-full text-xs font-medium transition-all border shrink-0 flex items-center gap-1.5 cursor-pointer ${filters.filtro_cita_atendida === 'no_atendidas'
                  ? 'bg-amber-600 text-white border-amber-600 shadow-2xs font-semibold'
                  : 'bg-amber-50 text-amber-800 border-amber-300 hover:bg-amber-100'
                  }`}
                title="Citas pendientes de ser atendidas"
              >
                <span>⏳ No atendidas</span>
                {citasSummary.no_atendidas > 0 && (
                  <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded-full ${filters.filtro_cita_atendida === 'no_atendidas' ? 'bg-white/25 text-white' : 'bg-amber-200 text-amber-900'}`}>
                    {citasSummary.no_atendidas.toLocaleString()}
                  </span>
                )}
              </button>

              {/* Atendidas */}
              <button
                onClick={() => {
                  setFilters(prev => ({ ...prev, filtro_cita_atendida: prev.filtro_cita_atendida === 'atendidas' ? '' : 'atendidas' }))
                  setPage(1)
                }}
                className={`px-2.5 py-0.5 rounded-full text-xs font-medium transition-all border shrink-0 flex items-center gap-1.5 cursor-pointer ${filters.filtro_cita_atendida === 'atendidas'
                  ? 'bg-emerald-600 text-white border-emerald-600 shadow-2xs font-semibold'
                  : 'bg-emerald-50 text-emerald-800 border-emerald-200 hover:bg-emerald-100'
                  }`}
                title="Citas completadas y atendidas"
              >
                <span>✅ Atendidas</span>
                {citasSummary.atendidas > 0 && (
                  <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded-full ${filters.filtro_cita_atendida === 'atendidas' ? 'bg-white/25 text-white' : 'bg-emerald-200 text-emerald-900'}`}>
                    {citasSummary.atendidas.toLocaleString()}
                  </span>
                )}
              </button>

              {/* No asistió */}
              <button
                onClick={() => {
                  setFilters(prev => ({ ...prev, filtro_cita_atendida: prev.filtro_cita_atendida === 'no_asistio' ? '' : 'no_asistio' }))
                  setPage(1)
                }}
                className={`px-2.5 py-0.5 rounded-full text-xs font-medium transition-all border shrink-0 flex items-center gap-1.5 cursor-pointer ${filters.filtro_cita_atendida === 'no_asistio'
                  ? 'bg-rose-600 text-white border-rose-600 shadow-2xs font-semibold'
                  : 'bg-rose-50 text-rose-800 border-rose-200 hover:bg-rose-100'
                  }`}
                title="Citas marcadas como no asistió"
              >
                <span>❌ No asistió</span>
                {citasSummary.no_asistio > 0 && (
                  <span className={`text-[10px] font-bold px-1.5 py-0.2 rounded-full ${filters.filtro_cita_atendida === 'no_asistio' ? 'bg-white/25 text-white' : 'bg-rose-200 text-rose-900'}`}>
                    {citasSummary.no_asistio.toLocaleString()}
                  </span>
                )}
              </button>
            </div>
          </div>
        )
      })()}

      {/* Subestados Pills Bar - solo visible cuando el estado activo tiene subestados */}
      {(() => {
        const activeEstadoObj = estados.find(e => String(e.id) === String(estadoFilter))
        const subestados = getSubestadosForEstado(activeEstadoObj?.nombre)
        if (!subestados || subestados.length === 0) return null

        return (
          <div className="flex items-center gap-1.5 overflow-x-auto pb-1 pl-1 flex-wrap animate-in fade-in">
            <span className="text-[11px] font-semibold text-gray-400 flex items-center gap-1 shrink-0">
              ↳ Subestado:
            </span>
            <button
              onClick={() => {
                setFilters(prev => ({ ...prev, subestado: '' }))
                setPage(1)
              }}
              className={`px-2.5 py-0.5 rounded-full text-xs font-medium transition-all border shrink-0 ${!filters.subestado
                ? 'bg-slate-800 text-white border-slate-800 shadow-2xs'
                : 'bg-white text-gray-600 border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                }`}
            >
              Todos
            </button>
            {subestados.map(sub => {
              const isSubActive = filters.subestado === sub
              return (
                <button
                  key={sub}
                  onClick={() => {
                    setFilters(prev => ({
                      ...prev,
                      subestado: isSubActive ? '' : sub,
                    }))
                    setPage(1)
                  }}
                  className={`px-2.5 py-0.5 rounded-full text-xs font-medium transition-all border shrink-0 ${isSubActive
                    ? 'bg-indigo-600 text-white border-indigo-600 shadow-2xs font-semibold'
                    : 'bg-white text-gray-600 border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                    }`}
                  title={sub}
                >
                  {formatSubestadoText(sub, 24)}
                </button>
              )
            })}
          </div>
        )
      })()}

      {/* Panel de filtros adicionales */}
      {showFilters && (
        <FilterPanel
          filters={filters}
          onChange={(k, v) => { setFilters(prev => ({ ...prev, [k]: v })); setPage(1) }}
          fuentes={fuentes}
          asesores={asesores}
          supervisores={supervisores}
          campanas={campanas}
          estados={estados}
          estadoFilter={estadoFilter}
          onChangeEstado={(v) => { setEstadoFilter(v); setPage(1) }}
          calidades={calidades}
          canFilterByAsesor={canFilterByAsesor}
          onClear={clearFilters}
        />
      )}

      {/* Banner de nuevos leads (V067.1 — discreto, sin pulse) */}
      {newLeadsCount > 0 && (
        <button
          onClick={handleRefreshNewLeads}
          className="w-full flex items-center justify-center gap-2 py-1.5 px-3 bg-indigo-50 hover:bg-indigo-100 border border-indigo-200 rounded-md text-xs font-medium text-indigo-700 transition-colors"
        >
          <Plus size={12} />
          {newLeadsCount > 500
            // Sanity guard — si la diff es absurda probablemente la baseline
            // quedo desincronizada (race entre filtros y polling). No mostramos
            // un numero alarmante; invitamos a recargar.
            ? 'Hay leads nuevos disponibles — actualizar'
            : `${newLeadsCount} lead${newLeadsCount !== 1 ? 's' : ''} nuevo${newLeadsCount !== 1 ? 's' : ''} — actualizar`}
        </button>
      )}

      {/* Tabla */}
      <Card>
        <DataTable
          headers={headers}
          rows={leads}
          renderCell={renderCell}
          isLoading={isLoading}
          error={error}
          // Scroll vertical confinado al viewport — el scrollbar horizontal
          // queda siempre accesible al fondo sin tener que bajar 50 filas.
          // 320px arriba ≈ header pagina + tabs + busqueda + bulk bar; el
          // resto del viewport va para la tabla. Combina con thead sticky.
          //
          // V095.6 — si el banner de recontactos esta visible, sumamos su
          // alto al offset (~46px de la pill compacta + 12px de margen).
          // Sin esto, el banner empuja la tabla hacia abajo y el scrollbar
          // horizontal del fondo cae fuera del viewport.
          maxHeight={
            (recontactosSummary.sin_atender_amber > 0 || recontactosSummary.sin_atender_red > 0)
              ? 'calc(100vh - 378px)'
              : 'calc(100vh - 320px)'
          }
          // V063: orden de columnas draggable persistido por usuario
          // (patron hojas de cálculo). El handle aparece al hover del header.
          columnOrderKey="leads_columns_order"
          // V063: orden controlado por la vista activa (cuando hay una).
          // Si no hay vista activa, DataTable usa su persistencia local.
          controlledOrder={activeView ? (activeView.columns_order || null) : (columnsOrder.length > 0 ? columnsOrder : null)}
          onColumnOrderChange={(next) => setColumnsOrder(next)}
          emptyTitle="No hay leads"
          emptyDescription={
            search || estadoFilter || extraFilterCount > 0
              ? 'Sin resultados para los filtros aplicados.'
              : 'Crea tu primer lead o importa desde Carga Masiva.'
          }
          emptyAction={
            (search || estadoFilter || extraFilterCount > 0) ? (
              <button
                onClick={clearFilters}
                className="text-sm text-indigo-600 hover:text-indigo-700 font-medium underline-offset-2 hover:underline"
              >
                Limpiar filtros
              </button>
            ) : null
          }
          // V093 — tint sutil para filas con recontacto reciente (≤7 días).
          // Resuelve la queja: "tengo que filtrar para verlos"; ahora se
          // ven directo. El tint es discreto para no abrumar pero clase
          // mundial — destaca lo importante sin gritar.
          rowClassName={(row) => {
            if (row.is_urgente_48h) return '!bg-red-50/70 hover:!bg-red-100/70 dark:!bg-red-950/30 dark:hover:!bg-red-900/30'
            if (row.is_sla_15m_vencido) return '!bg-rose-50/70 hover:!bg-rose-100/70 dark:!bg-rose-950/30 dark:hover:!bg-rose-900/30'
            if (!row.fecha_ultimo_recontacto) return ''
            const daysAgo = (Date.now() - new Date(row.fecha_ultimo_recontacto).getTime()) / 86400000
            return daysAgo <= 7 ? '!bg-amber-50/70 hover:!bg-amber-100/70 dark:!bg-amber-950/30 dark:hover:!bg-amber-900/30' : ''
          }}
          pagination={null}
          onPageChange={setPage}
          onRowClick={(row) => navigate(`/leads/${row.id}`)}
        />
      </Card>

      {canAssign && (
        <BulkReassignBar
          selectedRows={selectedRowsArray}
          asesores={asesores}
          groups={teamGroups}
          estados={estados}
          fuentes={fuentes}
          canChangeFuente={role === 'admin'}
          onAssign={handleBulkReassign}
          onChangeEstado={handleBulkEstadoChange}
          onChangeFuente={handleBulkFuenteChange}
          onRevertTmk={handleBulkRevertTmk}
          onDevolverHistoricos={handleBulkDevolverHistoricos}
          onDelete={() => setConfirmBulkDelete(true)}
          onClear={() => setSelectedLeads(new Set())}
          isAssigning={isBulkAssigning}
          isChangingEstado={isBulkChangingEstado}
          isChangingFuente={isBulkChangingFuente}
          isRevertingTmk={isBulkRevertingTmk}
          isDevolviendoHistoricos={isBulkDevolviendoHistoricos}
          isDeleting={isBulkDeleting}
        />
      )}

      <ConfirmDialog
        open={!!confirmBulkRevertTmk}
        variant="warning"
        title="Revertir asignación de Bolsa TMK"
        confirmLabel="Revertir a TMK"
        message={
          confirmBulkRevertTmk
            ? `¿Estás seguro de que deseas revertir la asignación de ${confirmBulkRevertTmk.count} lead${confirmBulkRevertTmk.count !== 1 ? 's' : ''} de Bolsa TMK? Se devolverán a su asesor y estado original previos al reciclaje.`
            : ''
        }
        onConfirm={handleConfirmRevertTmk}
        onCancel={() => setConfirmBulkRevertTmk(null)}
      />

      <ConfirmDialog
        open={!!confirmBulkDevolverHistoricos}
        variant="warning"
        title="Devolver leads a Históricos"
        confirmLabel="Devolver a Históricos"
        message={
          confirmBulkDevolverHistoricos
            ? `¿Estás seguro de que deseas devolver ${confirmBulkDevolverHistoricos.count} lead${confirmBulkDevolverHistoricos.count !== 1 ? 's' : ''} a la base de Históricos? Se quitará su asesor y supervisor asignados, y saldrán de la lista activa de leads.`
            : ''
        }
        onConfirm={handleConfirmDevolverHistoricos}
        onCancel={() => setConfirmBulkDevolverHistoricos(null)}
      />

      <ConfirmDialog
        open={confirmBulkDelete}
        title="Eliminar leads seleccionados"
        message={`¿Estás seguro de que deseas eliminar ${selectedLeads.size} lead${selectedLeads.size !== 1 ? 's' : ''}? Esta acción no se puede deshacer.`}
        onConfirm={handleBulkDeleteConfirm}
        onCancel={() => setConfirmBulkDelete(false)}
      />

      <ConfirmDialog
        open={!!pendingReassign}
        variant="warning"
        title={pendingReassign?.isUnassign ? 'Confirmar desasignación masiva' : 'Confirmar reasignación masiva'}
        confirmLabel={pendingReassign?.isUnassign ? 'Dejar sin asignar' : 'Reasignar'}
        message={
          pendingReassign
            ? pendingReassign.isUnassign
              ? [
                `¿Estás seguro de desasignar ${pendingReassign.count} lead${pendingReassign.count !== 1 ? 's' : ''}?`,
                pendingReassign.breakdown?.yaAsignados > 0
                  ? `${pendingReassign.breakdown.yaAsignados} perderá${pendingReassign.breakdown.yaAsignados !== 1 ? 'n' : ''} su asesor actual y pasarán a la cola sin asignar.`
                  : 'Quedarán en la cola general sin asesor.',
                'Cada cambio queda registrado en el historial.',
              ].filter(Boolean).join(' ')
              : [
                `${pendingReassign.count} lead${pendingReassign.count !== 1 ? 's' : ''} → ${pendingReassign.asesorNombre}.`,
                pendingReassign.breakdown?.yaAsignados > 0
                  ? `${pendingReassign.breakdown.yaAsignados} ya tenía${pendingReassign.breakdown.yaAsignados !== 1 ? 'n' : ''} asesor (se sobrescribirá).`
                  : null,
                pendingReassign.breakdown?.crossSupervisor
                  ? 'La selección cruza más de un equipo.'
                  : null,
                'Cada cambio queda registrado en el historial.',
              ].filter(Boolean).join(' ')
            : ''
        }
        onConfirm={handleConfirmReassign}
        onCancel={() => setPendingReassign(null)}
      />

      <CambioEstadoModal
        open={cambioEstadoModal.open}
        onClose={() => setCambioEstadoModal({ open: false, lead: null, targetEstado: null })}
        lead={cambioEstadoModal.lead}
        targetEstado={cambioEstadoModal.targetEstado}
        onConfirm={async (payload) => {
          if (cambioEstadoModal.lead) {
            await handleEstadoChange(cambioEstadoModal.lead.id, payload)
          }
        }}
        users={allUsersList}
      />

      <ConfirmDialog
        open={!!pendingEstadoChange}
        variant="warning"
        title="Confirmar cambio masivo de estado"
        confirmLabel="Cambiar estado"
        message={
          pendingEstadoChange
            ? `${pendingEstadoChange.count} lead${pendingEstadoChange.count !== 1 ? 's' : ''} cambiarán a "${pendingEstadoChange.estadoNombre}". Cada cambio queda registrado en el historial.`
            : ''
        }
        onConfirm={handleConfirmEstadoChange}
        onCancel={() => setPendingEstadoChange(null)}
      />

      <ConfirmDialog
        open={!!pendingFuenteChange}
        variant="warning"
        title="Confirmar cambio masivo de fuente"
        confirmLabel="Cambiar fuente"
        message={
          pendingFuenteChange
            ? `${pendingFuenteChange.count} lead${pendingFuenteChange.count !== 1 ? 's' : ''} cambiarán su fuente a "${pendingFuenteChange.fuenteNombre}". Cada cambio queda registrado en el historial.`
            : ''
        }
        onConfirm={handleConfirmFuenteChange}
        onCancel={() => setPendingFuenteChange(null)}
      />

      <ConfirmDialog
        open={!!pendingExport}
        variant="warning"
        title="Descarga grande"
        confirmLabel="Descargar"
        message={
          pendingExport
            ? `Estás a punto de descargar ${pendingExport.count.toLocaleString()} leads en Excel. La operación puede tardar y consumir recursos del sistema. Aplica filtros para reducir el tamaño si es posible. Recuerda: cada descarga queda registrada en el log de auditoría.`
            : ''
        }
        onConfirm={handleConfirmExport}
        onCancel={() => setPendingExport(null)}
      />

      <InfoDialog
        open={!!infoDialog}
        variant={infoDialog?.variant || 'info'}
        title={infoDialog?.title || ''}
        message={infoDialog?.message || ''}
        onClose={() => setInfoDialog(null)}
      />

      {/* V063: confirmacion destructiva para eliminar vista (reemplaza
          window.confirm nativo). V063.2: captura errores del backend
          y los muestra en InfoDialog para no fallar silenciosamente. */}
      <ConfirmDialog
        open={!!confirmDeleteView}
        variant="danger"
        title="Eliminar vista"
        confirmLabel="Sí, eliminar"
        cancelLabel="Cancelar"
        message={confirmDeleteView
          ? `Vas a eliminar la vista "${confirmDeleteView.name}". Esta acción no se puede deshacer — los filtros, orden de columnas y configuración guardada se perderán.\n\nLos leads NO se ven afectados.`
          : ''}
        onConfirm={async () => {
          if (!confirmDeleteView) return
          const target = confirmDeleteView
          // V067.1: si la vista a eliminar es la activa, reseteamos el
          // estado al "Todos" limpio ANTES del DELETE. Bug previo: solo
          // se limpiaba `activeViewId` y los filtros heredados de la
          // vista persistian (ej. Calificado quedaba seleccionado
          // mostrando "49 leads filtrados" en lugar de "Todos 5971").
          const wasActive = activeViewId === target.id
          setConfirmDeleteView(null)
          try {
            await deleteView(target.id)
            if (wasActive) applyView(null)
          } catch (err) {
            setInfoDialog({
              variant: 'error',
              title: 'No se pudo eliminar la vista',
              message: err?.response?.data?.detail
                || err?.message
                || 'Error inesperado al eliminar la vista. Intentá de nuevo.',
            })
          }
        }}
        onCancel={() => setConfirmDeleteView(null)}
      />

      {/* Modal para corregir fuente de leads históricos */}
      {showHistoricosModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6 bg-black/60 backdrop-blur-xs animate-fadeIn">
          <div className="bg-white dark:bg-slate-900 rounded-2xl border border-gray-200 dark:border-slate-800 shadow-2xl max-w-4xl w-full h-[85vh] max-h-[750px] p-6 flex flex-col justify-between animate-scaleIn">
            {/* Header */}
            <div className="flex items-center justify-between pb-4 border-b border-gray-100 dark:border-slate-800 shrink-0">
              <div className="flex items-center gap-3">
                <div className="p-2.5 bg-amber-100 dark:bg-amber-950/50 rounded-xl text-amber-700 dark:text-amber-400">
                  <RotateCcw size={20} />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-lg font-bold text-gray-900 dark:text-gray-100">
                      Regularizar Fuente de Leads Históricos
                    </h3>
                    <Badge variant="outline" className="border-amber-300 text-amber-800 bg-amber-50 dark:bg-amber-950/40 dark:text-amber-300">
                      {historicosSinFuente.count} detectados
                    </Badge>
                  </div>
                  <p className="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
                    Detección y corrección masiva de fuente para leads provenientes del módulo de históricos
                  </p>
                </div>
              </div>
              <button
                onClick={() => setShowHistoricosModal(false)}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-gray-200 p-1.5 rounded-lg hover:bg-gray-100 dark:hover:bg-slate-800 cursor-pointer transition-colors"
              >
                <X size={20} />
              </button>
            </div>

            {/* Description & Search Bar */}
            <div className="py-3 shrink-0 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs text-gray-600 dark:text-gray-300">
              <p className="leading-relaxed flex-1">
                Estos leads fueron asignados desde el módulo de históricos y su última asignación provino de allí, pero actualmente no tienen la fuente <strong className="text-amber-800 dark:text-amber-400">"Historico"</strong>. Al confirmar, se actualizará su procedencia a nivel global.
              </p>
              <div className="relative w-full sm:w-64 shrink-0">
                <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
                <input
                  type="text"
                  value={modalHistoricosSearch}
                  onChange={e => {
                    setModalHistoricosSearch(e.target.value)
                    setModalHistoricosPage(1)
                  }}
                  placeholder="Buscar por nombre, tel, asesor..."
                  className="w-full pl-8 pr-3 py-1.5 text-xs bg-gray-50 dark:bg-slate-800 border border-gray-200 dark:border-slate-700 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500"
                />
              </div>
            </div>

            {/* Table Container */}
            <div className="flex-1 min-h-0 border border-gray-200 dark:border-slate-800 rounded-xl overflow-hidden flex flex-col bg-white dark:bg-slate-900 shadow-inner">
              <div className="overflow-x-auto flex-1">
                <table className="w-full text-left text-xs">
                  <thead className="bg-gray-50 dark:bg-slate-800/80 border-b border-gray-200 dark:border-slate-700 text-gray-600 dark:text-gray-300 font-semibold sticky top-0 z-10">
                    <tr>
                      <th className="py-2.5 px-3 w-16 text-center">ID</th>
                      <th className="py-2.5 px-3">Lead</th>
                      <th className="py-2.5 px-3">Teléfono</th>
                      <th className="py-2.5 px-3">Asesor Asignado</th>
                      <th className="py-2.5 px-3">Estado</th>
                      <th className="py-2.5 px-3 text-right">Fuente Actual</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100 dark:divide-slate-800 text-gray-700 dark:text-gray-200">
                    {paginatedModalLeads.length === 0 ? (
                      <tr>
                        <td colSpan={6} className="py-8 text-center text-gray-400">
                          No se encontraron leads con ese criterio de búsqueda.
                        </td>
                      </tr>
                    ) : (
                      paginatedModalLeads.map(l => (
                        <tr key={l.id} className="hover:bg-gray-50/80 dark:hover:bg-slate-800/50 transition-colors">
                          <td className="py-2.5 px-3 text-center font-mono text-gray-500 dark:text-gray-400">
                            #{l.id}
                          </td>
                          <td className="py-2.5 px-3">
                            <div className="font-semibold text-gray-900 dark:text-gray-100">
                              {l.nombre_completo || 'Sin nombre'}
                            </div>
                            {l.email && (
                              <div className="text-[11px] text-gray-400 truncate max-w-[200px]">
                                {l.email}
                              </div>
                            )}
                          </td>
                          <td className="py-2.5 px-3 font-mono text-gray-600 dark:text-gray-300">
                            {l.telefono || '—'}
                          </td>
                          <td className="py-2.5 px-3">
                            {l.asesor_nombre ? (
                              <span className="text-gray-800 dark:text-gray-200 font-medium">
                                {l.asesor_nombre}
                              </span>
                            ) : (
                              <span className="text-gray-400 italic">Sin asesor</span>
                            )}
                          </td>
                          <td className="py-2.5 px-3">
                            <span className="px-2 py-0.5 text-[11px] rounded-md bg-gray-100 dark:bg-slate-800 text-gray-700 dark:text-gray-300">
                              {l.estado_nombre || 'Nuevo'}
                            </span>
                          </td>
                          <td className="py-2.5 px-3 text-right">
                            <span className="px-2 py-0.5 text-[11px] font-medium rounded-full bg-amber-50 text-amber-800 border border-amber-200 dark:bg-amber-950/40 dark:text-amber-300 dark:border-amber-900">
                              {l.fuente_actual}
                            </span>
                          </td>
                        </tr>
                      ))
                    )}
                  </tbody>
                </table>
              </div>

              {/* Modal Pagination Footer */}
              <div className="bg-gray-50 dark:bg-slate-800/60 px-4 py-2.5 border-t border-gray-200 dark:border-slate-800 flex flex-col sm:flex-row items-center justify-between gap-2 text-xs text-gray-500 dark:text-gray-400 shrink-0">
                <div>
                  Mostrando <span className="font-semibold text-gray-700 dark:text-gray-200">{filteredModalLeads.length > 0 ? (modalHistoricosPage - 1) * MODAL_PAGE_SIZE + 1 : 0}</span> a{' '}
                  <span className="font-semibold text-gray-700 dark:text-gray-200">{Math.min(modalHistoricosPage * MODAL_PAGE_SIZE, filteredModalLeads.length)}</span> de{' '}
                  <span className="font-semibold text-gray-700 dark:text-gray-200">{filteredModalLeads.length}</span> leads
                  {modalHistoricosSearch && ` (filtrados de ${historicosSinFuente.count})`}
                </div>

                <div className="flex items-center gap-1.5">
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setModalHistoricosPage(p => Math.max(1, p - 1))}
                    disabled={modalHistoricosPage <= 1}
                    className="h-7 px-2.5 text-xs gap-1"
                  >
                    <ChevronLeft size={13} />
                    Anterior
                  </Button>
                  <span className="px-2 text-xs font-medium text-gray-700 dark:text-gray-300">
                    {modalHistoricosPage} / {totalModalPages}
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setModalHistoricosPage(p => Math.min(totalModalPages, p + 1))}
                    disabled={modalHistoricosPage >= totalModalPages}
                    className="h-7 px-2.5 text-xs gap-1"
                  >
                    Siguiente
                    <ChevronRight size={13} />
                  </Button>
                </div>
              </div>
            </div>

            {/* Modal Actions */}
            <div className="flex items-center justify-between gap-3 pt-3 border-t border-gray-100 dark:border-slate-800 shrink-0">
              <span className="text-[11px] text-gray-400">
                Se regularizarán todos los {historicosSinFuente.count} leads detectados.
              </span>
              <div className="flex items-center gap-2.5">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowHistoricosModal(false)}
                  disabled={isFixingHistoricos}
                >
                  Cancelar
                </Button>
                <Button
                  size="sm"
                  onClick={async () => {
                    setIsFixingHistoricos(true)
                    try {
                      const res = await api.post('/api/leads/mantenimiento/corregir-fuente-historicos', {})
                      setShowHistoricosModal(false)
                      setInfoDialog({
                        variant: 'success',
                        title: 'Fuente de Históricos corregida',
                        message: res.data?.message || 'Se actualizó la fuente a "Historico" exitosamente.',
                      })
                      fetchLeads()
                      fetchCounts()
                      checkHistoricosSinFuente()
                    } catch (err) {
                      setInfoDialog({
                        variant: 'error',
                        title: 'Error al corregir fuente',
                        message: err.response?.data?.detail || 'No se pudo actualizar la fuente de los leads históricos.',
                      })
                    } finally {
                      setIsFixingHistoricos(false)
                    }
                  }}
                  disabled={isFixingHistoricos || historicosSinFuente.count === 0}
                  className="bg-amber-600 hover:bg-amber-700 text-white gap-1.5 cursor-pointer shadow-sm"
                >
                  <RotateCcw size={14} className={isFixingHistoricos ? 'animate-spin' : ''} />
                  {isFixingHistoricos ? 'Actualizando...' : `Cambiar a fuente "Historico" (${historicosSinFuente.count})`}
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
