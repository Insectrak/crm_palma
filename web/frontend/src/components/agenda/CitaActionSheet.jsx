/**
 * CitaActionSheet — modal de acciones rapidas sobre una cita (paridad mobile).
 *
 * V096 — Antes en /agenda, click en una cita navegaba directo al detalle del
 * lead. Para cambiar el estado de la cita (Completada/Cancelada/No asistio)
 * o reprogramarla, el asesor tenia que: navegar al lead -> abrir edit form
 * del contacto -> cambiar fecha o estado -> guardar -> volver a agenda.
 * 4 pasos vs 1 click en mobile.
 *
 * Ahora: click en cita abre este sheet con:
 *   - Info compacta (hora, fecha larga, tipo, estado actual con chip color)
 *   - Card del lead con telefono + asesor
 *   - Cambio rapido del estado del LEAD (Salesforce-style picker inline)
 *   - CTAs: Llamar al lead (tel:) + Completada / Reprogramar / No asistio
 *   - Cancelar como link destructivo abajo
 *   - Si estado final: Reabrir + Reprogramar
 *
 * Endpoints reusados:
 *   PATCH /api/leads/{leadId}/contactos/{contactoId} — cambia cita_estado_id
 *                                                     y/o fecha_cita
 *   PATCH /api/leads/{leadId}/estado                  — cambia estado del lead
 */
import { useState, useMemo, useEffect } from 'react'
import { Link } from 'react-router-dom'
import {
  X, Phone, Video, Mail, MapPin, MessageCircle,
  CheckCircle2, Calendar, UserX, RotateCcw, ChevronDown, ChevronRight, Loader2,
  Check, Copy, ExternalLink, Clock, Sparkles,
} from 'lucide-react'
import api from '@/lib/api'
import CambioEstadoModal, { requiresFormularioEspecifico } from '@/components/leads/CambioEstadoModal'

const MESES_ES = [
  'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio',
  'julio', 'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre',
]
const DIAS_ES = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado']

function parseLimaDateTime(iso) {
  if (!iso) return null
  const s = String(iso).trim()
  const hasTz = /[Zz]$|[+-]\d{2}(:\d{2})?$/.test(s)
  if (!hasTz) {
    const match = s.match(/(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})/)
    if (match) {
      return {
        date: `${match[1]}-${match[2]}-${match[3]}`,
        time: `${match[4]}:${match[5]}`,
        year: parseInt(match[1], 10),
        month: parseInt(match[2], 10) - 1,
        day: parseInt(match[3], 10),
      }
    }
  }
  try {
    let normalized = s.replace(' ', 'T')
    normalized = normalized.replace(/([+-]\d{2})$/, match => match + ':00')
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

      return {
        date: `${dMap.year}-${dMap.month}-${dMap.day}`,
        time: `${tMap.hour}:${tMap.minute}`,
        year: parseInt(dMap.year, 10),
        month: parseInt(dMap.month, 10) - 1,
        day: parseInt(dMap.day, 10),
      }
    }
  } catch {}
  return null
}

function formatHora(iso) {
  const parsed = parseLimaDateTime(iso)
  return parsed ? parsed.time : '--:--'
}

function formatFechaLarga(iso) {
  const parsed = parseLimaDateTime(iso)
  if (!parsed) return ''
  const dt = new Date(parsed.year, parsed.month, parsed.day)
  const diaNombre = Number.isNaN(dt.getTime()) ? '' : DIAS_ES[dt.getDay()]
  return `${diaNombre}, ${parsed.day} de ${MESES_ES[parsed.month] || ''} ${parsed.year}`
}

function tipoIcon(tipo) {
  const t = String(tipo || '').toLowerCase()
  if (t.includes('virtual') || t.includes('video')) return Video
  if (t.includes('whatsapp'))                       return MessageCircle
  if (t.includes('email'))                          return Mail
  if (t.includes('oficina') || t.includes('exterior') || t.includes('presencial')) return MapPin
  return Phone
}

/** Parsea ISO local y devuelve componentes para inputs date+time. */
function isoToDateTime(iso) {
  const parsed = parseLimaDateTime(iso)
  if (!parsed) return { date: '', time: '' }
  return { date: parsed.date, time: parsed.time }
}

function dateTimeToIso(date, time) {
  if (!date || !time) return null
  return `${date}T${time}:00`
}

export default function CitaActionSheet({
  cita,
  citaEstados = [],
  leadEstados = [],
  onClose,
  onUpdated,            // (citaActualizada) — refresh externo
  onLeadEstadoChanged,  // (leadId, nuevoEstado) — refresh externo
}) {
  const [busy, setBusy]                     = useState(false)
  const [errorMsg, setErrorMsg]             = useState(null)
  const [showReprogramar, setShowReprogramar] = useState(false)
  const [reprogDate, setReprogDate] = useState('')
  const [reprogTime, setReprogTime] = useState('')
  const [cambioEstadoModal, setCambioEstadoModal] = useState({ open: false, targetEstado: null })
  const [allUsersList, setAllUsersList] = useState([])
  const [reprogStep, setReprogStep]         = useState('date')   // 'date' | 'time'
  const [showLeadEstadoPicker, setShowLeadEstadoPicker] = useState(false)
  // V096 — confirmacion inline para Cancelar (evita window.confirm intrusivo).
  const [showCancelConfirm, setShowCancelConfirm] = useState(false)
  // V096 — sugerencia inline de avanzar lead Nuevo→Contactado tras Completada.
  // Debe declararse ANTES del early return (if !cita) para respetar Rules of Hooks.
  const [suggestAdvance, setSuggestAdvance] = useState(false)
  const [copiedUrl, setCopiedUrl] = useState(false)
  const [notas, setNotas] = useState(cita?.notas || '')
  const [guardadoExito, setGuardadoExito] = useState(false)

  useEffect(() => {
    api.get('/auth/users').then(res => setAllUsersList(res.data || [])).catch(() => {})
  }, [])

  const copyUrl = (e) => {
    e?.stopPropagation()
    if (!cita?.url_reunion) return
    const url = cita.url_reunion.startsWith('http://') || cita.url_reunion.startsWith('https://')
      ? cita.url_reunion
      : `https://${cita.url_reunion}`
    navigator.clipboard?.writeText(url)
    setCopiedUrl(true)
    setTimeout(() => setCopiedUrl(false), 2000)
  }

  // ESC cierra el sheet.
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose?.() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // Reset interno al cambiar de cita.
  useEffect(() => {
    setShowReprogramar(false)
    setShowLeadEstadoPicker(false)
    setShowCancelConfirm(false)
    setErrorMsg(null)
    setGuardadoExito(false)
    setNotas(cita?.notas || '')
    if (cita?.fecha_evento) {
      const { date, time } = isoToDateTime(cita.fecha_evento)
      setReprogDate(date)
      setReprogTime(time)
      setReprogStep('date')
    }
  }, [cita?.id, cita?.fecha_evento, cita?.notas])

  const estadoIdByCode = useMemo(() => {
    const map = {}
    ;(citaEstados || []).forEach(e => {
      if (e?.codigo) map[String(e.codigo).toLowerCase()] = e.id
    })
    return map
  }, [citaEstados])

  const agregarChipNota = (texto) => {
    setNotas(prev => {
      const trimmed = (prev || '').trim()
      if (!trimmed) return texto
      if (trimmed.includes(texto)) return trimmed
      return `${trimmed} · ${texto}`
    })
  }

  if (!cita) return null

  const itemKind = cita.item_kind === 'seguimiento' || cita.tipo_contacto === 'seguimiento'
    ? 'seguimiento'
    : (cita.item_kind === 'oportunidad_futura' || cita.tipo_contacto === 'oportunidad_futura')
      ? 'oportunidad_futura'
      : 'cita'
  const isLeadAgendaItem = itemKind === 'seguimiento' || itemKind === 'oportunidad_futura'

  const tipoValor = cita.tipo_cita || cita.tipo_contacto || 'cita'
  const Icon = itemKind === 'seguimiento'
    ? Clock
    : itemKind === 'oportunidad_futura'
      ? Sparkles
      : tipoIcon(tipoValor)
  const hora = formatHora(cita.fecha_evento)
  const fechaLarga = formatFechaLarga(cita.fecha_evento)
  const tipoLabel = itemKind === 'seguimiento'
    ? 'Seguimiento'
    : itemKind === 'oportunidad_futura'
      ? 'Oportunidad futura'
      : tipoValor.replace(/^./, c => c.toUpperCase())
  const titulo = cita.proxima_accion || ''
  const leadName = cita.lead_nombre || 'Sin lead'
  const phone = cita.lead_telefono || ''
  const estadoNombre = isLeadAgendaItem
    ? (itemKind === 'seguimiento' ? 'En seguimiento' : 'Oportunidad futura')
    : cita.cita_estado_nombre
  const estadoColor = itemKind === 'seguimiento'
    ? '#2563EB'
    : itemKind === 'oportunidad_futura'
      ? '#7C3AED'
      : (cita.cita_estado_color || '#3B82F6')
  const estadoCodigo = String(cita.cita_estado_codigo || '').toLowerCase()
  const isCompletada = estadoCodigo === 'completada'
  const isCancelada  = estadoCodigo === 'cancelada'
  const isNoAsistio  = estadoCodigo === 'no_asistio'
  const isFinal = isCompletada || isCancelada || isNoAsistio

  /* ── Actions ─────────────────────────────────────────────────────── */

  const patchCita = async ({ cita_estado_id, fecha_cita, notas: overrideNotas }) => {
    if (!cita.lead_id) return null
    const finalNotas = overrideNotas !== undefined ? overrideNotas : notas
    const payload = {
      tipo_contacto: cita.tipo_contacto || 'llamada',
      tipo_cita:     cita.tipo_cita || undefined,
      notas:         finalNotas !== '' ? finalNotas : null,
    }
    if (cita_estado_id !== undefined) payload.cita_estado_id = cita_estado_id
    if (fecha_cita     !== undefined) payload.fecha_cita     = fecha_cita
    await api.patch(`/api/leads/${cita.lead_id}/contactos/${cita.id}`, payload)
    return payload
  }

  const guardarNotas = async () => {
    setBusy(true)
    setErrorMsg(null)
    setGuardadoExito(false)
    try {
      await patchCita({ notas })
      onUpdated?.({
        ...cita,
        notas: notas !== '' ? notas : null,
      })
      setGuardadoExito(true)
      setTimeout(() => setGuardadoExito(false), 2500)
    } catch (err) {
      setErrorMsg(err.response?.data?.detail || 'No se pudo guardar la observación.')
    } finally {
      setBusy(false)
    }
  }

  const setEstado = async (codigo, { close = true } = {}) => {
    const estadoId = estadoIdByCode[codigo]
    if (!estadoId) {
      setErrorMsg(`No se encontró el estado "${codigo}" en el catálogo. Pídele al admin que lo agregue.`)
      return
    }
    setBusy(true)
    setErrorMsg(null)
    try {
      await patchCita({ cita_estado_id: estadoId, notas })
      const estadoObj = (citaEstados || []).find(e => e.id === estadoId)
      onUpdated?.({
        ...cita,
        notas:              notas !== '' ? notas : null,
        cita_estado_id:     estadoId,
        cita_estado_codigo: estadoObj?.codigo || codigo,
        cita_estado_nombre: estadoObj?.nombre || cita.cita_estado_nombre,
        cita_estado_color:  estadoObj?.color_hex || cita.cita_estado_color,
      })
      if (close) onClose?.()
    } catch (err) {
      setErrorMsg(err.response?.data?.detail || err.message || 'No se pudo actualizar la cita.')
    } finally {
      setBusy(false)
    }
  }

  // V096 — Sugiere avanzar lead Nuevo→Contactado tras Completada.
  // El useState vive arriba (junto al resto) por Rules of Hooks; aqui solo
  // queda la accion que lo utiliza.
  const completar = async () => {
    await setEstado('completada', { close: false })
    const codigo = String(cita.lead_estado_codigo || cita.lead_estado_nombre || '').toLowerCase()
    if (codigo.includes('nuevo')) {
      const contactado = (leadEstados || []).find(e =>
        String(e.nombre || '').toLowerCase() === 'contactado'
      )
      if (contactado) {
        setSuggestAdvance(true)
        return
      }
    }
    onClose?.()
  }

  const acceptAdvance = async () => {
    const contactado = (leadEstados || []).find(e =>
      String(e.nombre || '').toLowerCase() === 'contactado'
    )
    if (!contactado) { setSuggestAdvance(false); onClose?.(); return }
    setBusy(true)
    try {
      await api.patch(`/api/leads/${cita.lead_id}/estado`, { estado_id: contactado.id })
      onLeadEstadoChanged?.(cita.lead_id, contactado)
      setSuggestAdvance(false)
      onClose?.()
    } catch (err) {
      setErrorMsg(err.response?.data?.detail || 'No se pudo avanzar el lead.')
    } finally {
      setBusy(false)
    }
  }

  const changeLeadEstado = async (estadoIdOrPayload) => {
    const isObj = typeof estadoIdOrPayload === 'object' && estadoIdOrPayload !== null
    const payload = isObj ? estadoIdOrPayload : { estado_id: estadoIdOrPayload }
    const estadoId = payload.estado_id
    const estado = (leadEstados || []).find(e => e.id === estadoId)
    if (!estado) return

    if (!isObj && requiresFormularioEspecifico(estado.nombre)) {
      setShowLeadEstadoPicker(false)
      setCambioEstadoModal({ open: true, targetEstado: estado })
      return
    }

    setBusy(true)
    setErrorMsg(null)
    try {
      await api.patch(`/api/leads/${cita.lead_id}/estado`, payload)
      onLeadEstadoChanged?.(cita.lead_id, estado)
      setShowLeadEstadoPicker(false)
    } catch (err) {
      setErrorMsg(err.response?.data?.detail || 'No se pudo cambiar el estado del lead.')
    } finally {
      setBusy(false)
    }
  }

  const reprogramar = async () => {
    const iso = dateTimeToIso(reprogDate, reprogTime)
    if (!iso) {
      setErrorMsg('Selecciona fecha y hora antes de reprogramar.')
      return
    }
    // Tolerancia 5 min al pasado (defense in depth — backend tambien valida).
    const target = new Date(iso).getTime()
    if (Number.isNaN(target) || target < Date.now() - 5 * 60 * 1000) {
      setErrorMsg('No puedes reprogramar a una fecha pasada.')
      return
    }
    setBusy(true)
    setErrorMsg(null)
    try {
      if (isLeadAgendaItem) {
        const payload = { fecha_proxima_gestion: `${iso}-05:00` }
        if (itemKind === 'oportunidad_futura' && (notas || '').trim()) {
          payload.accion_proxima_gestion = notas.trim()
        }
        await api.patch(`/api/leads/${cita.lead_id}`, payload)
        onUpdated?.({
          ...cita,
          fecha_evento: iso,
          notas: (notas || '').trim() || cita.notas,
          proxima_accion: payload.accion_proxima_gestion || cita.proxima_accion,
        })
        onClose?.()
        return
      }
      const reprogId = estadoIdByCode['reprogramada'] || cita.cita_estado_id
      await patchCita({ fecha_cita: iso, cita_estado_id: reprogId, notas })
      const estadoObj = (citaEstados || []).find(e => e.id === reprogId)
      onUpdated?.({
        ...cita,
        fecha_evento:       iso,
        notas:              notas !== '' ? notas : null,
        cita_estado_id:     reprogId,
        cita_estado_codigo: estadoObj?.codigo || 'reprogramada',
        cita_estado_nombre: estadoObj?.nombre || cita.cita_estado_nombre,
        cita_estado_color:  estadoObj?.color_hex || cita.cita_estado_color,
      })
      onClose?.()
    } catch (err) {
      setErrorMsg(err.response?.data?.detail || 'No se pudo reprogramar.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {/* Backdrop oscuro */}
      <div
        className="fixed inset-0 bg-black/40 z-40 transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />

      {/* Side panel desde la derecha (Salesforce-style detail sheet en escritorio) */}
      <div
        className="fixed top-0 right-0 bottom-0 w-full max-w-md bg-white dark:bg-[#121a29] dark:border-l dark:border-slate-800 shadow-2xl z-50 flex flex-col overflow-hidden"
        role="dialog"
        aria-modal="true"
        aria-label={`Cita: ${tipoLabel} con ${leadName}`}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3 px-5 py-4 border-b border-gray-100 dark:border-slate-800">
          <div className="flex items-start gap-3 flex-1 min-w-0">
            <div className="w-10 h-10 rounded-full bg-indigo-50 dark:bg-indigo-950/60 flex items-center justify-center shrink-0">
              <Icon size={20} className="text-indigo-600 dark:text-indigo-400" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className="text-base font-bold text-gray-900 dark:text-slate-100 tabular-nums">{hora}</span>
                <span className="text-sm font-semibold text-indigo-600 dark:text-indigo-400">{tipoLabel}</span>
                {estadoNombre && (
                  <span
                    className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-semibold border"
                    style={{
                      backgroundColor: estadoColor + '22',
                      borderColor:     estadoColor + '55',
                      color:           estadoColor,
                    }}
                  >
                    {estadoNombre}
                  </span>
                )}
              </div>
              <p className="text-xs text-gray-500 dark:text-slate-400 mt-0.5 capitalize">{fechaLarga}</p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-gray-100 dark:hover:bg-slate-800 text-gray-400 hover:text-gray-600 dark:hover:text-slate-200 shrink-0 cursor-pointer"
            aria-label="Cerrar"
          >
            <X size={20} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          {titulo && (
            <p className="text-sm text-gray-700 dark:text-slate-200 line-clamp-3">{titulo}</p>
          )}

          {/* Lead card */}
          <div>
            <p className="text-[11px] uppercase tracking-wide text-gray-400 dark:text-slate-500 font-semibold mb-1.5">Lead</p>
            {cita.lead_id ? (
              <Link
                to={`/leads/${cita.lead_id}`}
                onClick={onClose}
                className="flex items-center gap-2 p-3 rounded-lg border border-gray-200 dark:border-slate-800 hover:bg-gray-50 dark:hover:bg-slate-800/50 hover:border-gray-300 dark:hover:border-slate-700 transition-colors"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-bold text-gray-900 dark:text-slate-100 truncate">{leadName}</p>
                  {phone && <p className="text-xs text-gray-500 dark:text-slate-400 font-mono mt-0.5">{phone}</p>}
                  {cita.asesor_nombre?.trim() && (
                    <p className="text-xs text-gray-400 dark:text-slate-500 mt-0.5">Asesor: {cita.asesor_nombre}</p>
                  )}
                </div>
                <ChevronRight size={18} className="text-gray-300 dark:text-slate-600 shrink-0" />
              </Link>
            ) : (
              <div className="p-3 rounded-lg border border-gray-200 dark:border-slate-800 bg-gray-50 dark:bg-slate-800/40 opacity-60">
                <p className="text-sm text-gray-500 dark:text-slate-400">Sin lead vinculado</p>
              </div>
            )}
          </div>

          {/* Enlace de Reunión Virtual (Meet / Zoom) */}
          {cita.url_reunion && (
            <div className="rounded-xl border border-sky-200 dark:border-sky-800/60 bg-gradient-to-br from-sky-50 to-indigo-50/50 dark:from-sky-950/40 dark:to-indigo-950/30 p-3.5 space-y-2.5 shadow-2xs">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <div className="w-7 h-7 rounded-lg bg-sky-500 text-white flex items-center justify-center shadow-xs">
                    <Video size={15} />
                  </div>
                  <div>
                    <p className="text-xs font-bold text-sky-950 dark:text-sky-200">Reunión Virtual</p>
                    <p className="text-[10px] text-sky-700 dark:text-sky-300">Enlace de videollamada programada</p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={copyUrl}
                  className="inline-flex items-center gap-1 text-xs font-medium text-sky-700 dark:text-sky-300 hover:text-sky-900 dark:hover:text-sky-100 bg-white/90 dark:bg-slate-800/90 hover:bg-white dark:hover:bg-slate-700 px-2 py-1 rounded-md border border-sky-200 dark:border-sky-800 shadow-2xs transition-colors cursor-pointer"
                  title="Copiar enlace"
                >
                  {copiedUrl ? <Check size={12} className="text-emerald-600 dark:text-emerald-400" /> : <Copy size={12} />}
                  <span>{copiedUrl ? '¡Copiado!' : 'Copiar'}</span>
                </button>
              </div>

              <div className="bg-white/90 dark:bg-[#090e17] border border-sky-100 dark:border-sky-900/60 rounded-lg px-2.5 py-1.5 flex items-center justify-between">
                <p className="text-xs font-mono text-gray-800 dark:text-sky-200 truncate select-all">{cita.url_reunion}</p>
              </div>

              <a
                href={cita.url_reunion.startsWith('http://') || cita.url_reunion.startsWith('https://') ? cita.url_reunion : `https://${cita.url_reunion}`}
                target="_blank"
                rel="noopener noreferrer"
                className="w-full py-2 px-3 rounded-lg bg-sky-600 hover:bg-sky-500 active:bg-sky-700 text-white text-xs font-bold flex items-center justify-center gap-2 shadow-xs transition-colors cursor-pointer"
              >
                <Video size={14} />
                <span>Unirse a la reunión</span>
                <ExternalLink size={12} className="opacity-80" />
              </a>
            </div>
          )}

          {/* Campo de Observaciones / Tipificación de la cita */}
          {!isLeadAgendaItem && (
          <div className="border border-gray-200 dark:border-slate-800 rounded-xl p-3.5 bg-gray-50/60 dark:bg-slate-800/30 space-y-2">
            <div className="flex items-center justify-between">
              <label className="text-xs font-bold text-gray-700 dark:text-slate-300 flex items-center gap-1.5">
                <span>Observaciones / Tipificación</span>
                {/potencial|cierre/i.test(notas) && (
                  <span className="text-[10px] px-1.5 py-0.2 rounded-full font-semibold bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300 border border-amber-300">
                    ⭐ Alto potencial
                  </span>
                )}
              </label>
              {guardadoExito && (
                <span className="text-[11px] font-semibold text-emerald-600 dark:text-emerald-400 flex items-center gap-0.5">
                  <Check size={12} /> Guardado
                </span>
              )}
            </div>
            <textarea
              value={notas}
              onChange={e => setNotas(e.target.value)}
              placeholder="Detalle u observación de la cita (ej: cliente tiene alto interés, reprogramar para firma)..."
              rows={2}
              className="w-full px-3 py-2 text-xs border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-gray-900 dark:text-slate-100 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none shadow-2xs"
            />
            <div className="flex items-center justify-between gap-2 flex-wrap pt-0.5">
              <div className="flex items-center gap-1 flex-wrap">
                {[
                  '⭐ Alto potencial de cierre',
                  '📞 Volver a llamar',
                  '🗓️ Cliente solicitó postergar',
                  '💰 Interesado en facilidades',
                ].map(chip => (
                  <button
                    key={chip}
                    type="button"
                    onClick={() => agregarChipNota(chip)}
                    className="text-[10px] font-medium bg-white dark:bg-slate-800 hover:bg-indigo-50 dark:hover:bg-indigo-950/60 hover:text-indigo-600 dark:hover:text-indigo-400 text-gray-600 dark:text-slate-300 px-2 py-0.5 rounded-md border border-gray-200 dark:border-slate-700 transition-colors cursor-pointer"
                  >
                    {chip}
                  </button>
                ))}
              </div>
              <button
                type="button"
                onClick={guardarNotas}
                disabled={busy}
                className="text-xs font-semibold px-2.5 py-1 rounded-md bg-indigo-600 hover:bg-indigo-700 text-white transition-colors disabled:opacity-50 cursor-pointer shadow-2xs"
              >
                Guardar nota
              </button>
            </div>
          </div>
          )}

          {/* Estado del lead (cambio inline — V096.5) */}
          {cita.lead_id && leadEstados.length > 0 && (
            <div>
              <button
                onClick={() => setShowLeadEstadoPicker(v => !v)}
                disabled={busy}
                className="w-full flex items-center justify-between p-3 rounded-lg border border-gray-200 dark:border-slate-800 hover:bg-gray-50 dark:hover:bg-slate-800/50 transition-colors text-left disabled:opacity-50"
              >
                <span className="text-sm font-semibold text-gray-600 dark:text-slate-300">Estado del lead</span>
                <span className="flex items-center gap-1.5">
                  <span className="text-sm font-bold text-indigo-600 dark:text-indigo-400">
                    {cita.lead_estado_nombre || 'Sin estado'}
                  </span>
                  <ChevronDown size={14} className={`text-gray-400 transition-transform ${showLeadEstadoPicker ? 'rotate-180' : ''}`} />
                </span>
              </button>
              {showLeadEstadoPicker && (
                <div className="mt-2 border border-gray-200 dark:border-slate-800 rounded-lg overflow-hidden bg-white dark:bg-[#121a29] shadow-sm">
                  {leadEstados.map(e => (
                    <button
                      key={e.id}
                      onClick={() => changeLeadEstado(e.id)}
                      disabled={busy || e.id === cita.lead_estado_id}
                      className={`w-full px-3 py-2 text-sm text-left hover:bg-indigo-50 dark:hover:bg-indigo-950/50 disabled:opacity-50 disabled:bg-gray-50 dark:disabled:bg-slate-800/50 border-b border-gray-100 dark:border-slate-800 last:border-b-0 ${e.id === cita.lead_estado_id ? 'bg-indigo-50 dark:bg-indigo-950/50 font-semibold text-indigo-700 dark:text-indigo-300' : 'text-gray-700 dark:text-slate-300'}`}
                    >
                      {e.nombre}
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* Error inline */}
          {errorMsg && (
            <div className="bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/60 text-rose-700 dark:text-rose-300 text-xs rounded-md px-3 py-2">
              {errorMsg}
            </div>
          )}

          {/* Reprogramar — picker 2-step (V096.4) */}
          {showReprogramar && (
            <div className="border border-indigo-200 dark:border-indigo-900/60 bg-indigo-50/40 dark:bg-indigo-950/30 rounded-lg p-3 space-y-2.5">
              <p className="text-xs font-semibold text-indigo-900 dark:text-indigo-300 mb-1">
                {reprogStep === 'date' ? '1. Nueva fecha' : '2. Nueva hora y motivo/observación'}
              </p>
              {reprogStep === 'date' ? (
                <input
                  type="date"
                  value={reprogDate}
                  onChange={e => setReprogDate(e.target.value)}
                  min={new Date().toISOString().slice(0, 10)}
                  className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-gray-900 dark:text-slate-100 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              ) : (
                <div className="space-y-2">
                  <input
                    type="time"
                    value={reprogTime}
                    onChange={e => setReprogTime(e.target.value)}
                    className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-gray-900 dark:text-slate-100 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                  <div>
                    <label className="text-[11px] font-semibold text-indigo-950 dark:text-indigo-200">
                      Observación de reprogramación
                    </label>
                    <textarea
                      value={notas}
                      onChange={e => setNotas(e.target.value)}
                      placeholder="Motivo o potencial de la reprogramación..."
                      rows={2}
                      className="w-full mt-1 px-2.5 py-1.5 text-xs border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-gray-900 dark:text-slate-100 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
                    />
                    <div className="flex items-center gap-1 flex-wrap mt-1">
                      {['⭐ Alto potencial de cierre', '🗓️ Cliente postergó', '📞 Volver a llamar'].map(ch => (
                        <button
                          key={ch}
                          type="button"
                          onClick={() => agregarChipNota(ch)}
                          className="text-[10px] font-medium bg-white dark:bg-slate-800 text-indigo-700 dark:text-indigo-300 px-1.5 py-0.5 rounded border border-indigo-200 dark:border-indigo-800 hover:bg-indigo-50 transition-colors cursor-pointer"
                        >
                          {ch}
                        </button>
                      ))}
                    </div>
                  </div>
                </div>
              )}
              <div className="flex gap-2 pt-1">
                <button
                  onClick={() => { setShowReprogramar(false); setReprogStep('date') }}
                  disabled={busy}
                  className="flex-1 px-3 py-1.5 text-xs font-medium border border-gray-200 dark:border-slate-700 rounded-md hover:bg-gray-50 dark:hover:bg-slate-800 text-gray-600 dark:text-slate-300 disabled:opacity-50"
                >
                  Cancelar
                </button>
                {reprogStep === 'date' ? (
                  <button
                    onClick={() => setReprogStep('time')}
                    disabled={busy || !reprogDate}
                    className="flex-1 px-3 py-1.5 text-xs font-bold rounded-md bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
                  >
                    Siguiente →
                  </button>
                ) : (
                  <button
                    onClick={reprogramar}
                    disabled={busy || !reprogTime}
                    className="flex-1 px-3 py-1.5 text-xs font-bold rounded-md bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50"
                  >
                    {busy ? 'Guardando…' : 'Confirmar reprogramación'}
                  </button>
                )}
              </div>
            </div>
          )}

          {/* Sugerencia avanzar lead post-Completada */}
          {suggestAdvance && (
            <div className="border border-emerald-200 dark:border-emerald-900/60 bg-emerald-50 dark:bg-emerald-950/30 rounded-lg p-3">
              <p className="text-sm font-semibold text-emerald-900 dark:text-emerald-300">¿Avanzar el lead?</p>
              <p className="text-xs text-emerald-800 dark:text-emerald-400 mt-1 mb-3">
                <strong>{leadName}</strong> está en "Nuevo". Como completaste la cita, ¿lo marcas como "Contactado"?
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => { setSuggestAdvance(false); onClose?.() }}
                  disabled={busy}
                  className="flex-1 px-3 py-1.5 text-xs font-medium border border-gray-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-800 hover:bg-gray-50 dark:hover:bg-slate-700 text-gray-600 dark:text-slate-300 disabled:opacity-50"
                >
                  No, dejar así
                </button>
                <button
                  onClick={acceptAdvance}
                  disabled={busy}
                  className="flex-1 px-3 py-1.5 text-xs font-bold rounded-md bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50"
                >
                  Sí, avanzar
                </button>
              </div>
            </div>
          )}

          {/* Acciones — distintas si es seguimiento/oportunidad o cita */}
          {!showReprogramar && !suggestAdvance && (
            <div>
              <p className="text-[11px] uppercase tracking-wide text-gray-400 dark:text-slate-500 font-semibold mb-2">Acciones</p>
              {isLeadAgendaItem ? (
                <div className="space-y-2">
                  <ActionRow
                    icon={Calendar}
                    label="Reprogramar fecha y hora"
                    color="#3b82f6"
                    onClick={() => setShowReprogramar(true)}
                    disabled={busy}
                  />
                  {cita.lead_id && (
                    <Link
                      to={`/leads/${cita.lead_id}`}
                      onClick={onClose}
                      className="w-full flex items-center justify-center gap-2 py-2.5 px-3 rounded-lg bg-indigo-600 hover:bg-indigo-700 text-white text-xs font-bold transition-colors"
                    >
                      <span>Abrir ficha del lead</span>
                      <ExternalLink size={13} />
                    </Link>
                  )}
                </div>
              ) : !isFinal ? (
                <div className="space-y-2">
                  <ActionRow
                    icon={CheckCircle2}
                    label="Completada"
                    color="#10b981"
                    onClick={completar}
                    disabled={busy}
                  />
                  <ActionRow
                    icon={Calendar}
                    label="Reprogramar"
                    color="#3b82f6"
                    onClick={() => setShowReprogramar(true)}
                    disabled={busy}
                  />
                  <ActionRow
                    icon={UserX}
                    label="No asistió"
                    color="#f59e0b"
                    onClick={() => setEstado('no_asistio')}
                    disabled={busy}
                  />
                  {/* Cancelar — confirmacion inline */}
                  {showCancelConfirm ? (
                    <div className="mt-2 border border-rose-200 dark:border-rose-900/60 bg-rose-50 dark:bg-rose-950/30 rounded-md p-2.5">
                      <p className="text-xs text-rose-900 dark:text-rose-300 mb-2">
                        ¿Cancelar esta cita? Se preserva en el historial del lead.
                      </p>
                      <div className="flex gap-2">
                        <button
                          onClick={() => setShowCancelConfirm(false)}
                          disabled={busy}
                          className="flex-1 px-2 py-1 text-xs font-medium border border-gray-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-800 hover:bg-gray-50 dark:hover:bg-slate-700 text-gray-600 dark:text-slate-300"
                        >
                          No
                        </button>
                        <button
                          onClick={() => { setShowCancelConfirm(false); setEstado('cancelada') }}
                          disabled={busy}
                          className="flex-1 px-2 py-1 text-xs font-bold rounded-md bg-rose-600 text-white hover:bg-rose-700"
                        >
                          Sí, cancelar cita
                        </button>
                      </div>
                    </div>
                  ) : (
                    <button
                      onClick={() => setShowCancelConfirm(true)}
                      disabled={busy}
                      className="w-full text-center py-2 mt-2 text-xs font-semibold text-rose-600 dark:text-rose-400 hover:text-rose-700 dark:hover:text-rose-300 hover:bg-rose-50 dark:hover:bg-rose-950/30 rounded-md transition-colors disabled:opacity-50 cursor-pointer"
                    >
                      Cancelar cita
                    </button>
                  )}
                </div>
              ) : (
                <div className="space-y-2">
                  {/* Estado final: Reabrir + Reprogramar */}
                  <ActionRow
                    icon={RotateCcw}
                    label="Reabrir"
                    color="#6366f1"
                    onClick={() => setEstado('pendiente', { close: false })}
                    disabled={busy}
                  />
                  <ActionRow
                    icon={Calendar}
                    label="Reprogramar"
                    color="#3b82f6"
                    onClick={() => setShowReprogramar(true)}
                    disabled={busy}
                  />
                </div>
              )}
            </div>
          )}
        </div>

        {/* Loader overlay */}
        {busy && (
          <div className="absolute inset-0 bg-white/60 dark:bg-black/60 flex items-center justify-center z-10">
            <Loader2 size={32} className="text-indigo-600 animate-spin" />
          </div>
        )}
      </div>

      <CambioEstadoModal
        open={cambioEstadoModal.open}
        onClose={() => setCambioEstadoModal({ open: false, targetEstado: null })}
        lead={{
          id: cita?.lead_id,
          nombre_completo: cita?.lead_nombre,
          telefono: cita?.lead_telefono,
          estado_id: cita?.lead_estado_id,
        }}
        targetEstado={cambioEstadoModal.targetEstado}
        onConfirm={async (payload) => {
          await changeLeadEstado(payload)
        }}
        users={allUsersList}
      />
    </>
  )
}

function ActionRow({ icon: Icon, label, color, onClick, disabled }) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="w-full flex items-center gap-3 px-3 py-2.5 rounded-lg border transition-all hover:brightness-95 dark:hover:brightness-110 disabled:opacity-40 disabled:cursor-not-allowed cursor-pointer"
      style={{
        backgroundColor: color + '15',
        borderColor:     color + '40',
      }}
    >
      <Icon size={20} style={{ color }} />
      <span className="text-sm font-semibold text-gray-800 dark:text-slate-200">{label}</span>
    </button>
  )
}
