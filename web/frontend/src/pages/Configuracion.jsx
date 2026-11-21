import { useState, useEffect, useCallback, useRef } from 'react'
import { useSearchParams } from 'react-router-dom'
import { CheckCircle, XCircle, Loader, RefreshCw, Database, Zap, Bot, Server, Mail, Settings, Lock, Users, Eye, EyeOff, Tag, Tags, Pencil, Trash2, Plus, Check, X as XIcon, UserCheck, ArrowRightLeft, MessageSquare, Globe, GripVertical, Palette, Upload, Building2, Image as ImageIcon, MessageCircle, Wand2, Hand, Megaphone, Phone, Star, KeyRound, Shield, ShieldCheck, Building, AlertTriangle, AlertCircle, Thermometer, Search, ChevronRight, ChevronDown, Sparkles, Calendar, MapPin, GitMerge, Moon, Sun, Info, BellRing, LayoutDashboard, Clock, Play } from 'lucide-react'
import { Button } from '@/components/ui/button'
import Switch from '@/components/ui/switch'
import ConfirmDialog from '@/components/shared/ConfirmDialog'
import useAuthStore from '@/store/authStore'
import useBrandStore from '@/store/brandStore'
import useThemeStore from '@/store/themeStore'
import api from '@/lib/api'
import UsuariosPage from './Usuarios'
import RolesPage from './Roles'
import SharingRulesPage from './SharingRules'
import PermissionAuditPage from './PermissionAudit'
import SafeTextInput from '@/components/ui/SafeTextInput'
import TeamRotationPanel from '@/components/equipos/TeamRotationPanel'
import SedesManager from '@/components/sedes/SedesManager'
import DuplicatesManager from '@/components/admin/DuplicatesManager'
import { cn } from '@/lib/utils'

// Categorías de navegación. Cada una agrupa tabs relacionadas para
// que la barra lateral quede escaneable (patrón patrón de configuración profesional
// Business Suite "Más herramientas").
const CATEGORIES = [
  { id: 'empresa',      label: 'Empresa',         icon: Building },
  { id: 'equipo',       label: 'Equipo',          icon: Users },
  // 'Pipeline' → 'Embudo de ventas' (UAT v3.1): el termino tecnico no era
  // claro para usuarios no-tech. "Embudo de ventas" es estandar en CRM.
  { id: 'pipeline',     label: 'Embudo de ventas', icon: Tag },
  { id: 'comunicacion', label: 'Comunicación',    icon: MessageSquare },
  { id: 'cuenta',       label: 'Mi cuenta',       icon: Lock },
]

// Tabs — cada una referencia una categoría vía `group`. La descripción
// alimenta el header premium de la página (patrón estándar Setup /
// configuración profesional: título + subtítulo que describe el ámbito).
const TABS = [
  // Empresa
  { id: 'general',   group: 'empresa',      label: 'General',          icon: Settings,      roles: ['admin', 'supervisor'], description: 'Estado de los servicios e información general del sistema.' },
  { id: 'marca',     group: 'empresa',      label: 'Marca',            icon: Palette,       roles: ['admin'],               description: 'Logotipo, favicon, nombre comercial y colores del CRM.' },
  { id: 'sedes',     group: 'empresa',      label: 'Sedes',            icon: MapPin,        roles: ['admin'],               description: 'Ubicaciones de servicio (multi-sede). Cada lead puede asignarse a una sede.' },
  // Equipo
  { id: 'usuarios',  group: 'equipo',       label: 'Usuarios',         icon: Users,         roles: ['admin'],               description: 'Cuentas, roles y accesos del equipo.' },
  { id: 'roles',     group: 'equipo',       label: 'Roles y permisos', icon: ShieldCheck,   roles: ['admin'],               description: 'Define qué módulos puede ver cada rol del CRM. Soporta roles built-in (admin/supervisor/asesor) y customs para equipos como marketing.' },
  { id: 'sharing_rules', group: 'equipo',   label: 'Vistas compartidas', icon: GitMerge,    roles: ['admin'],               description: 'Define qué leads ve cada rol personalizado según criterios (fuente, estado, sede, proveedor). Patrón reglas de visibilidad profesionales.' },
  { id: 'auditoria',  group: 'equipo',      label: 'Auditoría',        icon: Shield,        roles: ['admin'],               description: 'Quién cambió permisos o roles, cuándo, desde qué IP. Trazabilidad para cumplimiento Ley 29733 PE.' },
  { id: 'equipos',   group: 'equipo',       label: 'Equipos',          icon: UserCheck,     roles: ['admin', 'supervisor'], description: 'Agrupación de asesores bajo cada supervisor.' },
  { id: 'panel_jefatura', group: 'equipo',  label: 'Acceso Panel Jefatura', icon: LayoutDashboard, roles: ['admin'],         description: 'Designa qué supervisores individuales tienen acceso al Panel de Control de Jefatura y Supervisión.' },
  // Pipeline
  { id: 'estados',   group: 'pipeline',     label: 'Estados',          icon: Tag,           roles: ['admin', 'supervisor'], description: 'Estados configurables del ciclo de venta.' },
  { id: 'automatizaciones', group: 'pipeline', label: 'Automatización de estados', icon: Zap, roles: ['admin'],               description: 'Reglas automáticas de cambio de estado por llamadas, WhatsApp o tiempo transcurrido.' },
  { id: 'calidad',   group: 'pipeline',     label: 'Calidad',          icon: Thermometer,   roles: ['admin'],               description: 'Clasificación de calidad de los leads.' },
  { id: 'fuentes',   group: 'pipeline',     label: 'Fuentes',          icon: Globe,         roles: ['admin', 'supervisor'], description: 'Orígenes de captación (Meta, TikTok, referidos, etc).' },
  { id: 'campanas',  group: 'pipeline',     label: 'Campañas',         icon: Megaphone,     roles: ['admin', 'supervisor'], description: 'Campañas de marketing asociadas a los leads.' },
  { id: 'etiquetas', group: 'pipeline',     label: 'Etiquetas',        icon: Tags,          roles: ['admin', 'supervisor'], description: 'Tags personalizados para clasificar leads.' },
  { id: 'duplicados', group: 'pipeline',    label: 'Duplicados',       icon: GitMerge,      roles: ['admin'],               description: 'Detecta y fusiona leads duplicados (mismo teléfono). Preserva historial vía audit log.' },
  // Comunicación
  { id: 'contactos', group: 'comunicacion', label: 'Contactos',        icon: MessageSquare, roles: ['admin', 'supervisor'], description: 'Tipos de contacto y resultados de seguimiento.' },
  { id: 'cita_estados', group: 'comunicacion', label: 'Estados de cita', icon: Calendar,    roles: ['admin', 'supervisor'], description: 'Estados de las citas (Pendiente, Completada, Reprogramada, ...).' },
  { id: 'chips',     group: 'comunicacion', label: 'Categorías Chat',  icon: Wand2,         roles: ['admin'],               description: 'Sugerencias rápidas para conversaciones con leads.' },
  { id: 'ia',        group: 'comunicacion', label: 'IA Clasificador',  icon: Bot,           roles: ['admin'],               description: 'Ajusta cómo la IA clasifica los chats entrantes de WhatsApp.' },
  { id: 'push',      group: 'comunicacion', label: 'Notificaciones',   icon: Phone,         roles: ['admin'],               description: 'Templates editables de las notificaciones push que reciben los asesores.' },
  { id: 'movil',     group: 'comunicacion', label: 'Sincronización móvil', icon: RefreshCw, roles: ['admin'],               description: 'Frecuencia con que la app móvil sube el registro de llamadas al CRM.' },
  { id: 'correo',    group: 'comunicacion', label: 'Correo',           icon: Mail,          roles: ['admin'],               description: 'Servidor SMTP para invitaciones y alertas.' },
  // Mi cuenta
  { id: 'mis_notifs', group: 'cuenta',     label: 'Mis notificaciones', icon: BellRing,                                       description: 'Tu horario silencioso personal y qué tipos de push quieres recibir.' },
  { id: 'seguridad', group: 'cuenta',       label: 'Seguridad',        icon: Lock,                                          description: 'Contraseña y seguridad de tu cuenta.' },
]

// Servicios del sistema a verificar
const SERVICIOS = [
  { id: 'api', label: 'API Backend', descripcion: 'FastAPI — Servidor principal', icon: Server, color: 'text-indigo-600', bg: 'bg-indigo-50' },
  { id: 'db', label: 'Base de Datos', descripcion: 'PostgreSQL — Almacenamiento principal', icon: Database, color: 'text-green-600', bg: 'bg-green-50' },
]

function StatusDot({ estado }) {
  if (estado === 'verificando') return <Loader size={16} className="animate-spin text-indigo-500" />
  if (estado === 'online' || estado === 'demo_mode') return <CheckCircle size={16} className="text-green-500" />
  if (estado === 'offline' || estado === 'error') return <XCircle size={16} className="text-red-500" />
  return <div className="w-3 h-3 rounded-full bg-gray-300" />
}

function StatusLabel({ estado }) {
  const map = {
    verificando: { label: 'Verificando...', cls: 'text-indigo-600' },
    online: { label: 'Conectado', cls: 'text-green-700' },
    demo_mode: { label: 'Modo Demo', cls: 'text-amber-600' },
    offline: { label: 'Sin conexión', cls: 'text-red-600' },
    error: { label: 'Error', cls: 'text-red-600' },
    desconocido: { label: '—', cls: 'text-gray-400' },
  }
  const info = map[estado] || map.desconocido
  return <span className={`text-xs font-semibold ${info.cls}`}>{info.label}</span>
}

function MsgBox({ msg }) {
  if (!msg) return null
  const isOk = msg.tipo === 'ok'
  return (
    <div className={`rounded-lg p-3 text-sm flex items-center gap-2 ${
      isOk ? 'bg-green-50 border border-green-200 text-green-800' : 'bg-red-50 border border-red-200 text-red-700'
    }`}>
      {isOk ? <CheckCircle size={15} /> : <XCircle size={15} />}
      {msg.texto}
    </div>
  )
}

const SMTP_DEFAULTS = {
  from_address: '', smtp_server: '', from_domain: '', smtp_port: 587,
  username: '', password: '', use_ssl: false, ignore_tls_errors: false, reject_unauthorized: true,
}

/** Gestión de estados del pipeline */
/**
 * V042 — EstadosManager parametrizado.
 * Mismo manager visual que se usa para /api/estados (estados de leads) y
 * para /api/cita-estados (estados de citas). El endpoint, titulo y
 * descripcion se pasan por props.
 */
function EstadosManager({
  baseEndpoint = '/api/estados',
  title = 'Estados del embudo',
  description = 'Configura los estados del ciclo de venta.',
  newButtonLabel = 'Nuevo estado',
} = {}) {
  const [estados, setEstados] = useState([])
  const [editingId, setEditingId] = useState(null)
  const [editForm, setEditForm] = useState({})
  const [newForm, setNewForm] = useState({ nombre: '', color_hex: '#3b82f6' })
  const [showNew, setShowNew] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState(null)
  const [confirmId, setConfirmId] = useState(null)
  // V041.7 — drag & drop para reordenar estados (mismo patron que Fuentes,
  // Campanas, Calidad, Tipos-contacto). Backend: POST /api/estados/reorder.
  const [dragIndex, setDragIndex] = useState(null)
  const [dragOverIndex, setDragOverIndex] = useState(null)

  const load = () => {
    setLoading(true)
    api.get(baseEndpoint)
      .then(r => setEstados(r.data || []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const startEdit = (e) => {
    setEditingId(e.id)
    setEditForm({ nombre: e.nombre, color_hex: e.color_hex })
  }

  const saveEdit = async (id) => {
    setSaving(true)
    try {
      await api.patch(`${baseEndpoint}/${id}`, editForm)
      setEstados(prev => prev.map(e => e.id === id ? { ...e, ...editForm } : e))
      setEditingId(null)
      setMsg({ ok: true, text: 'Estado actualizado.' })
    } catch (err) {
      setMsg({ ok: false, text: err.response?.data?.detail || 'Error al guardar.' })
    } finally {
      setSaving(false)
      setTimeout(() => setMsg(null), 3000)
    }
  }

  const handleDelete = (id) => {
    setConfirmId(id)
  }

  const handleConfirmDelete = async () => {
    const id = confirmId
    setConfirmId(null)
    try {
      await api.delete(`${baseEndpoint}/${id}`)
      setEstados(prev => prev.filter(e => e.id !== id))
    } catch (err) {
      setMsg({ ok: false, text: err.response?.data?.detail || 'Error al eliminar.' })
      setTimeout(() => setMsg(null), 4000)
    }
  }

  const handleCreate = async () => {
    if (!newForm.nombre.trim()) return
    setSaving(true)
    try {
      const r = await api.post(baseEndpoint, newForm)
      setEstados(prev => [...prev, r.data])
      setNewForm({ nombre: '', color_hex: '#3b82f6' })
      setShowNew(false)
      setMsg({ ok: true, text: 'Estado creado.' })
    } catch (err) {
      setMsg({ ok: false, text: err.response?.data?.detail || 'Error al crear.' })
    } finally {
      setSaving(false)
      setTimeout(() => setMsg(null), 3000)
    }
  }

  // ─── Drag and drop handlers (V041.7) ──────────────────────────────────────
  const handleDragStart = (ev, index) => {
    setDragIndex(index)
    ev.dataTransfer.effectAllowed = 'move'
  }
  const handleDragOver = (ev, index) => {
    ev.preventDefault()
    ev.dataTransfer.dropEffect = 'move'
    if (index !== dragOverIndex) setDragOverIndex(index)
  }
  const handleDrop = async (ev, index) => {
    ev.preventDefault()
    if (dragIndex === null || dragIndex === index) {
      setDragIndex(null); setDragOverIndex(null)
      return
    }
    const reordered = [...estados]
    const [moved] = reordered.splice(dragIndex, 1)
    reordered.splice(index, 0, moved)
    // Optimistic: actualiza el orden local; el backend devuelve OK y la
    // proxima recarga trae los orden numerados (1, 2, 3...).
    const withOrden = reordered.map((it, i) => ({ ...it, orden: i + 1 }))
    setEstados(withOrden)
    setDragIndex(null); setDragOverIndex(null)
    try {
      await api.post(`${baseEndpoint}/reorder`, { ids: reordered.map(e => e.id) })
      setMsg({ ok: true, text: 'Orden actualizado.' })
      setTimeout(() => setMsg(null), 2000)
    } catch (err) {
      setMsg({ ok: false, text: err.response?.data?.detail || 'Error al guardar el orden.' })
      setTimeout(() => setMsg(null), 3000)
      // Rollback en caso de error: recargamos del backend
      load()
    }
  }
  const handleDragEnd = () => { setDragIndex(null); setDragOverIndex(null) }

  if (loading) return <div className="h-20 bg-gray-100 rounded animate-pulse" />

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-gray-900">{title}</h2>
          <p className="text-xs text-gray-400 mt-0.5">{description}</p>
        </div>
        <Button size="sm" onClick={() => setShowNew(true)} className="gap-1.5">
          <Plus size={13} /> {newButtonLabel}
        </Button>
      </div>

      {msg && (
        <div className={`rounded-lg p-3 text-sm flex items-center gap-2 ${msg.ok ? 'bg-green-50 border border-green-200 text-green-800' : 'bg-red-50 border border-red-200 text-red-700'}`}>
          {msg.ok ? <CheckCircle size={14} /> : <XCircle size={14} />} {msg.text}
        </div>
      )}

      {/* Nuevo estado */}
      {showNew && (
        <div className="border border-indigo-200 bg-indigo-50/30 rounded-xl p-4 flex items-center gap-3">
          <input
            type="color"
            value={newForm.color_hex}
            onChange={e => setNewForm(p => ({ ...p, color_hex: e.target.value }))}
            className="w-9 h-9 rounded-lg cursor-pointer border border-gray-200"
          />
          <input
            type="text"
            placeholder="Nombre del estado…"
            value={newForm.nombre}
            onChange={e => setNewForm(p => ({ ...p, nombre: e.target.value }))}
            onKeyDown={e => e.key === 'Enter' && handleCreate()}
            autoFocus
            className="flex-1 text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
          <button onClick={handleCreate} disabled={saving} className="p-2 rounded-lg bg-[var(--brand-primary)] text-white hover:bg-[var(--brand-primary-hover)]">
            <Check size={14} />
          </button>
          <button onClick={() => setShowNew(false)} className="p-2 rounded-lg hover:bg-gray-100 text-gray-400">
            <XIcon size={14} />
          </button>
        </div>
      )}

      {/* Lista de estados — drag & drop (V041.7) para reordenar */}
      <div className="border border-gray-100 rounded-xl overflow-hidden divide-y divide-gray-50">
        {estados.map((e, index) => (
          <div
            key={e.id}
            draggable={editingId !== e.id}
            onDragStart={(ev) => handleDragStart(ev, index)}
            onDragOver={(ev) => handleDragOver(ev, index)}
            onDrop={(ev) => handleDrop(ev, index)}
            onDragEnd={handleDragEnd}
            className={`group flex items-center gap-3 px-4 py-3 hover:bg-gray-50/60 transition-colors ${dragIndex === index ? 'opacity-40' : ''} ${dragOverIndex === index && dragIndex !== null && dragIndex !== index ? 'bg-indigo-50/60' : ''}`}
          >
            {/* Drag handle — visible siempre cuando no estas editando */}
            {editingId !== e.id && (
              <span
                className="text-gray-300 group-hover:text-gray-500 cursor-grab active:cursor-grabbing shrink-0 select-none"
                title="Arrastra para reordenar"
                aria-hidden="true"
              >
                ⠿
              </span>
            )}
            {editingId === e.id ? (
              <>
                <input
                  type="color"
                  value={editForm.color_hex}
                  onChange={ev => setEditForm(p => ({ ...p, color_hex: ev.target.value }))}
                  className="w-8 h-8 rounded-lg cursor-pointer border border-gray-200"
                />
                <input
                  type="text"
                  value={editForm.nombre}
                  onChange={ev => setEditForm(p => ({ ...p, nombre: ev.target.value }))}
                  onKeyDown={ev => ev.key === 'Enter' && saveEdit(e.id)}
                  autoFocus
                  className="flex-1 text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
                <button onClick={() => saveEdit(e.id)} disabled={saving} className="p-1.5 rounded-lg bg-[var(--brand-primary)] text-white hover:bg-[var(--brand-primary-hover)]">
                  <Check size={13} />
                </button>
                <button onClick={() => setEditingId(null)} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400">
                  <XIcon size={13} />
                </button>
              </>
            ) : (
              <>
                <span className="w-4 h-4 rounded-full shrink-0" style={{ backgroundColor: e.color_hex }} />
                <span
                  className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold border"
                  style={{ backgroundColor: e.color_hex + '20', color: e.color_hex, borderColor: e.color_hex + '40' }}
                >
                  {e.nombre}
                </span>
                <span className="text-xs text-gray-400 ml-1">orden {e.orden}</span>
                <div className="ml-auto flex items-center gap-1">
                  <button onClick={() => startEdit(e)} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-600">
                    <Pencil size={13} />
                  </button>
                  <button onClick={() => handleDelete(e.id)} className="p-1.5 rounded-lg hover:bg-red-50 text-gray-400 hover:text-red-500">
                    <Trash2 size={13} />
                  </button>
                </div>
              </>
            )}
          </div>
        ))}
      </div>

      <ConfirmDialog
        open={confirmId !== null}
        title="Eliminar estado"
        message="¿Estás seguro de que deseas eliminar este estado? Solo es posible si ningún lead lo usa."
        onConfirm={handleConfirmDelete}
        onCancel={() => setConfirmId(null)}
      />
    </div>
  )
}

/** Gestión de calidad (temperatura del lead) + toggle de obligatoriedad
 *  en la carga masiva. El catálogo vive en crm.catalogo_calidad; la bandera
 *  en public.app_settings (key=carga_masiva_config). */
// Convierte el nombre visible en un código interno determinístico:
// UPPER, sin tildes, sin símbolos, espacios → _ — estable y legible.
function slugifyCodigo(input) {
  return (input || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toUpperCase()
    .replace(/[^A-Z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 40)
}

function CalidadManager() {
  const [items, setItems] = useState([])
  const [editingId, setEditingId] = useState(null)
  const [editForm, setEditForm] = useState({})
  const [newForm, setNewForm] = useState({ nombre: '', color_hex: '#38bdf8' })
  const [showNew, setShowNew] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState(null)
  const [confirmId, setConfirmId] = useState(null)
  const [required, setRequired] = useState(false)
  const [savingFlag, setSavingFlag] = useState(false)
  const [dragIndex, setDragIndex] = useState(null)
  const [dragOverIndex, setDragOverIndex] = useState(null)

  const showMsg = (m) => { setMsg(m); setTimeout(() => setMsg(null), 4000) }

  // Extrae el mensaje más útil de un error de axios (detail del backend,
  // HTTP status, network) — evita el genérico que esconde la causa real.
  const apiErrMsg = (err, fallback = 'Error inesperado.') => {
    const d = err?.response?.data?.detail
    if (typeof d === 'string' && d.trim()) return d
    if (Array.isArray(d) && d[0]?.msg) return d[0].msg
    const status = err?.response?.status
    if (status === 401) return 'Sesión expirada. Vuelve a iniciar sesión.'
    if (status === 403) return 'No tienes permisos para esta acción.'
    if (status === 404) return 'El recurso no existe o fue eliminado.'
    if (status === 405) return 'El servidor no acepta esta operación (¿falta redeploy del backend?).'
    if (err?.message === 'Network Error') return 'Sin conexión con el servidor.'
    if (status) return `${fallback} (HTTP ${status})`
    return fallback
  }

  const load = () => {
    setLoading(true)
    Promise.all([
      api.get('/api/calidad').catch(() => ({ data: [] })),
      api.get('/api/settings/carga-masiva').catch(() => ({ data: { calidad_requerida: false } })),
    ]).then(([cat, cfg]) => {
      setItems(cat.data || [])
      setRequired(Boolean(cfg.data?.calidad_requerida))
    }).finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const startEdit = (it) => {
    setEditingId(it.id)
    setEditForm({ nombre: it.nombre, color_hex: it.color_hex })
  }

  const saveEdit = async (id) => {
    setSaving(true)
    try {
      const r = await api.patch(`/api/calidad/${id}`, editForm)
      setItems(prev => prev.map(it => it.id === id ? { ...it, ...r.data } : it))
      setEditingId(null)
      showMsg({ ok: true, text: 'Calidad actualizada.' })
    } catch (err) {
      showMsg({ ok: false, text: apiErrMsg(err, 'No se pudo actualizar.') })
    } finally { setSaving(false) }
  }

  const previewCodigo = slugifyCodigo(newForm.nombre)

  const handleCreate = async () => {
    const nombre = (newForm.nombre || '').trim()
    const codigo = slugifyCodigo(nombre)
    if (!nombre || !codigo) return
    setSaving(true)
    try {
      const r = await api.post('/api/calidad', { codigo, nombre, color_hex: newForm.color_hex })
      setItems(prev => {
        const exists = prev.some(it => it.id === r.data.id)
        return exists ? prev.map(it => it.id === r.data.id ? r.data : it) : [...prev, r.data]
      })
      setNewForm({ nombre: '', color_hex: '#38bdf8' })
      setShowNew(false)
      showMsg({ ok: true, text: `Calidad "${nombre}" creada.` })
    } catch (err) {
      showMsg({ ok: false, text: apiErrMsg(err, 'No se pudo crear.') })
    } finally { setSaving(false) }
  }

  const handleConfirmDelete = async () => {
    const id = confirmId
    setConfirmId(null)
    try {
      const r = await api.delete(`/api/calidad/${id}`)
      const afectados = r.data?.leads_afectados || 0
      showMsg({
        ok: true,
        text: afectados > 0
          ? `Calidad desactivada. ${afectados} lead(s) mantienen el valor hasta ser reclasificados.`
          : 'Calidad desactivada.'
      })
      // Recarga desde backend en lugar de filtrar local: garantiza
      // que la UI refleje exactamente lo que quedó persistido.
      load()
    } catch (err) {
      showMsg({ ok: false, text: apiErrMsg(err, 'No se pudo desactivar.') })
    }
  }

  const toggleRequired = async () => {
    const next = !required
    setSavingFlag(true)
    try {
      await api.put('/api/settings/carga-masiva', { calidad_requerida: next })
      setRequired(next)
      showMsg({
        ok: true,
        text: next
          ? 'Calidad obligatoria en carga masiva.'
          : 'Calidad opcional en carga masiva.'
      })
    } catch (err) {
      showMsg({ ok: false, text: apiErrMsg(err, 'No se pudo guardar.') })
    } finally { setSavingFlag(false) }
  }

  const handleDragStart = (e, index) => {
    setDragIndex(index)
    e.dataTransfer.effectAllowed = 'move'
  }
  const handleDragOver = (e, index) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    if (index !== dragOverIndex) setDragOverIndex(index)
  }
  const handleDrop = async (e, index) => {
    e.preventDefault()
    if (dragIndex === null || dragIndex === index) {
      setDragIndex(null); setDragOverIndex(null)
      return
    }
    const reordered = [...items]
    const [moved] = reordered.splice(dragIndex, 1)
    reordered.splice(index, 0, moved)
    const withOrden = reordered.map((it, i) => ({ ...it, orden: i + 1 }))
    setItems(withOrden)
    setDragIndex(null); setDragOverIndex(null)
    try {
      await api.post('/api/calidad/reorder', { ids: withOrden.map(i => i.id) })
    } catch {
      showMsg({ ok: false, text: 'Error al guardar el orden.' })
    }
  }
  const handleDragEnd = () => { setDragIndex(null); setDragOverIndex(null) }

  if (loading) return <div className="h-20 bg-gray-100 rounded animate-pulse" />

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Calidad del Lead</h2>
          <p className="text-xs text-gray-400 mt-0.5">
            Clasificación de temperatura del prospecto. Editá el nombre, color y orden a voluntad.
            El código interno es una referencia técnica y no cambia una vez creado.
          </p>
        </div>
        <Button size="sm" onClick={() => setShowNew(true)} className="gap-1.5">
          <Plus size={13} /> Nueva calidad
        </Button>
      </div>

      {msg && (
        <div className={`rounded-lg p-3 text-sm flex items-center gap-2 ${msg.ok ? 'bg-green-50 border border-green-200 text-green-800' : 'bg-red-50 border border-red-200 text-red-700'}`}>
          {msg.ok ? <CheckCircle size={14} /> : <XCircle size={14} />} {msg.text}
        </div>
      )}

      {/* Toggle: calidad obligatoria en carga masiva */}
      <div className="border border-gray-200 rounded-xl p-4 flex items-start gap-3">
        <div className="flex-1">
          <div className="text-sm font-semibold text-gray-900">Exigir calidad en carga masiva</div>
          <p className="text-xs text-gray-500 mt-1">
            Cuando está activo, el importador de leads rechaza las filas que no traigan un valor válido de calidad.
          </p>
        </div>
        <Switch
          checked={required}
          onChange={toggleRequired}
          disabled={savingFlag}
          ariaLabel="Exigir calidad en carga masiva"
        />
      </div>

      {/* Nuevo — solo pide nombre visible + color. El código se genera solo. */}
      {showNew && (
        <div className="border border-indigo-200 bg-indigo-50/30 rounded-xl p-4 space-y-3">
          <div className="flex items-center gap-3">
            <input
              type="color"
              value={newForm.color_hex}
              onChange={e => setNewForm(p => ({ ...p, color_hex: e.target.value }))}
              className="w-10 h-10 rounded-lg cursor-pointer border border-gray-200 shrink-0"
              title="Color del badge"
            />
            <input
              type="text"
              placeholder="Ej: Muy caliente, Listo para cierre, Sin interés…"
              value={newForm.nombre}
              onChange={e => setNewForm(p => ({ ...p, nombre: e.target.value }))}
              onKeyDown={e => e.key === 'Enter' && handleCreate()}
              autoFocus
              className="flex-1 text-sm border border-gray-200 rounded-lg px-3 py-2.5 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <button
              onClick={handleCreate}
              disabled={saving || !previewCodigo}
              className="px-4 py-2.5 rounded-lg bg-[var(--brand-primary)] text-white text-sm font-medium hover:bg-[var(--brand-primary-hover)] disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1.5"
            >
              <Check size={14} /> Crear
            </button>
            <button
              onClick={() => { setShowNew(false); setNewForm({ nombre: '', color_hex: '#38bdf8' }) }}
              className="p-2.5 rounded-lg hover:bg-gray-100 text-gray-400"
            >
              <XIcon size={14} />
            </button>
          </div>
          {newForm.nombre.trim() && (
            <div className="flex items-center gap-2 text-xs text-gray-500 pl-[52px]">
              <span>Vista previa:</span>
              <span
                className="inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold border"
                style={{ backgroundColor: newForm.color_hex + '20', color: newForm.color_hex, borderColor: newForm.color_hex + '40' }}
              >
                {newForm.nombre.trim()}
              </span>
              <span className="text-gray-300">·</span>
              <span className="font-mono text-gray-400">código: {previewCodigo || '—'}</span>
            </div>
          )}
        </div>
      )}

      {/* Lista — filas card con el nombre como hero */}
      <div className="border border-gray-100 rounded-xl overflow-hidden divide-y divide-gray-50">
        {items.map((it, index) => (
          <div
            key={it.id}
            draggable={editingId !== it.id}
            onDragStart={e => handleDragStart(e, index)}
            onDragOver={e => handleDragOver(e, index)}
            onDrop={e => handleDrop(e, index)}
            onDragEnd={handleDragEnd}
            className={`group flex items-center gap-4 px-4 py-3.5 hover:bg-gray-50/60 transition-colors ${dragIndex === index ? 'opacity-40' : ''} ${dragOverIndex === index && dragIndex !== null && dragIndex !== index ? 'bg-indigo-50/60' : ''}`}
          >
            {editingId === it.id ? (
              <>
                <input
                  type="color"
                  value={editForm.color_hex}
                  onChange={ev => setEditForm(p => ({ ...p, color_hex: ev.target.value }))}
                  className="w-10 h-10 rounded-lg cursor-pointer border border-gray-200 shrink-0"
                />
                <div className="flex-1 min-w-0">
                  <input
                    type="text"
                    value={editForm.nombre}
                    onChange={ev => setEditForm(p => ({ ...p, nombre: ev.target.value }))}
                    onKeyDown={ev => ev.key === 'Enter' && saveEdit(it.id)}
                    autoFocus
                    className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  />
                  <div className="flex items-center gap-1.5 text-[10px] text-gray-400 mt-1 pl-1">
                    <Lock size={10} />
                    <span className="font-mono uppercase">{it.codigo}</span>
                    <span className="text-gray-300">·</span>
                    <span>código interno · no editable</span>
                  </div>
                </div>
                <button onClick={() => saveEdit(it.id)} disabled={saving} className="p-2 rounded-lg bg-[var(--brand-primary)] text-white hover:bg-[var(--brand-primary-hover)]">
                  <Check size={13} />
                </button>
                <button onClick={() => setEditingId(null)} className="p-2 rounded-lg hover:bg-gray-100 text-gray-400">
                  <XIcon size={13} />
                </button>
              </>
            ) : (
              <>
                <span className="text-gray-300 group-hover:text-gray-400 cursor-grab active:cursor-grabbing shrink-0" title="Arrastra para reordenar">
                  <GripVertical size={14} />
                </span>
                <span
                  className="w-9 h-9 rounded-lg shrink-0 flex items-center justify-center"
                  style={{ backgroundColor: it.color_hex + '1f', border: `1px solid ${it.color_hex}4d` }}
                >
                  <Thermometer size={16} style={{ color: it.color_hex }} />
                </span>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span
                      className="inline-flex items-center rounded-full px-2.5 py-0.5 text-sm font-semibold border"
                      style={{ backgroundColor: it.color_hex + '20', color: it.color_hex, borderColor: it.color_hex + '40' }}
                    >
                      {it.nombre}
                    </span>
                  </div>
                  <div className="text-[10px] text-gray-400 mt-1 font-mono uppercase tracking-wide">
                    {it.codigo}
                  </div>
                </div>
                <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                  <button onClick={() => startEdit(it)} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-600" title="Editar">
                    <Pencil size={13} />
                  </button>
                  <button onClick={() => setConfirmId(it.id)} className="p-1.5 rounded-lg hover:bg-red-50 text-gray-400 hover:text-red-500" title="Desactivar">
                    <Trash2 size={13} />
                  </button>
                </div>
              </>
            )}
          </div>
        ))}
        {items.length === 0 && (
          <div className="px-4 py-8 text-sm text-gray-400 text-center">
            Aún no hay valores de calidad. Creá el primero con el botón de arriba.
          </div>
        )}
      </div>

      <ConfirmDialog
        open={confirmId !== null}
        title="Desactivar calidad"
        message="¿Desactivar este valor? Los leads con esta calidad conservan el valor hasta ser reclasificados."
        onConfirm={handleConfirmDelete}
        onCancel={() => setConfirmId(null)}
      />
    </div>
  )
}

/** Gestión de etiquetas: catálogo editable + conteo de uso.
 *  Las etiquetas complementan el estado — sirven para agrupar leads por
 *  necesidad (Caliente, Requiere visita, Pendiente info…) y se asignan
 *  desde el chat o el detalle del lead. */
function TagsManager() {
  const [tags, setTags] = useState([])
  const [editingId, setEditingId] = useState(null)
  const [editForm, setEditForm] = useState({})
  const [newForm, setNewForm] = useState({ nombre: '', color_hex: '#6366f1', descripcion: '' })
  const [showNew, setShowNew] = useState(false)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState(null)
  const [confirmId, setConfirmId] = useState(null)

  const load = () => {
    setLoading(true)
    api.get('/api/tags')
      .then(r => setTags(r.data || []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const showMsg = (m) => { setMsg(m); setTimeout(() => setMsg(null), 3000) }

  const startEdit = (t) => {
    setEditingId(t.id)
    setEditForm({ nombre: t.nombre, color_hex: t.color_hex, descripcion: t.descripcion || '' })
  }

  const saveEdit = async (id) => {
    setSaving(true)
    try {
      const r = await api.patch(`/api/tags/${id}`, editForm)
      setTags(prev => prev.map(t => t.id === id ? { ...t, ...r.data } : t))
      setEditingId(null)
      showMsg({ ok: true, text: 'Etiqueta actualizada.' })
    } catch (err) {
      showMsg({ ok: false, text: err.response?.data?.detail || 'Error al guardar.' })
    } finally { setSaving(false) }
  }

  const handleConfirmDelete = async () => {
    const id = confirmId
    setConfirmId(null)
    try {
      await api.delete(`/api/tags/${id}`)
      setTags(prev => prev.filter(t => t.id !== id))
      showMsg({ ok: true, text: 'Etiqueta desactivada.' })
    } catch (err) {
      showMsg({ ok: false, text: err.response?.data?.detail || 'Error al eliminar.' })
    }
  }

  const handleCreate = async () => {
    if (!newForm.nombre.trim()) return
    setSaving(true)
    try {
      const r = await api.post('/api/tags', newForm)
      setTags(prev => [...prev, r.data])
      setNewForm({ nombre: '', color_hex: '#6366f1', descripcion: '' })
      setShowNew(false)
      showMsg({ ok: true, text: 'Etiqueta creada.' })
    } catch (err) {
      showMsg({ ok: false, text: err.response?.data?.detail || 'Error al crear.' })
    } finally { setSaving(false) }
  }

  if (loading) return <div className="h-20 bg-gray-100 rounded animate-pulse" />

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-gray-900">Etiquetas</h2>
          <p className="text-xs text-gray-400 mt-0.5">
            Marcadores de gestión: Caliente, Requiere visita, Pendiente info… Un lead puede tener varias.
          </p>
        </div>
        <Button size="sm" onClick={() => setShowNew(true)} className="gap-1.5">
          <Plus size={13} /> Nueva etiqueta
        </Button>
      </div>

      {msg && (
        <div className={`rounded-lg p-3 text-sm flex items-center gap-2 ${msg.ok ? 'bg-green-50 border border-green-200 text-green-800' : 'bg-red-50 border border-red-200 text-red-700'}`}>
          {msg.ok ? <CheckCircle size={14} /> : <XCircle size={14} />} {msg.text}
        </div>
      )}

      {showNew && (
        <div className="border border-indigo-200 bg-indigo-50/30 rounded-xl p-4 space-y-3">
          <div className="flex items-center gap-3">
            <input
              type="color"
              value={newForm.color_hex}
              onChange={e => setNewForm(p => ({ ...p, color_hex: e.target.value }))}
              className="w-9 h-9 rounded-lg cursor-pointer border border-gray-200"
            />
            <input
              type="text"
              placeholder="Nombre de la etiqueta…"
              value={newForm.nombre}
              onChange={e => setNewForm(p => ({ ...p, nombre: e.target.value }))}
              onKeyDown={e => e.key === 'Enter' && handleCreate()}
              autoFocus
              maxLength={64}
              className="flex-1 text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <button onClick={handleCreate} disabled={saving} className="p-2 rounded-lg bg-[var(--brand-primary)] text-white hover:bg-[var(--brand-primary-hover)]">
              <Check size={14} />
            </button>
            <button onClick={() => setShowNew(false)} className="p-2 rounded-lg hover:bg-gray-100 text-gray-400">
              <XIcon size={14} />
            </button>
          </div>
          <input
            type="text"
            placeholder="Descripción opcional (para qué sirve esta etiqueta)"
            value={newForm.descripcion}
            onChange={e => setNewForm(p => ({ ...p, descripcion: e.target.value }))}
            className="w-full text-xs border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>
      )}

      <div className="border border-gray-100 rounded-xl overflow-hidden divide-y divide-gray-50">
        {tags.length === 0 && (
          <div className="px-4 py-8 text-center text-sm text-gray-400">
            No hay etiquetas todavía. Crea la primera con el botón de arriba.
          </div>
        )}
        {tags.map((t) => (
          <div key={t.id} className="flex items-center gap-3 px-4 py-3 hover:bg-gray-50/60">
            {editingId === t.id ? (
              <>
                <input
                  type="color"
                  value={editForm.color_hex}
                  onChange={ev => setEditForm(p => ({ ...p, color_hex: ev.target.value }))}
                  className="w-8 h-8 rounded-lg cursor-pointer border border-gray-200"
                />
                <input
                  type="text"
                  value={editForm.nombre}
                  onChange={ev => setEditForm(p => ({ ...p, nombre: ev.target.value }))}
                  onKeyDown={ev => ev.key === 'Enter' && saveEdit(t.id)}
                  autoFocus
                  maxLength={64}
                  className="flex-1 text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
                <input
                  type="text"
                  placeholder="Descripción"
                  value={editForm.descripcion}
                  onChange={ev => setEditForm(p => ({ ...p, descripcion: ev.target.value }))}
                  className="flex-1 text-xs border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
                <button onClick={() => saveEdit(t.id)} disabled={saving} className="p-1.5 rounded-lg bg-[var(--brand-primary)] text-white hover:bg-[var(--brand-primary-hover)]">
                  <Check size={13} />
                </button>
                <button onClick={() => setEditingId(null)} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400">
                  <XIcon size={13} />
                </button>
              </>
            ) : (
              <>
                <span
                  className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-semibold border"
                  style={{ backgroundColor: t.color_hex + '20', color: t.color_hex, borderColor: t.color_hex + '40' }}
                >
                  <Tag size={11} /> {t.nombre}
                </span>
                {t.descripcion && (
                  <span className="text-xs text-gray-500 truncate max-w-xs">{t.descripcion}</span>
                )}
                <span className="text-xs text-gray-400 ml-auto">
                  {t.leads_count} {t.leads_count === 1 ? 'lead' : 'leads'}
                </span>
                <div className="flex items-center gap-1">
                  <button onClick={() => startEdit(t)} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400 hover:text-gray-600">
                    <Pencil size={13} />
                  </button>
                  <button onClick={() => setConfirmId(t.id)} className="p-1.5 rounded-lg hover:bg-red-50 text-gray-400 hover:text-red-500">
                    <Trash2 size={13} />
                  </button>
                </div>
              </>
            )}
          </div>
        ))}
      </div>

      <ConfirmDialog
        open={confirmId !== null}
        title="Desactivar etiqueta"
        message="La etiqueta dejará de mostrarse en el catálogo, pero los leads que la tuvieran conservarán su historial. ¿Continuar?"
        onConfirm={handleConfirmDelete}
        onCancel={() => setConfirmId(null)}
      />
    </div>
  )
}


/** Gestión de equipos: asignar/mover/quitar asesores de supervisores */
function EquiposManager() {
  const user = useAuthStore(s => s.user)
  const isAdmin = user?.role === 'admin'

  const [equipos, setEquipos] = useState([])
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [msg, setMsg] = useState(null)
  const [pendingMoves, setPendingMoves] = useState({})
  const [saving, setSaving] = useState(null)
  const [confirmRemove, setConfirmRemove] = useState(null) // { asesorId, nombre }
  // Estado controlado del acordeon "Mover o quitar asesores del equipo".
  // Antes usabamos <details> HTML nativo, pero al re-renderizar tras un
  // load() el componente se desmonta y pierde el estado de expanded. El
  // admin abria el panel, movia un asesor, y el panel se cerraba solo.
  // Con state React la expansion es persistente entre re-renders.
  const [expandedTeams, setExpandedTeams] = useState({})
  const [expandedSubTeams, setExpandedSubTeams] = useState({})
  const toggleTeamExpanded = (supervisorId) =>
    setExpandedTeams(prev => ({ ...prev, [supervisorId]: !prev[supervisorId] }))
  const toggleSubTeamExpanded = (subId) =>
    setExpandedSubTeams(prev => ({ ...prev, [subId]: !prev[subId] }))

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [eq, us] = await Promise.all([api.get('/api/equipos'), api.get('/auth/users')])
      setEquipos(eq.data || [])
      setUsers(us.data || [])
    } catch {
      /* silencioso: la UI muestra listas vacías si falla la carga */
    }
    finally { setLoading(false) }
  }, [])

  useEffect(() => { load() }, [load])

  // V088 — filtramos usuarios deshabilitados de TODAS las listas. Un
  // usuario con is_active=false ya no debe operar en el CRM ni aparecer
  // como destinatario en asignaciones / equipos.
  const asesores = users.filter(u => u.role === 'asesor' && u.is_active !== false)
  const allSupervisores = users.filter(
    u => (u.role === 'supervisor' || u.role === 'admin') && u.is_active !== false
  )
  // Supervisor solo ve su propio equipo; admin ve todos
  const supervisores = isAdmin
    ? allSupervisores
    : allSupervisores.filter(s => s.id === user.user_id)
  const asignadoIds = new Set(equipos.map(e => e.asesor_id))
  const sinEquipo = asesores.filter(u => !asignadoIds.has(u.id))

  const fullName = (u) =>
    [u.first_name, u.last_name].filter(Boolean).join(' ') || u.email || 'Sin nombre'

  const showMsg = (m) => { setMsg(m); setTimeout(() => setMsg(null), 3500) }

  const handleAssign = async (asesorId, supervisorId) => {
    if (!supervisorId) return
    setSaving(asesorId)
    try {
      await api.post('/api/equipos', { asesor_id: asesorId, supervisor_id: supervisorId })
      await load()
      showMsg({ ok: true, text: 'Asesor asignado correctamente.' })
    } catch (err) {
      showMsg({ ok: false, text: err.response?.data?.detail || 'Error al asignar.' })
    } finally {
      setSaving(null)
      setPendingMoves(p => { const n = { ...p }; delete n[asesorId]; return n })
    }
  }

  const handleRemove = (asesorId, nombre) => {
    setConfirmRemove({ asesorId, nombre })
  }

  const handleConfirmRemove = async () => {
    const { asesorId } = confirmRemove
    setConfirmRemove(null)
    setSaving(asesorId)
    try {
      await api.delete(`/api/equipos/${asesorId}`)
      await load()
      showMsg({ ok: true, text: 'Asesor removido del equipo.' })
    } catch (err) {
      showMsg({ ok: false, text: err.response?.data?.detail || 'Error al remover.' })
    } finally {
      setSaving(null)
      // Limpiar el pendingMove del asesor — sin esto, el check verde/rojo
      // del confirmar quedaba visible aunque la accion ya se hubiera
      // ejecutado. Reportado en producción 2026-06-17.
      setPendingMoves(p => { const n = { ...p }; delete n[asesorId]; return n })
    }
  }

  if (loading) return (
    <div className="space-y-3">
      {[1, 2, 3].map(i => <div key={i} className="h-16 bg-gray-100 rounded-xl animate-pulse" />)}
    </div>
  )

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-base font-semibold text-gray-900">
            {isAdmin ? 'Gestión de Equipos' : 'Mi Equipo'}
          </h2>
          <p className="text-xs text-gray-400 mt-0.5">
            {isAdmin
              ? 'Asigna asesores a supervisores para organizar los equipos de venta.'
              : 'Asesores asignados a tu equipo de trabajo.'}
          </p>
        </div>
        <button
          onClick={load}
          className="flex items-center gap-1.5 text-xs text-gray-500 hover:text-gray-700 px-3 py-1.5 rounded-lg border border-gray-200 hover:bg-gray-50 transition-colors"
        >
          <RefreshCw size={12} /> Actualizar
        </button>
      </div>

      {msg && (
        <div className={`rounded-lg p-3 text-sm flex items-center gap-2 ${msg.ok
          ? 'bg-green-50 border border-green-200 text-green-800'
          : 'bg-red-50 border border-red-200 text-red-700'
        }`}>
          {msg.ok ? <CheckCircle size={14} /> : <XCircle size={14} />}
          {msg.text}
        </div>
      )}

      {/* Un bloque por supervisor */}
      {supervisores.map(supervisor => {
        const teamAsesores = equipos.filter(e => e.supervisor_id === supervisor.id)
        const subordinados = allSupervisores.filter(s => s.supervisor_jefe_id === supervisor.id)
        const isSubordinate = !!supervisor.supervisor_jefe_id

        return (
          <div key={supervisor.id} className={cn(
            "border border-gray-100 rounded-xl overflow-hidden transition-all",
            isSubordinate ? "ml-6 border-l-4 border-l-purple-400 bg-purple-50/10" : ""
          )}>
            <div className="flex items-center justify-between px-4 py-3 bg-gray-50 border-b border-gray-100 flex-wrap gap-2">
              <div className="flex items-center gap-3">
                <div className="w-8 h-8 bg-indigo-100 rounded-full flex items-center justify-center text-indigo-700 text-xs font-bold shrink-0">
                  {fullName(supervisor)[0]?.toUpperCase() || 'S'}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <p className="text-sm font-semibold text-gray-800">{fullName(supervisor)}</p>
                    {subordinados.length > 0 && (
                      <span className="text-[10px] bg-purple-100 text-purple-800 border border-purple-200 px-2 py-0.5 rounded-full font-bold">
                        Supervisor Jefe ({subordinados.length} sub-equipo{subordinados.length > 1 ? 's' : ''})
                      </span>
                    )}
                    {supervisor.supervisor_jefe_nombre && (
                      <span className="text-[10px] bg-purple-50 text-purple-700 border border-purple-200 px-2 py-0.5 rounded-full font-medium">
                        Jefe: {supervisor.supervisor_jefe_nombre}
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-400 capitalize">{supervisor.role}</p>
                </div>
              </div>

              <div className="flex items-center gap-3">
                {isAdmin && (
                  <div className="flex items-center gap-1.5 text-xs">
                    <span className="text-gray-400 text-[11px]">Supervisor Jefe:</span>
                    <select
                      value={supervisor.supervisor_jefe_id || ''}
                      onChange={async (ev) => {
                        const jefeId = ev.target.value || null
                        try {
                          await api.post('/api/equipos/supervisor-jefe', {
                            supervisor_id: supervisor.id,
                            supervisor_jefe_id: jefeId,
                          })
                          await load()
                          showMsg({ ok: true, text: 'Jerarquía de supervisor actualizada.' })
                        } catch (err) {
                          showMsg({ ok: false, text: err.response?.data?.detail || 'Error al actualizar.' })
                        }
                      }}
                      className="text-xs border border-gray-200 rounded-lg px-2 py-1 text-gray-700 bg-white font-normal"
                    >
                      <option value="">(Sin Jefe - Principal)</option>
                      {allSupervisores
                        .filter(s => s.id !== supervisor.id)
                        .map(s => (
                          <option key={s.id} value={s.id}>
                            {fullName(s)}
                          </option>
                        ))}
                    </select>
                  </div>
                )}
                <span className="text-xs bg-indigo-100 text-indigo-700 px-2.5 py-0.5 rounded-full font-medium">
                  {teamAsesores.length} {subordinados.length > 0 ? (teamAsesores.length === 1 ? 'asesor directo' : 'asesores directos') : (teamAsesores.length === 1 ? 'asesor' : 'asesores')}
                </span>
              </div>
            </div>

            {/* Supervisores subordinados a su cargo (si los tiene) */}
            {subordinados.length > 0 && (
              <div className="mx-4 my-3 p-3 bg-purple-50/70 border border-purple-200/80 rounded-xl space-y-2">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <UserCheck size={14} className="text-purple-600" />
                    <span className="text-xs font-semibold text-purple-900">
                      Supervisores subordinados a su cargo ({subordinados.length})
                    </span>
                  </div>
                </div>
                <div className="grid grid-cols-1 gap-2">
                  {subordinados.map(sub => {
                    const subAsesores = equipos.filter(e => e.supervisor_id === sub.id)
                    const isExpanded = expandedSubTeams[sub.id]
                    return (
                      <div key={sub.id} className="border border-purple-100 rounded-lg bg-white overflow-hidden shadow-2xs transition-all">
                        <button
                          type="button"
                          onClick={() => toggleSubTeamExpanded(sub.id)}
                          className="w-full flex items-center justify-between p-2.5 hover:bg-purple-50/50 cursor-pointer select-none text-left transition-colors"
                        >
                          <div className="flex items-center gap-2.5 min-w-0">
                            <div className="w-7 h-7 bg-purple-100 rounded-full flex items-center justify-center text-purple-700 text-xs font-bold shrink-0">
                              {fullName(sub)[0]?.toUpperCase() || 'S'}
                            </div>
                            <div className="min-w-0">
                              <p className="text-xs font-semibold text-gray-800 truncate">{fullName(sub)}</p>
                              <p className="text-[10px] text-purple-600 font-medium">Supervisor Subordinado</p>
                            </div>
                          </div>

                          <div className="flex items-center gap-2 shrink-0">
                            <span className="text-[10px] bg-purple-100 text-purple-800 px-2.5 py-0.5 rounded-full font-semibold">
                              {subAsesores.length} {subAsesores.length === 1 ? 'asesor' : 'asesores'}
                            </span>
                            <div className={cn("p-1 text-purple-500 rounded transition-transform duration-150", isExpanded && "rotate-180")}>
                              <ChevronDown size={14} />
                            </div>
                          </div>
                        </button>

                        {/* Lista desplegable de asesores del equipo subordinado */}
                        {isExpanded && (
                          <div className="border-t border-purple-100 bg-purple-50/30 p-2.5 space-y-1.5 animate-in fade-in duration-150">
                            <p className="text-[10px] font-semibold text-purple-900 uppercase tracking-wider px-1">
                              Asesores asignados a {fullName(sub)}:
                            </p>
                            {subAsesores.length === 0 ? (
                              <p className="text-xs text-gray-400 italic px-1 py-1">Sin asesores asignados a este equipo.</p>
                            ) : (
                              <div className="space-y-1">
                                {subAsesores.map(a => (
                                  <div key={a.asesor_id} className="flex items-center justify-between p-2 bg-white rounded-md border border-purple-100 text-xs">
                                    <div className="flex items-center gap-2 min-w-0">
                                      <div className="w-5 h-5 bg-indigo-50 text-indigo-600 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0">
                                        {a.asesor_nombre[0]?.toUpperCase()}
                                      </div>
                                      <span className="font-medium text-gray-800 truncate">{a.asesor_nombre}</span>
                                    </div>
                                    <span className="text-[10px] text-purple-700 bg-purple-50 px-2 py-0.5 rounded font-medium">Asesor</span>
                                  </div>
                                ))}
                              </div>
                            )}
                          </div>
                        )}
                      </div>
                    )
                  })}
                </div>
              </div>
            )}

            {/* Asesores directos a su cargo (si tiene supervisores subordinados y además asesores propios) */}
            {subordinados.length > 0 && teamAsesores.length > 0 && (
              <div className="mx-4 my-2 p-3 bg-indigo-50/70 border border-indigo-200/80 rounded-xl space-y-2">
                <div className="flex items-center gap-2">
                  <UserCheck size={14} className="text-indigo-600" />
                  <span className="text-xs font-semibold text-indigo-900">
                    Asesores directos a su cargo ({teamAsesores.length})
                  </span>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                  {teamAsesores.map(a => (
                    <div key={a.asesor_id} className="flex items-center justify-between p-2.5 bg-white rounded-lg border border-indigo-100 shadow-2xs text-xs">
                      <div className="flex items-center gap-2.5 min-w-0">
                        <div className="w-7 h-7 bg-indigo-100 text-indigo-700 rounded-full flex items-center justify-center text-xs font-bold shrink-0">
                          {a.asesor_nombre[0]?.toUpperCase() || 'A'}
                        </div>
                        <span className="font-semibold text-gray-800 truncate">{a.asesor_nombre}</span>
                      </div>
                      <span className="text-[10px] text-indigo-700 bg-indigo-50 px-2 py-0.5 rounded-full font-semibold border border-indigo-200">
                        Asesor Directo
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div className="px-4 py-3">
              {teamAsesores.length === 0 ? (
                <p className="text-xs text-gray-400 italic">Sin asesores asignados aún</p>
              ) : (
                <TeamRotationPanel
                  supervisorId={supervisor.id}
                  title="Jerarquía de rotación"
                  readOnly={false}
                />
              )}
            </div>

            {/* Acciones admin: mover/quitar asesores (debajo del panel).
                Acordeon controlado con React state para preservar el estado
                de expanded entre re-renders (ver expandedTeams arriba). */}
            {isAdmin && teamAsesores.length > 0 && (
              <div className="border-t border-gray-100">
                <button
                  type="button"
                  onClick={() => toggleTeamExpanded(supervisor.id)}
                  className="w-full text-left px-4 py-2 text-xs text-gray-500 cursor-pointer hover:bg-gray-50/50 select-none flex items-center gap-1.5"
                >
                  <span className={`inline-block transition-transform ${expandedTeams[supervisor.id] ? 'rotate-90' : ''}`}>
                    ▸
                  </span>
                  Mover o quitar asesores del equipo ({teamAsesores.length})
                </button>
                {expandedTeams[supervisor.id] && (
                <div className="divide-y divide-gray-50 bg-gray-50/30">
                  {teamAsesores.map(e => {
                    // Valor centinela reservado para la opcion "Quitar del
                    // equipo". Usamos un string que no puede colisionar con
                    // un UUID real de supervisor. Cuando se confirma con
                    // este valor, llamamos al handler de remove en lugar
                    // del de assign.
                    const REMOVE_VALUE = '__sin-equipo__'
                    const selected = pendingMoves[e.asesor_id] || ''
                    return (
                    <div key={e.asesor_id} className="flex items-center gap-3 px-4 py-2 hover:bg-white">
                      <span className="flex-1 text-sm text-gray-700 truncate">{e.asesor_nombre}</span>
                      <select
                        value={selected}
                        onChange={ev => setPendingMoves(p => ({ ...p, [e.asesor_id]: ev.target.value }))}
                        className="text-xs border border-gray-200 rounded-lg px-2 py-1 text-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white"
                      >
                        <option value="">Cambiar equipo...</option>
                        {allSupervisores.filter(s => s.id !== supervisor.id).map(s => (
                          <option key={s.id} value={s.id}>Mover a {fullName(s)}</option>
                        ))}
                        {/* Separador visual + accion destructiva al final.
                            Patron de UX para acciones de remover/destruir:
                            visualmente separadas de las acciones de mover. */}
                        <option disabled>──────────</option>
                        <option value={REMOVE_VALUE}>Quitar del equipo (sin supervisor)</option>
                      </select>

                      {selected && (
                        <button
                          onClick={() => {
                            if (selected === REMOVE_VALUE) {
                              // Confirma + DELETE /api/equipos/{asesorId}.
                              // El modal de confirmacion lo dispara el propio
                              // handler para evitar quitar por accidente.
                              handleRemove(e.asesor_id, e.asesor_nombre)
                            } else {
                              handleAssign(e.asesor_id, selected)
                            }
                          }}
                          disabled={saving === e.asesor_id}
                          title={selected === REMOVE_VALUE ? 'Confirmar quitar del equipo' : 'Confirmar movimiento'}
                          className={`p-1 rounded text-white disabled:opacity-50 shrink-0 ${
                            selected === REMOVE_VALUE
                              ? 'bg-red-500 hover:bg-red-600'
                              : 'bg-[var(--brand-primary)] hover:bg-[var(--brand-primary-hover)]'
                          }`}
                        >
                          {saving === e.asesor_id ? <Loader size={12} className="animate-spin" /> : <Check size={12} />}
                        </button>
                      )}

                      {/* Atajo rápido (queda como secundario). El flujo
                          principal ahora es por el dropdown — este boton X
                          se mantiene para usuarios que ya lo conocen. */}
                      <button
                        onClick={() => handleRemove(e.asesor_id, e.asesor_nombre)}
                        disabled={saving === e.asesor_id}
                        title="Quitar del equipo (atajo)"
                        className="p-1 rounded hover:bg-red-50 text-gray-300 hover:text-red-400 disabled:opacity-50 shrink-0"
                      >
                        <XIcon size={12} />
                      </button>
                    </div>
                    )
                  })}
                </div>
                )}
              </div>
            )}
          </div>
        )
      })}

      {/* Asesores sin equipo — solo admin */}
      {isAdmin && sinEquipo.length > 0 && (
        <div className="border border-orange-200 bg-orange-50/20 rounded-xl overflow-hidden">
          <div className="px-4 py-3 bg-orange-50/60 border-b border-orange-100">
            <h3 className="text-sm font-semibold text-orange-800">
              Sin equipo — {sinEquipo.length} {sinEquipo.length === 1 ? 'asesor' : 'asesores'}
            </h3>
            <p className="text-xs text-orange-600 mt-0.5">
              Sin supervisor asignado — <strong>no entran en la rotación automática</strong>.
              Asignalos a un equipo para que reciban leads, o asignales leads manualmente desde
              la pantalla Asignación.
            </p>
          </div>
          <div className="divide-y divide-orange-50">
            {sinEquipo.map(u => (
              <div key={u.id} className="flex items-center gap-3 px-4 py-2.5 hover:bg-orange-50/40">
                <div className="w-7 h-7 bg-orange-100 rounded-full flex items-center justify-center text-orange-600 text-xs font-bold shrink-0">
                  {fullName(u)[0]?.toUpperCase() || 'A'}
                </div>
                <div className="flex-1 min-w-0 flex items-center gap-2">
                  <span className="text-sm text-gray-700 truncate">{fullName(u)}</span>
                  {/* Badge sutil que recuerda la consecuencia operacional
                      de no estar en equipo: el asesor existe y puede recibir
                      leads manualmente, pero queda fuera de la rotacion. */}
                  <span
                    className="text-[10px] uppercase tracking-wide font-semibold px-1.5 py-0.5 rounded border border-orange-200 bg-orange-100 text-orange-700 shrink-0"
                    title="Este asesor no recibe leads de la rotación automática hasta que vuelva a un equipo"
                  >
                    sin auto-asignación
                  </span>
                </div>

                <select
                  value={pendingMoves[u.id] || ''}
                  onChange={ev => setPendingMoves(p => ({ ...p, [u.id]: ev.target.value }))}
                  className="text-xs border border-gray-200 rounded-lg px-2 py-1.5 text-gray-600 focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white"
                >
                  <option value="">Asignar a supervisor...</option>
                  {supervisores.map(s => (
                    <option key={s.id} value={s.id}>{fullName(s)}</option>
                  ))}
                </select>

                {pendingMoves[u.id] && (
                  <button
                    onClick={() => handleAssign(u.id, pendingMoves[u.id])}
                    disabled={saving === u.id}
                    title="Confirmar asignación"
                    className="p-1.5 rounded-lg bg-[var(--brand-primary)] text-white hover:bg-[var(--brand-primary-hover)] disabled:opacity-50 shrink-0"
                  >
                    {saving === u.id ? <Loader size={12} className="animate-spin" /> : <Check size={12} />}
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {asesores.length === 0 && (
        <p className="text-center text-gray-400 text-sm py-8">No hay asesores configurados.</p>
      )}

      {isAdmin && (
        <ConfirmDialog
          open={confirmRemove !== null}
          title="Quitar del equipo"
          message={`¿Estás seguro de que deseas quitar a ${confirmRemove?.nombre ?? ''} de su equipo?`}
          confirmLabel="Quitar"
          variant="warning"
          onConfirm={handleConfirmRemove}
          onCancel={() => {
            // Tambien limpiar el pendingMove al cancelar — sin esto, si
            // el user elige "Quitar del equipo" en el dropdown, abre el
            // modal y cancela, el check rojo del confirmar queda atascado
            // hasta que cambie de seleccion manualmente.
            const cancelledId = confirmRemove?.asesorId
            setConfirmRemove(null)
            if (cancelledId) {
              setPendingMoves(p => { const n = { ...p }; delete n[cancelledId]; return n })
            }
          }}
        />
      )}
    </div>
  )
}

/** Gestión de catálogos de contacto: tipos y resultados */
function CatalogoList({ title, description, endpoint, reorderEndpoint, hasIcon }) {
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [showNew, setShowNew] = useState(false)
  const [newNombre, setNewNombre] = useState('')
  const [newIcono, setNewIcono] = useState('📋')
  const [editingId, setEditingId] = useState(null)
  const [editForm, setEditForm] = useState({})
  const [msg, setMsg] = useState(null)
  const [confirmDeleteId, setConfirmDeleteId] = useState(null)
  // Drag-and-drop state
  const [dragIndex, setDragIndex] = useState(null)
  const [dragOverIndex, setDragOverIndex] = useState(null)

  const load = () => {
    setLoading(true)
    api.get(endpoint)
      .then(r => setItems(r.data || []))
      .catch(() => {})
      .finally(() => setLoading(false))
  }
  useEffect(() => { load() }, [])

  const showMsg = (m) => { setMsg(m); setTimeout(() => setMsg(null), 3000) }

  const handleCreate = async () => {
    if (!newNombre.trim()) return
    setSaving(true)
    try {
      const r = await api.post(endpoint, { nombre: newNombre.trim(), icono: newIcono })
      setItems(prev => [...prev, r.data])
      setNewNombre(''); setNewIcono('📋'); setShowNew(false)
      showMsg({ ok: true, text: 'Creado correctamente.' })
    } catch (err) {
      showMsg({ ok: false, text: err.response?.data?.detail || 'Error al crear.' })
    } finally { setSaving(false) }
  }

  const startEdit = (item) => {
    setEditingId(item.id)
    setEditForm({ nombre: item.nombre, icono: item.icono || '' })
  }

  const handleSaveEdit = async (id) => {
    setSaving(true)
    try {
      const payload = { nombre: editForm.nombre || undefined }
      if (hasIcon) payload.icono = editForm.icono || undefined
      const r = await api.patch(`${endpoint}/${id}`, payload)
      setItems(prev => prev.map(i => i.id === id ? { ...i, ...r.data } : i))
      setEditingId(null)
      showMsg({ ok: true, text: 'Actualizado.' })
    } catch (err) {
      showMsg({ ok: false, text: err.response?.data?.detail || 'Error al guardar.' })
    } finally { setSaving(false) }
  }

  const handleDelete = (id) => { setConfirmDeleteId(id) }

  const handleConfirmDelete = async () => {
    const id = confirmDeleteId
    setConfirmDeleteId(null)
    try {
      await api.delete(`${endpoint}/${id}`)
      setItems(prev => prev.filter(i => i.id !== id))
      showMsg({ ok: true, text: 'Eliminado.' })
    } catch (err) {
      showMsg({ ok: false, text: err.response?.data?.detail || 'Error al eliminar.' })
    }
  }

  // ─── Drag and drop handlers ───────────────────────────────────────────────
  const handleDragStart = (e, index) => {
    setDragIndex(index)
    e.dataTransfer.effectAllowed = 'move'
  }
  const handleDragOver = (e, index) => {
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
    if (index !== dragOverIndex) setDragOverIndex(index)
  }
  const handleDrop = async (e, index) => {
    e.preventDefault()
    if (dragIndex === null || dragIndex === index) {
      setDragIndex(null); setDragOverIndex(null)
      return
    }
    const reordered = [...items]
    const [moved] = reordered.splice(dragIndex, 1)
    reordered.splice(index, 0, moved)
    setItems(reordered)
    setDragIndex(null); setDragOverIndex(null)
    if (reorderEndpoint) {
      try {
        await api.post(reorderEndpoint, { ids: reordered.map(i => i.id) })
      } catch {
        showMsg({ ok: false, text: 'Error al guardar el orden.' })
      }
    }
  }
  const handleDragEnd = () => { setDragIndex(null); setDragOverIndex(null) }

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-gray-800">{title}</h3>
          <p className="text-xs text-gray-400 mt-0.5">{description}</p>
        </div>
        <Button size="sm" variant="outline" onClick={() => setShowNew(true)} className="gap-1.5">
          <Plus size={12} /> Agregar
        </Button>
      </div>

      {msg && (
        <div className={`rounded-lg p-2.5 text-sm flex items-center gap-2 ${msg.ok ? 'bg-green-50 border border-green-200 text-green-800' : 'bg-red-50 border border-red-200 text-red-700'}`}>
          {msg.ok ? <CheckCircle size={13} /> : <XCircle size={13} />} {msg.text}
        </div>
      )}

      {showNew && (
        <div className="border border-indigo-200 bg-indigo-50/30 rounded-xl p-3 flex items-center gap-2">
          {hasIcon && (
            <input
              type="text"
              value={newIcono}
              onChange={e => setNewIcono(e.target.value)}
              className="w-12 text-center text-lg border border-gray-200 rounded-lg px-1 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-500"
              maxLength={2}
            />
          )}
          <input
            type="text"
            placeholder="Nombre…"
            value={newNombre}
            onChange={e => setNewNombre(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleCreate()}
            autoFocus
            className="flex-1 text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
          <button onClick={handleCreate} disabled={saving} className="p-2 rounded-lg bg-[var(--brand-primary)] text-white hover:bg-[var(--brand-primary-hover)]">
            <Check size={13} />
          </button>
          <button onClick={() => setShowNew(false)} className="p-2 rounded-lg hover:bg-gray-100 text-gray-400">
            <XIcon size={13} />
          </button>
        </div>
      )}

      {loading ? (
        <div className="h-16 bg-gray-100 rounded-xl animate-pulse" />
      ) : (
        <div className="border border-gray-100 rounded-xl overflow-hidden divide-y divide-gray-50">
          {items.length === 0 && (
            <p className="px-4 py-3 text-xs text-gray-400 italic">Sin elementos</p>
          )}
          {items.map((item, index) => (
            <div
              key={item.id}
              draggable={!!reorderEndpoint && editingId !== item.id}
              onDragStart={e => handleDragStart(e, index)}
              onDragOver={e => handleDragOver(e, index)}
              onDrop={e => handleDrop(e, index)}
              onDragEnd={handleDragEnd}
              className={dragOverIndex === index && dragIndex !== index
                ? 'border-t-2 border-indigo-400'
                : ''
              }
            >
              {editingId === item.id ? (
                <div className="flex items-center gap-2 px-4 py-2.5 bg-amber-50/40">
                  {hasIcon && (
                    <input
                      type="text"
                      value={editForm.icono}
                      onChange={e => setEditForm(p => ({ ...p, icono: e.target.value }))}
                      className="w-12 text-center text-lg border border-gray-200 rounded-lg px-1 py-1 focus:outline-none focus:ring-2 focus:ring-amber-400"
                      maxLength={2}
                    />
                  )}
                  <input
                    type="text"
                    value={editForm.nombre}
                    onChange={e => setEditForm(p => ({ ...p, nombre: e.target.value }))}
                    onKeyDown={e => e.key === 'Enter' && handleSaveEdit(item.id)}
                    autoFocus
                    className="flex-1 text-sm border border-gray-200 rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-amber-400"
                  />
                  <button onClick={() => handleSaveEdit(item.id)} disabled={saving} className="p-1.5 rounded-lg bg-amber-500 text-white hover:bg-amber-600">
                    <Check size={13} />
                  </button>
                  <button onClick={() => setEditingId(null)} className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-400">
                    <XIcon size={13} />
                  </button>
                </div>
              ) : (
                <div className={`flex items-center gap-2 px-2 py-2.5 hover:bg-gray-50/60 ${dragIndex === index ? 'opacity-40' : ''}`}>
                  {reorderEndpoint && (
                    <span className="text-gray-300 hover:text-gray-400 cursor-grab active:cursor-grabbing shrink-0 px-1">
                      <GripVertical size={14} />
                    </span>
                  )}
                  {item.icono && <span className="text-base">{item.icono}</span>}
                  <span className="flex-1 text-sm text-gray-700">{item.nombre}</span>
                  <div className="flex items-center gap-1">
                    <button
                      onClick={() => startEdit(item)}
                      className="p-1.5 rounded-lg hover:bg-amber-50 text-gray-300 hover:text-amber-500 transition-colors"
                      title="Editar"
                    >
                      <Pencil size={13} />
                    </button>
                    <button
                      onClick={() => handleDelete(item.id)}
                      className="p-1.5 rounded-lg hover:bg-red-50 text-gray-300 hover:text-red-400 transition-colors"
                      title="Eliminar"
                    >
                      <Trash2 size={13} />
                    </button>
                  </div>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={confirmDeleteId !== null}
        title="Desactivar elemento"
        message="¿Estás seguro de que deseas desactivar este elemento del catálogo?"
        confirmLabel="Desactivar"
        onConfirm={handleConfirmDelete}
        onCancel={() => setConfirmDeleteId(null)}
      />
    </div>
  )
}

function FuentesManager() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-base font-semibold text-gray-900">Fuentes / Canales de Captación</h2>
        <p className="text-xs text-gray-400 mt-0.5">
          Define las fuentes desde donde llegan los leads (wa mensaje, fb, ig, etc.).
          Los cambios se reflejan en el gráfico de fuentes del dashboard.
        </p>
      </div>
      <CatalogoList
        title="Fuentes"
        description="Fuentes de captación disponibles al registrar o importar leads"
        endpoint="/api/fuentes"
        reorderEndpoint="/api/fuentes/reorder"
      />
    </div>
  )
}

function CampanasManager() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-base font-semibold text-gray-900">Campañas de Marketing</h2>
        <p className="text-xs text-gray-400 mt-0.5">
          Gestiona las campañas disponibles al registrar o importar leads.
          Se usan para segmentar el origen de cada lead.
        </p>
      </div>
      <CatalogoList
        title="Campañas"
        description="Campañas de marketing disponibles al registrar o importar leads"
        endpoint="/api/campanas"
        reorderEndpoint="/api/campanas/reorder"
      />
    </div>
  )
}

function ContactPermissionsPanel() {
  const [perms, setPerms] = useState({ asesor_can_edit: false, asesor_can_delete: false })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState(null)

  useEffect(() => {
    api.get('/api/settings/contact-permissions')
      .then(res => setPerms(res.data))
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  const toggle = async (field) => {
    const updated = { ...perms, [field]: !perms[field] }
    setPerms(updated)
    setSaving(true)
    setMsg(null)
    try {
      await api.put('/api/settings/contact-permissions', updated)
      setMsg({ tipo: 'ok', texto: 'Permisos guardados' })
      setTimeout(() => setMsg(null), 2000)
    } catch (err) {
      setPerms(perms) // revert
      setMsg({ tipo: 'error', texto: err.response?.data?.detail || 'Error al guardar' })
    } finally { setSaving(false) }
  }

  if (loading) return null

  return (
    <div>
      <h2 className="text-base font-semibold text-gray-900">Permisos de Asesores</h2>
      <p className="text-xs text-gray-400 mt-0.5 mb-4">Controla qué pueden hacer los asesores con el historial de contactos.</p>
      <div className="space-y-3">
        <label className="flex items-center justify-between p-3 border border-gray-100 rounded-xl hover:bg-gray-50 cursor-pointer">
          <div>
            <p className="text-sm font-medium text-gray-700">Asesor puede editar contactos</p>
            <p className="text-xs text-gray-400">Permite al asesor modificar llamadas, mensajes y notas registradas (las citas siempre pueden ser editadas por asesores para actualizar fecha o estado).</p>
          </div>
          <Switch
            checked={perms.asesor_can_edit}
            onChange={() => toggle('asesor_can_edit')}
            disabled={saving}
            ariaLabel="Asesor puede editar contactos"
          />
        </label>
        <label className="flex items-center justify-between p-3 border border-gray-100 rounded-xl hover:bg-gray-50 cursor-pointer">
          <div>
            <p className="text-sm font-medium text-gray-700">Asesor puede eliminar contactos</p>
            <p className="text-xs text-gray-400">Permite al asesor eliminar registros del historial de contactos.</p>
          </div>
          <Switch
            checked={perms.asesor_can_delete}
            onChange={() => toggle('asesor_can_delete')}
            disabled={saving}
            ariaLabel="Asesor puede eliminar contactos"
          />
        </label>
      </div>
      {msg && <MsgBox msg={msg} />}
    </div>
  )
}

/** Personalización de marca: logo, nombre y colores */
function MarcaManager() {
  const brand        = useBrandStore((s) => s.brand)
  const setBrandLocal = useBrandStore((s) => s.setBrandLocal)
  const saveBrand    = useBrandStore((s) => s.saveBrand)
  const loadBrand    = useBrandStore((s) => s.loadBrand)

  const [draft, setDraft] = useState(brand)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState(null)
  const fileRef = useRef(null)
  const faviconRef = useRef(null)

  // Sincroniza el draft cuando llega la marca del backend
  useEffect(() => { setDraft(brand) }, [brand])

  const update = (field, value) => {
    const next = { ...draft, [field]: value }
    setDraft(next)
    setBrandLocal({ [field]: value })  // Live preview
  }

  /**
   * Lector genérico de archivos → data URL. Centraliza la validación de
   * tamaño y la lectura asincrónica para evitar duplicación entre logo
   * y favicon (DRY + SRP).
   */
  const readFileAsDataUrl = (file, { maxBytes, label, onOk }) => {
    if (!file) return
    if (file.size > maxBytes) {
      const kb = Math.round(maxBytes / 1024)
      setMsg({ tipo: 'error', texto: `${label} demasiado grande (máx ${kb} KB)` })
      return
    }
    const reader = new FileReader()
    reader.onload = () => onOk(reader.result)
    reader.readAsDataURL(file)
  }

  const handleFile = (e) => {
    readFileAsDataUrl(e.target.files?.[0], {
      maxBytes: 500 * 1024,
      label: 'Imagen',
      onOk: (dataUrl) => update('logo_data_url', dataUrl),
    })
  }

  const handleFaviconFile = (e) => {
    readFileAsDataUrl(e.target.files?.[0], {
      maxBytes: 100 * 1024,
      label: 'Favicon',
      onOk: (dataUrl) => update('favicon_data_url', dataUrl),
    })
  }

  const removeLogo = () => update('logo_data_url', null)
  const removeFavicon = () => update('favicon_data_url', null)

  const handleSave = async () => {
    setSaving(true)
    setMsg(null)
    try {
      await saveBrand(draft)
      setMsg({ tipo: 'ok', texto: 'Marca actualizada correctamente.' })
      setTimeout(() => setMsg(null), 3000)
    } catch (err) {
      setMsg({ tipo: 'error', texto: err.response?.data?.detail || 'Error al guardar.' })
    } finally {
      setSaving(false)
    }
  }

  const handleReset = async () => {
    setSaving(true)
    try {
      // Vuelve a cargar lo persistido (descarta cambios locales)
      await loadBrand()
      setMsg({ tipo: 'ok', texto: 'Cambios descartados.' })
      setTimeout(() => setMsg(null), 2000)
    } finally { setSaving(false) }
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-base font-semibold text-gray-900">Personalización de Marca</h2>
        <p className="text-xs text-gray-400 mt-0.5">Configura el logo, nombre y colores que se mostrarán en toda la plataforma.</p>
      </div>

      {msg && <MsgBox msg={msg} />}

      {/* Logo */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">Logo de la empresa</label>
        <div className="flex items-center gap-4">
          <div
            className="w-24 h-24 rounded-2xl border-2 border-dashed border-gray-200 flex items-center justify-center overflow-hidden shrink-0"
            style={{ backgroundColor: draft.logo_data_url ? '#f9fafb' : draft.primary_color }}
          >
            {draft.logo_data_url ? (
              <img src={draft.logo_data_url} alt="logo" className="w-full h-full object-contain" />
            ) : (
              <Building2 size={40} className="text-white/80" />
            )}
          </div>
          <div className="flex-1 space-y-2">
            <input
              ref={fileRef}
              type="file"
              accept="image/png,image/jpeg,image/svg+xml,image/webp"
              onChange={handleFile}
              className="hidden"
            />
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => fileRef.current?.click()} className="gap-1.5">
                <Upload size={13} /> Subir logo
              </Button>
              {draft.logo_data_url && (
                <Button variant="outline" size="sm" onClick={removeLogo} className="gap-1.5 text-red-600 hover:bg-red-50">
                  <Trash2 size={13} /> Quitar
                </Button>
              )}
            </div>
            <div className="text-xs text-gray-500 space-y-0.5">
              <p><span className="font-semibold text-gray-600">Tamaño recomendado:</span> 256×256 px (cuadrado)</p>
              <p><span className="font-semibold text-gray-600">Mínimo:</span> 128×128 px · <span className="font-semibold text-gray-600">Máximo:</span> 512×512 px</p>
              <p className="text-gray-400">Formatos: PNG, JPG, SVG o WEBP — Hasta 500 KB · Fondo transparente recomendado</p>
            </div>
          </div>
        </div>
      </div>

      {/* Favicon (icono de pestaña del navegador) */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">Favicon (icono de pestaña)</label>
        <div className="flex items-center gap-4">
          <div className="w-16 h-16 rounded-xl border-2 border-dashed border-gray-200 flex items-center justify-center overflow-hidden shrink-0 bg-white">
            {draft.favicon_data_url ? (
              <img src={draft.favicon_data_url} alt="favicon" className="w-full h-full object-contain" />
            ) : (
              <img src="/favicon.svg" alt="favicon default" className="w-full h-full object-contain" />
            )}
          </div>
          <div className="flex-1 space-y-2">
            <input
              ref={faviconRef}
              type="file"
              accept="image/png,image/svg+xml,image/x-icon,.ico"
              onChange={handleFaviconFile}
              className="hidden"
            />
            <div className="flex gap-2">
              <Button variant="outline" size="sm" onClick={() => faviconRef.current?.click()} className="gap-1.5">
                <Upload size={13} /> Subir favicon
              </Button>
              {draft.favicon_data_url && (
                <Button variant="outline" size="sm" onClick={removeFavicon} className="gap-1.5 text-red-600 hover:bg-red-50">
                  <Trash2 size={13} /> Quitar
                </Button>
              )}
            </div>
            <div className="text-xs text-gray-500 space-y-0.5">
              <p><span className="font-semibold text-gray-600">Tamaño recomendado:</span> 32×32 o 64×64 px (cuadrado)</p>
              <p className="text-gray-400">Formatos: ICO, PNG o SVG — Hasta 100 KB</p>
            </div>
          </div>
        </div>
      </div>

      {/* Nombre y subtítulo */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1.5">Nombre de la empresa</label>
          <input
            type="text"
            value={draft.company_name || ''}
            onChange={(e) => update('company_name', e.target.value)}
            placeholder="Mi Empresa"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-gray-700 mb-1.5">Subtítulo</label>
          <input
            type="text"
            value={draft.company_subtitle || ''}
            onChange={(e) => update('company_subtitle', e.target.value)}
            placeholder="Plataforma de Gestión"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>
      </div>

      {/* Colores */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">Colores de marca</label>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
          {[
            { key: 'primary_color', label: 'Color principal',     desc: 'Botones, enlaces y acentos' },
            { key: 'primary_hover', label: 'Color hover',         desc: 'Estado hover de botones' },
            { key: 'sidebar_bg',    label: 'Fondo del sidebar',   desc: 'Color de la barra lateral' },
            { key: 'accent_color',  label: 'Color de acento',     desc: 'Detalles y badges' },
          ].map(({ key, label, desc }) => (
            <div key={key} className="border border-gray-100 rounded-xl p-3 flex items-center gap-3">
              <input
                type="color"
                value={draft[key] || '#000000'}
                onChange={(e) => update(key, e.target.value)}
                className="w-12 h-12 rounded-lg cursor-pointer border border-gray-200 shrink-0"
              />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-medium text-gray-700">{label}</p>
                <p className="text-xs text-gray-400 truncate">{desc}</p>
                <input
                  type="text"
                  value={draft[key] || ''}
                  onChange={(e) => update(key, e.target.value)}
                  className="mt-1 w-full text-xs font-mono uppercase border border-gray-200 rounded px-2 py-1 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* Vista previa */}
      <div>
        <label className="block text-sm font-medium text-gray-700 mb-2">Vista previa</label>
        <div className="border border-gray-200 rounded-2xl overflow-hidden">
          <div className="flex">
            {/* Sidebar preview */}
            <div className="w-48 p-4 shrink-0" style={{ backgroundColor: draft.sidebar_bg }}>
              <div className="flex items-center gap-2.5">
                <div
                  className="w-9 h-9 rounded-xl flex items-center justify-center overflow-hidden shrink-0"
                  style={{ backgroundColor: draft.logo_data_url ? 'transparent' : draft.primary_color }}
                >
                  {draft.logo_data_url
                    ? <img src={draft.logo_data_url} alt="logo" className="w-full h-full object-contain" />
                    : <Building2 size={18} className="text-white" />}
                </div>
                <div className="min-w-0">
                  <p className="text-white text-xs font-bold truncate">{draft.company_name || '—'}</p>
                  <p className="text-white/60 text-[10px] truncate">{draft.company_subtitle || '—'}</p>
                </div>
              </div>
              <div className="mt-4 space-y-1.5">
                <div className="px-2 py-1.5 rounded-md text-xs text-white" style={{ backgroundColor: draft.primary_color }}>
                  Dashboard
                </div>
                <div className="px-2 py-1.5 rounded-md text-xs text-white/60">Leads</div>
                <div className="px-2 py-1.5 rounded-md text-xs text-white/60">Reportes</div>
              </div>
            </div>
            {/* Content preview */}
            <div className="flex-1 bg-gray-50 p-4">
              <div className="bg-white border border-gray-100 rounded-xl p-4">
                <h3 className="text-sm font-semibold text-gray-800 mb-2">Botones</h3>
                <div className="flex gap-2">
                  <button
                    className="px-3 py-1.5 rounded-lg text-xs font-medium text-white"
                    style={{ backgroundColor: draft.primary_color }}
                  >
                    Acción principal
                  </button>
                  <button
                    className="px-3 py-1.5 rounded-lg text-xs font-medium border"
                    style={{ borderColor: draft.primary_color, color: draft.primary_color }}
                  >
                    Secundario
                  </button>
                </div>
                <div className="mt-3 flex gap-2">
                  <span
                    className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold"
                    style={{ backgroundColor: draft.primary_color + '20', color: draft.primary_color }}
                  >
                    Activo
                  </span>
                  <span
                    className="inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-semibold"
                    style={{ backgroundColor: draft.accent_color + '20', color: draft.accent_color }}
                  >
                    Acento
                  </span>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Acciones */}
      <div className="flex gap-3 pt-2 border-t border-gray-100">
        <Button onClick={handleSave} disabled={saving}>
          {saving ? (
            <span className="flex items-center gap-2"><Loader size={14} className="animate-spin" />Guardando...</span>
          ) : 'Guardar cambios'}
        </Button>
        <Button variant="outline" onClick={handleReset} disabled={saving}>
          Descartar
        </Button>
      </div>
    </div>
  )
}

function ContactosManager() {
  return (
    <div className="space-y-6">
      <ContactPermissionsPanel />
      <div className="border-t border-gray-100" />
      <div>
        <h2 className="text-base font-semibold text-gray-900">Catálogos de Contacto</h2>
        <p className="text-xs text-gray-400 mt-0.5">Configura los canales de contacto y resultados disponibles en el registro de contactabilidad.</p>
      </div>
      <CatalogoList
        title="Tipos de Contacto"
        description="Canales de comunicación disponibles (Llamada, WhatsApp, Email, Presencial, Nota, etc.)"
        endpoint="/api/tipos-contacto"
        reorderEndpoint="/api/tipos-contacto/reorder"
        hasIcon
      />
      <div className="border-t border-gray-100" />
      <CatalogoList
        title="Resultados de Contacto"
        description="Resultados posibles al registrar un intento de contacto"
        endpoint="/api/resultados-contacto"
        reorderEndpoint="/api/resultados-contacto/reorder"
      />
      <div className="border-t border-gray-100" />
      <div>
        <h2 className="text-base font-semibold text-gray-900">Catálogos de Cita</h2>
        <p className="text-xs text-gray-400 mt-0.5">Configura las modalidades y ubicaciones disponibles al agendar citas con los leads.</p>
      </div>
      <CatalogoList
        title="Tipos de Cita"
        description="Modalidades y lugares de atención (Cita oficina Bustamante, Cita oficina Umacollo, Cita Virtual, etc.)"
        endpoint="/api/tipos-cita"
        reorderEndpoint="/api/tipos-cita/reorder"
        hasIcon
      />
    </div>
  )
}

/** Diagnóstico del pipeline WhatsApp — verifica si el webhook recibe. */
function WhatsAppDiagnostics() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)

  const load = useCallback(() => {
    setLoading(true)
    api.get('/api/whatsapp/diagnostics')
      .then(r => setData(r.data))
      .catch(() => setData({ error: true }))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  if (!data) {
    return <div className="h-32 bg-gray-100 rounded-xl animate-pulse" />
  }
  if (data.error) {
    return (
      <div className="rounded-lg bg-red-50 border border-red-200 p-3 text-xs text-red-700">
        No se pudo obtener diagnóstico.
      </div>
    )
  }

  const { stats, config } = data
  const babas       = data.babas || []
  const babasCount  = data.babas_count || 0
  const babasActive = babas.filter(b => b.activo).length
  const babasDefault = babas.find(b => b.is_default)
  const lastInbound = stats.last_inbound_at ? new Date(stats.last_inbound_at) : null
  const minutesSince = lastInbound
    ? Math.floor((Date.now() - lastInbound.getTime()) / 60000)
    : null

  // Heuristica del estado: si nunca entro un mensaje o pasaron > 60 min sin
  // ningun inbound y no se recibio nada en la ultima hora, alertamos.
  const healthOk = stats.inbound_5min > 0 || (lastInbound && minutesSince < 60)
  const healthLabel = healthOk ? 'Recibiendo mensajes' : 'Sin actividad reciente'
  const healthCls = healthOk
    ? 'bg-green-50 border-green-200 text-green-800'
    : 'bg-amber-50 border-amber-200 text-amber-800'

  // ── Diagnostico inteligente del estado WhatsApp ───────────────────
  // Modelo del producto V034+: las WABAs viven en DB (UI). El backend
  // (whatsapp.py:326-356 y 117-160) busca verify_token y app_secret en
  // este orden: primero por WABA en DB, despues fallback al env.
  // Por lo tanto las env vars NO son necesarias si las WABAs en DB
  // tienen ambos secrets configurados.
  //
  // Logica del semaforo:
  // 1. Por cada WABA en DB: chequear si tiene has_verify_token Y
  //    has_app_secret. Si todas las activas los tienen -> ok por UI.
  // 2. Si hay WABAs pero alguna no tiene secrets -> amarillo
  //    (configurarlos en la UI editando la WABA).
  // 3. Si no hay WABAs en DB: chequear env vars. Si estan -> ok modo
  //    legacy. Si no -> rojo, falta todo.
  const hasUiWaba   = babasCount > 0
  const activeBabas = babas.filter(b => b.activo)
  const babasFullyConfigured = activeBabas.length > 0 && activeBabas.every(
    b => b.has_verify_token && b.has_app_secret
  )
  const babasPartial = hasUiWaba && !babasFullyConfigured
  const hasEnvVerify = config.verify_token_set
  const hasEnvSecret = config.app_secret_set
  const hasEnvFallback = hasEnvVerify && hasEnvSecret

  // OK si: (cada WABA activa tiene sus secrets) o (hay env fallback aunque
  // las WABAs no esten completas). El backend usa el primero que matchee.
  const allConfigured = babasFullyConfigured || (hasUiWaba && hasEnvFallback)

  const fmt = (ts) => {
    if (!ts) return '—'
    return new Date(ts).toLocaleString('es-PE', {
      day: '2-digit', month: '2-digit', year: '2-digit',
      hour: '2-digit', minute: '2-digit',
    })
  }

  const Tile = ({ label, value, hint }) => (
    <div className="rounded-lg border border-gray-200 bg-white px-3 py-2.5">
      <p className="text-[10px] uppercase tracking-wide text-gray-400 font-semibold">{label}</p>
      <p className="text-lg font-bold text-gray-900 mt-0.5 tabular-nums">{value}</p>
      {hint && <p className="text-[10px] text-gray-400 mt-0.5">{hint}</p>}
    </div>
  )

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-gray-900">Diagnóstico del webhook</h3>
          <p className="text-xs text-gray-400 mt-0.5">
            Verifica si Meta está entregando mensajes al CRM.
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-gray-200 hover:bg-gray-50 disabled:opacity-50"
        >
          <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          {loading ? 'Cargando...' : 'Refrescar'}
        </button>
      </div>

      <div className={`rounded-lg border p-3 text-xs ${healthCls}`}>
        <div className="flex items-center justify-between">
          <span className="font-semibold">{healthLabel}</span>
          <span>
            Último entrante: {fmt(stats.last_inbound_at)}
            {minutesSince != null && ` (hace ${minutesSince} min)`}
          </span>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <Tile label="Últimos 5 min" value={stats.inbound_5min} hint="entrantes" />
        <Tile label="Última hora"   value={stats.inbound_1h}   hint="entrantes" />
        <Tile label="Últimas 24h"   value={stats.inbound_24h}  hint="entrantes" />
        <Tile label="Salientes 24h" value={stats.outbound_24h} hint="enviados" />
      </div>

      {stats.audit_7d && (
        <div className="rounded-lg border border-emerald-100 bg-emerald-50/50 p-3 space-y-1.5 text-xs">
          <div className="flex items-center justify-between text-emerald-900 font-semibold">
            <span>Auditoría últimos 7 días</span>
            <span className="text-[11px] font-normal text-emerald-700">Conciliación Meta Ads / WhatsApp</span>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2 pt-1">
            <div className="bg-white rounded-md p-2 border border-emerald-100">
              <p className="text-[10px] text-gray-500 font-medium uppercase">Webhooks entrantes</p>
              <p className="text-base font-bold text-gray-900 mt-0.5">{stats.audit_7d.inbound_messages}</p>
            </div>
            <div className="bg-white rounded-md p-2 border border-emerald-100">
              <p className="text-[10px] text-gray-500 font-medium uppercase">Con Anuncio CTWA</p>
              <p className="text-base font-bold text-emerald-700 mt-0.5">{stats.audit_7d.events_with_referral}</p>
            </div>
            <div className="bg-white rounded-md p-2 border border-emerald-100">
              <p className="text-[10px] text-gray-500 font-medium uppercase">Leads creados</p>
              <p className="text-base font-bold text-emerald-700 mt-0.5">{stats.audit_7d.leads_created}</p>
            </div>
            <div className="bg-white rounded-md p-2 border border-emerald-100">
              <p className="text-[10px] text-gray-500 font-medium uppercase">Leads emparejados</p>
              <p className="text-base font-bold text-sky-700 mt-0.5">{stats.audit_7d.leads_matched}</p>
            </div>
          </div>
        </div>
      )}

      <div className="rounded-lg border border-gray-200 bg-gray-50/60 p-3 space-y-2">
        <div className="flex items-center justify-between">
          <p className="text-xs font-semibold text-gray-700">Estado de la integración</p>
          <span
            className={
              'text-[10px] font-semibold px-2 py-0.5 rounded-full ' +
              (allConfigured
                ? 'bg-green-100 text-green-800'
                : hasUiWaba
                  ? 'bg-amber-100 text-amber-800'
                  : 'bg-red-100 text-red-700')
            }
          >
            {allConfigured
              ? 'Operativo'
              : babasPartial
                ? 'Completar credenciales en WABA'
                : 'Sin WABA registrada'}
          </span>
        </div>

        {/* WABAs registradas en UI */}
        <div className="text-xs">
          <div className="flex items-center gap-1.5 mb-1">
            {babasFullyConfigured
              ? <CheckCircle size={12} className="text-green-600" />
              : babasPartial
                ? <XCircle    size={12} className="text-amber-500" />
                : <XCircle    size={12} className="text-red-500" />}
            <span className={babasFullyConfigured ? 'text-gray-700' : babasPartial ? 'text-amber-700' : 'text-red-700'}>
              {hasUiWaba
                ? babasActive + ' de ' + babasCount + ' cuenta' + (babasCount !== 1 ? 's' : '') + ' WABA activa' + (babasActive !== 1 ? 's' : '')
                : 'No hay cuentas WABA registradas'}
            </span>
          </div>
          {babasFullyConfigured && babasDefault && (
            <p className="text-[11px] text-gray-500 ml-5">
              Default: <span className="font-medium text-gray-700">{babasDefault.display_name}</span>
              {' · '}
              <span className="text-green-700">verify_token + app_secret OK</span>
            </p>
          )}
          {babasPartial && (
            <p className="text-[11px] text-amber-700 ml-5">
              Alguna WABA activa no tiene verify_token o app_secret. Edítala en la sección de arriba (lápiz) y completa los campos.
            </p>
          )}
          {!hasUiWaba && (
            <p className="text-[11px] text-red-700 ml-5">
              Registrá una WABA en la sección de arriba para empezar a recibir/enviar mensajes.
            </p>
          )}
        </div>

      </div>

      {!healthOk && allConfigured && (
        <div className="rounded-lg bg-sky-50 border border-sky-200 p-3 text-xs text-sky-900 space-y-1">
          <p className="font-semibold">¿Por qué no llegan mensajes?</p>
          <ul className="list-disc pl-4 space-y-0.5 text-sky-800">
            <li>Verifica que el número escrito esté hablando al WhatsApp Business correcto.</li>
            <li>En Meta Business Manager → Webhooks, confirma que el evento <span className="font-semibold">messages</span> esté suscrito.</li>
            <li>Prueba el endpoint de verificación: GET /api/whatsapp/webhook con hub.challenge.</li>
            <li>Revisa los logs del backend después de enviar un mensaje de prueba.</li>
          </ul>
        </div>
      )}
    </div>
  )
}

function WhatsAppAuditLog() {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [hasReferral, setHasReferral] = useState(null)
  const [outcome, setOutcome] = useState('')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const [selectedPayload, setSelectedPayload] = useState(null)
  const [showAdBreakdown, setShowAdBreakdown] = useState(false)
  const limit = 30

  const fetchAudit = useCallback(() => {
    setLoading(true)
    const params = { limit, offset: page * limit }
    if (hasReferral !== null) params.has_referral = hasReferral
    if (outcome) params.outcome = outcome
    if (search.trim()) params.search = search.trim()

    api.get('/api/whatsapp/audit-events', { params })
      .then(res => setData(res.data))
      .catch(() => setData({ error: true }))
      .finally(() => setLoading(false))
  }, [hasReferral, outcome, search, page])

  useEffect(() => {
    fetchAudit()
  }, [fetchAudit])

  const summary = data?.summary || {}
  const events = data?.events || []
  const adBreakdown = summary.ad_breakdown || []

  const fmtDate = (iso) => {
    if (!iso) return '—'
    return new Date(iso).toLocaleString('es-PE', {
      day: '2-digit', month: '2-digit', year: '2-digit',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    })
  }

  const getOutcomeBadge = (out) => {
    switch (out) {
      case 'lead_created':
      case 'lead_attributed':
        return (
          <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-emerald-700 bg-emerald-50 border border-emerald-200 px-2 py-0.5 rounded-full">
            <CheckCircle size={10} /> Lead creado
          </span>
        )
      case 'lead_matched':
      case 'lead_matched_existing':
        return (
          <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-sky-700 bg-sky-50 border border-sky-200 px-2 py-0.5 rounded-full">
            <Users size={10} /> Lead existente
          </span>
        )
      case 'lead_matched_duplicate':
        return (
          <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-amber-700 bg-amber-50 border border-amber-200 px-2 py-0.5 rounded-full">
            <AlertTriangle size={10} /> Duplicado
          </span>
        )
      case 'message_received':
        return (
          <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-gray-700 bg-gray-100 border border-gray-200 px-2 py-0.5 rounded-full">
            <MessageCircle size={10} /> Mensaje
          </span>
        )
      case 'message_organic_no_lead':
        return (
          <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-slate-700 bg-slate-100 border border-slate-200 px-2 py-0.5 rounded-full">
            <MessageCircle size={10} /> Orgánico sin lead
          </span>
        )
      case 'message_lead_matched':
        return (
          <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-blue-700 bg-blue-50 border border-blue-200 px-2 py-0.5 rounded-full">
            <UserCheck size={10} /> Chat recurrente
          </span>
        )
      case 'duplicate_message':
        return (
          <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-purple-700 bg-purple-50 border border-purple-200 px-2 py-0.5 rounded-full">
            <Clock size={10} /> Msg duplicado
          </span>
        )
      case 'lead_creation_failed':
      case 'referral_error':
      case 'webhook_processing_failed':
        return (
          <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-red-700 bg-red-50 border border-red-200 px-2 py-0.5 rounded-full">
            <XCircle size={10} /> Error
          </span>
        )
      default:
        if (out && out.startsWith('status_')) {
          return (
            <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-indigo-700 bg-indigo-50 border border-indigo-200 px-2 py-0.5 rounded-full">
              {out.replace('status_', 'Estado: ')}
            </span>
          )
        }
        return (
          <span className="inline-flex items-center gap-1 text-[10px] font-semibold text-gray-600 bg-gray-50 border border-gray-200 px-2 py-0.5 rounded-full">
            {out}
          </span>
        )
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <ShieldCheck size={16} className="text-emerald-600" />
            Auditoría Continua de Webhooks (Meta Ads & WhatsApp)
          </h3>
          <p className="text-xs text-gray-400 mt-0.5">
            Registro forense de cada evento recibido de Meta: atribución de anuncios Click-to-WhatsApp, creación de leads y conciliación en vivo.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowAdBreakdown(!showAdBreakdown)}
            className="inline-flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg border border-gray-200 hover:bg-gray-50 text-gray-700"
          >
            <Megaphone size={12} className="text-[var(--brand-primary)]" />
            {showAdBreakdown ? 'Ocultar anuncios' : 'Ver por anuncio'}
          </button>
          <button
            type="button"
            onClick={fetchAudit}
            disabled={loading}
            className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-gray-200 hover:bg-gray-50 text-gray-700 disabled:opacity-50"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
            {loading ? 'Cargando...' : 'Refrescar'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        <div className="rounded-xl border border-gray-200 bg-white p-3 shadow-xs">
          <p className="text-[10px] uppercase tracking-wide text-gray-400 font-semibold">Total Eventos</p>
          <p className="text-xl font-bold text-gray-900 mt-0.5 tabular-nums">{summary.total_events ?? '—'}</p>
          <p className="text-[10px] text-gray-400 mt-0.5">{summary.inbound_messages ?? 0} mensajes entrantes</p>
        </div>
        <div className="rounded-xl border border-emerald-100 bg-emerald-50/40 p-3 shadow-xs">
          <p className="text-[10px] uppercase tracking-wide text-emerald-700 font-semibold">Con Anuncio (CTWA)</p>
          <p className="text-xl font-bold text-emerald-800 mt-0.5 tabular-nums">{summary.events_with_referral ?? '—'}</p>
          <p className="text-[10px] text-emerald-600 mt-0.5">{summary.unique_referral_phones ?? 0} teléfonos únicos</p>
        </div>
        <div className="rounded-xl border border-emerald-100 bg-emerald-50/40 p-3 shadow-xs">
          <p className="text-[10px] uppercase tracking-wide text-emerald-700 font-semibold">Leads Creados</p>
          <p className="text-xl font-bold text-emerald-800 mt-0.5 tabular-nums">{summary.leads_created ?? '—'}</p>
          <p className="text-[10px] text-emerald-600 mt-0.5">atribución automática</p>
        </div>
        <div className="rounded-xl border border-sky-100 bg-sky-50/40 p-3 shadow-xs">
          <p className="text-[10px] uppercase tracking-wide text-sky-700 font-semibold">Leads Existentes</p>
          <p className="text-xl font-bold text-sky-800 mt-0.5 tabular-nums">{summary.leads_matched ?? '—'}</p>
          <p className="text-[10px] text-sky-600 mt-0.5">emparejados por teléfono</p>
        </div>
      </div>

      {showAdBreakdown && adBreakdown.length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white p-4 space-y-2">
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-semibold text-gray-900 flex items-center gap-1.5">
              <Megaphone size={13} className="text-[var(--brand-primary)]" />
              Rendimiento por Anuncio Meta Ads (Click-to-WhatsApp)
            </h4>
            <span className="text-[11px] text-gray-400">{adBreakdown.length} anuncios activos</span>
          </div>
          <div className="overflow-x-auto max-h-56 overflow-y-auto">
            <table className="w-full text-left text-xs">
              <thead className="text-[10px] uppercase text-gray-400 bg-gray-50 border-y border-gray-100">
                <tr>
                  <th className="py-1.5 px-2">Anuncio / Titular</th>
                  <th className="py-1.5 px-2">Ad ID</th>
                  <th className="py-1.5 px-2 text-right">Mensajes</th>
                  <th className="py-1.5 px-2 text-right">Teléfonos</th>
                  <th className="py-1.5 px-2 text-right">Leads CRM</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 text-gray-700">
                {adBreakdown.map((ad, idx) => (
                  <tr key={idx} className="hover:bg-gray-50/80">
                    <td className="py-2 px-2 font-medium text-gray-900 max-w-xs truncate" title={ad.headline}>
                      {ad.headline}
                    </td>
                    <td className="py-2 px-2 font-mono text-[11px] text-gray-500">
                      {ad.referral_ad_id}
                    </td>
                    <td className="py-2 px-2 text-right tabular-nums">
                      {ad.total_events}
                    </td>
                    <td className="py-2 px-2 text-right tabular-nums">
                      {ad.unique_phones}
                    </td>
                    <td className="py-2 px-2 text-right tabular-nums font-semibold text-emerald-700">
                      {ad.leads_created}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2 pt-1">
        <div className="relative flex-1 min-w-[200px]">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            value={search}
            onChange={e => setSearch(e.target.value)}
            placeholder="Buscar por teléfono, titular o contacto..."
            className="w-full pl-8 pr-3 py-1.5 text-xs rounded-lg border border-gray-200 focus:outline-none focus:ring-1 focus:ring-[var(--brand-primary)] bg-white"
          />
        </div>

        <div className="flex items-center gap-1 bg-gray-100 p-0.5 rounded-lg text-xs">
          <button
            type="button"
            onClick={() => { setHasReferral(null); setPage(0); }}
            className={'px-2.5 py-1 rounded-md transition-colors ' + (hasReferral === null ? 'bg-white font-medium text-gray-900 shadow-xs' : 'text-gray-600 hover:text-gray-900')}
          >
            Todos
          </button>
          <button
            type="button"
            onClick={() => { setHasReferral(true); setPage(0); }}
            className={'px-2.5 py-1 rounded-md transition-colors flex items-center gap-1 ' + (hasReferral === true ? 'bg-white font-medium text-emerald-800 shadow-xs' : 'text-gray-600 hover:text-gray-900')}
          >
            <Megaphone size={11} className="text-emerald-600" /> Solo Anuncios CTWA
          </button>
        </div>

        <select
          value={outcome}
          onChange={e => { setOutcome(e.target.value); setPage(0); }}
          className="py-1.5 px-2.5 text-xs rounded-lg border border-gray-200 bg-white text-gray-700 focus:outline-none focus:ring-1 focus:ring-[var(--brand-primary)]"
        >
          <option value="">Todos los resultados</option>
          <option value="lead_created">Lead creado</option>
          <option value="lead_attributed">Lead atribuido</option>
          <option value="lead_matched">Lead existente</option>
          <option value="lead_matched_duplicate">Lead duplicado</option>
          <option value="message_received">Mensaje recibido</option>
          <option value="duplicate_message">Msg duplicado</option>
          <option value="lead_creation_failed">Error en creación</option>
        </select>
      </div>

      <div className="rounded-xl border border-gray-200 bg-white overflow-hidden shadow-xs">
        <div className="overflow-x-auto max-h-96 overflow-y-auto">
          <table className="w-full text-left text-xs">
            <thead className="text-[10px] uppercase text-gray-400 bg-gray-50 border-b border-gray-100 sticky top-0 z-10">
              <tr>
                <th className="py-2 px-3">Fecha y Hora</th>
                <th className="py-2 px-3">Remitente</th>
                <th className="py-2 px-3">Anuncio (CTWA)</th>
                <th className="py-2 px-3">Resultado</th>
                <th className="py-2 px-3">Lead / Asesor</th>
                <th className="py-2 px-3 text-right">Forense</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 text-gray-700">
              {events.length === 0 ? (
                <tr>
                  <td colSpan={6} className="py-8 text-center text-gray-400">
                    {loading ? 'Cargando eventos de auditoría...' : 'No hay eventos de auditoría registrados con los filtros seleccionados.'}
                  </td>
                </tr>
              ) : (
                events.map(ev => (
                  <tr key={ev.id} className="hover:bg-gray-50/70">
                    <td className="py-2.5 px-3 text-gray-500 whitespace-nowrap">
                      {fmtDate(ev.received_at)}
                    </td>
                    <td className="py-2.5 px-3 whitespace-nowrap">
                      <div className="font-mono text-gray-900 font-medium">{ev.wa_phone || '—'}</div>
                      {ev.contact_name && <div className="text-[10px] text-gray-400">{ev.contact_name}</div>}
                    </td>
                    <td className="py-2.5 px-3 max-w-[220px]">
                      {ev.has_referral ? (
                        <div>
                          <div className="font-medium text-gray-900 truncate" title={ev.referral_headline || 'Anuncio sin titular'}>
                            {ev.referral_headline || 'Anuncio Click-to-WhatsApp'}
                          </div>
                          {ev.referral_ad_id && (
                            <div className="font-mono text-[10px] text-gray-400">
                              Ad ID: {ev.referral_ad_id}
                            </div>
                          )}
                        </div>
                      ) : (
                        <span className="text-gray-400 text-[11px]">Orgánico / Directo</span>
                      )}
                    </td>
                    <td className="py-2.5 px-3 whitespace-nowrap">
                      {getOutcomeBadge(ev.outcome)}
                      {ev.error_detail && (
                        <div className="text-[10px] text-red-600 truncate max-w-[180px]" title={ev.error_detail}>
                          {ev.error_detail}
                        </div>
                      )}
                    </td>
                    <td className="py-2.5 px-3 whitespace-nowrap">
                      {ev.lead_id ? (
                        <div>
                          <a
                            href={'/leads/' + ev.lead_id}
                            target="_blank"
                            rel="noreferrer"
                            className="font-medium text-[var(--brand-primary)] hover:underline"
                          >
                            Lead #{ev.lead_id}
                          </a>
                          {ev.asesor_nombre ? (
                            <div className="text-[10px] text-gray-500 truncate max-w-[140px]" title={ev.asesor_nombre}>
                              {ev.asesor_nombre}
                            </div>
                          ) : (
                            <div className="text-[10px] text-amber-600">Sin asesor</div>
                          )}
                        </div>
                      ) : (
                        <span className="text-gray-400 text-[11px]">—</span>
                      )}
                    </td>
                    <td className="py-2.5 px-3 text-right whitespace-nowrap">
                      <button
                        type="button"
                        onClick={() => setSelectedPayload(ev.payload || ev.metadata)}
                        className="inline-flex items-center gap-1 text-[11px] text-gray-500 hover:text-gray-900 hover:bg-gray-100 px-2 py-1 rounded-md transition-colors"
                        title="Inspeccionar JSON crudo de Meta"
                      >
                        <Eye size={12} /> Payload
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        <div className="p-2 border-t border-gray-100 flex items-center justify-between text-xs text-gray-500 bg-gray-50/50">
          <span>Página {page + 1}</span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setPage(p => Math.max(0, p - 1))}
              disabled={page === 0 || loading}
              className="px-2 py-1 rounded border border-gray-200 bg-white hover:bg-gray-50 disabled:opacity-40"
            >
              Anterior
            </button>
            <button
              type="button"
              onClick={() => setPage(p => p + 1)}
              disabled={events.length < limit || loading}
              className="px-2 py-1 rounded border border-gray-200 bg-white hover:bg-gray-50 disabled:opacity-40"
            >
              Siguiente
            </button>
          </div>
        </div>
      </div>

      {selectedPayload && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="bg-white rounded-2xl shadow-xl max-w-2xl w-full p-5 space-y-3">
            <div className="flex items-center justify-between border-b border-gray-100 pb-2">
              <h4 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
                <Database size={15} className="text-emerald-600" />
                Payload Original del Webhook (Meta Graph API)
              </h4>
              <button
                type="button"
                onClick={() => setSelectedPayload(null)}
                className="text-gray-400 hover:text-gray-600 p-1 rounded-lg"
              >
                <XIcon size={16} />
              </button>
            </div>
            <p className="text-xs text-gray-500">
              Datos crudos transmitidos por Meta para auditoría y verificación técnica:
            </p>
            <pre className="p-3 bg-gray-950 text-emerald-400 text-xs rounded-xl overflow-x-auto max-h-96 font-mono leading-relaxed">
              {JSON.stringify(selectedPayload, null, 2)}
            </pre>
            <div className="flex justify-end pt-2">
              <button
                type="button"
                onClick={() => setSelectedPayload(null)}
                className="px-4 py-1.5 text-xs font-semibold rounded-lg bg-gray-100 hover:bg-gray-200 text-gray-700"
              >
                Cerrar
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

/**
 * Gestor de chips del Chat — categorias IA, urgencia y bandejas del sidebar.
 * Cada label tiene key (inmutable, contrato interno) y label/color/icon
 * editables. Solo admin puede tocarlos.
 */
const CHIP_ICON_OPTIONS = [
  'Sparkles', 'MessageCircle', 'AlertCircle', 'Archive', 'Flame', 'Clock',
  'Tag', 'UserCheck', 'Layers', 'Wand2', 'Check', 'CheckCheck', 'Send',
]

const KIND_META = {
  category: {
    title: 'Categorías IA',
    description: 'Chips que muestra el clasificador automático sobre cada chat (Potencial, Cliente, Consulta, ...).',
  },
  urgency: {
    title: 'Urgencia',
    description: 'Marcas adicionales que la IA agrega cuando detecta prioridad alta.',
  },
  inbox: {
    title: 'Bandejas del sidebar',
    description: 'Opciones del filtro por bandeja (Clientes potenciales, Requieren revisión, ...).',
  },
}

function IconDot({ name, color }) {
  // En Configuración no necesitamos renderizar el icono real — basta con
  // un circulo de color + el nombre. El icono real se renderiza en Chat.jsx.
  return (
    <span
      className="inline-flex items-center justify-center w-5 h-5 rounded-full border text-[9px] font-bold"
      style={{ backgroundColor: color + '22', color, borderColor: color + '66' }}
      title={name}
    >
      {name[0]}
    </span>
  )
}

function ChipsLabelsManager() {
  const [labels, setLabels] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [edits, setEdits] = useState({}) // { [id]: {label, color_hex, icon_name, activo} }
  const [saving, setSaving] = useState({}) // { [id]: bool }
  const [toast, setToast] = useState(null)
  const [confirmResetOpen, setConfirmResetOpen] = useState(false)
  const [resetting, setResetting] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const { data } = await api.get('/api/whatsapp/ui-labels')
      setLabels(data || [])
      setEdits({})
    } catch (e) {
      setError(e.response?.data?.detail || 'No se pudieron cargar los chips.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  const getValue = (row, field) => {
    const edit = edits[row.id]
    if (edit && field in edit) return edit[field]
    return row[field]
  }

  const patch = (id, field, value) => {
    setEdits(prev => ({ ...prev, [id]: { ...(prev[id] || {}), [field]: value } }))
  }

  const isDirty = id => edits[id] && Object.keys(edits[id]).length > 0

  const save = async row => {
    const payload = edits[row.id]
    if (!payload) return
    setSaving(prev => ({ ...prev, [row.id]: true }))
    try {
      const { data } = await api.patch(`/api/whatsapp/ui-labels/${row.id}`, payload)
      setLabels(ls => ls.map(l => l.id === row.id ? data : l))
      setEdits(prev => {
        const { [row.id]: _omit, ...rest } = prev
        return rest
      })
      setToast({ type: 'ok', msg: 'Guardado' })
      setTimeout(() => setToast(null), 2000)
    } catch (e) {
      setToast({ type: 'err', msg: e.response?.data?.detail || 'Error al guardar' })
      setTimeout(() => setToast(null), 3500)
    } finally {
      setSaving(prev => ({ ...prev, [row.id]: false }))
    }
  }

  const cancel = id => {
    setEdits(prev => {
      const { [id]: _omit, ...rest } = prev
      return rest
    })
  }

  const resetDefaults = async () => {
    setResetting(true)
    try {
      await api.post('/api/whatsapp/ui-labels/reset-defaults')
      await load()
      setToast({ type: 'ok', msg: 'Valores de fábrica restaurados' })
      setTimeout(() => setToast(null), 2500)
    } catch (e) {
      setToast({ type: 'err', msg: e.response?.data?.detail || 'Error al restaurar' })
      setTimeout(() => setToast(null), 3500)
    } finally {
      setResetting(false)
      setConfirmResetOpen(false)
    }
  }

  if (loading) return <div className="py-8 text-center text-gray-500">Cargando chips...</div>
  if (error) return <div className="p-4 text-sm text-red-600 bg-red-50 rounded">{error}</div>

  const byKind = labels.reduce((acc, l) => {
    (acc[l.kind] = acc[l.kind] || []).push(l)
    return acc
  }, {})

  return (
    <div className="space-y-6">
      {/* Nota ayudante + accion secundaria a la derecha. El titulo grande
          ya lo pone el header de la pagina (TAB "Categorias Chat"), por
          eso no repetimos <h2>. */}
      <div className="flex items-start justify-between gap-4">
        <p className="text-xs text-gray-500 max-w-2xl">
          La <span className="font-mono text-gray-600">clave</span> es inmutable — es el contrato
          con el backend y el clasificador IA. Solo texto, color e ícono son editables.
        </p>
        <Button variant="outline" size="sm" onClick={() => setConfirmResetOpen(true)} className="shrink-0">
          Restaurar defaults
        </Button>
      </div>

      <ConfirmDialog
        open={confirmResetOpen}
        title="Restaurar valores de fábrica"
        message="¿Restaurar TODOS los chips (categorías, urgencia y bandejas) a los valores de fábrica? Se sobreescribirán los textos, colores e íconos personalizados."
        confirmLabel={resetting ? 'Restaurando…' : 'Restaurar'}
        cancelLabel="Cancelar"
        variant="warning"
        onConfirm={resetDefaults}
        onCancel={() => { if (!resetting) setConfirmResetOpen(false) }}
      />

      {toast && (
        <div className={`text-sm px-3 py-2 rounded-lg ${toast.type === 'ok' ? 'bg-green-50 text-green-700 border border-green-200' : 'bg-red-50 text-red-700 border border-red-200'}`}>
          {toast.msg}
        </div>
      )}

      {['category', 'urgency', 'inbox'].map(kind => {
        const rows = byKind[kind] || []
        if (rows.length === 0) return null
        const meta = KIND_META[kind]
        // Grid template compartido entre header y filas (patrón tabla herramientas premium).
        // IMPORTANTE: las clases deben ser literales — Tailwind JIT NO detecta
        // interpolación en template literals, así que no usar `md:${...}`.
        return (
          <section key={kind}>
            <header className="mb-2">
              <h3 className="text-sm font-semibold text-gray-900">{meta.title}</h3>
              <p className="text-xs text-gray-500 mt-0.5">{meta.description}</p>
            </header>

            <div className="bg-white border border-gray-200 rounded-xl overflow-hidden">
              {/* Header de tabla — se muestra una sola vez por seccion */}
              <div className="hidden md:grid md:grid-cols-[32px_140px_1fr_180px_150px_auto] gap-3 px-4 py-2.5 bg-gray-50 border-b border-gray-100 text-[10px] font-bold uppercase tracking-[0.06em] text-gray-500">
                <span />
                <span>Clave</span>
                <span>Texto visible</span>
                <span>Color</span>
                <span>Ícono</span>
                <span className="text-right">Acciones</span>
              </div>

              <div className="divide-y divide-gray-100">
                {rows.map(row => {
                  const curLabel = getValue(row, 'label')
                  const curColor = getValue(row, 'color_hex')
                  const curIcon  = getValue(row, 'icon_name')
                  const curActivo = getValue(row, 'activo')
                  const dirty = isDirty(row.id)
                  const isSaving = !!saving[row.id]

                  return (
                    <div
                      key={row.id}
                      className="grid grid-cols-1 md:grid-cols-[32px_140px_1fr_180px_150px_auto] gap-3 px-4 py-3 items-center hover:bg-gray-50/60 transition-colors"
                    >
                      <div className="shrink-0">
                        <IconDot name={curIcon} color={curColor} />
                      </div>
                      <code className="text-[11px] text-gray-600 font-mono truncate" title={row.key}>
                        {row.key}
                      </code>
                      <input
                        type="text"
                        value={curLabel}
                        onChange={e => patch(row.id, 'label', e.target.value)}
                        className="w-full h-9 px-3 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-[var(--brand-primary)]/50 focus:ring-2 focus:ring-[var(--brand-primary)]/15 transition"
                        maxLength={60}
                      />
                      <div className="flex items-center gap-1.5">
                        <input
                          type="color"
                          value={curColor}
                          onChange={e => patch(row.id, 'color_hex', e.target.value)}
                          className="w-9 h-9 border border-gray-200 rounded-lg cursor-pointer"
                        />
                        <input
                          type="text"
                          value={curColor}
                          onChange={e => patch(row.id, 'color_hex', e.target.value)}
                          className="w-24 h-9 px-2 border border-gray-200 rounded-lg text-xs font-mono focus:outline-none focus:border-[var(--brand-primary)]/50 focus:ring-2 focus:ring-[var(--brand-primary)]/15 transition"
                        />
                      </div>
                      <select
                        value={curIcon}
                        onChange={e => patch(row.id, 'icon_name', e.target.value)}
                        className="w-full h-9 px-2.5 border border-gray-200 rounded-lg text-sm bg-white focus:outline-none focus:border-[var(--brand-primary)]/50 focus:ring-2 focus:ring-[var(--brand-primary)]/15 transition"
                      >
                        {CHIP_ICON_OPTIONS.map(ic => (
                          <option key={ic} value={ic}>{ic}</option>
                        ))}
                      </select>
                      <div className="flex items-center justify-end gap-2">
                        {/* Toggle Activo — Switch reusable estilo SaaS pro */}
                        <Switch
                          size="sm"
                          checked={!!curActivo}
                          onChange={() => patch(row.id, 'activo', !curActivo)}
                          ariaLabel={curActivo ? 'Desactivar categoría' : 'Activar categoría'}
                        />
                        {dirty ? (
                          <>
                            <button
                              onClick={() => cancel(row.id)}
                              className="text-xs text-gray-500 hover:text-gray-700 font-medium"
                              disabled={isSaving}
                            >
                              Cancelar
                            </button>
                            <button
                              onClick={() => save(row)}
                              disabled={isSaving}
                              className="h-8 px-3 text-xs rounded-lg bg-[var(--brand-primary)] text-white font-semibold hover:bg-[var(--brand-primary-hover)] disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                            >
                              {isSaving ? '…' : 'Guardar'}
                            </button>
                          </>
                        ) : (
                          <span className="text-[11px] text-gray-300 w-[72px] text-right select-none">
                            —
                          </span>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </section>
        )
      })}
    </div>
  )
}


/**
 * Gestor de Cuentas Empresariales WhatsApp (WABA) — V034.
 *
 * Una WABA representa una cuenta en Meta (ej: "Palma del Rio",
 * "Doctor Muelita"). Guarda su access_token, app_secret y verify_token
 * cifrados en DB. Sin esto el admin tendria que tocar env vars en
 * EasyPanel cada vez que se suma un cliente/empresa.
 *
 * Los numeros (wa_numbers) viven debajo de una WABA — cada linea propia
 * pertenece a una WABA.
 */
function WaBabasManager({ onChange } = {}) {
  const user = useAuthStore(s => s.user)
  const isAdmin = user?.role === 'admin'
  const [babas, setBabas] = useState(null)
  const [msg, setMsg] = useState(null)
  const [saving, setSaving] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [confirmDel, setConfirmDel] = useState(null)
  const [form, setForm] = useState({
    waba_id: '',
    display_name: '',
    access_token: '',
    app_secret: '',
    webhook_verify_token: '',
    notes: '',
    set_as_default: false,
  })

  const showMsg = (m) => { setMsg(m); setTimeout(() => setMsg(null), 3500) }

  const load = useCallback(() => {
    api.get('/api/whatsapp/babas')
      .then(r => setBabas(r.data?.items || []))
      .catch(() => setBabas([]))
  }, [])

  useEffect(() => { load() }, [load])

  const resetForm = () => {
    setForm({
      waba_id: '',
      display_name: '',
      access_token: '',
      app_secret: '',
      webhook_verify_token: '',
      notes: '',
      set_as_default: false,
    })
    setEditingId(null)
    setShowForm(false)
  }

  const openCreate = () => {
    resetForm()
    setShowForm(true)
  }

  const openEdit = (b) => {
    setEditingId(b.id)
    setForm({
      waba_id: b.waba_id || '',
      display_name: b.display_name || '',
      access_token: '',          // vacio = mantener
      app_secret: '',
      webhook_verify_token: '',
      notes: b.notes || '',
      set_as_default: b.is_default,
    })
    setShowForm(true)
  }

  const submit = async (e) => {
    e.preventDefault()
    if (!isAdmin || saving) return
    if (!form.display_name.trim()) {
      showMsg({ tipo: 'error', texto: 'El nombre es obligatorio.' })
      return
    }
    if (!editingId) {
      if (!form.waba_id.trim()) {
        showMsg({ tipo: 'error', texto: 'El WABA ID de Meta es obligatorio.' })
        return
      }
      if (!form.access_token.trim() || form.access_token.trim().length < 20) {
        showMsg({ tipo: 'error', texto: 'Pega un Access Token permanente valido (largo).' })
        return
      }
    }
    setSaving(true)
    try {
      if (editingId) {
        // Solo enviamos campos que el admin toco (access_token vacio = preservar)
        const patch = {
          display_name: form.display_name.trim() || undefined,
          notes: form.notes.trim() || null,
        }
        if (form.access_token.trim()) patch.access_token = form.access_token.trim()
        if (form.app_secret.trim()) patch.app_secret = form.app_secret.trim()
        if (form.webhook_verify_token.trim()) patch.webhook_verify_token = form.webhook_verify_token.trim()
        await api.patch(`/api/whatsapp/babas/${editingId}`, patch)
        // set_as_default se maneja aparte (toggle explicito)
        showMsg({ tipo: 'ok', texto: 'Cuenta empresarial actualizada.' })
      } else {
        await api.post('/api/whatsapp/babas', {
          waba_id: form.waba_id.trim(),
          display_name: form.display_name.trim(),
          access_token: form.access_token.trim(),
          app_secret: form.app_secret.trim(),
          webhook_verify_token: form.webhook_verify_token.trim(),
          notes: form.notes.trim() || null,
          set_as_default: form.set_as_default,
        })
        showMsg({ tipo: 'ok', texto: 'Cuenta empresarial registrada.' })
      }
      resetForm()
      load()
      onChange?.()
    } catch (err) {
      showMsg({ tipo: 'error', texto: err.response?.data?.detail || 'Error al guardar.' })
    } finally {
      setSaving(false)
    }
  }

  const setDefault = async (b) => {
    if (!isAdmin || saving || b.is_default) return
    if (!b.activo) {
      showMsg({ tipo: 'error', texto: 'Activa la cuenta antes de marcarla como default.' })
      return
    }
    setSaving(true)
    try {
      await api.post(`/api/whatsapp/babas/${b.id}/set-default`)
      showMsg({ tipo: 'ok', texto: `"${b.display_name}" es ahora la cuenta default.` })
      load()
      onChange?.()
    } catch (err) {
      showMsg({ tipo: 'error', texto: err.response?.data?.detail || 'Error al actualizar.' })
    } finally {
      setSaving(false)
    }
  }

  const toggleActive = async (b) => {
    if (!isAdmin || saving) return
    setSaving(true)
    try {
      await api.patch(`/api/whatsapp/babas/${b.id}`, { activo: !b.activo })
      load()
      onChange?.()
    } catch (err) {
      showMsg({ tipo: 'error', texto: err.response?.data?.detail || 'Error al actualizar.' })
    } finally {
      setSaving(false)
    }
  }

  const doDelete = async () => {
    if (!confirmDel || saving) return
    setSaving(true)
    try {
      await api.delete(`/api/whatsapp/babas/${confirmDel.id}`)
      showMsg({ tipo: 'ok', texto: 'Cuenta eliminada.' })
      setConfirmDel(null)
      load()
      onChange?.()
    } catch (err) {
      showMsg({ tipo: 'error', texto: err.response?.data?.detail || 'No se pudo eliminar.' })
    } finally {
      setSaving(false)
    }
  }

  if (babas === null) return <div className="h-32 bg-gray-100 rounded-xl animate-pulse" />

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-900 flex items-center gap-2">
            <Building size={14} className="text-indigo-600" />
            Cuentas Empresariales (WABA)
          </h3>
          <p className="text-xs text-gray-400 mt-0.5 max-w-3xl">
            Cada empresa de la que gestionas WhatsApp necesita su propia cuenta aqui, con sus credenciales de Meta. Los tokens se guardan cifrados en la base de datos — no se ven desde EasyPanel ni en variables de entorno.
          </p>
        </div>
        {isAdmin && (
          <button
            type="button"
            onClick={openCreate}
            className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-indigo-600 text-white hover:opacity-90 shrink-0"
          >
            <Plus size={14} /> Nueva cuenta
          </button>
        )}
      </div>

      {msg && <MsgBox msg={msg} />}

      {showForm && isAdmin && (
        <form onSubmit={submit} className="rounded-xl border border-indigo-200 bg-indigo-50/40 p-4 space-y-3">
          <p className="text-xs font-semibold text-indigo-900 flex items-center gap-1.5">
            <ShieldCheck size={13} />
            {editingId ? 'Editar cuenta empresarial' : 'Registrar nueva cuenta empresarial'}
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div>
              <label className="text-[11px] font-semibold text-gray-600 uppercase tracking-wide">
                Nombre visible *
              </label>
              <input
                type="text"
                value={form.display_name}
                onChange={(e) => setForm(f => ({ ...f, display_name: e.target.value }))}
                placeholder="Nombre de tu empresa"
                className="w-full mt-1 px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-300"
              />
            </div>
            <div>
              <label className="text-[11px] font-semibold text-gray-600 uppercase tracking-wide">
                WABA ID (Meta) *
              </label>
              <input
                type="text"
                value={form.waba_id}
                onChange={(e) => setForm(f => ({ ...f, waba_id: e.target.value }))}
                disabled={!!editingId}
                placeholder="123456789012345"
                className="w-full mt-1 px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-300 font-mono disabled:bg-gray-100"
              />
              <p className="text-[10px] text-gray-400 mt-1">
                Business Manager → Cuentas de WhatsApp → ID.
              </p>
            </div>
            <div className="md:col-span-2">
              <label className="text-[11px] font-semibold text-gray-600 uppercase tracking-wide flex items-center gap-1">
                <KeyRound size={11} /> Access Token permanente {editingId ? '(dejar vacio para mantener)' : '*'}
              </label>
              <input
                type="password"
                value={form.access_token}
                onChange={(e) => setForm(f => ({ ...f, access_token: e.target.value }))}
                placeholder={editingId ? '••••••••••  (no cambiar)' : 'EAAG...'}
                autoComplete="new-password"
                className="w-full mt-1 px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-300 font-mono"
              />
              <p className="text-[10px] text-gray-400 mt-1">
                System User token con permiso <span className="font-mono">whatsapp_business_messaging</span>. Se cifra con AES-128 + HMAC antes de guardarse.
              </p>
            </div>
            <div>
              <label className="text-[11px] font-semibold text-gray-600 uppercase tracking-wide flex items-center gap-1">
                <ShieldCheck size={11} /> App Secret {editingId ? '(vacio = mantener)' : '(opcional)'}
              </label>
              <input
                type="password"
                value={form.app_secret}
                onChange={(e) => setForm(f => ({ ...f, app_secret: e.target.value }))}
                placeholder={editingId ? '••••••••' : 'Verifica firma del webhook'}
                autoComplete="new-password"
                className="w-full mt-1 px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-300 font-mono"
              />
            </div>
            <div>
              <label className="text-[11px] font-semibold text-gray-600 uppercase tracking-wide flex items-center gap-1">
                <KeyRound size={11} /> Webhook Verify Token {editingId ? '(vacio = mantener)' : ''}
              </label>
              <input
                type="password"
                value={form.webhook_verify_token}
                onChange={(e) => setForm(f => ({ ...f, webhook_verify_token: e.target.value }))}
                placeholder={editingId ? '••••••••' : 'El que registraste en Meta webhook'}
                autoComplete="new-password"
                className="w-full mt-1 px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-300 font-mono"
              />
            </div>
            <div className="md:col-span-2">
              <label className="text-[11px] font-semibold text-gray-600 uppercase tracking-wide">
                Notas (opcional)
              </label>
              <input
                type="text"
                value={form.notes}
                onChange={(e) => setForm(f => ({ ...f, notes: e.target.value }))}
                placeholder="ej: Empresa A — cuenta principal de ventas"
                className="w-full mt-1 px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-300"
              />
            </div>
            {!editingId && (
              <label className="md:col-span-2 inline-flex items-center gap-2 text-xs text-gray-700 cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={form.set_as_default}
                  onChange={(e) => setForm(f => ({ ...f, set_as_default: e.target.checked }))}
                  className="h-4 w-4 rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                />
                Marcar como cuenta default (se usara para envios sin contexto)
              </label>
            )}
          </div>
          <div className="flex items-center gap-2 pt-2">
            <button
              type="submit"
              disabled={saving}
              className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-indigo-600 text-white hover:opacity-90 disabled:opacity-50"
            >
              <Check size={14} /> {editingId ? 'Guardar' : 'Registrar'}
            </button>
            <button
              type="button"
              onClick={resetForm}
              className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-gray-200 hover:bg-gray-50"
            >
              <XIcon size={14} /> Cancelar
            </button>
          </div>
        </form>
      )}

      {babas.length === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-200 p-6 text-center text-xs text-gray-500">
          Aun no hay cuentas empresariales. Registra la primera para empezar a recibir y enviar mensajes.
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {babas.map(b => (
            <div key={b.id} className={`rounded-xl border p-4 ${
              b.is_default ? 'border-amber-300 bg-amber-50/40' : 'border-gray-200 bg-white'
            }`}>
              <div className="flex items-start justify-between gap-2 mb-2">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap">
                    <div className="w-8 h-8 rounded-lg bg-indigo-100 text-indigo-700 flex items-center justify-center shrink-0">
                      <Building size={14} />
                    </div>
                    <p className="text-sm font-semibold text-gray-900 truncate">{b.display_name}</p>
                    {b.is_default && (
                      <span className="inline-flex items-center gap-0.5 text-[9px] font-bold text-amber-800 bg-amber-100 px-1.5 py-0.5 rounded-full border border-amber-200">
                        <Star size={9} /> DEFAULT
                      </span>
                    )}
                    <span className={`inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                      b.activo
                        ? 'bg-green-50 text-green-700 border border-green-200'
                        : 'bg-gray-100 text-gray-600 border border-gray-200'
                    }`}>
                      {b.activo ? <CheckCircle size={10} /> : <XCircle size={10} />}
                      {b.activo ? 'Activa' : 'Inactiva'}
                    </span>
                  </div>
                  <p className="text-[11px] text-gray-500 mt-1 font-mono break-all">
                    WABA ID: {b.waba_id}
                  </p>
                </div>
                {isAdmin && (
                  <div className="flex items-center gap-1 shrink-0">
                    {!b.is_default && (
                      <button
                        onClick={() => setDefault(b)}
                        disabled={saving}
                        title="Marcar como default"
                        className="p-1.5 rounded hover:bg-amber-50 text-amber-700 disabled:opacity-50"
                      >
                        <Star size={14} />
                      </button>
                    )}
                    <button
                      onClick={() => toggleActive(b)}
                      disabled={saving || (b.is_default && b.activo)}
                      title={b.is_default && b.activo ? 'No se puede desactivar la default' : (b.activo ? 'Desactivar' : 'Activar')}
                      className="p-1.5 rounded hover:bg-gray-100 text-gray-600 disabled:opacity-40"
                    >
                      {b.activo ? <XCircle size={14} /> : <CheckCircle size={14} />}
                    </button>
                    <button
                      onClick={() => openEdit(b)}
                      disabled={saving}
                      title="Editar credenciales"
                      className="p-1.5 rounded hover:bg-gray-100 text-gray-600 disabled:opacity-50"
                    >
                      <Pencil size={14} />
                    </button>
                    <button
                      onClick={() => setConfirmDel(b)}
                      disabled={saving || (b.numbers_count || 0) > 0}
                      title={(b.numbers_count || 0) > 0 ? 'Elimina primero las lineas' : 'Eliminar'}
                      className="p-1.5 rounded hover:bg-red-50 text-red-600 disabled:opacity-30"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                )}
              </div>

              <div className="grid grid-cols-2 gap-2 text-[11px] mt-3">
                <div className={`rounded-lg px-2 py-1.5 border ${b.access_token_fp ? 'border-green-200 bg-green-50' : 'border-red-200 bg-red-50'}`}>
                  <p className="flex items-center gap-1 font-semibold text-gray-700">
                    <KeyRound size={10} /> Access Token
                  </p>
                  <p className="font-mono text-[10px] text-gray-600 truncate">
                    {b.access_token_mask || '— no configurado —'}
                  </p>
                </div>
                <div className={`rounded-lg px-2 py-1.5 border ${b.has_app_secret ? 'border-green-200 bg-green-50' : 'border-gray-200 bg-gray-50'}`}>
                  <p className="flex items-center gap-1 font-semibold text-gray-700">
                    <ShieldCheck size={10} /> App Secret
                  </p>
                  <p className="text-[10px] text-gray-600">
                    {b.has_app_secret ? 'Configurado' : 'Sin firma'}
                  </p>
                </div>
                <div className={`rounded-lg px-2 py-1.5 border ${b.has_verify_token ? 'border-green-200 bg-green-50' : 'border-gray-200 bg-gray-50'}`}>
                  <p className="flex items-center gap-1 font-semibold text-gray-700">
                    <KeyRound size={10} /> Verify Token
                  </p>
                  <p className="text-[10px] text-gray-600">
                    {b.has_verify_token ? 'Configurado' : 'Sin registrar'}
                  </p>
                </div>
                <div className="rounded-lg px-2 py-1.5 border border-indigo-200 bg-indigo-50">
                  <p className="flex items-center gap-1 font-semibold text-gray-700">
                    <Phone size={10} /> Lineas
                  </p>
                  <p className="text-[10px] text-gray-600">
                    {b.numbers_count || 0} numero{(b.numbers_count || 0) === 1 ? '' : 's'}
                  </p>
                </div>
              </div>

              {b.notes && (
                <p className="text-[11px] text-gray-500 mt-2 italic line-clamp-2">{b.notes}</p>
              )}
            </div>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={!!confirmDel}
        title="Eliminar cuenta empresarial"
        message={confirmDel
          ? `¿Eliminar "${confirmDel.display_name}"? Esta accion borra las credenciales guardadas — los numeros asociados dejarian de poder enviar/recibir mensajes.`
          : ''}
        confirmLabel="Eliminar"
        onConfirm={doDelete}
        onCancel={() => setConfirmDel(null)}
      />
    </div>
  )
}

// WhatsAppSettings se exporta (named export mas abajo) para reutilizarse
// desde la pagina Integraciones, que es donde vive ahora este bloque.
/**
 * Gestor de numeros propios de WhatsApp Business (multi-linea).
 * El admin puede:
 *   - Ver todos los phone_number_id registrados (tanto los activos como los
 *     auto-registrados por el webhook y que quedaron inactivos)
 *   - Dar de alta un numero nuevo (despues de agregarlo en Meta Business Manager)
 *   - Renombrar / activar / desactivar
 *   - Elegir cual es el default para envios sin contexto
 */
function WaNumbersManager({ onChange } = {}) {
  const user = useAuthStore(s => s.user)
  const isAdmin = user?.role === 'admin'
  const [numbers, setNumbers] = useState(null)
  const [babas, setBabas] = useState([])
  const [msg, setMsg] = useState(null)
  const [saving, setSaving] = useState(false)
  const [showForm, setShowForm] = useState(false)
  const [editingId, setEditingId] = useState(null)
  const [form, setForm] = useState({
    phone_number_id: '',
    display_phone: '',
    display_name: '',
    waba_id_ref: '',
  })

  const showMsg = (m) => { setMsg(m); setTimeout(() => setMsg(null), 3500) }

  const load = useCallback(() => {
    Promise.all([
      api.get('/api/whatsapp/numbers').catch(() => ({ data: { items: [] } })),
      api.get('/api/whatsapp/babas?only_active=true').catch(() => ({ data: { items: [] } })),
    ]).then(([nRes, bRes]) => {
      setNumbers(nRes.data?.items || [])
      setBabas(bRes.data?.items || [])
    })
  }, [])

  useEffect(() => { load() }, [load])

  const resetForm = () => {
    const defaultBaba = babas.find(b => b.is_default) || babas[0]
    setForm({
      phone_number_id: '',
      display_phone: '',
      display_name: '',
      waba_id_ref: defaultBaba ? String(defaultBaba.id) : '',
    })
    setEditingId(null)
    setShowForm(false)
  }

  const openCreate = () => {
    resetForm()
    setShowForm(true)
  }

  const openEdit = (n) => {
    setEditingId(n.id)
    setForm({
      phone_number_id: n.phone_number_id,
      display_phone: n.display_phone || '',
      display_name: n.display_name,
      waba_id_ref: n.waba_id_ref ? String(n.waba_id_ref) : '',
    })
    setShowForm(true)
  }

  const submit = async (e) => {
    e.preventDefault()
    if (!isAdmin || saving) return
    if (!form.display_name.trim()) {
      showMsg({ tipo: 'error', texto: 'El nombre de la linea es obligatorio.' })
      return
    }
    if (!editingId && !form.phone_number_id.trim()) {
      showMsg({ tipo: 'error', texto: 'phone_number_id es obligatorio al crear una linea.' })
      return
    }
    if (!editingId && babas.length > 0 && !form.waba_id_ref) {
      showMsg({ tipo: 'error', texto: 'Selecciona la Cuenta Empresarial (WABA) a la que pertenece la linea.' })
      return
    }
    setSaving(true)
    try {
      const waba_id_ref = form.waba_id_ref ? Number(form.waba_id_ref) : null
      if (editingId) {
        await api.patch(`/api/whatsapp/numbers/${editingId}`, {
          display_phone: form.display_phone.trim() || null,
          display_name: form.display_name.trim(),
          waba_id_ref,
        })
        showMsg({ tipo: 'ok', texto: 'Linea actualizada.' })
      } else {
        await api.post('/api/whatsapp/numbers', {
          phone_number_id: form.phone_number_id.trim(),
          display_phone: form.display_phone.trim() || null,
          display_name: form.display_name.trim(),
          waba_id_ref,
        })
        showMsg({ tipo: 'ok', texto: 'Linea registrada.' })
      }
      resetForm()
      load()
      onChange?.()
    } catch (err) {
      showMsg({ tipo: 'error', texto: err.response?.data?.detail || 'Error al guardar.' })
    } finally {
      setSaving(false)
    }
  }

  const toggleActive = async (n) => {
    if (!isAdmin || saving) return
    setSaving(true)
    try {
      await api.patch(`/api/whatsapp/numbers/${n.id}`, { activo: !n.activo })
      load()
    } catch (err) {
      showMsg({ tipo: 'error', texto: err.response?.data?.detail || 'Error al actualizar.' })
    } finally {
      setSaving(false)
    }
  }

  const setDefault = async (n) => {
    if (!isAdmin || saving || n.is_default) return
    if (!n.activo) {
      showMsg({ tipo: 'error', texto: 'Activa la linea antes de marcarla como default.' })
      return
    }
    setSaving(true)
    try {
      await api.post(`/api/whatsapp/numbers/${n.id}/set-default`)
      showMsg({ tipo: 'ok', texto: `"${n.display_name}" es ahora la linea default.` })
      load()
    } catch (err) {
      showMsg({ tipo: 'error', texto: err.response?.data?.detail || 'Error al actualizar.' })
    } finally {
      setSaving(false)
    }
  }

  if (numbers === null) return <div className="h-32 bg-gray-100 rounded-xl animate-pulse" />

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-gray-900">Lineas WhatsApp Business</h3>
          <p className="text-xs text-gray-400 mt-0.5">
            Cada numero propio que usa el CRM para enviar/recibir. El default se usa cuando se envia un mensaje sin contexto.
          </p>
        </div>
        {isAdmin && (
          <button
            type="button"
            onClick={openCreate}
            className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-[var(--brand-primary)] text-white hover:opacity-90"
          >
            <Plus size={14} /> Nueva linea
          </button>
        )}
      </div>

      {msg && <MsgBox msg={msg} />}

      {showForm && isAdmin && (
        <form onSubmit={submit} className="rounded-xl border border-gray-200 bg-gray-50/60 p-4 space-y-3">
          <p className="text-xs font-semibold text-gray-700">
            {editingId ? 'Editar linea' : 'Registrar nueva linea'}
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            <div className="md:col-span-2">
              <label className="text-[11px] font-semibold text-gray-600 uppercase tracking-wide">
                Cuenta Empresarial (WABA) *
              </label>
              <select
                value={form.waba_id_ref}
                onChange={(e) => setForm(f => ({ ...f, waba_id_ref: e.target.value }))}
                disabled={babas.length === 0}
                className="w-full mt-1 px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--brand-primary)]/30 disabled:bg-gray-100"
              >
                <option value="">— Selecciona una cuenta empresarial —</option>
                {babas.map(b => (
                  <option key={b.id} value={b.id}>
                    {b.display_name} · {b.waba_id}{b.is_default ? ' · DEFAULT' : ''}
                  </option>
                ))}
              </select>
              {babas.length === 0 && (
                <p className="text-[10px] text-amber-700 mt-1 flex items-center gap-1">
                  <AlertTriangle size={11} /> No hay cuentas empresariales registradas. Registra una arriba antes de agregar lineas.
                </p>
              )}
            </div>
            <div>
              <label className="text-[11px] font-semibold text-gray-600 uppercase tracking-wide">
                phone_number_id (Meta) *
              </label>
              <input
                type="text"
                value={form.phone_number_id}
                onChange={(e) => setForm(f => ({ ...f, phone_number_id: e.target.value }))}
                disabled={!!editingId}
                placeholder="123456789012345"
                className="w-full mt-1 px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--brand-primary)]/30 disabled:bg-gray-100"
              />
              <p className="text-[10px] text-gray-400 mt-1">
                Meta Business Manager → WhatsApp → API Setup.
              </p>
            </div>
            <div>
              <label className="text-[11px] font-semibold text-gray-600 uppercase tracking-wide">
                Nombre interno *
              </label>
              <input
                type="text"
                value={form.display_name}
                onChange={(e) => setForm(f => ({ ...f, display_name: e.target.value }))}
                placeholder="Ej: Ventas Sede Centro"
                className="w-full mt-1 px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--brand-primary)]/30"
              />
            </div>
            <div>
              <label className="text-[11px] font-semibold text-gray-600 uppercase tracking-wide">
                Telefono visible
              </label>
              <input
                type="text"
                value={form.display_phone}
                onChange={(e) => setForm(f => ({ ...f, display_phone: e.target.value }))}
                placeholder="+51 999 999 999"
                className="w-full mt-1 px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-[var(--brand-primary)]/30"
              />
              <p className="text-[10px] text-gray-400 mt-1">
                Solo para mostrar en listados. No afecta el envio.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 pt-2">
            <button
              type="submit"
              disabled={saving}
              className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-[var(--brand-primary)] text-white hover:opacity-90 disabled:opacity-50"
            >
              <Check size={14} /> {editingId ? 'Guardar' : 'Registrar'}
            </button>
            <button
              type="button"
              onClick={resetForm}
              className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-gray-200 hover:bg-gray-50"
            >
              <XIcon size={14} /> Cancelar
            </button>
          </div>
        </form>
      )}

      {numbers.length === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-200 p-6 text-center text-xs text-gray-400">
          No hay lineas registradas. El seed automatico debio crear la inicial — revisa el log del backend.
        </div>
      ) : (
        <div className="rounded-xl border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50">
              <tr className="text-left text-[11px] uppercase tracking-wide text-gray-500">
                <th className="px-3 py-2">Linea</th>
                <th className="px-3 py-2">WABA</th>
                <th className="px-3 py-2">phone_number_id</th>
                <th className="px-3 py-2">Estado</th>
                <th className="px-3 py-2 text-right">Acciones</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {numbers.map(n => (
                <tr key={n.id} className={n.is_default ? 'bg-amber-50/40' : ''}>
                  <td className="px-3 py-2.5">
                    <div className="flex items-center gap-2">
                      <div className="w-8 h-8 rounded-full bg-purple-100 text-purple-700 flex items-center justify-center shrink-0">
                        <Phone size={14} />
                      </div>
                      <div className="min-w-0">
                        <div className="flex items-center gap-1.5">
                          <p className="text-sm font-medium text-gray-900 truncate">{n.display_name}</p>
                          {n.is_default && (
                            <span className="inline-flex items-center gap-0.5 text-[9px] font-bold text-amber-700 bg-amber-100 px-1.5 py-0.5 rounded-full">
                              <Star size={9} /> DEFAULT
                            </span>
                          )}
                        </div>
                        {n.display_phone && (
                          <p className="text-[11px] text-gray-500">+{n.display_phone}</p>
                        )}
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-2.5">
                    {n.waba_display_name ? (
                      <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-indigo-50 text-indigo-700 border border-indigo-200">
                        <Building size={10} /> {n.waba_display_name}
                      </span>
                    ) : (
                      <span className="inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full bg-amber-50 text-amber-700 border border-amber-200">
                        <AlertTriangle size={10} /> Sin WABA
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2.5 text-xs text-gray-600 font-mono">
                    {n.phone_number_id}
                  </td>
                  <td className="px-3 py-2.5">
                    <span className={`inline-flex items-center gap-1 text-[10px] font-semibold px-2 py-0.5 rounded-full ${
                      n.activo
                        ? 'bg-green-50 text-green-700 border border-green-200'
                        : 'bg-gray-100 text-gray-600 border border-gray-200'
                    }`}>
                      {n.activo ? <CheckCircle size={10} /> : <XCircle size={10} />}
                      {n.activo ? 'Activa' : 'Inactiva'}
                    </span>
                  </td>
                  <td className="px-3 py-2.5 text-right">
                    {isAdmin && (
                      <div className="inline-flex items-center gap-1">
                        {!n.is_default && n.activo && (
                          <button
                            onClick={() => setDefault(n)}
                            disabled={saving}
                            title="Marcar como default"
                            className="p-1.5 rounded hover:bg-amber-50 text-amber-700 disabled:opacity-50"
                          >
                            <Star size={14} />
                          </button>
                        )}
                        <button
                          onClick={() => toggleActive(n)}
                          disabled={saving || (n.is_default && n.activo)}
                          title={n.is_default && n.activo ? 'No se puede desactivar el default' : (n.activo ? 'Desactivar' : 'Activar')}
                          className="p-1.5 rounded hover:bg-gray-100 text-gray-600 disabled:opacity-40"
                        >
                          {n.activo ? <XCircle size={14} /> : <CheckCircle size={14} />}
                        </button>
                        <button
                          onClick={() => openEdit(n)}
                          disabled={saving}
                          title="Editar"
                          className="p-1.5 rounded hover:bg-gray-100 text-gray-600 disabled:opacity-50"
                        >
                          <Pencil size={14} />
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="rounded-xl border border-gray-100 bg-gray-50/60 p-4 text-xs text-gray-600 space-y-1">
        <p><span className="font-semibold text-gray-700">Como agregar un numero nuevo:</span></p>
        <ol className="list-decimal pl-4 space-y-0.5 text-gray-600">
          <li>Primero registra la <span className="font-semibold">Cuenta Empresarial (WABA)</span> en la seccion de arriba si aun no existe.</li>
          <li>En Meta Business Manager → WhatsApp Manager, agrega el numero dentro de esa WABA y copia el <span className="font-mono">phone_number_id</span>.</li>
          <li>Registralo aca eligiendo a que WABA pertenece y poniendole un nombre interno (ej: "Postventa", "Ventas 2").</li>
          <li>Si llega un mensaje de un numero que todavia no registraste, el webhook lo crea automaticamente como inactivo — aca lo activas y lo asignas a su WABA.</li>
        </ol>
      </div>
    </div>
  )
}

export function WhatsAppSettings() {
  const user = useAuthStore(s => s.user)
  const isAdmin = user?.role === 'admin'
  const [mode, setMode] = useState(null)        // 'auto' | 'manual' | null (loading)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState(null)

  useEffect(() => {
    api.get('/api/whatsapp/settings')
      .then(r => setMode(r.data?.ia_mode || 'auto'))
      .catch(() => setMode('auto'))
  }, [])

  const showMsg = (m) => { setMsg(m); setTimeout(() => setMsg(null), 3000) }

  const handleChange = async (next) => {
    if (!isAdmin || saving || next === mode) return
    setSaving(true)
    const prev = mode
    setMode(next)  // optimistic
    try {
      await api.patch('/api/whatsapp/settings', { mode: next })
      showMsg({ tipo: 'ok', texto: `Modo IA actualizado a "${next}".` })
    } catch (err) {
      setMode(prev)
      showMsg({ tipo: 'error', texto: err.response?.data?.detail || 'Error al guardar.' })
    } finally {
      setSaving(false)
    }
  }

  if (mode === null) return <div className="h-32 bg-gray-100 rounded-xl animate-pulse" />

  const options = [
    {
      id: 'auto',
      label: 'Automático',
      icon: Wand2,
      description: 'La IA clasifica el primer mensaje de cada conversación nueva y enruta al asesor automáticamente.',
      pros: ['Sin trabajo manual', 'Asignación instantánea', 'Filtra spam y consultas no relacionadas'],
      cons: ['Depende de Ollama disponible', 'Posibles falsos positivos en mensajes ambiguos'],
    },
    {
      id: 'manual',
      label: 'Manual',
      icon: Hand,
      description: 'Las nuevas conversaciones quedan en "pendiente". El supervisor decide cuáles clasificar con el botón "Reclasificar".',
      pros: ['Control total sobre delegación', 'Útil mientras el modelo se afina', 'Sin uso de tokens en spam'],
      cons: ['Requiere revisión humana de cada nuevo chat', 'Demora hasta que alguien atienda'],
    },
  ]

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-base font-semibold text-gray-900">Clasificación IA de WhatsApp</h2>
        <p className="text-xs text-gray-400 mt-0.5">
          Define cómo se procesan los mensajes nuevos entrantes. Aplica a partir del próximo webhook recibido.
        </p>
      </div>

      {msg && <MsgBox msg={msg} />}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {options.map(opt => {
          const Icon = opt.icon
          const isActive = mode === opt.id
          return (
            <button
              key={opt.id}
              type="button"
              onClick={() => handleChange(opt.id)}
              disabled={!isAdmin || saving}
              className={`text-left rounded-2xl border p-4 transition-all ${
                isActive
                  ? 'border-[var(--brand-primary)] bg-[var(--brand-primary)]/5 ring-2 ring-[var(--brand-primary)]/20'
                  : 'border-gray-200 hover:border-gray-300 bg-white'
              } ${(!isAdmin || saving) ? 'cursor-not-allowed opacity-80' : 'cursor-pointer'}`}
            >
              <div className="flex items-center gap-3 mb-2">
                <div className={`w-10 h-10 rounded-xl flex items-center justify-center shrink-0 ${
                  isActive ? 'bg-[var(--brand-primary)] text-white' : 'bg-gray-100 text-gray-500'
                }`}>
                  <Icon size={18} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <p className="text-sm font-semibold text-gray-900">{opt.label}</p>
                    {isActive && (
                      <span className="inline-flex items-center gap-1 text-[10px] font-bold text-[var(--brand-primary)] bg-[var(--brand-primary)]/10 px-1.5 py-0.5 rounded-full">
                        <Check size={10} /> ACTIVO
                      </span>
                    )}
                  </div>
                  <p className="text-xs text-gray-500 leading-snug mt-0.5">{opt.description}</p>
                </div>
              </div>

              <div className="mt-3 grid grid-cols-2 gap-3 text-[11px]">
                <div>
                  <p className="font-semibold text-green-700 mb-1">Pros</p>
                  <ul className="space-y-0.5 text-gray-600">
                    {opt.pros.map((p, i) => <li key={i}>+ {p}</li>)}
                  </ul>
                </div>
                <div>
                  <p className="font-semibold text-amber-700 mb-1">Contras</p>
                  <ul className="space-y-0.5 text-gray-600">
                    {opt.cons.map((c, i) => <li key={i}>– {c}</li>)}
                  </ul>
                </div>
              </div>
            </button>
          )
        })}
      </div>

      {!isAdmin && (
        <div className="rounded-lg bg-amber-50 border border-amber-200 p-3 text-xs text-amber-800">
          Solo administradores pueden cambiar este ajuste. Estás viendo el modo actual ({mode}).
        </div>
      )}

      <div className="rounded-xl border border-gray-100 bg-gray-50/60 p-4 text-xs text-gray-600 space-y-1">
        <p><span className="font-semibold text-gray-700">Tip:</span> en modo manual, abre la pestaña <span className="font-semibold">Chat</span> y usa el botón <span className="inline-flex items-center gap-1 font-semibold"><Wand2 size={11}/> Reclasificar</span> sobre cada conversación pendiente.</p>
        <p>Si Ollama está caído, el modo auto seguirá ingresando los mensajes pero los marcará como <span className="font-semibold">failed</span>; podrás reintentarlos manualmente.</p>
      </div>

      <div className="border-t border-gray-100 pt-5">
        <WaBabasManager />
      </div>

      <div className="border-t border-gray-100 pt-5">
        <WaNumbersManager />
      </div>

      <div className="border-t border-gray-100 pt-5">
        <WhatsAppDiagnostics />
      </div>

      <div className="border-t border-gray-100 pt-5">
        <WhatsAppAuditLog />
      </div>
    </div>
  )
}


/** Configuracion del Clasificador IA — Nivel 1.
 *  Permite ajustar nombre/descripcion del negocio, keywords relevantes,
 *  thresholds de auto-asignacion/auto-archivo, modelo Ollama e instrucciones
 *  custom. Incluye un mini-playground para probar la clasificacion sin tocar
 *  un chat real. NO permite editar el prompt template entero (Nivel 2).
 */
// Modelos sugeridos por proveedor — dropdown poblado, no hay que tipear.
// Si el proveedor expone /models en health_check, esa lista override estos.
const PROVIDER_MODELS = {
  ollama: [
    'qwen2.5:7b', 'qwen2.5:14b', 'llama3.2', 'llama3.2:3b',
    'phi3.5', 'mistral:7b',
  ],
  openai: [
    'gpt-4o-mini', 'gpt-4o', 'gpt-4-turbo', 'gpt-3.5-turbo',
  ],
  anthropic: [
    'claude-haiku-4-5', 'claude-sonnet-4-6', 'claude-opus-4-7',
    'claude-3-5-sonnet-latest', 'claude-3-5-haiku-latest',
  ],
  gemini: [
    'gemini-1.5-flash', 'gemini-1.5-pro', 'gemini-2.0-flash', 'gemini-2.5-flash',
  ],
}

const PROVIDER_META = {
  ollama: {
    label:    'Ollama (on-premise)',
    badge:    'Gratis',
    badgeBg:  'bg-emerald-100 text-emerald-700 border-emerald-200',
    desc:     'Corre en tu servidor. Sin costo por mensaje, datos no salen de tu infra.',
  },
  openai: {
    label:    'OpenAI (ChatGPT)',
    badge:    'API key requerida',
    badgeBg:  'bg-blue-100 text-blue-700 border-blue-200',
    desc:     'Calidad alta, latencia 1-2s. ~$0.30-15/mes segun volumen.',
  },
  anthropic: {
    label:    'Anthropic (Claude)',
    badge:    'API key requerida',
    badgeBg:  'bg-violet-100 text-violet-700 border-violet-200',
    desc:     'Mejor entendimiento de matices. ~$0.50-40/mes segun volumen.',
  },
  gemini: {
    label:    'Google (Gemini)',
    badge:    'API key requerida',
    badgeBg:  'bg-indigo-100 text-indigo-700 border-indigo-200',
    desc:     'Excelente balance de velocidad y costo, ventana de contexto gigante.',
  },
}


function AiClassifierConfigSection() {
  const [config, setConfig] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState(null)

  const [testMessage, setTestMessage] = useState('')
  const [testAd, setTestAd] = useState('')
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState(null)

  // Health check del proveedor
  const [healthChecking, setHealthChecking] = useState(false)
  const [health, setHealth] = useState(null)

  useEffect(() => {
    let cancelled = false
    api.get('/api/settings/ai-classifier')
      .then(r => { if (!cancelled) setConfig(r.data) })
      .catch(() => { if (!cancelled) setMsg({ tipo: 'err', texto: 'No se pudo cargar la configuracion.' }) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  const update = (patch) => setConfig(c => ({ ...c, ...patch }))

  const handleSave = async (e) => {
    e?.preventDefault?.()
    if (!config) return
    setSaving(true)
    setMsg(null)
    try {
      const { data } = await api.put('/api/settings/ai-classifier', config)
      setConfig(data)
      setMsg({ tipo: 'ok', texto: 'Configuracion guardada. Se aplica al proximo chat clasificado.' })
      setTimeout(() => setMsg(null), 4000)
    } catch (err) {
      setMsg({ tipo: 'err', texto: err.response?.data?.detail || 'Error al guardar.' })
    } finally {
      setSaving(false)
    }
  }

  const handleTest = async () => {
    if (!testMessage.trim()) return
    setTesting(true)
    setTestResult(null)
    try {
      const { data } = await api.post('/api/settings/ai-classifier/test', {
        message:      testMessage.trim(),
        ad_headline:  testAd.trim() || null,
      })
      setTestResult(data)
    } catch (err) {
      setTestResult({
        error: err.response?.data?.detail || 'Error en el test.',
      })
    } finally {
      setTesting(false)
    }
  }

  const handleHealthCheck = async () => {
    setHealthChecking(true)
    setHealth(null)
    try {
      const { data } = await api.get('/api/settings/ai-classifier/health')
      setHealth(data)
    } catch (err) {
      setHealth({ ok: false, error: err.response?.data?.detail || 'Error.' })
    } finally {
      setHealthChecking(false)
    }
  }

  if (loading) {
    return <div className="py-12 text-center text-sm text-gray-400"><Loader className="inline animate-spin mr-2" size={16} /> Cargando...</div>
  }
  if (!config) {
    return <div className="py-12 text-center text-sm text-red-500">No se pudo cargar la configuracion.</div>
  }

  return (
    <div className="max-w-5xl">
      <div className="mb-6 flex items-start gap-3">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-violet-500 to-indigo-600 flex items-center justify-center shrink-0 shadow-sm">
          <Bot size={20} className="text-white" />
        </div>
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-gray-900">Configuracion del Clasificador IA</h2>
          <p className="text-xs text-gray-500 mt-0.5 leading-relaxed max-w-2xl">
            Ajusta como la IA decide si un chat de WhatsApp es un lead, una consulta general o spam.
            Los cambios se aplican al proximo chat clasificado.
          </p>
        </div>
      </div>

      <MsgBox msg={msg} />

      <form onSubmit={handleSave} className="mt-4 space-y-6">
        {/* Card 1 — Negocio */}
        <section className="bg-white border border-gray-200 rounded-2xl p-5 shadow-sm">
          <div className="flex items-center gap-2 mb-4">
            <Building size={15} className="text-gray-400" />
            <h3 className="text-sm font-semibold text-gray-900">Tu negocio</h3>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-xs font-semibold text-gray-700 mb-1.5">Nombre del negocio</label>
              <input
                type="text"
                value={config.company_name || ''}
                onChange={e => update({ company_name: e.target.value })}
                placeholder="Nombre de tu empresa"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              <p className="text-[10px] text-gray-400 mt-1">Aparece en el prompt de la IA.</p>
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-700 mb-1.5">Pais / region</label>
              <input
                type="text"
                value={config.country || ''}
                onChange={e => update({ country: e.target.value })}
                placeholder="Peru"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              <p className="text-[10px] text-gray-400 mt-1">Da contexto geografico al modelo.</p>
            </div>
            <div className="sm:col-span-2">
              <label className="block text-xs font-semibold text-gray-700 mb-1.5">Descripcion corta</label>
              <input
                type="text"
                value={config.company_description || ''}
                onChange={e => update({ company_description: e.target.value })}
                placeholder="describe brevemente qué hace tu empresa"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              <p className="text-[10px] text-gray-400 mt-1">Una linea: que vende y donde.</p>
            </div>
            <div className="sm:col-span-2">
              <label className="block text-xs font-semibold text-gray-700 mb-1.5">Palabras clave relevantes</label>
              <input
                type="text"
                value={config.relevant_keywords || ''}
                onChange={e => update({ relevant_keywords: e.target.value })}
                placeholder="precios, promociones, horarios, ubicación"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              <p className="text-[10px] text-gray-400 mt-1">Si el cliente menciona alguna → la IA lo trata como relevante.</p>
            </div>
          </div>
        </section>

        {/* Card 2 — Thresholds */}
        <section className="bg-white border border-gray-200 rounded-2xl p-5 shadow-sm">
          <div className="flex items-center gap-2 mb-4">
            <Thermometer size={15} className="text-gray-400" />
            <h3 className="text-sm font-semibold text-gray-900">Umbrales de decision</h3>
          </div>
          <div className="space-y-5">
            <ThresholdSlider
              label="Auto-asignar como lead"
              hint="A partir de esta confianza, la IA crea lead automatico y lo asigna por rotacion."
              value={config.auto_assign_threshold ?? 0.80}
              onChange={v => update({ auto_assign_threshold: v })}
              accent="emerald"
            />
            <ThresholdSlider
              label="Auto-archivar (spam / no relacionado)"
              hint="A partir de esta confianza, la IA archiva sola sin tocar al equipo."
              value={config.auto_archive_threshold ?? 0.85}
              onChange={v => update({ auto_archive_threshold: v })}
              accent="rose"
            />
          </div>
        </section>

        {/* Card 3 — Proveedor IA */}
        <section className="bg-white border border-gray-200 rounded-2xl p-5 shadow-sm">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Bot size={15} className="text-gray-400" />
              <h3 className="text-sm font-semibold text-gray-900">Proveedor IA</h3>
            </div>
            <button
              type="button"
              onClick={handleHealthCheck}
              disabled={healthChecking}
              className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-gray-300 hover:bg-gray-50 disabled:opacity-50 transition-colors"
            >
              {healthChecking ? <Loader size={12} className="animate-spin" /> : <Zap size={12} />}
              {healthChecking ? 'Probando...' : 'Probar conexion'}
            </button>
          </div>

          {/* Selector de proveedor — radio cards visuales */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-2 mb-4">
            {Object.entries(PROVIDER_META).map(([key, meta]) => {
              const active = (config.provider || 'ollama') === key
              return (
                <button
                  key={key}
                  type="button"
                  onClick={() => update({ provider: key })}
                  className={`text-left p-3 rounded-xl border-2 transition-all ${
                    active
                      ? 'border-indigo-500 bg-indigo-50/50 shadow-sm'
                      : 'border-gray-200 hover:border-gray-300 bg-white'
                  }`}
                >
                  <div className="flex items-center justify-between mb-1">
                    <div className="text-sm font-semibold text-gray-900">{meta.label}</div>
                    {active && <Check size={14} className="text-indigo-600 shrink-0" />}
                  </div>
                  <div className={`inline-block text-[10px] px-1.5 py-0.5 rounded-full border font-medium mb-1.5 ${meta.badgeBg}`}>
                    {meta.badge}
                  </div>
                  <p className="text-[11px] text-gray-500 leading-snug">{meta.desc}</p>
                </button>
              )
            })}
          </div>

          {/* Result del health check */}
          {health && (
            <div className={`rounded-lg p-3 mb-4 text-xs flex items-start gap-2 ${
              health.ok
                ? 'bg-emerald-50 border border-emerald-200 text-emerald-800'
                : 'bg-red-50 border border-red-200 text-red-700'
            }`}>
              {health.ok ? <CheckCircle size={14} className="shrink-0 mt-0.5" /> : <XCircle size={14} className="shrink-0 mt-0.5" />}
              <div className="flex-1 min-w-0">
                {health.ok ? (
                  <>
                    <div className="font-semibold">Conexion ok ({health.latency_ms}ms)</div>
                    <div className="mt-0.5 text-emerald-700">
                      Modelo activo: <code className="bg-emerald-100 px-1 rounded font-mono">{health.model}</code>
                      {health.model_installed === false && (
                        <span className="ml-2 text-amber-700">⚠ El modelo no esta instalado en el servidor.</span>
                      )}
                    </div>
                    {health.available_models?.length > 0 && (
                      <div className="mt-1 text-emerald-700">
                        {health.available_models.length} modelos disponibles
                      </div>
                    )}
                  </>
                ) : (
                  <>
                    <div className="font-semibold">No se pudo conectar</div>
                    <div className="mt-0.5">{health.error}</div>
                  </>
                )}
              </div>
            </div>
          )}

          {/* Campos condicionales por proveedor */}
          {(config.provider || 'ollama') === 'ollama' && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4 p-3 bg-gray-50 rounded-lg">
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1.5">URL del servidor Ollama</label>
                <input
                  type="text"
                  value={config.ollama_base_url || ''}
                  onChange={e => update({ ollama_base_url: e.target.value })}
                  placeholder="http://crm_ollama:11434"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
                <p className="text-[10px] text-gray-400 mt-1">Vacio = usa OLLAMA_BASE_URL del entorno.</p>
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1.5">Modelo</label>
                <ModelPickerWithSuggestions
                  value={config.ollama_model || ''}
                  onChange={v => update({ ollama_model: v })}
                  suggestions={health?.available_models?.length ? health.available_models : PROVIDER_MODELS.ollama}
                  placeholder="qwen2.5:7b"
                />
                <p className="text-[10px] text-gray-400 mt-1">Vacio = OLLAMA_MODEL del entorno.</p>
              </div>
            </div>
          )}

          {(config.provider || 'ollama') === 'openai' && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4 p-3 bg-blue-50/40 border border-blue-100 rounded-lg">
              <div className="sm:col-span-2">
                <label className="block text-xs font-semibold text-gray-700 mb-1.5 flex items-center gap-1.5">
                  <Lock size={11} className="text-blue-600" />
                  API Key (sk-proj-...)
                </label>
                <input
                  type="password"
                  value={config.openai_api_key || ''}
                  onChange={e => update({ openai_api_key: e.target.value })}
                  placeholder="Pegar nueva key, o dejar vacio para mantener la actual"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
                <p className="text-[10px] text-gray-400 mt-1">
                  Se cifra antes de guardar. Conseguila en <a href="https://platform.openai.com/api-keys" target="_blank" rel="noreferrer" className="text-blue-600 hover:underline">platform.openai.com/api-keys</a>.
                </p>
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1.5">Modelo</label>
                <ModelPickerWithSuggestions
                  value={config.openai_model || 'gpt-4o-mini'}
                  onChange={v => update({ openai_model: v })}
                  suggestions={health?.available_models?.length ? health.available_models : PROVIDER_MODELS.openai}
                  placeholder="gpt-4o-mini"
                />
              </div>
              <div className="text-[10px] text-blue-700 bg-blue-100/60 border border-blue-200 rounded-lg p-2">
                ⚠ Recomendacion: <strong>seteá un límite de gasto</strong> en tu cuenta OpenAI antes de usar la key.
                Settings → Limits → Hard limit $50/mes.
              </div>
            </div>
          )}

          {(config.provider || 'ollama') === 'anthropic' && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4 p-3 bg-violet-50/40 border border-violet-100 rounded-lg">
              <div className="sm:col-span-2">
                <label className="block text-xs font-semibold text-gray-700 mb-1.5 flex items-center gap-1.5">
                  <Lock size={11} className="text-violet-600" />
                  API Key (sk-ant-...)
                </label>
                <input
                  type="password"
                  value={config.anthropic_api_key || ''}
                  onChange={e => update({ anthropic_api_key: e.target.value })}
                  placeholder="Pegar nueva key, o dejar vacio para mantener la actual"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-violet-500"
                />
                <p className="text-[10px] text-gray-400 mt-1">
                  Se cifra antes de guardar. Conseguila en <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noreferrer" className="text-violet-600 hover:underline">console.anthropic.com/settings/keys</a>.
                </p>
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1.5">Modelo</label>
                <ModelPickerWithSuggestions
                  value={config.anthropic_model || 'claude-haiku-4-5'}
                  onChange={v => update({ anthropic_model: v })}
                  suggestions={PROVIDER_MODELS.anthropic}
                  placeholder="claude-haiku-4-5"
                />
              </div>
              <div className="text-[10px] text-violet-700 bg-violet-100/60 border border-violet-200 rounded-lg p-2">
                ⚠ Recomendacion: <strong>seteá un Spend Limit</strong> en tu cuenta Anthropic antes de usar la key.
                Settings → Spend Limits → $50/mes.
              </div>
            </div>
          )}

          {(config.provider || 'ollama') === 'gemini' && (
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4 p-3 bg-indigo-50/40 border border-indigo-100 rounded-lg">
              <div className="sm:col-span-2">
                <label className="block text-xs font-semibold text-gray-700 mb-1.5 flex items-center gap-1.5">
                  <Lock size={11} className="text-indigo-600" />
                  API Key (AIzaSy...)
                </label>
                <input
                  type="password"
                  value={config.gemini_api_key || ''}
                  onChange={e => update({ gemini_api_key: e.target.value })}
                  placeholder="Pegar nueva key, o dejar vacio para mantener la actual"
                  className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
                <p className="text-[10px] text-gray-400 mt-1">
                  Se cifra antes de guardar. Conseguila en <a href="https://aistudio.google.com/app/apikey" target="_blank" rel="noreferrer" className="text-indigo-600 hover:underline">aistudio.google.com/app/apikey</a>.
                </p>
              </div>
              <div>
                <label className="block text-xs font-semibold text-gray-700 mb-1.5">Modelo</label>
                <ModelPickerWithSuggestions
                  value={config.gemini_model || 'gemini-1.5-flash'}
                  onChange={v => update({ gemini_model: v })}
                  suggestions={health?.available_models?.length ? health.available_models : PROVIDER_MODELS.gemini}
                  placeholder="gemini-1.5-flash"
                />
              </div>
              <div className="text-[10px] text-indigo-700 bg-indigo-100/60 border border-indigo-200 rounded-lg p-2">
                ⚠ Recomendacion: Utiliza el modelo <strong>gemini-1.5-flash</strong> para obtener la mejor relacion velocidad/costo.
              </div>
            </div>
          )}

          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4 mb-4">
            <div>
              <label className="block text-xs font-semibold text-gray-700 mb-1.5">Mensajes historial</label>
              <input
                type="number" min={1} max={20}
                value={config.history_message_count ?? 5}
                onChange={e => update({ history_message_count: parseInt(e.target.value, 10) || 5 })}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              <p className="text-[10px] text-gray-400 mt-1">Entre 1 y 20.</p>
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-700 mb-1.5">Timeout (seg)</label>
              <input
                type="number" min={5} max={120}
                value={config.timeout_seconds ?? 30}
                onChange={e => update({ timeout_seconds: parseInt(e.target.value, 10) || 30 })}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              <p className="text-[10px] text-gray-400 mt-1">5-120s.</p>
            </div>
            <div>
              <label className="block text-xs font-semibold text-gray-700 mb-1.5">Temperature</label>
              <input
                type="number" step={0.1} min={0} max={1}
                value={config.temperature ?? 0.2}
                onChange={e => update({ temperature: parseFloat(e.target.value) || 0.2 })}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
              <p className="text-[10px] text-gray-400 mt-1">0 = deterministico, 1 = creativo.</p>
            </div>
          </div>

          <div>
            <label className="block text-xs font-semibold text-gray-700 mb-1.5">Instrucciones adicionales (opcional)</label>
            <textarea
              value={config.extra_instructions || ''}
              onChange={e => update({ extra_instructions: e.target.value })}
              rows={4}
              placeholder="Ej: Si el cliente menciona el barrio Cayma, marcar urgencia=alta."
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <p className="text-[10px] text-gray-400 mt-1">
              Texto libre que se agrega al prompt. Util para reglas especificas del negocio sin tocar codigo.
            </p>
          </div>
        </section>

        <div className="flex items-center justify-end gap-2">
          <button
            type="submit"
            disabled={saving}
            className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold rounded-lg disabled:opacity-50 transition-colors shadow-sm"
          >
            {saving ? <Loader size={14} className="animate-spin" /> : <Check size={14} />}
            {saving ? 'Guardando...' : 'Guardar cambios'}
          </button>
        </div>
      </form>

      {/* Playground de prueba */}
      <section className="mt-8 bg-gradient-to-br from-violet-50 to-indigo-50 border border-violet-200 rounded-2xl p-5">
        <div className="flex items-center gap-2 mb-4">
          <Sparkles size={15} className="text-violet-500" />
          <h3 className="text-sm font-semibold text-gray-900">Probar con un mensaje</h3>
          <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-violet-100 text-violet-700 border border-violet-200 font-medium">
            Playground
          </span>
        </div>
        <p className="text-xs text-gray-600 mb-3 max-w-xl">
          Simula un mensaje entrante de WhatsApp para ver como lo clasifica la IA con tu config actual.
          No afecta ningun chat real.
        </p>
        <div className="space-y-3">
          <div>
            <label className="block text-xs font-semibold text-gray-700 mb-1.5">Mensaje del cliente</label>
            <textarea
              value={testMessage}
              onChange={e => setTestMessage(e.target.value)}
              rows={2}
              placeholder="Hola, queria info del lote 8 en Cayma"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500"
            />
          </div>
          <div>
            <label className="block text-xs font-semibold text-gray-700 mb-1.5">Anuncio de origen (opcional)</label>
            <input
              type="text"
              value={testAd}
              onChange={e => setTestAd(e.target.value)}
              placeholder="Ej: Lotes desde S/. 19,900"
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-violet-500"
            />
            <p className="text-[10px] text-gray-400 mt-1">Si la conv viene de un anuncio (CTWA), pégalo aquí.</p>
          </div>
          <button
            type="button"
            onClick={handleTest}
            disabled={testing || !testMessage.trim()}
            className="inline-flex items-center gap-2 px-4 py-2 bg-violet-600 hover:bg-violet-700 text-white text-sm font-semibold rounded-lg disabled:opacity-50 transition-colors shadow-sm"
          >
            {testing ? <Loader size={14} className="animate-spin" /> : <Sparkles size={14} />}
            {testing ? 'Clasificando...' : 'Clasificar'}
          </button>

          {testResult && (
            <div className="mt-4">
              {testResult.error ? (
                <div className="rounded-lg p-3 bg-red-50 border border-red-200 text-sm text-red-700">
                  {testResult.error}
                </div>
              ) : (
                <TestResultCard result={testResult} />
              )}
            </div>
          )}
        </div>
      </section>
    </div>
  )
}

/** Input con sugerencias datalist — el usuario puede tipear cualquier modelo
 *  o elegir de la lista. Si el health check trajo modelos disponibles, esos
 *  override las sugerencias estaticas. */
function ModelPickerWithSuggestions({ value, onChange, suggestions, placeholder }) {
  const listId = `models-${Math.random().toString(36).slice(2, 8)}`
  return (
    <>
      <input
        type="text"
        list={listId}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500"
      />
      <datalist id={listId}>
        {suggestions.map(s => <option key={s} value={s} />)}
      </datalist>
    </>
  )
}

function ThresholdSlider({ label, hint, value, onChange, accent = 'indigo' }) {
  const pct = Math.round((value || 0) * 100)
  const accentClass = {
    emerald: 'accent-emerald-500',
    rose:    'accent-rose-500',
    indigo:  'accent-indigo-500',
  }[accent] || 'accent-indigo-500'
  const badgeClass = {
    emerald: 'bg-emerald-100 text-emerald-700 border-emerald-200',
    rose:    'bg-rose-100 text-rose-700 border-rose-200',
    indigo:  'bg-indigo-100 text-indigo-700 border-indigo-200',
  }[accent]
  return (
    <div>
      <div className="flex items-center justify-between mb-1.5">
        <label className="text-xs font-semibold text-gray-700">{label}</label>
        <span className={`text-xs px-2 py-0.5 rounded-full font-mono font-semibold border ${badgeClass}`}>
          {pct}%
        </span>
      </div>
      <input
        type="range"
        min={50}
        max={99}
        value={pct}
        onChange={e => onChange(parseInt(e.target.value, 10) / 100)}
        className={`w-full ${accentClass}`}
      />
      <p className="text-[10px] text-gray-400 mt-1">{hint}</p>
    </div>
  )
}

function TestResultCard({ result }) {
  const r = result.raw_result || {}
  const cat = r.categoria || 'consulta_general'
  const conf = (r.confianza || 0) * 100
  const catColor = {
    cliente_potencial: 'bg-emerald-50 border-emerald-200 text-emerald-800',
    cliente_existente: 'bg-blue-50 border-blue-200 text-blue-800',
    consulta_general:  'bg-amber-50 border-amber-200 text-amber-800',
    spam:              'bg-red-50 border-red-200 text-red-800',
    no_relacionado:    'bg-gray-50 border-gray-200 text-gray-700',
  }[cat] || 'bg-gray-50 border-gray-200 text-gray-700'

  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
      <div className="flex items-start gap-3">
        <div className={`px-2.5 py-1 rounded-lg border text-[11px] font-semibold uppercase tracking-wide ${catColor}`}>
          {cat.replace('_', ' ')}
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-xs text-gray-500">Confianza</div>
          <div className="flex items-center gap-2 mt-0.5">
            <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
              <div
                className="h-full bg-indigo-500 transition-all"
                style={{ width: `${conf}%` }}
              />
            </div>
            <span className="text-xs font-mono font-semibold text-gray-700 tabular-nums">
              {conf.toFixed(0)}%
            </span>
          </div>
        </div>
      </div>

      <dl className="grid grid-cols-2 gap-x-4 gap-y-2 mt-4 text-xs">
        <div>
          <dt className="text-gray-500">Interes</dt>
          <dd className="font-medium text-gray-800">{r.interes || '—'}</dd>
        </div>
        <div>
          <dt className="text-gray-500">Urgencia</dt>
          <dd className="font-medium text-gray-800">{r.urgencia || '—'}</dd>
        </div>
        <div className="col-span-2">
          <dt className="text-gray-500">Resumen</dt>
          <dd className="font-medium text-gray-800 mt-0.5">{r.resumen || '—'}</dd>
        </div>
        {r.zona_mencionada && (
          <div>
            <dt className="text-gray-500">Zona</dt>
            <dd className="font-medium text-gray-800">{r.zona_mencionada}</dd>
          </div>
        )}
        {r.presupuesto_mencionado && (
          <div>
            <dt className="text-gray-500">Presupuesto</dt>
            <dd className="font-medium text-gray-800">{r.presupuesto_mencionado}</dd>
          </div>
        )}
      </dl>

      <details className="mt-4">
        <summary className="text-[10px] text-gray-400 cursor-pointer hover:text-gray-600">Ver prompt enviado al modelo</summary>
        <pre className="mt-2 text-[10px] bg-gray-50 border border-gray-200 rounded-lg p-3 overflow-auto max-h-64 whitespace-pre-wrap font-mono text-gray-700">
          {result.prompt}
        </pre>
      </details>
    </div>
  )
}


// ── Notificaciones Push (V040) ─────────────────────────────────────────────

const PUSH_EVENT_META = {
  lead_created: {
    label:    'Lead asignado',
    desc:     'Cuando el sistema asigna un lead nuevo a un asesor.',
    icon:     UserCheck,
    accent:   'emerald',
  },
  lead_reassigned: {
    label:    'Lead reasignado',
    desc:     'Cuando un supervisor o admin reasigna un lead a otro asesor.',
    icon:     ArrowRightLeft,
    accent:   'blue',
  },
  wa_message_inbound: {
    label:    'Mensaje WhatsApp nuevo',
    desc:     'Cuando un cliente responde en un chat asignado al asesor (solo el primer mensaje del burst, sin spam).',
    icon:     MessageCircle,
    accent:   'violet',
  },
}

const PUSH_ACCENT = {
  emerald: { ring: 'border-emerald-200', soft: 'bg-emerald-50',  iconBg: 'bg-emerald-100', iconFg: 'text-emerald-700' },
  blue:    { ring: 'border-blue-200',    soft: 'bg-blue-50',     iconBg: 'bg-blue-100',    iconFg: 'text-blue-700' },
  violet:  { ring: 'border-violet-200',  soft: 'bg-violet-50',   iconBg: 'bg-violet-100',  iconFg: 'text-violet-700' },
}

function _renderPreview(template, ctx) {
  if (!template) return ''
  let out = template
  Object.entries(ctx).forEach(([k, v]) => { out = out.split(`{${k}}`).join(v ?? '') })
  return out.replace(/\s+/g, ' ').trim()
}

const PUSH_PREVIEW_CTX = {
  lead_name:       'Juan Pérez (DEMO)',
  fuente:          'WhatsApp',
  contact_name:    'María González (DEMO)',
  message_preview: 'Hola, quería más información',
  wa_phone:        '+51999000000',
}


function NotificationsConfigSection() {
  const [data, setData] = useState(null)   // {events, available_variables}
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState(null)
  const [testing, setTesting] = useState(null) // event_type siendo testeado

  // Firebase (FCM) credentials state
  const [fcm, setFcm] = useState(null)
  const [fcmEnabled, setFcmEnabled] = useState(false)
  const [fcmJson, setFcmJson] = useState('')   // input plaintext, server encripta
  const [fcmSaving, setFcmSaving] = useState(false)
  const [fcmTesting, setFcmTesting] = useState(false)
  const [fcmTestResult, setFcmTestResult] = useState(null)

  useEffect(() => {
    let cancelled = false
    Promise.all([
      api.get('/api/settings/notifications'),
      api.get('/api/settings/fcm'),
    ])
      .then(([nRes, fRes]) => {
        if (cancelled) return
        setData(nRes.data)
        setFcm(fRes.data)
        setFcmEnabled(!!fRes.data.enabled)
      })
      .catch(() => { if (!cancelled) setMsg({ tipo: 'err', texto: 'No se pudo cargar la configuracion.' }) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  const handleFcmSave = async () => {
    setFcmSaving(true); setMsg(null); setFcmTestResult(null)
    try {
      await api.put('/api/settings/fcm', {
        enabled:              fcmEnabled,
        service_account_json: fcmJson,  // server preserva si vacio
      })
      // Refrescar estado (preview de credencial actualizada)
      const { data: fresh } = await api.get('/api/settings/fcm')
      setFcm(fresh)
      setFcmJson('')  // limpiar el textarea — la credencial ya esta guardada
      setMsg({ tipo: 'ok', texto: 'Credenciales FCM guardadas. Firebase se reinicializa con la nueva config.' })
      setTimeout(() => setMsg(null), 4000)
    } catch (err) {
      setMsg({ tipo: 'err', texto: err.response?.data?.detail || 'Error al guardar.' })
    } finally { setFcmSaving(false) }
  }

  const handleFcmTest = async () => {
    setFcmTesting(true); setFcmTestResult(null)
    try {
      const { data: result } = await api.post('/api/settings/fcm/test')
      setFcmTestResult(result)
      // Refrescar status para mostrar initialized=true en el badge
      const { data: fresh } = await api.get('/api/settings/fcm')
      setFcm(fresh)
    } catch (err) {
      setFcmTestResult({
        ok: false,
        message: err.response?.data?.detail || 'Error al probar conexion.',
      })
    } finally { setFcmTesting(false) }
  }

  const updateEvent = (eventType, patch) => {
    setData(d => ({
      ...d,
      events: { ...d.events, [eventType]: { ...d.events[eventType], ...patch } },
    }))
  }

  // V070.52 — Quiet hours editor (paridad con CRMs profesionales Notification
  // Preferences). El admin define un rango global; los eventos en
  // urgent_events ignoran ese rango (cliente esperando respuesta).
  const updateQuietHours = (patch) => {
    setData(d => ({
      ...d,
      quiet_hours: { ...(d.quiet_hours || {}), ...patch },
    }))
  }

  const handleSave = async (e) => {
    e?.preventDefault?.()
    if (!data) return
    setSaving(true); setMsg(null)
    try {
      const { data: saved } = await api.put('/api/settings/notifications', {
        events: data.events,
        quiet_hours: data.quiet_hours,
      })
      setData(d => ({ ...d, events: saved.events, quiet_hours: saved.quiet_hours }))
      setMsg({ tipo: 'ok', texto: 'Configuracion guardada. Se aplica al proximo push.' })
      setTimeout(() => setMsg(null), 4000)
    } catch (err) {
      setMsg({ tipo: 'err', texto: err.response?.data?.detail || 'Error al guardar.' })
    } finally { setSaving(false) }
  }

  const handleTest = async (eventType) => {
    setTesting(eventType)
    try {
      const { data: result } = await api.post('/api/settings/notifications/test', {
        event_type: eventType,
      })
      setMsg({
        tipo: result.sent ? 'ok' : 'err',
        texto: result.info || (result.sent ? 'Push enviado.' : 'No se pudo enviar.'),
      })
      setTimeout(() => setMsg(null), 6000)
    } catch (err) {
      setMsg({ tipo: 'err', texto: err.response?.data?.detail || 'Error en el test.' })
    } finally { setTesting(null) }
  }

  if (loading) {
    return <div className="py-12 text-center text-sm text-gray-400"><Loader className="inline animate-spin mr-2" size={16} /> Cargando...</div>
  }
  if (!data) {
    return <div className="py-12 text-center text-sm text-red-500">No se pudo cargar la configuracion.</div>
  }

  const variables = data.available_variables || {}

  return (
    <div className="max-w-5xl">
      <div className="mb-6 flex items-start gap-3">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-400 to-orange-500 flex items-center justify-center shrink-0 shadow-sm">
          <Phone size={20} className="text-white" />
        </div>
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-gray-900">Notificaciones Push</h2>
          <p className="text-xs text-gray-500 mt-0.5 leading-relaxed max-w-2xl">
            Customiza el titulo y cuerpo de las push notifications que reciben los asesores.
            Cambios se aplican al proximo evento (sin restart).
          </p>
        </div>
      </div>

      <MsgBox msg={msg} />

      {/* Card 1 — Credenciales Firebase (FCM). Pre-requisito para que cualquier
          push funcione. Sin esto, el resto de la pagina edita templates que
          no se enviarian. */}
      {fcm && (
        <section className={`bg-white border rounded-2xl p-5 shadow-sm mt-4 ${
          fcm.initialized
            ? 'border-emerald-200'
            : fcm.has_credentials
              ? 'border-amber-200'
              : 'border-red-200'
        }`}>
          <div className="flex items-start justify-between gap-3 mb-4">
            <div className="flex items-start gap-3">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-orange-500 to-red-500 flex items-center justify-center shrink-0 shadow-sm">
                <KeyRound size={18} className="text-white" />
              </div>
              <div className="min-w-0">
                <h3 className="text-sm font-semibold text-gray-900">Firebase (FCM)</h3>
                <p className="text-xs text-gray-500 mt-0.5 max-w-xl leading-snug">
                  Credenciales del proyecto Firebase para enviar push. Sin esto, los templates de abajo no se envian.
                </p>
              </div>
            </div>
            {/* Badge de status */}
            <div className={`shrink-0 inline-flex items-center gap-1 text-[10px] font-bold px-2 py-1 rounded-full border ${
              fcm.initialized
                ? 'bg-emerald-100 text-emerald-700 border-emerald-200'
                : fcm.has_credentials
                  ? 'bg-amber-100 text-amber-700 border-amber-200'
                  : 'bg-red-100 text-red-700 border-red-200'
            }`}>
              <div className={`w-1.5 h-1.5 rounded-full ${
                fcm.initialized ? 'bg-emerald-500' : fcm.has_credentials ? 'bg-amber-500' : 'bg-red-500'
              }`} />
              {fcm.initialized ? 'Conectado' : fcm.has_credentials ? 'Sin testear' : 'Sin configurar'}
            </div>
          </div>

          {/* Estado actual */}
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3 mb-4">
            <div className="rounded-lg bg-gray-50 border border-gray-200 p-3">
              <div className="text-[10px] uppercase tracking-wide text-gray-400 font-semibold">Habilitado</div>
              <div className={`text-sm font-semibold mt-0.5 ${fcm.enabled ? 'text-emerald-700' : 'text-gray-400'}`}>
                {fcm.enabled ? 'Si' : 'No'}
              </div>
            </div>
            <div className="rounded-lg bg-gray-50 border border-gray-200 p-3">
              <div className="text-[10px] uppercase tracking-wide text-gray-400 font-semibold">Credencial</div>
              <div className="text-sm font-mono text-gray-700 mt-0.5 truncate">
                {fcm.credential_preview || <span className="text-gray-400 italic font-sans">— no configurada —</span>}
              </div>
            </div>
            <div className="rounded-lg bg-gray-50 border border-gray-200 p-3">
              <div className="text-[10px] uppercase tracking-wide text-gray-400 font-semibold">
                Origen de la credencial
              </div>
              <div className="mt-0.5">
                {fcm.credential_source === 'db' ? (
                  <>
                    <div className="inline-flex items-center gap-1.5 text-sm font-semibold text-emerald-700">
                      <CheckCircle size={13} />
                      Cargada desde la UI
                    </div>
                    <div className="text-[11px] text-gray-500 mt-0.5">
                      Esta credencial pisa la del archivo .env. Si quieres volver
                      a usar la del .env, borra la actual desde el botón de
                      abajo.
                    </div>
                  </>
                ) : fcm.credential_source === 'env' ? (
                  <>
                    <div className="inline-flex items-center gap-1.5 text-sm font-semibold text-amber-700">
                      <AlertTriangle size={13} />
                      Cargada desde .env
                    </div>
                    <div className="text-[11px] text-gray-500 mt-0.5">
                      Recomendado: carga la credencial desde la UI para poder
                      rotarla sin redeploy.
                    </div>
                  </>
                ) : (
                  <div className="text-sm text-gray-400 italic">
                    Sin credencial configurada
                  </div>
                )}
              </div>
            </div>
          </div>

          {fcm.last_error && (
            <div className="rounded-lg p-3 mb-4 text-xs flex items-start gap-2 bg-red-50 border border-red-200 text-red-700">
              <XCircle size={14} className="shrink-0 mt-0.5" />
              <div>
                <div className="font-semibold">Ultimo error de inicializacion</div>
                <div className="mt-0.5 font-mono text-[11px]">{fcm.last_error}</div>
              </div>
            </div>
          )}

          {/* Editor */}
          <div className="grid grid-cols-1 md:grid-cols-[180px_1fr] gap-4 items-start">
            <label className="inline-flex items-center gap-2 cursor-pointer pt-2">
              <input
                type="checkbox"
                checked={fcmEnabled}
                onChange={e => setFcmEnabled(e.target.checked)}
                className="rounded border-gray-300 text-emerald-600 focus:ring-emerald-500"
              />
              <span className="text-xs font-semibold text-gray-700">FCM activo</span>
            </label>
            <div>
              <label className="block text-xs font-semibold text-gray-700 mb-1.5 inline-flex items-center gap-1.5">
                <Lock size={11} className="text-orange-600" />
                Service Account JSON (Firebase Console)
              </label>
              <textarea
                value={fcmJson}
                onChange={e => setFcmJson(e.target.value)}
                rows={5}
                placeholder={fcm.has_credentials
                  ? 'Pegar nuevo JSON aqui para reemplazar — o dejar vacio para mantener el actual'
                  : 'Pegar el JSON completo del service account (incluyendo type, project_id, private_key, etc.)'}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-orange-500"
              />
              <p className="text-[10px] text-gray-400 mt-1 leading-snug">
                Conseguilo en <a href="https://console.firebase.google.com" target="_blank" rel="noreferrer" className="text-orange-600 hover:underline">Firebase Console</a> → Configuracion del proyecto →
                Cuentas de servicio → "Generar nueva clave privada". Se cifra con Fernet antes de guardar — nunca se devuelve en plaintext.
              </p>
            </div>
          </div>

          {fcmTestResult && (
            <div className={`mt-4 rounded-lg p-3 text-xs flex items-start gap-2 ${
              fcmTestResult.ok
                ? 'bg-emerald-50 border border-emerald-200 text-emerald-800'
                : 'bg-red-50 border border-red-200 text-red-700'
            }`}>
              {fcmTestResult.ok ? <CheckCircle size={14} className="shrink-0 mt-0.5" /> : <XCircle size={14} className="shrink-0 mt-0.5" />}
              <div className="flex-1">
                <div className="font-semibold">{fcmTestResult.ok ? 'Firebase OK' : 'No se pudo inicializar Firebase'}</div>
                <div className="mt-0.5">{fcmTestResult.message}</div>
              </div>
            </div>
          )}

          <div className="flex items-center justify-end gap-2 mt-4">
            <button
              type="button"
              onClick={handleFcmTest}
              disabled={fcmTesting}
              className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-gray-300 hover:bg-gray-50 disabled:opacity-50 transition-colors"
            >
              {fcmTesting ? <Loader size={12} className="animate-spin" /> : <Zap size={12} />}
              {fcmTesting ? 'Probando...' : 'Probar conexion'}
            </button>
            <button
              type="button"
              onClick={handleFcmSave}
              disabled={fcmSaving}
              className="inline-flex items-center gap-2 px-4 py-2 bg-orange-600 hover:bg-orange-700 text-white text-sm font-semibold rounded-lg disabled:opacity-50 transition-colors shadow-sm"
            >
              {fcmSaving ? <Loader size={14} className="animate-spin" /> : <Check size={14} />}
              {fcmSaving ? 'Guardando...' : 'Guardar credenciales'}
            </button>
          </div>
        </section>
      )}

      <form onSubmit={handleSave} className="mt-4 space-y-4">
        {/* V070.52 — Quiet hours card (paridad con CRMs profesionales
            preferencias de notificación). Rango horario donde no se envia push
            para no perturbar al asesor fuera del horario laboral. Los
            eventos en urgent_events (ej: WhatsApp inbound) son excepcion. */}
        {data.quiet_hours && (() => {
          const qh = data.quiet_hours
          const urgents = data.urgent_events || []
          return (
            <section className={`bg-white border ${qh.enabled ? 'border-indigo-200' : 'border-gray-200'} rounded-2xl p-5 shadow-sm transition-colors`}>
              <div className="flex items-start gap-3 mb-4">
                <div className="w-9 h-9 rounded-lg bg-indigo-50 flex items-center justify-center shrink-0">
                  <Moon size={16} className="text-indigo-600" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="text-sm font-semibold text-gray-900">Horario silencioso por defecto</h3>
                    <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-violet-100 text-violet-700 border border-violet-200 uppercase tracking-wide">
                      Default global
                    </span>
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5 leading-snug">
                    Default para todos los usuarios que no personalicen su horario. Cada uno puede sobreescribirlo desde <strong className="text-gray-700">Mi cuenta → Mis notificaciones</strong>. Los mensajes de WhatsApp entrantes son la única excepción (cliente esperando respuesta).
                  </p>
                </div>
                <label className="inline-flex items-center gap-2 cursor-pointer shrink-0">
                  <input
                    type="checkbox"
                    checked={!!qh.enabled}
                    onChange={e => updateQuietHours({ enabled: e.target.checked })}
                    className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                  />
                  <span className="text-xs font-semibold text-gray-700">
                    {qh.enabled ? 'Activo' : 'Desactivado'}
                  </span>
                </label>
              </div>

              <div className={`grid grid-cols-1 sm:grid-cols-2 gap-4 ${!qh.enabled ? 'opacity-50 pointer-events-none' : ''}`}>
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1.5">Desde</label>
                  <input
                    type="time"
                    value={qh.start || '21:00'}
                    onChange={e => updateQuietHours({ start: e.target.value })}
                    className="w-full h-10 px-3 border border-gray-200 rounded-lg text-sm font-mono focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/15 transition"
                  />
                </div>
                <div>
                  <label className="block text-xs font-semibold text-gray-700 mb-1.5">Hasta</label>
                  <input
                    type="time"
                    value={qh.end || '08:00'}
                    onChange={e => updateQuietHours({ end: e.target.value })}
                    className="w-full h-10 px-3 border border-gray-200 rounded-lg text-sm font-mono focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/15 transition"
                  />
                </div>
              </div>

              {qh.enabled && (
                <div className="mt-4 flex items-start gap-2 text-xs text-gray-500 bg-indigo-50/50 border border-indigo-100 rounded-lg px-3 py-2">
                  <Info size={13} className="text-indigo-500 shrink-0 mt-0.5" />
                  <div className="leading-relaxed">
                    Push silenciados entre <strong className="text-gray-700 font-mono">{qh.start}</strong> y <strong className="text-gray-700 font-mono">{qh.end}</strong> (hora Lima).
                    {urgents.length > 0 && (
                      <> Excepciones que siempre llegan: <strong className="text-gray-700">{urgents.join(', ')}</strong>.</>
                    )}
                  </div>
                </div>
              )}
            </section>
          )
        })()}

        {Object.entries(PUSH_EVENT_META).map(([eventType, meta]) => {
          const tpl = data.events[eventType] || { enabled: true, title: '', body: '' }
          const Icon = meta.icon
          const palette = PUSH_ACCENT[meta.accent] || PUSH_ACCENT.emerald
          const eventVars = variables[eventType] || []
          const previewTitle = _renderPreview(tpl.title, PUSH_PREVIEW_CTX)
          const previewBody  = _renderPreview(tpl.body,  PUSH_PREVIEW_CTX)

          return (
            <section
              key={eventType}
              className={`bg-white border ${tpl.enabled ? palette.ring : 'border-gray-200'} rounded-2xl p-5 shadow-sm transition-colors`}
            >
              <div className="flex items-start gap-3 mb-4">
                <div className={`w-9 h-9 rounded-lg ${palette.iconBg} flex items-center justify-center shrink-0`}>
                  <Icon size={16} className={palette.iconFg} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <h3 className="text-sm font-semibold text-gray-900">{meta.label}</h3>
                    <code className="text-[10px] px-1.5 py-0.5 rounded bg-gray-100 text-gray-500 font-mono">{eventType}</code>
                  </div>
                  <p className="text-xs text-gray-500 mt-0.5 leading-snug">{meta.desc}</p>
                </div>
                <label className="inline-flex items-center gap-2 cursor-pointer shrink-0">
                  <input
                    type="checkbox"
                    checked={!!tpl.enabled}
                    onChange={e => updateEvent(eventType, { enabled: e.target.checked })}
                    className="rounded border-gray-300 text-emerald-600 focus:ring-emerald-500"
                  />
                  <span className="text-xs font-semibold text-gray-700">
                    {tpl.enabled ? 'Activo' : 'Desactivado'}
                  </span>
                </label>
              </div>

              <div className={`grid grid-cols-1 lg:grid-cols-2 gap-4 ${!tpl.enabled ? 'opacity-50 pointer-events-none' : ''}`}>
                {/* Editor */}
                <div className="space-y-3">
                  <div>
                    <label className="block text-xs font-semibold text-gray-700 mb-1.5">Titulo del push</label>
                    <input
                      type="text"
                      value={tpl.title || ''}
                      onChange={e => updateEvent(eventType, { title: e.target.value })}
                      placeholder="Ej: Nuevo lead asignado"
                      maxLength={200}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-semibold text-gray-700 mb-1.5">Cuerpo del push</label>
                    <textarea
                      value={tpl.body || ''}
                      onChange={e => updateEvent(eventType, { body: e.target.value })}
                      placeholder="Ej: {lead_name} ({fuente})"
                      rows={2}
                      maxLength={500}
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </div>
                  {eventVars.length > 0 && (
                    <div>
                      <p className="text-[10px] uppercase tracking-wide text-gray-400 font-semibold mb-1.5">Variables disponibles (click para insertar)</p>
                      <div className="flex flex-wrap gap-1">
                        {eventVars.map(v => (
                          <button
                            key={v}
                            type="button"
                            onClick={() => updateEvent(eventType, { body: (tpl.body || '') + `{${v}}` })}
                            className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-gray-100 text-gray-700 border border-gray-200 hover:bg-gray-200 transition-colors"
                          >
                            {`{${v}}`}
                          </button>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                {/* Preview tipo notificacion mobile */}
                <div>
                  <p className="text-[10px] uppercase tracking-wide text-gray-400 font-semibold mb-1.5">Vista previa (en el celular)</p>
                  <div className="rounded-2xl bg-gradient-to-br from-gray-100 to-gray-200 p-4">
                    <div className="bg-white rounded-xl p-3 shadow-md flex gap-3">
                      <div className="w-8 h-8 rounded-lg bg-[var(--brand-primary)] flex items-center justify-center shrink-0">
                        <Phone size={14} className="text-white" />
                      </div>
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center justify-between gap-2 text-[10px] text-gray-500">
                          <span className="font-semibold uppercase tracking-wide">CRM</span>
                          <span>ahora</span>
                        </div>
                        <div className="text-sm font-semibold text-gray-900 truncate mt-0.5">
                          {previewTitle || <span className="text-gray-300 italic font-normal">(sin titulo)</span>}
                        </div>
                        <div className="text-xs text-gray-700 mt-0.5 line-clamp-2">
                          {previewBody || <span className="text-gray-300 italic">(sin cuerpo)</span>}
                        </div>
                      </div>
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={() => handleTest(eventType)}
                    disabled={testing === eventType || !tpl.enabled}
                    className="mt-2 w-full inline-flex items-center justify-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-gray-300 hover:bg-gray-50 disabled:opacity-50 transition-colors"
                  >
                    {testing === eventType ? <Loader size={12} className="animate-spin" /> : <Zap size={12} />}
                    {testing === eventType ? 'Enviando...' : 'Enviarme push de prueba'}
                  </button>
                </div>
              </div>
            </section>
          )
        })}

        <div className="flex items-center justify-end gap-2 pt-2">
          <button
            type="submit"
            disabled={saving}
            className="inline-flex items-center gap-2 px-4 py-2 bg-indigo-600 hover:bg-indigo-700 text-white text-sm font-semibold rounded-lg disabled:opacity-50 transition-colors shadow-sm"
          >
            {saving ? <Loader size={14} className="animate-spin" /> : <Check size={14} />}
            {saving ? 'Guardando...' : 'Guardar cambios'}
          </button>
        </div>
      </form>
    </div>
  )
}


// ── V070.54 — Mis Notificaciones (preferencias personales por usuario) ──
//
// Espejo web del flujo mobile ConfigMisNotificacionesScreen. Cada usuario
// (cualquier rol) gestiona sus propias prefs:
//   - Kill switch general (push on/off)
//   - Quiet hours personal (override del global)
//   - Opt-out por tipo de evento
// Paridad preferencias de notificación Preferences per-user.
const PUSH_EVENT_LABELS_MINE = {
  lead_created:        { title: 'Nuevo lead asignado',      desc: 'Cuando te asignan un lead nuevo.' },
  leads_batch:         { title: 'Varios leads asignados',   desc: 'Llegaron varios leads juntos (carga masiva o pico). Recibís un push consolidado.' },
  lead_reassigned:     { title: 'Lead reasignado',          desc: 'Cuando te transfieren un lead existente.' },
  lead_recontacto:     { title: 'Lead recontactado',        desc: 'Un lead viejo volvió a mostrar interés.' },
  wa_message_inbound:  { title: 'Mensaje de WhatsApp',      desc: 'Cliente respondió en uno de tus chats.' },
  // V070.78 — Team Circuit Breaker (solo para supervisores)
  team_blocked:        { title: 'Tu equipo fue BLOQUEADO',  desc: 'Demasiados asesores pausados. Tu equipo dejó de recibir leads — van a otros equipos hasta que reactivés asesores.' },
  team_unblocked:      { title: 'Tu equipo volvió a ACTIVO', desc: 'Hay suficientes asesores activos otra vez. Tu equipo vuelve a recibir leads automáticamente.' },
}

function MyNotificationPrefsSection() {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState(null)
  const [prefs, setPrefs] = useState(null)
  const [globalQh, setGlobalQh] = useState(null)
  const [availableEvents, setAvailableEvents] = useState([])
  const [urgentEvents, setUrgentEvents] = useState([])

  useEffect(() => {
    let cancelled = false
    api.get('/api/settings/me/notification-prefs')
      .then(res => {
        if (cancelled) return
        setPrefs(res.data.prefs)
        setGlobalQh(res.data.global_quiet_hours)
        setAvailableEvents(res.data.available_events || [])
        setUrgentEvents(res.data.urgent_events || [])
      })
      .catch(() => { if (!cancelled) setMsg({ tipo: 'err', texto: 'No se pudieron cargar tus preferencias.' }) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  const update = (patch) => setPrefs(p => ({ ...p, ...patch }))

  // V070.90 — Modelo 3-estados patrón estándar por evento.
  // Reemplaza los toggles independientes (Tipos + Excepciones) por una
  // sola eleccion clara: cuándo recibo este push?
  //   - 'all_time':     siempre, incluso en horario silencioso (urgent only)
  //   - 'active_hours': solo fuera de mi horario silencioso
  //   - 'never':        apagado
  // Internamente se mapea al backend (events_disabled, urgent_events_disabled).
  const getEventState = (evt) => {
    const isOff = (prefs.events_disabled || []).includes(evt)
    if (isOff) return 'never'
    const isUrgent = urgentEvents.includes(evt)
    if (!isUrgent) return 'active_hours'
    const bypassDisabled = (prefs.urgent_events_disabled || []).includes(evt)
    return bypassDisabled ? 'active_hours' : 'all_time'
  }

  const setEventState = (evt, newState) => {
    const eventsDisabled = new Set(prefs.events_disabled || [])
    const urgentDisabled = new Set(prefs.urgent_events_disabled || [])
    const isUrgent = urgentEvents.includes(evt)

    if (newState === 'never') {
      eventsDisabled.add(evt)
      urgentDisabled.delete(evt)
    } else if (newState === 'all_time') {
      eventsDisabled.delete(evt)
      if (isUrgent) urgentDisabled.delete(evt)
    } else if (newState === 'active_hours') {
      eventsDisabled.delete(evt)
      if (isUrgent) urgentDisabled.add(evt)
    }

    update({
      events_disabled:        Array.from(eventsDisabled),
      urgent_events_disabled: Array.from(urgentDisabled),
    })
  }

  const handleSave = async () => {
    if (!prefs) return
    setSaving(true); setMsg(null)
    try {
      const { data } = await api.put('/api/settings/me/notification-prefs', prefs)
      setPrefs(data.prefs)
      setMsg({ tipo: 'ok', texto: 'Preferencias guardadas.' })
      setTimeout(() => setMsg(null), 4000)
    } catch (err) {
      setMsg({ tipo: 'err', texto: err.response?.data?.detail || 'No se pudo guardar.' })
    } finally { setSaving(false) }
  }

  if (loading) {
    return <div className="py-12 text-center text-sm text-gray-400"><Loader className="inline animate-spin mr-2" size={16} /> Cargando…</div>
  }
  if (!prefs) {
    return <div className="py-12 text-center text-sm text-red-500">No se pudieron cargar tus preferencias.</div>
  }

  const personalOverride = prefs.quiet_hours_enabled !== null && prefs.quiet_hours_enabled !== undefined
  const effectiveStart = personalOverride && prefs.quiet_hours_start
    ? prefs.quiet_hours_start
    : globalQh?.start || '21:00'
  const effectiveEnd = personalOverride && prefs.quiet_hours_end
    ? prefs.quiet_hours_end
    : globalQh?.end || '08:00'
  const effectiveEnabled = personalOverride
    ? !!prefs.quiet_hours_enabled
    : !!globalQh?.enabled

  return (
    <div className="max-w-3xl">
      <div className="mb-6 flex items-start gap-3">
        <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-violet-500 flex items-center justify-center shrink-0 shadow-sm">
          <BellRing size={20} className="text-white" />
        </div>
        <div className="min-w-0">
          <h2 className="text-base font-semibold text-gray-900">Mis notificaciones</h2>
          <p className="text-xs text-gray-500 mt-0.5 leading-relaxed max-w-xl">
            Configura tu kill switch, horario silencioso y qué tipos de push quieres recibir.
            Sobrescribe los defaults globales del admin.
          </p>
        </div>
      </div>

      <MsgBox msg={msg} />

      {/* Card 1: kill switch */}
      <section className={`bg-white border ${prefs.push_enabled ? 'border-emerald-200' : 'border-gray-200'} rounded-2xl p-5 shadow-sm mt-4`}>
        <div className="flex items-start gap-3">
          <div className={`w-9 h-9 rounded-lg ${prefs.push_enabled ? 'bg-emerald-50' : 'bg-gray-100'} flex items-center justify-center shrink-0`}>
            <BellRing size={16} className={prefs.push_enabled ? 'text-emerald-600' : 'text-gray-400'} />
          </div>
          <div className="flex-1 min-w-0">
            <h3 className="text-sm font-semibold text-gray-900">Recibir notificaciones</h3>
            <p className="text-xs text-gray-500 mt-0.5 leading-snug">
              Si lo apagas, no recibirás ningún push (ni leads ni WhatsApp). Útil para días libres o vacaciones.
            </p>
          </div>
          <label className="inline-flex items-center gap-2 cursor-pointer shrink-0">
            <input
              type="checkbox"
              checked={!!prefs.push_enabled}
              onChange={e => update({ push_enabled: e.target.checked })}
              className="rounded border-gray-300 text-emerald-600 focus:ring-emerald-500"
            />
            <span className="text-xs font-semibold text-gray-700">
              {prefs.push_enabled ? 'Activo' : 'Apagado'}
            </span>
          </label>
        </div>
      </section>

      <div className={prefs.push_enabled ? '' : 'opacity-40 pointer-events-none'}>
        {/* Card 2: quiet hours */}
        <section className={`bg-white border ${effectiveEnabled ? 'border-indigo-200' : 'border-gray-200'} rounded-2xl p-5 shadow-sm mt-4`}>
          <div className="flex items-start gap-3 mb-4">
            <div className="w-9 h-9 rounded-lg bg-indigo-50 flex items-center justify-center shrink-0">
              <Moon size={16} className="text-indigo-600" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="text-sm font-semibold text-gray-900">Horario silencioso personal</h3>
                <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 border border-emerald-200 uppercase tracking-wide">
                  Personal
                </span>
              </div>
              <p className="text-xs text-gray-500 mt-0.5 leading-snug">
                Tu rango propio. Si eliges <strong className="text-gray-700">Personalizar</strong>, sobreescribe el default global que configuró el admin. Los mensajes de WhatsApp entrantes son la única excepción.
              </p>
            </div>
          </div>

          {/* Toggle usar global / personalizar */}
          <div className="grid grid-cols-2 gap-2">
            <button
              type="button"
              onClick={() => update({
                quiet_hours_enabled: null,
                quiet_hours_start: null,
                quiet_hours_end: null,
              })}
              className={`p-3 rounded-xl border text-left transition ${
                !personalOverride
                  ? 'border-indigo-300 bg-indigo-50/50 ring-2 ring-indigo-200'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <div className="text-xs font-semibold text-gray-700">Usar el global</div>
              <div className="text-[11px] text-gray-500 mt-0.5">
                {globalQh?.enabled
                  ? <>Default: <span className="font-mono">{globalQh.start}–{globalQh.end}</span></>
                  : 'El admin lo tiene desactivado'}
              </div>
            </button>
            <button
              type="button"
              onClick={() => update({
                quiet_hours_enabled: prefs.quiet_hours_enabled ?? true,
                quiet_hours_start:   prefs.quiet_hours_start || globalQh?.start || '21:00',
                quiet_hours_end:     prefs.quiet_hours_end   || globalQh?.end   || '08:00',
              })}
              className={`p-3 rounded-xl border text-left transition ${
                personalOverride
                  ? 'border-indigo-300 bg-indigo-50/50 ring-2 ring-indigo-200'
                  : 'border-gray-200 hover:border-gray-300'
              }`}
            >
              <div className="text-xs font-semibold text-gray-700">Personalizar</div>
              <div className="text-[11px] text-gray-500 mt-0.5">Define tu propio horario</div>
            </button>
          </div>

          {personalOverride && (
            <div className="mt-4 space-y-3">
              <div className="flex items-center justify-between">
                <label className="text-xs font-semibold text-gray-700">Activar horario silencioso</label>
                <label className="inline-flex items-center gap-2 cursor-pointer">
                  <input
                    type="checkbox"
                    checked={!!prefs.quiet_hours_enabled}
                    onChange={e => update({ quiet_hours_enabled: e.target.checked })}
                    className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
                  />
                  <span className="text-xs font-semibold text-gray-700">
                    {prefs.quiet_hours_enabled ? 'On' : 'Off'}
                  </span>
                </label>
              </div>

              {prefs.quiet_hours_enabled && (
                <div className="grid grid-cols-2 gap-3">
                  <div>
                    <label className="block text-[11px] font-semibold text-gray-600 mb-1">Desde</label>
                    <input
                      type="time"
                      value={prefs.quiet_hours_start || effectiveStart}
                      onChange={e => update({ quiet_hours_start: e.target.value })}
                      className="w-full h-10 px-3 border border-gray-200 rounded-lg text-sm font-mono focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/15 transition"
                    />
                  </div>
                  <div>
                    <label className="block text-[11px] font-semibold text-gray-600 mb-1">Hasta</label>
                    <input
                      type="time"
                      value={prefs.quiet_hours_end || effectiveEnd}
                      onChange={e => update({ quiet_hours_end: e.target.value })}
                      className="w-full h-10 px-3 border border-gray-200 rounded-lg text-sm font-mono focus:outline-none focus:border-indigo-500 focus:ring-2 focus:ring-indigo-500/15 transition"
                    />
                  </div>
                </div>
              )}
            </div>
          )}

          <div className="mt-4 flex items-start gap-2 text-xs text-gray-500 bg-indigo-50/50 border border-indigo-100 rounded-lg px-3 py-2">
            <Info size={13} className="text-indigo-500 shrink-0 mt-0.5" />
            <div className="leading-relaxed">
              {effectiveEnabled
                ? <>Push silenciados entre <strong className="text-gray-700 font-mono">{effectiveStart}</strong> y <strong className="text-gray-700 font-mono">{effectiveEnd}</strong> (hora Lima).</>
                : 'El horario silencioso está desactivado — recibirás push a toda hora.'}
              {urgentEvents.length > 0 && (
                <> Excepciones que siempre llegan: <strong className="text-gray-700">{urgentEvents.map(e => PUSH_EVENT_LABELS_MINE[e]?.title || e).join(', ')}</strong>.</>
              )}
            </div>
          </div>
        </section>

        {/* V070.90 — Card unificada: 3 opciones por evento (patrón estándar).
            Reemplaza las 2 cards anteriores (Tipos + Excepciones) que confundian
            al usuario al exigir razonar la hora actual y la interaccion entre
            toggles. Ahora cada evento tiene UN solo control claro. */}
        <section className="bg-white border border-gray-200 rounded-2xl p-5 shadow-sm mt-4">
          <div className="flex items-start gap-3 mb-4">
            <div className="w-9 h-9 rounded-lg bg-amber-50 flex items-center justify-center shrink-0">
              <MessageSquare size={16} className="text-amber-600" />
            </div>
            <div className="flex-1 min-w-0">
              <h3 className="text-sm font-semibold text-gray-900">Notificaciones por tipo</h3>
              <p className="text-xs text-gray-500 mt-0.5 leading-snug">
                Elige cuándo quieres recibir cada tipo de push. Los marcados como{' '}
                <span className="text-red-700 font-semibold">URGENTE</span> pueden recibirse 24/7 si lo prefieres.
              </p>
            </div>
          </div>

          <div className="divide-y divide-gray-100">
            {availableEvents.map(evt => {
              const meta = PUSH_EVENT_LABELS_MINE[evt] || { title: evt, desc: '' }
              const isUrgent = urgentEvents.includes(evt)
              const state = getEventState(evt)
              return (
                <div key={evt} className="py-4">
                  <div className="flex items-center gap-2 mb-2 flex-wrap">
                    <div className="text-sm font-semibold text-gray-800">{meta.title}</div>
                    {isUrgent && (
                      <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-red-100 text-red-700 border border-red-200 uppercase tracking-wide">
                        Urgente
                      </span>
                    )}
                  </div>
                  <div className="text-xs text-gray-500 mb-2">{meta.desc}</div>
                  <div className="flex gap-1.5 flex-wrap">
                    {isUrgent && (
                      <button
                        type="button"
                        onClick={() => setEventState(evt, 'all_time')}
                        className={`flex-1 min-w-[100px] px-3 py-2 rounded-lg border text-xs font-semibold transition ${
                          state === 'all_time'
                            ? 'border-red-300 bg-red-50 text-red-700 ring-2 ring-red-200'
                            : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300'
                        }`}
                      >
                        Todo el tiempo
                      </button>
                    )}
                    <button
                      type="button"
                      onClick={() => setEventState(evt, 'active_hours')}
                      className={`flex-1 min-w-[100px] px-3 py-2 rounded-lg border text-xs font-semibold transition ${
                        state === 'active_hours'
                          ? 'border-indigo-300 bg-indigo-50 text-indigo-700 ring-2 ring-indigo-200'
                          : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300'
                      }`}
                    >
                      En horario activo
                    </button>
                    <button
                      type="button"
                      onClick={() => setEventState(evt, 'never')}
                      className={`flex-1 min-w-[100px] px-3 py-2 rounded-lg border text-xs font-semibold transition ${
                        state === 'never'
                          ? 'border-gray-400 bg-gray-100 text-gray-800 ring-2 ring-gray-300'
                          : 'border-gray-200 bg-white text-gray-600 hover:border-gray-300'
                      }`}
                    >
                      Nunca
                    </button>
                  </div>
                </div>
              )
            })}
          </div>
        </section>
      </div>

      <div className="mt-5 flex justify-end">
        <Button onClick={handleSave} disabled={saving}>
          {saving ? <><Loader size={14} className="animate-spin mr-1.5" />Guardando…</> : 'Guardar preferencias'}
        </Button>
      </div>
    </div>
  )
}


// ── Sincronización móvil — intervalo de auto-sync del registro de llamadas ──
//
// Antes era una constante hardcoded en la APK (30 min). Ahora vive en la base
// y se aplica sin recompilar: la APK lee el valor al arrancar y al volver a
// foreground. Rango 5-120 min validado server-side.
function MobileSyncSection() {
  const [minutes, setMinutes] = useState(30)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState(null)

  const MIN = 5
  const MAX = 120

  useEffect(() => {
    let cancelled = false
    api.get('/api/settings/mobile-sync')
      .then(r => { if (!cancelled) setMinutes(r.data?.auto_sync_minutes ?? 30) })
      .catch(() => { if (!cancelled) setMsg({ tipo: 'err', texto: 'No se pudo cargar la configuración.' }) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  const handleSave = async (e) => {
    e?.preventDefault?.()
    if (minutes < MIN || minutes > MAX) {
      setMsg({ tipo: 'err', texto: `El valor debe estar entre ${MIN} y ${MAX} minutos.` })
      return
    }
    setSaving(true); setMsg(null)
    try {
      await api.put('/api/settings/mobile-sync', { auto_sync_minutes: minutes })
      setMsg({ tipo: 'ok', texto: 'Guardado. La APK aplicará el nuevo intervalo en su próximo arranque o foreground.' })
      setTimeout(() => setMsg(null), 5000)
    } catch (err) {
      setMsg({ tipo: 'err', texto: err.response?.data?.detail || 'Error al guardar.' })
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="text-sm text-gray-400">Cargando…</div>

  return (
    <div className="max-w-3xl">
      <div className="mb-5">
        <h2 className="text-base font-semibold text-gray-900">Sincronización móvil</h2>
        <p className="text-xs text-gray-400 mt-0.5">
          Cada cuántos minutos la app móvil sube automáticamente el registro de llamadas al CRM.
        </p>
      </div>

      <form onSubmit={handleSave} className="space-y-5">
        <div className="border border-gray-100 rounded-xl p-5 bg-gray-50/40">
          <label className="text-sm font-medium text-gray-700">
            Intervalo de auto-sincronización
          </label>
          <p className="text-xs text-gray-500 mt-1">
            Rango permitido: {MIN}–{MAX} minutos. Default sugerido: 30.
          </p>

          <div className="mt-3 flex items-center gap-3">
            <input
              type="number"
              min={MIN}
              max={MAX}
              step={1}
              value={minutes}
              onChange={e => setMinutes(parseInt(e.target.value, 10) || MIN)}
              className="w-28 h-10 px-3 border border-gray-200 rounded-lg text-sm focus:outline-none focus:border-[var(--brand-primary)]/50 focus:ring-2 focus:ring-[var(--brand-primary)]/15 transition"
            />
            <span className="text-sm text-gray-500">minutos</span>
          </div>

          <div className="mt-4 grid grid-cols-3 gap-2">
            {[10, 30, 60].map(preset => (
              <button
                key={preset}
                type="button"
                onClick={() => setMinutes(preset)}
                className={`text-xs py-2 rounded-lg border transition ${
                  minutes === preset
                    ? 'bg-[var(--brand-primary)]/10 border-[var(--brand-primary)]/30 text-[var(--brand-primary)] font-semibold'
                    : 'border-gray-200 text-gray-600 hover:bg-gray-50'
                }`}
              >
                {preset} min
              </button>
            ))}
          </div>
        </div>

        <div className="rounded-xl bg-amber-50/60 border border-amber-200 p-4 text-xs text-amber-800 space-y-1.5">
          <p className="font-semibold">Cómo elegir un valor</p>
          <ul className="list-disc list-inside space-y-1 ml-1">
            <li><strong>10–15 min</strong>: cuando hay campañas activas y se necesita ver llamadas casi en vivo en los reportes.</li>
            <li><strong>30 min</strong> (default): balance entre frescura de datos y batería del asesor.</li>
            <li><strong>60–120 min</strong>: si el equipo no requiere métricas en tiempo real y se prioriza autonomía del dispositivo.</li>
          </ul>
        </div>

        <MsgBox msg={msg} />

        <div className="flex justify-end">
          <button
            type="submit"
            disabled={saving}
            className="inline-flex items-center gap-1.5 text-sm px-4 py-2 rounded-lg bg-[var(--brand-primary)] text-white hover:opacity-90 disabled:opacity-50"
          >
            {saving ? 'Guardando…' : 'Guardar'}
          </button>
        </div>
      </form>
    </div>
  )
}


/**
 * LeadAutomationConfigSection — Configuración dinámica de automatizaciones de estados.
 * Permite al administrador definir las reglas de cambio automático de estados
 * según llamadas, mensajes de WhatsApp y tiempo transcurrido, asociándolas a cualquiera
 * de los estados existentes en la plataforma.
 */
function LeadAutomationConfigSection() {
  const [config, setConfig] = useState(null)
  const [estados, setEstados] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [msg, setMsg] = useState(null)
  const [testResult, setTestResult] = useState(null)

  const loadData = useCallback(async () => {
    setLoading(true)
    setMsg(null)
    try {
      const res = await api.get('/api/settings/lead-automation')
      setConfig(res.data?.config || {
        enabled: false,
        reglas_intentos: [],
        reglas_tiempo: [],
        excluir_contacto_efectivo: true,
        respetar_gestion_admin: true,
      })
      setEstados(res.data?.estados || [])
    } catch (err) {
      setMsg({ tipo: 'err', texto: 'No se pudo cargar la configuración de automatizaciones.' })
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadData()
  }, [loadData])

  const handleSave = async (e) => {
    e?.preventDefault?.()
    setSaving(true)
    setMsg(null)
    setTestResult(null)
    try {
      await api.put('/api/settings/lead-automation', config)
      setMsg({ tipo: 'ok', texto: 'Configuración guardada exitosamente.' })
      setTimeout(() => setMsg(null), 5000)
    } catch (err) {
      setMsg({ tipo: 'err', texto: err.response?.data?.detail || 'Error al guardar la configuración.' })
    } finally {
      setSaving(false)
    }
  }

  const handleRunNow = async () => {
    if (!window.confirm('¿Deseas ejecutar un ciclo de evaluación de automatizaciones ahora mismo con los leads actuales?')) {
      return
    }
    setTesting(true)
    setTestResult(null)
    setMsg(null)
    try {
      const res = await api.post('/api/settings/lead-automation/run-now')
      setTestResult(res.data)
      if (res.data?.enabled === false) {
        setMsg({ tipo: 'err', texto: 'El motor está desactivado. Actívalo con el interruptor y guarda los cambios para que procese leads.' })
      } else {
        setMsg({ tipo: 'ok', texto: `Ciclo finalizado. Total leads actualizados: ${res.data?.total_movidos ?? 0}` })
      }
    } catch (err) {
      setMsg({ tipo: 'err', texto: err.response?.data?.detail || 'Error al ejecutar la automatización.' })
    } finally {
      setTesting(false)
    }
  }

  const addReglaIntento = () => {
    const nextOrder = (config?.reglas_intentos?.length || 0) + 1
    const defaultEstadoId = estados[0]?.id || 1
    const newRule = {
      id: `intento_${Date.now()}`,
      nombre: `Escalamiento ${nextOrder}`,
      estado_destino_id: defaultEstadoId,
      min_llamadas: nextOrder * 2,
      min_whatsapp: nextOrder,
      orden: nextOrder,
      activo: true,
    }
    setConfig(prev => ({
      ...prev,
      reglas_intentos: [...(prev.reglas_intentos || []), newRule],
    }))
  }

  const updateReglaIntento = (index, field, value) => {
    setConfig(prev => {
      const copy = [...(prev.reglas_intentos || [])]
      copy[index] = { ...copy[index], [field]: value }
      return { ...prev, reglas_intentos: copy }
    })
  }

  const removeReglaIntento = (index) => {
    setConfig(prev => ({
      ...prev,
      reglas_intentos: (prev.reglas_intentos || []).filter((_, i) => i !== index),
    }))
  }

  const addReglaTiempo = () => {
    const defaultOrigen = estados[0]?.id || 1
    const defaultDestino = estados[1]?.id || estados[0]?.id || 1
    const newRule = {
      id: `tiempo_${Date.now()}`,
      nombre: 'Pase a Bolsa por inactividad',
      estado_origen_id: defaultOrigen,
      horas_espera: 12,
      estado_destino_id: defaultDestino,
      desasignar_asesor: true,
      activo: true,
    }
    setConfig(prev => ({
      ...prev,
      reglas_tiempo: [...(prev.reglas_tiempo || []), newRule],
    }))
  }

  const updateReglaTiempo = (index, field, value) => {
    setConfig(prev => {
      const copy = [...(prev.reglas_tiempo || [])]
      copy[index] = { ...copy[index], [field]: value }
      return { ...prev, reglas_tiempo: copy }
    })
  }

  const removeReglaTiempo = (index) => {
    setConfig(prev => ({
      ...prev,
      reglas_tiempo: (prev.reglas_tiempo || []).filter((_, i) => i !== index),
    }))
  }

  if (loading) {
    return (
      <div className="py-12 flex flex-col items-center justify-center gap-3 text-gray-400">
        <Loader size={20} className="animate-spin text-indigo-500" />
        <span className="text-sm">Cargando configuración de automatizaciones...</span>
      </div>
    )
  }

  const isEnabled = Boolean(config?.enabled)

  return (
    <div className="max-w-4xl space-y-6 animate-fadeIn">
      {/* Encabezado */}
      <div>
        <div className="flex items-center gap-2">
          <Zap size={20} className="text-amber-500" />
          <h2 className="text-base font-semibold text-gray-900">Automatización de Estados del CRM</h2>
        </div>
        <p className="text-xs text-gray-500 mt-1">
          Configura libremente qué estados de la plataforma se asignan de forma automática
          al registrar llamadas, mensajes de WhatsApp o tras determinado tiempo en espera.
        </p>
      </div>

      <MsgBox msg={msg} />

      {/* Tarjeta de Control Maestro */}
      <div className={`p-5 rounded-2xl border transition-all ${
        isEnabled
          ? 'bg-emerald-50/50 border-emerald-200'
          : 'bg-amber-50/40 border-amber-200'
      }`}>
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <span className={`w-2.5 h-2.5 rounded-full ${isEnabled ? 'bg-emerald-500 animate-pulse' : 'bg-amber-500'}`} />
              <span className="text-sm font-semibold text-gray-900">
                Estado del Motor: {isEnabled ? 'ACTIVADO' : 'DESHABILITADO'}
              </span>
              <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full ${
                isEnabled
                  ? 'bg-emerald-100 text-emerald-800'
                  : 'bg-amber-100 text-amber-800'
              }`}>
                {isEnabled ? 'En ejecución automática' : 'Apagado / Sin cambios automáticos'}
              </span>
            </div>
            <p className="text-xs text-gray-600">
              {isEnabled
                ? 'Las reglas configuradas abajo se están evaluando en tiempo real y en segundo plano cada minuto.'
                : 'Ningún lead cambiará de estado automáticamente. Puedes personalizar las reglas a continuación y encenderlo cuando desees.'}
            </p>
          </div>

          <div className="flex items-center gap-3 shrink-0">
            <span className="text-xs font-medium text-gray-600">
              {isEnabled ? 'Motor Activo' : 'Motor Inactivo'}
            </span>
            <Switch
              checked={isEnabled}
              onChange={() => setConfig(prev => ({ ...prev, enabled: !prev.enabled }))}
              ariaLabel="Interruptor maestro de automatización"
            />
          </div>
        </div>
      </div>

      {/* SECCIÓN 1: REGLAS POR INTENTOS DE CONTACTO */}
      <div className="border border-gray-100 rounded-2xl p-5 bg-white shadow-xs space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-gray-100 pb-3">
          <div>
            <div className="flex items-center gap-2">
              <Phone size={16} className="text-indigo-600" />
              <h3 className="text-sm font-semibold text-gray-800">
                Reglas por intentos telefónicos y WhatsApp
              </h3>
            </div>
            <p className="text-xs text-gray-500 mt-0.5">
              Si un lead acumula las llamadas y WhatsApps indicados, se promoverá automáticamente al estado destino.
            </p>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={addReglaIntento}
            className="gap-1.5 self-start text-xs"
          >
            <Plus size={14} />
            Agregar regla de intento
          </Button>
        </div>

        {(!config?.reglas_intentos || config.reglas_intentos.length === 0) ? (
          <div className="py-8 text-center text-xs text-gray-400 bg-gray-50/50 rounded-xl border border-dashed border-gray-200">
            No hay reglas de intentos configuradas. Haz clic en "Agregar regla de intento" para crear la primera.
          </div>
        ) : (
          <div className="space-y-3">
            {config.reglas_intentos.map((regla, idx) => {
              const targetEstado = estados.find(e => e.id === Number(regla.estado_destino_id))
              return (
                <div
                  key={regla.id || idx}
                  className={`p-4 rounded-xl border transition-all ${
                    regla.activo
                      ? 'bg-gray-50/50 border-gray-200 hover:border-gray-300'
                      : 'bg-gray-100/50 border-gray-200 opacity-60'
                  }`}
                >
                  <div className="flex flex-col md:flex-row md:items-center gap-3 justify-between">
                    {/* Nombre y Orden */}
                    <div className="flex items-center gap-2 flex-1 min-w-[200px]">
                      <span className="text-[11px] font-bold text-gray-400 w-6 text-center shrink-0">
                        #{regla.orden || idx + 1}
                      </span>
                      <input
                        type="text"
                        value={regla.nombre || ''}
                        onChange={(e) => updateReglaIntento(idx, 'nombre', e.target.value)}
                        placeholder="Nombre descriptivo de la regla"
                        className="text-xs font-semibold px-2.5 py-1.5 rounded-lg border border-gray-200 bg-white text-gray-800 focus:outline-none focus:ring-1 focus:ring-indigo-500 w-full"
                      />
                    </div>

                    {/* Estado Destino Dropdown */}
                    <div className="flex items-center gap-2 min-w-[240px]">
                      <span className="text-xs text-gray-500 shrink-0">Mover a:</span>
                      <div className="relative flex-1">
                        <select
                          value={regla.estado_destino_id || ''}
                          onChange={(e) => updateReglaIntento(idx, 'estado_destino_id', Number(e.target.value))}
                          className="w-full text-xs font-medium pl-6 pr-3 py-1.5 rounded-lg border border-gray-200 bg-white text-gray-800 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                        >
                          {estados.map(est => (
                            <option key={est.id} value={est.id}>
                              {est.nombre} {est.es_final ? '(Final)' : ''}
                            </option>
                          ))}
                        </select>
                        <span
                          className="absolute left-2.5 top-1/2 -translate-y-1/2 w-2 h-2 rounded-full pointer-events-none"
                          style={{ backgroundColor: targetEstado?.color_hex || '#3b82f6' }}
                        />
                      </div>
                    </div>

                    {/* Umbrales de llamadas y WhatsApp */}
                    <div className="flex items-center gap-3">
                      <div className="flex items-center gap-1.5">
                        <Phone size={13} className="text-gray-400" />
                        <span className="text-[11px] text-gray-500">Llamadas &ge;</span>
                        <input
                          type="number"
                          min="0"
                          max="99"
                          value={regla.min_llamadas ?? 0}
                          onChange={(e) => updateReglaIntento(idx, 'min_llamadas', parseInt(e.target.value) || 0)}
                          className="w-14 text-xs text-center px-1 py-1 rounded border border-gray-200 bg-white focus:outline-none"
                        />
                      </div>

                      <div className="flex items-center gap-1.5">
                        <MessageSquare size={13} className="text-gray-400" />
                        <span className="text-[11px] text-gray-500">WA &ge;</span>
                        <input
                          type="number"
                          min="0"
                          max="99"
                          value={regla.min_whatsapp ?? 0}
                          onChange={(e) => updateReglaIntento(idx, 'min_whatsapp', parseInt(e.target.value) || 0)}
                          className="w-14 text-xs text-center px-1 py-1 rounded border border-gray-200 bg-white focus:outline-none"
                        />
                      </div>
                    </div>

                    {/* Acciones y Toggle de la Regla */}
                    <div className="flex items-center gap-2 self-end md:self-auto shrink-0">
                      <Switch
                        checked={Boolean(regla.activo)}
                        onChange={() => updateReglaIntento(idx, 'activo', !regla.activo)}
                        ariaLabel={`Activar o desactivar regla ${regla.nombre}`}
                      />
                      <button
                        type="button"
                        onClick={() => removeReglaIntento(idx)}
                        className="p-1.5 text-gray-400 hover:text-red-500 rounded-lg hover:bg-red-50 transition"
                        title="Eliminar regla"
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* SECCIÓN 2: REGLAS POR TIEMPO / TRANSICIÓN A BOLSA */}
      <div className="border border-gray-100 rounded-2xl p-5 bg-white shadow-xs space-y-4">
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-gray-100 pb-3">
          <div>
            <div className="flex items-center gap-2">
              <Clock size={16} className="text-indigo-600" />
              <h3 className="text-sm font-semibold text-gray-800">
                Reglas de transición por tiempo en estado
              </h3>
            </div>
            <p className="text-xs text-gray-500 mt-0.5">
              Mueve leads a otro estado tras X horas sin avance (ej. de un estado de no contesta a Bolsa de reciclaje).
            </p>
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={addReglaTiempo}
            className="gap-1.5 self-start text-xs"
          >
            <Plus size={14} />
            Agregar regla por tiempo
          </Button>
        </div>

        {(!config?.reglas_tiempo || config.reglas_tiempo.length === 0) ? (
          <div className="py-8 text-center text-xs text-gray-400 bg-gray-50/50 rounded-xl border border-dashed border-gray-200">
            No hay reglas por tiempo configuradas. Haz clic en "Agregar regla por tiempo" si deseas activar pases automáticos a bolsa.
          </div>
        ) : (
          <div className="space-y-3">
            {config.reglas_tiempo.map((regla, idx) => {
              const srcEstado = estados.find(e => e.id === Number(regla.estado_origen_id))
              const dstEstado = estados.find(e => e.id === Number(regla.estado_destino_id))
              return (
                <div
                  key={regla.id || idx}
                  className={`p-4 rounded-xl border transition-all ${
                    regla.activo
                      ? 'bg-gray-50/50 border-gray-200 hover:border-gray-300'
                      : 'bg-gray-100/50 border-gray-200 opacity-60'
                  }`}
                >
                  <div className="flex flex-col lg:flex-row lg:items-center gap-3 justify-between">
                    {/* Nombre */}
                    <div className="min-w-[180px] flex-1">
                      <input
                        type="text"
                        value={regla.nombre || ''}
                        onChange={(e) => updateReglaTiempo(idx, 'nombre', e.target.value)}
                        placeholder="Descripción de la transición"
                        className="text-xs font-semibold px-2.5 py-1.5 rounded-lg border border-gray-200 bg-white text-gray-800 focus:outline-none focus:ring-1 focus:ring-indigo-500 w-full"
                      />
                    </div>

                    {/* Flujo: De Estado Origen -> Horas -> Estado Destino */}
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-xs text-gray-500">Desde:</span>
                      <div className="relative min-w-[150px]">
                        <select
                          value={regla.estado_origen_id || ''}
                          onChange={(e) => updateReglaTiempo(idx, 'estado_origen_id', Number(e.target.value))}
                          className="w-full text-xs font-medium pl-6 pr-2 py-1.5 rounded-lg border border-gray-200 bg-white text-gray-800 focus:outline-none"
                        >
                          {estados.map(est => (
                            <option key={est.id} value={est.id}>{est.nombre}</option>
                          ))}
                        </select>
                        <span
                          className="absolute left-2.5 top-1/2 -translate-y-1/2 w-2 h-2 rounded-full pointer-events-none"
                          style={{ backgroundColor: srcEstado?.color_hex || '#6b7280' }}
                        />
                      </div>

                      <span className="text-xs text-gray-500">tras</span>
                      <div className="flex items-center gap-1">
                        <input
                          type="number"
                          min="1"
                          max="720"
                          value={regla.horas_espera ?? 12}
                          onChange={(e) => updateReglaTiempo(idx, 'horas_espera', parseInt(e.target.value) || 1)}
                          className="w-14 text-xs text-center px-1 py-1 rounded border border-gray-200 bg-white focus:outline-none"
                        />
                        <span className="text-xs text-gray-500">horas</span>
                      </div>

                      <span className="text-xs text-gray-500">&rarr; hacia:</span>
                      <div className="relative min-w-[150px]">
                        <select
                          value={regla.estado_destino_id || ''}
                          onChange={(e) => updateReglaTiempo(idx, 'estado_destino_id', Number(e.target.value))}
                          className="w-full text-xs font-medium pl-6 pr-2 py-1.5 rounded-lg border border-gray-200 bg-white text-gray-800 focus:outline-none"
                        >
                          {estados.map(est => (
                            <option key={est.id} value={est.id}>{est.nombre}</option>
                          ))}
                        </select>
                        <span
                          className="absolute left-2.5 top-1/2 -translate-y-1/2 w-2 h-2 rounded-full pointer-events-none"
                          style={{ backgroundColor: dstEstado?.color_hex || '#6b7280' }}
                        />
                      </div>
                    </div>

                    {/* Desasignar Asesor */}
                    <label className="flex items-center gap-2 cursor-pointer bg-white px-2.5 py-1.5 rounded-lg border border-gray-200 text-xs text-gray-700">
                      <input
                        type="checkbox"
                        checked={Boolean(regla.desasignar_asesor)}
                        onChange={(e) => updateReglaTiempo(idx, 'desasignar_asesor', e.target.checked)}
                        className="rounded text-indigo-600 focus:ring-indigo-500"
                      />
                      <span>Desasignar asesor</span>
                    </label>

                    {/* Switch y Eliminar */}
                    <div className="flex items-center gap-2 shrink-0">
                      <Switch
                        checked={Boolean(regla.activo)}
                        onChange={() => updateReglaTiempo(idx, 'activo', !regla.activo)}
                        ariaLabel={`Activar o desactivar regla ${regla.nombre}`}
                      />
                      <button
                        type="button"
                        onClick={() => removeReglaTiempo(idx)}
                        className="p-1.5 text-gray-400 hover:text-red-500 rounded-lg hover:bg-red-50 transition"
                        title="Eliminar regla"
                      >
                        <Trash2 size={15} />
                      </button>
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* SECCIÓN 3: PROTECCIONES Y REGLAS ESPECIALES */}
      <div className="border border-gray-100 rounded-2xl p-5 bg-white shadow-xs space-y-4">
        <div>
          <div className="flex items-center gap-2">
            <Shield size={16} className="text-indigo-600" />
            <h3 className="text-sm font-semibold text-gray-800">
              Protecciones y exclusiones automáticas
            </h3>
          </div>
          <p className="text-xs text-gray-500 mt-0.5">
            Garantiza que leads contactados exitosamente o atendidos de forma especial no sean afectados.
          </p>
        </div>

        <div className="divide-y divide-gray-100">
          <div className="py-3 flex items-center justify-between gap-4">
            <div>
              <div className="text-xs font-semibold text-gray-800">
                Excluir leads con contacto efectivo registrado
              </div>
              <div className="text-[11px] text-gray-500 mt-0.5">
                Si un lead tiene alguna llamada con duración &gt; 0, cita agendada o resultado de contacto positivo (ej. Contestó, Interesado, Matrícula), no se moverá a estados de no contesta.
              </div>
            </div>
            <Switch
              checked={Boolean(config?.excluir_contacto_efectivo)}
              onChange={() => setConfig(prev => ({ ...prev, excluir_contacto_efectivo: !prev.excluir_contacto_efectivo }))}
              ariaLabel="Excluir leads con contacto efectivo"
            />
          </div>

          <div className="py-3 flex items-center justify-between gap-4">
            <div>
              <div className="text-xs font-semibold text-gray-800">
                Respetar Gestión Especial por Administración (🛡️)
              </div>
              <div className="text-[11px] text-gray-500 mt-0.5">
                Si un usuario administrador modificó manualmente el estado de un lead, se mantendrá exento de las transiciones automáticas.
              </div>
            </div>
            <Switch
              checked={Boolean(config?.respetar_gestion_admin)}
              onChange={() => setConfig(prev => ({ ...prev, respetar_gestion_admin: !prev.respetar_gestion_admin }))}
              ariaLabel="Respetar gestión especial por administración"
            />
          </div>
        </div>
      </div>

      {/* Resultado de Test / Ejecución Manual */}
      {testResult && (
        <div className="p-4 rounded-xl bg-indigo-50/60 border border-indigo-200 text-xs text-indigo-900 space-y-2 animate-fadeIn">
          <div className="flex items-center gap-2 font-semibold">
            <CheckCircle size={15} className="text-indigo-600" />
            Resumen de la última ejecución manual:
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1 text-center font-mono">
            <div className="p-2 bg-white rounded-lg border border-indigo-100">
              <div className="text-lg font-bold text-indigo-700">{testResult.total_movidos ?? 0}</div>
              <div className="text-[10px] text-gray-500 uppercase">Total Movidos</div>
            </div>
            {testResult.detalles && Object.entries(testResult.detalles).map(([k, v]) => (
              <div key={k} className="p-2 bg-white rounded-lg border border-indigo-100">
                <div className="text-lg font-bold text-gray-800">{v}</div>
                <div className="text-[10px] text-gray-500 truncate" title={k}>{k}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Barra de Acciones */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pt-2">
        <Button
          type="button"
          variant="outline"
          onClick={handleRunNow}
          disabled={testing || saving}
          className="gap-2 text-xs"
        >
          {testing ? <Loader size={14} className="animate-spin" /> : <Play size={14} className="text-indigo-600" />}
          {testing ? 'Evaluando leads...' : 'Probar ejecución manual ahora'}
        </Button>

        <Button
          type="button"
          onClick={handleSave}
          disabled={saving || testing}
          className="gap-2"
        >
          {saving ? <Loader size={14} className="animate-spin" /> : <CheckCircle size={15} />}
          {saving ? 'Guardando configuración...' : 'Guardar Configuración'}
        </Button>
      </div>
    </div>
  )
}


export default function Configuracion() {
  const { user } = useAuthStore()
  const { isDark, setTheme } = useThemeStore()
  const isAdmin = user?.role === 'admin' || user?.role === 'supervisor'
  const isStrictAdmin = user?.role === 'admin'

  // ADR-0011 — helper para chequear permisos custom (rol con role_id). Permite
  // que usuarios con rol custom (ej. marketing_proveedor con `usuarios.manage`
  // = true) puedan acceder a tabs como Usuarios sin ser admin legacy.
  // Admin legacy SIEMPRE pasa (bypass clásico).
  const perms = user?.permissions || {}
  const hasPerm = (key) => (
    isStrictAdmin || perms._all === true || perms[key] === true
  )
  const canManageUsers       = hasPerm('usuarios.manage')
  const canManageRoles       = hasPerm('roles.manage')
  const canManageConfig      = hasPerm('config.manage')
  const [searchParams, setSearchParams] = useSearchParams()
  const defaultTab = isAdmin ? 'general' : 'seguridad'
  const initialTab = searchParams.get('tab') || defaultTab
  const [tab, setTab] = useState(initialTab)

  const changeTab = (id) => {
    setTab(id)
    if (id === 'general') {
      setSearchParams({})
    } else {
      setSearchParams({ tab: id })
    }
    // Al cambiar de sección devolvemos el scroll arriba. Sin esto el
    // usuario ve el tab nuevo arrancando "desde el medio" porque el
    // scroll del contenedor (<main>) se queda donde estaba.
    // Usamos 'instant' para evitar que la animación se solape con el
    // render del nuevo tab o con el auto-scroll del sidebar.
    const mainEl = document.querySelector('main')
    if (mainEl) mainEl.scrollTo({ top: 0, behavior: 'instant' })
    else window.scrollTo({ top: 0, behavior: 'instant' })
  }
  const [servicios, setServicios] = useState(Object.fromEntries(SERVICIOS.map((s) => [s.id, 'desconocido'])))
  const [verificando, setVerificando] = useState(false)
  const [passwordForm, setPasswordForm] = useState({ actual: '', nueva: '', confirmar: '' })
  const [passwordMsg, setPasswordMsg] = useState(null)
  const [smtp, setSmtp] = useState(SMTP_DEFAULTS)
  const [smtpMsg, setSmtpMsg] = useState(null)
  const [smtpLoading, setSmtpLoading] = useState(false)
  const [smtpTestLoading, setSmtpTestLoading] = useState(false)
  const [smtpTestMsg, setSmtpTestMsg] = useState(null)
  const [showSmtpPass, setShowSmtpPass] = useState(false)

  // En mobile mostramos el sidebar como drawer colapsable.
  const [mobileNavOpen, setMobileNavOpen] = useState(false)

  // Filtro de tabs en el sidebar (patrón estándar: "Search settings").
  // Mantenemos la lista original intacta y filtramos por label al render.
  const [navQuery, setNavQuery] = useState('')

  useEffect(() => {
    api.get('/api/settings/smtp')
      .then(res => setSmtp({ ...SMTP_DEFAULTS, ...res.data }))
      .catch(() => {})
  }, [])

  const verificarConexiones = useCallback(async () => {
    setVerificando(true)
    setServicios(Object.fromEntries(SERVICIOS.map((s) => [s.id, 'verificando'])))
    try {
      const response = await api.get('/api/health')
      const { db, demo } = response.data
      if (demo) {
        setServicios({ api: 'online', db: 'demo_mode', ollama: 'demo_mode', claude: 'demo_mode' })
      } else {
        setServicios({ api: 'online', db: db === 'connected' ? 'online' : 'offline', ollama: 'desconocido', claude: 'desconocido' })
      }
    } catch {
      setServicios({ api: 'offline', db: 'offline', ollama: 'offline', claude: 'offline' })
    } finally {
      setVerificando(false)
    }
  }, [])

  useEffect(() => { verificarConexiones() }, [verificarConexiones])

  // Cuando cambia el tab activo (incluye el mount inicial con ?tab=…),
  // hacemos scroll del item dentro del sidebar para que siempre sea
  // visible aunque caiga debajo del fold (ej. Etiquetas, Seguridad).
  //
  // Importante: hacemos el scroll manualmente sobre el contenedor
  // interno del sidebar (marcado con data-config-nav-scroll) en vez de
  // `scrollIntoView`. Este último burbujea y puede scrollear también
  // al <main>, cancelando el scrollTo(top:0) que disparamos en
  // changeTab — lo que hacía que al cambiar de tab la página
  // apareciera "en la mitad" en lugar de arrancar desde su encabezado.
  useEffect(() => {
    const btn = document.querySelector(`[data-config-tab="${tab}"]`)
    if (!btn) return
    const container = btn.closest('[data-config-nav-scroll]')
    if (!container) return
    const btnRect = btn.getBoundingClientRect()
    const containerRect = container.getBoundingClientRect()
    if (btnRect.top < containerRect.top) {
      container.scrollTop += btnRect.top - containerRect.top - 8
    } else if (btnRect.bottom > containerRect.bottom) {
      container.scrollTop += btnRect.bottom - containerRect.bottom + 8
    }
  }, [tab])

  const handlePasswordSubmit = async (e) => {
    e.preventDefault()
    setPasswordMsg(null)
    if (!passwordForm.actual || !passwordForm.nueva) { setPasswordMsg({ tipo: 'error', texto: 'Completa todos los campos.' }); return }
    if (passwordForm.nueva !== passwordForm.confirmar) { setPasswordMsg({ tipo: 'error', texto: 'La contraseña nueva no coincide con la confirmación.' }); return }
    if (passwordForm.nueva.length < 6) { setPasswordMsg({ tipo: 'error', texto: 'La contraseña debe tener al menos 6 caracteres.' }); return }
    try {
      await api.post('/auth/change-password', {
        current_password: passwordForm.actual,
        new_password: passwordForm.nueva,
      })
      setPasswordMsg({ tipo: 'ok', texto: 'Contraseña actualizada exitosamente.' })
      setPasswordForm({ actual: '', nueva: '', confirmar: '' })
    } catch (err) {
      setPasswordMsg({ tipo: 'error', texto: err.response?.data?.detail || 'Error al cambiar contraseña' })
    }
  }

  const handleSmtpSubmit = async (e) => {
    e.preventDefault()
    setSmtpMsg(null)
    setSmtpLoading(true)
    try {
      await api.put('/api/settings/smtp', smtp)
      setSmtpMsg({ tipo: 'ok', texto: 'Configuración SMTP guardada exitosamente.' })
    } catch {
      setSmtpMsg({ tipo: 'error', texto: 'No se pudo guardar la configuración SMTP.' })
    } finally {
      setSmtpLoading(false)
    }
  }

  const isDemoMode = import.meta.env.VITE_DEMO_MODE === 'true'

function PanelJefaturaPermisosTab() {
  const [supervisores, setSupervisores] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState(null)

  const loadPermisos = async () => {
    setLoading(true)
    try {
      const res = await api.get('/api/dashboard/jefatura/permisos')
      setSupervisores(res.data.supervisores || [])
    } catch (err) {
      setMsg({ tipo: 'error', texto: 'Error al cargar permisos de supervisores.' })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadPermisos()
  }, [])

  const handleToggle = (id) => {
    setSupervisores(prev =>
      prev.map(s => s.supervisor_id === id ? { ...s, permitido: !s.permitido } : s)
    )
  }

  const handleSave = async () => {
    setSaving(true)
    setMsg(null)
    try {
      const permitidosIds = supervisores.filter(s => s.permitido).map(s => s.supervisor_id)
      await api.post('/api/dashboard/jefatura/permisos', { supervisores_ids: permitidosIds })
      setMsg({ tipo: 'ok', texto: 'Permisos del Panel de Jefatura actualizados correctamente.' })
    } catch (err) {
      setMsg({ tipo: 'error', texto: 'Error al guardar los permisos.' })
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="space-y-6 max-w-4xl animate-fadeIn">
      <div>
        <h2 className="text-base font-semibold text-gray-900 flex items-center gap-2">
          <LayoutDashboard size={18} className="text-indigo-600" />
          Permisos de Acceso al Panel de Jefatura
        </h2>
        <p className="text-xs text-gray-400 mt-1">
          Por defecto, el Panel de Jefatura solo es visible para Administradores. Activa aquí qué supervisores individuales tienen autorización para visualizar este panel consolidado de métricas y SLA.
        </p>
      </div>

      <MsgBox msg={msg} />

      <div className="bg-white border border-gray-100 rounded-2xl overflow-hidden shadow-xs">
        <div className="p-4 bg-gray-50/70 border-b border-gray-100 flex items-center justify-between text-xs text-gray-500 font-semibold">
          <span>Supervisor</span>
          <span>Acceso al Panel</span>
        </div>

        {loading ? (
          <div className="p-8 text-center text-xs text-gray-400 flex items-center justify-center gap-2">
            <Loader size={16} className="animate-spin text-indigo-500" />
            Cargando supervisores...
          </div>
        ) : (
          <div className="divide-y divide-gray-100">
            {supervisores.map(s => (
              <div key={s.supervisor_id} className="p-4 flex items-center justify-between hover:bg-gray-50/50 transition-colors">
                <div>
                  <div className="text-sm font-semibold text-gray-800">{s.nombre}</div>
                  <div className="text-xs text-gray-400 flex items-center gap-2 mt-0.5">
                    <span>{s.email}</span>
                    <span>·</span>
                    <span className="bg-indigo-50 text-indigo-600 font-medium px-2 py-0.5 rounded-full text-[10px]">
                      {s.total_asesores_equipo || 0} asesores en equipo
                    </span>
                  </div>
                </div>
                <div className="flex items-center gap-3">
                  <span className={`text-xs font-semibold ${s.permitido ? 'text-indigo-600' : 'text-gray-400'}`}>
                    {s.permitido ? 'Habilitado' : 'Sin Acceso'}
                  </span>
                  <Switch
                    checked={!!s.permitido}
                    onChange={() => handleToggle(s.supervisor_id)}
                    ariaLabel={`Permitir acceso a ${s.nombre}`}
                  />
                </div>
              </div>
            ))}
            {supervisores.length === 0 && (
              <div className="p-8 text-center text-xs text-gray-400">
                No hay supervisores activos registrados en el sistema.
              </div>
            )}
          </div>
        )}
      </div>

      <div className="flex justify-end">
        <Button onClick={handleSave} disabled={saving || loading} className="gap-2">
          {saving ? <Loader size={14} className="animate-spin" /> : <CheckCircle size={15} />}
          {saving ? 'Guardando...' : 'Guardar Permisos'}
        </Button>
      </div>
    </div>
  )
}

  // ADR-0011 — Lookup de cuáles tabs requieren qué permission custom.
  // Si el usuario tiene esa permission en su rol custom, el tab se le muestra
  // aunque su `role` text legacy no esté en `t.roles`.
  const TAB_PERMISSION_MAP = {
    usuarios:       'usuarios.manage',
    roles:          'roles.manage',
    sharing_rules:  'roles.manage',
    auditoria:      'roles.manage',  // mismo nivel que gestionar los roles auditados
    integraciones: 'integraciones.manage',
    general:        'config.manage',
    marca:          'config.manage',
    sedes:          'config.manage',
    panel_jefatura: 'config.manage',
    automatizaciones: 'config.manage',
  }
  // V089 — Algunos tabs requieren un permiso explícito incluso si no tienen
  // `t.roles` restrictivo (es decir, "todos los autenticados pueden verlo
  // salvo que el admin lo bloquee a un rol específico"). Default es TRUE en
  // built-ins admin/supervisor/asesor, así que es backward-compat.
  const TAB_REQUIRES_PERMISSION = {
    mis_notifs: 'notificaciones.manage_own',
  }
  const visibleTabs = TABS.filter(t => {
    // V089 — gate de "requiere permiso explícito". Admin legacy bypasea.
    const requireKey = TAB_REQUIRES_PERMISSION[t.id]
    if (requireKey && user?.role !== 'admin' && !hasPerm(requireKey)) return false

    if (!t.roles) return true
    if (t.roles.includes(user?.role)) return true
    // Permite tabs si el usuario tiene el permission custom correspondiente.
    const requiredKey = TAB_PERMISSION_MAP[t.id]
    if (requiredKey && hasPerm(requiredKey)) return true
    return false
  })
  const currentTabMeta = visibleTabs.find(t => t.id === tab)

  const handleTabClick = (id) => {
    changeTab(id)
    setMobileNavOpen(false)
  }

  const currentCategory = CATEGORIES.find(c => c.id === currentTabMeta?.group)
  const TabIcon = currentTabMeta?.icon || Settings
  const q = navQuery.trim().toLowerCase()

  return (
    <div>
      {/* Breadcrumb: Categoría / Sección.
          El app shell ya muestra "PDR › Configuración", así que arrancamos
          desde la categoría para evitar repetir "Configuración" dos veces.
          Patrón configuración profesional / configuración profesional. */}
      {(currentCategory || currentTabMeta) && (
        <nav className="flex items-center gap-1.5 text-xs text-gray-500 mb-3" aria-label="Ruta de navegación">
          {currentCategory && <span>{currentCategory.label}</span>}
          {currentCategory && currentTabMeta && (
            <ChevronRight size={12} className="text-gray-300" />
          )}
          {currentTabMeta && (
            <span className="text-gray-700 font-medium">{currentTabMeta.label}</span>
          )}
        </nav>
      )}

      {/* Encabezado premium: ícono grande + título dinámico + descripción.
          Reemplaza al header estático "Configuración" por uno que refleja
          la sección activa (igual que panel profesional / patrón estándar). */}
      <div className="flex items-start gap-3 pb-5 mb-6 border-b border-gray-100">
        <div
          className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
          style={{ backgroundColor: 'rgba(var(--brand-primary-rgb), 0.1)' }}
        >
          <TabIcon size={20} style={{ color: 'var(--brand-primary)' }} />
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-semibold text-gray-900 leading-tight">
            {currentTabMeta?.label || 'Configuración'}
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {currentTabMeta?.description || 'Ajustes generales del sistema.'}
          </p>
        </div>
      </div>

      {/* Breadcrumb mobile: tab actual + toggle del drawer de navegación. */}
      <div className="md:hidden mb-4 flex items-center justify-between border border-gray-200 rounded-lg px-3 py-2 bg-white">
        <div className="flex items-center gap-2 text-sm font-medium text-gray-800">
          {currentTabMeta?.icon && <currentTabMeta.icon size={15} className="text-gray-500" />}
          {currentTabMeta?.label || 'Secciones'}
        </div>
        <button
          type="button"
          onClick={() => setMobileNavOpen(v => !v)}
          className="text-xs text-[var(--brand-primary)] font-semibold"
        >
          {mobileNavOpen ? 'Cerrar' : 'Ver secciones'}
        </button>
      </div>

      <div className="md:grid md:grid-cols-[260px_1fr] md:gap-6 items-start">
        {/* Sidebar vertical agrupado por categoría con búsqueda — patrón
            configuración profesional ("Search settings") + configuración profesional.
            Sticky con altura máxima = viewport, search fijo arriba y
            la lista de categorías scrollea internamente. Sin esto los
            tabs del final (Etiquetas, Categorías Chat, Correo, Seguridad)
            quedaban debajo del fold y no se veían. */}
        <nav
          className={`${
            mobileNavOpen ? 'block' : 'hidden'
          } md:flex md:flex-col md:sticky md:top-4 md:max-h-[calc(100dvh-13rem)] mb-4 md:mb-0`}
          aria-label="Secciones de configuración"
        >
          <div className="relative mb-4 shrink-0 pr-2">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 pointer-events-none" />
            {/* SafeTextInput blinda contra el bug del Escape → "null" causado por
                extensiones del browser que sobreescriben el value directo al DOM. */}
            <SafeTextInput
              type="search"
              value={navQuery}
              onChange={(v) => setNavQuery(v)}
              placeholder="Buscar en configuración…"
              name="crm_config_nav_search_unique"
              className="w-full text-sm rounded-lg border border-gray-200 bg-white pl-9 pr-3 py-2 placeholder:text-gray-400 focus:outline-none focus:border-[var(--brand-primary)]/50 focus:ring-2 focus:ring-[var(--brand-primary)]/15 transition"
            />
          </div>

          <div
            data-config-nav-scroll
            className="md:flex-1 md:min-h-0 md:overflow-y-auto wa-scrollbar pr-2 pb-10"
          >
            {(() => {
              const rendered = CATEGORIES.map((cat, idx) => {
                const items = visibleTabs.filter(t =>
                  t.group === cat.id && (!q || t.label.toLowerCase().includes(q))
                )
                if (items.length === 0) return null
                return (
                  <div key={cat.id} className={idx > 0 ? 'mt-5 pt-4 border-t border-gray-100' : ''}>
                    <div className="px-2 mb-2 text-[11px] font-semibold uppercase tracking-[0.08em] text-gray-400">
                      {cat.label}
                    </div>
                    <ul className="space-y-0.5">
                      {items.map(t => {
                        const Icon = t.icon
                        const isActive = tab === t.id
                        return (
                          <li key={t.id} className="relative">
                            {isActive && (
                              <span
                                aria-hidden
                                className="absolute left-0 top-1.5 bottom-1.5 w-[3px] rounded-r-full"
                                style={{ backgroundColor: 'var(--brand-primary)' }}
                              />
                            )}
                            <button
                              type="button"
                              data-config-tab={t.id}
                              onClick={() => handleTabClick(t.id)}
                              className={`w-full flex items-center gap-2.5 pl-3 pr-2.5 py-2 rounded-lg text-sm text-left transition-colors ${
                                isActive
                                  ? 'bg-[var(--brand-primary)]/[0.06] text-gray-900 font-semibold'
                                  : 'text-gray-600 hover:bg-gray-50 hover:text-gray-900'
                              }`}
                            >
                              <Icon
                                size={15}
                                style={isActive ? { color: 'var(--brand-primary)' } : undefined}
                                className={isActive ? '' : 'text-gray-400'}
                              />
                              <span className="truncate">{t.label}</span>
                            </button>
                          </li>
                        )
                      })}
                    </ul>
                  </div>
                )
              }).filter(Boolean)

              if (rendered.length === 0) {
                return (
                  <div className="text-xs text-gray-400 px-2 py-4">
                    Sin resultados para “{navQuery}”.
                  </div>
                )
              }
              return rendered
            })()}
          </div>
        </nav>

        {/* Contenido de la sección activa — framing de tarjeta premium
            (bg blanco, borde sutil, radius 12px, sombra ligera). */}
        <div className="min-w-0">
          <div className="bg-white border border-gray-100 rounded-xl shadow-sm p-5 sm:p-7">

        {/* ============ MARCA (admin legacy o roles con config.manage) ============ */}
        {tab === 'marca' && canManageConfig && <MarcaManager />}

        {/* ============ SEDES (V065 — admin legacy o roles con config.manage) ============ */}
        {tab === 'sedes' && canManageConfig && <SedesManager />}

        {/* ============ USUARIOS (admin legacy o permission usuarios.manage) ============ */}
        {tab === 'usuarios' && canManageUsers && <UsuariosPage />}

        {/* ============ ROLES Y PERMISOS (admin legacy o roles.manage) — ADR-0011 ============ */}
        {tab === 'roles' && canManageRoles && <RolesPage />}

        {/* ============ VISTAS COMPARTIDAS (admin legacy o roles.manage) — ADR-0012 ============ */}
        {tab === 'sharing_rules' && canManageRoles && <SharingRulesPage />}

        {/* ============ AUDITORÍA (admin legacy o roles.manage) — Ley 29733 ============ */}
        {tab === 'auditoria' && canManageRoles && <PermissionAuditPage />}

        {/* ============ EQUIPOS (admin) ============ */}
        {tab === 'equipos' && (isAdmin || user?.role === 'supervisor') && <EquiposManager />}

        {/* ============ ESTADOS (admin) ============ */}
        {tab === 'estados' && isAdmin && <EstadosManager />}

        {/* ============ AUTOMATIZACIÓN DE ESTADOS (admin) ============ */}
        {tab === 'automatizaciones' && isStrictAdmin && <LeadAutomationConfigSection />}

        {/* ============ ESTADOS DE CITA (admin/supervisor) — V042 ============ */}
        {tab === 'cita_estados' && isAdmin && (
          <EstadosManager
            baseEndpoint="/api/cita-estados"
            title="Estados de cita"
            description="Estados de las citas agendadas: Pendiente, Completada, Reprogramada, Cancelada, No asistió. El supervisor las marca tras la cita para medir efectividad."
            newButtonLabel="Nuevo estado de cita"
          />
        )}

        {/* ============ CALIDAD (admin) ============ */}
        {tab === 'calidad' && isAdmin && <CalidadManager />}

        {/* ============ FUENTES (admin) ============ */}
        {tab === 'fuentes' && isAdmin && <FuentesManager />}

        {/* ============ CAMPAÑAS (admin/supervisor) ============ */}
        {tab === 'campanas' && isAdmin && <CampanasManager />}

        {/* ============ ETIQUETAS (admin/supervisor) ============ */}
        {tab === 'etiquetas' && isAdmin && <TagsManager />}

        {/* ============ DUPLICADOS (V067 — solo admin) ============ */}
        {tab === 'duplicados' && isStrictAdmin && <DuplicatesManager />}

        {/* ============ CONTACTOS (admin) ============ */}
        {tab === 'contactos' && isAdmin && <ContactosManager />}

        {/* ============ CHIPS CHAT (admin) ============ */}
        {tab === 'chips' && isStrictAdmin && <ChipsLabelsManager />}
        {tab === 'ia' && isStrictAdmin && <AiClassifierConfigSection />}
        {tab === 'push' && isStrictAdmin && <NotificationsConfigSection />}
        {tab === 'movil' && isStrictAdmin && <MobileSyncSection />}
        {tab === 'mis_notifs' && (
          hasPerm('notificaciones.manage_own')
            ? <MyNotificationPrefsSection />
            : (
              // V089 — el admin revocó este permiso. Mostramos un mensaje
              // amigable en lugar de la sección, para que el usuario sepa
              // por qué la pantalla no está disponible (no es un bug).
              <div className="max-w-2xl">
                <div className="bg-amber-50 border border-amber-200 rounded-2xl p-6 flex items-start gap-4">
                  <div className="w-10 h-10 rounded-xl bg-amber-100 flex items-center justify-center shrink-0">
                    <BellRing size={20} className="text-amber-700" />
                  </div>
                  <div className="min-w-0">
                    <h2 className="text-base font-semibold text-amber-900">Tu administrador gestiona estas notificaciones</h2>
                    <p className="text-sm text-amber-800 mt-1.5 leading-relaxed">
                      Para esta empresa, las preferencias de push (kill switch y horario silencioso)
                      las controla el administrador. Si necesitas pausar tus notificaciones por un día
                      libre o vacaciones, coordínalo con tu supervisor.
                    </p>
                  </div>
                </div>
              </div>
            )
        )}

        {/* ============ GENERAL ============ */}
        {tab === 'general' && (
          <div className="space-y-6 max-w-4xl">
            {/* Estado del sistema */}
            <div>
              <div className="flex items-center justify-between mb-4">
                <div>
                  <h2 className="text-base font-semibold text-gray-900">Estado del Sistema</h2>
                  <p className="text-xs text-gray-400 mt-0.5">Conexión a los servicios del sistema.</p>
                </div>
                <Button
                  variant="outline" size="sm"
                  onClick={verificarConexiones} disabled={verificando}
                  className="gap-1.5"
                >
                  <RefreshCw size={14} className={verificando ? 'animate-spin' : ''} />
                  Verificar
                </Button>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {SERVICIOS.map((servicio) => {
                  const Icon = servicio.icon
                  return (
                    <div key={servicio.id} className="flex items-center gap-3 p-3 rounded-xl border border-gray-100 bg-gray-50/60">
                      <div className={`w-10 h-10 rounded-xl ${servicio.bg} flex items-center justify-center shrink-0`}>
                        <Icon size={18} className={servicio.color} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-semibold text-gray-800">{servicio.label}</p>
                        <p className="text-xs text-gray-400 truncate">{servicio.descripcion}</p>
                      </div>
                      <div className="flex flex-col items-center gap-0.5 shrink-0">
                        <StatusDot estado={servicios[servicio.id]} />
                        <StatusLabel estado={servicios[servicio.id]} />
                      </div>
                    </div>
                  )
                })}
              </div>
              {isDemoMode && (
                <div className="mt-4 bg-amber-50 border border-amber-200 rounded-lg p-3 text-sm text-amber-800">
                  <strong>Modo Demo activo.</strong> Los servicios muestran estado simulado.
                </div>
              )}
            </div>

            {/* Apariencia / Tema de la plataforma */}
            <div>
              <div className="mb-3">
                <h2 className="text-base font-semibold text-gray-900">Apariencia</h2>
                <p className="text-xs text-gray-400 mt-0.5">Personaliza el tema visual de la plataforma en este dispositivo.</p>
              </div>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                <button
                  type="button"
                  onClick={() => setTheme('light')}
                  className={`p-4 rounded-xl border text-left transition-all flex items-start gap-3 cursor-pointer ${
                    !isDark
                      ? 'border-[var(--brand-primary)] bg-[var(--brand-primary)]/[0.04] ring-2 ring-[var(--brand-primary)]/20'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <div className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${!isDark ? 'bg-amber-100 text-amber-600' : 'bg-gray-100 text-gray-500'}`}>
                    <Sun size={18} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <p className="text-sm font-semibold text-gray-900">Modo Claro</p>
                      {!isDark && <Check size={16} className="text-[var(--brand-primary)] font-bold" />}
                    </div>
                    <p className="text-xs text-gray-400 mt-0.5">Interfaz limpia y luminosa para ambientes con luz.</p>
                  </div>
                </button>

                <button
                  type="button"
                  onClick={() => setTheme('dark')}
                  className={`p-4 rounded-xl border text-left transition-all flex items-start gap-3 cursor-pointer ${
                    isDark
                      ? 'border-[var(--brand-primary)] bg-[var(--brand-primary)]/[0.04] ring-2 ring-[var(--brand-primary)]/20'
                      : 'border-gray-200 hover:border-gray-300'
                  }`}
                >
                  <div className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 ${isDark ? 'bg-indigo-900/50 text-indigo-400' : 'bg-gray-100 text-gray-500'}`}>
                    <Moon size={18} />
                  </div>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between">
                      <p className="text-sm font-semibold text-gray-900">Modo Oscuro</p>
                      {isDark && <Check size={16} className="text-[var(--brand-primary)] font-bold" />}
                    </div>
                    <p className="text-xs text-gray-400 mt-0.5">Fondo oscuro slate de alto contraste que reduce el cansancio visual.</p>
                  </div>
                </button>
              </div>
            </div>

            {/* Información del sistema.
                __BUILD_COMMIT__ y __BUILD_TIME__ los inyecta vite.config.js
                al momento del build (commit corto + fecha ISO). Sirve para
                verificar a simple vista que build esta corriendo en lab vs
                prod — pidiendole al usuario un screenshot de este card. */}
            <div>
              <h2 className="text-base font-semibold text-gray-900 mb-3">Información del Sistema</h2>
              <div className="border border-gray-100 rounded-xl overflow-hidden">
                {[
                  { label: 'Versión', value: 'v3.0' },
                  { label: 'Build', value: (() => {
                    // Hash puede venir vacio (Docker build sin git) — en ese caso
                    // mostramos solo la fecha (sin el "unknown ·" feo).
                    const commit = typeof __BUILD_COMMIT__ !== 'undefined' ? __BUILD_COMMIT__ : ''
                    const t = typeof __BUILD_TIME__ !== 'undefined' ? __BUILD_TIME__ : ''
                    const d = t ? new Date(t).toLocaleString('es-PE', { dateStyle: 'short', timeStyle: 'short' }) : ''
                    if (commit && d) return `${commit} · ${d}`
                    if (commit) return commit
                    if (d) return d
                    return 'dev'
                  })() },
                  { label: 'Cliente', value: 'Palma del Río — Inmobiliaria' },
                  { label: 'Modo', value: isDemoMode ? 'Demo (sin base de datos)' : 'Producción' },
                ].map(({ label, value }, i) => (
                  <div key={label} className={`flex items-center justify-between px-4 py-3 text-sm ${i > 0 ? 'border-t border-gray-100' : ''}`}>
                    <span className="text-gray-500">{label}</span>
                    <span className="font-medium text-gray-800 text-right font-mono text-xs">{value}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ============ CORREO (solo admin) ============ */}
        {tab === 'correo' && isStrictAdmin && (
          <div className="max-w-4xl">
            <div className="mb-5">
              <h2 className="text-base font-semibold text-gray-900">Configuración de Correo (SMTP)</h2>
              <p className="text-xs text-gray-400 mt-0.5">Ajustes del servidor de correo para invitaciones y alertas.</p>
            </div>

            <form onSubmit={handleSmtpSubmit} className="space-y-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1.5">Dirección remitente</label>
                  <input type="email" value={smtp.from_address} onChange={(e) => setSmtp(s => ({ ...s, from_address: e.target.value }))}
                    placeholder="notificaciones@tudominio.com"
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1.5">Dominio del remitente</label>
                  <input type="text" value={smtp.from_domain} onChange={(e) => setSmtp(s => ({ ...s, from_domain: e.target.value }))}
                    placeholder="tudominio.com"
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                <div className="sm:col-span-2">
                  <label className="block text-sm font-medium text-gray-700 mb-1.5">Servidor SMTP</label>
                  <input type="text" value={smtp.smtp_server} onChange={(e) => setSmtp(s => ({ ...s, smtp_server: e.target.value }))}
                    placeholder="smtp.gmail.com"
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1.5">Puerto SMTP</label>
                  <input type="number" value={smtp.smtp_port} onChange={(e) => setSmtp(s => ({ ...s, smtp_port: parseInt(e.target.value) || 587 }))}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" />
                </div>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1.5">Usuario SMTP</label>
                  <input type="text" value={smtp.username} onChange={(e) => setSmtp(s => ({ ...s, username: e.target.value }))}
                    placeholder="usuario@gmail.com" autoComplete="off"
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" />
                </div>
                <div>
                  <label className="block text-sm font-medium text-gray-700 mb-1.5">Contraseña SMTP</label>
                  <div className="relative">
                    <input type={showSmtpPass ? 'text' : 'password'} value={smtp.password} onChange={(e) => setSmtp(s => ({ ...s, password: e.target.value }))}
                      placeholder="••••••••" autoComplete="new-password"
                      className="w-full rounded-lg border border-gray-300 px-3 py-2 pr-10 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500" />
                    <button type="button" onClick={() => setShowSmtpPass(!showSmtpPass)} tabIndex={-1}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600">
                      {showSmtpPass ? <EyeOff size={16} /> : <Eye size={16} />}
                    </button>
                  </div>
                </div>
              </div>

              {/* Toggles */}
              <div className="space-y-2.5 pt-1">
                {[
                  { key: 'use_ssl', label: 'Usar conexión segura (SSL/TLS)', description: 'Habilita cifrado SSL/TLS para la conexión SMTP.' },
                  { key: 'ignore_tls_errors', label: 'Ignorar errores TLS', description: 'No detiene el envío si hay errores de certificado.' },
                  { key: 'reject_unauthorized', label: 'Rechazar certificados no autorizados', description: 'Recomendado en producción.' },
                ].map(({ key, label, description }) => (
                  <div key={key} className="flex items-start gap-3">
                    <Switch
                      checked={!!smtp[key]}
                      onChange={() => setSmtp(s => ({ ...s, [key]: !s[key] }))}
                      ariaLabel={label}
                    />
                    <div>
                      <p className="text-sm font-medium text-gray-700">{label}</p>
                      <p className="text-xs text-gray-400">{description}</p>
                    </div>
                  </div>
                ))}
              </div>

              <MsgBox msg={smtpMsg} />

              <div className="flex gap-3 pt-1">
                <Button type="submit" disabled={smtpLoading}>
                  {smtpLoading ? (
                    <span className="flex items-center gap-2"><Loader size={14} className="animate-spin" />Guardando...</span>
                  ) : 'Guardar configuración SMTP'}
                </Button>
                <Button type="button" variant="outline" disabled={smtpTestLoading}
                  onClick={async () => {
                    setSmtpTestMsg(null)
                    const testTo = smtp.from_address || smtp.username
                    if (!testTo) { setSmtpTestMsg({ tipo: 'error', texto: 'Configura un email primero.' }); return }
                    setSmtpTestLoading(true)
                    try {
                      const res = await api.post('/api/settings/smtp/test', { to: testTo })
                      setSmtpTestMsg({ tipo: 'ok', texto: res.data.message })
                    } catch (err) {
                      setSmtpTestMsg({ tipo: 'error', texto: err.response?.data?.detail || 'Error al probar SMTP' })
                    } finally { setSmtpTestLoading(false) }
                  }}
                >
                  {smtpTestLoading ? (
                    <span className="flex items-center gap-2"><Loader size={14} className="animate-spin" />Probando...</span>
                  ) : 'Probar envío'}
                </Button>
              </div>

              <MsgBox msg={smtpTestMsg} />
            </form>
          </div>
        )}

        {/* ============ PANEL JEFATURA PERMISOS (solo admin) ============ */}
        {tab === 'panel_jefatura' && isStrictAdmin && (
          <PanelJefaturaPermisosTab />
        )}

        {/* ============ SEGURIDAD ============ */}
        {tab === 'seguridad' && (
          <div className="max-w-4xl">
            <div className="mb-5">
              <h2 className="text-base font-semibold text-gray-900">Cambiar Contraseña</h2>
              <p className="text-xs text-gray-400 mt-0.5">Actualiza la contraseña de tu cuenta.</p>
            </div>

            <form onSubmit={handlePasswordSubmit} className="space-y-4 max-w-sm">
              {[
                { id: 'actual', label: 'Contraseña actual', field: 'actual' },
                { id: 'nueva', label: 'Nueva contraseña', field: 'nueva' },
                { id: 'confirmar', label: 'Confirmar nueva contraseña', field: 'confirmar' },
              ].map(({ id, label, field }) => (
                <div key={id}>
                  <label htmlFor={id} className="block text-sm font-medium text-gray-700 mb-1.5">{label}</label>
                  <input
                    id={id} type="password" value={passwordForm[field]}
                    onChange={(e) => setPasswordForm((p) => ({ ...p, [field]: e.target.value }))}
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    placeholder="••••••••"
                  />
                </div>
              ))}

              <MsgBox msg={passwordMsg} />

              <Button type="submit">
                Actualizar contraseña
              </Button>
            </form>
          </div>
        )}

          </div>
        </div>
      </div>
    </div>
  )
}
