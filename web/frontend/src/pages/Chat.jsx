import { useState, useEffect, useLayoutEffect, useRef, useCallback, useMemo } from 'react'
import { useSearchParams, useLocation, useNavigate } from 'react-router-dom'
import {
  MessageCircle, Send, Search, Megaphone, RefreshCw, Check, CheckCheck,
  Sparkles, AlertCircle, Archive, Clock, Flame, Wand2, UserCheck, Layers,
  FilePlus, X, Tag, Plus, ChevronDown, Filter, Star,
  Image as ImageIcon, Mic, Video as VideoIcon, FileText, MapPin, Smile,
  ShieldAlert, Phone, MoreVertical, Info, Link2, ExternalLink,
} from 'lucide-react'
import api from '@/lib/api'
import useAuthStore from '@/store/authStore'
import useBrandStore from '@/store/brandStore'
import LoadingSpinner from '@/components/shared/LoadingSpinner'
import ConfirmDialog from '@/components/shared/ConfirmDialog'
import { Dialog, DialogHeader, DialogContent } from '@/components/ui/dialog'

/**
 * POC WhatsApp Business — UI minimal estilo WhatsApp Web.
 *
 * Dos paneles:
 *   [sidebar] lista de conversaciones (polling 5s)
 *   [main]    mensajes del chat activo + input para enviar texto
 *
 * Scope:
 *   - Recibir mensajes (via webhook -> BD)
 *   - Enviar texto dentro de ventana 24h
 *   - Enviar plantillas aprobadas fuera de ventana 24h (modal selector + variables)
 *   - Mostrar banner de atribucion de campaña si el lead llego por CTWA
 *   - Filtro basico por campaña
 *
 * Fuera de scope (proximas iteraciones):
 *   - Multimedia (imagenes, audio, doc)
 *   - Mensajes interactivos (botones, listas)
 *   - WebSocket (ahora polling)
 */

/** Formato relativo para la lista de chats: hoy → HH:MM, ayer → "ayer",
 *  >2 dias → "dd/MM" (o "dd/MM/yy" si ya es otro año). Estilo WhatsApp Web. */
function formatChatListTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''

  // dayDiff sobre inicios de dia → robusto contra horas (no cuenta "23h atras"
  // como "1 dia" si cae en el mismo dia calendario).
  const startOf = (date) => {
    const x = new Date(date)
    x.setHours(0, 0, 0, 0)
    return x
  }
  const dayDiff = Math.round(
    (startOf(new Date()) - startOf(d)) / (1000 * 60 * 60 * 24),
  )

  // Hoy → hora HH:MM (estilo WhatsApp Web)
  if (dayDiff === 0) {
    return d.toLocaleTimeString('es-PE', {
      hour: '2-digit', minute: '2-digit', hour12: false,
    })
  }
  if (dayDiff === 1) return 'Ayer'

  // 2 a 6 dias atras → nombre del dia de la semana capitalizado
  // ("Sábado", "Viernes"...). Cap a 6 para evitar ambiguedad: a 7 dias el
  // mismo nombre se repetiria (lunes hoy vs lunes hace 7) y el usuario
  // necesita la fecha exacta para distinguir.
  if (dayDiff >= 2 && dayDiff <= 6) {
    const day = d.toLocaleDateString('es-PE', { weekday: 'long' })
    return day.charAt(0).toUpperCase() + day.slice(1)
  }

  // 7+ dias → fecha completa dd/mm/yyyy (estilo WhatsApp Web)
  return d.toLocaleDateString('es-PE', {
    day: '2-digit', month: '2-digit', year: 'numeric',
  })
}

/** Etiqueta de separador de dia en la conversacion: "HOY" / "AYER" / "23 abr 2026". */
function formatMessageDay(iso) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const now = new Date()
  const sameDay = d.toDateString() === now.toDateString()
  if (sameDay) return 'HOY'
  const yest = new Date(now); yest.setDate(now.getDate() - 1)
  if (d.toDateString() === yest.toDateString()) return 'AYER'
  return d.toLocaleDateString('es-PE', {
    day: '2-digit', month: 'short', year: 'numeric',
  }).toUpperCase()
}

/** Icono de estado tipo WhatsApp: ✓ enviado, ✓✓ gris entregado, ✓✓ azul leido.
 *  Cuando status='failed', muestra ! rojo con tooltip que detalla el motivo
 *  exacto que devolvio Meta (errorCode + errorDetail), para que el asesor
 *  diagnostique sin abrir BD ni logs. */
function MessageStatus({ status, errorCode, errorDetail }) {
  if (status === 'read')      return <CheckCheck size={12} className="text-sky-500" aria-label="leido" />
  if (status === 'delivered') return <CheckCheck size={12} className="text-gray-400" aria-label="entregado" />
  if (status === 'sent')      return <Check      size={12} className="text-gray-400" aria-label="enviado" />
  if (status === 'failed') {
    const tooltipParts = []
    if (errorCode) tooltipParts.push(`Codigo Meta: ${errorCode}`)
    if (errorDetail) tooltipParts.push(errorDetail)
    if (!tooltipParts.length) tooltipParts.push('Meta marco el envio como fallido pero no envio detalle del motivo. Posibles causas: numero sin WhatsApp activo, plantilla pausada por calidad, o webhook de status no recibido.')
    const tooltip = tooltipParts.join(' — ')
    return (
      <span
        className="text-red-500 text-[11px] font-bold cursor-help"
        title={tooltip}
        aria-label={`fallo: ${tooltip}`}
      >
        !
      </span>
    )
  }
  return <Check size={12} className="text-gray-300" aria-label="pendiente" />
}

/**
 * Render visual de mensajes multimedia (image/audio/video/document/location/sticker).
 * Fase 2: el binario se descarga via proxy /api/whatsapp/media/:id que
 * consulta Meta Graph API y cachea en PG. El hook convierte la respuesta
 * blob en object URL para que <img>, <audio>, <video> puedan renderizarla.
 */
const MEDIA_META = {
  image:    { Icon: ImageIcon,  label: 'Imagen',        bg: 'bg-blue-50',   fg: 'text-blue-600'   },
  sticker:  { Icon: Smile,      label: 'Sticker',       bg: 'bg-pink-50',   fg: 'text-pink-600'   },
  audio:    { Icon: Mic,        label: 'Nota de voz',   bg: 'bg-violet-50', fg: 'text-violet-600' },
  video:    { Icon: VideoIcon,  label: 'Video',         bg: 'bg-orange-50', fg: 'text-orange-600' },
  document: { Icon: FileText,   label: 'Documento',     bg: 'bg-slate-100', fg: 'text-slate-600'  },
  location: { Icon: MapPin,     label: 'Ubicación',     bg: 'bg-emerald-50',fg: 'text-emerald-600'},
}

/**
 * Hook: descarga el binario de un mensaje WA via /api/whatsapp/media/:id y
 * retorna un object URL que se puede usar en <img>, <audio>, <video>.
 * Se revoca automaticamente al desmontar para liberar memoria.
 */
function useWaMediaBlob(messageId, enabled = true) {
  const [url, setUrl] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!enabled || !messageId) return
    let cancelled = false
    let objectUrl = null
    setLoading(true)
    setError(null)
    api.get(`/api/whatsapp/media/${messageId}`, { responseType: 'blob' })
      .then(res => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(res.data)
        setUrl(objectUrl)
      })
      .catch(err => {
        if (cancelled) return
        setError(err.response?.data?.detail || err.message || 'Error al cargar media')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [messageId, enabled])

  return { url, loading, error }
}

/**
 * Hook: descarga el thumbnail cacheado del creative de un ad Meta.
 * Similar a useWaMediaBlob pero apunta a /api/whatsapp/campaigns/:id/creative-thumbnail
 * y solo dispara si `ready` (la conv indica que el backend tiene cache).
 */
function useCampaignThumbnailBlob(campaignId, ready) {
  const [url, setUrl] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (!ready || !campaignId) {
      setUrl(null)
      return
    }
    let cancelled = false
    let objectUrl = null
    setLoading(true)
    setError(null)
    api.get(`/api/whatsapp/campaigns/${campaignId}/creative-thumbnail`, { responseType: 'blob' })
      .then(res => {
        if (cancelled) return
        objectUrl = URL.createObjectURL(res.data)
        setUrl(objectUrl)
      })
      .catch(err => {
        if (cancelled) return
        setError(err.response?.data?.detail || err.message || 'Sin preview')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [campaignId, ready])

  return { url, loading, error }
}

/** Placeholder compacto para tipos sin renderer específico o cuando hay error. */
function MediaPlaceholder({ msg_type, filename, mimeType, error }) {
  const meta = MEDIA_META[msg_type] || { Icon: FileText, label: msg_type, bg: 'bg-gray-50', fg: 'text-gray-600' }
  const { Icon, label, bg, fg } = meta
  return (
    <div className={`flex items-center gap-2.5 px-2.5 py-2 rounded-md ${bg} border border-gray-200/70`}>
      <div className={`w-9 h-9 rounded-md bg-white flex items-center justify-center shrink-0 ${fg}`}>
        <Icon size={18} />
      </div>
      <div className="min-w-0 flex-1">
        <p className={`text-xs font-semibold ${fg}`}>{label}</p>
        <p className="text-[11px] text-gray-500 truncate" title={filename || mimeType || error || ''}>
          {error ? `Error: ${error}` : (filename || mimeType || 'Archivo de WhatsApp')}
        </p>
      </div>
    </div>
  )
}

function PhishingBadge({ flags }) {
  const [open, setOpen] = useState(false)
  if (!flags || !flags.is_phishing) return null

  const level = flags.level || 'low'
  const styles = {
    high:   { wrap: 'bg-red-50 border-red-300 text-red-800',       icon: 'text-red-600' },
    medium: { wrap: 'bg-amber-50 border-amber-300 text-amber-800', icon: 'text-amber-600' },
    low:    { wrap: 'bg-gray-50 border-gray-300 text-gray-700',    icon: 'text-gray-500' },
  }[level] || { wrap: 'bg-gray-50 border-gray-300 text-gray-700', icon: 'text-gray-500' }

  const label = level === 'high' ? 'Posible estafa' : level === 'medium' ? 'Sospechoso' : 'Revisar'
  const reasons = Array.isArray(flags.reasons) ? flags.reasons : []
  const llmReason = flags.llm?.reason

  return (
    <div className={`mb-1.5 rounded-md border ${styles.wrap}`}>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-1.5 px-2 py-1 text-[11px] font-semibold"
      >
        <ShieldAlert className={`w-3.5 h-3.5 ${styles.icon}`} />
        <span>{label}</span>
        <span className="text-[10px] opacity-70 ml-auto">
          {open ? 'ocultar' : `ver detalle`}
        </span>
      </button>
      {open && (
        <div className="px-2 pb-2 text-[11px] space-y-1 border-t border-current/10">
          {llmReason && (
            <p className="pt-1.5"><span className="font-semibold">IA:</span> {llmReason}</p>
          )}
          {reasons.length > 0 && (
            <ul className="list-disc list-inside space-y-0.5">
              {reasons.map((r, i) => <li key={i}>{r}</li>)}
            </ul>
          )}
          {flags.urls && flags.urls.length > 0 && (
            <div className="pt-1">
              <span className="font-semibold">URLs:</span>
              <ul className="list-disc list-inside">
                {flags.urls.map((u, i) => (
                  <li key={i} className="break-all">{u}</li>
                ))}
              </ul>
            </div>
          )}
          <p className="text-[10px] opacity-60 pt-1">
            Motor: {flags.engine} · Score {flags.score}/100
          </p>
        </div>
      )}
    </div>
  )
}

/**
 * Tarjeta compacta estilo WhatsApp que renderiza la atribucion CTWA
 * (Click-to-WhatsApp) encima del primer mensaje que el cliente envio
 * tras hacer clic en el anuncio. Meta solo adjunta `referral` al PRIMER
 * mensaje del CTWA click, asi que este componente se renderiza 0..N
 * veces por conversacion (N = cantidad de clicks distintos del cliente
 * al mismo o distintos ads).
 *
 * Fuente de datos:
 *   - headline / body / source_url vienen del propio referral del mensaje
 *   - thumbnailUrl se comparte a nivel de conversacion (todas las cards
 *     muestran el creative del ad al que mapea la wa_campaign de la conv)
 */
function CTWAReferralCard({ referral, thumbnailUrl, mediaType }) {
  if (!referral) return null
  const headline   = (referral.headline || '').trim()
  const body       = (referral.body || '').trim()
  const sourceUrl  = (referral.source_url || '').trim()
  let sourceHost = null
  if (sourceUrl) {
    try { sourceHost = new URL(sourceUrl).hostname.replace(/^www\./, '') }
    catch { sourceHost = null }
  }
  const displayBody = body.length > 140 ? `${body.slice(0, 140)}…` : body

  return (
    <div className="mb-1.5 -mx-1 overflow-hidden rounded-md bg-gray-50/90 border-l-[3px] border-indigo-400">
      {thumbnailUrl && (
        <div className="relative">
          <img
            src={thumbnailUrl}
            alt=""
            className="w-full h-28 object-cover"
          />
          {mediaType === 'video' && (
            <span className="absolute inset-0 flex items-center justify-center">
              <span className="w-8 h-8 rounded-full bg-black/55 flex items-center justify-center">
                <VideoIcon size={14} className="text-white" />
              </span>
            </span>
          )}
        </div>
      )}
      <div className="px-2 py-1.5 space-y-0.5">
        <p className="text-[11px] font-semibold text-indigo-700 flex items-center gap-1">
          <Megaphone size={10} /> Anuncio
        </p>
        {headline && (
          <p className="text-[12.5px] font-semibold text-gray-800 leading-tight">
            {headline}
          </p>
        )}
        {displayBody && (
          <p className="text-[11.5px] text-gray-600 leading-snug">
            {displayBody}
          </p>
        )}
        {sourceHost && (
          <p className="text-[10.5px] text-gray-500 pt-0.5">
            {sourceHost}
          </p>
        )}
      </div>
    </div>
  )
}

function MediaBubble({ msg }) {
  const { id, msg_type, content, payload } = msg
  const data  = payload?.[msg_type] || {}
  const defaultPlaceholder = `[${msg_type}]`
  const caption = data.caption || (content && content !== defaultPlaceholder ? content : null)
  const filename = data.filename
  const mimeType = data.mime_type

  const autoFetchTypes = ['image', 'sticker', 'audio', 'video']
  const shouldFetch = autoFetchTypes.includes(msg_type)
  const { url, loading, error } = useWaMediaBlob(id, shouldFetch)

  // Texto / interactivo / tipo desconocido: fallback al contenido plano
  if (!MEDIA_META[msg_type]) {
    return <p className="whitespace-pre-wrap break-words">{content || defaultPlaceholder}</p>
  }

  // Imagen / sticker: render <img> real
  if (msg_type === 'image' || msg_type === 'sticker') {
    const maxW = msg_type === 'sticker' ? 'max-w-[140px]' : 'max-w-[280px]'
    return (
      <div>
        {loading && (
          <div className={`${maxW} h-48 bg-gray-100 animate-pulse rounded-md flex items-center justify-center`}>
            <ImageIcon size={28} className="text-gray-300" />
          </div>
        )}
        {error && <MediaPlaceholder msg_type={msg_type} error={error} />}
        {url && (
          <a href={url} target="_blank" rel="noopener noreferrer" className="block">
            <img
              src={url}
              alt={caption || 'imagen'}
              loading="lazy"
              onLoad={() => window.dispatchEvent(new CustomEvent('chat:media-loaded'))}
              className={`${maxW} rounded-md object-cover hover:opacity-95 transition-opacity cursor-zoom-in`}
            />
          </a>
        )}
        {caption && <p className="whitespace-pre-wrap break-words mt-1.5 text-sm">{caption}</p>}
      </div>
    )
  }

  // Audio: <audio> nativo con controles
  if (msg_type === 'audio') {
    return (
      <div className="min-w-[220px]">
        {loading && <div className="h-10 w-56 bg-gray-100 animate-pulse rounded" />}
        {error && <MediaPlaceholder msg_type="audio" error={error} />}
        {url && <audio controls src={url} className="max-w-[280px]" />}
      </div>
    )
  }

  // Video: <video> con controles
  if (msg_type === 'video') {
    return (
      <div>
        {loading && (
          <div className="max-w-[320px] h-52 bg-gray-100 animate-pulse rounded-md flex items-center justify-center">
            <VideoIcon size={32} className="text-gray-300" />
          </div>
        )}
        {error && <MediaPlaceholder msg_type="video" error={error} />}
        {url && <video controls src={url} className="max-w-[320px] rounded-md" preload="metadata" />}
        {caption && <p className="whitespace-pre-wrap break-words mt-1.5 text-sm">{caption}</p>}
      </div>
    )
  }

  // Documento: boton de descarga (fetch bajo demanda)
  if (msg_type === 'document') {
    return (
      <DocumentBubble msg={msg} filename={filename} mimeType={mimeType} caption={caption} />
    )
  }

  // Ubicacion u otros: placeholder informativo
  return (
    <div>
      <MediaPlaceholder msg_type={msg_type} filename={filename} mimeType={mimeType} />
      {caption && <p className="whitespace-pre-wrap break-words mt-1.5 text-sm">{caption}</p>}
    </div>
  )
}

/** Documento: no autoload. Click → descarga/abre en tab nueva. */
function DocumentBubble({ msg, filename, mimeType, caption }) {
  const [clicked, setClicked] = useState(false)
  const { url, loading, error } = useWaMediaBlob(msg.id, clicked)

  useEffect(() => {
    if (url && filename) {
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
    } else if (url) {
      window.open(url, '_blank', 'noopener,noreferrer')
    }
  }, [url, filename])

  return (
    <div>
      <button
        onClick={() => setClicked(true)}
        disabled={loading}
        className="flex items-center gap-2.5 px-2.5 py-2 rounded-md bg-slate-100 border border-gray-200/70 hover:bg-slate-200 transition-colors w-full text-left"
      >
        <div className="w-9 h-9 rounded-md bg-white flex items-center justify-center shrink-0 text-slate-600">
          <FileText size={18} />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold text-slate-600">
            {loading ? 'Descargando…' : error ? 'Error al descargar' : 'Documento'}
          </p>
          <p className="text-[11px] text-gray-500 truncate" title={filename || mimeType || ''}>
            {filename || mimeType || 'Click para descargar'}
          </p>
        </div>
      </button>
      {caption && <p className="whitespace-pre-wrap break-words mt-1.5 text-sm">{caption}</p>}
    </div>
  )
}

/**
 * Thumbnail con lazy-load via IntersectionObserver. Solo dispara la descarga
 * del blob cuando el elemento entra al viewport. Evita saturar el backend
 * cuando se abre el panel en un chat con decenas o cientos de medios.
 */
function LazyMediaThumb({ msg, onClick }) {
  const [visible, setVisible] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!ref.current || visible) return
    const io = new IntersectionObserver(
      entries => entries.forEach(e => { if (e.isIntersecting) setVisible(true) }),
      { rootMargin: '200px' },
    )
    io.observe(ref.current)
    return () => io.disconnect()
  }, [visible])

  const isImage = msg.msg_type === 'image' || msg.msg_type === 'sticker'
  return (
    <button
      ref={ref}
      type="button"
      onClick={onClick}
      className="relative aspect-square bg-gray-100 rounded-md overflow-hidden hover:ring-2 hover:ring-green-500 focus:ring-2 focus:ring-green-500 focus:outline-none transition"
      title={msg.payload?.[msg.msg_type]?.caption || msg.msg_type}
    >
      {visible
        ? <MediaThumbInner msg={msg} isImage={isImage} />
        : <div className="w-full h-full animate-pulse bg-gray-100" />}
    </button>
  )
}

function MediaThumbInner({ msg, isImage }) {
  const { url, loading, error } = useWaMediaBlob(msg.id, true)
  if (loading) return <div className="w-full h-full animate-pulse bg-gray-100" />
  if (error || !url) {
    const meta = MEDIA_META[msg.msg_type]
    const Icon = meta?.Icon || FileText
    return (
      <div className="w-full h-full flex items-center justify-center text-gray-400">
        <Icon size={24} />
      </div>
    )
  }
  if (isImage) {
    return <img src={url} alt="" loading="lazy" className="w-full h-full object-cover" />
  }
  if (msg.msg_type === 'video') {
    return (
      <div className="relative w-full h-full">
        <video src={url} className="w-full h-full object-cover" preload="metadata" muted />
        <div className="absolute inset-0 flex items-center justify-center bg-black/20">
          <VideoIcon size={24} className="text-white drop-shadow" />
        </div>
      </div>
    )
  }
  return (
    <div className="w-full h-full flex items-center justify-center text-gray-400">
      <FileText size={24} />
    </div>
  )
}

/**
 * Valida que una URL sea http/https antes de usarla como href.
 * Defensa en profundidad contra XSS tipo javascript:alert(1) aunque el
 * backend ya aplica una whitelist con regex.
 */
function safeHref(url) {
  if (typeof url !== 'string') return null
  try {
    const u = new URL(url)
    if (u.protocol === 'http:' || u.protocol === 'https:') return u.toString()
  } catch { /* malformada */ }
  return null
}

/**
 * Panel lateral "Info del contacto" estilo WhatsApp Web.
 *
 * Tres tabs:
 *   - Archivos: grid de thumbnails (image/sticker/video) + lista
 *               de documents y audios. Lazy-load con IntersectionObserver.
 *   - Enlaces:  URLs extraidas de mensajes de texto con contexto.
 *               Todos los enlaces abren en nueva pestaña con rel
 *               noopener/noreferrer/nofollow.
 *   - Info:     metadata del lead (telefono, campaña, etiquetas).
 *
 * Seguridad:
 *   - safeHref() valida esquema http/https antes de renderizar <a>.
 *   - Todo el contenido del usuario se inserta como texto — React escapa
 *     por defecto, no usamos dangerouslySetInnerHTML en ningun punto.
 *   - El backend aplica _assert_conv_visible para evitar IDOR.
 */
function ContactInfoPanel({ conv, onClose, leadTags, waNumbers, initialTab = 'files' }) {
  const [tab, setTab] = useState(initialTab)
  const [query, setQuery] = useState('')
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [thumbLightbox, setThumbLightbox] = useState(false)

  // V037: thumbnail del creative del ad. Solo descarga si el backend ya
  // cacheo el binario (meta_creative_thumbnail_ready) — evita el 404 ruidoso
  // en campanas donde Graph no expuso media o aun no se enriquecio.
  const thumb = useCampaignThumbnailBlob(
    conv?.wa_campaign_id,
    Boolean(conv?.meta_creative_thumbnail_ready),
  )

  useEffect(() => {
    if (!conv?.id) return
    let cancelled = false
    setLoading(true)
    setError(null)
    api.get(`/api/whatsapp/conversations/${conv.id}/attachments`)
      .then(r => { if (!cancelled) setData(r.data) })
      .catch(err => { if (!cancelled) setError(err.response?.data?.detail || 'No se pudo cargar') })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [conv?.id])

  // Cerrar con Esc — accesibilidad estandar para drawers.
  useEffect(() => {
    const onKey = e => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const q = query.trim().toLowerCase()
  const mediaList = data?.media
  const linksList = data?.links
  const filteredMedia = useMemo(() => {
    if (!mediaList) return []
    if (!q) return mediaList
    return mediaList.filter(m => {
      const cap = (m.payload?.[m.msg_type]?.caption || '').toLowerCase()
      const fn  = (m.payload?.[m.msg_type]?.filename || '').toLowerCase()
      const content = (m.content || '').toLowerCase()
      return cap.includes(q) || fn.includes(q) || content.includes(q) || m.msg_type.includes(q)
    })
  }, [mediaList, q])

  const filteredLinks = useMemo(() => {
    if (!linksList) return []
    if (!q) return linksList
    return linksList.filter(l =>
      l.url.toLowerCase().includes(q) ||
      (l.context || '').toLowerCase().includes(q),
    )
  }, [linksList, q])

  // Separa media en visuales (imagen/video/sticker) vs no-visuales (audio/doc).
  const visualMedia  = filteredMedia.filter(m => ['image', 'sticker', 'video'].includes(m.msg_type))
  const fileMedia    = filteredMedia.filter(m => ['document', 'audio'].includes(m.msg_type))

  const displayName = conv.contact_name || conv.lead_name || conv.wa_phone

  return (
    <aside
      role="complementary"
      aria-label="Información del contacto"
      className="w-[340px] border-l border-gray-200 bg-white flex flex-col shrink-0 animate-in slide-in-from-right duration-200"
    >
      <header className="px-4 py-3 border-b border-gray-200 flex items-center gap-3">
        <button
          onClick={onClose}
          className="text-gray-500 hover:text-gray-800 p-1 -ml-1 rounded"
          title="Cerrar (Esc)"
          aria-label="Cerrar panel"
        >
          <X size={20} />
        </button>
        <h3 className="text-base font-semibold text-gray-800 flex-1">Info del contacto</h3>
      </header>

      <div className="px-4 py-4 border-b border-gray-200 flex items-center gap-3">
        <div className="w-14 h-14 rounded-full bg-gradient-to-br from-green-400 to-emerald-600 text-white flex items-center justify-center font-semibold text-lg shadow-sm shrink-0">
          {displayName[0].toUpperCase()}
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-[15px] font-semibold text-gray-900 truncate">{displayName}</p>
          <p className="text-[13px] text-gray-500">+{conv.wa_phone}</p>
        </div>
      </div>

      <div className="flex border-b border-gray-200">
        {[
          { key: 'files', label: 'Archivos', count: data?.counts?.media },
          { key: 'links', label: 'Enlaces',  count: data?.counts?.links },
          { key: 'info',  label: 'Info' },
        ].map(t => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`flex-1 py-2.5 text-[13px] font-medium border-b-2 transition-colors ${
              tab === t.key
                ? 'border-green-600 text-green-700'
                : 'border-transparent text-gray-500 hover:text-gray-700'
            }`}
          >
            {t.label}{t.count != null && t.count > 0 ? ` (${t.count})` : ''}
          </button>
        ))}
      </div>

      {(tab === 'files' || tab === 'links') && (
        <div className="px-4 py-2 border-b border-gray-100">
          <div className="relative">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder={tab === 'files' ? 'Buscar archivo...' : 'Buscar enlace...'}
              className="w-full h-8 pl-8 pr-2 rounded-md border border-gray-200 bg-gray-50 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 focus:bg-white transition-colors"
            />
          </div>
        </div>
      )}

      <div className="flex-1 overflow-y-auto wa-scrollbar">
        {loading && <div className="py-8"><LoadingSpinner /></div>}
        {error && (
          <div className="m-4 p-3 text-sm text-red-600 bg-red-50 border border-red-200 rounded">
            {error}
          </div>
        )}

        {!loading && !error && tab === 'files' && (
          <div className="p-4 space-y-4">
            {visualMedia.length === 0 && fileMedia.length === 0 && (
              <p className="text-sm text-gray-400 text-center py-6">
                {q ? 'Sin resultados.' : 'Sin archivos en este chat.'}
              </p>
            )}
            {visualMedia.length > 0 && (
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-2">
                  Imagenes y videos
                </p>
                <div className="grid grid-cols-3 gap-1.5">
                  {visualMedia.map(m => (
                    <LazyMediaThumb
                      key={m.id}
                      msg={m}
                      onClick={() => {
                        // Reuso del endpoint — al hacer click el navegador
                        // pedira el blob y lo abrira en una nueva pestaña.
                        api.get(`/api/whatsapp/media/${m.id}`, { responseType: 'blob' })
                          .then(res => {
                            const url = URL.createObjectURL(res.data)
                            window.open(url, '_blank', 'noopener,noreferrer')
                            // Revocar al cerrar la pestaña es cosa del GC del browser;
                            // dejar expirar es aceptable para este caso.
                          })
                      }}
                    />
                  ))}
                </div>
              </div>
            )}
            {fileMedia.length > 0 && (
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-2">
                  Documentos y audios
                </p>
                <ul className="space-y-1.5">
                  {fileMedia.map(m => {
                    const meta = MEDIA_META[m.msg_type]
                    const Icon = meta?.Icon || FileText
                    const filename = m.payload?.[m.msg_type]?.filename || meta?.label || m.msg_type
                    const mime = m.payload?.[m.msg_type]?.mime_type
                    return (
                      <li key={m.id}>
                        <button
                          type="button"
                          onClick={() => {
                            api.get(`/api/whatsapp/media/${m.id}`, { responseType: 'blob' })
                              .then(res => {
                                const url = URL.createObjectURL(res.data)
                                const a = document.createElement('a')
                                a.href = url
                                a.download = filename
                                a.click()
                              })
                          }}
                          className="w-full flex items-center gap-2.5 px-2.5 py-2 rounded-md border border-gray-200 hover:bg-gray-50 text-left transition-colors"
                        >
                          <div className={`w-9 h-9 rounded-md ${meta?.bg || 'bg-slate-100'} ${meta?.fg || 'text-slate-600'} flex items-center justify-center shrink-0`}>
                            <Icon size={18} />
                          </div>
                          <div className="min-w-0 flex-1">
                            <p className="text-xs font-medium text-gray-800 truncate">{filename}</p>
                            <p className="text-[11px] text-gray-500 truncate">{mime || meta?.label}</p>
                          </div>
                        </button>
                      </li>
                    )
                  })}
                </ul>
              </div>
            )}
          </div>
        )}

        {!loading && !error && tab === 'links' && (
          <div className="p-4">
            {filteredLinks.length === 0 ? (
              <p className="text-sm text-gray-400 text-center py-6">
                {q ? 'Sin resultados.' : 'Sin enlaces en este chat.'}
              </p>
            ) : (
              <ul className="space-y-2">
                {filteredLinks.map((l, idx) => {
                  const href = safeHref(l.url)
                  let domain = l.url
                  try { domain = new URL(l.url).hostname.replace(/^www\./, '') } catch { /* noop */ }
                  if (!href) return null
                  return (
                    <li key={`${l.message_id}-${idx}`} className="border border-gray-200 rounded-md p-2.5 hover:bg-gray-50 transition-colors">
                      <a
                        href={href}
                        target="_blank"
                        rel="noopener noreferrer nofollow"
                        className="flex items-start gap-2 text-sm"
                      >
                        <Link2 size={14} className="text-green-600 shrink-0 mt-0.5" />
                        <div className="min-w-0 flex-1">
                          <p className="text-blue-700 hover:underline font-medium truncate">{domain}</p>
                          <p className="text-[11px] text-gray-500 truncate">{l.url}</p>
                        </div>
                        <ExternalLink size={12} className="text-gray-400 shrink-0 mt-0.5" />
                      </a>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>
        )}

        {!loading && !error && tab === 'info' && (
          <dl className="p-4 space-y-3 text-sm">
            <div>
              <dt className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Telefono</dt>
              <dd className="text-gray-800">+{conv.wa_phone}</dd>
            </div>
            {conv.lead_name && (
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Lead</dt>
                <dd className="text-gray-800">{conv.lead_name}</dd>
              </div>
            )}
            {(conv.meta_ad_name ||
              conv.meta_campaign_name ||
              conv.meta_creative_body ||
              conv.wa_campaign_headline ||
              conv.campaign_name) && (() => {
              const adName =
                conv.meta_ad_name ||
                conv.wa_campaign_headline ||
                conv.campaign_name
              const campaignName =
                conv.meta_campaign_name || conv.campaign_name
              const adsetName = conv.meta_adset_name
              const creativeBody = conv.meta_creative_body
              const showCampaign = campaignName && campaignName !== adName
              // Misma heuristica que el banner original: si Graph solo devolvio
              // ad.name (sin adset/campaign/creative), lo mas probable es que
              // sea un boosted post de la fan page y "name" sea el cuerpo del
              // post, no un nombre operativo.
              const isBoostedPost =
                !!conv.meta_ad_name &&
                !conv.meta_adset_name &&
                !conv.meta_campaign_name &&
                !conv.meta_creative_body
              const promoCopy = isBoostedPost ? conv.meta_ad_name : null
              return (
                <div>
                  <dt className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 flex items-center gap-1.5">
                    <Megaphone size={11} className="text-indigo-600" />
                    {isBoostedPost ? 'Promocion de pagina' : 'Anuncio'}
                  </dt>
                  <dd className="text-[13px] text-gray-800 space-y-0.5 mt-1">
                    {/* V037: thumbnail del creative. Solo se renderiza si el
                        backend tiene el binario cacheado. El tipo (video/image/
                        post/thumbnail) se muestra como chip encima. */}
                    {conv.meta_creative_thumbnail_ready && (
                      <div className="mb-2">
                        {thumb.url ? (
                          <button
                            type="button"
                            onClick={() => setThumbLightbox(true)}
                            className="group relative block w-full overflow-hidden rounded-md border border-gray-200 bg-gray-50 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                            aria-label="Ampliar creative del ad"
                          >
                            <img
                              src={thumb.url}
                              alt="Creative del ad"
                              className="w-full h-40 object-cover transition group-hover:scale-[1.02]"
                            />
                            {conv.meta_creative_media_type === 'video' && (
                              <span className="absolute inset-0 flex items-center justify-center">
                                <span className="w-10 h-10 rounded-full bg-black/55 flex items-center justify-center">
                                  <VideoIcon size={18} className="text-white" />
                                </span>
                              </span>
                            )}
                            <span className="absolute top-1.5 left-1.5 text-[10px] font-semibold uppercase tracking-wide bg-black/55 text-white px-1.5 py-0.5 rounded">
                              {conv.meta_creative_media_type === 'video' && 'Video'}
                              {conv.meta_creative_media_type === 'image' && 'Imagen'}
                              {conv.meta_creative_media_type === 'post' && 'Post'}
                              {(conv.meta_creative_media_type === 'thumbnail' || !conv.meta_creative_media_type) && 'Creative'}
                            </span>
                          </button>
                        ) : thumb.loading ? (
                          <div className="w-full h-40 rounded-md bg-gray-100 animate-pulse" />
                        ) : null}
                      </div>
                    )}
                    {isBoostedPost ? (
                      <>
                        <p className="text-[11px] text-gray-500">
                          Boosted post — sin jerarquia de campaña estructurada.
                        </p>
                        <p className="italic text-gray-800 whitespace-pre-line break-words pt-1">
                          {promoCopy.length > 400 ? `${promoCopy.slice(0, 400)}…` : promoCopy}
                        </p>
                      </>
                    ) : (
                      <>
                        <p><span className="text-gray-500">Ad:</span> {adName}</p>
                        {adsetName && (
                          <p><span className="text-gray-500">Conjunto:</span> {adsetName}</p>
                        )}
                        {showCampaign && (
                          <p><span className="text-gray-500">Campaña:</span> {campaignName}</p>
                        )}
                        {creativeBody && (
                          <div className="mt-1.5 pt-1.5 border-t border-gray-100">
                            <p className="text-[11px] text-gray-500 mb-0.5">Copy:</p>
                            <p className="italic text-gray-800 whitespace-pre-line break-words">
                              {creativeBody.length > 400 ? `${creativeBody.slice(0, 400)}…` : creativeBody}
                            </p>
                          </div>
                        )}
                      </>
                    )}
                  </dd>
                </div>
              )
            })()}
            {conv.wa_number_name && waNumbers?.length > 1 && (
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Linea</dt>
                <dd className="text-gray-800 flex items-center gap-1.5">
                  <Phone size={12} className="text-purple-600" />
                  {conv.wa_number_name}
                  {conv.wa_number_phone && <span className="text-gray-400 text-xs">+{conv.wa_number_phone}</span>}
                </dd>
              </div>
            )}
            {leadTags?.length > 0 && (
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wide text-gray-500 mb-1">Etiquetas</dt>
                <dd className="flex flex-wrap gap-1">
                  {leadTags.map(t => (
                    <span
                      key={t.id}
                      className="inline-flex items-center gap-1 text-[11px] px-2 py-0.5 rounded-full border font-medium"
                      style={{
                        backgroundColor: t.color_hex + '22',
                        color: t.color_hex,
                        borderColor: t.color_hex + '55',
                      }}
                    >
                      <Tag size={10} /> {t.nombre}
                    </span>
                  ))}
                </dd>
              </div>
            )}
            {conv.classification_summary && (
              <div>
                <dt className="text-[11px] font-semibold uppercase tracking-wide text-gray-500">Resumen IA</dt>
                <dd className="text-gray-700 text-[13px] whitespace-pre-wrap">{conv.classification_summary}</dd>
              </div>
            )}
          </dl>
        )}
      </div>

      {thumbLightbox && thumb.url && (
        <div
          className="fixed inset-0 bg-black/80 z-[60] flex items-center justify-center p-6"
          onClick={() => setThumbLightbox(false)}
          role="dialog"
          aria-label="Creative del anuncio"
        >
          <button
            type="button"
            onClick={() => setThumbLightbox(false)}
            className="absolute top-4 right-4 text-white/90 hover:text-white p-1 rounded-full bg-black/40"
            aria-label="Cerrar"
          >
            <X size={22} />
          </button>
          <img
            src={thumb.url}
            alt="Creative del ad (ampliado)"
            className="max-h-[85vh] max-w-[90vw] object-contain rounded-md shadow-2xl"
            onClick={e => e.stopPropagation()}
          />
        </div>
      )}
    </aside>
  )
}

// Map de iconos disponibles para chips editables (debe coincidir con
// _ALLOWED_ICONS del backend y CHIP_ICON_OPTIONS de Configuracion.jsx).
const CHIP_ICONS = {
  Sparkles, MessageCircle, AlertCircle, Archive, Flame, Clock, Tag,
  UserCheck, Layers, Wand2, Check, CheckCheck, Send,
}

// Fallback hardcoded — se usa si uiLabels aun no cargo o no encuentra la key.
const CATEGORY_FALLBACK = {
  cliente_potencial: { label: 'Potencial',     color_hex: '#16a34a', icon_name: 'Sparkles' },
  cliente_existente: { label: 'Cliente',       color_hex: '#6366f1', icon_name: 'UserCheck' },
  consulta_general:  { label: 'Consulta',      color_hex: '#0ea5e9', icon_name: 'MessageCircle' },
  spam:              { label: 'Spam',          color_hex: '#6b7280', icon_name: 'Archive' },
  no_relacionado:    { label: 'No relacionado',color_hex: '#6b7280', icon_name: 'Archive' },
  pending:           { label: 'Clasificando',  color_hex: '#64748b', icon_name: 'Clock' },
  manual_review:     { label: 'Revisar',       color_hex: '#f59e0b', icon_name: 'AlertCircle' },
  archived:          { label: 'Archivado',     color_hex: '#6b7280', icon_name: 'Archive' },
  skipped:           { label: 'Cliente',       color_hex: '#6366f1', icon_name: 'Sparkles' },
}

/**
 * Devuelve {label, color_hex, icon_name} para un chat dado, usando los
 * labels configurables (uiLabels) y cayendo al hardcoded si no hay config.
 */
function classifyBadge(c, labelsMap) {
  const status = c.classification_status
  const cat    = c.classification_category

  let key = null
  if (status === 'pending' || status === 'queued') key = 'pending'
  else if (status === 'failed')        return { label: 'Error IA', color_hex: '#dc2626', icon_name: 'AlertCircle' }
  else if (status === 'manual_review') key = 'manual_review'
  else if (status === 'archived')      key = 'archived'
  else if (status === 'skipped')       key = 'skipped'
  else if (status === 'classified')    key = cat

  if (!key) return null
  // labelsMap: Map keyed por `${kind}:${key}`
  const fromCfg = labelsMap?.get(`category:${key}`)
  if (fromCfg && fromCfg.activo) return fromCfg
  return CATEGORY_FALLBACK[key] || null
}

/**
 * ¿El usuario puede tomar este chat?
 *  - admin/supervisor: siempre que no sea ya suyo (con lead)
 *  - asesor: solo si esta sin asignar O ya es suyo pero sin lead todavia
 *  - cualquiera: si ya es suyo Y tiene lead → oculto (no hay nada que hacer)
 *
 * Caso huerfano: la conv ya tiene asesor_id=self pero lead_id=NULL — sucede
 * con conversaciones tomadas antes del fix donde "Tomar" no creaba lead.
 * En ese caso mostramos el boton para que el usuario pueda re-tomar y forzar
 * la creacion del lead. El backend detecta este caso y crea/reusa lead.
 */
function canTakeChat(conv, user) {
  if (!conv || !user) return false
  const myId = user.user_id
  const ownerId = conv.asesor_id
  const hasLead = conv.lead_id != null
  // V070.8 — "Tomar este chat" SOLO en orfanas o cuando soy yo pero falta el
  // lead vinculado. Antes admin/supervisor lo veian sobre cualquier chat
  // ajeno; esto provocaba que un admin abriera el chat de Edwin (asignado a
  // Fabiola) y viera el boton "Tomar" en vez de "Asignado: Fabiola Gamero".
  // Patron CRMs profesionales: el owner se muestra como info; reasignar es
  // un flujo separado (no un boton expuesto). Si el admin de verdad quiere
  // robar, lo hace desde el detalle del lead o Asignacion.
  if (ownerId === myId && !hasLead) return true   // re-tomar para crear lead
  return ownerId == null                          // huerfano: cualquiera lo toma
}

function ClassifyChip({ conv, compact = false, labelsMap }) {
  const b = classifyBadge(conv, labelsMap)
  if (!b) return null
  const Icon = CHIP_ICONS[b.icon_name] || Tag
  const size = compact ? 'text-[9px] px-1.5 py-0.5' : 'text-[10px] px-2 py-0.5'
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border ${size} font-medium whitespace-nowrap`}
      style={{
        backgroundColor: b.color_hex + '22',
        color: b.color_hex,
        borderColor: b.color_hex + '55',
      }}
    >
      <Icon size={compact ? 8 : 10} />
      {b.label}
    </span>
  )
}

/** Toast flotante reutilizable — top-right, slide-in animado, auto-dismiss.
 *  Soporta tipos ok | err | info y un CTA opcional. Sin dependencias externas. */
function Toast({ open, type = 'ok', title, message, action, onClose, durationMs = 5000 }) {
  useEffect(() => {
    if (!open) return
    const t = setTimeout(onClose, durationMs)
    return () => clearTimeout(t)
  }, [open, durationMs, onClose])

  if (!open) return null

  const palette = type === 'err'
    ? { ring: 'border-red-200',     bg: 'bg-red-50',     icon: 'text-red-600',     title: 'text-red-900' }
    : type === 'info'
    ? { ring: 'border-blue-200',    bg: 'bg-blue-50',    icon: 'text-blue-600',    title: 'text-blue-900' }
    : { ring: 'border-emerald-200', bg: 'bg-emerald-50', icon: 'text-emerald-600', title: 'text-emerald-900' }

  return (
    <div
      role="status"
      aria-live="polite"
      className="fixed top-4 right-4 z-[60] max-w-sm animate-in slide-in-from-right-4 fade-in duration-300"
    >
      <div className={`flex gap-3 ${palette.bg} ${palette.ring} border rounded-xl shadow-lg p-3 pr-2`}>
        <div className={`shrink-0 ${palette.icon} pt-0.5`}>
          {type === 'err' ? <AlertCircle size={20} /> : <Check size={20} />}
        </div>
        <div className="min-w-0 flex-1">
          {title && <div className={`text-sm font-semibold ${palette.title}`}>{title}</div>}
          {message && <div className="text-xs text-gray-700 mt-0.5">{message}</div>}
          {action && (
            <button
              onClick={() => { action.onClick(); onClose() }}
              className={`mt-2 inline-flex items-center gap-1 text-xs font-semibold ${palette.icon} hover:underline`}
            >
              {action.label}
              <ExternalLink size={11} />
            </button>
          )}
        </div>
        <button
          onClick={onClose}
          className="shrink-0 text-gray-400 hover:text-gray-600 p-1"
          aria-label="Cerrar"
        >
          <X size={14} />
        </button>
      </div>
    </div>
  )
}

// Fallback: se usa si no hay config en uiLabels. Labels cortos estilo
// mensajería profesional para que los chips entren en 320px de sidebar
// sin truncarse. Coincide con el badge por-chat ("Revisar") para que el
// usuario vea la misma palabra en la lista y en el bucket.
const STATUS_LABELS_FALLBACK = {
  potenciales:     'Potenciales',
  revisar:         'Revisar',
  sin_clasificar:  'Sin clasificar',
  delegar:         'Delegar',
  archivados:      'Archivados',
}

// Override para los chips — preferimos label corto incluso si el admin dejo
// el legacy verbose ("Clientes potenciales", "Requieren revision") en la
// config. El label largo sigue vivo para el screen de Configuracion.
const INBOX_CHIP_LABEL_OVERRIDES = {
  potenciales:     'Potenciales',
  revisar:         'Revisar',
  sin_clasificar:  'Sin clasificar',
  delegar:         'Delegar',
  archivados:      'Archivados',
}

const URGENCY_FALLBACK = {
  alta: { label: 'Urgente', color_hex: '#dc2626', icon_name: 'Flame' },
}

// ── Custom lists (estilo "+ Crear lista" de WhatsApp Web) ─────────────────
// Persistencia en localStorage, scoped por usuario para que dos asesores en
// la misma maquina no se mezclen. Cada lista = { id, name, conversationIds[] }.
// Solo se incluyen conversaciones individuales (no hay grupos en el CRM).
const _CUSTOM_LISTS_STORAGE_KEY = (userId) => `crm.chat.custom_lists.${userId || 'anon'}`

function _readCustomLists(userId) {
  try {
    const raw = localStorage.getItem(_CUSTOM_LISTS_STORAGE_KEY(userId))
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function _writeCustomLists(userId, lists) {
  try {
    localStorage.setItem(_CUSTOM_LISTS_STORAGE_KEY(userId), JSON.stringify(lists))
  } catch {
    // Sin localStorage → silencioso. La feature degrada pero no rompe.
  }
}

// ── Favoritos (chip "Favoritos" estilo WhatsApp Web) ──────────────────────
// Mismo patron que custom lists: persistencia local por usuario. El array de
// IDs vive en Set en memoria y JSON en disco.
const _FAVORITES_STORAGE_KEY = (userId) => `crm.chat.favorites.${userId || 'anon'}`

function _readFavorites(userId) {
  try {
    const raw = localStorage.getItem(_FAVORITES_STORAGE_KEY(userId))
    if (!raw) return new Set()
    const parsed = JSON.parse(raw)
    return new Set(Array.isArray(parsed) ? parsed : [])
  } catch {
    return new Set()
  }
}

function _writeFavorites(userId, favoritesSet) {
  try {
    localStorage.setItem(
      _FAVORITES_STORAGE_KEY(userId),
      JSON.stringify(Array.from(favoritesSet)),
    )
  } catch {
    // Silencioso — sin localStorage la feature no persiste pero no rompe.
  }
}

/** Modal "Anade a Favoritos" — multi-select con preselect de favoritos
 *  actuales. Al guardar, reemplaza el set completo (no es delta). */
function FavoritesDialog({ open, onClose, conversations, currentFavorites, onSave }) {
  const [selectedIds, setSelectedIds] = useState(() => new Set(currentFavorites))
  const [search, setSearch] = useState('')

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return conversations
    return conversations.filter(c =>
      (c.contact_name || '').toLowerCase().includes(q) ||
      (c.lead_name || '').toLowerCase().includes(q) ||
      (c.wa_phone || '').includes(q)
    )
  }, [conversations, search])

  const toggle = (id) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleSave = () => {
    onSave(selectedIds)
    onClose()
  }

  return (
    <Dialog open={open} onClose={onClose} size="md">
      <DialogHeader onClose={onClose}>Anadir a Favoritos</DialogHeader>
      <DialogContent>
        <div className="space-y-3">
          <div className="text-xs text-green-700 bg-green-50 border border-green-200 px-3 py-2 rounded-lg">
            Anade tantas personas como quieras. Solo tu puedes ver quienes
            estan incluidos en tus favoritos.
          </div>
          <div className="relative">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Buscar un nombre o numero"
              className="w-full pl-8 pr-3 py-2 text-sm border border-gray-200 rounded-full focus:outline-none focus:ring-2 focus:ring-green-500"
              autoFocus
            />
          </div>
          <div>
            <div className="text-[10px] uppercase tracking-wide text-gray-400 mb-1 px-1">
              Chats recientes
            </div>
            <div className="max-h-72 overflow-y-auto wa-scrollbar border border-gray-200 rounded-lg divide-y divide-gray-100">
              {filtered.length === 0 ? (
                <div className="text-center text-xs text-gray-400 py-6">
                  Sin contactos para mostrar.
                </div>
              ) : filtered.map(c => {
                const checked = selectedIds.has(c.id)
                const label = c.contact_name || c.lead_name || c.wa_phone || `#${c.id}`
                return (
                  <label
                    key={c.id}
                    className="flex items-center gap-3 px-3 py-2 hover:bg-gray-50 cursor-pointer text-sm"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggle(c.id)}
                      className="rounded border-gray-300 text-green-600 focus:ring-green-500"
                    />
                    <div className="w-8 h-8 rounded-full bg-gradient-to-br from-green-400 to-emerald-600 text-white flex items-center justify-center text-xs font-semibold shrink-0">
                      {label[0].toUpperCase()}
                    </div>
                    <span className="flex-1 truncate text-gray-800">{label}</span>
                    {c.wa_phone && (
                      <span className="text-[10px] text-gray-400 tabular-nums">
                        {c.wa_phone}
                      </span>
                    )}
                  </label>
                )
              })}
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
            >
              Cancelar
            </button>
            <button
              onClick={handleSave}
              className="px-4 py-2 text-sm font-medium text-white bg-green-600 hover:bg-green-700 rounded-lg transition-colors"
            >
              Guardar ({selectedIds.size})
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

/** Modal para crear una lista — nombre + multi-select de conversaciones.
 *  Solo muestra contactos individuales (el CRM no tiene chats de grupo). */
function CreateListDialog({ open, onClose, conversations, onCreate }) {
  const [name, setName] = useState('')
  const [selectedIds, setSelectedIds] = useState(() => new Set())
  const [search, setSearch] = useState('')

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return conversations
    return conversations.filter(c =>
      (c.contact_name || '').toLowerCase().includes(q) ||
      (c.lead_name || '').toLowerCase().includes(q) ||
      (c.wa_phone || '').includes(q)
    )
  }, [conversations, search])

  const toggle = (id) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const handleSave = () => {
    const trimmed = name.trim()
    if (!trimmed || selectedIds.size === 0) return
    onCreate({
      id: `list_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
      name: trimmed,
      conversationIds: Array.from(selectedIds),
    })
    onClose()
  }

  const canSave = name.trim().length > 0 && selectedIds.size > 0

  return (
    <Dialog open={open} onClose={onClose} size="md">
      <DialogHeader onClose={onClose}>Crear nueva lista</DialogHeader>
      <DialogContent>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-medium text-gray-600 mb-1">
              Nombre de la lista
            </label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Ej: VIPs, Pendientes hoy..."
              className="w-full px-3 py-2 text-sm border border-gray-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-green-500 focus:border-transparent"
              maxLength={40}
              autoFocus
            />
          </div>
          <div>
            <div className="flex items-center justify-between mb-1">
              <label className="block text-xs font-medium text-gray-600">
                Personas incluidas
              </label>
              <span className="text-[10px] text-gray-400">
                {selectedIds.size} seleccionada{selectedIds.size === 1 ? '' : 's'}
              </span>
            </div>
            <div className="relative mb-2">
              <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Buscar persona..."
                className="w-full pl-8 pr-3 py-1.5 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-green-500"
              />
            </div>
            <div className="max-h-64 overflow-y-auto wa-scrollbar border border-gray-200 rounded-lg divide-y divide-gray-100">
              {filtered.length === 0 ? (
                <div className="text-center text-xs text-gray-400 py-6">
                  Sin contactos para mostrar.
                </div>
              ) : filtered.map(c => {
                const checked = selectedIds.has(c.id)
                const label = c.contact_name || c.lead_name || c.wa_phone || `#${c.id}`
                return (
                  <label
                    key={c.id}
                    className="flex items-center gap-2 px-3 py-2 hover:bg-gray-50 cursor-pointer text-sm"
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={() => toggle(c.id)}
                      className="rounded border-gray-300 text-green-600 focus:ring-green-500"
                    />
                    <span className="flex-1 truncate text-gray-800">{label}</span>
                    {c.wa_phone && (
                      <span className="text-[10px] text-gray-400 tabular-nums">
                        {c.wa_phone}
                      </span>
                    )}
                  </label>
                )
              })}
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <button
              onClick={onClose}
              className="px-4 py-2 text-sm font-medium text-gray-600 hover:bg-gray-100 rounded-lg transition-colors"
            >
              Cancelar
            </button>
            <button
              onClick={handleSave}
              disabled={!canSave}
              className="px-4 py-2 text-sm font-medium text-white bg-green-600 hover:bg-green-700 rounded-lg disabled:bg-gray-300 disabled:cursor-not-allowed transition-colors"
            >
              Crear lista
            </button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  )
}

export default function Chat() {
  const { user } = useAuthStore()
  const brand = useBrandStore(s => s.brand)
  const canReclassify = user?.role === 'admin' || user?.role === 'supervisor'
  const [searchParams, setSearchParams] = useSearchParams()
  const location = useLocation()
  const navigate = useNavigate()

  const [conversations, setConversations] = useState([])
  const [selectedId, setSelectedId] = useState(null)
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [loadingConvs, setLoadingConvs] = useState(true)
  // V070.5 — status de configuracion WhatsApp. null = aun cargando, false =
  // sin WABA conectada (mostrar onboarding), true = listo para operar.
  // Lo consume el empty state del sidebar para mostrar CTA a Integraciones
  // (admin) o instrucciones (asesor/supervisor) cuando no hay nada que listar.
  const [waConfigured, setWaConfigured] = useState(null)
  const [loadingMsgs, setLoadingMsgs] = useState(false)
  const [sending, setSending] = useState(false)
  const [reclassifying, setReclassifying] = useState(false)
  const [taking, setTaking] = useState(false)
  // Toast flotante para feedback de acciones (lead creado, error, etc.).
  // Estructura: { type: 'ok'|'err'|'info', title, message, action?: {label, onClick} }
  const [toast, setToast] = useState(null)
  const [showArchive, setShowArchive] = useState(false)
  const [archiveReason, setArchiveReason] = useState('not_a_lead')
  const [archiveNotes, setArchiveNotes] = useState('')
  const [archiving, setArchiving] = useState(false)
  const [showCases, setShowCases] = useState(false)
  const [cases, setCases] = useState([])
  const [loadingCases, setLoadingCases] = useState(false)
  const [showNewCase, setShowNewCase] = useState(false)
  const [newCaseReason, setNewCaseReason] = useState('')
  const [openingNewCase, setOpeningNewCase] = useState(false)
  // Tags del lead activo (V026). leadTags = asignadas al lead; tagCatalog = todas las activas.
  const [leadTags, setLeadTags] = useState([])
  const [tagCatalog, setTagCatalog] = useState([])
  const [uiLabels, setUiLabels] = useState([])
  const [showTagPicker, setShowTagPicker] = useState(false)
  const [tagMutating, setTagMutating] = useState(null) // tag_id siendo agregado/removido
  const [error, setError] = useState(null)
  const [search, setSearch] = useState('')
  const [campaignFilter, setCampaignFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState('')  // '' | potenciales | revisar | archivados | sin_clasificar
  // Conteos por bandeja para los chips + el "Archivados (N)" estilo WhatsApp.
  // Refresca en paralelo con fetchConversations (mismo poll de 5s) — sin
  // round-trip extra desde el punto de vista del UX.
  const [inboxCounts, setInboxCounts] = useState({})
  const [tagFilter, setTagFilter] = useState('')        // '' | <tag_id>  — filtra chats por etiqueta del lead
  const [numberFilter, setNumberFilter] = useState('') // '' | <wa_number_id>  — filtra por linea propia
  const [waNumbers, setWaNumbers] = useState([])       // lineas propias activas (multi-numero)
  const [tagFilterOpen, setTagFilterOpen] = useState(false)
  const [filtersOpen, setFiltersOpen] = useState(false) // popover del header con todos los filtros
  // Custom lists tipo "+ Crear lista" estilo WhatsApp Web — persistidas en
  // localStorage por usuario. activeCustomListId override de los demas filtros
  // (cuando hay lista activa, mostramos solo las conversaciones de esa lista).
  const [customLists, setCustomLists] = useState(() => _readCustomLists(user?.id))
  const [activeCustomListId, setActiveCustomListId] = useState('')
  const [createListOpen, setCreateListOpen] = useState(false)
  // V070.81 — ConfirmDialog premium para eliminar lista en vez de
  // confirm() nativo del browser. {id, name} o null.
  const [confirmDeleteList, setConfirmDeleteList] = useState(null)
  // Quick filter estilo WhatsApp Web — 'all' | 'unread' | 'favorites'.
  // Reemplaza los chips de status (Potenciales/Revisar/...) en la barra
  // principal — esos siguen disponibles via el popover del icono de embudo.
  const [quickFilter, setQuickFilter] = useState('all')
  const [favorites, setFavorites] = useState(() => _readFavorites(user?.id))
  const [favoritesDialogOpen, setFavoritesDialogOpen] = useState(false)
  // V040 — menu contextual por conversacion (estilo WhatsApp Web). Almacena
  // el id de la conv cuyo dropdown esta abierto, o null. Se cierra al click
  // fuera (listener global) y al elegir cualquier accion.
  const [convMenuId, setConvMenuId] = useState(null)
  // V041.1 — direccion en la que se despliega el menu (up | down). Se decide
  // al abrir comparando el espacio disponible arriba vs abajo del chevron,
  // asi la primera conversacion (chevron casi en el tope) abre HACIA ABAJO
  // y las del fondo abren HACIA ARRIBA — ninguna queda recortada.
  const [convMenuDir, setConvMenuDir] = useState('up')
  const convMenuRef = useRef(null)
  // Re-sincronizamos si cambia el usuario logueado (ej. logout/login en la misma sesion).
  useEffect(() => {
    setCustomLists(_readCustomLists(user?.id))
    setFavorites(_readFavorites(user?.id))
    setActiveCustomListId('')
    setQuickFilter('all')
  }, [user?.id])
  // Panel "Info del contacto" (archivos / enlaces / info) — se abre desde el menu kebab del header.
  const [showContactPanel, setShowContactPanel] = useState(false)
  const [contactPanelTab, setContactPanelTab] = useState('files')
  const [headerMenuOpen, setHeaderMenuOpen] = useState(false)
  // Templates de WhatsApp para enviar fuera de ventana 24h.
  // selectedTemplate guarda el template elegido para mostrar el formulario de variables.
  // templateVars es un array de strings (un valor por placeholder {{1}}, {{2}}, ...).
  const [showTemplates, setShowTemplates] = useState(false)
  const [templates, setTemplates] = useState([])
  const [templatesMeta, setTemplatesMeta] = useState(null) // diagnostico cuando lista vacia
  const [loadingTemplates, setLoadingTemplates] = useState(false)
  const [selectedTemplate, setSelectedTemplate] = useState(null)
  const [templateVars, setTemplateVars] = useState([])
  const [sendingTemplate, setSendingTemplate] = useState(false)
  const tagFilterRef = useRef(null)
  const filtersPanelRef = useRef(null)
  const headerMenuRef = useRef(null)
  const messagesEndRef = useRef(null)
  const messagesContainerRef = useRef(null)
  // true cuando el usuario esta "pegado" al final del hilo. Si el usuario
  // scrolea hacia arriba para leer historial, no forzamos scroll cuando
  // llegan mensajes/imagenes nuevos.
  const atBottomRef = useRef(true)
  const prevSelectedIdRef = useRef(null)
  // Id del ultimo mensaje renderizado. Sirve para detectar "llego un mensaje
  // nuevo" sin depender de messages.length (que se estanca cuando el backend
  // limita a los ultimos N y entran mensajes mientras la conv crece).
  const lastMsgIdRef = useRef(null)
  // Al entrar a un chat forzamos scroll al fondo en los primeros frames, aun
  // si banners/media crecen despues del primer paint. Mientras esta en true,
  // ignoramos los scroll events para no perder el "pegado al final".
  const forceScrollToBottomRef = useRef(false)
  // Conv fijada (pinned) que debe aparecer si aun no esta en el listado del
  // backend — tipicamente la conv recien abierta desde LeadDetalle que no
  // tiene mensajes. Se limpia sola cuando el backend la empieza a devolver.
  const pinnedConvRef = useRef(null)

  // Cierra el dropdown de filtro por etiqueta al click fuera
  useEffect(() => {
    if (!tagFilterOpen) return
    const handler = e => {
      if (tagFilterRef.current && !tagFilterRef.current.contains(e.target)) {
        setTagFilterOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [tagFilterOpen])

  // Cierra el panel de filtros al click fuera
  useEffect(() => {
    if (!filtersOpen) return
    const handler = e => {
      if (filtersPanelRef.current && !filtersPanelRef.current.contains(e.target)) {
        setFiltersOpen(false)
        setTagFilterOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [filtersOpen])

  // Cierra el menu kebab del header al click fuera.
  useEffect(() => {
    if (!headerMenuOpen) return
    const handler = e => {
      if (headerMenuRef.current && !headerMenuRef.current.contains(e.target)) {
        setHeaderMenuOpen(false)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [headerMenuOpen])

  // V040: cerrar el menu contextual de conversacion al click fuera.
  useEffect(() => {
    if (convMenuId == null) return
    const handler = e => {
      if (convMenuRef.current && !convMenuRef.current.contains(e.target)) {
        setConvMenuId(null)
      }
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [convMenuId])

  // Cerrar panel "Info del contacto" al cambiar de conversacion — evita
  // mostrar archivos/enlaces obsoletos si el usuario salta a otro chat.
  useEffect(() => {
    setShowContactPanel(false)
    setHeaderMenuOpen(false)
  }, [selectedId])

  // ── Carga lineas propias una vez (multi-numero V033) ────────────────
  // V035: si el usuario tiene una linea por defecto asignada (Escenario A+),
  // pre-selecciona el filtro al primer load. El usuario puede cambiarlo
  // manualmente cualquier momento via el popover de filtros.
  useEffect(() => {
    let alive = true
    // Dos requests en paralelo — mismo mount, mismo round-trip percibido.
    // /status devuelve solo booleanos (no expone phone_number_id) → ligero
    // y seguro de pedir en cada navegacion al chat.
    Promise.all([
      api.get('/api/whatsapp/numbers', { params: { only_active: true } }),
      api.get('/api/whatsapp/status'),
    ])
      .then(([numbersRes, statusRes]) => {
        if (!alive) return
        const items = numbersRes.data.items || []
        setWaNumbers(items)
        if (user?.default_wa_number_id && items.some(n => n.id === user.default_wa_number_id)) {
          setNumberFilter(String(user.default_wa_number_id))
        }
        setWaConfigured(Boolean(statusRes.data?.has_sending_capability))
      })
      .catch(() => {
        // En caso de error, asumimos NO configurado — el empty state
        // pedira al admin revisar Integraciones. Mejor falso negativo que
        // mostrar un chat funcional que despues falla al enviar.
        if (alive) setWaConfigured(false)
      })
    return () => { alive = false }
  }, [user?.default_wa_number_id])

  // ── Fetch conversations (polling 5s) ────────────────────────────────
  const fetchConversations = useCallback(async (silent = false) => {
    if (!silent) setLoadingConvs(true)
    try {
      const params = {}
      if (campaignFilter) params.campaign_id   = campaignFilter
      if (statusFilter)   params.status        = statusFilter
      if (tagFilter)      params.tag_id        = tagFilter
      if (numberFilter)   params.wa_number_id  = numberFilter

      // Conteos comparten todos los filtros excepto status — un usuario que
      // filtra por linea/campaña/etiqueta espera que los chips reflejen ese
      // alcance, no el global. Las dos peticiones van en paralelo: el poll
      // sigue siendo 1 round-trip percibido.
      const countsParams = { ...params }
      delete countsParams.status

      const [convsRes, countsRes] = await Promise.all([
        api.get('/api/whatsapp/conversations', { params }),
        api.get('/api/whatsapp/conversations/counts', { params: countsParams })
          .catch(() => ({ data: { counts: {} } })),  // counts no debe romper la lista
      ])
      setInboxCounts(countsRes.data?.counts || {})
      const data = convsRes.data
      const list = data.conversations || []
      // Preserva la conv pinned (recien abierta desde LeadDetalle) si aun
      // no la devuelve el backend — evita que desaparezca del sidebar en el
      // siguiente poll. Cuando el backend ya la entrega (p.ej. tras primer
      // mensaje), limpiamos el ref.
      const pinned = pinnedConvRef.current
      if (pinned && !list.some(c => c.id === pinned.id)) {
        setConversations([pinned, ...list])
      } else {
        if (pinned) pinnedConvRef.current = null
        setConversations(list)
      }
      setError(null)
    } catch (err) {
      if (!silent) setError(err.response?.data?.detail || 'Error al cargar chats')
    } finally {
      if (!silent) setLoadingConvs(false)
    }
  }, [campaignFilter, statusFilter, tagFilter, numberFilter])

  // El primer mount muestra spinner; las recreaciones del callback (cambio
  // de filtro/bandeja) refetchean en silencio para que la lista previa siga
  // visible mientras llegan los nuevos datos. Evita el "parpadeo" estilo
  // empty-state al cambiar de tab.
  const fetchedOnceRef = useRef(false)
  // Ref siempre apuntando al callback vigente — los setTimeouts disparados
  // tras una accion (reclasificar, desarchivar, archivar) usan esta ref en
  // lugar de capturar la version del callback al momento del click. Asi un
  // refetch tardio no sobreescribe la lista con datos del filtro anterior.
  const fetchConversationsRef = useRef(fetchConversations)
  useEffect(() => {
    fetchConversationsRef.current = fetchConversations
    fetchConversations(fetchedOnceRef.current)
    fetchedOnceRef.current = true
  }, [fetchConversations])
  useEffect(() => {
    const id = setInterval(() => fetchConversationsRef.current(true), 5000)
    return () => clearInterval(id)
  }, [])

  // Deep-link desde LeadDetalle: ?conv=X&draft=... selecciona el chat y
  // precarga el mensaje. LeadDetalle pasa una conv minima en
  // location.state.prefetchedConversation (construida con datos locales) —
  // la inyectamos como pinned para que aparezca en el sidebar al instante y
  // sobreviva a los polls hasta que el backend la empiece a devolver.
  useEffect(() => {
    const convParam  = searchParams.get('conv')
    const draftParam = searchParams.get('draft')
    if (!convParam && !draftParam) return
    if (loadingConvs) return
    const prefetched = location.state?.prefetchedConversation
    if (convParam) {
      const id = parseInt(convParam, 10)
      if (!Number.isNaN(id)) {
        // Limpiamos filtros por si estaban escondiendo la conv.
        setStatusFilter('')
        setCampaignFilter('')
        setTagFilter('')
        setSelectedId(id)
        if (prefetched && prefetched.id === id) {
          // Pin esta conv: el ref la mantiene viva frente al polling.
          pinnedConvRef.current = prefetched
          setConversations(prev => {
            const exists = prev.some(c => c.id === id)
            if (exists) return prev.map(c => c.id === id ? { ...c, ...prefetched } : c)
            return [prefetched, ...prev]
          })
        } else if (!conversations.some(c => c.id === id)) {
          // Sin prefetched y no esta en la lista — fallback: fetch unitario.
          api.get(`/api/whatsapp/conversations/${id}`)
            .then(r => {
              const conv = r.data?.conversation
              if (!conv) return
              pinnedConvRef.current = conv
              setConversations(prev => {
                const exists = prev.some(c => c.id === conv.id)
                if (exists) return prev.map(c => c.id === conv.id ? { ...c, ...conv } : c)
                return [conv, ...prev]
              })
            })
            .catch(() => {})
        }
      }
    }
    if (draftParam) setDraft(draftParam)
    setSearchParams({}, { replace: true })
    // Limpiamos el state para no re-aplicar el prefetched al recargar la ruta
    if (location.state?.prefetchedConversation) {
      navigate(location.pathname, { replace: true, state: {} })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams, loadingConvs])

  // ── Fetch messages del chat activo ──────────────────────────────────
  const fetchMessages = useCallback(async (convId, silent = false) => {
    if (!convId) return
    if (!silent) setLoadingMsgs(true)
    try {
      const { data } = await api.get(`/api/whatsapp/conversations/${convId}/messages`)
      // backend devuelve DESC; mostramos ASC
      setMessages((data.messages || []).slice().reverse())
    } catch {
      if (!silent) setMessages([])
    } finally {
      if (!silent) setLoadingMsgs(false)
    }
  }, [])

  useEffect(() => {
    if (!selectedId) return
    // Al cambiar de chat limpiamos el hilo anterior y armamos el "force
    // scroll" antes de pedir los mensajes nuevos. Evita ver mensajes
    // stale y garantiza que el primer paint quede al fondo.
    setMessages([])
    lastMsgIdRef.current = null
    atBottomRef.current = true
    forceScrollToBottomRef.current = true
    fetchMessages(selectedId)
    // Optimistic: zero local unread_count ya — no esperamos al PATCH ni al
    // proximo poll. Asi el badge verde y la tipografia "nuevo" se apagan
    // al instante cuando abres el chat.
    setConversations(prev => prev.map(c =>
      c.id === selectedId && c.unread_count > 0 ? { ...c, unread_count: 0 } : c
    ))
    // Avisa al sidebar para que refresque el badge rojo sin esperar al
    // polling de 15s.
    window.dispatchEvent(new CustomEvent('chat:unread-changed'))
    api.patch(`/api/whatsapp/conversations/${selectedId}/read`)
      .then(() => {
        // Confirmacion del backend: refresca lista (por si otro cliente cambio
        // contadores) y vuelve a notificar al sidebar con el numero real.
        fetchConversations(true)
        window.dispatchEvent(new CustomEvent('chat:unread-changed'))
      })
      .catch(() => {})
    const id = setInterval(() => fetchMessages(selectedId, true), 4000)
    return () => clearInterval(id)
  }, [selectedId, fetchMessages, fetchConversations])

  // Mientras la conv esta abierta, el badge de no-leidos debe mantenerse en 0.
  // El backend incrementa unread_count en cada mensaje inbound sin saber que
  // el usuario ya lo esta viendo, por eso re-marcamos como leido cuando el
  // polling trae un valor > 0.
  useEffect(() => {
    if (!selectedId) return
    const conv = conversations.find(c => c.id === selectedId)
    if (!conv || (conv.unread_count || 0) === 0) return
    setConversations(prev => prev.map(c =>
      c.id === selectedId ? { ...c, unread_count: 0 } : c
    ))
    api.patch(`/api/whatsapp/conversations/${selectedId}/read`)
      .then(() => window.dispatchEvent(new CustomEvent('chat:unread-changed')))
      .catch(() => {})
  }, [selectedId, conversations])

  // Scroll al final del hilo.
  // - Al cambiar de conversacion: salto instantaneo (como WhatsApp), con
  //   varios re-ajustes en los frames siguientes porque banners, badges y
  //   media async crecen despues del primer paint.
  // - En el mismo chat cuando llega un mensaje nuevo: suave, solo si el
  //   usuario sigue "pegado" al final. Si esta leyendo historial arriba,
  //   respetamos su posicion.
  const scrollToBottom = useCallback((behavior = 'auto') => {
    const el = messagesContainerRef.current
    if (el) el.scrollTop = el.scrollHeight
    messagesEndRef.current?.scrollIntoView({ behavior, block: 'end' })
  }, [])

  // useLayoutEffect corre sincronico antes del paint, evitando el "flash"
  // donde el hilo aparece a mitad un frame antes de bajar.
  useLayoutEffect(() => {
    if (loadingMsgs) return
    if (!messages.length) return
    prevSelectedIdRef.current = selectedId

    const lastId = messages[messages.length - 1].id
    const prevLastId = lastMsgIdRef.current
    const newMessage = prevLastId !== null && lastId !== prevLastId
    lastMsgIdRef.current = lastId

    if (forceScrollToBottomRef.current) {
      // Triple ajuste: sincronico + 2 rAFs. Cubre el caso de banners de
      // campaña/caso/etiquetas y media (imagenes, audios) que se pintan
      // despues del primer frame y alargan el contenedor.
      scrollToBottom('auto')
      requestAnimationFrame(() => {
        scrollToBottom('auto')
        requestAnimationFrame(() => {
          scrollToBottom('auto')
          atBottomRef.current = true
          forceScrollToBottomRef.current = false
        })
      })
      return
    }
    if (newMessage && atBottomRef.current) {
      scrollToBottom('smooth')
    }
  }, [selectedId, messages, loadingMsgs, scrollToBottom])

  // Las imagenes/audio/video se cargan async via blob URL. Cuando terminan
  // de cargar crecen el contenido y pueden dejar el ultimo mensaje fuera de
  // vista. Si el usuario sigue pegado al final, re-ajustamos.
  useEffect(() => {
    const handler = () => {
      if (atBottomRef.current) scrollToBottom('auto')
    }
    window.addEventListener('chat:media-loaded', handler)
    return () => window.removeEventListener('chat:media-loaded', handler)
  }, [scrollToBottom])

  const handleMessagesScroll = (e) => {
    // Mientras estamos auto-ajustando tras abrir un chat, ignoramos los
    // scroll events: el navegador puede emitir eventos transitorios (banners
    // creciendo, medios pintando) que nos moverian fuera de "atBottom".
    if (forceScrollToBottomRef.current) return
    const el = e.currentTarget
    atBottomRef.current = el.scrollHeight - (el.scrollTop + el.clientHeight) < 80
  }

  // ── Send ────────────────────────────────────────────────────────────
  const handleSend = async () => {
    const text = draft.trim()
    if (!text || !selectedConv) return
    setSending(true)
    try {
      await api.post('/api/whatsapp/send', { to: selectedConv.wa_phone, text })
      setDraft('')
      fetchMessages(selectedId, true)
      fetchConversations(true)
    } catch (err) {
      alert(err.response?.data?.detail || 'Error al enviar mensaje')
    } finally {
      setSending(false)
    }
  }

  // ── Templates (fuera de ventana 24h) ───────────────────────────────
  // Cuenta los placeholders {{n}} en el body para saber cuantas variables
  // debe llenar el usuario antes de enviar. Devuelve el N maximo encontrado.
  const countTemplateVars = (body) => {
    if (!body) return 0
    const matches = body.match(/\{\{\s*(\d+)\s*\}\}/g) || []
    if (!matches.length) return 0
    const nums = matches.map(m => parseInt(m.replace(/[^\d]/g, ''), 10))
    return Math.max(...nums)
  }

  const openTemplatesModal = async () => {
    setShowTemplates(true)
    setSelectedTemplate(null)
    setTemplateVars([])
    setTemplatesMeta(null)
    // Siempre recargamos al abrir — el asesor puede haber aprobado un template
    // nuevo en Meta entre aperturas y queremos verlo sin tener que recargar.
    setLoadingTemplates(true)
    try {
      const params = selectedConv?.wa_number_id ? { wa_number_id: selectedConv.wa_number_id } : {}
      const { data } = await api.get('/api/whatsapp/templates', { params })
      setTemplates(data.templates || [])
      setTemplatesMeta(data.meta || null)
    } catch (err) {
      setToast({
        type: 'err',
        title: 'No se pudieron cargar las plantillas',
        message: err.response?.data?.detail || 'Error de red o servicio. Intenta de nuevo en unos segundos.',
      })
      setShowTemplates(false)
    } finally {
      setLoadingTemplates(false)
    }
  }

  const pickTemplate = (tpl) => {
    setSelectedTemplate(tpl)
    const n = countTemplateVars(tpl.body)
    setTemplateVars(new Array(n).fill(''))
  }

  // Sustituye {{1}}, {{2}}, ... por los valores actuales para el preview.
  const renderTemplatePreview = (body, vars) => {
    if (!body) return ''
    return body.replace(/\{\{\s*(\d+)\s*\}\}/g, (_, n) => {
      const v = vars[parseInt(n, 10) - 1]
      return v ? v : `{{${n}}}`
    })
  }

  // Traduce errores conocidos de Meta a un mensaje accionable en espanol.
  // Si no reconoce el codigo, devuelve el detail crudo. El backend reenvia
  // el JSON de Meta dentro de detail.error.{message,code,...}.
  const friendlyMetaError = (rawDetail) => {
    // Backend devuelve detail como string que empieza con "Meta rechazo el template: {...}".
    // Tambien puede ser objeto si vino de otra ruta. Normalizamos.
    let metaErr = null
    try {
      if (typeof rawDetail === 'string') {
        const m = rawDetail.match(/\{.*\}$/s)
        if (m) {
          const parsed = JSON.parse(m[0].replace(/'/g, '"'))
          metaErr = parsed?.error || null
        }
      } else if (rawDetail?.error) {
        metaErr = rawDetail.error
      }
    } catch { /* fallthrough */ }
    if (!metaErr) {
      return { title: 'Meta rechazo el envio', body: String(rawDetail || 'Error desconocido') }
    }
    const code = metaErr.code
    const msg = metaErr.message || ''
    if (code === 131058 || /Hello World/i.test(msg)) {
      return {
        title: 'hello_world solo funciona en sandbox',
        body: 'Meta restringe el template "hello_world" a numeros de prueba. Crea tus propias plantillas (bienvenida_lead_asignado, etc.) en tu WABA y, una vez aprobadas, se podran enviar desde tu numero de produccion.',
      }
    }
    if (code === 132001) {
      return {
        title: 'Plantilla no existe en esta WABA',
        body: 'La plantilla no esta registrada en la WABA del numero que estas usando. Verifica que la creaste en la cuenta correcta y no en otra.',
      }
    }
    if (code === 132000) {
      return {
        title: 'Numero del lead no es valido',
        body: 'Meta no acepta este numero. Verifica que tenga prefijo de pais correcto y que sea movil con WhatsApp activo.',
      }
    }
    if (code === 131026) {
      return {
        title: 'No se puede enviar a este numero',
        body: 'El destinatario no esta en WhatsApp o bloqueo mensajes desde tu numero comercial.',
      }
    }
    if (code === 100) {
      return {
        title: 'Configuracion incorrecta',
        body: `${msg}. Verifica los IDs y permisos del access_token en Configuracion > WhatsApp.`,
      }
    }
    return {
      title: `Meta rechazo el envio (codigo ${code})`,
      body: msg || 'Sin detalle.',
    }
  }

  const handleSendTemplate = async () => {
    if (!selectedTemplate || !selectedConv) return
    if (templateVars.some(v => !v || !v.trim())) {
      setToast({
        type: 'err',
        title: 'Faltan variables',
        message: 'Completa todas las variables del template antes de enviar.',
      })
      return
    }
    setSendingTemplate(true)
    try {
      const components = templateVars.length > 0
        ? [{
            type: 'body',
            parameters: templateVars.map(v => ({ type: 'text', text: v.trim() })),
          }]
        : undefined
      await api.post('/api/whatsapp/send/template', {
        to: selectedConv.wa_phone,
        template_name: selectedTemplate.name,
        language: selectedTemplate.language || 'es',
        components,
        wa_number_id: selectedConv.wa_number_id || undefined,
      })
      setShowTemplates(false)
      setSelectedTemplate(null)
      setTemplateVars([])
      setToast({
        type: 'ok',
        title: 'Plantilla enviada',
        message: `"${selectedTemplate.name}" llego a Meta para entrega.`,
      })
      fetchMessages(selectedId, true)
      fetchConversations(true)
    } catch (err) {
      const friendly = friendlyMetaError(err.response?.data?.detail)
      // Toast no bloqueante — el modal se queda abierto para que el asesor
      // pruebe con otro template sin perder lo que ya tipeo.
      setToast({
        type: 'err',
        title: friendly.title,
        message: friendly.body,
      })
    } finally {
      setSendingTemplate(false)
    }
  }

  // ── Historico de casos (N:M chat <-> lead) ─────────────────────────
  const loadCases = useCallback(async (convId) => {
    if (!convId) return
    setLoadingCases(true)
    try {
      const { data } = await api.get(`/api/whatsapp/conversations/${convId}/cases`)
      setCases(data.cases || [])
    } catch {
      setCases([])
    } finally {
      setLoadingCases(false)
    }
  }, [])

  // Cierra el panel al cambiar de chat
  useEffect(() => {
    setShowCases(false); setCases([])
    setShowNewCase(false); setNewCaseReason('')
    setShowTagPicker(false); setLeadTags([])
  }, [selectedId])

  // ── Tags (V026) ────────────────────────────────────────────────────
  // Carga catalogo una sola vez y tags del lead activo cuando hay lead
  useEffect(() => {
    api.get('/api/tags').then(r => setTagCatalog(r.data || [])).catch(() => {})
    api.get('/api/whatsapp/ui-labels').then(r => setUiLabels(r.data || [])).catch(() => {})
  }, [])

  // Map `${kind}:${key}` -> {label, color_hex, icon_name, activo} para lookup O(1)
  const labelsMap = useMemo(() => {
    const m = new Map()
    uiLabels.forEach(l => m.set(`${l.kind}:${l.key}`, l))
    return m
  }, [uiLabels])

  // Labels de bandejas (inbox) ordenados segun sort_order
  const inboxOptions = useMemo(() => {
    const rows = uiLabels.filter(l => l.kind === 'inbox' && l.activo)
    if (rows.length === 0) {
      // Fallback si la config no cargo
      return Object.entries(STATUS_LABELS_FALLBACK).map(([key, label]) => ({ key, label }))
    }
    return [...rows].sort((a, b) => a.sort_order - b.sort_order).map(l => ({ key: l.key, label: l.label }))
  }, [uiLabels])

  // Etiqueta de urgencia (si la IA marco urgencia alta)
  const urgencyLabel = useMemo(() => {
    return labelsMap.get('urgency:alta') || URGENCY_FALLBACK.alta
  }, [labelsMap])

  // V038: tags pueden vivir a nivel conversacion (cuando no hay lead todavia).
  // Cuando se "toma" el chat y se crea el lead, el trigger SQL copia las tags
  // al lead automaticamente. Desde ese momento, todo se gestiona via lead.
  // El frontend elige el endpoint segun el estado de la conv:
  //   - lead_id presente → /api/leads/{lead_id}/tags        (existing)
  //   - lead_id ausente   → /api/whatsapp/conversations/{id}/tags (V038)
  const selectedLeadId = useMemo(
    () => conversations.find(c => c.id === selectedId)?.lead_id || null,
    [conversations, selectedId]
  )

  const tagsEndpoint = useMemo(() => {
    if (selectedLeadId) {
      return {
        list:   () => `/api/leads/${selectedLeadId}/tags`,
        add:    () => `/api/leads/${selectedLeadId}/tags`,
        remove: (tagId) => `/api/leads/${selectedLeadId}/tags/${tagId}`,
      }
    }
    if (selectedId) {
      return {
        list:   () => `/api/whatsapp/conversations/${selectedId}/tags`,
        add:    () => `/api/whatsapp/conversations/${selectedId}/tags`,
        remove: (tagId) => `/api/whatsapp/conversations/${selectedId}/tags/${tagId}`,
      }
    }
    return null
  }, [selectedLeadId, selectedId])

  const loadLeadTags = useCallback(async () => {
    if (!tagsEndpoint) { setLeadTags([]); return }
    try {
      const { data } = await api.get(tagsEndpoint.list())
      setLeadTags(data || [])
    } catch { setLeadTags([]) }
  }, [tagsEndpoint])

  useEffect(() => { loadLeadTags() }, [loadLeadTags])

  const handleAddTag = async (tagId) => {
    if (!tagsEndpoint || tagMutating) return
    setTagMutating(tagId)
    try {
      await api.post(tagsEndpoint.add(), { tag_id: tagId })
      const added = tagCatalog.find(t => t.id === tagId)
      if (added && !leadTags.some(t => t.id === tagId)) {
        setLeadTags(prev => [...prev, added])
      }
      setShowTagPicker(false)
      fetchConversations(true)
    } catch (err) {
      alert(err.response?.data?.detail || 'No se pudo agregar la etiqueta')
    } finally { setTagMutating(null) }
  }

  const handleRemoveTag = async (tagId) => {
    if (!tagsEndpoint || tagMutating) return
    setTagMutating(tagId)
    try {
      await api.delete(tagsEndpoint.remove(tagId))
      setLeadTags(prev => prev.filter(t => t.id !== tagId))
      fetchConversations(true)
    } catch (err) {
      alert(err.response?.data?.detail || 'No se pudo quitar la etiqueta')
    } finally { setTagMutating(null) }
  }

  // ── Abrir nuevo caso (cliente vuelve por nuevo lote) ───────────────
  const handleOpenNewCase = async () => {
    if (!selectedId) return
    setOpeningNewCase(true)
    try {
      await api.post(`/api/whatsapp/conversations/${selectedId}/new_case`, {
        reason: newCaseReason.trim() || null,
      })
      setShowNewCase(false)
      setNewCaseReason('')
      // El classifier corre en background ~10s. Refrescamos en cascada
      // para que el chip "Caso N" se actualice cuando el router cree el lead.
      fetchConversationsRef.current(true)
      setTimeout(() => fetchConversationsRef.current(true), 4000)
      setTimeout(() => fetchConversationsRef.current(true), 12000)
    } catch (err) {
      alert(err.response?.data?.detail || 'Error al abrir nuevo caso')
    } finally {
      setOpeningNewCase(false)
    }
  }

  // ── Tomar este chat (auto-asignarme + crear lead si no existe) ───────
  const handleTake = async () => {
    if (!selectedId) return
    setTaking(true)
    try {
      const { data } = await api.post(
        `/api/whatsapp/conversations/${selectedId}/take`,
      )
      // Feedback via toast flotante (no bloqueante). Casos del backend:
      //   lead_created=true → se creo lead nuevo
      //   via=lead_reused   → se reuso lead activo del mismo telefono
      //   via=lead_reassign → ya tenia lead, solo se reasigno
      //   already_owned     → ya era tuyo con lead (no toast — silencioso)
      const goToLead = data?.lead_id
        ? () => window.open(`/leads/${data.lead_id}`, '_blank')
        : null
      if (data?.lead_created) {
        setToast({
          type:    'ok',
          title:   'Lead creado',
          message: `"${data.lead_name}" se asignó a ti. Ya está en /Leads.`,
          action:  goToLead && { label: 'Ver lead', onClick: goToLead },
        })
      } else if (data?.via === 'lead_reused') {
        setToast({
          type:    'info',
          title:   'Asignado a lead existente',
          message: `Ya tenías un lead activo para "${data.lead_name}". Te lo reasignamos.`,
          action:  goToLead && { label: 'Ver lead', onClick: goToLead },
        })
      } else if (data?.via === 'lead_reassign') {
        setToast({
          type:    'ok',
          title:   'Chat reasignado',
          message: `Ahora "${data.lead_name || 'el chat'}" es tuyo.`,
          action:  goToLead && { label: 'Ver lead', onClick: goToLead },
        })
      }
      // Refresca el listado para que el header muestre el nuevo estado.
      fetchConversations(true)
    } catch (err) {
      setToast({
        type:    'err',
        title:   'Error al tomar el chat',
        message: err.response?.data?.detail || 'Intentalo de nuevo en unos segundos.',
      })
    } finally {
      setTaking(false)
    }
  }

  // ── Reclasificar (manual trigger IA) ───────────────────────────────
  const handleReclassify = async () => {
    if (!selectedId) return
    setReclassifying(true)
    try {
      const { data } = await api.post(
        `/api/whatsapp/conversations/${selectedId}/reclassify`
      )
      // Caso "Desarchivar": el backend cambia status a manual_review en la
      // misma request — un solo refresh y listo. Sin setTimeouts: evita que
      // refetchs tardios con filtro stale ("Archivados") sobreescriban la
      // lista cuando el usuario ya cambio a otro tab.
      if (data?.unarchived) {
        fetchConversationsRef.current(true)
        return
      }
      // Caso "Reclasificar" real: el BackgroundTask de IA tarda ~10s.
      // Mantenemos los polls escalonados para refrescar el chip.
      fetchConversationsRef.current(true)
      setTimeout(() => fetchConversationsRef.current(true), 4000)
      setTimeout(() => fetchConversationsRef.current(true), 12000)
    } catch (err) {
      alert(err.response?.data?.detail || 'Error al reclasificar')
    } finally {
      setReclassifying(false)
    }
  }

  // ── Archivar (descalificar conversacion patrón estándar) ────────
  const handleArchive = async () => {
    if (!selectedId || !archiveReason) return
    setArchiving(true)
    try {
      await api.post(
        `/api/whatsapp/conversations/${selectedId}/archive`,
        { reason: archiveReason, notes: archiveNotes || null }
      )
      setShowArchive(false)
      setArchiveNotes('')
      setArchiveReason('not_a_lead')
      // El chat sale del inbox por defecto — limpiamos seleccion y recargamos
      setSelectedId(null)
      fetchConversations(true)
    } catch (err) {
      alert(err.response?.data?.detail || 'Error al archivar')
    } finally {
      setArchiving(false)
    }
  }

  // ── Derived ─────────────────────────────────────────────────────────
  const selectedConv = useMemo(
    () => conversations.find(c => c.id === selectedId),
    [conversations, selectedId]
  )

  const activeCustomList = useMemo(
    () => customLists.find(l => l.id === activeCustomListId) || null,
    [customLists, activeCustomListId],
  )

  const filteredConvs = useMemo(() => {
    let base = conversations
    // Custom list activa = override absoluto. Coexiste con quickFilter
    // priorizando la lista (mas especifica que "no leidos" o "favoritos").
    if (activeCustomList) {
      const ids = new Set(activeCustomList.conversationIds)
      base = conversations.filter(c => ids.has(c.id))
    } else if (quickFilter === 'unread') {
      base = conversations.filter(c => (c.unread_count || 0) > 0)
    } else if (quickFilter === 'favorites') {
      base = conversations.filter(c => favorites.has(c.id))
    }
    const q = search.trim().toLowerCase()
    if (!q) return base
    return base.filter(c =>
      (c.contact_name || '').toLowerCase().includes(q) ||
      (c.lead_name || '').toLowerCase().includes(q) ||
      (c.wa_phone || '').includes(q)
    )
  }, [conversations, search, activeCustomList, quickFilter, favorites])

  // Conteo en vivo para los chips — se recalcula con cada poll de convs.
  const unreadCount = useMemo(
    () => conversations.filter(c => (c.unread_count || 0) > 0).length,
    [conversations],
  )

  // NOTA: WhatsApp Web NO auto-selecciona conversaciones al cargar. El
  // panel derecho queda limpio hasta que el usuario elige un chat. Respeta
  // mejor la atencion del usuario y matchea la UX que el equipo conoce.
  // Solo el deep-link (?conv=...) selecciona automaticamente — eso lo
  // maneja otro effect.

  const handleCreateCustomList = useCallback((list) => {
    setCustomLists(prev => {
      const next = [...prev, list]
      _writeCustomLists(user?.id, next)
      return next
    })
    setActiveCustomListId(list.id) // foco automatico en la lista recien creada
    setQuickFilter('all')
  }, [user?.id])

  const handleDeleteCustomList = useCallback((listId) => {
    setCustomLists(prev => {
      const next = prev.filter(l => l.id !== listId)
      _writeCustomLists(user?.id, next)
      return next
    })
    setActiveCustomListId(prev => prev === listId ? '' : prev)
  }, [user?.id])

  const toggleFavorite = useCallback((convId) => {
    setFavorites(prev => {
      const next = new Set(prev)
      if (next.has(convId)) next.delete(convId)
      else next.add(convId)
      _writeFavorites(user?.id, next)
      return next
    })
  }, [user?.id])

  const handleSaveFavorites = useCallback((newFavorites) => {
    setFavorites(newFavorites)
    _writeFavorites(user?.id, newFavorites)
  }, [user?.id])

  const activeFiltersCount =
    (statusFilter ? 1 : 0) + (campaignFilter ? 1 : 0) + (tagFilter ? 1 : 0) + (numberFilter ? 1 : 0)
  const hasActiveFilters = activeFiltersCount > 0

  // Lista de campañas unicas agrupadas por label (meta_ad_name/headline).
  // Un mismo copy puede existir con varios wa_campaign_id porque Meta crea
  // un ad_id distinto cada vez que se impulsa el post. En el dropdown los
  // colapsamos en una sola opcion y el filtro envia todos los ids juntos.
  const campaigns = useMemo(() => {
    const byLabel = new Map() // label → [ids]
    conversations.forEach(c => {
      const label = c.meta_ad_name || c.wa_campaign_headline || c.campaign_name
      if (c.wa_campaign_id && label) {
        const ids = byLabel.get(label) || []
        if (!ids.includes(c.wa_campaign_id)) ids.push(c.wa_campaign_id)
        byLabel.set(label, ids)
      }
    })
    return Array.from(byLabel, ([name, ids]) => ({
      id: ids.join(','),
      name,
      count: ids.length,
    }))
  }, [conversations])

  const windowOpen = selectedConv?.window_expires_at &&
    new Date(selectedConv.window_expires_at) > new Date()

  // V037: thumbnail del creative al nivel de la conversacion. Se comparte
  // entre todas las tarjetas de referral del hilo (que tipicamente son del
  // mismo ad) para evitar N requests identicos.
  const convThumb = useCampaignThumbnailBlob(
    selectedConv?.wa_campaign_id,
    Boolean(selectedConv?.meta_creative_thumbnail_ready),
  )

  // ── Render ──────────────────────────────────────────────────────────
  return (
    <div className="flex h-full bg-white rounded-xl overflow-hidden border border-gray-200">
      {/* Sidebar — lista de chats */}
      <aside className="w-80 border-r border-gray-200 flex flex-col bg-gray-50/40">
        <div ref={filtersPanelRef} className="p-3 border-b border-gray-200 bg-white space-y-2 relative">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-gray-800 flex items-center gap-2">
              <MessageCircle size={16} className="text-green-600" /> Chats
            </h2>
            <div className="flex items-center gap-1">
              <button
                onClick={() => setFiltersOpen(o => !o)}
                className={`relative p-1.5 rounded transition-colors ${filtersOpen || hasActiveFilters ? 'text-green-600 bg-green-50' : 'text-gray-400 hover:text-gray-600'}`}
                title="Filtros"
              >
                <Filter size={14} />
                {hasActiveFilters && (
                  <span className="absolute -top-0.5 -right-0.5 bg-green-500 text-white text-[9px] font-bold rounded-full w-3.5 h-3.5 flex items-center justify-center leading-none">
                    {activeFiltersCount}
                  </span>
                )}
              </button>
              <button
                onClick={() => fetchConversations()}
                className="text-gray-400 hover:text-gray-600 p-1.5 rounded transition-colors"
                title="Recargar"
              >
                <RefreshCw size={14} />
              </button>
            </div>
          </div>
          <div className="relative">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              placeholder={
                activeCustomList
                  ? `Buscar en "${activeCustomList.name}"...`
                  : quickFilter === 'unread'
                    ? 'Buscar chats no leidos...'
                    : quickFilter === 'favorites'
                      ? 'Buscar chats favoritos...'
                      : 'Buscar chat...'
              }
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full h-9 pl-8 pr-2 rounded-lg border border-gray-200 bg-gray-50 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 focus:bg-white transition-colors"
            />
          </div>

          {/* Bandejas rapidas — chips horizontales estilo WhatsApp
              (Todos / Potenciales / Revisar / ...). Acceso sin abrir el popover.
              Conteo a la derecha de cada label (estilo mensajería profesional) para que
              el usuario vea el inventario sin abrir cada bandeja.
              Fade en el borde derecho insinua scroll horizontal cuando hay
              mas chips de los que entran en el ancho del sidebar. */}
          <div className="relative">
            <div className="flex gap-1.5 overflow-x-auto no-scrollbar -mx-0.5 px-0.5">
              {/* Chips estilo WhatsApp Web: Todos / No leidos / Favoritos.
                  Reemplazan los chips de status (Potenciales / Revisar /...)
                  que ahora viven en el popover del icono de embudo. */}
              <button
                onClick={() => { setQuickFilter('all'); setActiveCustomListId('') }}
                className={`shrink-0 inline-flex items-center gap-1.5 text-[11px] font-medium px-2.5 py-1 rounded-full border transition-colors ${
                  quickFilter === 'all' && !activeCustomListId
                    ? 'bg-green-100 text-green-800 border-green-200'
                    : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'
                }`}
              >
                Todos
              </button>
              <button
                onClick={() => { setQuickFilter('unread'); setActiveCustomListId('') }}
                className={`shrink-0 inline-flex items-center gap-1.5 text-[11px] font-medium px-2.5 py-1 rounded-full border transition-colors ${
                  quickFilter === 'unread' && !activeCustomListId
                    ? 'bg-green-100 text-green-800 border-green-200'
                    : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'
                }`}
              >
                No leidos
                {unreadCount > 0 && (
                  <span className={`text-[10px] tabular-nums ${
                    quickFilter === 'unread' && !activeCustomListId ? 'text-green-700/80' : 'text-gray-400'
                  }`}>
                    {unreadCount}
                  </span>
                )}
              </button>
              <button
                onClick={() => { setQuickFilter('favorites'); setActiveCustomListId('') }}
                className={`shrink-0 inline-flex items-center gap-1.5 text-[11px] font-medium px-2.5 py-1 rounded-full border transition-colors ${
                  quickFilter === 'favorites' && !activeCustomListId
                    ? 'bg-green-100 text-green-800 border-green-200'
                    : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'
                }`}
              >
                Favoritos
                {favorites.size > 0 && (
                  <span className={`text-[10px] tabular-nums ${
                    quickFilter === 'favorites' && !activeCustomListId ? 'text-green-700/80' : 'text-gray-400'
                  }`}>
                    {favorites.size}
                  </span>
                )}
              </button>
              {/* Custom lists del usuario (persistidas en localStorage). Cada
                  chip es deletable: la X aparece on hover y solo en la lista
                  activa para no agregar ruido visual. */}
              {customLists.map(list => {
                const active = activeCustomListId === list.id
                return (
                  <div
                    key={list.id}
                    className={`group/chip shrink-0 inline-flex items-center gap-1 text-[11px] font-medium pl-2.5 pr-1 py-0.5 rounded-full border transition-colors ${
                      active
                        ? 'bg-green-100 text-green-800 border-green-200'
                        : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'
                    }`}
                  >
                    <button
                      onClick={() => {
                        setStatusFilter('')
                        setActiveCustomListId(active ? '' : list.id)
                      }}
                      className="inline-flex items-center gap-1.5 py-0.5"
                      title={`${list.conversationIds.length} contacto${list.conversationIds.length === 1 ? '' : 's'}`}
                    >
                      <span className="truncate max-w-[100px]">{list.name}</span>
                      <span className={`text-[10px] tabular-nums ${
                        active ? 'text-green-700/80' : 'text-gray-400'
                      }`}>
                        {list.conversationIds.length}
                      </span>
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation()
                        // V070.81 — abre ConfirmDialog premium (antes era
                        // confirm() nativo del browser).
                        setConfirmDeleteList({ id: list.id, name: list.name })
                      }}
                      className={`p-0.5 rounded-full transition-opacity ${
                        active ? 'opacity-70 hover:opacity-100' : 'opacity-0 group-hover/chip:opacity-60 hover:!opacity-100'
                      } hover:bg-black/10`}
                      title="Eliminar lista"
                      aria-label="Eliminar lista"
                    >
                      <X size={11} />
                    </button>
                  </div>
                )
              })}
              {/* Botón "+" para crear lista custom — estilo WhatsApp Web.
                  Solo visible si hay conversaciones para elegir. */}
              {conversations.length > 0 && (
                <button
                  onClick={() => setCreateListOpen(true)}
                  className="shrink-0 inline-flex items-center justify-center w-7 h-7 rounded-full border border-gray-200 bg-white text-gray-500 hover:bg-gray-100 hover:text-gray-700 transition-colors"
                  title="Crear nueva lista"
                  aria-label="Crear nueva lista"
                >
                  <Plus size={14} />
                </button>
              )}
            </div>
            {/* Gradient fade derecho — pista visual de scroll horizontal */}
            <div className="pointer-events-none absolute top-0 right-0 h-full w-6 bg-gradient-to-l from-white to-transparent" />
          </div>

          {/* Chips de filtros activos — solo muestran filtros que NO estan en la
              barra de bandejas (campaña, etiqueta, linea). El status ya tiene
              su propio pill resaltado arriba. */}
          {(campaignFilter || tagFilter || numberFilter) && (
            <div className="flex items-center gap-1 flex-wrap">
              {campaignFilter && (
                <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full bg-blue-50 text-blue-700 border border-blue-200">
                  {campaigns.find(c => String(c.id) === String(campaignFilter))?.name || 'Campaña'}
                  <button onClick={() => setCampaignFilter('')} className="hover:text-blue-900">
                    <X size={10} />
                  </button>
                </span>
              )}
              {tagFilter && (() => {
                const t = tagCatalog.find(x => String(x.id) === String(tagFilter))
                if (!t) return null
                return (
                  <span
                    className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full border"
                    style={{ backgroundColor: t.color_hex + '22', color: t.color_hex, borderColor: t.color_hex + '55' }}
                  >
                    <span className="inline-block w-1.5 h-1.5 rounded-full" style={{ backgroundColor: t.color_hex }} />
                    {t.nombre}
                    <button onClick={() => setTagFilter('')} className="hover:opacity-70">
                      <X size={10} />
                    </button>
                  </span>
                )
              })()}
              {numberFilter && (() => {
                const n = waNumbers.find(x => String(x.id) === String(numberFilter))
                if (!n) return null
                return (
                  <span className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full bg-purple-50 text-purple-700 border border-purple-200">
                    {n.display_name}
                    <button onClick={() => setNumberFilter('')} className="hover:text-purple-900">
                      <X size={10} />
                    </button>
                  </span>
                )
              })()}
              <button
                onClick={() => { setStatusFilter(''); setCampaignFilter(''); setTagFilter(''); setNumberFilter('') }}
                className="text-[10px] text-gray-500 hover:text-gray-700 underline ml-1"
              >
                Limpiar
              </button>
            </div>
          )}

          {/* Popover de filtros — debajo del header */}
          {filtersOpen && (
            <div className="absolute left-3 right-3 top-full mt-1 z-30 bg-white border border-gray-200 rounded-lg shadow-xl p-3 space-y-2.5">
              {waNumbers.length > 1 && (
                <div>
                  <label className="block text-[10px] font-semibold uppercase tracking-wide text-gray-500 mb-1">Linea</label>
                  <select
                    value={numberFilter}
                    onChange={e => setNumberFilter(e.target.value)}
                    className="w-full h-8 rounded-md border border-gray-200 bg-white text-sm px-2 focus:outline-none focus:ring-2 focus:ring-green-500"
                  >
                    <option value="">Todas las lineas</option>
                    {waNumbers.map(n => (
                      <option key={n.id} value={n.id}>
                        {n.display_name}{n.display_phone ? ` · ${n.display_phone}` : ''}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              <div>
                <label className="block text-[10px] font-semibold uppercase tracking-wide text-gray-500 mb-1">Bandeja</label>
                <select
                  value={statusFilter}
                  onChange={e => setStatusFilter(e.target.value)}
                  className="w-full h-8 rounded-md border border-gray-200 bg-white text-sm px-2 focus:outline-none focus:ring-2 focus:ring-green-500"
                >
                  <option value="">Todos los chats</option>
                  {inboxOptions
                    .filter(o => canReclassify || o.key !== 'delegar')
                    .map(o => (
                      <option key={o.key} value={o.key}>{o.label}</option>
                    ))}
                </select>
              </div>
              {campaigns.length > 0 && (
                <div>
                  <label className="block text-[10px] font-semibold uppercase tracking-wide text-gray-500 mb-1">Campaña</label>
                  <select
                    value={campaignFilter}
                    onChange={e => setCampaignFilter(e.target.value)}
                    className="w-full h-8 rounded-md border border-gray-200 bg-white text-sm px-2 focus:outline-none focus:ring-2 focus:ring-green-500"
                  >
                    <option value="">Todas las campañas</option>
                    {campaigns.map(c => (
                      <option key={c.id} value={c.id}>
                        {c.name}{c.count > 1 ? ` (${c.count} ads)` : ''}
                      </option>
                    ))}
                  </select>
                </div>
              )}
              {tagCatalog.length > 0 && (() => {
                const selectedTag = tagCatalog.find(t => String(t.id) === String(tagFilter))
                return (
                  <div>
                    <label className="block text-[10px] font-semibold uppercase tracking-wide text-gray-500 mb-1">Etiqueta del lead</label>
                    <div ref={tagFilterRef} className="relative">
                      <button
                        type="button"
                        onClick={() => setTagFilterOpen(o => !o)}
                        className="w-full h-8 rounded-md border border-gray-200 bg-white text-sm px-2 flex items-center justify-between gap-2 hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-green-500"
                      >
                        <span className="flex items-center gap-1.5 truncate min-w-0">
                          {selectedTag ? (
                            <>
                              <span
                                className="inline-block w-2.5 h-2.5 rounded-full shrink-0 border"
                                style={{ backgroundColor: selectedTag.color_hex, borderColor: selectedTag.color_hex + '99' }}
                              />
                              <span className="truncate" style={{ color: selectedTag.color_hex }}>{selectedTag.nombre}</span>
                            </>
                          ) : (
                            <span className="text-gray-600">Todas las etiquetas</span>
                          )}
                        </span>
                        <ChevronDown size={14} className={`shrink-0 text-gray-400 transition-transform ${tagFilterOpen ? 'rotate-180' : ''}`} />
                      </button>
                      {tagFilterOpen && (
                        <div className="absolute left-0 right-0 mt-1 z-10 bg-white border border-gray-200 rounded-md shadow-lg max-h-56 overflow-y-auto">
                          <button
                            type="button"
                            onClick={() => { setTagFilter(''); setTagFilterOpen(false) }}
                            className={`w-full text-left px-2.5 py-1.5 text-sm hover:bg-gray-50 ${!tagFilter ? 'bg-green-50 text-green-700 font-medium' : 'text-gray-700'}`}
                          >
                            Todas las etiquetas
                          </button>
                          {tagCatalog.map(t => (
                            <button
                              key={t.id}
                              type="button"
                              onClick={() => { setTagFilter(String(t.id)); setTagFilterOpen(false) }}
                              className={`w-full text-left px-2.5 py-1.5 text-sm hover:bg-gray-50 flex items-center gap-1.5 ${String(tagFilter) === String(t.id) ? 'bg-gray-50 font-medium' : ''}`}
                            >
                              <span
                                className="inline-block w-2.5 h-2.5 rounded-full shrink-0 border"
                                style={{ backgroundColor: t.color_hex, borderColor: t.color_hex + '99' }}
                              />
                              <span className="truncate" style={{ color: t.color_hex }}>{t.nombre}</span>
                            </button>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                )
              })()}
              <div className="flex justify-end pt-1 border-t border-gray-100">
                <button
                  onClick={() => setFiltersOpen(false)}
                  className="text-xs text-gray-600 hover:text-gray-800 px-2 py-1"
                >
                  Cerrar
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="flex-1 overflow-y-auto wa-scrollbar">
          {/* Encabezado "Archivados" estilo WhatsApp Web — siempre visible
              arriba de la lista cuando hay archivados y NO estamos viendolos.
              Click → cambia el filtro a la bandeja de archivados. Resuelve el
              caso "tengo un chat nuevo pero quedo archivado y no lo encuentro".

              Dos estados visuales:
              - Neutro: gris, contador total a la derecha (rutina, sin urgencia).
              - Alerta: cuando hay chats archivados con mensajes no leidos,
                icono verde + texto bold + pill verde con el # de no leidos
                (estilo unread badge de WhatsApp). Asi el usuario sabe al
                toque que "hay algo nuevo ahi, hay que revisarlo". */}
          {statusFilter !== 'archivados' && (inboxCounts.archivados || 0) > 0 && !search && (() => {
            const unread = inboxCounts.archivados_unread || 0
            const hasUnread = unread > 0
            return (
              <button
                onClick={() => setStatusFilter('archivados')}
                className={`w-full px-3 py-2.5 border-b flex items-center gap-3 transition-colors group ${
                  hasUnread
                    ? 'bg-green-50/60 hover:bg-green-50 border-green-100'
                    : 'hover:bg-gray-50 border-gray-100'
                }`}
                title={hasUnread ? `${unread} no leído${unread > 1 ? 's' : ''} en archivados` : 'Ver chats archivados'}
              >
                <div className={`w-9 h-9 rounded-full flex items-center justify-center shrink-0 transition-colors ${
                  hasUnread
                    ? 'bg-green-100 text-green-700 group-hover:bg-green-200'
                    : 'bg-gray-100 text-gray-500 group-hover:bg-gray-200'
                }`}>
                  <Archive size={16} />
                </div>
                <div className="flex-1 flex items-center justify-between gap-2 min-w-0">
                  <div className="flex flex-col items-start min-w-0">
                    <span className={`text-sm truncate ${
                      hasUnread ? 'font-semibold text-gray-900' : 'font-medium text-gray-700'
                    }`}>
                      Archivados
                    </span>
                    {hasUnread && (
                      <span className="text-[11px] text-green-700 font-medium">
                        {unread} nuevo{unread > 1 ? 's' : ''} sin leer
                      </span>
                    )}
                  </div>
                  {hasUnread ? (
                    <span className="shrink-0 bg-green-500 text-white text-[10px] font-bold px-1.5 min-w-[20px] h-5 rounded-full flex items-center justify-center leading-none shadow-sm tabular-nums">
                      {unread > 99 ? '99+' : unread}
                    </span>
                  ) : (
                    <span className="text-xs text-gray-500 tabular-nums shrink-0">
                      {inboxCounts.archivados}
                    </span>
                  )}
                </div>
              </button>
            )
          })()}
          {loadingConvs ? (
            <div className="py-8"><LoadingSpinner /></div>
          ) : error ? (
            <div className="p-4 text-sm text-red-600 bg-red-50 m-2 rounded">{error}</div>
          ) : waConfigured === false && filteredConvs.length === 0 ? (
            // V070.5 — Empty state de onboarding: WhatsApp Business no esta
            // configurado. Tiene prioridad sobre los demas empty states porque
            // sin WABA no hay forma de que entren chats — mejor decirlo
            // explicito que mostrar "Aun no hay chats" que sugiere "espera y
            // llegaran". CTA condicional al rol: admin va directo a la
            // pagina de configuracion; asesor/supervisor solo recibe la guia.
            <div className="px-6 py-12 text-center">
              <div className="w-16 h-16 rounded-2xl bg-amber-50 mx-auto mb-3 flex items-center justify-center">
                <ShieldAlert size={28} className="text-amber-500" />
              </div>
              <div className="text-sm font-semibold text-gray-700 mb-1">
                WhatsApp no esta conectado
              </div>
              <p className="text-xs text-gray-500 mb-4 max-w-[240px] mx-auto leading-relaxed">
                {user?.role === 'admin'
                  ? 'Conecta tu cuenta de WhatsApp Business (WABA) para empezar a recibir y enviar mensajes desde el CRM.'
                  : 'Pide al admin que conecte la cuenta de WhatsApp Business en Integraciones para empezar a recibir chats.'}
              </p>
              {user?.role === 'admin' && (
                <button
                  onClick={() => navigate('/integraciones')}
                  className="inline-flex items-center gap-1.5 text-xs font-medium px-3 py-1.5 rounded-full bg-green-600 text-white hover:bg-green-700 transition-colors"
                >
                  <Link2 size={12} />
                  Ir a Integraciones
                </button>
              )}
            </div>
          ) : filteredConvs.length === 0 ? (
            // Empty state contextual al filtro activo. El de Favoritos es
            // mas elaborado (estilo WhatsApp Web) con CTA para abrir el
            // dialog. El resto sigue siendo simple.
            quickFilter === 'favorites' && favorites.size === 0 && !search ? (
              <div className="px-6 py-12 text-center">
                <div className="w-16 h-16 rounded-2xl bg-green-50 mx-auto mb-3 flex items-center justify-center">
                  <Star size={28} className="text-green-500" />
                </div>
                <div className="text-sm font-semibold text-gray-700 mb-1">
                  Anade chats a Favoritos
                </div>
                <p className="text-xs text-gray-500 mb-4 max-w-[220px] mx-auto leading-relaxed">
                  Haz que sea facil encontrar a las personas mas importantes en el CRM.
                </p>
                <button
                  onClick={() => setFavoritesDialogOpen(true)}
                  className="text-xs font-medium text-green-700 hover:text-green-800"
                >
                  Anadir a Favoritos
                </button>
              </div>
            ) : (
              <div className="p-6 text-center text-gray-400 text-sm">
                {search ? 'Sin resultados.' : 'Aun no hay chats.'}
              </div>
            )
          ) : (
            filteredConvs.map(c => {
              const listTime = formatChatListTime(c.last_message_at)
              const isFav = favorites.has(c.id)
              const menuOpen = convMenuId === c.id
              const canTake = canTakeChat(c, user)
              return (
              // V040 — fila de conversacion con menu contextual estilo
              // WhatsApp Web. Antes era un <button> simple; ahora un div
              // (role=button) que aloja el chevron como <button> real
              // adentro sin anidar buttons (HTML invalido) y sin requerir
              // stopPropagation gimnastico. group-hover muestra el chevron
              // solo al pasar el mouse — limpio en idle, accionable en hover.
              <div
                key={c.id}
                role="button"
                tabIndex={0}
                onClick={() => setSelectedId(c.id)}
                onKeyDown={e => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    setSelectedId(c.id)
                  }
                }}
                className={`group relative w-full text-left px-3 py-3 border-b border-gray-100 flex gap-3 transition-colors cursor-pointer
                  ${selectedId === c.id ? 'bg-gray-100' : 'hover:bg-gray-50'}`}
              >
                <div className="w-11 h-11 rounded-full bg-gradient-to-br from-green-400 to-emerald-600 text-white flex items-center justify-center font-semibold shrink-0 shadow-sm">
                  {(c.contact_name || c.lead_name || c.wa_phone || '?')[0].toUpperCase()}
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-semibold text-gray-900 truncate inline-flex items-center gap-1">
                      {isFav && (
                        <Star size={11} className="text-amber-500 fill-amber-500 shrink-0" />
                      )}
                      {c.contact_name || c.lead_name || c.wa_phone}
                    </span>
                    <span className={`text-[11px] shrink-0 ${c.unread_count > 0 ? 'text-green-600 font-semibold' : 'text-gray-400'}`}>
                      {listTime}
                    </span>
                  </div>
                  {/* Cuando hay mensajes nuevos sin leer, prioriza el ultimo
                      mensaje (lo que el cliente acaba de escribir). Cuando el
                      chat esta "calmo" (todo leido), muestra el resumen IA
                      como contexto. Asi un cliente que vuelve a escribir tras
                      la clasificacion sigue siendo visible en la lista. */}
                  <div className="flex items-center justify-between gap-2 mt-0.5">
                    <p className={`text-xs truncate flex-1 min-w-0 ${
                      c.unread_count > 0 ? 'text-gray-900 font-medium' : 'text-gray-500'
                    }`}>
                      {c.unread_count > 0
                        ? (c.last_message_preview || c.classification_summary || '—')
                        : (c.classification_summary || c.last_message_preview || '—')}
                    </p>
                    {c.unread_count > 0 && (
                      <span className="shrink-0 bg-green-500 text-white text-[10px] font-bold px-1.5 min-w-[20px] h-5 rounded-full flex items-center justify-center leading-none shadow-sm">
                        {c.unread_count > 99 ? '99+' : c.unread_count}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-1.5 mt-1 flex-nowrap overflow-hidden">
                    <ClassifyChip conv={c} compact labelsMap={labelsMap} />
                    {c.classification_urgency === 'alta' && (() => {
                      const UrgIcon = CHIP_ICONS[urgencyLabel.icon_name] || Flame
                      return (
                        <span
                          className="inline-flex items-center gap-0.5 text-[9px] px-1.5 py-0.5 rounded-full border font-medium shrink-0"
                          style={{
                            backgroundColor: urgencyLabel.color_hex + '22',
                            color: urgencyLabel.color_hex,
                            borderColor: urgencyLabel.color_hex + '55',
                          }}
                        >
                          <UrgIcon size={8} /> {urgencyLabel.label}
                        </span>
                      )
                    })()}
                    {c.tags && c.tags.length > 0 && c.tags.slice(0, 1).map(t => (
                      <span
                        key={t.id}
                        className="inline-flex items-center gap-0.5 text-[9px] leading-none px-1.5 py-0.5 rounded-full border font-medium max-w-[90px] truncate shrink-0"
                        style={{
                          backgroundColor: t.color_hex + '22',
                          color: t.color_hex,
                          borderColor: t.color_hex + '55',
                        }}
                        title={c.tags.map(x => x.nombre).join(', ')}
                      >
                        <Tag size={8} className="shrink-0" />
                        <span className="truncate">{t.nombre}</span>
                      </span>
                    ))}
                    {c.tags && c.tags.length > 1 && (
                      <span className="text-[9px] text-gray-400 font-medium shrink-0">
                        +{c.tags.length - 1}
                      </span>
                    )}
                    {(c.meta_ad_name || c.wa_campaign_headline || c.campaign_name) && (
                      <span className="text-[10px] text-indigo-600 truncate flex items-center gap-1 min-w-0">
                        <Megaphone size={9} className="shrink-0" />
                        <span className="truncate">
                          {c.meta_ad_name || c.wa_campaign_headline || c.campaign_name}
                        </span>
                      </span>
                    )}
                    {c.wa_number_name && waNumbers.length > 1 && (
                      <span
                        className="text-[10px] text-purple-700 bg-purple-50 border border-purple-200 truncate flex items-center gap-1 min-w-0 px-1.5 py-0.5 rounded-full shrink-0"
                        title={c.wa_number_phone ? `+${c.wa_number_phone}` : c.wa_number_name}
                      >
                        <Phone size={8} className="shrink-0" />
                        <span className="truncate">{c.wa_number_name}</span>
                      </span>
                    )}
                  </div>
                </div>

                {/* Chevron desplegable estilo WhatsApp Web — visible en
                    hover o si el menu esta abierto. Se posiciona absolute
                    arriba-derecha sin alterar el layout interno de la fila.
                    e.stopPropagation evita que el click sobre el chevron
                    abra la conversacion. */}
                {/* Chevron — vive en el ultimo renglon de la card (abajo
                    a la derecha) para que NUNCA tape la hora (renglon 1)
                    ni el preview / resumen IA (renglon 2). Asi el usuario
                    siempre ve los datos importantes intactos en hover.
                    Solo visible en hover; al abrir el menu queda fijo. */}
                <button
                  type="button"
                  /* V041.2: stopPropagation EN onMouseDown ademas del onClick.
                     El listener global de "click fuera" escucha mousedown
                     (que dispara antes que click). Sin esto, el segundo
                     click del chevron primero cerraba el menu (mousedown →
                     listener) y luego el onClick lo reabria — el toggle
                     parecia roto. */
                  onMouseDown={e => e.stopPropagation()}
                  onClick={e => {
                    e.stopPropagation()
                    if (menuOpen) {
                      setConvMenuId(null)
                      return
                    }
                    // V041.2: la altura del menu cambia con el contenido.
                    // Calculamos el espacio respecto al SCROLL CONTAINER
                    // de la lista (el div con overflow-y:auto), no respecto
                    // a la ventana — el clipping real lo hace el container.
                    // Si no hay margen suficiente arriba, abrimos hacia abajo.
                    const btn = e.currentTarget
                    let scrollEl = btn.parentElement
                    while (scrollEl) {
                      const cs = getComputedStyle(scrollEl)
                      if (cs.overflowY === 'auto' || cs.overflowY === 'scroll') break
                      scrollEl = scrollEl.parentElement
                    }
                    const btnRect = btn.getBoundingClientRect()
                    const containerTop = scrollEl ? scrollEl.getBoundingClientRect().top : 0
                    const containerBottom = scrollEl ? scrollEl.getBoundingClientRect().bottom : window.innerHeight
                    const ESTIMATED_MENU_HEIGHT = 220
                    const spaceAbove = btnRect.top - containerTop
                    const spaceBelow = containerBottom - btnRect.bottom
                    const dir = spaceAbove < ESTIMATED_MENU_HEIGHT && spaceBelow > spaceAbove
                      ? 'down'
                      : 'up'
                    setConvMenuDir(dir)
                    setConvMenuId(c.id)
                  }}
                  className={`absolute bottom-2 right-2 w-6 h-6 rounded-full flex items-center justify-center transition-all
                    ${menuOpen
                      ? 'bg-gray-200 text-gray-700 opacity-100'
                      : 'bg-white/95 backdrop-blur-sm text-gray-500 opacity-0 group-hover:opacity-100 hover:bg-gray-200 hover:text-gray-700 shadow-sm'}`}
                  title="Más opciones"
                  aria-label="Más opciones de la conversación"
                >
                  <ChevronDown size={14} />
                </button>

                {menuOpen && (
                  <div
                    ref={convMenuRef}
                    /* V041.1: posicion adaptativa. La primera conversacion
                       (poco espacio arriba del chevron) abre HACIA ABAJO
                       (top-full mt-1) — antes quedaba cortada por el tope
                       del scroll container. Las conversaciones lejos del
                       tope siguen abriendo HACIA ARRIBA (bottom-9) que es
                       el patron natural cuando el chevron esta abajo. */
                    className={`absolute right-2 z-50 w-56 bg-white ring-1 ring-black/10 rounded-xl shadow-[0_25px_60px_-15px_rgba(15,23,42,0.4)] overflow-hidden animate-in fade-in zoom-in-95 duration-100 ${
                      convMenuDir === 'down' ? 'top-full mt-1' : 'bottom-9'
                    }`}
                    onClick={e => e.stopPropagation()}
                  >
                    {c.unread_count > 0 && (
                      <button
                        type="button"
                        onClick={e => {
                          e.stopPropagation()
                          // Optimistic: zero local + PATCH al backend.
                          setConversations(prev => prev.map(x =>
                            x.id === c.id ? { ...x, unread_count: 0 } : x
                          ))
                          api.patch(`/api/whatsapp/conversations/${c.id}/read`)
                            .then(() => window.dispatchEvent(new CustomEvent('chat:unread-changed')))
                            .catch(() => {})
                          setConvMenuId(null)
                        }}
                        className="w-full text-left px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-2"
                      >
                        <span className="w-2 h-2 rounded-full bg-green-500 shrink-0" />
                        Marcar como leído
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={e => {
                        e.stopPropagation()
                        toggleFavorite(c.id)
                        setConvMenuId(null)
                      }}
                      className="w-full text-left px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-2"
                    >
                      <Star size={14} className={isFav ? 'text-amber-500 fill-amber-500' : 'text-gray-500'} />
                      {isFav ? 'Quitar de Favoritos' : 'Añadir a Favoritos'}
                    </button>
                    {c.lead_id && (
                      <button
                        type="button"
                        onClick={e => {
                          e.stopPropagation()
                          setConvMenuId(null)
                          navigate(`/leads/${c.lead_id}`)
                        }}
                        className="w-full text-left px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-2"
                      >
                        <ExternalLink size={14} className="text-gray-500" />
                        Abrir lead
                      </button>
                    )}
                    {canTake && (
                      <button
                        type="button"
                        onClick={e => {
                          e.stopPropagation()
                          setSelectedId(c.id)
                          setConvMenuId(null)
                          // pequeño delay para que selectedConv quede sincronizado
                          // antes de disparar handleTake (que lee selectedConv).
                          setTimeout(() => handleTake(), 0)
                        }}
                        className="w-full text-left px-3 py-2 text-sm text-emerald-700 hover:bg-emerald-50 flex items-center gap-2"
                      >
                        <UserCheck size={14} />
                        Tomar este chat
                      </button>
                    )}
                    {c.lead_id && (
                      <button
                        type="button"
                        onClick={e => {
                          e.stopPropagation()
                          setSelectedId(c.id)
                          setConvMenuId(null)
                          setShowNewCase(true)
                        }}
                        className="w-full text-left px-3 py-2 text-sm text-violet-700 hover:bg-violet-50 flex items-center gap-2"
                      >
                        <FilePlus size={14} />
                        Nueva consulta
                      </button>
                    )}
                    {canReclassify && c.classification_status !== 'archived' && (
                      <>
                        <div className="border-t border-gray-100" />
                        <button
                          type="button"
                          onClick={e => {
                            e.stopPropagation()
                            setSelectedId(c.id)
                            setConvMenuId(null)
                            setShowArchive(true)
                          }}
                          className="w-full text-left px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 flex items-center gap-2"
                        >
                          <Archive size={14} className="text-slate-500" />
                          Archivar conversación
                        </button>
                      </>
                    )}
                  </div>
                )}
              </div>
              )
            })
          )}
        </div>
      </aside>

      {/* Main — conversacion */}
      <main className="flex-1 flex flex-col">
        {!selectedConv ? (
          // Empty state estilo WhatsApp Web: ilustracion minimalista,
          // sin texto intrusivo. La marca (logo MessageCircle) actua como
          // el "wallpaper" del panel; el footer recuerda el cifrado/encrypted
          // como hace WhatsApp para reforzar confianza.
          <div className="flex-1 flex flex-col items-center justify-center bg-gray-50/40 border-l border-gray-200 relative">
            <div className="flex flex-col items-center text-center max-w-md px-8">
              <div className="w-44 h-44 rounded-full bg-gradient-to-br from-emerald-50 to-emerald-100/40 flex items-center justify-center mb-6">
                <MessageCircle size={88} strokeWidth={1.2} className="text-emerald-300" />
              </div>
              <h2 className="text-[28px] font-light text-gray-700 tracking-tight">
                {brand?.company_name || 'CRM'}
              </h2>
              <p className="text-sm text-gray-500 mt-2 leading-relaxed">
                Conversaciones de WhatsApp Business sincronizadas en tiempo real.
                Selecciona un chat para empezar.
              </p>
            </div>
            <div className="absolute bottom-6 inset-x-0 flex items-center justify-center gap-1.5 text-[11px] text-gray-400">
              <ShieldAlert size={11} />
              Mensajes y llamadas estan cifrados de extremo a extremo
            </div>
          </div>
        ) : (
          <>
            {/* Header del chat — V040: layout en 2 filas para que la
                metadata (clasificacion + tags) tenga ancho completo y
                no quede comprimida bajo el nombre. Antes las acciones
                (Archivar / Nueva consulta / etc) se llevaban la mitad
                del ancho horizontal y los chips se cortaban a mitad
                ("Promocio...") aunque sobrara espacio. Patron patrón premium /
                patrón premium / herramienta premium: identidad + acciones arriba, metadata
                a ancho completo abajo. */}
            <div className="px-4 py-2.5 border-b border-gray-200 bg-white flex flex-col gap-2">
              {/* Fila 1: identidad (avatar + nombre/telefono) | acciones */}
              <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3 min-w-0 flex-1">
                <div className="w-9 h-9 rounded-full bg-green-100 text-green-700 flex items-center justify-center font-semibold shrink-0">
                  {(selectedConv.contact_name || selectedConv.lead_name || selectedConv.wa_phone)[0].toUpperCase()}
                </div>
                <div className="min-w-0">
                  <p className="text-sm font-semibold text-gray-900 truncate">
                    {selectedConv.contact_name || selectedConv.lead_name || selectedConv.wa_phone}
                  </p>
                  <p className="text-xs text-gray-400 truncate">+{selectedConv.wa_phone}</p>
                </div>
              </div>
              <div className="flex items-center gap-2 shrink-0 relative">
                {selectedConv.cases_count > 1 && (
                  <button
                    onClick={() => {
                      const next = !showCases
                      setShowCases(next)
                      if (next) loadCases(selectedId)
                    }}
                    className="inline-flex items-center gap-1 text-xs bg-violet-50 hover:bg-violet-100 border border-violet-200 text-violet-700 px-2 py-1 rounded-md transition-colors"
                    title={`${selectedConv.cases_count} casos historicos en este chat`}
                  >
                    <Layers size={12} />
                    Caso {selectedConv.cases_count}
                  </button>
                )}
                {/* V040 — el badge de asignacion ahora SIEMPRE se muestra,
                    incluso si la conv esta sin asignar o es del usuario
                    actual. Saber quien gestiona el lead es info critica
                    para coordinar al equipo. Antes solo aparecia cuando
                    asesor_id era de otro usuario. */}
                {(() => {
                  const isMine = selectedConv.asesor_id === user?.user_id
                  const unassigned = !selectedConv.asesor_id
                  const isSupervisor = selectedConv.asesor_role === 'supervisor'
                  const label = unassigned
                    ? 'Sin asignar'
                    : isMine
                      ? 'Asignado a mí'
                      : `${isSupervisor ? 'Supervisor: ' : 'Asignado: '}${selectedConv.asesor_nombre || '—'}`
                  const cls = unassigned
                    ? 'bg-amber-50 border-amber-200 text-amber-700'
                    : isMine
                      ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
                      : 'bg-slate-100 border-slate-200 text-slate-700'
                  const title = unassigned
                    ? 'Conversación sin asesor asignado'
                    : isMine
                      ? 'Esta conversación es tuya'
                      : isSupervisor
                        ? 'Asignado a supervisor — pendiente de delegar'
                        : 'Asignado a otro asesor'
                  return (
                    <span className={`text-xs border px-2 py-1 rounded-md ${cls}`} title={title}>
                      {label}
                    </span>
                  )
                })()}
                {/* V040 — los botones de accion (Tomar / Archivar /
                    Nueva consulta / Reclasificar / Desarchivar) que antes
                    vivian inline en el header se movieron al menu kebab
                    de mas abajo. La fila ahora queda mas limpia: solo
                    info contextual (Caso N, Asignado, Fuera de ventana)
                    + favorito + kebab. Las acciones siguen accesibles
                    con un click extra y ademas estan replicadas en el
                    menu chevron por conversacion en la lista. */}
                {!windowOpen && (
                  <span
                    className="text-xs bg-amber-50 border border-amber-200 text-amber-700 px-2 py-1 rounded-md cursor-help"
                    title="Pasaron más de 24h desde el último mensaje del cliente — solo se pueden enviar plantillas (templates) aprobadas por Meta."
                  >
                    Fuera de ventana 24h
                  </span>
                )}

                {/* Toggle Favorito — estilo WhatsApp Web. Boton siempre
                    visible junto al kebab; estado claro (relleno amarillo
                    si fav, outline gris si no). Solo aparece con un chat
                    seleccionado, asi no genera ruido visual. */}
                {selectedConv && (() => {
                  const isFav = favorites.has(selectedConv.id)
                  return (
                    <button
                      onClick={() => toggleFavorite(selectedConv.id)}
                      className="w-8 h-8 flex items-center justify-center rounded-full text-gray-500 hover:bg-gray-100 transition-colors"
                      title={isFav ? 'Quitar de Favoritos' : 'Anadir a Favoritos'}
                      aria-label={isFav ? 'Quitar de Favoritos' : 'Anadir a Favoritos'}
                      aria-pressed={isFav}
                    >
                      <Star
                        size={18}
                        className={isFav ? 'text-amber-500 fill-amber-500' : 'text-gray-500'}
                      />
                    </button>
                  )
                })()}

                {/* Menu kebab (3 puntos) — estilo WhatsApp Web. De aqui se abre "Info del contacto". */}
                <div ref={headerMenuRef} className="relative">
                  <button
                    onClick={() => setHeaderMenuOpen(v => !v)}
                    className="w-8 h-8 flex items-center justify-center rounded-full text-gray-500 hover:bg-gray-100 transition-colors"
                    title="Mas opciones"
                    aria-label="Mas opciones"
                  >
                    <MoreVertical size={18} />
                  </button>
                  {headerMenuOpen && (
                    <div className="absolute right-0 top-full mt-1 z-30 w-60 bg-white border border-gray-200 rounded-xl shadow-[0_20px_50px_-12px_rgba(15,23,42,0.25)] overflow-hidden animate-in fade-in zoom-in-95 duration-100">
                      <button
                        onClick={() => {
                          setContactPanelTab('files')
                          setShowContactPanel(true)
                          setHeaderMenuOpen(false)
                        }}
                        className="w-full text-left px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-2"
                      >
                        <Info size={14} className="text-gray-500" />
                        Info del contacto
                      </button>
                      {canTakeChat(selectedConv, user) && (
                        <button
                          onClick={() => { setHeaderMenuOpen(false); handleTake() }}
                          disabled={taking}
                          className="w-full text-left px-3 py-2 text-sm text-emerald-700 hover:bg-emerald-50 flex items-center gap-2 disabled:opacity-50"
                        >
                          <UserCheck size={14} />
                          {taking ? 'Tomando…' : 'Tomar este chat'}
                        </button>
                      )}
                      {selectedConv.lead_id && (
                        <button
                          onClick={() => { setHeaderMenuOpen(false); setShowNewCase(true) }}
                          className="w-full text-left px-3 py-2 text-sm text-violet-700 hover:bg-violet-50 flex items-center gap-2"
                        >
                          <FilePlus size={14} />
                          Nueva consulta
                        </button>
                      )}
                      {canReclassify && !selectedConv.lead_id && selectedConv.classification_status !== 'archived' && (
                        <button
                          onClick={() => { setHeaderMenuOpen(false); handleReclassify() }}
                          disabled={reclassifying}
                          className="w-full text-left px-3 py-2 text-sm text-sky-700 hover:bg-sky-50 flex items-center gap-2 disabled:opacity-50"
                        >
                          <Wand2 size={14} />
                          {reclassifying ? 'Encolando…' : 'Reclasificar'}
                        </button>
                      )}
                      {canReclassify && selectedConv.classification_status === 'archived' && (
                        <button
                          onClick={() => { setHeaderMenuOpen(false); handleReclassify() }}
                          disabled={reclassifying}
                          className="w-full text-left px-3 py-2 text-sm text-amber-700 hover:bg-amber-50 flex items-center gap-2 disabled:opacity-50"
                        >
                          <RefreshCw size={14} />
                          {reclassifying ? 'Encolando…' : 'Desarchivar'}
                        </button>
                      )}
                      {canReclassify && selectedConv.classification_status !== 'archived' && (
                        <>
                          <div className="border-t border-gray-100" />
                          <button
                            onClick={() => { setHeaderMenuOpen(false); setShowArchive(true) }}
                            className="w-full text-left px-3 py-2 text-sm text-slate-700 hover:bg-slate-50 flex items-center gap-2"
                          >
                            <Archive size={14} className="text-slate-500" />
                            Archivar conversación
                          </button>
                        </>
                      )}
                    </div>
                  )}
                </div>

                {showCases && (
                  <div className="absolute right-0 top-full mt-2 w-80 bg-white border border-gray-200 rounded-lg shadow-lg z-20 overflow-hidden">
                    <div className="px-3 py-2 border-b border-gray-100 bg-gray-50 flex items-center justify-between">
                      <span className="text-xs font-semibold text-gray-700">
                        Historial de casos
                      </span>
                      <button
                        onClick={() => setShowCases(false)}
                        className="text-gray-400 hover:text-gray-600 text-xs"
                      >
                        Cerrar
                      </button>
                    </div>
                    <div className="max-h-72 overflow-y-auto">
                      {loadingCases ? (
                        <div className="py-4"><LoadingSpinner /></div>
                      ) : cases.length === 0 ? (
                        <p className="p-4 text-xs text-gray-400 text-center">Sin casos.</p>
                      ) : (
                        cases.map((cs, idx) => (
                          <div
                            key={cs.id}
                            className={`px-3 py-2 border-b border-gray-100 text-xs ${
                              cs.closed_at == null ? 'bg-emerald-50/40' : ''
                            }`}
                          >
                            <div className="flex items-center justify-between gap-2">
                              <span className="font-semibold text-gray-800 truncate">
                                #{cases.length - idx} {cs.lead_name || `Lead ${cs.lead_id}`}
                              </span>
                              {cs.closed_at == null && (
                                <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-emerald-100 text-emerald-700 border border-emerald-200 font-medium shrink-0">
                                  Activo
                                </span>
                              )}
                            </div>
                            <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                              {cs.estado && (
                                <span
                                  className="text-[10px] px-1.5 py-0.5 rounded-full font-medium border"
                                  style={{
                                    backgroundColor: cs.estado_color ? `${cs.estado_color}22` : undefined,
                                    color: cs.estado_color || undefined,
                                    borderColor: cs.estado_color ? `${cs.estado_color}55` : undefined,
                                  }}
                                >
                                  {cs.estado}
                                </span>
                              )}
                              {cs.campana && (
                                <span className="text-[10px] text-indigo-600 truncate">
                                  {cs.campana}
                                </span>
                              )}
                            </div>
                            <p className="text-[10px] text-gray-500 mt-1">
                              Abierto: {new Date(cs.opened_at).toLocaleString('es-PE', {
                                day: '2-digit', month: '2-digit', year: '2-digit',
                                hour: '2-digit', minute: '2-digit',
                              })}
                              {cs.closed_at && (
                                <> · Cerrado: {new Date(cs.closed_at).toLocaleString('es-PE', {
                                  day: '2-digit', month: '2-digit', year: '2-digit',
                                })}</>
                              )}
                            </p>
                            {cs.asesor_nombre && (
                              <p className="text-[10px] text-gray-500">Asesor: {cs.asesor_nombre}</p>
                            )}
                            {cs.reason && (
                              <p className="text-[10px] text-gray-600 italic mt-0.5">"{cs.reason}"</p>
                            )}
                          </div>
                        ))
                      )}
                    </div>
                  </div>
                )}
              </div>
              </div>
              {/* Fila 2 — metadata a ancho completo: chips de
                  clasificacion (auto) + separador sutil + etiquetas
                  manuales + boton "Agregar etiqueta". Patron patrón premium /
                  patrón premium / herramienta premium. Scroll horizontal si excede; el header
                  no crece en altura ni recorta texto. pl-12 alinea
                  el contenido con el inicio del nombre (avatar + gap). */}
              <div className="flex items-center gap-1.5 overflow-x-auto no-scrollbar pl-12">
                  {selectedConv.wa_number_name && waNumbers.length > 1 && (
                    <span
                      className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-purple-50 text-purple-700 border border-purple-200 font-medium shrink-0 whitespace-nowrap"
                      title={selectedConv.wa_number_phone ? `Linea: +${selectedConv.wa_number_phone}` : `Linea: ${selectedConv.wa_number_name}`}
                    >
                      <Phone size={10} />
                      {selectedConv.wa_number_name}
                    </span>
                  )}
                  <div className="shrink-0"><ClassifyChip conv={selectedConv} labelsMap={labelsMap} /></div>
                  {selectedConv.classification_interest && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full border bg-slate-50 text-slate-700 border-slate-200 font-medium shrink-0 whitespace-nowrap">
                      {selectedConv.classification_interest}
                    </span>
                  )}
                  {selectedConv.classification_urgency === 'alta' && (() => {
                    const UrgIcon = CHIP_ICONS[urgencyLabel.icon_name] || Flame
                    return (
                      <span
                        className="inline-flex items-center gap-0.5 text-[10px] px-2 py-0.5 rounded-full border font-medium shrink-0 whitespace-nowrap"
                        style={{
                          backgroundColor: urgencyLabel.color_hex + '22',
                          color: urgencyLabel.color_hex,
                          borderColor: urgencyLabel.color_hex + '55',
                        }}
                      >
                        <UrgIcon size={10} /> {urgencyLabel.label}
                      </span>
                    )
                  })()}
                  {selectedConv.classification_confidence != null && (
                    <span className="text-[10px] text-gray-400 shrink-0 whitespace-nowrap">
                      conf {Math.round(selectedConv.classification_confidence * 100)}%
                    </span>
                  )}
                  {(selectedConv.meta_ad_name ||
                    selectedConv.meta_campaign_name ||
                    selectedConv.meta_creative_body ||
                    selectedConv.wa_campaign_headline ||
                    selectedConv.campaign_name) && (() => {
                    const label =
                      selectedConv.meta_ad_name ||
                      selectedConv.wa_campaign_headline ||
                      selectedConv.campaign_name
                    const isBoosted =
                      !!selectedConv.meta_ad_name &&
                      !selectedConv.meta_adset_name &&
                      !selectedConv.meta_campaign_name &&
                      !selectedConv.meta_creative_body
                    return (
                      <button
                        type="button"
                        onClick={() => {
                          setContactPanelTab('info')
                          setShowContactPanel(true)
                        }}
                        className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-200 hover:bg-indigo-100 transition-colors shrink-0 whitespace-nowrap max-w-[320px]"
                        title={isBoosted
                          ? `Promocion de pagina — ${label}`
                          : `Anuncio — ${label}`}
                      >
                        <Megaphone size={10} className="shrink-0" />
                        <span className="truncate">
                          {isBoosted ? 'Promocion' : 'Anuncio'}: {label}
                        </span>
                      </button>
                    )
                  })()}
                  {/* Separador sutil entre chips de sistema y etiquetas
                      manuales del usuario — gesto patrón premium / patrón premium. */}
                  {leadTags.length > 0 && (
                    <span className="w-px h-4 bg-gray-200 mx-1 shrink-0" aria-hidden="true" />
                  )}
                  {leadTags.map(t => (
                    <span
                      key={t.id}
                      className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full border font-medium group shrink-0 whitespace-nowrap"
                      style={{
                        backgroundColor: t.color_hex + '22',
                        color: t.color_hex,
                        borderColor: t.color_hex + '55',
                      }}
                    >
                      <Tag size={9} /> {t.nombre}
                      <button
                        onClick={() => handleRemoveTag(t.id)}
                        disabled={tagMutating === t.id}
                        className="ml-0.5 opacity-40 hover:opacity-100 disabled:opacity-20"
                        title="Quitar etiqueta"
                      >
                        <X size={9} />
                      </button>
                    </span>
                  ))}
                  {/* Wrapper relative para que el picker se ancle al
                      boton +Agregar etiqueta y no al contenedor de la
                      fila completa (asi el dropdown sale debajo del
                      boton, no del extremo izquierdo). */}
                  <div className="relative shrink-0">
                    <button
                      onClick={() => setShowTagPicker(v => !v)}
                      className="inline-flex items-center gap-1 text-[10px] px-1.5 py-0.5 rounded-full border border-dashed border-gray-300 text-gray-500 hover:bg-gray-50 hover:border-gray-400 whitespace-nowrap"
                      title="Agregar etiqueta"
                    >
                      <Plus size={10} /> {leadTags.length === 0 ? 'Agregar etiqueta' : 'Etiqueta'}
                    </button>
                    {showTagPicker && (
                      <div className="absolute left-0 top-full mt-1 z-30 bg-white border border-gray-200 rounded-lg shadow-lg w-64 max-h-60 overflow-y-auto">
                        <div className="px-3 py-2 border-b border-gray-100 bg-gray-50 text-[11px] font-semibold text-gray-700 flex items-center justify-between">
                          <span>Etiquetas disponibles</span>
                          <button onClick={() => setShowTagPicker(false)} className="text-gray-400 hover:text-gray-600">
                            <X size={11} />
                          </button>
                        </div>
                        {tagCatalog.filter(t => !leadTags.some(lt => lt.id === t.id)).length === 0 ? (
                          <p className="p-3 text-[11px] text-gray-400 text-center">
                            No hay mas etiquetas. Crea nuevas en Configuracion &gt; Etiquetas.
                          </p>
                        ) : (
                          tagCatalog.filter(t => !leadTags.some(lt => lt.id === t.id)).map(t => (
                            <button
                              key={t.id}
                              onClick={() => handleAddTag(t.id)}
                              disabled={tagMutating === t.id}
                              className="w-full text-left px-3 py-1.5 hover:bg-gray-50 flex items-center gap-2 disabled:opacity-50"
                            >
                              <span
                                className="inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full border font-medium"
                                style={{
                                  backgroundColor: t.color_hex + '22',
                                  color: t.color_hex,
                                  borderColor: t.color_hex + '55',
                                }}
                              >
                                <Tag size={9} /> {t.nombre}
                              </span>
                              {t.descripcion && (
                                <span className="text-[10px] text-gray-400 truncate">{t.descripcion}</span>
                              )}
                            </button>
                          ))
                        )}
                      </div>
                    )}
                  </div>
                </div>
            </div>

            {/* Banner con resumen IA (si existe y es clasificado) */}
            {selectedConv.classification_summary && selectedConv.classification_status === 'classified' && (
              <div className="mx-4 mt-3 p-2.5 bg-sky-50 border border-sky-200 rounded-lg flex gap-2 items-start">
                <Sparkles size={14} className="text-sky-600 mt-0.5 shrink-0" />
                <p className="text-xs text-sky-900">
                  <span className="font-semibold">Resumen IA:</span> {selectedConv.classification_summary}
                </p>
              </div>
            )}

            {/* Mensajes — fondo estilo WhatsApp Web con doodles sutiles. */}
            <div
              ref={messagesContainerRef}
              onScroll={handleMessagesScroll}
              className="flex-1 overflow-y-auto wa-scrollbar px-4 py-4 space-y-1.5"
              style={{
                backgroundColor: '#efeae2',
                backgroundImage:
                  "url(\"data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='140' height='140' viewBox='0 0 140 140'><g fill='none' stroke='%23d4ccbf' stroke-width='1' opacity='0.35'><circle cx='20' cy='20' r='3'/><circle cx='110' cy='30' r='2'/><path d='M50 60 Q60 50 70 60 T90 60' /><path d='M20 100 Q35 90 50 100 T80 100'/><circle cx='120' cy='110' r='4'/><path d='M95 15 l8 8 M103 15 l-8 8' stroke-width='1.2'/></g></svg>\")",
              }}
            >
              {loadingMsgs ? (
                <LoadingSpinner />
              ) : messages.length === 0 ? (
                <p className="text-center text-gray-400 text-sm py-8">Sin mensajes aun.</p>
              ) : (
                (() => {
                  let lastDay = null
                  return messages.map(m => {
                    const isInbound = m.direction === 'inbound'
                    const phishLevel = isInbound && m.risk_flags?.is_phishing ? m.risk_flags.level : null
                    const phishBorder = phishLevel === 'high'
                      ? 'border-red-400 ring-1 ring-red-200'
                      : phishLevel === 'medium'
                        ? 'border-amber-400 ring-1 ring-amber-200'
                        : 'border-transparent'
                    // Separador de dia: chip centrado cuando cambia el dia
                    const dayKey = new Date(m.timestamp).toDateString()
                    const showDayDivider = dayKey !== lastDay
                    lastDay = dayKey
                    return (
                      <div key={m.id}>
                        {showDayDivider && (
                          <div className="flex justify-center my-3">
                            <span className="text-[11px] font-medium text-gray-600 bg-white/85 px-3 py-1 rounded-lg shadow-sm backdrop-blur-sm tracking-wide">
                              {formatMessageDay(m.timestamp)}
                            </span>
                          </div>
                        )}
                        <div className={`flex ${m.direction === 'outbound' ? 'justify-end' : 'justify-start'}`}>
                          <div
                            className={`max-w-[72%] px-2.5 py-1.5 shadow-sm text-sm relative
                              ${m.direction === 'outbound'
                                ? 'bg-[#d9fdd3] text-gray-800 rounded-lg rounded-tr-[3px]'
                                : `bg-white text-gray-800 rounded-lg rounded-tl-[3px] border ${phishBorder}`}`}
                          >
                            {isInbound && <PhishingBadge flags={m.risk_flags} />}
                            {isInbound && m.payload?.referral && (
                              <CTWAReferralCard
                                referral={m.payload.referral}
                                thumbnailUrl={convThumb.url}
                                mediaType={selectedConv?.meta_creative_media_type}
                              />
                            )}
                            <MediaBubble msg={m} />
                            <p className="text-[10px] text-gray-500 text-right mt-0.5 -mb-0.5 flex items-center justify-end gap-1 select-none">
                              <span>
                                {new Date(m.timestamp).toLocaleTimeString('es-PE', {
                                  hour: '2-digit', minute: '2-digit', hour12: false,
                                })}
                              </span>
                              {m.direction === 'outbound' && (
                                <MessageStatus
                                  status={m.status}
                                  errorCode={m.error_code}
                                  errorDetail={m.error_detail}
                                />
                              )}
                            </p>
                          </div>
                        </div>
                      </div>
                    )
                  })
                })()
              )}
              <div ref={messagesEndRef} />
            </div>

            {/* Input — texto libre dentro de ventana 24h, plantilla aprobada fuera. */}
            {windowOpen ? (
              <div className="p-3 border-t border-gray-200 bg-white flex gap-2">
                <input
                  type="text"
                  value={draft}
                  onChange={e => setDraft(e.target.value)}
                  onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }}
                  placeholder="Escribe un mensaje..."
                  disabled={sending}
                  className="flex-1 h-10 px-3 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-green-500 disabled:bg-gray-50 disabled:text-gray-400"
                />
                <button
                  onClick={handleSend}
                  disabled={!draft.trim() || sending}
                  className="w-10 h-10 flex items-center justify-center rounded-lg bg-green-600 hover:bg-green-500 disabled:opacity-40 text-white transition-colors"
                >
                  <Send size={16} />
                </button>
              </div>
            ) : (
              <div className="p-3 border-t border-gray-200 bg-white">
                <button
                  onClick={openTemplatesModal}
                  className="w-full h-10 flex items-center justify-center gap-2 rounded-lg bg-green-600 hover:bg-green-500 text-white text-sm font-medium transition-colors"
                >
                  <FilePlus size={16} />
                  Enviar plantilla aprobada
                </button>
                <p className="text-[11px] text-gray-500 text-center mt-1.5">
                  Fuera de ventana 24h — solo plantillas aprobadas por Meta.
                </p>
              </div>
            )}
          </>
        )}
      </main>

      {/* Panel lateral "Info del contacto" — archivos, enlaces, info. Estilo WhatsApp Web.
          Se abre desde el menu kebab (3 puntos) del header del chat. Convive con <main>
          como hermano flex para que no tape la conversacion. */}
      {showContactPanel && selectedConv && (
        <ContactInfoPanel
          conv={selectedConv}
          onClose={() => setShowContactPanel(false)}
          leadTags={leadTags}
          waNumbers={waNumbers}
          initialTab={contactPanelTab}
        />
      )}

      {/* Modal — Plantillas aprobadas (envio fuera de ventana 24h).
          Dos pasos: 1) elegir template, 2) llenar variables y previsualizar. */}
      <Dialog open={showTemplates} onClose={() => !sendingTemplate && setShowTemplates(false)} size="lg">
        <DialogHeader onClose={() => !sendingTemplate && setShowTemplates(false)}>
          {selectedTemplate ? selectedTemplate.name : 'Elegir plantilla'}
        </DialogHeader>
        <DialogContent>
          {loadingTemplates ? (
            <div className="py-8"><LoadingSpinner /></div>
          ) : !selectedTemplate ? (
            <>
              {templates.length === 0 ? (
                <div className="py-6 space-y-3">
                  <p className="text-sm text-gray-700 text-center font-medium">
                    {templatesMeta?.message || 'No tienes plantillas aprobadas en Meta.'}
                  </p>
                  {templatesMeta?.waba_id && (
                    <p className="text-xs text-gray-500 text-center">
                      WABA consultada: <span className="font-mono">{templatesMeta.waba_id}</span>
                    </p>
                  )}
                  {templatesMeta?.reason === 'meta_error' && templatesMeta?.detail && (
                    <details className="text-xs text-gray-500">
                      <summary className="cursor-pointer hover:text-gray-700">Ver respuesta de Meta</summary>
                      <pre className="mt-2 p-2 bg-gray-50 rounded border border-gray-200 overflow-x-auto whitespace-pre-wrap">
                        {templatesMeta.detail}
                      </pre>
                    </details>
                  )}
                  {templatesMeta?.status_breakdown && (
                    <div className="text-xs text-gray-500 text-center">
                      Status encontrados:{' '}
                      {Object.entries(templatesMeta.status_breakdown)
                        .map(([k, v]) => `${k}: ${v}`)
                        .join(' · ')}
                    </div>
                  )}
                </div>
              ) : (
                <div className="space-y-2 max-h-[60vh] overflow-y-auto">
                  {templates.map(tpl => (
                    <button
                      key={tpl.id}
                      onClick={() => pickTemplate(tpl)}
                      className="w-full text-left p-3 border border-gray-200 rounded-lg hover:border-green-500 hover:bg-green-50 transition-colors"
                    >
                      <div className="flex items-center justify-between gap-2 mb-1">
                        <span className="font-medium text-sm text-gray-900">{tpl.name}</span>
                        <div className="flex items-center gap-1.5 shrink-0">
                          <span className="text-[10px] px-2 py-0.5 rounded-full bg-gray-100 text-gray-600 uppercase">
                            {tpl.category}
                          </span>
                          <span className="text-[10px] px-2 py-0.5 rounded-full bg-gray-100 text-gray-500 uppercase">
                            {tpl.language}
                          </span>
                        </div>
                      </div>
                      <p className="text-xs text-gray-600 whitespace-pre-line line-clamp-3">
                        {tpl.body}
                      </p>
                    </button>
                  ))}
                </div>
              )}
            </>
          ) : (
            <>
              <div className="mb-3 p-3 bg-[#d9fdd3] rounded-lg border border-green-200">
                <p className="text-[11px] uppercase tracking-wide text-green-700 mb-1 font-semibold">
                  Vista previa
                </p>
                <p className="text-sm text-gray-800 whitespace-pre-line">
                  {renderTemplatePreview(selectedTemplate.body, templateVars)}
                </p>
              </div>

              {templateVars.length > 0 && (
                <div className="space-y-2 mb-4">
                  <p className="text-xs font-semibold text-gray-700">
                    Variables ({templateVars.length})
                  </p>
                  {templateVars.map((v, i) => (
                    <div key={i}>
                      <label className="text-[11px] text-gray-500 block mb-1">
                        Variable {`{{${i + 1}}}`}
                      </label>
                      <input
                        type="text"
                        value={v}
                        onChange={e => {
                          const next = [...templateVars]
                          next[i] = e.target.value
                          setTemplateVars(next)
                        }}
                        placeholder={`Valor para {{${i + 1}}}`}
                        className="w-full h-9 px-3 rounded-lg border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-green-500"
                      />
                    </div>
                  ))}
                </div>
              )}

              <div className="flex items-center justify-between gap-2 pt-3 border-t border-gray-100">
                <button
                  onClick={() => { setSelectedTemplate(null); setTemplateVars([]) }}
                  disabled={sendingTemplate}
                  className="text-sm text-gray-600 hover:text-gray-800 disabled:opacity-50"
                >
                  ← Otra plantilla
                </button>
                <button
                  onClick={handleSendTemplate}
                  disabled={sendingTemplate || templateVars.some(v => !v || !v.trim())}
                  className="inline-flex items-center gap-2 px-4 h-9 rounded-lg bg-green-600 hover:bg-green-500 disabled:opacity-40 text-white text-sm font-medium transition-colors"
                >
                  <Send size={14} />
                  {sendingTemplate ? 'Enviando...' : 'Enviar plantilla'}
                </button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>

      {/* Modal — Nueva consulta (cliente vuelve por algo distinto al caso activo) */}
      {showNewCase && selectedConv && (
        <div
          className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4"
          // V5.63 — anti close-on-text-drag (mismo bug que arreglamos en
          // components/ui/dialog.jsx). Usamos onMouseDown + target===currentTarget
          // para que solo cierre si el gesto EMPEZO directo en el overlay.
          // Si arrastras texto desde un input adentro, el mousedown empezo
          // en el input (child), no en el overlay -> no cierra.
          onMouseDown={(e) => {
            if (e.target === e.currentTarget && !openingNewCase) {
              setShowNewCase(false)
            }
          }}
        >
          <div
            className="bg-white rounded-xl shadow-2xl w-full max-w-md overflow-hidden"
            onClick={e => e.stopPropagation()}
          >
            <div className="px-5 py-4 border-b border-gray-200 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-violet-100 flex items-center justify-center">
                  <FilePlus size={16} className="text-violet-700" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-gray-900">Abrir nuevo caso</h3>
                  <p className="text-xs text-gray-500">
                    {selectedConv.contact_name || selectedConv.lead_name || selectedConv.wa_phone}
                  </p>
                </div>
              </div>
              <button
                onClick={() => setShowNewCase(false)}
                disabled={openingNewCase}
                className="text-gray-400 hover:text-gray-600 p-1 rounded disabled:opacity-50"
              >
                <X size={16} />
              </button>
            </div>

            <div className="p-5 space-y-3">
              <div className="p-3 bg-amber-50 border border-amber-200 rounded-lg text-xs text-amber-900">
                <p className="font-semibold mb-0.5">Esto cerrara el caso activo</p>
                <p>
                  La IA reclasificara el chat y creara un nuevo lead via rotacion
                  de supervisor. El historial del caso anterior queda visible en
                  el chip <span className="font-semibold">Caso N</span>.
                </p>
              </div>

              <div>
                <label className="text-xs font-medium text-gray-700 block mb-1">
                  Motivo <span className="text-gray-400">(opcional)</span>
                </label>
                <textarea
                  value={newCaseReason}
                  onChange={e => setNewCaseReason(e.target.value)}
                  placeholder="Ej. Cliente compro Lote 8 y ahora pregunta por Lote 12 sector B"
                  rows={3}
                  maxLength={500}
                  className="w-full text-sm px-3 py-2 rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-violet-500 resize-none"
                />
                <p className="text-[10px] text-gray-400 mt-1 text-right">
                  {newCaseReason.length}/500
                </p>
              </div>
            </div>

            <div className="px-5 py-3 border-t border-gray-200 bg-gray-50 flex justify-end gap-2">
              <button
                onClick={() => setShowNewCase(false)}
                disabled={openingNewCase}
                className="text-sm px-3 py-1.5 rounded-lg text-gray-700 hover:bg-gray-200 disabled:opacity-50 transition-colors"
              >
                Cancelar
              </button>
              <button
                onClick={handleOpenNewCase}
                disabled={openingNewCase}
                className="inline-flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg bg-violet-600 hover:bg-violet-500 text-white disabled:opacity-50 transition-colors"
              >
                <FilePlus size={13} />
                {openingNewCase ? 'Abriendo...' : 'Abrir nuevo caso'}
              </button>
            </div>
          </div>
        </div>
      )}

      {showArchive && selectedConv && (
        <div
          className="fixed inset-0 bg-black/40 z-50 flex items-center justify-center p-4"
          // V5.63 — anti close-on-text-drag (ver dialog.jsx). onMouseDown con
          // target===currentTarget: solo cierra si el gesto empezo directo
          // en el overlay (no si arrastras texto desde un input adentro).
          onMouseDown={(e) => {
            if (e.target === e.currentTarget && !archiving) {
              setShowArchive(false)
            }
          }}
        >
          <div
            className="bg-white rounded-xl shadow-2xl w-full max-w-md overflow-hidden"
            onClick={e => e.stopPropagation()}
          >
            <div className="px-5 py-4 border-b border-gray-200 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <div className="w-8 h-8 rounded-lg bg-slate-100 flex items-center justify-center">
                  <Archive size={16} className="text-slate-700" />
                </div>
                <div>
                  <h3 className="text-sm font-semibold text-gray-900">Archivar conversacion</h3>
                  <p className="text-xs text-gray-500">
                    {selectedConv.contact_name || selectedConv.lead_name || selectedConv.wa_phone}
                  </p>
                </div>
              </div>
              <button
                onClick={() => setShowArchive(false)}
                disabled={archiving}
                className="text-gray-400 hover:text-gray-600 p-1 rounded disabled:opacity-50"
              >
                <X size={16} />
              </button>
            </div>

            <div className="p-5 space-y-3">
              <div className="p-3 bg-slate-50 border border-slate-200 rounded-lg text-xs text-slate-700">
                <p>
                  La conversacion desaparece del inbox principal. Los mensajes se
                  conservan para auditoria y puedes desarchivar en cualquier momento.
                </p>
              </div>

              <div>
                <label className="text-xs font-medium text-gray-700 block mb-1">
                  Motivo
                </label>
                <select
                  value={archiveReason}
                  onChange={e => setArchiveReason(e.target.value)}
                  className="w-full h-9 rounded-lg border border-gray-200 bg-white text-sm px-2 focus:outline-none focus:ring-2 focus:ring-slate-500"
                >
                  <option value="not_a_lead">No es lead comercial</option>
                  <option value="spam">Spam</option>
                  <option value="duplicate">Duplicado</option>
                  <option value="no_response">Sin respuesta</option>
                  <option value="other">Otro</option>
                </select>
              </div>

              <div>
                <label className="text-xs font-medium text-gray-700 block mb-1">
                  Nota <span className="text-gray-400">(opcional)</span>
                </label>
                <textarea
                  value={archiveNotes}
                  onChange={e => setArchiveNotes(e.target.value)}
                  placeholder="Ej. Cliente escribio por error, queria soporte tecnico"
                  rows={3}
                  maxLength={500}
                  className="w-full text-sm px-3 py-2 rounded-lg border border-gray-200 focus:outline-none focus:ring-2 focus:ring-slate-500 resize-none"
                />
                <p className="text-[10px] text-gray-400 mt-1 text-right">
                  {archiveNotes.length}/500
                </p>
              </div>
            </div>

            <div className="px-5 py-3 border-t border-gray-200 bg-gray-50 flex justify-end gap-2">
              <button
                onClick={() => setShowArchive(false)}
                disabled={archiving}
                className="text-sm px-3 py-1.5 rounded-lg text-gray-700 hover:bg-gray-200 disabled:opacity-50 transition-colors"
              >
                Cancelar
              </button>
              <button
                onClick={handleArchive}
                disabled={archiving || !archiveReason}
                className="inline-flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-white disabled:opacity-50 transition-colors"
              >
                <Archive size={13} />
                {archiving ? 'Archivando...' : 'Archivar'}
              </button>
            </div>
          </div>
        </div>
      )}

      {createListOpen && (
        <CreateListDialog
          open
          onClose={() => setCreateListOpen(false)}
          conversations={conversations}
          onCreate={handleCreateCustomList}
        />
      )}
      {favoritesDialogOpen && (
        <FavoritesDialog
          open
          onClose={() => setFavoritesDialogOpen(false)}
          conversations={conversations}
          currentFavorites={favorites}
          onSave={handleSaveFavorites}
        />
      )}
      <Toast
        open={!!toast}
        type={toast?.type}
        title={toast?.title}
        message={toast?.message}
        action={toast?.action}
        onClose={() => setToast(null)}
        durationMs={toast?.type === 'err' ? 6500 : 5000}
      />

      {/* V070.81 — Modal: Confirmar eliminar lista de favoritos */}
      <ConfirmDialog
        open={!!confirmDeleteList}
        variant="danger"
        title="Eliminar lista"
        confirmLabel="Sí, eliminar"
        cancelLabel="Cancelar"
        message={confirmDeleteList
          ? `Vas a eliminar la lista "${confirmDeleteList.name}". Las conversaciones NO se eliminan, solo se quita la agrupación. Esta acción no se puede deshacer.`
          : ''}
        onConfirm={() => {
          if (confirmDeleteList) handleDeleteCustomList(confirmDeleteList.id)
          setConfirmDeleteList(null)
        }}
        onCancel={() => setConfirmDeleteList(null)}
      />
    </div>
  )
}
