import { useState, useEffect, useLayoutEffect, useCallback, useRef } from 'react'
import { createPortal } from 'react-dom'
import { Users, Plus, Trash2, Shield, Briefcase, UserCheck, Mail, Copy, Check, X, Clock, Send, MoreVertical, RefreshCw, Link2, Search, Pencil, Key, Sparkles, MailCheck, UserX, UserCog, Lock } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog, DialogHeader, DialogContent } from '@/components/ui/dialog'
import LoadingSpinner from '@/components/shared/LoadingSpinner'
import ConfirmDialog from '@/components/shared/ConfirmDialog'
import { useUndoToast } from '@/components/shared/UndoToast'
import api from '@/lib/api'
import useAuthStore from '@/store/authStore'
import { hasPermission } from '@/lib/permissions'
import { normalizePhonePE, normalizePhonePEEdit } from '@/lib/phone'

// Roles legacy fallback. Si el endpoint /api/roles falla, se usa esta lista.
const LEGACY_ROLES = [
  { value: 'admin', label: 'Administrador', icon: Shield },
  { value: 'supervisor', label: 'Supervisor', icon: Briefcase },
  { value: 'asesor', label: 'Asesor', icon: UserCheck },
]

// Map de etiquetas built-in para que la badge se muestre con el label en español
// que ya usaban los usuarios existentes.
const BUILTIN_LABELS = { admin: 'Administrador', supervisor: 'Supervisor', asesor: 'Asesor' }

// V5.63 — Validacion de email cliente-side (paridad backend RFC 5322).
// Detecta @@, espacios, falta de TLD, etc. Patron pragmatico que cubre
// >99% de casos reales (no perseguimos compliance perfecta RFC, eso es
// para el server). Si pasa esta validacion, el SMTP la valida en server.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/

function emailValidationMsg(email) {
  const v = (email ?? '').trim()
  if (!v) return 'El correo es obligatorio.'
  if (EMAIL_RE.test(v)) return null
  if (v.split('@').length > 2) return 'El correo no puede tener más de un símbolo @.'
  if (!v.includes('@')) return 'El correo debe contener un @.'
  if (/\s/.test(v)) return 'El correo no puede tener espacios.'
  if (!v.split('@')[1]?.includes('.')) return 'El dominio debe incluir un punto (ej: empresa.com).'
  return 'Formato de correo inválido (ej: nombre@empresa.com).'
}

// V5.63 — Validacion de telefono inline. Reusa normalizePhonePE para
// mensaje. Si esta vacio devuelve null (campo opcional en edicion).
function phoneValidationMsg(raw, initial) {
  const v = (raw ?? '').trim()
  if (!v) return null  // Opcional: vacio no es error
  const r = normalizePhonePEEdit(v, initial || '')
  return r.error  // null si valido, string si invalido
}

function RoleBadge({ role, roleName, isActive, loginBlocked }) {
  // V088 — si el usuario está deshabilitado, la badge de rol queda eclipsada
  // por una badge "Deshabilitado" más prominente. Sin esto el admin se
  // confunde y piensa que el usuario sigue operativo.
  if (isActive === false) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium border border-amber-200 bg-amber-50 text-amber-800">
        <UserX size={12} />
        Deshabilitado
      </span>
    )
  }
  // roleName puede venir de role_name (rol custom). Si no hay roleName, usa
  // el rol legacy text con su label en español. Default Asesor para no romper
  // si llega un nombre desconocido.
  const baseLabel = BUILTIN_LABELS[role] || role || 'Asesor'
  const label = roleName
    ? (BUILTIN_LABELS[roleName] || roleName)
    : baseLabel
  // V090 — tooltip con la combinación dual (rol legacy + rol custom).
  // Resuelve la confusión donde el admin veía solo el rol custom y no
  // sabía qué rol base operativo tenía el usuario.
  const tooltip = roleName
    ? `Rol base: ${baseLabel} · Rol custom: ${label}`
    : `Rol: ${label}`
  // V094 — usuario activo pero con login bloqueado: badge del rol + chip
  // "Login bloqueado" al lado. Sigue visible en todas las listas (es la
  // diferencia con `is_active=false`), pero el admin debe saber que no
  // puede entrar.
  const roleBadge = (
    <span
      title={tooltip}
      className="inline-flex items-center gap-1 px-2.5 py-1 rounded-md text-xs font-medium border border-gray-200 bg-white text-gray-600"
    >
      {label}
    </span>
  )
  if (loginBlocked) {
    return (
      <span className="inline-flex items-center gap-1.5">
        {roleBadge}
        <span
          title="El usuario sigue visible en listas pero no puede iniciar sesión."
          className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-[11px] font-medium border border-slate-300 bg-slate-50 text-slate-600"
        >
          <Lock size={11} />
          Login bloqueado
        </span>
      </span>
    )
  }
  return roleBadge
}

/** Dropdown menu de tres puntos — usa fixed positioning para evitar overflow clip */
function ActionMenu({ items }) {
  const [open, setOpen] = useState(false)
  const btnRef = useRef(null)
  const menuRef = useRef(null)
  const [pos, setPos] = useState({ top: 0, left: 0 })

  useEffect(() => {
    if (!open) return
    const handleClick = (e) => {
      if (btnRef.current?.contains(e.target)) return
      if (menuRef.current && !menuRef.current.contains(e.target)) setOpen(false)
    }
    const handleScroll = () => setOpen(false)
    document.addEventListener('mousedown', handleClick)
    window.addEventListener('scroll', handleScroll, true)
    return () => { document.removeEventListener('mousedown', handleClick); window.removeEventListener('scroll', handleScroll, true) }
  }, [open])

  // V067.9 — useLayoutEffect: sincrónico antes del paint. Garantiza que el
  // segundo render (con coords reales tras medir offsetHeight) se aplique
  // antes de que el browser pinte el primer frame. Sin esto, el menu se
  // pintaba primero en -9999 (off-screen) y luego saltaba a su posición.
  // Aunque -9999 estaba fuera de pantalla, el double-paint era costoso.
  useLayoutEffect(() => {
    if (!open || !menuRef.current || !btnRef.current) return
    const rect = btnRef.current.getBoundingClientRect()
    const menuH = menuRef.current.offsetHeight
    const spaceBelow = window.innerHeight - rect.bottom
    const top = spaceBelow < menuH + 8
      ? Math.max(8, rect.top - menuH - 4)
      : rect.bottom + 4
    setPos({ top, left: Math.max(8, rect.right - 264) })
  }, [open])

  const toggle = () => {
    if (!open && btnRef.current) {
      const rect = btnRef.current.getBoundingClientRect()
      setPos({ top: -9999, left: rect.right - 264 })
    }
    setOpen(!open)
  }

  return (
    <>
      <button
        ref={btnRef}
        onClick={toggle}
        className="w-8 h-8 flex items-center justify-center rounded-md border border-gray-200 hover:bg-gray-50 text-gray-400 hover:text-gray-600 transition-colors"
      >
        <MoreVertical size={15} />
      </button>
      {/* V092.1 — Portal al document.body para que el menú NO herede
          la `opacity-60` de la <tr> de un usuario deshabilitado.
          Sin esto, abrir el ⋮ en una fila deshabilitada renderizaba
          el menú semi-transparente y dejaba ver el contenido detrás.
          createPortal saca el nodo del subtree y lo monta al final
          del body, fuera de cualquier stacking context heredado. */}
      {open && createPortal(
        <div
          ref={menuRef}
          className="fixed w-64 bg-white border border-gray-200 rounded-lg shadow-xl py-1.5"
          style={{ top: pos.top, left: Math.max(8, pos.left), zIndex: 9999 }}
        >
          {items.map((item, i) => (
            item.separator ? (
              <div key={i} className="border-t border-gray-100 my-1.5" />
            ) : (
              <button
                key={i}
                onClick={() => { setOpen(false); item.onClick() }}
                disabled={item.disabled}
                className={`w-full text-left px-4 py-2 text-[13px] flex items-center gap-3 transition-colors
                  ${item.danger ? 'text-red-600 hover:bg-red-50' : 'text-gray-700 hover:bg-gray-50'}
                  ${item.disabled ? 'opacity-40 cursor-not-allowed' : ''}`}
              >
                {item.icon && <item.icon size={15} className={item.danger ? 'text-red-400' : 'text-gray-400'} />}
                {item.label}
              </button>
            )
          ))}
        </div>,
        document.body,
      )}
    </>
  )
}

export default function Usuarios() {
  const { user } = useAuthStore()
  const [users, setUsers] = useState([])
  const [invitations, setInvitations] = useState([])
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState(null)
  const [deletingId, setDeletingId] = useState(null)
  const [confirmDeleteUser, setConfirmDeleteUser] = useState(null)
  // V070.81 — ConfirmDialog premium en lugar de window.confirm() nativo
  // para cambio de rol y cancelacion de invitacion (consistencia UX).
  const [confirmRoleChange, setConfirmRoleChange] = useState(null)  // {user, newRole, roleLabel}
  const [confirmCancelInvite, setConfirmCancelInvite] = useState(null)  // invitacion
  const [search, setSearch] = useState('')
  const [editUser, setEditUser] = useState(null)
  const [editForm, setEditForm] = useState({ first_name: '', last_name: '' })
  const [editLoading, setEditLoading] = useState(false)
  const [editError, setEditError] = useState('')
  const [waNumbers, setWaNumbers] = useState([])
  // V087 — pre-check de duplicado de email en vivo mientras el admin tipea.
  // null = sin chequear, true = libre, {owner_name, owner_email} = ocupado.
  const [emailAvailability, setEmailAvailability] = useState(null)
  const [emailChecking, setEmailChecking] = useState(false)

  // V087 — confirmacion antes de enviar correo de restablecimiento (es una
  // operacion sensible: notifica al usuario, deja audit log).
  const [confirmSendReset, setConfirmSendReset] = useState(null)
  // V088 — confirmacion antes de deshabilitar / re-habilitar usuario.
  // Soft-disable correcto (is_active=false) en vez del DELETE destructivo.
  const [confirmToggleActive, setConfirmToggleActive] = useState(null)
  const [togglingActive, setTogglingActive] = useState(false)
  const [sendingReset, setSendingReset] = useState(false)

  // V090 — Modal de reasignación de leads pre-disable.
  // null = cerrado. Si abierto: { user, leadsCount, mode, targetUserId, error }
  const [reassignModal, setReassignModal] = useState(null)
  const [reassigning, setReassigning] = useState(false)
  // V090 — Loading state al "Quitar rol personalizado".
  const [clearingCustomRoleId, setClearingCustomRoleId] = useState(null)
  // V092 — Confirm dialog del freeze rápido (bloquear inicio de sesión).
  const [confirmFreeze, setConfirmFreeze] = useState(null)
  const [freezing, setFreezing] = useState(false)

  // Modal states
  const [showCreateModal, setShowCreateModal] = useState(false)
  const [showInviteModal, setShowInviteModal] = useState(false)

  // Create user form
  const [form, setForm] = useState({ email: '', password: '', role: 'asesor', role_id: null, first_name: '', last_name: '', telefono: '' })
  const [formError, setFormError] = useState('')
  const [formLoading, setFormLoading] = useState(false)

  // Invite form
  const [inviteEmail, setInviteEmail] = useState('')
  const [inviteRole, setInviteRole] = useState('asesor')
  const [inviteRoleId, setInviteRoleId] = useState(null)  // ADR-0011: rol custom opcional
  const [inviteLoading, setInviteLoading] = useState(false)
  const [inviteError, setInviteError] = useState('')
  const [inviteSuccess, setInviteSuccess] = useState(null)
  const [copiedUrl, setCopiedUrl] = useState(false)

  // ADR-0011 — Roles disponibles cargados desde /api/roles. Incluye built-in
  // (admin/supervisor/asesor) + customs creados en /configuracion/roles
  // (marketing, etc).
  const [availableRoles, setAvailableRoles] = useState([])

  // ADR-0011 — Modal de asignación de rol custom desde el menú de cada usuario.
  // null cuando cerrado; { user, selectedRoleId } cuando abierto.
  const [customRoleModal, setCustomRoleModal] = useState(null)
  const [assigningRole, setAssigningRole] = useState(false)

  // Toast
  const [toast, setToast] = useState(null)
  const showToast = (msg) => { setToast(msg); setTimeout(() => setToast(null), 3000) }
  // V087.1 — Undo toast global (provider en App.jsx). Usado en saves
  // reversibles como editar datos del usuario.
  const { showUndoToast } = useUndoToast()

  const fetchUsers = useCallback(async (silent = false) => {
    if (!silent) { setIsLoading(true); setError(null) }
    try {
      const [usersRes, invRes] = await Promise.all([
        api.get('/auth/users'),
        api.get('/auth/invitations').catch(() => ({ data: [] })),
      ])
      setUsers(usersRes.data)
      setInvitations(invRes.data)
    } catch (err) {
      if (!silent) setError(err.response?.data?.detail || 'Error al cargar usuarios')
    } finally {
      if (!silent) setIsLoading(false)
    }
  }, [])

  useEffect(() => { fetchUsers() }, [fetchUsers])

  useEffect(() => {
    api.get('/api/whatsapp/numbers', { params: { only_active: true } })
      .then(res => setWaNumbers(res.data?.items || []))
      .catch(() => setWaNumbers([]))
  }, [])

  // ADR-0011 — Carga roles disponibles para el dropdown del modal Invitar/Crear.
  // Fallback silencioso a los 3 legacy si el endpoint falla (ej. backend
  // pre-V078 desplegado).
  useEffect(() => {
    api.get('/api/roles')
      .then(res => setAvailableRoles(Array.isArray(res.data) ? res.data : []))
      .catch(() => setAvailableRoles([]))
  }, [])

  useEffect(() => {
    const interval = setInterval(() => fetchUsers(true), 15000)
    return () => clearInterval(interval)
  }, [fetchUsers])

  const resetCreateForm = () => {
    setForm({ email: '', password: '', role: 'asesor', role_id: null, first_name: '', last_name: '', telefono: '' })
    setFormError('')
  }

  const resetInviteForm = () => {
    setInviteEmail('')
    setInviteRole('asesor')
    setInviteRoleId(null)
    setInviteError('')
    setInviteSuccess(null)
    setCopiedUrl(false)
  }

  const handleCreate = async (e) => {
    e.preventDefault()
    setFormError('')
    if (!form.email.includes('@')) {
      setFormError('Ingresa un email válido'); return
    }
    if (!form.password || form.password.length < 6) {
      setFormError('La contraseña debe tener al menos 6 caracteres'); return
    }
    // V070.96 — telefono opcional, pero si se ingresa debe ser valido E.164.
    let phoneToSend = form.telefono
    if (form.telefono && form.telefono.trim()) {
      const r = normalizePhonePE(form.telefono)
      if (!r.valid) { setFormError(`Teléfono inválido: ${r.error}`); return }
      phoneToSend = r.normalized
    }
    setFormLoading(true)
    try {
      // ADR-0011: si hay role_id custom, lo mandamos junto con el role legacy
      // ('asesor' por default cuando es custom). El backend asigna role_id si
      // viene; si no, usa solo el role legacy text como antes.
      const payload = { ...form, telefono: phoneToSend }
      if (!form.role_id) delete payload.role_id  // no mandar null por limpieza
      await api.post('/auth/users', payload)
      resetCreateForm()
      setShowCreateModal(false)
      fetchUsers()
    } catch (err) {
      setFormError(err.response?.data?.detail || 'Error al crear usuario')
    } finally {
      setFormLoading(false)
    }
  }

  const handleInvite = async (e) => {
    e.preventDefault()
    setInviteError('')
    setInviteSuccess(null)
    if (!inviteEmail.includes('@')) {
      setInviteError('Ingresa un email válido'); return
    }
    setInviteLoading(true)
    try {
      // ADR-0011: mando `role` legacy + `role_id` opcional para roles custom.
      // Backend lo guarda en auth.invitations.role_id y al aceptar la invitación
      // vincula el usuario a ese role_id.
      const payload = { email: inviteEmail, role: inviteRole }
      if (inviteRoleId) payload.role_id = inviteRoleId
      const res = await api.post('/auth/invite', payload)
      setInviteSuccess(res.data)
      setInviteEmail('')
      fetchUsers()
    } catch (err) {
      setInviteError(err.response?.data?.detail || 'Error al enviar invitación')
    } finally {
      setInviteLoading(false)
    }
  }

  const handleEditOpen = (u) => {
    setEditUser(u)
    setEditForm({
      first_name: u.first_name || '',
      last_name: u.last_name || '',
      email: u.email || '',
      telefono: u.telefono || '',
      default_wa_number_id: u.default_wa_number_id ?? 0,
    })
    setEditError('')
    setEmailAvailability(null)
    setEmailChecking(false)
  }

  // V087 — pre-check con debounce mientras tipea. Solo dispara al backend
  // si el email es sintacticamente valido Y distinto del actual del user.
  useEffect(() => {
    if (!editUser) return
    const next = (editForm.email ?? '').trim().toLowerCase()
    const current = (editUser.email ?? '').trim().toLowerCase()
    // Sin cambio o sin email aun -> limpiar estado, no consultar.
    if (!next || next === current) {
      setEmailAvailability(null)
      setEmailChecking(false)
      return
    }
    // Email malformado -> el validador inline ya muestra el error, no
    // gastamos un round-trip al backend.
    if (emailValidationMsg(next)) {
      setEmailAvailability(null)
      setEmailChecking(false)
      return
    }
    setEmailChecking(true)
    const timer = setTimeout(async () => {
      try {
        const res = await api.get('/auth/users/check-email', {
          params: { email: next, exclude_user_id: editUser.id },
        })
        setEmailAvailability(res.data)
      } catch {
        // Si el endpoint falla (404 si backend antiguo), no bloqueamos el
        // submit — el PATCH va a devolver 409 si hay colision real.
        setEmailAvailability(null)
      } finally {
        setEmailChecking(false)
      }
    }, 400)
    return () => clearTimeout(timer)
  }, [editForm.email, editUser])

  const handleEditSave = async () => {
    setEditLoading(true); setEditError('')

    // V5.63 — Validacion pre-submit (email + telefono) con mensaje
    // especifico antes de pegarle al backend. Si algo invalido,
    // mostramos el error inline y abortamos.
    const emailErr = emailValidationMsg(editForm.email ?? editUser.email)
    if (emailErr) {
      setEditError(emailErr)
      setEditLoading(false)
      return
    }

    // V070.98 — dirty validation: si el telefono no cambio del valor original
    // del usuario, permitimos guardar aunque sea legacy junk. Solo bloqueamos
    // si el supervisor tipea un valor nuevo invalido (patrón estándar).
    let payload = editForm
    if (editForm.telefono && String(editForm.telefono).trim()) {
      const r = normalizePhonePEEdit(editForm.telefono, editUser?.telefono || '')
      if (!r.valid) {
        setEditError(`Teléfono inválido: ${r.error}`)
        setEditLoading(false)
        return
      }
      payload = { ...editForm, telefono: r.normalized }
    }
    // V087.1 — Snapshot del estado previo para ofrecer "Deshacer" 8s.
    // Solo incluimos los 4 campos que el PATCH realmente modifica.
    const prevSnapshot = {
      first_name: editUser.first_name || '',
      last_name:  editUser.last_name || '',
      email:      editUser.email || '',
      telefono:   editUser.telefono || '',
      default_wa_number_id: editUser.default_wa_number_id ?? null,
    }
    const userId = editUser.id

    try {
      await api.patch(`/auth/users/${userId}`, payload)
      setEditUser(null)
      fetchUsers()
      showUndoToast({
        message: 'Cambios guardados en el usuario.',
        onUndo: async () => {
          try {
            await api.patch(`/auth/users/${userId}`, prevSnapshot)
            await fetchUsers(true)
            showToast('Cambios revertidos')
          } catch (err) {
            alert(err.response?.data?.detail || 'No se pudo deshacer el cambio')
          }
        },
      })
    } catch (err) {
      setEditError(err.response?.data?.detail || 'Error al guardar')
    } finally { setEditLoading(false) }
  }

  const handleCopyResetLink = async (u) => {
    try {
      const res = await api.post(`/auth/users/${u.id}/reset-link`)
      const url = `${window.location.origin}/reset-password?token=${res.data.token}`
      await navigator.clipboard.writeText(url)
      showToast('Enlace de restablecimiento copiado')
    } catch (err) {
      alert(err.response?.data?.detail || 'Error al generar enlace')
    }
  }

  // V070.81 — abre modal en vez de confirm() nativo. La accion real
  // ocurre en handleRoleChangeConfirm tras confirmar.
  const handleRoleChange = (u, newRole) => {
    const roleLabel = { admin: 'Administrador', supervisor: 'Supervisor', asesor: 'Asesor' }
    setConfirmRoleChange({ user: u, newRole, roleLabel: roleLabel[newRole] })
  }

  const handleRoleChangeConfirm = async () => {
    if (!confirmRoleChange) return
    const { user: u, newRole, roleLabel } = confirmRoleChange
    setConfirmRoleChange(null)
    try {
      await api.patch(`/auth/users/${u.id}/role`, { role: newRole })
      showToast(`Rol actualizado a ${roleLabel}`)
      fetchUsers()
    } catch (err) {
      alert(err.response?.data?.detail || 'Error al cambiar rol')
    }
  }

  const handleDelete = (u) => {
    setConfirmDeleteUser(u)
  }

  // V088 — Soft-disable / re-habilitar usuario.
  // V090 — Si vamos a DESHABILITAR y el user tiene leads activos, abrimos
  // primero el modal de reasignación. Para re-habilitar saltamos directo
  // al confirm porque no hay leads que mover.
  // V092 — Default inteligente del modal según el rol: para supervisores
  // no preseleccionamos "Devolver al supervisor del equipo" porque ellos
  // SON el supervisor del equipo.
  const handleToggleActive = async (u) => {
    const willDisable = u.is_active !== false
    if (!willDisable) {
      // Re-habilitar: confirm simple, no hay leads que mover.
      setConfirmToggleActive(u)
      return
    }
    // Disable: chequear leads activos. Si > 0, abrir modal de reasignación.
    try {
      const res = await api.get(`/auth/users/${u.id}/active-leads-count`)
      const leadsCount = res.data?.count || 0
      if (leadsCount > 0) {
        const smartDefault = u.role === 'asesor' ? 'supervisor' : 'asesor'
        setReassignModal({
          user: u,
          leadsCount,
          mode: smartDefault,
          targetUserId: '',
          error: null,
        })
      } else {
        // Sin leads activos: confirm directo de deshabilitar.
        setConfirmToggleActive(u)
      }
    } catch {
      // Si el endpoint falla, igual permitimos deshabilitar con confirm
      // simple — no bloqueamos al admin por una falla de pre-check.
      setConfirmToggleActive(u)
    }
  }

  // V092 — Freeze rápido (patrón estándar). Bloquea login + cierra sesiones
  // SIN reasignar leads. Útil para lockout urgente, vacaciones cortas, o
  // cuando el user NO es asesor (supervisor sin supervisor arriba).
  // V094 — ahora usa endpoint dedicado /login-blocked que NO toca is_active.
  // El usuario sigue visible en TODAS las listas operacionales (rotación,
  // asignación, equipos, dropdowns) — solo se le impide entrar al CRM.
  const handleFreezeLogin = (u) => {
    setConfirmFreeze(u)
  }

  const handleFreezeLoginConfirm = async () => {
    if (!confirmFreeze) return
    const u = confirmFreeze
    const willBlock = !u.login_blocked
    setFreezing(true)
    try {
      await api.patch(`/auth/users/${u.id}/login-blocked`, { login_blocked: willBlock })
      const nombre = u.nombre_completo || u.email
      showToast(
        willBlock
          ? `Inicio de sesión bloqueado para ${nombre}. Sigue visible en las listas.`
          : `Inicio de sesión desbloqueado para ${nombre}. Ya puede entrar de nuevo.`
      )
      setConfirmFreeze(null)
      fetchUsers()
    } catch (err) {
      alert(err.response?.data?.detail || 'No se pudo cambiar el bloqueo de inicio de sesión')
    } finally {
      setFreezing(false)
    }
  }

  const handleToggleActiveConfirm = async () => {
    if (!confirmToggleActive) return
    const u = confirmToggleActive
    const nextActive = !u.is_active
    setTogglingActive(true)
    try {
      await api.patch(`/auth/users/${u.id}/active`, { is_active: nextActive })
      showToast(
        nextActive
          ? `${u.nombre_completo || u.email} re-habilitado`
          : `${u.nombre_completo || u.email} deshabilitado`
      )
      setConfirmToggleActive(null)
      fetchUsers()
    } catch (err) {
      alert(err.response?.data?.detail || 'Error al cambiar el estado del usuario')
    } finally {
      setTogglingActive(false)
    }
  }

  // V090 — Reasignar leads y después deshabilitar en una sola operación.
  // V092 — Errores inline en el modal (no más alert() nativo).
  const handleReassignAndDisable = async () => {
    if (!reassignModal) return
    const { user: u, mode, targetUserId } = reassignModal
    if (mode === 'asesor' && !targetUserId) {
      setReassignModal(prev => ({ ...prev, error: 'Selecciona el asesor destino antes de continuar.' }))
      return
    }
    setReassigning(true)
    setReassignModal(prev => ({ ...prev, error: null }))
    try {
      // 1) Reasignar los leads (mode=keep es no-op).
      const reassignRes = await api.post(`/auth/users/${u.id}/reassign-leads`, {
        mode,
        target_user_id: mode === 'asesor' ? targetUserId : null,
      })
      const reassigned = reassignRes.data?.reassigned || 0
      const targetName = reassignRes.data?.target_name

      // 2) Deshabilitar el usuario.
      await api.patch(`/auth/users/${u.id}/active`, { is_active: false })

      let msg = `${u.nombre_completo || u.email} deshabilitado.`
      if (mode === 'supervisor' && reassigned > 0) {
        msg += ` ${reassigned} lead${reassigned === 1 ? '' : 's'} → cola de ${targetName}.`
      } else if (mode === 'asesor' && reassigned > 0) {
        msg += ` ${reassigned} lead${reassigned === 1 ? '' : 's'} → ${targetName}.`
      } else if (mode === 'unassign' && reassigned > 0) {
        msg += ` ${reassigned} lead${reassigned === 1 ? '' : 's'} ahora sin asesor.`
      } else if (mode === 'keep') {
        msg += ` Sus leads quedaron asignados a él (huérfanos).`
      }
      showToast(msg)
      setReassignModal(null)
      fetchUsers()
    } catch (err) {
      // V092 — Error inline en el modal con guía accionable según el modo.
      const detail = err.response?.data?.detail || 'No se pudo reasignar / deshabilitar.'
      setReassignModal(prev => ({ ...prev, error: detail }))
    } finally {
      setReassigning(false)
    }
  }

  // V090 — Acción directa "Quitar rol personalizado" sin pasar por modal.
  const handleClearCustomRole = async (u) => {
    setClearingCustomRoleId(u.id)
    try {
      await api.patch(`/api/roles/users/${u.id}`, { role_id: null })
      showToast(
        `Rol personalizado quitado. ${u.nombre_completo || u.email} vuelve al rol ${u.role}.`
      )
      fetchUsers()
    } catch (err) {
      alert(err.response?.data?.detail || 'No se pudo quitar el rol personalizado')
    } finally {
      setClearingCustomRoleId(null)
    }
  }

  const handleConfirmDelete = async () => {
    if (!confirmDeleteUser) return
    const u = confirmDeleteUser
    setConfirmDeleteUser(null)
    setDeletingId(u.id)
    try {
      await api.delete(`/auth/users/${u.id}`)
      fetchUsers()
    } catch (err) {
      alert(err.response?.data?.detail || 'Error al eliminar usuario')
    } finally {
      setDeletingId(null)
    }
  }

  const handleResendInvite = async (email, role) => {
    try {
      const res = await api.post('/auth/invite', { email, role })
      const msg = res.data?.email_sent
        ? `Invitación enviada a ${email}`
        : `Invitación creada — copia el enlace manualmente`
      showToast(msg)
      fetchUsers(true)  // silent: no muestra loading spinner
    } catch (err) {
      alert(err.response?.data?.detail || 'Error al reenviar invitación')
    }
  }

  // V087 — envia correo de restablecimiento de contraseña al usuario
  // activo. Backend genera token de 24h + envia email branded + audita.
  const handleSendResetEmail = (u) => {
    setConfirmSendReset(u)
  }

  const handleSendResetEmailConfirm = async () => {
    if (!confirmSendReset) return
    const u = confirmSendReset
    setSendingReset(true)
    try {
      const res = await api.post(`/auth/users/${u.id}/send-reset-email`)
      const targetEmail = res.data?.target_email || u.email
      showToast(`Correo de restablecimiento enviado a ${targetEmail}`)
      setConfirmSendReset(null)
    } catch (err) {
      // 502 = SMTP fallo. El backend ya genero el token y dejo audit, asi
      // que el admin puede caer al fallback de "Copiar URL" sin perder nada.
      alert(err.response?.data?.detail || 'No se pudo enviar el correo de restablecimiento')
    } finally {
      setSendingReset(false)
    }
  }

  // ADR-0011 — Abrir modal de asignación de rol custom.
  const openCustomRoleModal = (u) => {
    setCustomRoleModal({ user: u, selectedRoleId: u.role_id ?? null })
  }

  // ADR-0011 — Aplicar la asignación (PATCH al endpoint que ya existe).
  const handleAssignCustomRole = async () => {
    if (!customRoleModal) return
    const { user: u, selectedRoleId } = customRoleModal
    setAssigningRole(true)
    try {
      await api.patch(`/api/roles/users/${u.id}`, { role_id: selectedRoleId })
      const newRoleLabel = selectedRoleId
        ? (availableRoles.find((r) => r.id === selectedRoleId)?.name || `id=${selectedRoleId}`)
        : 'rol legacy'
      showToast(`Rol actualizado a ${newRoleLabel}. El usuario lo verá al volver a iniciar sesión.`)
      setCustomRoleModal(null)
      fetchUsers()
    } catch (err) {
      alert(err.response?.data?.detail || 'Error al asignar el rol personalizado')
    } finally {
      setAssigningRole(false)
    }
  }

  // V070.81 — abre modal en vez de confirm() nativo.
  const handleCancelInvite = (inv) => {
    setConfirmCancelInvite(inv)
  }

  const handleCancelInviteConfirm = async () => {
    if (!confirmCancelInvite) return
    const inv = confirmCancelInvite
    setConfirmCancelInvite(null)
    try {
      await api.delete(`/auth/invitations/${inv.id}`)
      fetchUsers()
    } catch (err) {
      alert(err.response?.data?.detail || 'Error al cancelar invitación')
    }
  }

  const copyToClipboard = (text, msg) => {
    navigator.clipboard.writeText(text)
    if (msg) showToast(msg)
    setCopiedUrl(true)
    setTimeout(() => setCopiedUrl(false), 2000)
  }

  const buildInviteUrl = (token) => `${window.location.origin}/invite?token=${token}`

  if (!hasPermission(user, 'usuarios.manage')) {
    return <div className="p-8 text-center text-gray-500">No tienes permisos para acceder a esta sección.</div>
  }

  // Filtrar por búsqueda
  const filteredUsers = users.filter(u => {
    const nombre = [u.first_name, u.last_name].filter(Boolean).join(' ')
    return !search ||
      (u.email || '').toLowerCase().includes(search.toLowerCase()) ||
      nombre.toLowerCase().includes(search.toLowerCase())
  }).map(u => ({
    ...u,
    nombre_completo: [u.first_name, u.last_name].filter(Boolean).join(' ') || u.email
  }))

  const pendingInvites = invitations.filter(i => !i.accepted_at && new Date(i.expires_at) > new Date())

  return (
    <div className="space-y-0 max-w-4xl mx-auto">
      {/* Toast */}
      {toast && (
        <div className="fixed top-4 right-4 z-50 bg-slate-800 text-white px-4 py-2.5 rounded-lg shadow-lg text-sm flex items-center gap-2">
          <Check size={14} />
          {toast}
        </div>
      )}

      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 bg-indigo-50 rounded-lg flex items-center justify-center">
            <Users size={18} className="text-indigo-600" />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-gray-900">Gestión de usuarios</h1>
            <p className="text-gray-400 text-xs">{users.length} miembros{pendingInvites.length > 0 && ` · ${pendingInvites.length} pendientes`}</p>
          </div>
        </div>
        <Button onClick={() => { resetInviteForm(); setShowInviteModal(true) }} className="gap-1.5 h-9 px-4 text-sm">
          <Plus size={15} />
          Invitar a un usuario
        </Button>
      </div>

      {/* Search + refresh */}
      <div className="flex items-center gap-3 mb-4">
        <div className="relative flex-1 max-w-sm">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input
            type="search"
            placeholder="Buscar por nombre o correo…"
            value={search ?? ''}
            onChange={(e) => setSearch(e.target.value ?? '')}
            className="w-full h-9 pl-9 pr-3 rounded-lg border border-gray-200 bg-white text-sm text-gray-700 placeholder-gray-400 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
            autoComplete="off"
            spellCheck={false}
          />
        </div>
        <button
          onClick={() => fetchUsers()}
          className="w-9 h-9 flex items-center justify-center rounded-lg border border-gray-200 hover:bg-gray-50 text-gray-400 hover:text-gray-600 transition-colors"
        >
          <RefreshCw size={15} />
        </button>
      </div>

      {/* Users table */}
      <div className="border border-gray-200 rounded-xl overflow-hidden bg-white">
        {isLoading ? (
          <div className="py-12"><LoadingSpinner message="Cargando usuarios..." /></div>
        ) : error ? (
          <div className="p-6">
            <div className="bg-red-50 border border-red-200 text-red-700 rounded-md p-4 text-sm">{error}</div>
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-100">
                <th className="text-left px-5 py-3 font-medium text-gray-500 text-xs uppercase tracking-wider">Usuarios</th>
                <th className="text-center px-5 py-3 font-medium text-gray-500 text-xs uppercase tracking-wider w-44">Acceder</th>
                <th className="text-center px-3 py-3 font-medium text-gray-500 text-xs uppercase tracking-wider w-24">Acciones</th>
              </tr>
            </thead>
            <tbody>
              {filteredUsers.map((u) => (
                <tr key={u.id} className={`border-b border-gray-50 hover:bg-gray-50/60 transition-colors ${u.is_active === false ? 'opacity-60' : ''}`}>
                  <td className="px-5 py-3.5">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 bg-indigo-100 rounded-full flex items-center justify-center shrink-0">
                        <span className="text-indigo-600 font-semibold text-xs">
                          {(u.nombre_completo || u.username).charAt(0).toUpperCase()}
                        </span>
                      </div>
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-gray-900 truncate">{u.nombre_completo}</p>
                        <p className="text-xs text-gray-400 truncate">{u.email}</p>
                        {u.default_wa_number_name && (
                          <p className="text-[11px] text-emerald-600 truncate mt-0.5">WA: {u.default_wa_number_name}</p>
                        )}
                      </div>
                    </div>
                  </td>
                  <td className="px-5 py-3.5 text-center">
                    {/* ADR-0011 — si el usuario tiene rol custom (role_name), la badge
                        muestra ese label en vez del rol legacy. Para legacy puro,
                        roleName es undefined y RoleBadge cae al role text. */}
                    <RoleBadge
                      role={u.role}
                      roleName={u.role_name}
                      isActive={u.is_active}
                      loginBlocked={u.login_blocked}
                    />
                  </td>
                  <td className="px-3 py-3.5 text-center">
                    {u.id !== user?.user_id ? (
                      <ActionMenu items={[
                        { icon: Pencil, label: 'Editar datos', onClick: () => handleEditOpen(u) },
                        // V087 — Acciones de credenciales agrupadas: primero la
                        // primaria (email automatico al usuario), despues el
                        // fallback manual (copiar URL si SMTP falla).
                        { icon: MailCheck, label: 'Enviar correo de restablecimiento de contraseña', onClick: () => handleSendResetEmail(u) },
                        { icon: Key, label: 'Copiar enlace de restablecimiento', onClick: () => handleCopyResetLink(u) },
                        { separator: true },
                        ...(u.role !== 'supervisor' ? [{ icon: Briefcase, label: 'Cambiar a Supervisor', onClick: () => handleRoleChange(u, 'supervisor') }] : []),
                        ...(u.role !== 'asesor' ? [{ icon: UserCheck, label: 'Cambiar a Asesor', onClick: () => handleRoleChange(u, 'asesor') }] : []),
                        // ADR-0011 — Asignar/cambiar/quitar rol custom solo si hay
                        // roles custom disponibles. Sino el item no aparece (no
                        // confunde al admin con una opción inútil).
                        ...(availableRoles.filter((r) => !r.is_builtin).length > 0 ? [{
                          icon: Sparkles,
                          label: u.role_id
                            ? `Cambiar rol personalizado (actual: ${u.role_name || 'custom'})`
                            : 'Asignar rol personalizado',
                          onClick: () => openCustomRoleModal(u),
                        }] : []),
                        // V090 — Acción directa para quitar el rol personalizado
                        // sin abrir el modal. Resuelve la confusión donde el
                        // admin no sabía cómo "regresar a asesor" cuando el
                        // user tenía un rol custom encima. Solo aparece si el
                        // user tiene role_id asignado.
                        ...(u.role_id ? [{
                          icon: UserCheck,
                          label: clearingCustomRoleId === u.id
                            ? 'Quitando rol personalizado…'
                            : `Quitar rol personalizado (volver a ${BUILTIN_LABELS[u.role] || u.role || 'asesor'})`,
                          onClick: () => handleClearCustomRole(u),
                          disabled: clearingCustomRoleId === u.id,
                        }] : []),
                        { separator: true },
                        // V088 — Soft-disable: la acción correcta para sacar
                        // a alguien del CRM sin perder historial. Re-habilitar
                        // es simétrico (mismo botón, etiqueta inversa).
                        // V092 — Para usuarios activos agregamos 2 niveles:
                        //   - Bloquear inicio de sesión: freeze rápido (patrón estándar)
                        //   - Deshabilitar usuario: full removal con reasignación de leads
                        // Para deshabilitados, una sola opción: Re-habilitar.
                        ...(u.is_active === false
                          ? [{ icon: UserCog, label: 'Re-habilitar usuario', onClick: () => handleToggleActive(u) }]
                          : [
                              // V094 — login_blocked es independiente de is_active.
                              // El label refleja el estado actual para que el admin
                              // sepa si va a bloquear o desbloquear.
                              u.login_blocked
                                ? { icon: Lock, label: 'Desbloquear inicio de sesión', onClick: () => handleFreezeLogin(u) }
                                : { icon: Lock, label: 'Bloquear inicio de sesión (sigue visible en listas)', onClick: () => handleFreezeLogin(u) },
                              { icon: UserX, label: 'Deshabilitar usuario (con reasignar leads)', onClick: () => handleToggleActive(u), danger: true },
                            ]),
                        { icon: Trash2, label: 'Eliminar Usuario (definitivo)', onClick: () => handleDelete(u), danger: true, disabled: deletingId === u.id },
                      ]} />
                    ) : (
                      /* Usuario actual (admin): solo puede editar sus propios datos —
                         no puede auto-eliminarse ni cambiarse el rol a si mismo */
                      <ActionMenu items={[
                        { icon: Pencil, label: 'Editar mis datos', onClick: () => handleEditOpen(u) },
                      ]} />
                    )}
                  </td>
                </tr>
              ))}
              {filteredUsers.length === 0 && (
                <tr>
                  <td colSpan={3} className="px-5 py-12 text-center text-gray-400 text-sm">
                    {search ? 'No se encontraron miembros.' : 'No hay usuarios registrados.'}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>

      {/* Invitations section (pendientes) */}
      {pendingInvites.length > 0 && (
        <div className="border border-gray-200 rounded-xl overflow-hidden bg-white mt-5">
          <div className="px-5 py-3 border-b border-gray-100 bg-gray-50/50">
            <h3 className="font-medium text-gray-600 text-sm">Invitaciones pendientes</h3>
          </div>
          <table className="w-full text-sm">
            <tbody>
              {pendingInvites.map((inv) => (
                <tr key={inv.id} className="border-b border-gray-50 hover:bg-gray-50/60 transition-colors">
                  <td className="px-5 py-3">
                    <div className="flex items-center gap-3">
                      <div className="w-8 h-8 bg-amber-100 rounded-full flex items-center justify-center shrink-0">
                        <Clock size={14} className="text-amber-600" />
                      </div>
                      <div>
                        <p className="text-sm text-gray-700">{inv.email}</p>
                        <p className="text-xs text-gray-400">Invitado por {inv.invited_by}</p>
                      </div>
                    </div>
                  </td>
                  <td className="px-5 py-3">
                    <RoleBadge role={inv.role} />
                  </td>
                  <td className="px-3 py-3 text-center w-20">
                    <ActionMenu items={[
                      { icon: RefreshCw, label: 'Reenviar la invitación al correo electrónico', onClick: () => handleResendInvite(inv.email, inv.role) },
                      { icon: Copy, label: 'Copiar URL de invitación', onClick: () => copyToClipboard(buildInviteUrl(inv.token), 'URL de invitación copiada') },
                      { separator: true },
                      { icon: Trash2, label: 'Cancelar invitación', onClick: () => handleCancelInvite(inv), danger: true },
                    ]} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ===== Modal: Editar usuario ===== */}
      {editUser && (
        <Dialog open={!!editUser} onClose={() => setEditUser(null)}>
          <DialogHeader onClose={() => setEditUser(null)}>Editar usuario</DialogHeader>
          <DialogContent>
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-1.5">
                  <Label className="text-sm font-medium text-gray-700">Nombre</Label>
                  <Input
                    value={editForm.first_name}
                    onChange={e => setEditForm(f => ({ ...f, first_name: e.target.value }))}
                    placeholder="Nombre"
                    className="h-10"
                    autoFocus
                  />
                </div>
                <div className="space-y-1.5">
                  <Label className="text-sm font-medium text-gray-700">Apellido</Label>
                  <Input
                    value={editForm.last_name}
                    onChange={e => setEditForm(f => ({ ...f, last_name: e.target.value }))}
                    placeholder="Apellido"
                    className="h-10"
                  />
                </div>
              </div>
              {/* V5.63 — feedback inline de validacion sintactica.
                  V087 — feedback inline de duplicado (consulta al backend
                  con debounce; ver useEffect arriba). */}
              {(() => {
                const emailVal = editForm.email ?? editUser.email
                const emailErr = (emailVal ?? '').trim() ? emailValidationMsg(emailVal) : null
                const isTaken = !emailErr && emailAvailability && emailAvailability.available === false
                const isFree  = !emailErr && emailAvailability && emailAvailability.available === true
                const showErrorRing = !!emailErr || isTaken
                return (
                  <div className="space-y-1.5">
                    <Label className="text-sm font-medium text-gray-700">Email</Label>
                    <Input
                      type="email"
                      value={emailVal}
                      onChange={e => setEditForm(f => ({ ...f, email: e.target.value }))}
                      placeholder="correo@ejemplo.com"
                      className={`h-10 ${showErrorRing ? 'border-red-300 focus-visible:ring-red-400' : ''}`}
                      aria-invalid={showErrorRing}
                      autoComplete="off"
                      spellCheck={false}
                    />
                    {emailErr && <p className="text-xs text-red-600">{emailErr}</p>}
                    {!emailErr && emailChecking && (
                      <p className="text-xs text-gray-400">Verificando disponibilidad…</p>
                    )}
                    {isTaken && (
                      <p className="text-xs text-red-600">
                        Ese correo ya está usado por{' '}
                        <strong>{emailAvailability.owner_name || emailAvailability.owner_email}</strong>.
                        Elige uno distinto.
                      </p>
                    )}
                    {isFree && (
                      <p className="text-xs text-emerald-600">Disponible.</p>
                    )}
                  </div>
                )
              })()}
              {(() => {
                const phoneErr = phoneValidationMsg(editForm.telefono, editUser?.telefono || '')
                return (
                  <div className="space-y-1.5">
                    <Label className="text-sm font-medium text-gray-700">Celular del asesor</Label>
                    <Input
                      type="tel"
                      value={editForm.telefono}
                      onChange={e => setEditForm(f => ({ ...f, telefono: e.target.value }))}
                      placeholder="+51 999 999 999"
                      className={`h-10 ${phoneErr ? 'border-red-300 focus-visible:ring-red-400' : ''}`}
                      aria-invalid={!!phoneErr}
                      inputMode="tel"
                      autoComplete="off"
                    />
                    {phoneErr ? (
                      <p className="text-xs text-red-600">{phoneErr}</p>
                    ) : (
                      <p className="text-xs text-gray-500">Formato internacional: código país + 9 dígitos (ej: +51 999 888 777).</p>
                    )}
                  </div>
                )
              })()}
              <div className="space-y-1.5">
                <Label className="text-sm font-medium text-gray-700">Línea WhatsApp por defecto</Label>
                <select
                  value={editForm.default_wa_number_id ?? 0}
                  onChange={e => setEditForm(f => ({ ...f, default_wa_number_id: Number(e.target.value) }))}
                  className="w-full h-10 px-3 rounded-md border border-gray-300 bg-white text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value={0}>— Sin línea asignada (usa la global) —</option>
                  {waNumbers.map(n => (
                    <option key={n.id} value={n.id}>
                      {n.display_name}{n.display_phone ? ` · ${n.display_phone}` : ''}
                    </option>
                  ))}
                </select>
                <p className="text-xs text-gray-500">
                  Línea desde la que este usuario enviará por defecto cuando no haya conversación previa.
                </p>
              </div>
              {editError && (
                <p className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{editError}</p>
              )}
              <div className="flex gap-3 pt-1">
                <Button
                  onClick={handleEditSave}
                  // V087 — bloqueamos submit si el pre-check del backend
                  // confirmo duplicado. Asi evitamos el round-trip y le
                  // damos feedback inmediato al admin.
                  disabled={editLoading || (emailAvailability && emailAvailability.available === false)}
                  className="flex-1"
                >
                  {editLoading ? 'Guardando...' : 'Guardar cambios'}
                </Button>
                <Button variant="outline" onClick={() => setEditUser(null)}>Cancelar</Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      )}

      {/* ===== Modal: Invitar por Email ===== */}
      <Dialog open={showInviteModal} onClose={() => setShowInviteModal(false)}>
        <DialogHeader onClose={() => setShowInviteModal(false)}>
          Invitar a un usuario
        </DialogHeader>
        <DialogContent>
          {!inviteSuccess ? (
            <form onSubmit={handleInvite} className="space-y-5">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label className="text-sm font-medium text-gray-700">Correo electrónico</Label>
                  <Input
                    type="email"
                    // value defensivo: si por algún motivo react-state arranca con
                    // null/undefined, `|| ''` evita que el input muestre "null".
                    value={inviteEmail || ''}
                    onChange={(e) => setInviteEmail(e.target.value ?? '')}
                    disabled={inviteLoading}
                    autoFocus
                    autoComplete="off"
                    placeholder="correo@empresa.com"
                    className="h-10"
                  />
                </div>
                <div className="space-y-2">
                  <Label className="text-sm font-medium text-gray-700">Rol de usuario</Label>
                  <select
                    // ADR-0011 — Selector único que combina rol legacy + custom:
                    //   - opciones legacy (admin/supervisor/asesor) NO mandan role_id
                    //   - opciones custom mandan role_id Y role legacy="asesor" (base)
                    // El value del select es "legacy:asesor" o "custom:<id>" para
                    // distinguir las opciones unívocamente.
                    value={inviteRoleId ? `custom:${inviteRoleId}` : `legacy:${inviteRole}`}
                    onChange={(e) => {
                      const v = e.target.value
                      if (v.startsWith('custom:')) {
                        setInviteRoleId(parseInt(v.slice(7), 10))
                        setInviteRole('asesor')
                      } else {
                        setInviteRoleId(null)
                        setInviteRole(v.slice(7))
                      }
                    }}
                    disabled={inviteLoading}
                    className="w-full h-10 rounded-md border border-gray-200 bg-white px-3 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                  >
                    {/* Roles built-in (siempre disponibles) */}
                    <optgroup label="Roles del sistema">
                      {LEGACY_ROLES.map((r) => (
                        <option key={r.value} value={`legacy:${r.value}`}>{r.label}</option>
                      ))}
                    </optgroup>
                    {/* Roles custom configurados en /configuracion/roles */}
                    {availableRoles.filter((r) => !r.is_builtin).length > 0 && (
                      <optgroup label="Roles personalizados">
                        {availableRoles.filter((r) => !r.is_builtin).map((r) => (
                          <option key={r.id} value={`custom:${r.id}`}>
                            {r.name}{r.is_external ? ' (externo)' : ''}
                          </option>
                        ))}
                      </optgroup>
                    )}
                  </select>
                  {inviteRoleId && availableRoles.find((r) => r.id === inviteRoleId)?.is_external && (
                    <p className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded-md p-2">
                      ⚠️ Este es un rol externo (proveedor). El usuario invitado va a necesitar tener un proveedor (api_client_id) asignado para poder iniciar sesión.
                    </p>
                  )}
                </div>
              </div>

              {inviteError && <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-md px-3 py-2">{inviteError}</div>}

              <div className="flex justify-end">
                <Button type="submit" disabled={inviteLoading} className="gap-2 px-6">
                  <Send size={14} />
                  {inviteLoading ? 'Enviando...' : 'Invitar'}
                </Button>
              </div>
            </form>
          ) : (
            <div className="space-y-4">
              {inviteSuccess.email_sent ? (
                <div className="bg-green-50 border border-green-200 rounded-lg p-4 text-center">
                  <Check size={20} className="text-green-600 mx-auto mb-2" />
                  <p className="text-sm text-green-800 font-medium">{inviteSuccess.message}</p>
                </div>
              ) : (
                <>
                  <div className="flex items-center gap-2 text-sm text-gray-500">
                    <Link2 size={14} />
                    Copiar URL de invitación
                  </div>
                  <div className="bg-green-50 border border-green-200 rounded-lg p-3 flex items-center gap-3">
                    <Check size={18} className="text-green-600 shrink-0" />
                    <code className="text-xs text-green-800 flex-1 break-all leading-relaxed">{inviteSuccess.invite_url}</code>
                    <button
                      onClick={() => copyToClipboard(inviteSuccess.invite_url, 'URL copiada al portapapeles')}
                      className="p-2 rounded-md hover:bg-green-100 text-green-600 shrink-0 transition-colors"
                    >
                      {copiedUrl ? <Check size={16} /> : <Copy size={16} />}
                    </button>
                  </div>
                  <p className="text-xs text-gray-500">
                    Copia el link de invitación y envíalo a <strong>{inviteSuccess.invite_email || 'el usuario'}</strong>.
                  </p>
                </>
              )}

              <div className="flex justify-end pt-1">
                <Button type="button" variant="outline" size="sm" className="gap-1.5" onClick={() => resetInviteForm()}>
                  <Send size={14} />
                  Invitar más
                </Button>
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* ===== Modal: Crear Usuario ===== */}
      <Dialog open={showCreateModal} onClose={() => setShowCreateModal(false)}>
        <DialogHeader onClose={() => setShowCreateModal(false)}>
          Crear usuario
        </DialogHeader>
        <DialogContent>
          <form onSubmit={handleCreate} className="space-y-4">
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label className="text-sm font-medium text-gray-700">Nombre</Label>
                <Input placeholder="Nombre" value={form.first_name} onChange={(e) => setForm({ ...form, first_name: e.target.value })} disabled={formLoading} autoFocus className="h-10" />
              </div>
              <div className="space-y-2">
                <Label className="text-sm font-medium text-gray-700">Apellido</Label>
                <Input placeholder="Apellido" value={form.last_name} onChange={(e) => setForm({ ...form, last_name: e.target.value })} disabled={formLoading} className="h-10" />
              </div>
              <div className="space-y-2 sm:col-span-2">
                <Label className="text-sm font-medium text-gray-700">Correo electrónico</Label>
                <Input type="email" placeholder="correo@empresa.com" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} disabled={formLoading} autoComplete="off" className="h-10" />
              </div>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label className="text-sm font-medium text-gray-700">Contraseña</Label>
                <Input type="password" placeholder="Mínimo 6 caracteres" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} disabled={formLoading} autoComplete="new-password" className="h-10" />
              </div>
              <div className="space-y-2">
                <Label className="text-sm font-medium text-gray-700">Rol de usuario</Label>
                <select
                  // ADR-0011 — mismo selector unificado legacy + custom que en Invitar.
                  value={form.role_id ? `custom:${form.role_id}` : `legacy:${form.role}`}
                  onChange={(e) => {
                    const v = e.target.value
                    if (v.startsWith('custom:')) {
                      setForm({ ...form, role_id: parseInt(v.slice(7), 10), role: 'asesor' })
                    } else {
                      setForm({ ...form, role_id: null, role: v.slice(7) })
                    }
                  }}
                  disabled={formLoading}
                  className="w-full h-10 rounded-md border border-gray-200 bg-white px-3 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent"
                >
                  <optgroup label="Roles del sistema">
                    {LEGACY_ROLES.map((r) => (
                      <option key={r.value} value={`legacy:${r.value}`}>{r.label}</option>
                    ))}
                  </optgroup>
                  {availableRoles.filter((r) => !r.is_builtin).length > 0 && (
                    <optgroup label="Roles personalizados">
                      {availableRoles.filter((r) => !r.is_builtin).map((r) => (
                        <option key={r.id} value={`custom:${r.id}`}>
                          {r.name}{r.is_external ? ' (externo)' : ''}
                        </option>
                      ))}
                    </optgroup>
                  )}
                </select>
              </div>
            </div>
            <div className="space-y-2">
              <Label className="text-sm font-medium text-gray-700">
                Teléfono <span className="text-gray-400 font-normal">(para recordatorios WhatsApp)</span>
              </Label>
              <Input
                type="tel"
                placeholder="51999888777"
                value={form.telefono}
                onChange={(e) => setForm({ ...form, telefono: e.target.value.replace(/\D/g, '').slice(0, 15) })}
                disabled={formLoading}
                className="h-10"
              />
            </div>
            {formError && <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-md px-3 py-2">{formError}</div>}
            <div className="flex justify-end pt-1">
              <Button type="submit" disabled={formLoading} className="gap-2 px-6">
                <Plus size={14} />
                {formLoading ? 'Creando...' : 'Crear Usuario'}
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>

      {/* ===== Modal: Confirmar eliminación ===== */}
      <ConfirmDialog
        open={!!confirmDeleteUser}
        title="Eliminar usuario"
        message={confirmDeleteUser ? `¿Estás seguro de eliminar a ${[confirmDeleteUser.first_name, confirmDeleteUser.last_name].filter(Boolean).join(' ') || confirmDeleteUser.email} (${confirmDeleteUser.email})? Esta acción no se puede deshacer. Los leads asignados a este usuario quedarán sin asesor.` : ''}
        confirmLabel="Sí, eliminar"
        onConfirm={handleConfirmDelete}
        onCancel={() => setConfirmDeleteUser(null)}
      />

      {/* V070.81 — Modal: Confirmar cambio de rol */}
      <ConfirmDialog
        open={!!confirmRoleChange}
        variant="warning"
        title="Cambiar rol del usuario"
        confirmLabel="Sí, cambiar"
        cancelLabel="Cancelar"
        message={confirmRoleChange
          ? `Vas a cambiar el rol de "${confirmRoleChange.user.nombre_completo || confirmRoleChange.user.email}" a ${confirmRoleChange.roleLabel}. El usuario va a ver inmediatamente los permisos del nuevo rol al refrescar.`
          : ''}
        onConfirm={handleRoleChangeConfirm}
        onCancel={() => setConfirmRoleChange(null)}
      />

      {/* V070.81 — Modal: Confirmar cancelar invitacion */}
      <ConfirmDialog
        open={!!confirmCancelInvite}
        variant="danger"
        title="Cancelar invitación"
        confirmLabel="Sí, cancelar invitación"
        cancelLabel="Volver"
        message={confirmCancelInvite
          ? `Vas a cancelar la invitación pendiente a "${confirmCancelInvite.email}". El link de invitación dejará de funcionar. Si el usuario aún la necesita, deberás enviarla de nuevo.`
          : ''}
        onConfirm={handleCancelInviteConfirm}
        onCancel={() => setConfirmCancelInvite(null)}
      />

      {/* V090 — Modal: Reasignar leads antes de deshabilitar usuario.
          Patrón estándar de la industria: cuando un usuario sale de la
          empresa, sus leads no pueden quedar huérfanos. El admin elige
          qué hacer en una sola operación atómica. */}
      {reassignModal && (
        <Dialog open={!!reassignModal} onClose={() => !reassigning && setReassignModal(null)}>
          <DialogHeader onClose={() => !reassigning && setReassignModal(null)}>
            Reasignar leads antes de deshabilitar
          </DialogHeader>
          <DialogContent>
            <div className="space-y-4">
              <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 flex items-start gap-3">
                <div className="w-8 h-8 rounded-full bg-amber-100 flex items-center justify-center shrink-0">
                  <UserX size={15} className="text-amber-700" />
                </div>
                <div className="text-sm text-amber-900 leading-relaxed">
                  <strong>{reassignModal.user.nombre_completo || reassignModal.user.email}</strong> tiene{' '}
                  <strong>{reassignModal.leadsCount} lead{reassignModal.leadsCount === 1 ? '' : 's'} activo{reassignModal.leadsCount === 1 ? '' : 's'}</strong> asignado{reassignModal.leadsCount === 1 ? '' : 's'}.
                  Elige qué hacer con ellos antes de deshabilitar la cuenta.
                </div>
              </div>

              {/* V092 — Error inline (reemplaza alert nativo) */}
              {reassignModal.error && (
                <div className="bg-rose-50 border border-rose-200 text-rose-800 rounded-lg p-3 text-sm flex items-start gap-2">
                  <X size={16} className="text-rose-600 shrink-0 mt-0.5" />
                  <div className="flex-1">{reassignModal.error}</div>
                </div>
              )}

              <div className="space-y-2">
                {/* V092 — Opción 1 solo aplica si el user es asesor (tiene
                    supervisor de equipo arriba). Para supervisores o admin,
                    la opción no tiene sentido — la deshabilitamos con
                    explicación. */}
                {(() => {
                  const isAsesor = reassignModal.user.role === 'asesor'
                  const disabled = !isAsesor
                  return (
                    <label className={`flex items-start gap-3 p-3.5 rounded-xl border-2 transition-all ${
                      disabled
                        ? 'border-gray-200 bg-gray-50 opacity-60 cursor-not-allowed'
                        : reassignModal.mode === 'supervisor'
                        ? 'border-emerald-400 bg-emerald-50/40 cursor-pointer'
                        : 'border-gray-200 hover:border-gray-300 cursor-pointer'
                    }`}>
                      <input
                        type="radio"
                        name="reassign-mode"
                        value="supervisor"
                        checked={reassignModal.mode === 'supervisor'}
                        onChange={() => !disabled && setReassignModal({ ...reassignModal, error: null, mode: 'supervisor' })}
                        disabled={disabled}
                        className="mt-0.5 accent-emerald-600"
                      />
                      <div className="flex-1">
                        <div className="text-sm font-semibold text-gray-900 flex items-center gap-1.5 flex-wrap">
                          Devolver a la cola del supervisor del equipo
                          {!disabled && (
                            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-700 border border-emerald-200 uppercase tracking-wide">
                              Recomendado
                            </span>
                          )}
                          {disabled && (
                            <span className="text-[10px] font-bold px-1.5 py-0.5 rounded bg-gray-200 text-gray-600 border border-gray-300 uppercase tracking-wide">
                              No aplica
                            </span>
                          )}
                        </div>
                        <div className="text-xs text-gray-500 mt-1 leading-relaxed">
                          {disabled
                            ? `Esta opción es solo para asesores. ${reassignModal.user.nombre_completo || reassignModal.user.email} es ${reassignModal.user.role}, no tiene supervisor de equipo arriba.`
                            : 'Los leads quedan sin asesor, pero asignados al supervisor del equipo. Aparecen en su tab "Sin asignar" y los reparte cuando puede.'}
                        </div>
                      </div>
                    </label>
                  )
                })()}

                {/* Opción 2: reasignar a otro asesor específico */}
                <label className={`flex items-start gap-3 p-3.5 rounded-xl border-2 cursor-pointer transition-all ${reassignModal.mode === 'asesor' ? 'border-indigo-400 bg-indigo-50/40' : 'border-gray-200 hover:border-gray-300'}`}>
                  <input
                    type="radio"
                    name="reassign-mode"
                    value="asesor"
                    checked={reassignModal.mode === 'asesor'}
                    onChange={() => setReassignModal({ ...reassignModal, error: null, mode: 'asesor' })}
                    className="mt-0.5 accent-indigo-600"
                  />
                  <div className="flex-1">
                    <div className="text-sm font-semibold text-gray-900">Reasignar todos a otro asesor</div>
                    <div className="text-xs text-gray-500 mt-1 leading-relaxed">
                      Bulk reassign a un asesor específico. Útil si ya sabés quién hereda la cartera.
                    </div>
                    {reassignModal.mode === 'asesor' && (
                      <select
                        value={reassignModal.targetUserId}
                        onChange={e => setReassignModal({ ...reassignModal, targetUserId: e.target.value })}
                        disabled={reassigning}
                        className="mt-2 w-full h-9 px-3 rounded-md border border-gray-300 bg-white text-sm text-gray-900 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                      >
                        <option value="">— Selecciona asesor destino —</option>
                        {users
                          .filter(t => t.id !== reassignModal.user.id && t.role === 'asesor' && t.is_active !== false)
                          .map(t => (
                            <option key={t.id} value={t.id}>
                              {[t.first_name, t.last_name].filter(Boolean).join(' ') || t.email}
                            </option>
                          ))}
                      </select>
                    )}
                  </div>
                </label>

                {/* Opción 3: dejar sin asesor (cola global "Sin asignar") */}
                <label className={`flex items-start gap-3 p-3.5 rounded-xl border-2 cursor-pointer transition-all ${reassignModal.mode === 'unassign' ? 'border-slate-400 bg-slate-50' : 'border-gray-200 hover:border-gray-300'}`}>
                  <input
                    type="radio"
                    name="reassign-mode"
                    value="unassign"
                    checked={reassignModal.mode === 'unassign'}
                    onChange={() => setReassignModal({ ...reassignModal, error: null, mode: 'unassign' })}
                    className="mt-0.5 accent-slate-600"
                  />
                  <div className="flex-1">
                    <div className="text-sm font-semibold text-gray-900">Dejar sin asesor</div>
                    <div className="text-xs text-gray-500 mt-1 leading-relaxed">
                      Los leads quedan en la cola global "Sin asignar". Útil si vas a revisarlos vos antes de repartir.
                    </div>
                  </div>
                </label>

                {/* Opción 4: mantener (huérfanos) — con warning */}
                <label className={`flex items-start gap-3 p-3.5 rounded-xl border-2 cursor-pointer transition-all ${reassignModal.mode === 'keep' ? 'border-rose-300 bg-rose-50/30' : 'border-gray-200 hover:border-gray-300'}`}>
                  <input
                    type="radio"
                    name="reassign-mode"
                    value="keep"
                    checked={reassignModal.mode === 'keep'}
                    onChange={() => setReassignModal({ ...reassignModal, error: null, mode: 'keep' })}
                    className="mt-0.5 accent-rose-600"
                  />
                  <div className="flex-1">
                    <div className="text-sm font-semibold text-gray-900">
                      Mantener asignados a {reassignModal.user.nombre_completo || reassignModal.user.email}
                      <span className="ml-1.5 text-[10px] font-bold px-1.5 py-0.5 rounded bg-rose-100 text-rose-700 border border-rose-200 uppercase tracking-wide">
                        No recomendado
                      </span>
                    </div>
                    <div className="text-xs text-gray-500 mt-1 leading-relaxed">
                      Los leads no se mueven. Como el usuario quedará deshabilitado, los leads se vuelven huérfanos
                      (asignados a alguien que no entra al CRM).
                    </div>
                  </div>
                </label>
              </div>

              <div className="flex justify-end gap-2 pt-2">
                <Button variant="outline" onClick={() => setReassignModal(null)} disabled={reassigning}>
                  Cancelar
                </Button>
                <Button
                  onClick={handleReassignAndDisable}
                  disabled={reassigning || (reassignModal.mode === 'asesor' && !reassignModal.targetUserId)}
                  className="bg-amber-600 hover:bg-amber-700 text-white border-amber-600"
                >
                  {reassigning ? 'Aplicando…' : 'Aplicar y deshabilitar'}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      )}

      {/* V092 — Modal: Confirmar freeze. Bloquea login + cierra sesiones SIN
          reasignar leads. Reversible.
          V094 — Ahora es dinámico: bloquear vs desbloquear según estado actual.
          Diferencia clave con "Deshabilitar usuario": el usuario SIGUE visible
          en todas las listas operacionales (rotación, asignación, equipos). */}
      <ConfirmDialog
        open={!!confirmFreeze}
        variant={confirmFreeze?.login_blocked ? 'warning' : 'danger'}
        title={confirmFreeze?.login_blocked
          ? 'Desbloquear inicio de sesión'
          : 'Bloquear inicio de sesión'}
        confirmLabel={freezing
          ? 'Aplicando…'
          : confirmFreeze?.login_blocked ? 'Sí, desbloquear' : 'Sí, bloquear acceso'}
        cancelLabel="Cancelar"
        message={confirmFreeze
          ? confirmFreeze.login_blocked
            ? `Vas a desbloquear el inicio de sesión de ${[confirmFreeze.first_name, confirmFreeze.last_name].filter(Boolean).join(' ') || confirmFreeze.email}. Va a poder volver a entrar al CRM con sus credenciales actuales.`
            : `Vas a bloquear el inicio de sesión de ${[confirmFreeze.first_name, confirmFreeze.last_name].filter(Boolean).join(' ') || confirmFreeze.email}. Sus sesiones activas se cerrarán al instante. El usuario SIGUE visible en todas las listas (rotación, asignación, equipos) — solo no podrá entrar al CRM. Sus leads quedan asignados a él. Reversible desde el mismo menú.`
          : ''}
        onConfirm={handleFreezeLoginConfirm}
        onCancel={() => setConfirmFreeze(null)}
      />

      {/* V088 — Modal: Confirmar deshabilitar / re-habilitar usuario.
          Reemplaza el patrón previo donde el admin terminaba usando
          "Eliminar Usuario" (destructivo) o "Asignar rol Sin Acceso"
          (no efectivo) para sacar a alguien del CRM. */}
      <ConfirmDialog
        open={!!confirmToggleActive}
        variant={confirmToggleActive?.is_active === false ? 'warning' : 'danger'}
        title={confirmToggleActive?.is_active === false ? 'Re-habilitar usuario' : 'Deshabilitar usuario'}
        confirmLabel={togglingActive
          ? 'Aplicando…'
          : confirmToggleActive?.is_active === false ? 'Sí, re-habilitar' : 'Sí, deshabilitar'}
        cancelLabel="Cancelar"
        message={confirmToggleActive
          ? confirmToggleActive.is_active === false
            ? `Vas a re-habilitar a ${[confirmToggleActive.first_name, confirmToggleActive.last_name].filter(Boolean).join(' ') || confirmToggleActive.email}. Va a poder iniciar sesión de nuevo y aparecerá en las listas de su rol (${confirmToggleActive.role}).`
            : `Vas a deshabilitar a ${[confirmToggleActive.first_name, confirmToggleActive.last_name].filter(Boolean).join(' ') || confirmToggleActive.email}. Efectos: no podrá iniciar sesión, desaparece de todas las listas de supervisores y equipos, y sus sesiones activas se cierran. Sus leads y su historial se preservan intactos. Reversible con "Re-habilitar usuario".`
          : ''}
        onConfirm={handleToggleActiveConfirm}
        onCancel={() => setConfirmToggleActive(null)}
      />

      {/* V087 — Modal: Confirmar envío de correo de restablecimiento */}
      <ConfirmDialog
        open={!!confirmSendReset}
        variant="warning"
        title="Enviar correo de restablecimiento"
        confirmLabel={sendingReset ? 'Enviando…' : 'Sí, enviar correo'}
        cancelLabel="Cancelar"
        message={confirmSendReset
          ? `Le enviarás un correo a ${[confirmSendReset.first_name, confirmSendReset.last_name].filter(Boolean).join(' ') || confirmSendReset.email} (${confirmSendReset.email}) con un enlace para que elija una nueva contraseña. El enlace es de un solo uso y expira en 24 horas. La acción quedará registrada en el log de auditoría.`
          : ''}
        onConfirm={handleSendResetEmailConfirm}
        onCancel={() => setConfirmSendReset(null)}
      />

      {/* ===== Modal: Asignar rol personalizado (ADR-0011) ===== */}
      {customRoleModal && (
        <Dialog open={!!customRoleModal} onClose={() => setCustomRoleModal(null)}>
          <DialogHeader onClose={() => setCustomRoleModal(null)}>
            Asignar rol personalizado
          </DialogHeader>
          <DialogContent>
            <div className="space-y-4">
              <p className="text-sm text-slate-600">
                Usuario: <strong>{customRoleModal.user.nombre_completo || customRoleModal.user.email}</strong>
              </p>

              <div className="space-y-2">
                <Label className="text-sm font-medium text-gray-700">Rol personalizado</Label>
                <select
                  value={customRoleModal.selectedRoleId ?? ''}
                  onChange={(e) => setCustomRoleModal({
                    ...customRoleModal,
                    selectedRoleId: e.target.value ? parseInt(e.target.value, 10) : null,
                  })}
                  disabled={assigningRole}
                  className="w-full h-10 rounded-md border border-gray-200 bg-white px-3 text-sm text-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  <option value="">— Sin rol personalizado (usa el rol legacy) —</option>
                  {availableRoles.filter((r) => !r.is_builtin).map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.name}{r.is_external ? ' (externo)' : ''}{r.description ? ` — ${r.description}` : ''}
                    </option>
                  ))}
                </select>
              </div>

              <div className="bg-blue-50 border border-blue-200 rounded-lg p-3 text-xs text-blue-800 space-y-1">
                <p className="font-medium">¿Cómo funciona?</p>
                <ul className="list-disc list-inside space-y-0.5">
                  <li>El rol legacy (<strong>{customRoleModal.user.role}</strong>) NO cambia — sigue usándose para filtrar leads y asignaciones.</li>
                  <li>El rol personalizado define qué <strong>módulos</strong> del CRM puede ver el usuario.</li>
                  <li>Al elegir &quot;Sin rol personalizado&quot;, el usuario vuelve al comportamiento base de su rol legacy.</li>
                  <li>El cambio se ve en el próximo inicio de sesión del usuario.</li>
                </ul>
              </div>

              <div className="flex justify-end gap-2 pt-1">
                <Button variant="outline" onClick={() => setCustomRoleModal(null)} disabled={assigningRole}>
                  Cancelar
                </Button>
                <Button onClick={handleAssignCustomRole} disabled={assigningRole}>
                  {assigningRole ? 'Guardando…' : 'Aplicar'}
                </Button>
              </div>
            </div>
          </DialogContent>
        </Dialog>
      )}
    </div>
  )
}
