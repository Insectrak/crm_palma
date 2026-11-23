import { useEffect, useState, useMemo, useRef } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  ArrowLeft, Edit2, Save, X, Plus, Phone, MessageSquare, MessageCircle,
  Mail, Users, FileText, Calendar, AlertCircle, Clock, User, Tag, Trash2,
  History, ArrowRight, UserMinus, UserPlus, Shuffle, Archive, ChevronDown,
  Sparkles, Check, CheckCircle, XCircle, RefreshCw, Megaphone, Copy, MapPin,
  IdCard, Video, Lock, UserCheck, ExternalLink, Bot, Shield, ClipboardList,
  GitMerge,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import LoadingSpinner from '@/components/shared/LoadingSpinner'
import ConfirmDialog from '@/components/shared/ConfirmDialog'
import NextLeadFooter from '@/components/leads/NextLeadFooter'
import useAuthStore from '@/store/authStore'
import useCrmStore from '@/store/crmStore'
import useBrandStore from '@/store/brandStore'
import { canReadField, canEditField, hasPermission } from '@/lib/permissions'
import api from '@/lib/api'
import { fireAssignmentChanged } from '@/lib/events'
import { buildTeamGroups, flattenGroups } from '@/lib/teamGroups'
import { normalizePhonePEEdit } from '@/lib/phone'
import CambioEstadoModal, { isEstadoSeguimiento, isEstadoPerdido, isEstadoMatricula, isEstadoOportunidadFutura, MOTIVOS_PERDIDA_OPCIONES, ACCIONES_OPORTUNIDAD_FUTURA_OPCIONES, requiresFormularioEspecifico } from '@/components/leads/CambioEstadoModal'
import FichaTecnicaCard from '@/components/leads/FichaTecnicaCard'
import LeadHistorialCambios from '@/components/leads/LeadHistorialCambios'
import MergedLeadBanner from '@/components/leads/MergedLeadBanner'
import FusionarLeadModal from '@/components/leads/FusionarLeadModal'
import { getFichaTecnicaStats } from '@/lib/fichaTecnica'

/**
 * Formato de fecha-hora ISO a legible en español.
 */
function formatDateTime(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('es-PE', {
    timeZone: 'America/Lima',
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

/**
 * Ícono según tipo de contacto.
 */
function ContactoIcon({ tipo }) {
  const norm = String(tipo || '').toLowerCase()
  if (norm.includes('virtual') || norm.includes('video')) {
    return (
      <div className="w-8 h-8 rounded-full bg-sky-50 flex items-center justify-center shrink-0">
        <Video size={15} className="text-sky-500" />
      </div>
    )
  }
  if (norm.includes('bustamante') || norm.includes('umacollo') || norm.includes('oficina') || norm.includes('presencial') || norm.includes('exterior') || norm.includes('cita')) {
    return (
      <div className="w-8 h-8 rounded-full bg-indigo-50 flex items-center justify-center shrink-0">
        <Calendar size={15} className="text-indigo-600" />
      </div>
    )
  }
  const map = {
    llamada:       { Icon: Phone,        color: 'text-indigo-500', bg: 'bg-indigo-50' },
    whatsapp:      { Icon: MessageSquare,color: 'text-green-500',  bg: 'bg-green-50' },
    email:         { Icon: Mail,         color: 'text-purple-500', bg: 'bg-purple-50' },
    presencial:    { Icon: Users,        color: 'text-orange-500', bg: 'bg-orange-50' },
    nota:          { Icon: FileText,     color: 'text-gray-500',   bg: 'bg-gray-50' },
    cambio_estado: { Icon: Tag,          color: 'text-amber-500',  bg: 'bg-amber-50' },
  }
  const { Icon, color, bg } = map[norm] || map.nota
  return (
    <div className={`w-8 h-8 rounded-full ${bg} flex items-center justify-center shrink-0`}>
      <Icon size={15} className={color} />
    </div>
  )
}

/**
 * Badge de estado del lead usando color del catálogo.
 */
function EstadoBadge({ estadoId, estados }) {
  const estado = estados.find(e => e.id === estadoId)
  if (!estado) return null
  return (
    <span
      className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold border"
      style={{
        backgroundColor: (estado.color_hex || '#6b7280') + '20',
        color: estado.color_hex || '#6b7280',
        borderColor: (estado.color_hex || '#6b7280') + '40',
      }}
    >
      {estado.nombre}
    </span>
  )
}

/**
 * Mapea un motivo del log a un par {label, icon, color} para la UI.
 * Mantener este map en un solo lugar respeta el principio Open/Closed:
 * añadir un motivo nuevo solo requiere extender este objeto.
 */
const MOTIVO_META = {
  inicial:               { label: 'Asignación inicial',           Icon: UserPlus,    color: 'text-emerald-600 bg-emerald-50 border-emerald-200' },
  campana_exclusiva:     { label: '🎯 Leads Campañas (Exclusivo)', Icon: Megaphone,   color: 'text-purple-600 bg-purple-50 border-purple-200' },
  auto_asignacion:       { label: '⚡ Reparto Automático',         Icon: Shuffle,     color: 'text-blue-600 bg-blue-50 border-blue-200' },
  round_robin:           { label: 'Round-robin',                  Icon: Shuffle,     color: 'text-sky-600 bg-sky-50 border-sky-200' },
  manual_admin:          { label: 'Reasignación (admin)',         Icon: ArrowRight,  color: 'text-indigo-600 bg-indigo-50 border-indigo-200' },
  manual_supervisor:     { label: 'Reasignación',                 Icon: ArrowRight,  color: 'text-indigo-600 bg-indigo-50 border-indigo-200' },
  derivacion_supervisor: { label: 'Derivación entre supervisores',Icon: ArrowRight,  color: 'text-indigo-600 bg-indigo-50 border-indigo-200' },
  derivacion_antecedente:{ label: 'Devuelto por antecedentes',    Icon: History,     color: 'text-teal-600 bg-teal-50 border-teal-200' },
  liberacion:            { label: 'Liberación',                   Icon: UserMinus,   color: 'text-amber-600 bg-amber-50 border-amber-200' },
}

/**
 * Timeline de reasignaciones del lead. Solo se muestra cuando hay
 * registros — un lead intacto no consume espacio en la UI.
 */
function AsignacionesHistorial({ items }) {
  if (!items || items.length === 0) return null

  return (
    <Card>
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-semibold text-gray-700 flex items-center gap-2">
          <History size={15} /> Historial de asignaciones ({items.length})
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        <ol className="space-y-3">
          {items.map((it) => {
            const meta = MOTIVO_META[it.motivo] || MOTIVO_META.manual_supervisor
            const { Icon } = meta
            const anterior = it.asesor_anterior_nombre || (it.asesor_anterior_id ? '—' : 'Sin asignar')
            const nuevo    = it.asesor_nuevo_nombre    || (it.asesor_nuevo_id    ? '—' : 'Liberado')
            return (
              <li key={it.id} className="flex gap-3">
                <div className={`w-8 h-8 rounded-full border flex items-center justify-center shrink-0 ${meta.color}`}>
                  <Icon size={14} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <span className="text-xs font-semibold text-gray-700">{meta.label}</span>
                    <span className="text-xs text-gray-400">{formatDateTime(it.fecha)}</span>
                  </div>
                  <p className="text-sm text-gray-700 mt-0.5 truncate">
                    <span className="text-gray-500">{anterior}</span>
                    <ArrowRight size={11} className="inline mx-1 text-gray-400" />
                    <span className="font-medium">{nuevo}</span>
                  </p>
                  {it.asignado_por_nombre && (
                    <p className="text-xs text-gray-400 mt-0.5">por {it.asignado_por_nombre}</p>
                  )}
                </div>
              </li>
            )
          })}
        </ol>
      </CardContent>
    </Card>
  )
}

/**
 * Sub-seccion colapsable del detalle del lead. Patron patrón estándar
 * Lightning / patrón estándar: agrupa campos relacionados bajo un header
 * con icono. Default abierto vs cerrado segun importancia.
 */
function DetailSection({ title, icon, defaultOpen = false, children }) {
  const [open, setOpen] = useState(defaultOpen)
  return (
    <div className="border border-gray-200/80 dark:border-slate-800 rounded-lg overflow-hidden shadow-2xs">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center justify-between gap-2 px-3 py-2 bg-gray-50/80 hover:bg-gray-100 dark:bg-slate-800/80 dark:hover:bg-slate-800 transition-colors text-left cursor-pointer"
      >
        <span className="flex items-center gap-2 text-[11px] font-bold uppercase tracking-wider text-gray-700 dark:text-slate-100">
          <span className="text-gray-500 dark:text-indigo-400 flex items-center shrink-0">
            {icon}
          </span>
          {title}
        </span>
        <ChevronDown
          size={14}
          className={`text-gray-400 dark:text-slate-300 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>
      {open && (
        <div className="px-3 py-2.5 space-y-2 bg-white dark:bg-[#0e1626]">
          {children}
        </div>
      )}
    </div>
  )
}

/**
 * Fila label/value dentro de una DetailSection. Si value es falsy y no
 * hay render custom, muestra "—" en gris (consistente con UI previa).
 */
function DetailRow({ label, value, mono = false, render = null }) {
  return (
    <div className="flex gap-3">
      <dt className="text-xs font-medium text-gray-500 dark:text-slate-400 w-24 shrink-0 pt-0.5">{label}</dt>
      <dd className={`text-sm text-gray-800 dark:text-slate-100 flex-1 ${mono ? 'font-mono' : ''}`}>
        {render ? render(value) : (value || <span className="text-gray-400 dark:text-slate-600">—</span>)}
      </dd>
    </div>
  )
}


/**
 * V058: Origen Meta helpers fuera del componente para evitar
 * "Cannot create components during render" del lint en React Compiler.
 */
function _origenMetaFmt(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('es-PE', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch { return iso }
}

function _copyToClipboard(text) {
  if (!text) return
  try { navigator.clipboard?.writeText(text) } catch { /* noop */ }
}

function OrigenMetaField({ label, value, mono = true }) {
  return (
    <div className="flex items-start gap-3 group">
      <dt className="text-[11px] font-medium text-gray-500 w-28 shrink-0 pt-0.5">{label}</dt>
      <dd className={`text-xs flex-1 break-all ${mono ? 'font-mono text-gray-700' : 'text-gray-800'}`}>
        {value || <span className="text-gray-400 font-sans">—</span>}
      </dd>
      {value && (
        <button
          onClick={() => _copyToClipboard(value)}
          className="opacity-0 group-hover:opacity-100 transition-opacity text-gray-400 hover:text-indigo-600"
          title="Copiar"
          type="button"
        >
          <Copy size={11} />
        </button>
      )}
    </div>
  )
}

/**
 * V058: Origen Meta — muestra la jerarquía de Facebook/Instagram que
 * generó el lead: Campaign → Ad Set → Ad + Facebook Lead ID. Permite
 * copiar IDs al clipboard (debug, soporte, atribución manual).
 *
 * Solo se renderiza si hay al menos una interacción Meta. Lead manual
 * o de otro origen → la card queda oculta.
 */
function OrigenMetaCard({ items, open, onToggle }) {
  if (!items || items.length === 0) return null

  // El primero es la interacción más reciente (ORDER BY DESC en backend)
  const main = items[0]
  const olderCount = items.length - 1

  return (
    <Card>
      <CardHeader
        className="cursor-pointer hover:bg-gray-50 transition-colors"
        onClick={onToggle}
      >
        <CardTitle className="text-sm flex items-center justify-between gap-2">
          <span className="flex items-center gap-2">
            <Megaphone size={15} className="text-blue-600" /> Origen Meta
            <span className="text-[10px] font-normal text-gray-400">
              · {items.length} {items.length === 1 ? 'interacción' : 'interacciones'}
            </span>
          </span>
          <ChevronDown
            size={14}
            className={`text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`}
          />
        </CardTitle>
      </CardHeader>
      {open && (
        <CardContent className="space-y-3 pt-0">
          <div className="bg-blue-50/50 border border-blue-100 rounded-lg p-3">
            <dl className="space-y-2">
              <OrigenMetaField label="Facebook Lead ID" value={main.leadgen_id} />
              <OrigenMetaField label="Page ID" value={main.page_id} />

              {/* Campaña */}
              <div className="pt-2 mt-2 border-t border-blue-100">
                <div className="text-[10px] font-semibold text-blue-700 uppercase tracking-wide mb-1.5">
                  Jerarquía publicitaria
                </div>
                <OrigenMetaField label="Campaign" value={main.campaign_name} mono={false} />
                <OrigenMetaField label="Campaign ID" value={main.campaign_id} />
                <OrigenMetaField label="Ad Set Name" value={main.adset_name} mono={false} />
                <OrigenMetaField label="Ad Set ID" value={main.adset_id} />
                <OrigenMetaField label="Ad Name" value={main.ad_name} mono={false} />
                <OrigenMetaField label="Ad ID" value={main.ad_id} />
              </div>

              {/* Form */}
              {(main.form_name || main.form_id) && (
                <div className="pt-2 mt-2 border-t border-blue-100">
                  <OrigenMetaField label="Form" value={main.form_name} mono={false} />
                  <OrigenMetaField label="Form ID" value={main.form_id} />
                </div>
              )}

              {/* Metadata */}
              <div className="pt-2 mt-2 border-t border-blue-100 flex items-center justify-between text-[10px] text-gray-500">
                <span className="flex items-center gap-1">
                  <Clock size={10} /> {_origenMetaFmt(main.fecha_interaccion)}
                </span>
                {main.es_duplicado && (
                  <span className="px-1.5 py-0.5 bg-amber-100 text-amber-700 rounded font-semibold">
                    Duplicado
                  </span>
                )}
              </div>
            </dl>
          </div>

          {olderCount > 0 && (
            <div className="text-[11px] text-gray-500 italic">
              + {olderCount} interacción{olderCount > 1 ? 'es' : ''} previa{olderCount > 1 ? 's' : ''} (mismo cliente, otra campaña/anuncio)
            </div>
          )}
        </CardContent>
      )}
    </Card>
  )
}


/**
 * Antecedentes del lead: matches por telefono o DNI contra el historico
 * legacy (sistema anterior) y contra leads inactivos del propio CRM
 * (duplicados/reactivaciones). Compacto y colapsable — util para ver
 * de un vistazo si el cliente ya habia sido trabajado y por quien,
 * sin salir del detalle.
 */
function AntecedentesHistorial({
  items,
  summary = null,
  open,
  onToggle,
  canDerive = false,
  currentAsesorId = null,
  onDerive = null,
  derivingId = null,
}) {
  // V070.82: top 5 por defecto + boton "ver X mas" (patron estandar).
  const TOP_LIMIT = 5
  const [expandAll, setExpandAll] = useState(false)

  if (!items || items.length === 0) return null

  // V070.83: fecha incluye hora porque varios antecedentes del mismo dia
  // se ven indistinguibles. Patron consistente con otros cards (contactos,
  // llamadas) que muestran '16 may., 17:35'.
  const formatDate = (iso) => {
    if (!iso) return '—'
    try {
      const d = new Date(iso)
      const date = d.toLocaleDateString('es-PE', { day: '2-digit', month: 'short', year: 'numeric' })
      const time = d.toLocaleTimeString('es-PE', { hour: '2-digit', minute: '2-digit', hour12: false })
      return `${date}, ${time}`
    } catch { return iso }
  }

  const sourceLabel = (src) => {
    if (src === 'crm_activo')   return 'Duplicado activo'
    if (src === 'crm_inactivo') return 'Lead anterior'
    return 'Histórico'
  }
  const sourceClass = (src) => {
    if (src === 'crm_activo')   return 'bg-rose-50 text-rose-700 border-rose-200'
    if (src === 'crm_inactivo') return 'bg-indigo-50 text-indigo-700 border-indigo-200'
    return 'bg-amber-50 text-amber-700 border-amber-200'
  }

  // V070.83: ordenar items con asesor PRIMERO (mas accionables: tienen
  // boton Derivar) y sin asesor despues. Dentro de cada grupo se respeta
  // el orden de fecha desc que viene del backend (Array.sort es estable
  // en JS moderno).
  const sortedItems = [...items].sort((a, b) => {
    const aHas = a.asesor_id ? 1 : 0
    const bHas = b.asesor_id ? 1 : 0
    return bHas - aHas  // con asesor (1) antes que sin asesor (0)
  })

  const visibleItems = expandAll ? sortedItems : sortedItems.slice(0, TOP_LIMIT)
  const hiddenCount = sortedItems.length - visibleItems.length

  return (
    <Card>
      <CardHeader className="pb-2">
        <button
          type="button"
          onClick={onToggle}
          className="w-full flex items-center justify-between gap-2 text-left"
        >
          <CardTitle className="text-sm font-semibold text-amber-800 flex items-center gap-2">
            <Archive size={15} /> Antecedentes ({items.length})
          </CardTitle>
          <ChevronDown
            size={16}
            className={`text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`}
          />
        </button>
        {!open && (
          <p className="text-xs text-gray-500 mt-1">
            Este cliente ya figura en registros previos del sistema.
          </p>
        )}
      </CardHeader>
      {open && (
        <CardContent className="pt-0 space-y-3">
          {/* Summary box: razon del match + asesor */}
          {summary && (
            <AntecedentesSummary summary={summary} total={items.length} />
          )}
          <ol className="space-y-3">
            {visibleItems.map((h) => {
              // Botón Derivar: solo si el rol permite, hay asesor_id real
              // (excluye legacy), y no es el asesor actual del lead.
              const showDerive =
                canDerive &&
                !!h.asesor_id &&
                h.asesor_id !== currentAsesorId &&
                typeof onDerive === 'function'
              const isLoading = derivingId === h.asesor_id
              // V070.83: items SIN asesor se ven mas atenuados — son
              // contexto historico, no accionables (no se puede 'derivar
              // al asesor anterior' si no hay).
              const dim = !h.asesor_id
              return (
                <li
                  key={`${h.source}-${h.id}`}
                  className={`border rounded-md p-2.5 transition-colors ${
                    dim
                      ? 'border-gray-150 bg-gray-50/60 opacity-75'
                      : 'border-amber-100 bg-amber-50/40'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2 flex-wrap">
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className={`inline-flex items-center rounded-full px-1.5 py-0.5 text-[10px] font-medium border ${sourceClass(h.source)}`}>
                        {sourceLabel(h.source)}
                      </span>
                      <MatchReasonChips h={h} />
                      {h.proyecto && (
                        <Badge variant="secondary" className="text-[10px] capitalize">{h.proyecto}</Badge>
                      )}
                      {h.canal && (
                        <span className="text-[10px] text-gray-600 capitalize">· {h.canal}</span>
                      )}
                    </div>
                    <span className="text-[11px] text-gray-500">{formatDate(h.fecha_ingreso)}</span>
                  </div>
                  <div className="mt-1.5 space-y-0.5 text-xs text-gray-700">
                    {h.asesor_nombre && (
                      <p><span className="text-gray-500">Asesor anterior:</span> <span className="font-medium">{h.asesor_nombre}</span></p>
                    )}
                    {h.estado && (
                      <p><span className="text-gray-500">Estado:</span> <span className="font-medium">{h.estado}</span></p>
                    )}
                    {h.seguimiento && (
                      <p className="text-gray-600 truncate" title={h.seguimiento}>
                        <span className="text-gray-500">Seguimiento:</span> {h.seguimiento}
                      </p>
                    )}
                    {h.observaciones && (
                      <p className="text-gray-600 truncate" title={h.observaciones}>
                        <span className="text-gray-500">Obs:</span> {h.observaciones}
                      </p>
                    )}
                  </div>
                  {showDerive && (
                    <div className="mt-2 flex justify-end">
                      <button
                        type="button"
                        disabled={isLoading}
                        onClick={() => onDerive(h.asesor_id, h.asesor_nombre)}
                        className="inline-flex items-center gap-1 rounded-md border border-indigo-200 bg-white px-2 py-1 text-[11px] font-medium text-indigo-700 hover:bg-indigo-50 disabled:opacity-50 disabled:cursor-not-allowed"
                      >
                        {isLoading ? 'Derivando…' : `Derivar a ${h.asesor_nombre || 'asesor original'}`}
                      </button>
                    </div>
                  )}
                </li>
              )
            })}
          </ol>
          {/* Boton "Ver X mas" / "Mostrar menos" — mas prominente (V070.83) */}
          {items.length > TOP_LIMIT && (
            <div className="flex justify-center pt-2 border-t border-amber-100">
              <button
                type="button"
                onClick={() => setExpandAll(v => !v)}
                className="inline-flex items-center gap-2 px-4 py-2 text-xs font-semibold text-amber-800 bg-white hover:bg-amber-50 border-2 border-amber-200 hover:border-amber-300 rounded-full shadow-sm hover:shadow transition-all mt-2"
              >
                <ChevronDown
                  size={14}
                  className={`transition-transform ${expandAll ? 'rotate-180' : ''}`}
                />
                {expandAll
                  ? `Mostrar solo los primeros ${TOP_LIMIT}`
                  : `Ver los ${hiddenCount} restantes`}
              </button>
            </div>
          )}
        </CardContent>
      )}
    </Card>
  )
}

/**
 * V070.82: chips compactos que indican por qué este antecedente matcheó
 * con el lead actual. Util cuando hay 14 antecedentes y el operador no
 * entiende por qué aparecen — ahora ve que es por DNI compartido / mismo
 * teléfono / ambos.
 */
function MatchReasonChips({ h }) {
  const byTel = Boolean(h.match_telefono)
  const byDni = Boolean(h.match_dni)
  if (!byTel && !byDni) return null
  return (
    <>
      {byTel && (
        <span
          className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium bg-emerald-50 text-emerald-700 border border-emerald-200"
          title="Coincide el último teléfono normalizado"
        >
          <Phone size={10} /> mismo teléfono
        </span>
      )}
      {byDni && (
        <span
          className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-medium bg-blue-50 text-blue-700 border border-blue-200"
          title="Coincide el DNI"
        >
          <IdCard size={10} /> mismo DNI
        </span>
      )}
    </>
  )
}

/**
 * V070.82: resumen del card de antecedentes en 2 filas — primera fila
 * desglosa el match (por tel / por DNI / por ambos) y la segunda muestra
 * cuántos antecedentes ya tienen asesor asignado vs cuántos están en
 * cola. Permite leer el contexto del cliente en 2 segundos.
 */
function AntecedentesSummary({ summary, total }) {
  const { by_telefono = 0, by_dni = 0, by_ambos = 0, con_asesor = 0, sin_asesor = 0 } = summary
  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2 text-xs text-amber-900">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span className="font-semibold">{total} antecedente{total !== 1 ? 's' : ''}</span>
        <span className="text-amber-700">·</span>
        <SummaryStat label="por teléfono"     value={by_telefono} tone="emerald" />
        <SummaryStat label="por DNI"          value={by_dni}      tone="blue" />
        <SummaryStat label="por ambos"        value={by_ambos}    tone="purple" />
      </div>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 mt-1 text-[11px] text-amber-800">
        <SummaryStat label="con asesor" value={con_asesor} tone="gray" />
        <span className="text-amber-700">·</span>
        <SummaryStat label="en cola"    value={sin_asesor} tone="gray" />
      </div>
    </div>
  )
}

function SummaryStat({ label, value, tone = 'gray' }) {
  const toneMap = {
    emerald: 'text-emerald-700',
    blue:    'text-blue-700',
    purple:  'text-purple-700',
    gray:    'text-gray-700',
  }
  if (value === 0) {
    return <span className="text-gray-400">{value} {label}</span>
  }
  return (
    <span><span className={`font-semibold ${toneMap[tone] || toneMap.gray}`}>{value}</span> {label}</span>
  )
}

/**
 * V048: Re-engagement / Recontactos.
 *
 * Card que muestra cuándo y por qué fuentes el mismo cliente (mismo
 * teléfono) volvió a entrar al CRM después de su primer contacto.
 * Patrón patrón estándar 'Lead Recapture' / patrón estándar 'Re-engagement Workflow'.
 */
function RecontactosCard({ items, open, onToggle }) {
  if (!items || items.length === 0) return null

  const formatDate = (iso) => {
    if (!iso) return '—'
    try {
      return new Date(iso).toLocaleDateString('es-PE', {
        day: '2-digit', month: 'short', year: 'numeric',
        hour: '2-digit', minute: '2-digit',
      })
    } catch { return iso }
  }

  const estrategiaLabel = (e) => {
    if (e === 'mantener_asesor')      return { label: 'Asesor mantenido', cls: 'bg-emerald-50 text-emerald-700 border-emerald-200' }
    if (e === 'liberar_inactivo')     return { label: 'Asesor inactivo · liberado', cls: 'bg-amber-50 text-amber-700 border-amber-200' }
    if (e === 'liberar_sin_contacto') return { label: 'Sin contacto previo · liberado', cls: 'bg-sky-50 text-sky-700 border-sky-200' }
    if (e === 'sin_asesor_original')  return { label: 'Sin asesor previo', cls: 'bg-gray-50 text-gray-600 border-gray-200' }
    return { label: e || '—', cls: 'bg-gray-50 text-gray-600 border-gray-200' }
  }

  return (
    <Card className="border-violet-200 bg-violet-50/30">
      <CardHeader className="pb-2">
        <button
          type="button"
          onClick={onToggle}
          className="w-full flex items-center justify-between gap-2 text-left"
        >
          <CardTitle className="text-sm font-semibold text-violet-800 flex items-center gap-2">
            <Sparkles size={15} /> Re-engagement ({items.length})
          </CardTitle>
          <ChevronDown
            size={16}
            className={`text-gray-400 transition-transform ${open ? 'rotate-180' : ''}`}
          />
        </button>
        {!open && (
          <p className="text-xs text-gray-500 mt-1">
            Este cliente volvió a interesarse {items.length === 1 ? 'una vez' : `${items.length} veces`} por otra fuente.
          </p>
        )}
      </CardHeader>
      {open && (
        <CardContent className="pt-0">
          <p className="text-[11px] text-gray-500 mb-3 leading-relaxed">
            Cada fila es una vez que el mismo teléfono volvió a entrar al CRM por una fuente distinta.
            El asesor original mantiene el lead salvo que ya no esté activo en la empresa.
          </p>
          <ol className="space-y-2.5">
            {items.map((r) => {
              const est = estrategiaLabel(r.estrategia)
              return (
                <li key={r.id} className="bg-white border border-violet-100 rounded-md p-3 shadow-sm">
                  <div className="flex items-center gap-2 flex-wrap text-xs">
                    <span className="font-mono text-[10px] text-gray-400">{formatDate(r.created_at)}</span>
                    <span className={`text-[10px] px-1.5 py-0.5 rounded border font-semibold ${est.cls}`}>
                      {est.label}
                    </span>
                    {r.notificado && (
                      <span className="text-[10px] bg-blue-50 text-blue-700 border border-blue-200 px-1.5 py-0.5 rounded">
                        ✓ Notificado
                      </span>
                    )}
                  </div>
                  <div className="mt-1.5 grid grid-cols-2 gap-x-3 gap-y-0.5 text-[11px]">
                    {r.fuente_nombre && (
                      <div>
                        <span className="text-gray-500">Fuente:</span>{' '}
                        <span className="font-semibold text-gray-800">{r.fuente_nombre}</span>
                      </div>
                    )}
                    {r.api_client_nombre && (
                      <div>
                        <span className="text-gray-500">Proveedor:</span>{' '}
                        <span className="font-semibold text-gray-800">{r.api_client_nombre}</span>
                      </div>
                    )}
                    {/* V096.4 — Campaña/Form muestran nombre legible (resuelto via
                        meta_catalog_cache) con el ID en chico abajo. Para leads
                        viejos sin cache, sigue mostrando solo el ID (graceful). */}
                    {r.campana && (
                      <div className="col-span-2">
                        <span className="text-gray-500">Campaña:</span>{' '}
                        <span className="font-semibold text-gray-800">
                          {r.campaign_name || r.campana}
                        </span>
                        {r.campaign_name && r.campana && r.campaign_name !== r.campana && (
                          <div className="font-mono text-[10px] text-gray-400 ml-[58px]">{r.campana}</div>
                        )}
                      </div>
                    )}
                    {r.conjunto && (
                      <div className="col-span-2">
                        <span className="text-gray-500">Conjunto:</span>{' '}
                        <span className="font-semibold text-gray-800">{r.conjunto}</span>
                      </div>
                    )}
                    {r.anuncio && (
                      <div className="col-span-2">
                        <span className="text-gray-500">Anuncio:</span>{' '}
                        <span className="font-semibold text-gray-800">{r.anuncio}</span>
                      </div>
                    )}
                    {(r.form_name || r.fuente_form_id) && (
                      <div className="col-span-2">
                        <span className="text-gray-500">Form:</span>{' '}
                        <span className="font-semibold text-gray-800">
                          {r.form_name || r.fuente_form_id}
                        </span>
                        {r.form_name && r.fuente_form_id && r.form_name !== r.fuente_form_id && (
                          <div className="font-mono text-[10px] text-gray-400 ml-[34px]">{r.fuente_form_id}</div>
                        )}
                      </div>
                    )}
                    {r.asesor_mantenido_nombre && (
                      <div className="col-span-2">
                        <span className="text-gray-500">Asignado a:</span>{' '}
                        <span className="font-semibold text-gray-800">{r.asesor_mantenido_nombre}</span>
                      </div>
                    )}
                    {r.estado_lead_anterior && (
                      <div className="col-span-2">
                        <span className="text-gray-500">Estado al volver:</span>{' '}
                        <span className="font-semibold text-gray-800">{r.estado_lead_anterior}</span>
                      </div>
                    )}
                  </div>
                  {r.razon && (
                    <p className="text-[10px] text-gray-400 italic mt-1.5">{r.razon}</p>
                  )}
                </li>
              )
            })}
          </ol>
        </CardContent>
      )}
    </Card>
  )
}

const TIPOS_DEFAULT   = [
  { nombre: 'llamada',    label: 'Llamada' },
  { nombre: 'whatsapp',  label: 'WhatsApp' },
  { nombre: 'email',     label: 'Email' },
  { nombre: 'presencial',label: 'Presencial' },
  { nombre: 'nota',      label: 'Nota interna' },
]
const RESULTADOS_DEFAULT = [
  { nombre: '',              label: 'Seleccionar…' },
  { nombre: 'contesto',      label: 'Contestó' },
  { nombre: 'no_contesto',   label: 'No contestó' },
  { nombre: 'buzon',         label: 'Buzón de voz' },
  { nombre: 'cita_agendada', label: 'Cita agendada' },
  { nombre: 'no_interesado', label: 'No interesado' },
  { nombre: 'volver_llamar', label: 'Volver a llamar' },
]

/**
 * Formulario inline para editar un contacto existente.
 */
function EditContactoForm({ leadId, contacto, tipos, tiposCita = [], resultados, citaEstados = [], onSuccess, onOptimisticUpdate, onCancel }) {
  const parseLimaParts = (iso) => {
    if (!iso) return null
    const s = String(iso).trim()
    const hasTz = /[Zz]$|[+-]\d{2}(:\d{2})?$/.test(s)
    if (!hasTz) {
      const m = s.match(/(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/)
      if (m) return { date: `${m[1]}-${m[2]}-${m[3]}`, time: `${m[4]}:${m[5]}` }
    }
    try {
      let normalized = s.replace(' ', 'T')
      normalized = normalized.replace(/([+-]\d{2})$/, m => m + ':00')
      const d = new Date(normalized)
      if (!Number.isNaN(d.getTime())) {
        const dParts = new Intl.DateTimeFormat('en-CA', {
          timeZone: 'America/Lima',
          year: 'numeric', month: '2-digit', day: '2-digit',
        }).formatToParts(d)
        const dMap = Object.fromEntries(dParts.filter(p => p.type !== 'literal').map(p => [p.type, p.value]))

        const tParts = new Intl.DateTimeFormat('en-GB', {
          timeZone: 'America/Lima',
          hour: '2-digit', minute: '2-digit', hour12: false,
        }).formatToParts(d)
        const tMap = Object.fromEntries(tParts.filter(p => p.type !== 'literal').map(p => [p.type, p.value]))

        return { date: `${dMap.year}-${dMap.month}-${dMap.day}`, time: `${tMap.hour}:${tMap.minute}` }
      }
    } catch {}
    const m = s.match(/(\d{4})-(\d{2})-(\d{2})/)
    return m ? { date: `${m[1]}-${m[2]}-${m[3]}`, time: '09:00' } : null
  }

  const toDatePart = (iso) => {
    const parsed = parseLimaParts(iso)
    return parsed ? parsed.date : ''
  }
  const toTimePart = (iso) => {
    const parsed = parseLimaParts(iso)
    return parsed ? parsed.time : '09:00'
  }

  // V042 — id default 'pendiente' si hay cita sin estado guardado.
  // Asi al abrir edit con un contacto legacy (cita pero cita_estado_id=null),
  // el form arranca con Pendiente pre-seleccionado y, si el usuario no toca
  // nada, al guardar se persiste Pendiente en la DB. No mas estados vacios.
  const pendienteId = (citaEstados.find(e => (e.codigo || '').toLowerCase() === 'pendiente') || {}).id || null
  const initialEstadoId = contacto.cita_estado_id || (contacto.fecha_cita && pendienteId) || ''
  const defaultTipoCita = contacto.tipo_cita || (tiposCita[0]?.nombre || 'Cita oficina Bustamante')

  const [form, setForm] = useState({
    tipo_contacto:    contacto.tipo_contacto || 'llamada',
    tipo_cita:        defaultTipoCita,
    url_reunion:      contacto.url_reunion || '',
    resultado:        contacto.resultado || '',
    notas:            (contacto.notas && contacto.notas !== 'null') ? contacto.notas : '',
    fecha_cita_date:  toDatePart(contacto.fecha_cita),
    fecha_cita_time:  toTimePart(contacto.fecha_cita),
    cita_estado_id:   initialEstadoId,
  })
  // V042 fix — sincronizar form cuando cambia el contacto (e.g., el padre
  // refetchea tras guardar) O cuando llega el catalogo citaEstados (que
  // carga async y puede llegar despues del mount inicial).
  useEffect(() => {
    const pendId = (citaEstados.find(e => (e.codigo || '').toLowerCase() === 'pendiente') || {}).id || null
    const estadoId = contacto.cita_estado_id || (contacto.fecha_cita && pendId) || ''
    // Solo actualizamos si realmente cambia para no pisar la seleccion del
    // usuario mid-edit (e.g., poll refresh pasa nueva ref pero mismo valor).
    setForm(prev => ({
      ...prev,
      tipo_contacto:    contacto.tipo_contacto || 'llamada',
      tipo_cita:        contacto.tipo_cita || prev.tipo_cita || defaultTipoCita,
      url_reunion:      contacto.url_reunion || prev.url_reunion || '',
      resultado:        contacto.resultado || '',
      notas:            (contacto.notas && contacto.notas !== 'null') ? contacto.notas : '',
      fecha_cita_date:  toDatePart(contacto.fecha_cita),
      fecha_cita_time:  toTimePart(contacto.fecha_cita),
      // No pisar si el usuario ya cambio el valor en este render
      cita_estado_id:   prev.cita_estado_id || estadoId,
    }))
  }, [contacto.id, contacto.cita_estado_id, contacto.fecha_cita, contacto.tipo_cita, contacto.url_reunion, contacto.tipo_contacto, contacto.resultado, contacto.notas, citaEstados, defaultTipoCita])
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState(null)

  const isCita = form.resultado?.toLowerCase().includes('cita')
  const isVirtual = isCita && ((form.tipo_cita || '').toLowerCase().includes('virtual') || (form.tipo_cita || '').toLowerCase().includes('video') || (form.tipo_cita || '').toLowerCase().includes('meet') || (form.tipo_cita || '').toLowerCase().includes('zoom'))
  const set = (key) => (e) => setForm(p => ({ ...p, [key]: e.target.value }))

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (isCita && !form.fecha_cita_date) {
      setError('La fecha de la cita es obligatoria.')
      return
    }
    if (isCita && isVirtual && (!form.url_reunion || !form.url_reunion.trim())) {
      setError('La URL de la reunión (Meet, Zoom, etc.) es obligatoria para citas virtuales.')
      return
    }
    const fecha_cita = isCita && form.fecha_cita_date
      ? `${form.fecha_cita_date}T${form.fecha_cita_time || '09:00'}:00`
      : null

    // V042 — Solo validamos fecha pasada si el usuario CAMBIO la fecha.
    // Caso real: editar una cita historica (ya pasada) para marcarla como
    // Completada / Reprogramada / etc sin tocar la fecha. Si validamos
    // siempre, el flujo queda bloqueado y el supervisor nunca puede
    // registrar el resultado de citas que ya pasaron.
    const originalDate = toDatePart(contacto.fecha_cita)
    const originalTime = toTimePart(contacto.fecha_cita)
    const fechaCambio  = form.fecha_cita_date !== originalDate
                      || form.fecha_cita_time !== originalTime
    if (fecha_cita && fechaCambio) {
      const citaDate = new Date(fecha_cita)
      const now = new Date()
      if (citaDate < new Date(now.getTime() - 5 * 60 * 1000)) {
        setError('No puedes agendar una cita con fecha pasada.')
        return
      }
    }

    setIsSubmitting(true)
    setError(null)
    try {
      // V042: si es cita y el form tiene un cita_estado_id (porque el
      // usuario lo eligio O porque defaulteo a Pendiente al cargar), lo
      // enviamos. Si por algun motivo aun esta vacio, defaulteamos al
      // Pendiente del catalogo. Asi NUNCA enviamos null para una cita
      // valida — el supervisor siempre ve el estado.
      let citaEstadoIdToSend = null
      if (isCita) {
        if (form.cita_estado_id) {
          citaEstadoIdToSend = parseInt(form.cita_estado_id)
        } else {
          const pe = citaEstados.find(e => (e.codigo || '').toLowerCase() === 'pendiente')
          if (pe) citaEstadoIdToSend = pe.id
        }
      }
      const payload = {
        tipo_contacto: form.tipo_contacto,
        tipo_cita:     isCita ? form.tipo_cita : null,
        url_reunion:   isCita && isVirtual && form.url_reunion.trim() ? form.url_reunion.trim() : null,
        resultado:     form.resultado || null,
        notas:         form.notas || null,
        fecha_cita:    fecha_cita,
        cita_estado_id: citaEstadoIdToSend,
      }
      await api.patch(`/api/leads/${leadId}/contactos/${contacto.id}`, payload)

      // V042 — Optimistic update COMPREHENSIVO.
      if (typeof onOptimisticUpdate === 'function') {
        const ce = citaEstadoIdToSend
          ? citaEstados.find(e => e.id === citaEstadoIdToSend)
          : null
        onOptimisticUpdate({
          id: contacto.id,
          tipo_contacto: form.tipo_contacto,
          tipo_cita:     isCita ? form.tipo_cita : null,
          url_reunion:   isCita && isVirtual && form.url_reunion.trim() ? form.url_reunion.trim() : null,
          resultado:     form.resultado || null,
          notas:         form.notas || null,
          fecha_cita:    fecha_cita,
          ...(ce ? {
            cita_estado_id: ce.id,
            cita_estado_codigo: ce.codigo,
            cita_estado_nombre: ce.nombre,
            cita_estado_color: ce.color_hex,
          } : { cita_estado_id: null, cita_estado_nombre: null, cita_estado_color: null }),
        })
      }

      onSuccess()
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al guardar.')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="border border-amber-200 bg-amber-50/30 rounded-lg p-3">
      <form onSubmit={handleSubmit} className="space-y-2.5">
        <div className="grid grid-cols-2 gap-2">
          <div>
            <Label className="text-xs">Tipo</Label>
            <select value={form.tipo_contacto} onChange={set('tipo_contacto')}
              className="w-full mt-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-amber-500">
              {tipos.map(t => <option key={t.nombre} value={t.nombre}>{t.label}</option>)}
            </select>
          </div>
          <div>
            <Label className="text-xs">Resultado</Label>
            <select value={form.resultado} onChange={set('resultado')}
              className="w-full mt-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-amber-500">
              {resultados.map(r => <option key={r.nombre} value={r.nombre}>{r.label}</option>)}
            </select>
          </div>
        </div>

        {/* Fecha y hora — SIEMPRE montado, oculto con CSS */}
        <div style={{ display: isCita ? 'block' : 'none' }}>
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-2.5 space-y-2">
            <div>
              <Label className="text-xs text-amber-700 font-semibold mb-1 block">Tipo de cita <span className="text-red-500">*</span></Label>
              <select
                value={form.tipo_cita}
                onChange={set('tipo_cita')}
                className="w-full text-sm border border-amber-300 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-amber-500"
              >
                {tiposCita.length > 0 ? (
                  tiposCita.map(tc => (
                    <option key={tc.id || tc.nombre} value={tc.nombre}>
                      {tc.label || tc.nombre}
                    </option>
                  ))
                ) : (
                  <>
                    <option value="Cita oficina Bustamante">Cita oficina Bustamante</option>
                    <option value="Cita oficina Umacollo">Cita oficina Umacollo</option>
                    <option value="Cita exteriores">Cita exteriores</option>
                    <option value="Cita virtual">Cita virtual</option>
                  </>
                )}
              </select>
            </div>

            {/* URL de reunión si es virtual */}
            {isVirtual && (
              <div className="bg-white/80 border border-amber-300 rounded-lg p-2.5 space-y-1 animate-in fade-in duration-150">
                <Label className="text-xs text-amber-800 font-semibold flex items-center gap-1.5">
                  <Video size={13} className="text-amber-700" />
                  URL de la reunión (Meet / Zoom / Teams) <span className="text-red-500">*</span>
                </Label>
                <input
                  type="url"
                  value={form.url_reunion}
                  onChange={set('url_reunion')}
                  placeholder="https://meet.google.com/... o https://zoom.us/j/..."
                  required={isVirtual}
                  className="w-full text-sm border border-amber-300 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-amber-500"
                />
                <p className="text-[10px] text-amber-700/70">
                  Ingresa el enlace donde se llevará a cabo la videollamada.
                </p>
              </div>
            )}

            <Label className="text-xs text-amber-700 font-semibold">Fecha y hora de la cita <span className="text-red-500">*</span></Label>
            <div className="grid grid-cols-2 gap-2">
              <input type="date" value={form.fecha_cita_date} onChange={set('fecha_cita_date')}
                className="w-full text-sm border border-amber-300 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-amber-500" />
              {/* step=900 → opciones cada 15 min en el dropdown nativo. */}
              <input type="time" value={form.fecha_cita_time} onChange={set('fecha_cita_time')}
                step={900}
                className="w-full text-sm border border-amber-300 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-amber-500" />
            </div>
            <p className="text-[10px] text-amber-700/70 mt-1">
              Hora en formato 24h (ej. 09:00 = mañana, 21:00 = noche). Si tu
              navegador muestra AM/PM, usa las flechas ↑↓ o las teclas A/P.
            </p>

            {/* V042 — Estado de la cita: el supervisor / asesor lo marca
                tras la cita. Solo aparece al EDITAR (no al crear) y solo
                si el catalogo /api/cita-estados respondio (V042 aplicada).
                Pills mas grandes con icono + active state obvio (relleno
                + check + ring). UX premium tipo patrón estándar. */}
            {citaEstados.length > 0 && (
              <div className="pt-2 mt-1 border-t border-amber-200">
                <Label className="text-xs text-amber-700 font-semibold mb-1.5 block">Estado de la cita</Label>
                <div className="flex flex-wrap gap-2">
                  {citaEstados.map(ce => {
                    const active = String(form.cita_estado_id) === String(ce.id)
                    // Icono inferido del codigo del estado (paridad cross-row)
                    const code = (ce.codigo || ce.nombre || '').toLowerCase()
                    const Icon =
                      code.includes('pendiente')    ? Clock :
                      code.includes('completa')     ? CheckCircle :
                      code.includes('reprogram')    ? RefreshCw :
                      code.includes('cancel')       ? XCircle :
                      code.includes('asisti')       ? AlertCircle :
                      Calendar
                    return (
                      <button
                        type="button"
                        key={ce.id}
                        onClick={() => setForm(p => ({ ...p, cita_estado_id: ce.id }))}
                        className={`inline-flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg border-2 font-semibold transition-all ${
                          active ? 'shadow-md scale-[1.03]' : 'hover:scale-[1.02]'
                        }`}
                        style={active ? {
                          backgroundColor: ce.color_hex,
                          color: '#fff',
                          borderColor: ce.color_hex,
                        } : {
                          backgroundColor: '#fff',
                          color: ce.color_hex,
                          borderColor: ce.color_hex + '60',
                        }}
                      >
                        <Icon size={14} />
                        {ce.nombre}
                        {active && <Check size={14} strokeWidth={3} />}
                      </button>
                    )
                  })}
                </div>
                <p className="text-[10px] text-amber-700/70 mt-1.5">
                  Marca cómo terminó la cita. Esto ayuda al supervisor a medir efectividad.
                </p>
              </div>
            )}
          </div>
        </div>

        <div>
          <Label className="text-xs">Notas</Label>
          <textarea value={form.notas} onChange={set('notas')} rows={2}
            className="w-full mt-1 text-sm border border-gray-200 rounded-md px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-amber-500 resize-none" />
        </div>

        {error && (
          <div className="bg-red-50 border border-red-200 text-red-700 text-xs rounded px-3 py-1.5">{error}</div>
        )}
        <div className="flex gap-2 justify-end">
          <Button type="button" variant="outline" size="sm" onClick={onCancel}>Cancelar</Button>
          <Button type="submit" size="sm" disabled={isSubmitting} className="gap-1.5 bg-amber-600 hover:bg-amber-700 text-white">
            <Save size={12} />
            {isSubmitting ? 'Guardando…' : 'Guardar cambios'}
          </Button>
        </div>
      </form>
    </div>
  )
}

/**
 * V041.4 — heuristica que sugiere un nuevo estado para el lead segun
 * el contacto que se acaba de registrar. Inspirado en el comportamiento
 * de CRMs profesionales: cuando registras una actividad significativa,
 * el sistema te ofrece avanzar la etapa del deal sin obligarte.
 *
 * Reglas (texto-insensitive sobre `resultado`):
 *   - Estado actual final (Ganado/Perdido/No interesado/Historico) → null
 *   - resultado contiene "no interesa" / "rechaz"           → No interesado
 *   - resultado contiene "compr" / "firm" / "ganad"         → Ganado
 *   - Nuevo + cualquier contacto                            → Contactado
 *   - Contactado + "cita" / "calific" / "interesa"          → Calificado
 *   - Calificado + "cita" / "negocia" / "propuesta"         → En negociacion
 *   - resto                                                 → null
 */
function suggestNextEstadoId(currentEstadoNombre, resultado, estadoCatalog) {
  const normTxt = (s) => (s || '').toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '').trim()
  const finals = new Set(['ganado', 'perdido', 'no interesado', 'historico'])
  const cur = normTxt(currentEstadoNombre)
  if (finals.has(cur)) return null

  const r = (resultado || '').toLowerCase()
  const findId = (nombre) => {
    const target = normTxt(nombre)
    const found = estadoCatalog.find(
      e => normTxt(e.nombre) === target
    )
    return found ? found.id : null
  }

  if (r.includes('no interesa') || r.includes('rechaz')) return findId('No interesado')
  if (r.includes('compr') || r.includes('firm') || r.includes('ganad')) return findId('Ganado')

  if (cur === 'nuevo')         return findId('Contactado')
  if (cur === 'contactado')    {
    if (r.includes('cita') || r.includes('calific') || r.includes('interesa')) return findId('Calificado')
  }
  if (cur === 'calificado') {
    if (r.includes('cita') || r.includes('negocia') || r.includes('propuesta')) return findId('En negociación')
  }
  return null
}

/**
 * V051 — Edicion inline de notas + resultado en una llamada del cel.
 * Las llamadas vienen del sync APK con duracion + tipo + telefono ya
 * capturados por el OS (no se editan). Aqui solo agregamos el contexto
 * humano: notas y resultado.
 */
function LlamadaEditForm({ llamada, resultados, onSaved, onCancel }) {
  const [notas, setNotas] = useState(llamada.notas || '')
  const [resultado, setResultado] = useState(llamada.resultado || '')
  const [saving, setSaving] = useState(false)

  const handleSave = async () => {
    setSaving(true)
    try {
      await onSaved({ notas: notas || null, resultado: resultado || null })
    } finally { setSaving(false) }
  }

  return (
    <div className="mt-2 pt-2 border-t border-gray-100 space-y-2">
      <div>
        <Label className="text-[11px]">Resultado</Label>
        <select
          value={resultado}
          onChange={e => setResultado(e.target.value)}
          className="w-full mt-0.5 text-xs border border-gray-200 rounded-md px-2 py-1 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
        >
          <option value="">— Sin resultado —</option>
          {(resultados || []).map(r => (
            <option key={r.nombre} value={r.nombre}>{r.label}</option>
          ))}
        </select>
      </div>
      <div>
        <Label className="text-[11px]">Notas</Label>
        <textarea
          value={notas}
          onChange={e => setNotas(e.target.value)}
          rows={2}
          placeholder="Ej: Cliente pidió volver a llamar el jueves..."
          className="w-full mt-0.5 text-xs border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
        />
      </div>
      <div className="flex gap-1.5 justify-end">
        <Button variant="outline" size="sm" onClick={onCancel} disabled={saving} className="h-7 text-xs">
          Cancelar
        </Button>
        <Button size="sm" onClick={handleSave} disabled={saving} className="h-7 text-xs gap-1">
          <Save size={11} /> {saving ? 'Guardando…' : 'Guardar'}
        </Button>
      </div>
    </div>
  )
}

/**
 * Formulario para registrar un nuevo contacto.
 * Fecha y hora de cita siempre montados en el DOM (ocultos con CSS).
 * Todo controlado con estado React normal.
 */
function NuevoContactoForm({ leadId, tipos, tiposCita = [], resultados, estados = [], currentEstadoId, currentEstadoNombre, onSuccess, onCancel, defaultTipo, defaultTipoCita, defaultResultado }) {
  // V070.44 — Default = primer item del catalogo.
  const primerTipo = defaultTipo
    || (Array.isArray(tipos) && tipos[0]?.nombre)
    || 'llamada';
  const primerTipoCita = defaultTipoCita
    || (Array.isArray(tiposCita) && tiposCita[0]?.nombre)
    || 'Cita oficina Bustamante';

  const [form, setForm] = useState({
    tipo_contacto: primerTipo,
    tipo_cita: primerTipoCita,
    url_reunion: '',
    resultado: defaultResultado || '',
    notas: '',
    proxima_accion: '',
    fecha_proxima_accion_date: '',
    fecha_proxima_accion_time: '09:00',
    fecha_cita_date: '',
    fecha_cita_time: '09:00',
    duracion_minutos: '',
    nuevo_estado_id: '',
  })
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [estadoTouched, setEstadoTouched] = useState(false)

  // Sincronizar tipo_cita si llegan tiposCita async
  useEffect(() => {
    if (tiposCita.length > 0 && (!form.tipo_cita || !tiposCita.some(t => t.nombre === form.tipo_cita))) {
      setForm(p => ({ ...p, tipo_cita: defaultTipoCita || tiposCita[0].nombre }))
    }
  }, [tiposCita, defaultTipoCita])

  const isCita = form.resultado?.toLowerCase().includes('cita')
  const isVirtual = isCita && ((form.tipo_cita || '').toLowerCase().includes('virtual') || (form.tipo_cita || '').toLowerCase().includes('video') || (form.tipo_cita || '').toLowerCase().includes('meet') || (form.tipo_cita || '').toLowerCase().includes('zoom'))

  // Sugerencia recalculada segun el resultado seleccionado.
  const suggestedEstadoId = useMemo(
    () => suggestNextEstadoId(currentEstadoNombre, form.resultado, estados),
    [currentEstadoNombre, form.resultado, estados]
  )

  // Aplicar la sugerencia automaticamente cuando cambia y el usuario aun
  // no ha tocado el selector. Esto da el "magic feeling" tipo patrón estándar.
  useEffect(() => {
    if (estadoTouched) return
    if (suggestedEstadoId && String(suggestedEstadoId) !== form.nuevo_estado_id) {
      setForm(p => ({ ...p, nuevo_estado_id: String(suggestedEstadoId) }))
    }
  }, [suggestedEstadoId, estadoTouched, form.nuevo_estado_id])

  const suggestedEstadoNombre = suggestedEstadoId
    ? (estados.find(e => e.id === suggestedEstadoId)?.nombre || '')
    : ''

  const set = (key) => (e) => setForm(p => ({ ...p, [key]: e.target.value }))

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!form.tipo_contacto) {
      setError('El tipo de contacto es requerido.')
      return
    }
    if (isCita && !form.fecha_cita_date) {
      setError('La fecha de la cita es obligatoria.')
      return
    }
    if (isCita && isVirtual && (!form.url_reunion || !form.url_reunion.trim())) {
      setError('La URL de la reunión (Meet, Zoom, etc.) es obligatoria para citas virtuales.')
      return
    }

    // Construir fecha_cita ISO
    let fecha_cita = null
    if (isCita && form.fecha_cita_date) {
      fecha_cita = `${form.fecha_cita_date}T${form.fecha_cita_time || '09:00'}:00`
    }

    // Construir fecha_proxima_accion ISO (con hora)
    let fecha_proxima_accion = null
    if (!isCita && form.fecha_proxima_accion_date) {
      fecha_proxima_accion = `${form.fecha_proxima_accion_date}T${form.fecha_proxima_accion_time || '09:00'}:00`
    }

    // V041.4: si el usuario eligio cambiar de estado (sea por sugerencia
    // automatica o por override manual) lo enviamos; el backend ya soporta
    // nuevo_estado_id en ContactoIn y aplica el cambio en la misma tx.
    const nuevoEstadoIdInt = form.nuevo_estado_id ? parseInt(form.nuevo_estado_id) : null
    const willChangeEstado = nuevoEstadoIdInt && nuevoEstadoIdInt !== currentEstadoId

    const payload = {
      tipo_contacto:        form.tipo_contacto,
      tipo_cita:            isCita ? form.tipo_cita : null,
      url_reunion:          isCita && isVirtual && form.url_reunion.trim() ? form.url_reunion.trim() : null,
      resultado:            form.resultado || null,
      notas:                form.notas || null,
      proxima_accion:       form.proxima_accion || null,
      fecha_proxima_accion: fecha_proxima_accion,
      fecha_cita:           fecha_cita,
      duracion_minutos:     form.duracion_minutos ? parseInt(form.duracion_minutos) : null,
      nuevo_estado_id:      willChangeEstado ? nuevoEstadoIdInt : null,
    }

    setIsSubmitting(true)
    setError(null)
    try {
      await api.post(`/api/agenda/contacto/${leadId}`, payload)
      onSuccess()
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al registrar el contacto.')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <Card className="border-indigo-200 bg-indigo-50/30">
      <CardContent className="pt-4">
        <form onSubmit={handleSubmit} className="space-y-3">
          <div className={['llamada', 'video llamada'].includes(form.tipo_contacto) ? 'grid grid-cols-3 gap-3' : 'grid grid-cols-2 gap-3'}>
            <div>
              <Label className="text-xs">Tipo de contacto</Label>
              <select value={form.tipo_contacto} onChange={set('tipo_contacto')}
                className="w-full mt-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500">
                {tipos.map(t => <option key={t.nombre} value={t.nombre}>{t.label}</option>)}
              </select>
            </div>
            <div>
              <Label className="text-xs">Resultado</Label>
              <select value={form.resultado} onChange={set('resultado')}
                className="w-full mt-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500">
                {resultados.map(r => <option key={r.nombre} value={r.nombre}>{r.label}</option>)}
              </select>
            </div>
            {['llamada', 'video llamada'].includes(form.tipo_contacto) && (
              <div>
                <Label className="text-xs">Duración (min) <span className="text-gray-400 font-normal">opc.</span></Label>
                <Input
                  type="number"
                  min="0"
                  value={form.duracion_minutos}
                  onChange={set('duracion_minutos')}
                  placeholder="Ej: 5"
                  className="h-8 text-sm mt-1"
                  title="Cuánto duró la llamada en minutos"
                />
              </div>
            )}
          </div>

          {/* Fecha y hora de cita — SIEMPRE montado, oculto con CSS cuando no es cita */}
          <div style={{ display: isCita ? 'block' : 'none' }}>
            <div className="bg-indigo-50 border border-indigo-200 rounded-xl p-3 space-y-2.5">
              <p className="text-xs font-semibold text-indigo-700 flex items-center gap-1.5">
                <Calendar size={12} /> Datos de la cita
              </p>
              <div>
                <Label className="text-xs text-indigo-700 font-semibold">Tipo de cita <span className="text-red-500">*</span></Label>
                <select
                  value={form.tipo_cita}
                  onChange={set('tipo_cita')}
                  className="w-full mt-1 text-sm border border-indigo-300 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  {tiposCita.length > 0 ? (
                    tiposCita.map(tc => (
                      <option key={tc.id || tc.nombre} value={tc.nombre}>
                        {tc.label || tc.nombre}
                      </option>
                    ))
                  ) : (
                    <>
                      <option value="Cita oficina Bustamante">Cita oficina Bustamante</option>
                      <option value="Cita oficina Umacollo">Cita oficina Umacollo</option>
                      <option value="Cita exteriores">Cita exteriores</option>
                      <option value="Cita virtual">Cita virtual</option>
                    </>
                  )}
                </select>
              </div>

              {/* URL de reunión si es virtual */}
              {isVirtual && (
                <div className="bg-white/80 border border-indigo-200 rounded-lg p-2.5 space-y-1 animate-in fade-in duration-150">
                  <Label className="text-xs text-indigo-700 font-semibold flex items-center gap-1.5">
                    <Video size={13} className="text-indigo-600" />
                    URL de la reunión (Meet / Zoom / Teams) <span className="text-red-500">*</span>
                  </Label>
                  <input
                    type="url"
                    value={form.url_reunion}
                    onChange={set('url_reunion')}
                    placeholder="https://meet.google.com/... o https://zoom.us/j/..."
                    required={isVirtual}
                    className="w-full text-sm border border-indigo-300 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                  <p className="text-[10px] text-indigo-700/70">
                    Ingresa el enlace donde se llevará a cabo la videollamada.
                  </p>
                </div>
              )}

              <div className="grid grid-cols-2 gap-2">
                <div>
                  <Label className="text-xs text-indigo-700">Fecha <span className="text-red-500">*</span></Label>
                  <input type="date" value={form.fecha_cita_date} onChange={set('fecha_cita_date')}
                    className="w-full mt-1 text-sm border border-indigo-300 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500" />
                </div>
                <div>
                  <Label className="text-xs text-indigo-700">Hora <span className="text-red-500">*</span></Label>
                  <input type="time" value={form.fecha_cita_time} onChange={set('fecha_cita_time')}
                    className="w-full mt-1 text-sm border border-indigo-300 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500" />
                </div>
              </div>
            </div>
          </div>

          <div>
            <Label className="text-xs">Notas</Label>
            <textarea value={form.notas} onChange={set('notas')} rows={2} placeholder="Descripción del contacto..."
              className="w-full mt-1 text-sm border border-gray-200 rounded-md px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none" />
          </div>

          <div style={{ display: isCita ? 'none' : 'block' }}>
            <div className="flex flex-col sm:flex-row items-stretch sm:items-start gap-3">
              <div className="flex-1 min-w-[180px]">
                <Label className="text-xs font-medium text-gray-700 dark:text-slate-300 block mb-1">
                  Próxima acción
                </Label>
                <Input
                  value={form.proxima_accion}
                  onChange={set('proxima_accion')}
                  placeholder="ej: Enviar propuesta"
                  className="h-9 text-sm bg-white dark:bg-slate-900 border-gray-200 dark:border-slate-700 text-gray-900 dark:text-slate-100"
                />
              </div>
              <div className="w-full sm:w-[160px] shrink-0">
                <Label className="text-xs font-medium text-gray-700 dark:text-slate-300 block mb-1">
                  Fecha próx. acción
                </Label>
                <input
                  type="date"
                  value={form.fecha_proxima_accion_date}
                  onChange={set('fecha_proxima_accion_date')}
                  className="h-9 w-full text-sm border border-gray-200 dark:border-slate-700 rounded-md px-3 py-1.5 bg-white dark:bg-slate-900 text-gray-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>
              <div className="w-full sm:w-[115px] shrink-0">
                <Label className="text-xs font-medium text-gray-700 dark:text-slate-300 flex items-center gap-1 mb-1">
                  <Clock size={12} className="text-indigo-600 dark:text-indigo-400 shrink-0" />
                  <span>Hora</span>
                </Label>
                <input
                  type="time"
                  value={form.fecha_proxima_accion_time}
                  onChange={set('fecha_proxima_accion_time')}
                  className="h-9 w-full text-sm border border-gray-200 dark:border-slate-700 rounded-md px-2.5 py-1.5 bg-white dark:bg-slate-900 text-gray-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>
            </div>
            {form.fecha_proxima_accion_date && (
              <p className="text-[11px] text-indigo-600 dark:text-indigo-400 mt-1.5 flex items-center gap-1.5 font-medium">
                <Clock size={11} className="shrink-0" />
                Alerta programada: el sistema emitirá una alerta 1 hora antes ({form.fecha_proxima_accion_time || '09:00'}).
              </p>
            )}
          </div>

          {/* V041.4 — Sugeridor de cambio de estado. Aparece solo si hay
              estados en el catalogo y el lead no esta en estado final.
              Pre-selecciona el estado sugerido por la heuristica; el
              usuario puede confirmar (default), elegir otro o "Mantener
              actual" para no cambiar. Patron CRMs profesionales:
              cuando logueas una actividad, el sistema te ofrece avanzar
              la etapa sin obligarte. */}
          {estados.length > 0 && currentEstadoNombre && (() => {
            const finals = ['ganado', 'perdido', 'no interesado', 'histórico', 'historico']
            if (finals.includes((currentEstadoNombre || '').toLowerCase())) return null
            return (
              <div className="bg-gradient-to-r from-indigo-50 to-violet-50 border border-indigo-200 rounded-xl p-3 space-y-2">
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <p className="text-xs font-semibold text-indigo-700 flex items-center gap-1.5">
                    ⚡ Avanzar estado del lead
                    <span className="text-[10px] font-normal text-indigo-500 italic">
                      (opcional, recomendado tras cada contacto)
                    </span>
                  </p>
                  <span className="text-[11px] text-gray-500">
                    Actual: <span className="font-medium text-gray-800">{currentEstadoNombre}</span>
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <Label className="text-xs text-indigo-700 shrink-0">Cambiar a</Label>
                  <select
                    value={form.nuevo_estado_id}
                    onChange={e => {
                      setEstadoTouched(true)
                      setForm(p => ({ ...p, nuevo_estado_id: e.target.value }))
                    }}
                    className="flex-1 text-sm border border-indigo-300 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  >
                    <option value="">— Mantener actual —</option>
                    {estados
                      .filter(e => e.id !== currentEstadoId)
                      .map(e => (
                        <option key={e.id} value={e.id}>
                          {e.nombre}
                          {suggestedEstadoId === e.id ? ' · sugerido' : ''}
                        </option>
                      ))}
                  </select>
                </div>
                {form.nuevo_estado_id && parseInt(form.nuevo_estado_id) !== currentEstadoId && (
                  <p className="text-[11px] text-indigo-600">
                    Al guardar pasará de <span className="font-semibold">{currentEstadoNombre}</span>
                    {' → '}
                    <span className="font-semibold">
                      {estados.find(e => e.id === parseInt(form.nuevo_estado_id))?.nombre}
                    </span>
                  </p>
                )}
                {!form.nuevo_estado_id && suggestedEstadoNombre && (
                  <p className="text-[11px] text-gray-500 italic">
                    Sugerencia descartada — el estado se mantendrá en {currentEstadoNombre}.
                  </p>
                )}
              </div>
            )
          })()}

          {error && (
            <div className="bg-red-50 border border-red-200 text-red-700 text-xs rounded px-3 py-2">{error}</div>
          )}

          <div className="flex gap-2 justify-end pt-1">
            <Button type="button" variant="outline" size="sm" onClick={onCancel}>
              Cancelar
            </Button>
            <Button type="submit" size="sm" disabled={isSubmitting} className="gap-1.5">
              <Save size={13} />
              {isSubmitting ? 'Guardando…' : 'Registrar contacto'}
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  )
}

/**
 * Formulario de edición de datos del lead.
 */
// V028: la calidad es configurable desde `crm.catalogo_calidad`. El valor
// persistido en `lead.calidad` es el `codigo` (FRIO / TIBIO / CALIENTE o el
// que el admin haya creado). El badge usa el `color_hex` del catálogo como
// fuente de verdad, sin hardcodear clases de Tailwind por valor.
function CalidadBadge({ value, catalog = [] }) {
  if (!value) return <span className="text-gray-400">—</span>
  const entry = catalog.find(c => c.codigo === value)
  // Fallback si el valor no está en el catálogo (eliminado / legacy):
  // mostramos el código crudo con estilo neutro para no romper la UI.
  if (!entry) {
    return (
      <span className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold border bg-gray-50 text-gray-700 border-gray-200">
        {value}
      </span>
    )
  }
  const color = entry.color_hex || '#64748b'
  return (
    <span
      className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold border"
      style={{
        backgroundColor: `${color}1a`,  // ~10% alpha
        color,
        borderColor: `${color}4d`,       // ~30% alpha
      }}
    >
      {entry.nombre || entry.codigo}
    </span>
  )
}

// V040 — heuristica para inferir el tipo de documento desde el valor crudo.
// La columna `crm.leads.dni` es TEXT y guarda solo el codigo; el tipo no se
// persiste. Al editar, infierimos por longitud y composicion para que el
// selector arranque con la opcion correcta sin sorprender al usuario.
function inferDocumentType(value) {
  const v = (value || '').trim().toUpperCase()
  if (!v) return 'DNI'
  // Cualquier letra → Pasaporte (DNI/CE son siempre numericos)
  if (/[A-Z]/.test(v)) return 'Pasaporte'
  if (/^\d{8}$/.test(v)) return 'DNI'
  if (/^\d{9}$/.test(v)) return 'CE'
  return 'DNI'
}

function EditLeadForm({ lead, estados, sedes = [], onSave, onCancel, canAssign, asesores, teamGroups, calidadCatalog = [], fuentes = [] }) {
  // FLS (ADR-0011 Sprint 5): el form respeta los flags `field.leads.<x>.edit`
  // del rol del usuario. Si no puede editar, el input se deshabilita.
  // Si tampoco puede leer, el field se oculta entero (el value ya viene
  // enmascarado del backend, asi que no hay leak por defaults).
  const { user: _editUser } = useAuthStore()
  const _canReadTelefono  = canReadField(_editUser, 'leads', 'telefono')
  const _canEditTelefono  = canEditField(_editUser, 'leads', 'telefono')
  const _canReadEmail     = canReadField(_editUser, 'leads', 'email')
  const _canEditEmail     = canEditField(_editUser, 'leads', 'email')
  const _canReadObs       = canReadField(_editUser, 'leads', 'observaciones')
  const _canEditObs       = canEditField(_editUser, 'leads', 'observaciones')
  // V069.5 — Campaña UX world-class (patrón estándar de la industria):
  // En vez de mostrar el campaign_id raw de TikTok/Meta (ej. "1858117249047009"),
  // mostramos el nombre legible si existe ("palmeras 26"). Guardamos el ID
  // y el nombre originales para detectar si el usuario cambio el valor:
  //   - Si lo dejo igual al nombre original → preservamos el ID raw al guardar
  //     (mantiene el link al meta_catalog_cache).
  //   - Si lo cambio a texto distinto → se persiste el texto como nuevo
  //     campana (override intencional del usuario).
  const initialCampanaDisplay = lead.campana_nombre || lead.campana || ''
  const _origCampanaRaw     = useRef(lead.campana || '')
  const _origCampanaDisplay = useRef(initialCampanaDisplay)

  const [form, setForm] = useState({
    nombres:       lead.nombres || '',
    apellidos:     lead.apellidos || '',
    telefono:      lead.telefono || '',
    email:         lead.email || '',
    // V041: tipo_documento ya viene persistido del backend. Si por algun
    // motivo viene vacio (datos legacy creados antes de V041), caemos al
    // inferDocumentType heuristico para que el selector arranque coherente.
    tipo_documento: lead.tipo_documento || inferDocumentType(lead.dni),
    dni:           lead.dni || '',
    campana:       initialCampanaDisplay,
    observaciones: lead.observaciones || '',
    // V060.1: convertir a string para que el <select value=...> matchee
    // las <option value={String(s.id)}>. Sin esto, number vs string podia
    // dejar el dropdown sin seleccion visible aun teniendo estado_id valido.
    estado_id:     lead.estado_id != null ? String(lead.estado_id) : '',
    // V095.11 — fuente_id editable. Antes solo se podia cambiar via PATCH
    // directo al backend; ahora la UI lo expone para admin/supervisor.
    fuente_id:     lead.fuente_id != null ? String(lead.fuente_id) : '',
    codigo_convenio: lead.codigo_convenio || '',
    asesor_id:     lead.asesor_id || '',
    ciudad:        lead.ciudad || '',
    // V067.4: trabajo expuesto en la UI (el backend siempre lo persistio,
    // pero solo se editaba via mobile/LeadFormScreen y merge dialog).
    trabajo:       lead.trabajo || '',
    calidad:       lead.calidad || '',
    // V065: sede de destino. Cadena vacia = "sin sede" en el form, se
    // convierte a null al enviar (el backend acepta null para limpiar).
    sede_id:       lead.sede_id || '',
    // V102: campos específicos por estado
    fecha_proxima_gestion: lead.fecha_proxima_gestion ? (() => {
      try {
        const d = new Date(lead.fecha_proxima_gestion)
        if (!isNaN(d.getTime())) {
          const tzOffset = d.getTimezoneOffset() * 60000
          return new Date(d.getTime() - tzOffset).toISOString().slice(0, 16)
        }
      } catch {}
      return ''
    })() : '',
    accion_proxima_gestion: lead.accion_proxima_gestion || '',
    motivo_perdida: lead.motivo_perdida || '',
    motivo_perdida_otro: lead.motivo_perdida_otro || '',
    tipo_cierre: lead.tipo_cierre || '',
    segunda_voz: lead.segunda_voz || '',
    // V060: 'proyecto' y 'estrategia' ya no se editan desde la UI.
    // Si hay datos legacy se preservan en DB pero no se envian en el PATCH.
  })
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const [fieldErrors, setFieldErrors] = useState({})
  // V070.98 — warning suave (amber, no rojo) para campos con legacy data
  // invalida. No bloquea submit. patrón estándar "fix when you can".
  const [fieldWarnings, setFieldWarnings] = useState({})
  // V070.98 — capturar el telefono inicial cargado para dirty-validation.
  // Si el usuario no cambio el campo, preservamos legacy aunque sea junk.
  const _origTelefono = useRef(lead.telefono || '')

  // Determinar si la segunda_voz previa matchea con algún asesor o es custom/otro
  const initialSegundaVozMatch = useMemo(() => {
    if (!lead.segunda_voz) return { select: '', otro: '' }
    const matched = (asesores || []).some(u => {
      const n = u.nombre_completo || `${u.first_name || ''} ${u.last_name || ''}`.trim() || u.username
      return n === lead.segunda_voz
    })
    if (matched || !asesores || asesores.length === 0) {
      return { select: lead.segunda_voz, otro: '' }
    }
    return { select: '__otro__', otro: lead.segunda_voz }
  }, [lead.segunda_voz, asesores])

  const [segundaVozSelect, setSegundaVozSelect] = useState(initialSegundaVozMatch.select)
  const [segundaVozOtro, setSegundaVozOtro] = useState(initialSegundaVozMatch.otro)

  const isConvenio = useMemo(() => {
    if (!form.fuente_id) return Boolean(form.codigo_convenio)
    const f = (fuentes || []).find(x => String(x.id) === String(form.fuente_id))
    return f?.nombre?.toLowerCase().includes('convenio') || Boolean(form.codigo_convenio)
  }, [form.fuente_id, form.codigo_convenio, fuentes])

  // V070.98 — Warning live: si el form arranca con legacy junk (caso
  // Leonardo Bellido = +51999999999), mostramos el warning amber al cargar.
  // Sin esto el usuario veria el border gris hasta hacer submit fallido.
  useEffect(() => {
    if (form.telefono && form.telefono.trim()) {
      const r = normalizePhonePEEdit(form.telefono, _origTelefono.current)
      setFieldWarnings(p => ({ ...p, telefono: r.warning || undefined }))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.telefono])

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!form.nombres && !form.apellidos) {
      setError('Se requiere al menos nombre o apellido.')
      return
    }
    // Validacion de documento por tipo (mismo patron que NuevoLead).
    const errors = {}
    const warnings = {}
    if (form.dni && form.dni.trim()) {
      const v = form.dni.trim().toUpperCase()
      if (form.tipo_documento === 'DNI' && !/^\d{8}$/.test(v)) {
        errors.dni = 'El DNI debe tener exactamente 8 dígitos.'
      } else if (form.tipo_documento === 'CE' && !/^\d{9}$/.test(v)) {
        errors.dni = 'El Carnet de Extranjería debe tener 9 dígitos.'
      } else if (form.tipo_documento === 'Pasaporte' && !/^[A-Z0-9]{6,12}$/.test(v)) {
        errors.dni = 'El pasaporte debe tener entre 6 y 12 caracteres alfanuméricos.'
      }
    }
    // V070.98 — patrón estándar dirty validation: si el usuario no cambio
    // el telefono y es legacy junk, permitimos guardar con warning suave.
    // Bloqueamos solo cuando el usuario tipea un valor NUEVO invalido.
    let normalizedPhone = form.telefono
    if (form.telefono && form.telefono.trim()) {
      const r = normalizePhonePEEdit(form.telefono, _origTelefono.current)
      if (!r.valid) {
        errors.telefono = r.error || 'Número de teléfono inválido.'
      } else {
        normalizedPhone = r.normalized
        if (r.warning) warnings.telefono = r.warning
      }
    }

    if (canAssign && !form.fuente_id) {
      errors.fuente_id = 'La fuente es obligatoria.'
    }

    if (isConvenio && !form.codigo_convenio?.trim()) {
      errors.codigo_convenio = 'Debe indicar el código de convenio.'
    }

    // V102 — Validaciones específicas según el estado seleccionado
    const selectedEstadoObj = (estados || []).find(e => String(e.id) === String(form.estado_id))
    const isSeg = isEstadoSeguimiento(selectedEstadoObj?.nombre)
    const isOpor = isEstadoOportunidadFutura(selectedEstadoObj?.nombre)
    const isPerd = isEstadoPerdido(selectedEstadoObj?.nombre)
    const isMatr = isEstadoMatricula(selectedEstadoObj?.nombre)
    const isSup = _editUser?.role === 'supervisor'

    if (isSeg) {
      if (!form.fecha_proxima_gestion || !form.fecha_proxima_gestion.trim()) {
        errors.fecha_proxima_gestion = 'La fecha y hora de próxima gestión es obligatoria para este estado.'
      }
    }

    if (isOpor) {
      if (!form.fecha_proxima_gestion || !form.fecha_proxima_gestion.trim()) {
        errors.fecha_proxima_gestion = 'La fecha y hora programada es obligatoria para Oportunidad futura.'
      }
      if (!form.accion_proxima_gestion || !form.accion_proxima_gestion.trim()) {
        errors.accion_proxima_gestion = 'Debe indicar la acción a realizar en esa fecha.'
      }
    }

    if (isPerd) {
      if (!form.motivo_perdida) {
        errors.motivo_perdida = 'Debe seleccionar un motivo de pérdida.'
      } else if (form.motivo_perdida === 'Otro' && (!form.motivo_perdida_otro || !form.motivo_perdida_otro.trim())) {
        errors.motivo_perdida_otro = 'Debe digitar el motivo específico en el campo de texto libre.'
      }
    }

    if (isMatr) {
      const effectiveTipoCierre = form.tipo_cierre || 'Cierre autónomo'
      if (!effectiveTipoCierre) {
        errors.tipo_cierre = 'Debe seleccionar el tipo de cierre de forma obligatoria.'
      } else if (effectiveTipoCierre === 'Con segunda voz') {
        const finalSegundaVoz = (segundaVozSelect === '__otro__' ? segundaVozOtro : (segundaVozSelect || form.segunda_voz))?.trim()
        if (!finalSegundaVoz) {
          errors.segunda_voz = 'Debe indicar la persona que realizó la segunda voz.'
        }
      }
    }

    setFieldWarnings(warnings)
    if (Object.keys(errors).length > 0) {
      setFieldErrors(errors)
      return
    }
    setFieldErrors({})
    setIsSubmitting(true)
    setError(null)
    try {
      // V069.5 — Campaña: si el usuario NO cambio el valor mostrado (que
      // era el nombre legible), preservamos el ID raw original al guardar.
      // Asi el link a meta_catalog_cache se mantiene intacto.
      // Si el usuario lo cambio a texto distinto, se persiste lo nuevo
      // (override intencional del usuario, ej. corregir un nombre).
      const campanaToSend = (form.campana === _origCampanaDisplay.current)
        ? _origCampanaRaw.current
        : form.campana

      const patchData = {
        ...form,
        telefono:  normalizedPhone,
        campana:   campanaToSend,
        estado_id: form.estado_id ? parseInt(form.estado_id) : undefined,
        // V095.11 — fuente_id editable. Vacio = no enviar (no sobreescribir).
        // El backend valida FLS: admin + supervisor pueden, asesor recibe 403.
        fuente_id: form.fuente_id ? parseInt(form.fuente_id) : undefined,
        codigo_convenio: form.codigo_convenio ? form.codigo_convenio.trim() : null,
        asesor_id: form.asesor_id || null,
        // V065: sede vacia → null explicito para limpiar la sede del lead
        sede_id:   form.sede_id || null,
        // V102 / V111: Campos específicos
        fecha_proxima_gestion: (isSeg || isOpor) && form.fecha_proxima_gestion ? new Date(form.fecha_proxima_gestion).toISOString() : null,
        accion_proxima_gestion: isOpor && form.accion_proxima_gestion ? form.accion_proxima_gestion.trim() : null,
        motivo_perdida: isPerd ? (form.motivo_perdida || null) : null,
        motivo_perdida_otro: isPerd && form.motivo_perdida === 'Otro' ? (form.motivo_perdida_otro?.trim() || null) : null,
        tipo_cierre: isMatr ? (form.tipo_cierre || 'Cierre autónomo') : null,
        segunda_voz: isMatr && (form.tipo_cierre === 'Con segunda voz')
          ? ((segundaVozSelect === '__otro__' ? segundaVozOtro : (segundaVozSelect || form.segunda_voz))?.trim() || null)
          : null,
      }

      // V041: tipo_documento ya se persiste — lo enviamos en el PATCH para
      // que el backend lo guarde junto con el codigo crudo en `dni`.
      await api.patch(`/api/leads/${lead.id}`, patchData)
      onSave()
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al guardar los cambios.')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {/* 📇 Identidad y contacto — los datos personales del lead */}
      <DetailSection title="Identidad y contacto" icon={<User size={12} className="text-gray-500" />} defaultOpen>
        <div className="grid grid-cols-2 gap-3 mb-3">
          <div>
            <Label className="text-xs">Nombres</Label>
            <Input value={form.nombres} onChange={e => setForm(p => ({ ...p, nombres: e.target.value }))} className="mt-1" />
          </div>
          <div>
            <Label className="text-xs">Apellidos</Label>
            <Input value={form.apellidos} onChange={e => setForm(p => ({ ...p, apellidos: e.target.value }))} className="mt-1" />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-3 mb-3">
          {_canReadTelefono && (
            <div>
              <Label className="text-xs">Teléfono</Label>
              <div className="flex mt-1">
                <span className="inline-flex items-center px-3 text-sm rounded-l-md border border-r-0 border-gray-200 bg-gray-50 text-gray-500 font-mono select-none">
                  +51
                </span>
                <input
                  type="tel"
                  value={form.telefono.replace(/^\+?51/, '')}
                  onChange={e => {
                    const digits = e.target.value.replace(/\D/g, '').slice(0, 9)
                    setForm(p => ({ ...p, telefono: digits ? '+51' + digits : '' }))
                    if (fieldErrors.telefono) setFieldErrors(p => ({ ...p, telefono: undefined }))
                    if (fieldWarnings.telefono) setFieldWarnings(p => ({ ...p, telefono: undefined }))
                  }}
                  placeholder="987 654 321"
                  maxLength={9}
                  disabled={!_canEditTelefono}
                  className={`flex-1 min-w-0 border rounded-r-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:bg-gray-50 disabled:text-gray-500 disabled:cursor-not-allowed ${
                    fieldErrors.telefono ? 'border-red-400'
                    : fieldWarnings.telefono ? 'border-amber-400'
                    : 'border-gray-200'
                  }`}
                />
              </div>
              {!_canEditTelefono && (
                <p className="text-[10px] text-gray-400 mt-0.5">Tu rol no puede editar este campo.</p>
              )}
              {fieldErrors.telefono && <p className="text-xs text-red-500 mt-0.5">{fieldErrors.telefono}</p>}
              {!fieldErrors.telefono && fieldWarnings.telefono && (
                <p className="text-xs text-amber-600 mt-0.5">⚠️ {fieldWarnings.telefono}</p>
              )}
            </div>
          )}
          {_canReadEmail && (
            <div>
              <Label className="text-xs">Email</Label>
              <Input
                type="email"
                value={form.email}
                onChange={e => setForm(p => ({ ...p, email: e.target.value }))}
                disabled={!_canEditEmail}
                className="mt-1 disabled:bg-gray-50 disabled:text-gray-500 disabled:cursor-not-allowed"
              />
              {!_canEditEmail && (
                <p className="text-[10px] text-gray-400 mt-0.5">Tu rol no puede editar este campo.</p>
              )}
            </div>
          )}
        </div>
        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className="text-xs">Documento</Label>
            {/* V040 — selector de tipo + input adaptativo. */}
            <div className="flex mt-1">
              <select
                value={form.tipo_documento}
                onChange={e => setForm(p => ({ ...p, tipo_documento: e.target.value, dni: '' }))}
                className="text-sm rounded-l-md border border-r-0 border-gray-200 bg-gray-50 text-gray-700 px-2 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                title="Tipo de documento"
              >
                <option value="DNI">DNI</option>
                <option value="CE">CE</option>
                <option value="Pasaporte">Pasaporte</option>
              </select>
              <Input
                value={form.dni}
                inputMode={form.tipo_documento === 'Pasaporte' ? 'text' : 'numeric'}
                maxLength={
                  form.tipo_documento === 'DNI' ? 8
                    : form.tipo_documento === 'CE' ? 9 : 12
                }
                placeholder={
                  form.tipo_documento === 'DNI' ? '12345678'
                    : form.tipo_documento === 'CE' ? '001234567' : 'AB123456'
                }
                onChange={e => {
                  const raw = e.target.value
                  let cleaned
                  if (form.tipo_documento === 'Pasaporte') {
                    cleaned = raw.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 12)
                  } else if (form.tipo_documento === 'CE') {
                    cleaned = raw.replace(/\D/g, '').slice(0, 9)
                  } else {
                    cleaned = raw.replace(/\D/g, '').slice(0, 8)
                  }
                  setForm(p => ({ ...p, dni: cleaned }))
                }}
                className={`flex-1 min-w-0 rounded-l-none rounded-r-md ${fieldErrors.dni ? 'border-red-400' : ''}`}
              />
            </div>
            {fieldErrors.dni && <p className="text-xs text-red-500 mt-0.5">{fieldErrors.dni}</p>}
          </div>
          <div>
            <Label className="text-xs">Ciudad</Label>
            <Input
              value={form.ciudad}
              onChange={e => setForm(p => ({ ...p, ciudad: e.target.value }))}
              placeholder="Ej. Arequipa"
              className="mt-1"
            />
          </div>
        </div>

        {/* V067.4: Trabajo / cargo — info de perfil, util para personalizar
            la conversacion con el lead. Se persiste en crm.leads.trabajo. */}
        <div className="mt-3">
          <Label className="text-xs">Trabajo / Cargo</Label>
          <Input
            value={form.trabajo}
            onChange={e => setForm(p => ({ ...p, trabajo: e.target.value }))}
            placeholder="Ej. Ingeniero, Independiente, Comerciante"
            className="mt-1"
          />
        </div>

        {/* V065: Sede de destino — info operativa (donde sera atendido
            el cliente), va aca y NO en Comercial/Tracking. Solo aparece
            si hay sedes configuradas en el catalogo. */}
        {sedes.length > 0 && (
          <div className="mt-3">
            <Label className="text-xs flex items-center gap-1.5">
              <MapPin size={11} className="text-gray-400" /> Sede de destino
            </Label>
            <select
              value={form.sede_id || ''}
              onChange={e => setForm(p => ({ ...p, sede_id: e.target.value }))}
              className="w-full mt-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="">— Sin sede —</option>
              {sedes.map(s => (
                <option key={s.id} value={s.id}>
                  {s.ciudad ? `${s.nombre} · ${s.ciudad}` : s.nombre}
                </option>
              ))}
            </select>
          </div>
        )}
      </DetailSection>

      {/* 💼 Comercial — campaña ocupa fila completa (suelen ser nombres
          largos), calidad + estado emparejados (ambos clasifican el lead). */}
      <DetailSection title="Comercial" icon={<Tag size={12} className="text-gray-500" />} defaultOpen>
        <div className="mb-3">
          <Label className="text-xs flex items-center gap-1">
            Campaña
            <span
              className="text-gray-300 text-[10px] cursor-help"
              title="Campaña incluye el proyecto/desarrollo. Ej: 'ILLARY D9 10% inicial' o 'Test Mayo 2026'."
            >ⓘ</span>
          </Label>
          <Input
            value={form.campana}
            onChange={e => setForm(p => ({ ...p, campana: e.target.value }))}
            className="mt-1"
            placeholder="Ej: Campaña Mayo 2026"
          />
          {/* V069.5 — Helper text con el ID externo de Meta/TikTok cuando
              existe Y es distinto del nombre. Da contexto al usuario sobre
              la trazabilidad del lead sin saturar el input. */}
          {_origCampanaRaw.current
            && _origCampanaDisplay.current
            && _origCampanaRaw.current !== _origCampanaDisplay.current && (
            <p className="text-[10px] text-gray-400 mt-1 font-mono">
              ID externo: {_origCampanaRaw.current}
            </p>
          )}
        </div>

        {/* V095.11 — Fuente editable. Solo admin + supervisor (canAssign).
            El asesor NO puede cambiar la atribucion de marketing — esto
            protege la integridad de los reportes por canal. El field-level
            security del backend rechaza la edicion de fuente_id para
            asesores con un 403 explicito. */}
        {canAssign && (
          <div className="mb-3">
            <Label className="text-xs flex items-center gap-1">
              Fuente <span className="text-red-400">*</span>
              <span
                className="text-gray-300 text-[10px] cursor-help"
                title="Canal/estrategia de origen del lead. Ej: Facebook, Instagram, Activación, Referido."
              >ⓘ</span>
            </Label>
            <select
              value={form.fuente_id}
              onChange={e => setForm(p => ({ ...p, fuente_id: e.target.value }))}
              className={`w-full mt-1 text-sm border rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                fieldErrors.fuente_id ? 'border-red-400' : 'border-gray-200'
              }`}
            >
              <option value="">— Seleccionar fuente —</option>
              {(fuentes || []).filter(f => f.activo !== false).map(f => (
                <option key={f.id} value={String(f.id)}>{f.nombre}</option>
              ))}
            </select>
            {fieldErrors.fuente_id && (
              <p className="text-xs text-red-500 mt-0.5">{fieldErrors.fuente_id}</p>
            )}
            <p className="text-[10px] text-gray-400 mt-1">
              Cambiar la fuente afecta los reportes de atribución. Solo cámbiala si fue mal clasificada al ingresar.
            </p>
          </div>
        )}

        {isConvenio && (
          <div className="mb-3">
            <Label className="text-xs">
              Código de convenio <span className="text-red-400">*</span>
            </Label>
            <Input
              value={form.codigo_convenio}
              onChange={e => setForm(p => ({ ...p, codigo_convenio: e.target.value }))}
              placeholder="Ej: CONV-2026 / PNP / MINEDU"
              className={`mt-1 ${fieldErrors.codigo_convenio ? 'border-red-400' : ''}`}
            />
            {fieldErrors.codigo_convenio && (
              <p className="text-xs text-red-500 mt-0.5">{fieldErrors.codigo_convenio}</p>
            )}
          </div>
        )}

        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className="text-xs">Calidad</Label>
            <select
              value={form.calidad}
              onChange={e => setForm(p => ({ ...p, calidad: e.target.value }))}
              className="w-full mt-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="">— sin clasificar —</option>
              {calidadCatalog.map(c => (
                <option key={c.codigo} value={c.codigo}>{c.nombre || c.codigo}</option>
              ))}
            </select>
          </div>
          <div>
            <Label className="text-xs">Estado</Label>
            <select
              value={form.estado_id != null ? String(form.estado_id) : ''}
              onChange={e => {
                const newEstadoId = e.target.value
                const targetEst = (estados || []).find(st => String(st.id) === String(newEstadoId))
                setForm(p => {
                  const next = { ...p, estado_id: newEstadoId }
                  if (isEstadoMatricula(targetEst?.nombre) && !p.tipo_cierre) {
                    next.tipo_cierre = 'Cierre autónomo'
                  }
                  return next
                })
                if (fieldErrors.estado_id) setFieldErrors(p => ({ ...p, estado_id: undefined }))
              }}
              className="w-full mt-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="">— Seleccionar —</option>
              {(estados || []).map(s => (
                <option key={s.id} value={String(s.id)}>{s.nombre}</option>
              ))}
            </select>
          </div>
        </div>

        {/* V102: Formulario condicional para En seguimiento */}
        {(() => {
          const selectedEstadoObj = (estados || []).find(e => String(e.id) === String(form.estado_id))
          if (!isEstadoSeguimiento(selectedEstadoObj?.nombre)) return null
          return (
            <div className="mt-3 p-3 bg-blue-50/70 border border-blue-200 rounded-lg space-y-2 animate-in fade-in">
              <Label className="text-xs font-semibold text-blue-950 flex items-center gap-1.5">
                <Calendar size={13} className="text-blue-600" />
                Fecha y hora de próxima acción <span className="text-red-500">*</span>
              </Label>
              <Input
                type="datetime-local"
                value={form.fecha_proxima_gestion}
                onChange={e => setForm(p => ({ ...p, fecha_proxima_gestion: e.target.value }))}
                required
                className={`bg-white ${fieldErrors.fecha_proxima_gestion ? 'border-red-400' : ''}`}
              />
              {fieldErrors.fecha_proxima_gestion && (
                <p className="text-xs text-red-500">{fieldErrors.fecha_proxima_gestion}</p>
              )}
              <p className="text-[10px] text-blue-700">
                Obligatorio para programar la próxima acción. El sistema emitirá una alerta 1 hora antes al asesor y supervisor.
              </p>
            </div>
          )
        })()}

        {/* Formulario condicional para Oportunidad Futura */}
        {(() => {
          const selectedEstadoObj = (estados || []).find(e => String(e.id) === String(form.estado_id))
          if (!isEstadoOportunidadFutura(selectedEstadoObj?.nombre)) return null
          return (
            <div className="mt-3 p-3 bg-purple-50/70 border border-purple-200 rounded-lg space-y-2.5 animate-in fade-in">
              <Label className="text-xs font-semibold text-purple-950 flex items-center gap-1.5">
                <Calendar size={13} className="text-purple-600" />
                Fecha y hora de próxima acción <span className="text-red-500">*</span>
              </Label>
              <Input
                type="datetime-local"
                value={form.fecha_proxima_gestion}
                onChange={e => setForm(p => ({ ...p, fecha_proxima_gestion: e.target.value }))}
                required
                className={`bg-white ${fieldErrors.fecha_proxima_gestion ? 'border-red-400' : ''}`}
              />
              {fieldErrors.fecha_proxima_gestion && (
                <p className="text-xs text-red-500">{fieldErrors.fecha_proxima_gestion}</p>
              )}

              <Label className="text-xs font-semibold text-purple-950 flex items-center gap-1.5 pt-1">
                Acción a realizar <span className="text-red-500">*</span>
              </Label>
              <Input
                type="text"
                list="acciones-oportunidad-options-detalle"
                placeholder="Ej: Llamar para coordinar inicio, enviar oferta por WhatsApp..."
                value={form.accion_proxima_gestion}
                onChange={e => setForm(p => ({ ...p, accion_proxima_gestion: e.target.value }))}
                required
                className={`bg-white text-xs ${fieldErrors.accion_proxima_gestion ? 'border-red-400' : ''}`}
              />
              <datalist id="acciones-oportunidad-options-detalle">
                {ACCIONES_OPORTUNIDAD_FUTURA_OPCIONES.filter(opt => opt !== 'Otro').map(opt => (
                  <option key={opt} value={opt} />
                ))}
              </datalist>
              {fieldErrors.accion_proxima_gestion && (
                <p className="text-xs text-red-500">{fieldErrors.accion_proxima_gestion}</p>
              )}
            </div>
          )
        })()}

        {/* V102: Formulario condicional para Perdido */}
        {(() => {
          const selectedEstadoObj = (estados || []).find(e => String(e.id) === String(form.estado_id))
          if (!isEstadoPerdido(selectedEstadoObj?.nombre)) return null
          return (
            <div className="mt-3 p-3 bg-rose-50/70 border border-rose-200 rounded-lg space-y-2.5 animate-in fade-in">
              <Label className="text-xs font-semibold text-rose-950 flex items-center gap-1.5">
                <AlertCircle size={13} className="text-rose-600" />
                Motivo de pérdida <span className="text-red-500">*</span>
              </Label>
              <select
                value={form.motivo_perdida}
                onChange={e => setForm(p => ({ ...p, motivo_perdida: e.target.value }))}
                className={`w-full text-sm border rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-rose-500 ${
                  fieldErrors.motivo_perdida ? 'border-red-400' : 'border-gray-200'
                }`}
              >
                <option value="">— Seleccionar motivo de pérdida —</option>
                {MOTIVOS_PERDIDA_OPCIONES.map(m => (
                  <option key={m} value={m}>{m}</option>
                ))}
                {form.motivo_perdida && !MOTIVOS_PERDIDA_OPCIONES.includes(form.motivo_perdida) && (
                  <option key={form.motivo_perdida} value={form.motivo_perdida}>
                    {form.motivo_perdida} (actual)
                  </option>
                )}
              </select>
              {fieldErrors.motivo_perdida && (
                <p className="text-xs text-red-500">{fieldErrors.motivo_perdida}</p>
              )}

              {form.motivo_perdida === 'Otro' && (
                <div className="pt-1">
                  <Label className="text-xs font-semibold text-rose-950">
                    Especifique el motivo <span className="text-red-500">*</span>
                  </Label>
                  <textarea
                    value={form.motivo_perdida_otro}
                    onChange={e => setForm(p => ({ ...p, motivo_perdida_otro: e.target.value }))}
                    rows={2}
                    placeholder="Detalle el motivo específico…"
                    className={`w-full mt-1 text-sm border rounded-md p-2 bg-white focus:outline-none focus:ring-2 focus:ring-rose-500 resize-none ${
                      fieldErrors.motivo_perdida_otro ? 'border-red-400' : 'border-gray-200'
                    }`}
                  />
                  {fieldErrors.motivo_perdida_otro && (
                    <p className="text-xs text-red-500">{fieldErrors.motivo_perdida_otro}</p>
                  )}
                </div>
              )}
            </div>
          )
        })()}

        {/* Formulario condicional para Matrícula / Cierre */}
        {(() => {
          const selectedEstadoObj = (estados || []).find(e => String(e.id) === String(form.estado_id))
          if (!isEstadoMatricula(selectedEstadoObj?.nombre)) return null
          const currentTipoCierre = form.tipo_cierre || 'Cierre autónomo'
          return (
            <div className="mt-3 p-3.5 bg-emerald-50/70 border border-emerald-200 rounded-lg space-y-3 animate-in fade-in">
              <div className="flex items-center gap-2 text-emerald-950 font-semibold text-xs">
                <UserCheck size={14} className="text-emerald-600 shrink-0" />
                <span>Datos de Venta y Cierre</span>
              </div>

              <div>
                <Label className="text-xs font-semibold text-gray-700">
                  Tipo de cierre <span className="text-red-500">*</span>
                </Label>
                <div className="grid grid-cols-2 gap-2 mt-1.5">
                  <label
                    className={`flex items-center gap-2 p-2.5 rounded-lg border text-xs cursor-pointer transition-all ${
                      currentTipoCierre === 'Cierre autónomo'
                        ? 'bg-emerald-50 border-emerald-400 font-medium text-emerald-900 shadow-2xs'
                        : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    <input
                      type="radio"
                      name="edit_lead_tipo_cierre"
                      value="Cierre autónomo"
                      checked={currentTipoCierre === 'Cierre autónomo'}
                      onChange={() => {
                        setForm(p => ({ ...p, tipo_cierre: 'Cierre autónomo' }))
                        if (fieldErrors.tipo_cierre) setFieldErrors(p => ({ ...p, tipo_cierre: undefined }))
                      }}
                      className="text-emerald-600 focus:ring-emerald-500"
                    />
                    <span>Cierre autónomo</span>
                  </label>

                  <label
                    className={`flex items-center gap-2 p-2.5 rounded-lg border text-xs cursor-pointer transition-all ${
                      currentTipoCierre === 'Con segunda voz'
                        ? 'bg-emerald-50 border-emerald-400 font-medium text-emerald-900 shadow-2xs'
                        : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                    }`}
                  >
                    <input
                      type="radio"
                      name="edit_lead_tipo_cierre"
                      value="Con segunda voz"
                      checked={currentTipoCierre === 'Con segunda voz'}
                      onChange={() => {
                        setForm(p => ({ ...p, tipo_cierre: 'Con segunda voz' }))
                        if (fieldErrors.tipo_cierre) setFieldErrors(p => ({ ...p, tipo_cierre: undefined }))
                      }}
                      className="text-emerald-600 focus:ring-emerald-500"
                    />
                    <span>Con segunda voz</span>
                  </label>
                </div>
                {fieldErrors.tipo_cierre && (
                  <p className="text-xs text-red-500 mt-1">{fieldErrors.tipo_cierre}</p>
                )}
              </div>

              {currentTipoCierre === 'Con segunda voz' && (
                <div className="pt-1 animate-in fade-in space-y-1.5">
                  <Label className="text-xs font-semibold text-gray-700">
                    Persona que realizó la segunda voz <span className="text-red-500">*</span>
                  </Label>
                  {asesores && asesores.length > 0 ? (
                    <div className="space-y-1.5">
                      <select
                        value={segundaVozSelect}
                        onChange={(e) => {
                          const val = e.target.value
                          setSegundaVozSelect(val)
                          if (val !== '__otro__') {
                            setForm(p => ({ ...p, segunda_voz: val }))
                            setSegundaVozOtro('')
                          } else {
                            setForm(p => ({ ...p, segunda_voz: segundaVozOtro }))
                          }
                          if (fieldErrors.segunda_voz) setFieldErrors(p => ({ ...p, segunda_voz: undefined }))
                        }}
                        className={`w-full text-sm border rounded-md px-2.5 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-emerald-500 ${
                          fieldErrors.segunda_voz ? 'border-red-400' : 'border-gray-200'
                        }`}
                      >
                        <option value="">— Seleccionar usuario / asesor —</option>
                        {asesores.map((u) => {
                          const nombre = u.nombre_completo || `${u.first_name || ''} ${u.last_name || ''}`.trim() || u.username
                          return (
                            <option key={u.id || nombre} value={nombre}>
                              {nombre} {u.role ? `(${u.role})` : ''}
                            </option>
                          )
                        })}
                        <option value="__otro__">Otro (escribir nombre)…</option>
                      </select>
                      {segundaVozSelect === '__otro__' && (
                        <Input
                          placeholder="Nombre de la persona que realizó la segunda voz"
                          value={segundaVozOtro}
                          onChange={(e) => {
                            const val = e.target.value
                            setSegundaVozOtro(val)
                            setForm(p => ({ ...p, segunda_voz: val }))
                            if (fieldErrors.segunda_voz) setFieldErrors(p => ({ ...p, segunda_voz: undefined }))
                          }}
                          className={`mt-1 bg-white ${fieldErrors.segunda_voz ? 'border-red-400' : ''}`}
                          autoFocus
                        />
                      )}
                    </div>
                  ) : (
                    <Input
                      placeholder="Nombre de la persona que realizó la segunda voz"
                      value={form.segunda_voz}
                      onChange={(e) => {
                        setForm(p => ({ ...p, segunda_voz: e.target.value }))
                        if (fieldErrors.segunda_voz) setFieldErrors(p => ({ ...p, segunda_voz: undefined }))
                      }}
                      className={`mt-1 bg-white ${fieldErrors.segunda_voz ? 'border-red-400' : ''}`}
                    />
                  )}
                  {fieldErrors.segunda_voz && (
                    <p className="text-xs text-red-500 mt-0.5">{fieldErrors.segunda_voz}</p>
                  )}
                </div>
              )}
            </div>
          )
        })()}
      </DetailSection>

      {/* 🎯 Asignación — solo si el rol puede reasignar */}
      {canAssign && (
        <DetailSection title="Asignación" icon={<UserPlus size={12} className="text-gray-500" />} defaultOpen>
          <div>
            <Label className="text-xs">Asesor asignado</Label>
            <select
              value={form.asesor_id}
              onChange={e => setForm(p => ({ ...p, asesor_id: e.target.value }))}
              className="w-full mt-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="">Sin asignar</option>
              {Array.isArray(teamGroups) && teamGroups.length > 0 ? (
                teamGroups.map(g => (
                  <optgroup
                    key={g.supervisor_id}
                    label={
                      g.supervisor_id === '__supers__'
                        ? (g.supervisor_nombre || 'Supervisores')
                        : `Equipo: ${g.supervisor_nombre || ''}`
                    }
                  >
                    {(g.asesores || []).map(a => (
                      <option key={a.id} value={a.id}>
                        {a.nombre_completo || a.username}
                      </option>
                    ))}
                  </optgroup>
                ))
              ) : (
                (asesores || []).map(a => (
                  <option key={a.id} value={a.id}>{a.nombre_completo || a.username}</option>
                ))
              )}
            </select>
          </div>
        </DetailSection>
      )}

      {/* 📝 Observaciones */}
      {_canReadObs && (
        <DetailSection title="Observaciones" icon={<FileText size={12} className="text-gray-500" />} defaultOpen>
          <textarea
            value={form.observaciones}
            onChange={e => setForm(p => ({ ...p, observaciones: e.target.value }))}
            rows={3}
            placeholder="Notas del asesor sobre el lead…"
            disabled={!_canEditObs}
            className="w-full text-sm border border-gray-200 rounded-md px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none disabled:bg-gray-50 disabled:text-gray-500 disabled:cursor-not-allowed"
          />
          {!_canEditObs && (
            <p className="text-[10px] text-gray-400 mt-0.5">Tu rol no puede editar este campo.</p>
          )}
        </DetailSection>
      )}

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded px-3 py-2">
          {error}
        </div>
      )}
      <div className="flex gap-2 justify-end pt-1">
        <Button type="button" variant="outline" size="sm" onClick={onCancel}>
          <X size={13} className="mr-1" /> Cancelar
        </Button>
        <Button type="submit" size="sm" disabled={isSubmitting} className="gap-1.5">
          <Save size={13} />
          {isSubmitting ? 'Guardando…' : 'Guardar cambios'}
        </Button>
      </div>
    </form>
  )
}

export default function LeadDetalle() {
  const { id } = useParams()
  const navigate = useNavigate()
  const { user } = useAuthStore()
  const { estados, fuentes, loadCatalogs } = useCrmStore()
  const role = user?.role || 'asesor'
  const canEdit   = hasPermission(user, 'leads.edit')
  const canAssign = role === 'admin' || role === 'supervisor' || hasPermission(user, 'asignacion.manage')
  const canCreateCita = hasPermission(user, 'agenda.edit')
  const canCreateContact = hasPermission(user, 'agenda.edit') || hasPermission(user, 'leads.edit')
  const [contactPerms, setContactPerms] = useState({ asesor_can_edit: false, asesor_can_delete: false })

  const [activeTab, setActiveTab] = useState('detalle') // 'detalle' | 'historial'
  const [historialCount, setHistorialCount] = useState(0)
  const [duplicateCandidates, setDuplicateCandidates] = useState([])
  const [showMergeModal, setShowMergeModal] = useState(false)
  const [lead, setLead]           = useState(null)
  const [contactos, setContactos] = useState([])
  const [llamadas, setLlamadas]   = useState([])
  const [llamadasTotal, setLlamadasTotal] = useState(0)
  const [asignaciones, setAsignaciones] = useState([])
  const [antecedentes, setAntecedentes] = useState([])
  const [antecedentesSummary, setAntecedentesSummary] = useState(null)
  const [propiedades, setPropiedades] = useState([])
  const [recontactos, setRecontactos] = useState([])
  const [origenMeta, setOrigenMeta] = useState([])     // V058
  const [showAntecedentes, setShowAntecedentes] = useState(false)
  const [showRecontactos, setShowRecontactos] = useState(true)
  const [showOrigenMeta, setShowOrigenMeta] = useState(false)
  const [asesores, setAsesores]   = useState([])
  // Grupos por equipo, alineados con Asignación y Leads.
  const [teamGroups, setTeamGroups] = useState([])
  // V065: catalogo de sedes activas — para el selector en edicion
  const [sedes, setSedes] = useState([])
  useEffect(() => {
    api.get('/api/sedes/lookup?only_active=true')
      .then(res => setSedes(res.data || []))
      .catch(() => {})
  }, [])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError]         = useState(null)
  const [isEditing, setIsEditing] = useState(false)
  const [showNuevoContacto, setShowNuevoContacto] = useState(false)
  // V096.1 — Defaults para pre-llenar el form. Se setea desde el boton
  // "Agendar cita" del header (tipo='cita', resultado='cita_agendada')
  // o null cuando se abre normal desde "Registrar".
  const [nuevoContactoDefaults, setNuevoContactoDefaults] = useState(null)
  const [deletingContactoId, setDeletingContactoId] = useState(null)
  const [editingContactoId, setEditingContactoId]   = useState(null)
  const [editingLlamadaId,  setEditingLlamadaId]    = useState(null)
  const [confirmDialog, setConfirmDialog] = useState({ open: false, type: null, id: null })
  // V070.81 — confirmacion para derivar lead a un asesor antecedente.
  // {asesorId, asesorNombre} o null.
  const [confirmDerivar, setConfirmDerivar] = useState(null)
  const [tiposContacto, setTiposContacto]     = useState(TIPOS_DEFAULT)
  const [tiposCita, setTiposCita]             = useState([])
  const [resultadosContacto, setResultadosContacto] = useState(RESULTADOS_DEFAULT)
  // V042: catalogo de estados de cita (Pendiente, Completada, ...)
  const [citaEstados, setCitaEstados] = useState([])
  // V028: catálogo de temperatura del lead (configurable desde panel admin).
  const [calidadCatalog, setCalidadCatalog] = useState([])
  const [showWaModal, setShowWaModal] = useState(false)
  const [waMessage, setWaMessage] = useState('')
  const [sendingWa, setSendingWa] = useState(false)
  const [derivingAsesorId, setDerivingAsesorId] = useState(null)
  // V070.5 — preflight de WhatsApp Business. null mientras carga, true si
  // hay >=1 numero activo, false si no hay nada conectado. Lo consume el
  // boton WhatsApp del header del lead: si es false, el boton va en estado
  // deshabilitado con tooltip explicito en vez de abrir un modal que
  // despues falla al enviar.
  const [waConfigured, setWaConfigured] = useState(null)

  useEffect(() => {
    let alive = true
    api.get('/api/whatsapp/status')
      .then(({ data }) => {
        if (alive) setWaConfigured(Boolean(data?.has_sending_capability))
      })
      .catch(() => {
        // Fail-closed: si no podemos confirmar, asumimos NO configurado.
        // Mejor un boton deshabilitado que un envio que va a fallar feo.
        if (alive) setWaConfigured(false)
      })
    return () => { alive = false }
  }, [])

  const [savingReactivation, setSavingReactivation] = useState(false)

  const handleReactivarAutomatizacion = async () => {
    if (!window.confirm('¿Deseas reactivar el cambio automático de estados para este lead? Volverá a evaluarse según las reglas estándar de No Contesta / Contactos.')) {
      return
    }
    setSavingReactivation(true)
    try {
      await api.patch(`/api/leads/${id}`, { gestion_especial_admin: false })
      await fetchLead()
    } catch (err) {
      alert(err.response?.data?.detail || 'Error al reactivar automatización del lead.')
    } finally {
      setSavingReactivation(false)
    }
  }

  const handleDeleteContacto = (contactoId) => {
    setConfirmDialog({ open: true, type: 'contacto', id: contactoId })
  }

  const handleDeleteLlamada = (llamadaId) => {
    setConfirmDialog({ open: true, type: 'llamada', id: llamadaId })
  }

  const handleConfirmDelete = async () => {
    const { type, id: itemId } = confirmDialog
    setConfirmDialog({ open: false, type: null, id: null })
    if (type === 'contacto') {
      setDeletingContactoId(itemId)
      try {
        await api.delete(`/api/leads/${id}/contactos/${itemId}`)
        setContactos(prev => prev.filter(c => c.id !== itemId))
      } catch (err) {
        alert(err.response?.data?.detail || 'Error al eliminar el contacto.')
      } finally {
        setDeletingContactoId(null)
      }
    } else if (type === 'llamada') {
      try {
        await api.delete(`/api/llamadas/${itemId}`)
        setLlamadas(prev => prev.filter(l => l.id !== itemId))
      } catch (err) {
        alert(err.response?.data?.detail || 'Error al eliminar la llamada.')
      }
    }
  }

  useEffect(() => { loadCatalogs() }, [])

  // Cargar permisos de contactos para asesores
  useEffect(() => {
    if (role === 'asesor') {
      api.get('/api/settings/contact-permissions')
        .then(res => setContactPerms(res.data))
        .catch(() => {})
    }
  }, [role])

  // V028: catálogo de calidad — carga en paralelo, silencioso si falla.
  useEffect(() => {
    api.get('/api/calidad')
      .then(res => { if (Array.isArray(res.data)) setCalidadCatalog(res.data) })
      .catch(() => {})
  }, [])

  useEffect(() => {
    Promise.all([
      api.get('/api/tipos-contacto').catch(() => ({ data: [] })),
      api.get('/api/tipos-cita').catch(() => ({ data: [] })),
      api.get('/api/resultados-contacto').catch(() => ({ data: [] })),
      // V042: catalogo de estados de cita (silencioso si V042 no aplicado)
      api.get('/api/cita-estados').catch(() => ({ data: [] })),
    ]).then(([tiposRes, tiposCitaRes, resultadosRes, citaEstadosRes]) => {
      if (citaEstadosRes.data?.length) setCitaEstados(citaEstadosRes.data)
      if (tiposRes.data?.length) {
        setTiposContacto(tiposRes.data.map(t => ({
          nombre: t.nombre,
          label: t.nombre.charAt(0).toUpperCase() + t.nombre.slice(1).replace(/_/g, ' '),
        })))
      }
      if (tiposCitaRes.data?.length) {
        setTiposCita(tiposCitaRes.data.map(t => ({
          id: t.id,
          nombre: t.nombre,
          label: t.nombre,
          icono: t.icono,
        })))
      }
      if (resultadosRes.data?.length) {
        setResultadosContacto([
          { nombre: '', label: 'Seleccionar…' },
          ...resultadosRes.data.map(r => ({
            nombre: r.nombre,
            label: r.nombre.replace(/_/g, ' ').replace(/^\w/, c => c.toUpperCase()),
          })),
        ])
      }
    })
  }, [])

  useEffect(() => {
    if (!canAssign) return
    Promise.all([
      api.get('/auth/users'),
      api.get('/api/equipos'),
    ])
      .then(([usersRes, equiposRes]) => {
        const asignacionScope = user?.permissions?.['asignacion.scope'] || (role === 'admin' ? 'global' : 'equipo')
        const allowedUserIds = user?.permissions?.['asignacion.allowed_users'] || []
        const { groups } = buildTeamGroups({
          users:         usersRes.data || [],
          equipos:       equiposRes.data || [],
          role,
          currentUserId: user?.user_id,
          asignacionScope,
          allowedUserIds,
        })
        setTeamGroups(groups)
        setAsesores(flattenGroups(groups))
      })
      .catch(() => {})
  }, [canAssign, role, user?.user_id, user?.permissions])

  // Normaliza telefono a formato wa.me: solo digitos, con codigo de pais.
  // Si el numero no tiene +51 lo agregamos (Peru).
  const normalizeWaPhone = (raw) => {
    if (!raw) return ''
    const digits = String(raw).replace(/\D/g, '')
    if (!digits) return ''
    if (digits.startsWith('51')) return digits
    return '51' + digits
  }

  const openWaModal = () => {
    if (!lead?.telefono) {
      alert('Este lead no tiene teléfono registrado.')
      return
    }
    const nombreLead = (lead.nombres || '').trim() || 'amigo'
    const brand = useBrandStore.getState().brand
    const brandName = brand?.company_name || 'Palma del Río'
    setWaMessage(
      `Hola ${nombreLead}, te saluda ${user?.first_name || 'el equipo'} de ${brandName}. ` +
      `Quería retomar contacto sobre tu interés en nuestros proyectos. ¿Sigues interesado?`
    )
    setShowWaModal(true)
  }

  const handleWaOutreach = async () => {
    const phone = normalizeWaPhone(lead.telefono)
    if (!phone) {
      alert('Teléfono inválido.')
      return
    }
    const text = waMessage.trim()
    if (!text) {
      alert('Escribe un mensaje antes de enviar.')
      return
    }
    setSendingWa(true)
    try {
      // 1. Abre/reusa la conversacion en nuestro panel y la ata al lead
      const nombreLead = [lead.nombres, lead.apellidos].filter(Boolean).join(' ').trim() || null
      const { data } = await api.post('/api/whatsapp/conversations/open', {
        wa_phone: phone,
        lead_id: lead.id,
        contact_name: nombreLead,
      })
      const convId = data?.conversation_id
      // 2. Construimos la conv minima con los datos locales — asi Chat.jsx
      //    puede mostrarla en el sidebar al instante, sin depender de que el
      //    backend devuelva la conv completa ni de que este en la primera
      //    pagina del listado. El poll la refrescara con datos reales.
      //    data.conversation (si el backend lo devuelve) tiene prioridad —
      //    trae campos derivados (classification_*, tags, cases_count).
      const clientConv = {
        id: convId,
        wa_phone: phone,
        contact_name: nombreLead,
        lead_id: lead.id,
        lead_name: nombreLead,
        last_message_at: null,
        last_message_preview: null,
        unread_count: 0,
        window_expires_at: null,
        wa_campaign_id: null,
        wa_campaign_headline: null,
        campaign_name: null,
        // Heredamos el asesor del lead que estamos viendo. Es el mismo principio
        // del trigger V070.3 pero en cliente: si el backend no devuelve la conv
        // (fallback) este optimistic state ya viene con el asesor correcto, asi
        // el sidebar nunca muestra "Sin asignar" para un lead que SI lo tiene.
        asesor_id: lead.asesor_id || null,
        asesor_nombre: lead.asesor_nombre || null,
        asesor_role: lead.asesor_role || null,
        cases_count: 1,
        classification_status: 'pending',
        classification_category: null,
        classification_confidence: null,
        classification_interest: null,
        classification_urgency: null,
        classification_summary: null,
        tags: [],
      }
      const prefetchedConversation = data?.conversation || clientConv
      navigate(
        `/chat?conv=${convId}&draft=${encodeURIComponent(text)}`,
        { state: { prefetchedConversation } },
      )
    } catch (err) {
      // V070.5 — el backend ahora devuelve 409 con detail estructurado
      // {code: 'WHATSAPP_NOT_CONFIGURED', message: ...} cuando no hay WABA.
      // Lo detectamos para mostrar mensaje accionable en vez de propagar
      // un JSON crudo en el alert.
      const detail = err.response?.data?.detail
      if (detail && typeof detail === 'object' && detail.code === 'WHATSAPP_NOT_CONFIGURED') {
        alert(detail.message)
        setWaConfigured(false)
      } else {
        alert(typeof detail === 'string' ? detail : 'No se pudo abrir la conversación.')
      }
    } finally {
      setSendingWa(false)
    }
  }

  // V070.81 — abre modal en vez de confirm() nativo. La accion real
  // ocurre en handleDerivarAntecedenteConfirm tras confirmar.
  const handleDerivarAntecedente = (asesorId, asesorNombre) => {
    if (!asesorId) return
    setConfirmDerivar({ asesorId, asesorNombre })
  }

  const handleDerivarAntecedenteConfirm = async () => {
    if (!confirmDerivar?.asesorId) return
    const { asesorId } = confirmDerivar
    setConfirmDerivar(null)
    setDerivingAsesorId(asesorId)
    try {
      await api.post(`/api/leads/${id}/derivar-antecedente`, { asesor_id: asesorId })
      // V070.79 — notificar al Sidebar badge "Asignacion" en <500ms.
      fireAssignmentChanged()
      await fetchLead()
    } catch (err) {
      alert(err.response?.data?.detail || 'No se pudo derivar el lead.')
    } finally {
      setDerivingAsesorId(null)
    }
  }

  const fetchLead = async () => {
    setIsLoading(true)
    setError(null)
    try {
      const [leadRes, contactosRes, llamadasRes, asignacionesRes, antecedentesRes, propiedadesRes, recontactosRes, origenMetaRes] = await Promise.all([
        api.get(`/api/leads/${id}`),
        api.get(`/api/leads/${id}/contactos`),
        api.get(`/api/llamadas?lead_id=${id}&limit=500`).catch(() => ({ data: { items: [], total: 0 } })),
        // Historial de asignaciones — endpoint nuevo. Si falla (p.ej. permisos),
        // simplemente no se muestra la sección, sin tirar el resto del detalle.
        api.get(`/api/leads/${id}/asignaciones`).catch(() => ({ data: [] })),
        // Antecedentes — match en crm_legacy.leads_historico. Fail-safe: si no
        // existe la tabla legacy, el backend devuelve items=[].
        api.get(`/api/leads/${id}/antecedentes`).catch(() => ({ data: { items: [] } })),
        // Propiedades custom (EAV) creadas por mapeos de formularios.
        // Fail-safe: la tabla es opcional y la feature puede no estar habilitada.
        api.get(`/api/leads/${id}/properties`).catch(() => ({ data: { items: [] } })),
        // V048: Re-engagement (recontactos del mismo cliente por otra fuente).
        api.get(`/api/leads/${id}/recontactos`).catch(() => ({ data: { items: [] } })),
        // V058: Origen Meta (Facebook/Instagram) — leadgen_id, ad/adset/campaign con nombres.
        api.get(`/api/leads/${id}/origen-meta`).catch(() => ({ data: { interactions: [] } })),
      ])
      setLead(leadRes.data)
      setContactos(contactosRes.data || [])
      setLlamadas(llamadasRes.data?.items || [])
      setLlamadasTotal(llamadasRes.data?.total ?? (llamadasRes.data?.items?.length || 0))
      setAsignaciones(asignacionesRes.data || [])
      setPropiedades(propiedadesRes.data?.items || [])
      setRecontactos(recontactosRes.data?.items || [])

      // V127: Chequear si existen leads duplicados con el mismo teléfono para ofrecer fusión (solo admins)
      if (user?.role === 'admin') {
        api.get(`/api/leads/${id}/duplicate-candidate`)
          .then(res => {
            setDuplicateCandidates(res.data?.duplicates || [])
          })
          .catch(() => {
            setDuplicateCandidates([])
          })
      } else {
        setDuplicateCandidates([])
      }

      // Obtener conteo de historial de cambios para el badge
      api.get(`/api/leads/${id}/historial-cambios?limit=1`).then(res => {
        setHistorialCount(res.data?.total || 0)
      }).catch(() => {})

      const metaItems = origenMetaRes.data?.interactions || []
      setOrigenMeta(metaItems)
      setShowOrigenMeta(metaItems.length > 0)
      const antecItems = antecedentesRes.data?.items || []
      setAntecedentes(antecItems)
      setAntecedentesSummary(antecedentesRes.data?.summary || null)
      // UX: si hay antecedentes, los dejamos expandidos al entrar — no hay que
      // hacer clic extra para verlos. El usuario los puede colapsar si molesta.
      setShowAntecedentes(antecItems.length > 0)
    } catch (err) {
      setError(err.response?.data?.detail || 'Lead no encontrado.')
    } finally {
      setIsLoading(false)
    }
  }

  const refreshHistorial = async () => {
    try {
      const [contactosRes, llamadasRes] = await Promise.all([
        api.get(`/api/leads/${id}/contactos`),
        api.get(`/api/llamadas?lead_id=${id}&limit=500`).catch(() => ({ data: { items: [], total: 0 } })),
      ])
      // V042 — preserve cita_estado fields cuando el backend no los trae.
      // Si un contacto tiene __local_cita_estado=true (lo seteamos tras
      // un save optimistic) y la respuesta del backend NO trae
      // cita_estado_id (porque el deploy del SELECT esta lageado), nos
      // quedamos con el valor local. Asi el badge no parpadea.
      setContactos(prev => {
        const nuevos = contactosRes.data || []
        const localById = new Map(
          (prev || [])
            .filter(c => c.__local_cita_estado)
            .map(c => [c.id, c])
        )
        return nuevos.map(c => {
          const local = localById.get(c.id)
          if (local && c.cita_estado_id == null) {
            // Backend no trajo el campo — preservar local
            return {
              ...c,
              cita_estado_id: local.cita_estado_id,
              cita_estado_codigo: local.cita_estado_codigo,
              cita_estado_nombre: local.cita_estado_nombre,
              cita_estado_color: local.cita_estado_color,
              __local_cita_estado: true,
            }
          }
          return c
        })
      })
      setLlamadas(llamadasRes.data?.items || [])
      setLlamadasTotal(llamadasRes.data?.total ?? (llamadasRes.data?.items?.length || 0))
    } catch { /* silencioso */ }
  }

  useEffect(() => { fetchLead() }, [id])

  useEffect(() => {
    if (!id) return
    const interval = setInterval(() => {
      if (!document.hidden) refreshHistorial()
    }, 15000)
    const onFocus = () => refreshHistorial()
    window.addEventListener('focus', onFocus)
    return () => {
      clearInterval(interval)
      window.removeEventListener('focus', onFocus)
    }
  }, [id])

  if (isLoading) return (
    <div className="flex items-center justify-center py-20">
      <LoadingSpinner />
    </div>
  )

  if (error) return (
    <div className="flex flex-col items-center justify-center py-20 gap-4">
      <AlertCircle size={40} className="text-red-400" />
      <p className="text-gray-600">{error}</p>
      {/* V070.102 — back history-aware: si hay historia previa (vino de
          Dashboard, Agenda, Chat, etc) vuelve al origen; sino fallback a
          /leads (deep link directo o reload). patrón estándar. */}
      <Button
        variant="outline"
        size="sm"
        onClick={() => (window.history.length > 1 ? navigate(-1) : navigate('/leads'))}
      >
        <ArrowLeft size={14} className="mr-1" /> Volver
      </Button>
    </div>
  )

  const nombreCompleto = [lead.nombres, lead.apellidos].filter(Boolean).join(' ') || 'Sin nombre'
  const fuente = fuentes.find(f => f.id === lead.fuente_id)

  return (
    <div className="space-y-5 max-w-5xl">
      {/* Encabezado */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => (window.history.length > 1 ? navigate(-1) : navigate('/leads'))}
          className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500 transition-colors"
          title="Volver"
        >
          <ArrowLeft size={18} />
        </button>
        <div className="flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h1 className="text-xl font-bold text-gray-900">{nombreCompleto}</h1>
            <EstadoBadge estadoId={lead.estado_id} estados={estados} />
            {lead.gestion_especial_admin && (
              <span
                className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold bg-amber-50 text-amber-900 border border-amber-300 shadow-sm"
                title={`Lead con gestión especial por Administración (cambio automático desactivado)${lead.gestion_admin_at ? ` desde ${formatDateTime(lead.gestion_admin_at)}` : ''}`}
              >
                <Shield size={12} className="text-amber-600" />
                Gestión Admin (Auto-cambio apagado)
              </span>
            )}
            {fuente && (
              <Badge variant="secondary" className="capitalize text-xs">{fuente.nombre}</Badge>
            )}
            {/* V060: campana en cabecera (engloba al proyecto). Para leads
                legacy sin campana pero con proyecto, mostramos el proyecto
                como fallback para no perder la info de un vistazo. Truncamos
                con ellipsis para no romper el layout en campañas largas. */}
            {(lead.campana || lead.proyecto) && (
              <span
                className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold border bg-indigo-50 text-indigo-700 border-indigo-200 max-w-[260px] truncate"
                title={lead.campana || lead.proyecto}
              >
                {lead.campana || lead.proyecto}
              </span>
            )}
            {/* Calidad: prioridad comercial (Frio/Tibio/Caliente) */}
            {lead.calidad && (
              <CalidadBadge value={lead.calidad} catalog={calidadCatalog} />
            )}
            {/* Asesor (owner del lead) — patrón estándar de la industria: el "owner"
                es info de cabecera. Antes estaba abajo en Datos del Lead. */}
            {lead.asesor_nombre && (
              <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium bg-gray-100 text-gray-700 border border-gray-200">
                <User size={11} className="text-gray-500" />
                {lead.asesor_nombre}
              </span>
            )}
            {/* V091.1 — Badge "Heredado de X" PERMANENTE hasta próxima
                reasignación. Si el lead se vuelve a transferir, el badge
                se actualiza solo (apunta al asesor anterior más reciente). */}
            {(() => {
              if (!lead.reassigned_at || !lead.previous_asesor_nombre) return null
              const ms = new Date(lead.reassigned_at).getTime()
              if (Number.isNaN(ms)) return null
              const dias = (Date.now() - ms) / 86400000
              const label = dias < 1
                ? 'hoy'
                : dias < 2
                ? 'ayer'
                : dias < 30
                ? `hace ${Math.floor(dias)} días`
                : dias < 365
                ? `hace ${Math.floor(dias / 30)} ${Math.floor(dias / 30) === 1 ? 'mes' : 'meses'}`
                : `hace ${Math.floor(dias / 365)} ${Math.floor(dias / 365) === 1 ? 'año' : 'años'}`
              const fechaIso = new Date(ms).toLocaleDateString('es-PE', {
                day: '2-digit', month: '2-digit', year: 'numeric',
              })
              return (
                <span
                  className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium bg-violet-50 text-violet-800 border border-violet-200"
                  title={`Este lead estaba asignado a ${lead.previous_asesor_nombre} y fue reasignado el ${fechaIso} (${label}). El badge se actualiza solo cuando el lead se vuelva a reasignar.`}
                >
                  ↪ Heredado de {lead.previous_asesor_nombre} · {label}
                </span>
              )
            })()}
          </div>
          {/* Quick contacts: tel + email clickables. Permite llamar/email sin
              scrollear al detalle. Mailto/tel: usan los handlers nativos del SO. */}
          <div className="flex items-center gap-3 mt-1 flex-wrap text-xs">
            {lead.telefono && (
              <a
                href={`tel:${lead.telefono}`}
                className="inline-flex items-center gap-1 text-gray-600 hover:text-indigo-600 font-mono transition-colors"
                title="Llamar"
              >
                <Phone size={11} /> {lead.telefono}
              </a>
            )}
            {lead.email && (
              <a
                href={`mailto:${lead.email}`}
                className="inline-flex items-center gap-1 text-gray-600 hover:text-indigo-600 transition-colors truncate max-w-[280px]"
                title="Enviar email"
              >
                <Mail size={11} /> {lead.email}
              </a>
            )}
          </div>
          <p className="text-xs text-gray-400 mt-1">
            Registrado el {formatDateTime(lead.fecha_ingreso || lead.created_at)}
          </p>
        </div>
        {lead.telefono && !isEditing && (
          // V070.5 — Boton WhatsApp con preflight de WABA. Si no hay numero
          // configurado el boton sigue visible (para no confundir al usuario
          // moviendolo) pero queda deshabilitado con tooltip que explica el
          // motivo. El admin ve un mensaje accionable; los demas roles ven
          // a quien pedirselo.
          <Button
            variant="outline"
            size="sm"
            onClick={openWaModal}
            disabled={waConfigured === false}
            className="gap-1.5 border-green-200 text-green-700 hover:bg-green-50 hover:text-green-800 disabled:opacity-50 disabled:cursor-not-allowed"
            title={
              waConfigured === false
                ? (user?.role === 'admin'
                    ? 'WhatsApp no esta conectado. Ve a Integraciones para configurar tu WABA.'
                    : 'WhatsApp no esta conectado. Pide al admin que configure la WABA en Integraciones.')
                : 'Contactar por WhatsApp'
            }
          >
            <MessageCircle size={13} /> WhatsApp
          </Button>
        )}
        {/* V096.1 — Botón "Agendar cita" prominente (paridad mobile). */}
        {canCreateCita && !isEditing && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => {
              const tipoCita = (tiposContacto || []).find(t =>
                String(t.nombre || '').toLowerCase().includes('cita')
                || String(t.codigo || '').toLowerCase().includes('cita'))
              const resultadoCita = (resultadosContacto || []).find(r =>
                String(r.nombre || r.codigo || '').toLowerCase().includes('cita'))
              const primerTipoCita = (tiposCita || [])[0]?.nombre || 'Cita oficina Bustamante'
              setNuevoContactoDefaults({
                defaultTipo: tipoCita?.nombre || 'cita',
                defaultTipoCita: primerTipoCita,
                defaultResultado: resultadoCita?.nombre || resultadoCita?.codigo || 'cita_agendada',
              })
              setShowNuevoContacto(true)
              setTimeout(() => {
                document.getElementById('historial-contactos-anchor')?.scrollIntoView({
                  behavior: 'smooth', block: 'start',
                })
              }, 60)
            }}
            className="gap-1.5 border-emerald-200 text-emerald-700 hover:bg-emerald-50 hover:text-emerald-800"
            title="Agendar una cita con este lead"
          >
            <Calendar size={13} /> Agendar cita
          </Button>
        )}
        {lead.gestion_especial_admin && user?.role === 'admin' && !isEditing && (
          <Button
            variant="outline"
            size="sm"
            onClick={handleReactivarAutomatizacion}
            disabled={savingReactivation}
            className="gap-1.5 border-amber-300 text-amber-800 hover:bg-amber-50"
            title="Reactivar el cambio automático de estados para este lead"
          >
            <RefreshCw size={13} className={savingReactivation ? 'animate-spin' : ''} /> Reactivar automatización
          </Button>
        )}
        {canEdit && !isEditing && (
          <Button variant="outline" size="sm" onClick={() => setIsEditing(true)} className="gap-1.5">
            <Edit2 size={13} /> Editar
          </Button>
        )}
        {/* V127: Botón Fusionar datos (solo admins, si hay otro lead con el mismo teléfono) */}
        {user?.role === 'admin' && duplicateCandidates.length > 0 && !isEditing && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowMergeModal(true)}
            className="gap-1.5 border-purple-300 text-purple-700 hover:bg-purple-50 dark:border-purple-800 dark:text-purple-300 dark:hover:bg-purple-950/50 shadow-2xs"
            title="Fusionar datos con otro lead que comparte el mismo teléfono (solo administradores)"
          >
            <GitMerge size={13} className="text-purple-600 dark:text-purple-400" />
            Fusionar lead {duplicateCandidates.length > 1 ? `(${duplicateCandidates.length})` : ''}
          </Button>
        )}
              {!isEditing && (
          <Button
            variant={activeTab === 'historial' ? 'default' : 'outline'}
            size="sm"
            onClick={() => setActiveTab(activeTab === 'historial' ? 'detalle' : 'historial')}
            className={`gap-1.5 transition-all ${
              activeTab === 'historial'
                ? 'bg-indigo-600 hover:bg-indigo-700 text-white shadow-2xs'
                : 'border-gray-200 text-gray-700 hover:bg-gray-50 dark:border-slate-700 dark:text-slate-200 dark:hover:bg-slate-800'
            }`}
            title="Ver historial de cambios del lead"
          >
            <History size={13} /> Historial
            {historialCount > 0 && (
              <span className={`text-[10px] px-1.5 py-0.2 rounded-full font-bold leading-none ${
                activeTab === 'historial' ? 'bg-indigo-800 text-white' : 'bg-indigo-100 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-300'
              }`}>
                {historialCount}
              </span>
            )}
          </Button>
        )}
      </div>

      {/* Navegacion por pestanas: Ficha del lead vs Historial de cambios */}
      <div className="flex items-center gap-6 border-b border-gray-200 dark:border-slate-800 pb-px">
        <button
          type="button"
          onClick={() => setActiveTab('detalle')}
          className={`inline-flex items-center gap-2 pb-2.5 text-sm font-semibold border-b-2 transition-all cursor-pointer ${
            activeTab === 'detalle'
              ? 'border-indigo-600 text-indigo-600 dark:border-indigo-400 dark:text-indigo-400'
              : 'border-transparent text-gray-500 hover:text-gray-800 dark:text-slate-400 dark:hover:text-slate-200'
          }`}
        >
          <User size={15} /> Ficha del Lead
        </button>
        <button
          type="button"
          onClick={() => setActiveTab('historial')}
          className={`inline-flex items-center gap-2 pb-2.5 text-sm font-semibold border-b-2 transition-all cursor-pointer ${
            activeTab === 'historial'
              ? 'border-indigo-600 text-indigo-600 dark:border-indigo-400 dark:text-indigo-400'
              : 'border-transparent text-gray-500 hover:text-gray-800 dark:text-slate-400 dark:hover:text-slate-200'
          }`}
        >
          <History size={15} /> Historial de Cambios
          {historialCount > 0 && (
            <span className="text-xs px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-600 border border-indigo-200 dark:bg-indigo-950/60 dark:text-indigo-400 dark:border-indigo-900 font-bold leading-none">
              {historialCount}
            </span>
          )}
        </button>
      </div>

      {activeTab === 'historial' ? (
        <LeadHistorialCambios leadId={id} onCountUpdate={setHistorialCount} />
      ) : (
        <>

      {/* V127: Aviso dentro del lead fusionado informando que la información viene de dos leads fusionados */}
      {lead?.is_merged && lead?.merges?.length > 0 && (
        <MergedLeadBanner
          merges={lead.merges}
          currentPhone={lead.telefono}
          onViewHistory={() => setActiveTab('historial')}
        />
      )}

      {/* V127: Aviso si este lead fue absorbido en otro lead */}
      {lead?.merged_into && (
        <div className="mb-5 p-3.5 bg-purple-50 dark:bg-purple-950/40 border border-purple-200 dark:border-purple-800 rounded-xl flex items-center justify-between gap-3 shadow-2xs">
          <div className="flex items-center gap-2.5">
            <GitMerge size={16} className="text-purple-600 shrink-0" />
            <p className="text-xs text-purple-900 dark:text-purple-200">
              Este lead fue absorbido en el <strong>Lead #{lead.merged_into}</strong> mediante una fusión de datos duplicados.
            </p>
          </div>
          <Button
            size="sm"
            variant="outline"
            className="text-xs border-purple-300 text-purple-800 hover:bg-purple-100"
            onClick={() => navigate(`/leads/${lead.merged_into}`)}
          >
            Ver lead principal →
          </Button>
        </div>
      )}

      {/* V127: Alerta inline de leads duplicados detectados con el mismo teléfono (solo admins) */}
      {user?.role === 'admin' && !lead?.is_merged && !lead?.merged_into && duplicateCandidates.length > 0 && !isEditing && (
        <div className="mb-5 p-3.5 bg-gradient-to-r from-purple-50 via-indigo-50/50 to-purple-50/30 dark:from-purple-950/40 dark:via-indigo-950/30 dark:to-purple-950/20 border border-purple-200 dark:border-purple-800/60 rounded-xl flex items-center justify-between gap-4 shadow-2xs">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-purple-100 dark:bg-purple-900/60 text-purple-700 dark:text-purple-300 flex items-center justify-center shrink-0">
              <GitMerge size={16} />
            </div>
            <div>
              <h4 className="text-xs font-bold text-purple-950 dark:text-purple-100 flex items-center gap-2">
                Se detectó {duplicateCandidates.length === 1 ? 'otro lead' : `${duplicateCandidates.length} otros leads`} con el mismo número de teléfono
                <span className="font-mono text-[11px] font-semibold text-purple-800 dark:text-purple-300 bg-purple-100 dark:bg-purple-900/70 px-2 py-0.5 rounded">
                  {lead?.telefono}
                </span>
              </h4>
              <p className="text-[11px] text-purple-800 dark:text-purple-300 mt-0.5">
                Puedes fusionar los registros para unificar información, historial de contactos y definir cuál de los dos dueños tendrá autoridad.
              </p>
            </div>
          </div>
          <Button
            size="sm"
            onClick={() => setShowMergeModal(true)}
            className="shrink-0 h-8 text-xs bg-purple-600 hover:bg-purple-700 text-white gap-1.5 shadow-2xs font-semibold"
          >
            <GitMerge size={13} /> Fusionar datos
          </Button>
        </div>
      )}

      {/* Recalco: Aviso de Ficha Técnica pendiente */}
      {(() => {
        const fichaStats = getFichaTecnicaStats(lead?.ficha_tecnica)
        if (!fichaStats.isComplete) {
          return (
            <div className="mb-5 p-3.5 bg-gradient-to-r from-amber-50 to-orange-50 dark:from-amber-950/40 dark:to-orange-950/30 border border-amber-200 dark:border-amber-800/60 rounded-xl flex items-center justify-between gap-4 shadow-2xs">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 rounded-full bg-amber-100 dark:bg-amber-900/60 text-amber-700 dark:text-amber-300 flex items-center justify-center shrink-0">
                  <ClipboardList size={16} />
                </div>
                <div>
                  <h4 className="text-xs font-bold text-amber-900 dark:text-amber-100 flex items-center gap-2">
                    Ficha técnica pendiente por rellenar
                    <span className="text-[10px] font-semibold px-2 py-0.5 rounded-full bg-amber-200/80 text-amber-900 border border-amber-300">
                      {fichaStats.completedCount}/6 completadas
                    </span>
                  </h4>
                  <p className="text-[11px] text-amber-800 dark:text-amber-300 mt-0.5">
                    {fichaStats.completedCount === 0
                      ? 'Este lead aún no cuenta con respuestas en su cuestionario de descubrimiento comercial.'
                      : `Aún faltan ${fichaStats.total - fichaStats.completedCount} preguntas clave por responder en la ficha técnica.`}
                    {' '}El asesor encargado debe completarla para el correcto seguimiento y personalización de la venta.
                  </p>
                </div>
              </div>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  document.getElementById('card-ficha-tecnica')?.scrollIntoView({ behavior: 'smooth' })
                }}
                className="shrink-0 h-8 text-xs bg-white dark:bg-slate-900 border-amber-300 dark:border-amber-700 text-amber-900 dark:text-amber-200 hover:bg-amber-100"
              >
                Completar ficha técnica
              </Button>
            </div>
          )
        }
        return null
      })()}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Panel izquierdo: datos del lead */}
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-3">
              <CardTitle className="text-sm font-semibold text-gray-700 flex items-center gap-2">
                <User size={15} /> Datos del Lead
              </CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              {isEditing ? (
                <EditLeadForm
                  lead={lead}
                  estados={estados}
                  asesores={asesores}
                  teamGroups={teamGroups}
                  canAssign={canAssign}
                  calidadCatalog={calidadCatalog}
                  sedes={sedes}
                  fuentes={fuentes}
                  onSave={async () => { await fetchLead(); setIsEditing(false) }}
                  onCancel={() => setIsEditing(false)}
                />
              ) : (
                <div className="space-y-4">
                  {/* 📇 Contacto — siempre expandido. Datos para llamar/escribir
                      al cliente. Es lo que más se mira al abrir un lead. */}
                  <DetailSection title="Contacto" icon={<User size={12} className="text-gray-500" />} defaultOpen>
                    <DetailRow label="Teléfono" value={lead.telefono} mono />
                    <DetailRow label="Email" value={lead.email} />
                    <DetailRow
                      label={(() => {
                        const t = lead.tipo_documento || inferDocumentType(lead.dni)
                        return t === 'DNI' ? 'DNI' : t === 'CE' ? 'Carnet Extr.' : 'Pasaporte'
                      })()}
                      value={lead.dni}
                      mono
                    />
                    <DetailRow label="Ciudad" value={lead.ciudad} />
                    {/* V067.4: Trabajo / cargo del lead. Util para personalizar
                        la conversacion. Antes solo visible en mobile y merge. */}
                    <DetailRow label="Trabajo" value={lead.trabajo} />
                    {/* V065: Sede de destino del lead. Movida desde
                        "Tracking de campaña" a "Contacto" porque es info
                        operativa (donde sera atendido el cliente), no de
                        marketing/atribucion. Single-sede no la ve. */}
                    {sedes.length > 0 && (
                      <DetailRow
                        label="Sede"
                        value={lead.sede_id ? (lead.sede_nombre || lead.sede_codigo) : null}
                        render={v => {
                          if (!v) {
                            return (
                              <span className="text-gray-400 inline-flex items-center gap-1 text-xs">
                                — <span className="text-[10px] text-gray-300">(sin asignar)</span>
                              </span>
                            )
                          }
                          const color = lead.sede_color || '#6366f1'
                          return (
                            <span
                              className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded border"
                              style={{
                                backgroundColor: color + '14',
                                color: color,
                                borderColor: color + '40',
                              }}
                            >
                              <MapPin size={10} /> {v}
                            </span>
                          )
                        }}
                      />
                    )}
                  </DetailSection>

                  {/* 💼 Comercial — info de venta. V060: convencion unificada
                      en Campaña (engloba proyecto) y Fuente (engloba estrategia). */}
                  <DetailSection title="Comercial" icon={<Tag size={12} className="text-gray-500" />} defaultOpen>
                    <DetailRow
                      label={
                        <span className="inline-flex items-center gap-1 cursor-help"
                          title="Campaña incluye el proyecto/desarrollo inmobiliario. Ej: 'ILLARY D9 10% inicial' o 'Test Mayo 2026'."
                        >
                          Campaña <span className="text-gray-300 text-[9px]">ⓘ</span>
                        </span>
                      }
                      value={lead.campana_nombre || lead.campana}
                      render={v => {
                        // V069.3 — Si el nombre legible existe Y el campana raw
                        // es distinto (ej. campana=ID numerico, campana_nombre=
                        // "palmeras 26"), mostramos el nombre arriba y el ID
                        // pequeñito debajo (paridad con la columna en la lista).
                        if (!v) return <span className="text-gray-400">—</span>
                        const showId = lead.campana_nombre &&
                                       lead.campana &&
                                       lead.campana_nombre !== lead.campana
                        return (
                          <div className="flex flex-col">
                            <span className="text-gray-800 dark:text-slate-100">{v}</span>
                            {showId && (
                              <span className="font-mono text-[10px] text-gray-400 dark:text-slate-500 mt-0.5">
                                {lead.campana}
                              </span>
                            )}
                          </div>
                        )
                      }}
                    />
                    <DetailRow
                      label={
                        <span className="inline-flex items-center gap-1 cursor-help"
                          title="Fuente incluye el canal/estrategia de origen. Ej: Activación, Referido, Volanteo, Facebook, Instagram."
                        >
                          Fuente <span className="text-gray-300 dark:text-slate-500 text-[9px]">ⓘ</span>
                        </span>
                      }
                      value={fuente?.nombre}
                    />
                    <DetailRow
                      label="Calidad"
                      value={lead.calidad}
                      render={v => <CalidadBadge value={v} catalog={calidadCatalog} />}
                    />
                    {lead.fecha_proxima_gestion && (
                      <DetailRow
                        label="Próx. gestión"
                        value={lead.fecha_proxima_gestion}
                        render={v => (
                          <div className="flex flex-col gap-0.5">
                            <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded font-medium bg-blue-50 text-blue-700 border border-blue-200 w-fit">
                              <Calendar size={11} /> {formatDateTime(v)}
                            </span>
                            {lead.accion_proxima_gestion && (
                              <span className="text-xs text-purple-700 dark:text-purple-300 font-medium pl-0.5 mt-0.5">
                                ↳ Acción: {lead.accion_proxima_gestion}
                              </span>
                            )}
                          </div>
                        )}
                      />
                    )}
                    {lead.motivo_perdida && (
                      <DetailRow
                        label="Motivo pérdida"
                        value={lead.motivo_perdida}
                        render={v => (
                          <div className="flex flex-col">
                            <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded font-medium bg-rose-50 text-rose-700 border border-rose-200 w-fit">
                              <AlertCircle size={11} /> {v}
                            </span>
                            {lead.motivo_perdida_otro && (
                              <span className="text-[11px] text-gray-500 dark:text-slate-400 mt-1 italic pl-1">
                                &quot;{lead.motivo_perdida_otro}&quot;
                              </span>
                            )}
                          </div>
                        )}
                      />
                    )}
                  </DetailSection>

                  {/* Venta / Cierre — visible si tiene datos o está en estado de cierre/venta */}
                  {(lead.tipo_cierre || isEstadoMatricula(lead.estado_nombre)) && (
                    <DetailSection title="Venta / Cierre" icon={<UserCheck size={12} className="text-gray-500" />} defaultOpen>
                      <DetailRow
                        label="Tipo de cierre"
                        value={lead.tipo_cierre}
                        render={v => v ? (
                          <span className={`inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded font-medium border ${
                            v === 'Cierre autónomo'
                              ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                              : 'bg-indigo-50 text-indigo-700 border-indigo-200'
                          }`}>
                            <UserCheck size={11} /> {v}
                          </span>
                        ) : <span className="text-gray-400">—</span>}
                      />
                      {lead.tipo_cierre === 'Con segunda voz' && (
                        <DetailRow
                          label="Segunda voz"
                          value={lead.segunda_voz}
                          render={v => v ? (
                            <span className="text-gray-800 dark:text-slate-100 font-medium text-xs bg-gray-50 dark:bg-slate-800/80 px-2 py-1 rounded border border-gray-200 dark:border-slate-700 inline-block">
                              {v}
                            </span>
                          ) : <span className="text-gray-400">—</span>}
                        />
                      )}
                    </DetailSection>
                  )}

                  {/* 📊 Tracking de marketing — colapsado por default. Util
                      para reportes/atribución, no para llamar al cliente. */}
                  <DetailSection title="Tracking de campaña" icon={<FileText size={12} className="text-gray-500" />}>
                    {/* V069.4 — Formulario (form_id de Meta/TikTok) con nombre
                        resuelto via meta_catalog_cache. Paridad con campana
                        del bloque Comercial. */}
                    <DetailRow
                      label="Formulario"
                      value={lead.form_nombre || lead.fuente_form_id}
                      render={v => {
                        if (!v) return <span className="text-gray-400">—</span>
                        const showId = lead.form_nombre &&
                                       lead.fuente_form_id &&
                                       lead.form_nombre !== lead.fuente_form_id
                        return (
                          <div className="flex flex-col">
                            <span className="text-gray-800 dark:text-slate-100">{v}</span>
                            {showId && (
                              <span className="font-mono text-[10px] text-gray-400 dark:text-slate-500 mt-0.5">
                                {lead.fuente_form_id}
                              </span>
                            )}
                          </div>
                        )
                      }}
                    />
                    <DetailRow label="Conjunto (Ad Set)" value={lead.conjunto} />
                    <DetailRow label="Anuncio (Ad)" value={lead.anuncio} />
                    <DetailRow
                      label="Proveedor"
                      value={lead.proveedor_nombre}
                      render={v => v
                        ? <span className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-emerald-50 text-emerald-700 border border-emerald-200">{v}</span>
                        : <span className="text-gray-400">—</span>}
                    />
                    {/* V062: trazabilidad post-unlink. El proveedor activo
                        puede haber desaparecido (admin lo desvinculo o borro)
                        pero el slug+nombre original quedaron snapshoteados.
                        Solo se muestra cuando hay valor legacy y el activo
                        ya no esta. */}
                    {!lead.proveedor_nombre && lead.api_client_legacy_nombre && (
                      <DetailRow
                        label="Proveedor original"
                        value={lead.api_client_legacy_nombre}
                        render={v => (
                          <span
                            className="inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded bg-amber-50 text-amber-700 border border-amber-200"
                            title="Proveedor desvinculado — snapshot preservado para trazabilidad"
                          >
                            <Archive size={10} /> {v}
                          </span>
                        )}
                      />
                    )}
                    {lead.referido_por && (
                      <DetailRow label="Referido por" value={lead.referido_por} />
                    )}
                    {lead.codigo_convenio && (
                      <DetailRow label="Código de convenio" value={lead.codigo_convenio} />
                    )}
                  </DetailSection>

                  {/* V060: Datos legacy — solo aparece si el lead tiene valor en
                      las columnas viejas proyecto o estrategia. Read-only.
                      Default cerrado para no distraer (la mayoría de leads
                      modernos no tendrán datos aquí). */}
                  {(lead.proyecto || lead.estrategia) && (
                    <DetailSection
                      title="Datos legacy"
                      icon={<Archive size={12} className="text-gray-400" />}
                    >
                      <p className="text-[10px] text-gray-400 mb-2 italic">
                        Estos campos ya no se usan en leads nuevos. Se preservan para
                        consulta histórica. La convención actual es Campaña + Fuente.
                      </p>
                      {lead.proyecto && (
                        <DetailRow label="Proyecto" value={lead.proyecto} />
                      )}
                      {lead.estrategia && (
                        <DetailRow label="Estrategia" value={lead.estrategia} />
                      )}
                    </DetailSection>
                  )}

                  {/* 📝 Notas — observaciones del asesor */}
                  {lead.observaciones && (
                    <DetailSection title="Observaciones" icon={<FileText size={12} className="text-gray-500" />} defaultOpen>
                      <div className="text-sm text-gray-800 dark:text-slate-200 whitespace-pre-wrap leading-relaxed">
                        {lead.observaciones}
                      </div>
                    </DetailSection>
                  )}
                  {lead.resumen_ia && (
                    <DetailSection
                      title="Resumen previo de IA"
                      icon={<span className="text-xs">🤖</span>}
                      defaultOpen
                    >
                      <div className="bg-violet-50/60 dark:bg-violet-950/30 border border-violet-100 dark:border-violet-900/60 rounded-md p-3 text-sm text-gray-700 dark:text-slate-200 leading-relaxed whitespace-pre-wrap">
                        {lead.resumen_ia}
                      </div>
                    </DetailSection>
                  )}
                  {lead.datos_extra && Object.keys(lead.datos_extra).length > 0 && (
                    <DetailSection
                      title="Datos adicionales"
                      icon={<FileText size={12} className="text-gray-500" />}
                    >
                      <pre className="bg-gray-50 dark:bg-slate-900/80 border border-gray-100 dark:border-slate-800 rounded-md p-3 text-xs text-gray-600 dark:text-slate-300 font-mono overflow-x-auto whitespace-pre">
                        {JSON.stringify(lead.datos_extra, null, 2)}
                      </pre>
                    </DetailSection>
                  )}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Ficha técnica del lead */}
          <FichaTecnicaCard
            lead={lead}
            canEdit={canEdit}
            isParentEditing={isEditing}
            onSaveSuccess={fetchLead}
          />

          {/* Propiedades custom — valores capturados por mapeos patrón estándar.
              Solo se muestra si hay al menos una propiedad. */}
          {propiedades.length > 0 && (
            <Card className="border-violet-100 bg-violet-50/20">
              <CardHeader className="pb-3">
                <CardTitle className="text-sm font-semibold text-violet-900 flex items-center gap-2">
                  <Sparkles size={15} /> Propiedades Custom
                  <span className="ml-auto text-[11px] font-normal text-violet-700/70">
                    {propiedades.length}
                  </span>
                </CardTitle>
              </CardHeader>
              <CardContent className="pt-0">
                <dl className="space-y-2.5">
                  {propiedades.map(p => (
                    <div key={p.property_key} className="flex gap-3">
                      <dt
                        className="text-xs font-medium text-violet-900/80 w-32 shrink-0 pt-0.5"
                        title={p.property_key}
                      >
                        {p.display_name || p.property_key}
                      </dt>
                      <dd className="text-sm text-gray-800 flex-1 break-words">
                        {p.property_value || <span className="text-gray-400">—</span>}
                      </dd>
                    </div>
                  ))}
                </dl>
              </CardContent>
            </Card>
          )}

          {/* V058: Origen Meta — Facebook Lead ID + ad/adset/campaign hierarchy */}
          <OrigenMetaCard
            items={origenMeta}
            open={showOrigenMeta}
            onToggle={() => setShowOrigenMeta(o => !o)}
          />

          {/* Antecedentes — matches en crm_legacy.leads_historico. Solo si hay. */}
          <AntecedentesHistorial
            items={antecedentes}
            summary={antecedentesSummary}
            open={showAntecedentes}
            onToggle={() => setShowAntecedentes(o => !o)}
            canDerive={canAssign}
            currentAsesorId={lead?.asesor_id || null}
            onDerive={handleDerivarAntecedente}
            derivingId={derivingAsesorId}
          />

          {/* V048: Re-engagement — el cliente volvio a interesarse via otra fuente */}
          <RecontactosCard
            items={recontactos}
            open={showRecontactos}
            onToggle={() => setShowRecontactos(o => !o)}
          />

          {/* Historial de asignaciones (auditoría) — solo aparece si hay registros */}
          <AsignacionesHistorial items={asignaciones} />
        </div>

        {/* Panel derecho: timeline de contactos */}
        <div className="space-y-4" id="historial-contactos-anchor">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-700 flex items-center gap-2">
              <Clock size={15} /> Historial de Contactos ({contactos.filter(c => !['cambio_estado', 'cambio_fuente', 'sistema', 'reasignacion'].includes(c.tipo_contacto)).length + llamadasTotal})
            </h2>
            {!showNuevoContacto && canCreateContact && (
              <Button
                size="sm"
                onClick={() => { setNuevoContactoDefaults(null); setShowNuevoContacto(true) }}
                className="gap-1.5"
              >
                <Plus size={13} /> Registrar
              </Button>
            )}
          </div>

          {showNuevoContacto && (
            <NuevoContactoForm
              leadId={id}
              tipos={tiposContacto}
              tiposCita={tiposCita}
              resultados={resultadosContacto}
              estados={estados}
              currentEstadoId={lead.estado_id}
              currentEstadoNombre={lead.estado_nombre}
              // V096.1 — defaults para pre-llenar cuando el user hizo click
              // en "Agendar cita" del header del lead.
              defaultTipo={nuevoContactoDefaults?.defaultTipo}
              defaultTipoCita={nuevoContactoDefaults?.defaultTipoCita}
              defaultResultado={nuevoContactoDefaults?.defaultResultado}
              onSuccess={async () => {
                await fetchLead()
                setShowNuevoContacto(false)
                setNuevoContactoDefaults(null)
              }}
              onCancel={() => {
                setShowNuevoContacto(false)
                setNuevoContactoDefaults(null)
              }}
            />
          )}

          {/* Timeline — contactos manuales + llamadas sync mezclados por fecha (DESC) */}
          {(() => {
            // Merge unico de ambas fuentes, ordenado por fecha descendente
            const timeline = [
              ...llamadas.map(ll => ({ _kind: 'llamada',  _date: ll.fecha_llamada, data: ll })),
              ...contactos.map(c  => ({ _kind: 'contacto', _date: c.created_at,     data: c  })),
            ].sort((a, b) => new Date(b._date) - new Date(a._date))
            return (
          <div className="space-y-3">
            {contactos.length === 0 && llamadas.length === 0 && !showNuevoContacto && (
              <div className="text-center py-8">
                <MessageSquare size={28} className="text-gray-300 mx-auto mb-2" />
                <p className="text-sm text-gray-400">Sin contactos registrados aún.</p>
              </div>
            )}
            {timeline.map((entry) => {
              if (entry._kind === 'llamada') {
                const ll = entry.data
                const tipoColor = { saliente: 'text-green-600', entrante: 'text-blue-600', perdida: 'text-red-500' }
                const tipoBg    = { saliente: 'bg-green-50',    entrante: 'bg-blue-50',    perdida: 'bg-red-50' }
                const durStr = ll.duracion_segundos > 0
                  ? `${Math.floor(ll.duracion_segundos / 60)}m ${ll.duracion_segundos % 60}s`
                  : 'Sin respuesta'
                const isEditing = editingLlamadaId === ll.id
                return (
                  <div key={`ll-${ll.id}`} className="flex gap-3">
                    <div className={`w-8 h-8 rounded-full ${tipoBg[ll.tipo] || 'bg-gray-50'} flex items-center justify-center shrink-0`}>
                      <Phone size={14} className={tipoColor[ll.tipo] || 'text-gray-400'} />
                    </div>
                    <div className="flex-1 bg-white border border-gray-100 rounded-lg p-3 shadow-sm">
                      <div className="flex items-center justify-between gap-2 mb-0.5">
                        <span className="text-xs font-semibold text-gray-700">
                          Llamada {ll.tipo || ''}
                          <span className="ml-1.5 font-normal text-gray-400">— {durStr}</span>
                        </span>
                        <div className="flex items-center gap-1 shrink-0">
                          <span className="text-xs text-gray-400">{formatDateTime(ll.fecha_llamada)}</span>
                          {canEdit && !isEditing && (
                            <button
                              onClick={() => setEditingLlamadaId(ll.id)}
                              className="p-1 rounded hover:bg-indigo-50 text-gray-300 hover:text-indigo-500 transition-colors"
                              title="Agregar/editar notas"
                            >
                              <Edit2 size={12} />
                            </button>
                          )}
                          {((canAssign && !user?.role_id) || (user?.role_id && hasPermission(user, 'leads.delete'))) && !isEditing && (
                            <button
                              onClick={() => handleDeleteLlamada(ll.id)}
                              className="p-1 rounded hover:bg-red-50 text-gray-300 hover:text-red-400 transition-colors"
                              title="Eliminar llamada"
                            >
                              <Trash2 size={12} />
                            </button>
                          )}
                        </div>
                      </div>
                      <p className="text-sm text-gray-600 font-mono">{ll.telefono}</p>
                      {ll.asesor_nombre && (
                        <p className="text-xs text-gray-400 mt-0.5">{ll.asesor_nombre} · App Android</p>
                      )}
                      {/* V051: notas + resultado editables */}
                      {isEditing ? (
                        <LlamadaEditForm
                          llamada={ll}
                          resultados={resultadosContacto}
                          onCancel={() => setEditingLlamadaId(null)}
                          onSaved={async (changes) => {
                            try {
                              await api.patch(`/api/llamadas/${ll.id}`, changes)
                              setLlamadas(prev => prev.map(x => x.id === ll.id ? { ...x, ...changes, edited_at: new Date().toISOString() } : x))
                            } catch (err) {
                              alert(err.response?.data?.detail || 'Error al guardar')
                            } finally {
                              setEditingLlamadaId(null)
                            }
                          }}
                        />
                      ) : (
                        (ll.notas || ll.resultado) && (
                          <div className="mt-2 pt-2 border-t border-gray-100 space-y-1">
                            {ll.resultado && (
                              <p className="text-[11px] text-gray-500">
                                <span className="font-semibold">Resultado:</span> {ll.resultado}
                              </p>
                            )}
                            {ll.notas && (
                              <p className="text-[11px] text-gray-700 whitespace-pre-wrap">{ll.notas}</p>
                            )}
                          </div>
                        )
                      )}
                    </div>
                  </div>
                )
              }
              // entry._kind === 'contacto'
              const contacto = entry.data
              // Cambios de estado: renderizado compacto tipo sistema / auditoría
              if (contacto.tipo_contacto === 'cambio_estado') {
                const isAuto = Boolean(contacto.notas && (contacto.notas.toLowerCase().includes('automátic') || contacto.notas.toLowerCase().includes('automatic') || contacto.notas.toLowerCase().includes('sistema')))
                const isAdminSpecial = Boolean(contacto.notas && (contacto.notas.includes('Gestión por Administración') || contacto.notas.includes('Caso especial') || contacto.notas.includes('apagado el cambio')))
                const isReactivado = Boolean(contacto.notas && contacto.notas.includes('reactivado el cambio'))

                const badgeBg = isAdminSpecial ? 'bg-amber-100 text-amber-900 border-amber-300'
                  : isReactivado ? 'bg-emerald-100 text-emerald-800 border-emerald-300'
                  : isAuto ? 'bg-purple-100 text-purple-700 border-purple-200'
                  : 'bg-gray-100 text-gray-700 border-gray-200'

                const badgeLabel = isAdminSpecial ? '🛡️ Caso Especial Admin'
                  : isReactivado ? '🔄 Auto Reactivado'
                  : isAuto ? '🤖 Automatización'
                  : '🏷️ Manual'

                const cardBg = isAdminSpecial ? 'bg-amber-50/70 border-amber-200'
                  : isReactivado ? 'bg-emerald-50/60 border-emerald-200'
                  : isAuto ? 'bg-purple-50/50 border-purple-100'
                  : 'bg-amber-50/60 border-amber-100'

                const iconBg = isAdminSpecial ? 'bg-amber-100'
                  : isReactivado ? 'bg-emerald-100'
                  : isAuto ? 'bg-purple-50'
                  : 'bg-amber-50'

                return (
                  <div key={contacto.id} className="flex gap-3 items-center">
                    <div className={`w-8 h-8 rounded-full ${iconBg} flex items-center justify-center shrink-0`}>
                      {isAdminSpecial ? (
                        <Shield size={14} className="text-amber-700" />
                      ) : isReactivado ? (
                        <RefreshCw size={14} className="text-emerald-700" />
                      ) : isAuto ? (
                        <Bot size={14} className="text-purple-600" />
                      ) : (
                        <Tag size={14} className="text-amber-500" />
                      )}
                    </div>
                    <div className={`flex-1 ${cardBg} border rounded-lg px-3 py-2 flex items-center justify-between gap-3`}>
                      <div className="flex items-center gap-2 flex-wrap min-w-0">
                        <span className={`text-xs font-medium ${isAdminSpecial ? 'text-amber-950 font-semibold' : isReactivado ? 'text-emerald-950 font-semibold' : isAuto ? 'text-purple-900' : 'text-amber-700'}`}>
                          {contacto.notas}
                        </span>
                        <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-bold rounded border ${badgeBg}`}>
                          {badgeLabel}
                        </span>
                      </div>
                      <div className="text-right shrink-0">
                        <span className="text-xs text-gray-400 block">{formatDateTime(contacto.created_at)}</span>
                        {contacto.asesor_nombre ? (
                          <span className="text-xs text-gray-500 font-medium">por {contacto.asesor_nombre}</span>
                        ) : isAuto ? (
                          <span className="text-[11px] text-purple-600 font-medium">Sistema</span>
                        ) : null}
                      </div>
                    </div>
                  </div>
                )
              }

              // Eventos del sistema, reasignaciones y cambios de fuente: renderizado compacto de auditoría
              if (['sistema', 'reasignacion', 'cambio_fuente'].includes(contacto.tipo_contacto)) {
                const isReasig = contacto.tipo_contacto === 'reasignacion'
                const isFuente = contacto.tipo_contacto === 'cambio_fuente'
                return (
                  <div key={contacto.id} className="flex gap-3 items-center">
                    <div className={`w-8 h-8 rounded-full ${isReasig ? 'bg-blue-50' : isFuente ? 'bg-amber-50' : 'bg-purple-50'} flex items-center justify-center shrink-0`}>
                      {isReasig ? <RefreshCw size={14} className="text-blue-600" /> : isFuente ? <Tag size={14} className="text-amber-500" /> : <Bot size={14} className="text-purple-600" />}
                    </div>
                    <div className={`flex-1 ${isReasig ? 'bg-blue-50/50 border-blue-100' : isFuente ? 'bg-amber-50/60 border-amber-100' : 'bg-purple-50/50 border-purple-100'} border rounded-lg px-3 py-2 flex items-center justify-between gap-3`}>
                      <div className="flex items-center gap-2 flex-wrap min-w-0">
                        <span className={`text-xs font-medium ${isReasig ? 'text-blue-900' : isFuente ? 'text-amber-700' : 'text-purple-900'}`}>
                          {contacto.notas || contacto.resultado || 'Movimiento del sistema'}
                        </span>
                        <span className={`inline-flex items-center gap-1 px-1.5 py-0.5 text-[10px] font-bold rounded ${isReasig ? 'bg-blue-100 text-blue-700 border border-blue-200' : isFuente ? 'bg-amber-100 text-amber-700 border border-amber-200' : 'bg-purple-100 text-purple-700 border border-purple-200'}`}>
                          {isReasig ? '🔄 Reasignación' : isFuente ? '🏷️ Fuente' : '⚡ Sistema'}
                        </span>
                      </div>
                      <div className="text-right shrink-0">
                        <span className="text-xs text-gray-400 block">{formatDateTime(contacto.created_at)}</span>
                        {contacto.asesor_nombre ? (
                          <span className="text-xs text-gray-400">por {contacto.asesor_nombre}</span>
                        ) : (
                          <span className="text-[11px] text-purple-600 font-medium">Sistema</span>
                        )}
                      </div>
                    </div>
                  </div>
                )
              }

              // Contactos normales
              const esCita = contacto.resultado?.toLowerCase().includes('cita') || Boolean(contacto.fecha_cita) || Boolean(contacto.tipo_cita) || contacto.tipo_contacto?.toLowerCase().includes('cita') || Boolean(contacto.cita_estado_id)
              const tipoDisplay = contacto.tipo_cita || contacto.tipo_contacto
              return (
                <div key={contacto.id} className="flex gap-3">
                  <ContactoIcon tipo={tipoDisplay} />
                  <div className={`flex-1 bg-white rounded-lg p-3 shadow-sm ${esCita ? 'border border-indigo-200' : 'border border-gray-100'}`}>
                    <div className="flex items-center justify-between gap-2 mb-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="text-xs font-semibold text-gray-700 capitalize">
                          {tipoDisplay}
                          {contacto.resultado && (
                            <span className="ml-1.5 font-normal text-gray-400">— {contacto.resultado.replace(/_/g, ' ')}</span>
                          )}
                        </span>
                        {/* Fecha cita — siempre visible en el header cuando existe */}
                        {contacto.fecha_cita && (
                          <span className="inline-flex items-center gap-1 bg-indigo-100 text-indigo-700 text-[10px] font-bold rounded-full px-2 py-0.5">
                            <Calendar size={9} /> {formatDateTime(contacto.fecha_cita)}
                          </span>
                        )}
                        {/* Sin fecha pero es cita — advertencia */}
                        {esCita && !contacto.fecha_cita && (
                          <span className="inline-flex items-center gap-1 bg-amber-100 text-amber-700 text-[10px] font-bold rounded-full px-2 py-0.5">
                            <AlertCircle size={9} /> Sin fecha
                          </span>
                        )}
                      </div>
                      <div className="flex items-center gap-1 shrink-0">
                        <span className="text-xs text-gray-400">
                          {formatDateTime(contacto.created_at)}
                        </span>
                        {((canAssign && !user?.role_id) || (user?.role === 'asesor' && !user?.role_id && (contactPerms.asesor_can_edit || esCita)) || (user?.role_id && (esCita ? hasPermission(user, 'agenda.edit') : hasPermission(user, 'leads.edit')))) && (
                            <button
                              onClick={() => setEditingContactoId(
                                editingContactoId === contacto.id ? null : contacto.id
                              )}
                              className="p-1 rounded hover:bg-amber-50 text-gray-300 hover:text-amber-500 transition-colors"
                              title={esCita ? "Editar cita" : "Editar contacto"}
                            >
                              <Edit2 size={12} />
                            </button>
                        )}
                        {((canAssign && !user?.role_id) || (user?.role === 'asesor' && !user?.role_id && contactPerms.asesor_can_delete) || (user?.role_id && (esCita ? (hasPermission(user, 'agenda.edit') || hasPermission(user, 'leads.delete')) : hasPermission(user, 'leads.delete')))) && (
                            <button
                              onClick={() => handleDeleteContacto(contacto.id)}
                              disabled={deletingContactoId === contacto.id}
                              className="p-1 rounded hover:bg-red-50 text-gray-300 hover:text-red-400 disabled:opacity-50 transition-colors"
                              title="Eliminar contacto"
                            >
                              <Trash2 size={12} />
                            </button>
                        )}
                      </div>
                    </div>
                    {editingContactoId === contacto.id ? (
                      <EditContactoForm
                        leadId={id}
                        contacto={contacto}
                        tipos={tiposContacto}
                        tiposCita={tiposCita}
                        resultados={resultadosContacto}
                        citaEstados={citaEstados}
                        onOptimisticUpdate={(patch) => {
                          // V042 — actualiza el contacto en el array local
                          // CON PERSISTENCIA: el patch tiene los campos
                          // editados; los aplicamos sobre el contacto.
                          // Marcamos con __local_cita_estado para que el
                          // refreshHistorial no los pise si el GET no
                          // trae cita_estado_id (deploy lageado).
                          setContactos(prev => prev.map(c =>
                            c.id === patch.id
                              ? { ...c, ...patch, __local_cita_estado: patch.cita_estado_id != null }
                              : c
                          ))
                        }}
                        onSuccess={() => {
                          // V042: NO llamamos fetchLead aca. El optimistic
                          // update ya tiene los valores correctos. Llamar
                          // fetchLead corre el riesgo de pisar los datos
                          // si el backend deploy esta lageado y el GET
                          // no devuelve cita_estado_id. El polling de
                          // refreshHistorial cada 15s se encarga del
                          // sync eventual.
                          setEditingContactoId(null)
                        }}
                        onCancel={() => setEditingContactoId(null)}
                      />
                    ) : (
                      <>
                        {contacto.notas && contacto.notas !== 'null' && (
                          <p className="text-sm text-gray-600">{contacto.notas}</p>
                        )}
                        {contacto.proxima_accion && contacto.proxima_accion !== 'null' && (
                          <div className="mt-1.5 flex items-center gap-1.5 text-xs text-indigo-600">
                            <Calendar size={11} />
                            <span>{contacto.proxima_accion}</span>
                            {contacto.fecha_proxima_accion && (
                              <span className="text-gray-400">
                                · {formatDateTime(contacto.fecha_proxima_accion)}
                              </span>
                            )}
                          </div>
                        )}
                        {contacto.duracion_minutos && (
                          <p className="text-xs text-gray-400 mt-1">{contacto.duracion_minutos} min</p>
                        )}
                        {/* URL de reunión virtual en el historial */}
                        {contacto.url_reunion && (
                          <div className="mt-2">
                            <a
                              href={contacto.url_reunion.startsWith('http://') || contacto.url_reunion.startsWith('https://') ? contacto.url_reunion : `https://${contacto.url_reunion}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-50 hover:bg-indigo-100 dark:bg-indigo-950/40 dark:hover:bg-indigo-900/60 border border-indigo-200 dark:border-indigo-800/60 text-indigo-700 dark:text-indigo-300 text-xs font-semibold transition-colors"
                              title="Abrir enlace de reunión"
                            >
                              <Video size={13} className="text-indigo-600 dark:text-indigo-400" />
                              <span>Unirse a reunión virtual</span>
                              <ExternalLink size={11} className="text-indigo-400 ml-0.5" />
                            </a>
                          </div>
                        )}
                        {/* V042 — Footer del card: 'por {asesor}' a la izquierda
                            y badge de estado de cita a la derecha (bottom-right
                            como pidio el usuario). Ambos en la misma fila con
                            justify-between. Si no hay cita, solo se ve el asesor. */}
                        <div className="mt-1.5 flex items-end justify-between gap-2">
                          <p className="text-xs text-gray-400">
                            {contacto.asesor_nombre ? `por ${contacto.asesor_nombre}` : ''}
                          </p>
                          {contacto.fecha_cita && (() => {
                            const estadoNombre = contacto.cita_estado_nombre || 'Pendiente'
                            const estadoColor  = contacto.cita_estado_color  || '#3B82F6'
                            const code = (contacto.cita_estado_codigo || estadoNombre || '').toLowerCase()
                            const StatusIcon =
                              code.includes('pendiente')  ? Clock :
                              code.includes('completa')   ? CheckCircle :
                              code.includes('reprogram')  ? RefreshCw :
                              code.includes('cancel')     ? XCircle :
                              code.includes('asisti')     ? AlertCircle :
                              Calendar
                            return (
                              <button
                                type="button"
                                onClick={() => setEditingContactoId(contacto.id)}
                                className="inline-flex items-center gap-1.5 text-xs font-semibold px-2.5 py-1 rounded-full border-2 hover:scale-[1.03] transition-transform cursor-pointer shrink-0"
                                style={{
                                  backgroundColor: estadoColor + '15',
                                  color: estadoColor,
                                  borderColor: estadoColor + '60',
                                }}
                                title="Click para cambiar el estado de la cita"
                              >
                                <StatusIcon size={12} />
                                Cita: {estadoNombre}
                              </button>
                            )
                          })()}
                        </div>
                      </>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
            )
          })()}
        </div>
      </div>
        </>
      )}

      {/* Modal de confirmación para eliminar */}
      <ConfirmDialog
        open={confirmDialog.open}
        title={confirmDialog.type === 'contacto' ? 'Eliminar contacto' : 'Eliminar llamada'}
        message="¿Estás seguro de que deseas eliminar este registro del historial? Esta acción no se puede deshacer."
        onConfirm={handleConfirmDelete}
        onCancel={() => setConfirmDialog({ open: false, type: null, id: null })}
      />

      {/* V070.81 — Modal: Confirmar derivacion del lead a asesor antecedente */}
      <ConfirmDialog
        open={!!confirmDerivar}
        variant="warning"
        title="Derivar lead al asesor antecedente"
        confirmLabel="Sí, derivar"
        cancelLabel="Cancelar"
        message={confirmDerivar
          ? `Vas a derivar este lead a ${confirmDerivar.asesorNombre || 'el asesor original'}. El lead quedará asignado a ese asesor y reemplazará al asesor actual.`
          : ''}
        onConfirm={handleDerivarAntecedenteConfirm}
        onCancel={() => setConfirmDerivar(null)}
      />

      {/* Modal de salida WhatsApp — wa.me + registro del intento */}
      {showWaModal && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="bg-white rounded-xl shadow-xl w-full max-w-md overflow-hidden">
            <div className="px-5 py-3 border-b border-gray-200 bg-green-50 flex items-center justify-between">
              <h3 className="text-sm font-semibold text-green-800 flex items-center gap-2">
                <MessageCircle size={16} /> Contactar por WhatsApp
              </h3>
              <button
                onClick={() => setShowWaModal(false)}
                className="text-gray-400 hover:text-gray-600"
              >
                <X size={16} />
              </button>
            </div>
            <div className="p-5 space-y-3">
              <div className="text-xs text-gray-600 bg-amber-50 border border-amber-200 rounded-md p-2.5">
                Abriremos el chat de este lead en el panel Chat con el mensaje
                pre-cargado. Solo debes revisar y apretar enviar.
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600 block mb-1">
                  Para: <span className="font-mono text-gray-800">+{normalizeWaPhone(lead?.telefono)}</span>
                </label>
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600 block mb-1">Mensaje</label>
                <textarea
                  value={waMessage}
                  onChange={e => setWaMessage(e.target.value)}
                  rows={5}
                  maxLength={1000}
                  className="w-full text-sm border border-gray-200 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-green-500"
                />
                <div className="text-[10px] text-gray-400 text-right mt-0.5">
                  {waMessage.length}/1000
                </div>
              </div>
              <div className="flex items-center justify-end gap-2 pt-2">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => setShowWaModal(false)}
                  disabled={sendingWa}
                >
                  Cancelar
                </Button>
                <Button
                  size="sm"
                  onClick={handleWaOutreach}
                  disabled={sendingWa || !waMessage.trim()}
                  className="bg-green-600 hover:bg-green-700 text-white gap-1.5"
                >
                  <MessageCircle size={13} />
                  {sendingWa ? 'Abriendo…' : 'Abrir en Chat'}
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* V127: Modal interactivo de fusión de leads */}
      <FusionarLeadModal
        currentLead={lead}
        candidateDuplicates={duplicateCandidates}
        isOpen={showMergeModal}
        onClose={() => setShowMergeModal(false)}
        onSuccess={() => {
          fetchLead()
          setHistorialCount((c) => c + 1)
        }}
      />

      {/* V064: Auto-next lead Netflix-style. Aparece tras 1.5s en bottom-right
          con el siguiente lead recomendado (excluye el actual). Dismissable
          y solo se muestra si hay un proximo distinto. */}
      <NextLeadFooter currentLeadId={id} />
    </div>
  )
}
