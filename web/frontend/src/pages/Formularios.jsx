/**
 * Formularios.jsx — Gestión de formularios públicos de captura de leads.
 *
 * Solo accesible por admin y supervisor (enforced en App.jsx con SupervisorRoute).
 *
 * Funcionalidades:
 *  - Listar forms propios (supervisor) / todos (admin)
 *  - Crear form con wizard simple
 *  - Ver detalle: QR + URL pública + contador de leads
 *  - Archivar (soft delete)
 *  - Copiar link al portapapeles
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  Plus, ExternalLink, Copy, QrCode, Archive, RefreshCw, FileText, CheckCircle2,
  Sparkles, Settings2, ListChecks, MessageSquare, AlertTriangle, Users, Calendar,
  Pencil, Trash2, UserCheck,
} from 'lucide-react'
import api from '@/lib/api'
import useAuthStore from '@/store/authStore'
import { hasPermission } from '@/lib/permissions'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Dialog } from '@/components/ui/dialog'
import LoadingSpinner from '@/components/shared/LoadingSpinner'
import EmptyState from '@/components/shared/EmptyState'

// Campos que el creador puede activar en el form — corresponden a las
// columnas aceptadas en el backend (ALLOWED_LEAD_FIELDS).
const FIELD_CATALOG = [
  { key: 'nombres',       label: 'Nombres',        default: true  },
  { key: 'apellidos',     label: 'Apellidos',      default: true  },
  { key: 'telefono',      label: 'Teléfono',       default: true  },
  { key: 'email',         label: 'Correo',         default: false },
  { key: 'dni',           label: 'DNI',            default: false },
  { key: 'observaciones', label: 'Comentarios',    default: false },
]

function formatApiError(err, fallback = 'Error inesperado.') {
  const detail = err?.response?.data?.detail
  if (detail == null) return err?.message || fallback
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map(d => {
      if (typeof d === 'string') return d
      const msg = d?.msg || d?.message || JSON.stringify(d)
      return msg
    }).join(' · ')
  }
  if (typeof detail === 'object') return detail.msg || detail.message || JSON.stringify(detail)
  return String(detail)
}

function buildPublicUrl(slug) {
  if (typeof window === 'undefined') return `/f/${slug}`
  return `${window.location.origin}/f/${slug}`
}

export default function Formularios() {
  const { user } = useAuthStore()
  // Permite que rol custom con `formularios.manage` administre formularios sin
  // ser admin legacy. Mantiene admin legacy por compat (hasPermission lo cubre).
  const isAdmin = hasPermission(user, 'formularios.manage')

  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [includeArchived, setIncludeArchived] = useState(false)

  const [fuentes, setFuentes] = useState([])
  const [campanas, setCampanas] = useState([])
  const [assignees, setAssignees] = useState([])
  const [showCreate, setShowCreate] = useState(false)
  const [showDetail, setShowDetail] = useState(null)  // form object | null

  // Estado del diálogo de confirmación de archivo.
  // `archiveTarget` es el form a archivar; null cierra el modal.
  const [archiveTarget, setArchiveTarget] = useState(null)
  const [archiving, setArchiving] = useState(false)
  const [archiveError, setArchiveError] = useState('')

  // Edición
  const [editTarget, setEditTarget] = useState(null)  // form a editar

  // Borrado permanente (hard delete) — irreversible
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [deleteError, setDeleteError] = useState('')

  const loadForms = useCallback(async (silent = false) => {
    if (!silent) setLoading(true)
    try {
      const res = await api.get('/api/public-forms', {
        params: includeArchived ? { include_archived: true } : undefined,
      })
      setItems(res.data?.items || [])
      setError(null)
    } catch (err) {
      if (!silent) setError(formatApiError(err, 'No se pudieron cargar los formularios.'))
    } finally {
      if (!silent) setLoading(false)
    }
  }, [includeArchived])

  const loadFuentes = useCallback(async () => {
    try {
      const res = await api.get('/api/fuentes')
      setFuentes(res.data || [])
    } catch {
      setFuentes([])
    }
  }, [])

  // Catalogo de campañas para el dropdown del form (UAT v3.1: el campo era
  // texto libre y eso ensuciaba el catalogo con variantes "fb-mayo" /
  // "FB Mayo 2026" / "FB_mayo26" entrando como tres campañas distintas).
  const loadCampanas = useCallback(async () => {
    try {
      const res = await api.get('/api/campanas?activos=true')
      setCampanas(res.data || [])
    } catch {
      setCampanas([])
    }
  }, [])

  const loadAssignees = useCallback(async () => {
    try {
      const res = await api.get('/api/public-forms/assignees')
      setAssignees(res.data?.items || [])
    } catch {
      setAssignees([])
    }
  }, [])

  useEffect(() => {
    loadForms()
    loadFuentes()
    loadCampanas()
    loadAssignees()
  }, [loadForms, loadFuentes, loadCampanas, loadAssignees])

  // Auto-refresh silencioso cada 30s — el contador de leads capturados se
  // actualiza solo sin que el usuario tenga que clickear "Actualizar". Pausa
  // cuando la pestaña esta en background (visibilitychange) para no gastar
  // requests innecesarios. Skip si hay un dialog abierto (no interrumpir UX).
  useEffect(() => {
    let cancelled = false
    const tick = () => {
      if (cancelled) return
      if (document.hidden) return
      // No refrescar mientras el usuario edita/borra — evita race con dialogs
      if (showCreate || archiveTarget || deleteTarget || editTarget) return
      loadForms(true)
    }
    const intervalId = setInterval(tick, 30000)
    return () => { cancelled = true; clearInterval(intervalId) }
  }, [loadForms, showCreate, archiveTarget, deleteTarget, editTarget])

  const requestArchive = (form) => {
    setArchiveError('')
    setArchiveTarget(form)
  }

  const confirmArchive = async () => {
    if (!archiveTarget) return
    setArchiving(true)
    setArchiveError('')
    try {
      await api.delete(`/api/public-forms/${archiveTarget.id}`)
      const archivedId = archiveTarget.id
      setArchiveTarget(null)
      await loadForms()
      if (showDetail?.id === archivedId) setShowDetail(null)
    } catch (err) {
      setArchiveError(formatApiError(err, 'No se pudo archivar.'))
    } finally {
      setArchiving(false)
    }
  }

  const handleRestore = async (form) => {
    try {
      await api.patch(`/api/public-forms/${form.id}`, { activo: true })
      await loadForms()
      if (showDetail?.id === form.id) {
        setShowDetail({ ...showDetail, activo: true })
      }
    } catch (err) {
      setError(formatApiError(err, 'No se pudo reactivar el formulario.'))
    }
  }

  const requestDelete = (form) => {
    setDeleteError('')
    setDeleteTarget(form)
  }

  const confirmDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    setDeleteError('')
    try {
      await api.delete(`/api/public-forms/${deleteTarget.id}/permanent`)
      const deletedId = deleteTarget.id
      setDeleteTarget(null)
      await loadForms()
      if (showDetail?.id === deletedId) setShowDetail(null)
    } catch (err) {
      setDeleteError(formatApiError(err, 'No se pudo borrar el formulario.'))
    } finally {
      setDeleting(false)
    }
  }

  const activeCount = items.filter(f => f.activo).length
  const archivedCount = items.filter(f => !f.activo).length

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-semibold text-slate-800">Formularios públicos</h1>
          <p className="text-sm text-slate-500">
            Crea links compartibles para capturar leads en eventos y campañas.
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" onClick={loadForms} disabled={loading}>
            <RefreshCw size={16} className={loading ? 'animate-spin' : ''} />
            <span className="ml-2">Actualizar</span>
          </Button>
          <Button
            onClick={() => setShowCreate(true)}
            style={{ backgroundColor: 'var(--brand-primary)' }}
          >
            <Plus size={16} />
            <span className="ml-2">Nuevo formulario</span>
          </Button>
        </div>
      </div>

      {/* Toolbar: filtros + contadores */}
      <div className="flex items-center justify-between gap-3 flex-wrap border-b border-slate-200 pb-3">
        <div className="flex gap-1.5">
          <FilterTab
            active={!includeArchived}
            onClick={() => setIncludeArchived(false)}
            label="Activos"
            count={includeArchived ? activeCount : items.length}
          />
          <FilterTab
            active={includeArchived}
            onClick={() => setIncludeArchived(true)}
            label="Todos"
            count={includeArchived ? items.length : undefined}
            hint="incluye archivados"
          />
        </div>
        {includeArchived && archivedCount > 0 && (
          <span className="text-xs text-slate-500">
            {archivedCount} archivado{archivedCount !== 1 ? 's' : ''} — puedes reactivarlos
          </span>
        )}
      </div>

      {error && (
        <div className="rounded-md bg-rose-50 border border-rose-200 text-rose-700 text-sm p-3">
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-16"><LoadingSpinner /></div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={FileText}
          title="Sin formularios todavía"
          description="Crea tu primer formulario público para capturar leads desde eventos o campañas."
        >
          <Button
            onClick={() => setShowCreate(true)}
            style={{ backgroundColor: 'var(--brand-primary)' }}
          >
            Crear formulario
          </Button>
        </EmptyState>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {items.map((f) => (
            <FormCard
              key={f.id}
              form={f}
              isAdmin={isAdmin}
              onOpen={() => setShowDetail(f)}
              onArchive={() => requestArchive(f)}
              onRestore={() => handleRestore(f)}
              onDelete={() => requestDelete(f)}
            />
          ))}
        </div>
      )}

      {/* Wizard de creación */}
      <CreateFormDialog
        open={showCreate}
        fuentes={fuentes}
        campanas={campanas}
        assignees={assignees}
        currentUser={user}
        onClose={() => setShowCreate(false)}
        onCreated={(form) => {
          setShowCreate(false)
          loadForms()
          setShowDetail(form)
        }}
      />

      {/* Detalle: QR + URL + contador */}
      <FormDetailDialog
        form={showDetail}
        onClose={() => setShowDetail(null)}
        onEdit={() => showDetail && setEditTarget(showDetail)}
        onArchive={() => showDetail && requestArchive(showDetail)}
        onRestore={() => showDetail && handleRestore(showDetail)}
        onDelete={() => showDetail && requestDelete(showDetail)}
      />

      {/* Confirmación de archivo (soft delete, reversible) */}
      <ConfirmArchiveDialog
        form={archiveTarget}
        saving={archiving}
        error={archiveError}
        onClose={() => { if (!archiving) setArchiveTarget(null) }}
        onConfirm={confirmArchive}
      />

      {/* Edición — remount con key para resetear estado al cambiar target */}
      {editTarget && (
        <EditFormDialog
          key={editTarget.id}
          form={editTarget}
          fuentes={fuentes}
          campanas={campanas}
          assignees={assignees}
          currentUser={user}
          onClose={() => setEditTarget(null)}
          onSaved={(updated) => {
            setEditTarget(null)
            loadForms()
            if (showDetail?.id === updated.id) {
              setShowDetail({ ...showDetail, ...updated })
            }
          }}
        />
      )}

      {/* Borrado permanente (hard delete) — irreversible.
          key={deleteTarget?.id} fuerza remount para resetear el input "typed". */}
      <ConfirmDeleteDialog
        key={deleteTarget?.id || 'no-delete'}
        form={deleteTarget}
        saving={deleting}
        error={deleteError}
        onClose={() => { if (!deleting) setDeleteTarget(null) }}
        onConfirm={confirmDelete}
      />
    </div>
  )
}


/* ── Filter tab ──────────────────────────────────────────────────────────── */

function FilterTab({ active, onClick, label, count, hint }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold transition-all ${
        active
          ? 'bg-[var(--brand-primary)] text-white shadow-sm'
          : 'bg-slate-100 text-slate-600 hover:bg-slate-200'
      }`}
      title={hint}
    >
      {label}
      {typeof count === 'number' && (
        <span className={`ml-1.5 ${active ? 'text-white/80' : 'text-slate-400'}`}>
          ({count})
        </span>
      )}
    </button>
  )
}


/* ── Card de resumen ─────────────────────────────────────────────────────── */

function FormCard({ form, isAdmin, onOpen, onArchive, onRestore, onDelete }) {
  const publicUrl = buildPublicUrl(form.slug)
  const isInactive = !form.activo
  const submissions = form.submission_count ?? form.leads_creados ?? 0
  const createdDate = form.created_at
    ? new Date(form.created_at).toLocaleDateString('es-PE', {
        day: '2-digit', month: 'short', year: 'numeric',
      })
    : null

  return (
    <div
      className={`group relative bg-white rounded-2xl border border-slate-200 shadow-sm hover:shadow-md hover:border-slate-300 transition-all overflow-hidden ${
        isInactive ? 'opacity-75' : ''
      }`}
    >
      {/* Barra de color superior — visual anchor con color de marca */}
      <div
        className="h-1 w-full"
        style={{
          background: isInactive
            ? '#cbd5e1'
            : 'linear-gradient(90deg, var(--brand-primary), var(--brand-primary-light, var(--brand-primary)))',
        }}
      />

      <div className="p-5">
        {/* Header: título + status */}
        <div className="flex items-start justify-between gap-2 mb-1">
          <h3 className="text-base font-semibold text-slate-900 line-clamp-2 leading-snug">
            {form.titulo}
          </h3>
          {isInactive ? (
            <span className="shrink-0 inline-flex items-center gap-1 text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full bg-slate-200 text-slate-600 font-semibold">
              <Archive size={10} />
              Archivado
            </span>
          ) : (
            <span className="shrink-0 inline-flex items-center gap-1 text-[10px] uppercase tracking-wide px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 font-semibold border border-emerald-200">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              Activo
            </span>
          )}
        </div>

        {/* Metadata */}
        <div className="space-y-0.5">
          {(form.empresa || form.nombre_evento) && (
            <p className="text-xs text-slate-500 truncate">
              {form.nombre_evento || form.empresa}
              {form.empresa && form.nombre_evento && (
                <span className="text-slate-400"> · {form.empresa}</span>
              )}
            </p>
          )}
          {form.creador_nombre && (
            <p className="text-xs text-slate-400 truncate">
              Creado por <span className="font-medium text-slate-500">{form.creador_nombre}</span>
            </p>
          )}
          {form.asignado_nombre && (
            <p className="text-xs text-slate-600 truncate flex items-center gap-1.5 mt-0.5">
              <UserCheck size={12} className="text-indigo-600 shrink-0" />
              <span>Leads a: <strong className="font-medium text-slate-700">{form.asignado_nombre}</strong></span>
              {form.asignado_rol && (
                <span className="text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.2 rounded bg-slate-100 text-slate-600 border border-slate-200">
                  {form.asignado_rol}
                </span>
              )}
            </p>
          )}
        </div>

        {/* KPI: Submissions — visual anchor.
            V093 — antes este card decia "Leads capturados" pero mostraba
            submission_count (incluye recontactos), mientras que el modal
            decia "Leads capturados" y mostraba leads_creados (solo nuevos).
            Mismo label, dos numeros distintos. Ahora "Submissions" es
            inequivoco; el modal tiene desglose completo. */}
        <div className="mt-4 flex items-center gap-3 rounded-xl bg-slate-50 border border-slate-100 px-4 py-3">
          <div
            className="w-9 h-9 rounded-lg flex items-center justify-center shrink-0"
            style={{ backgroundColor: 'var(--brand-primary)' }}
          >
            <Users size={16} className="text-white" />
          </div>
          <div className="flex-1 min-w-0">
            <div className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">
              Submissions
            </div>
            <div className="text-xl font-bold text-slate-900 leading-tight">{submissions}</div>
            <div className="text-[10px] text-slate-400">incluye recontactos</div>
          </div>
        </div>

        {/* Slug + fecha */}
        <div className="mt-3 flex items-center justify-between text-[11px] text-slate-500">
          <span className="truncate font-mono">/f/{form.slug}</span>
          {createdDate && (
            <span className="inline-flex items-center gap-1 shrink-0 ml-2">
              <Calendar size={10} />
              {createdDate}
            </span>
          )}
        </div>

        {/* Acciones */}
        <div className="mt-4 flex gap-2">
          <Button variant="outline" size="sm" className="flex-1" onClick={onOpen}>
            <QrCode size={14} />
            <span className="ml-1.5">Ver detalle</span>
          </Button>
          {!isInactive && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => window.open(publicUrl, '_blank', 'noopener,noreferrer')}
                title="Abrir formulario en una pestaña nueva"
              >
                <ExternalLink size={14} />
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={onArchive}
                title="Archivar formulario"
              >
                <Archive size={14} />
              </Button>
            </>
          )}
          {isInactive && onRestore && (
            <Button
              variant="outline"
              size="sm"
              onClick={onRestore}
              title="Reactivar formulario"
            >
              <RefreshCw size={14} />
              <span className="ml-1.5">Reactivar</span>
            </Button>
          )}
          {isInactive && isAdmin && onDelete && (
            <Button
              variant="outline"
              size="sm"
              onClick={onDelete}
              title="Eliminar definitivamente — irreversible"
              className="text-red-600 hover:bg-red-50 hover:border-red-300 hover:text-red-700"
            >
              <Trash2 size={14} />
            </Button>
          )}
        </div>
      </div>
    </div>
  )
}


/* ── Dialogo: crear ──────────────────────────────────────────────────────── */

function CreateFormDialog({ open, onClose, onCreated, fuentes, campanas = [], assignees = [], currentUser }) {
  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')

  const [titulo, setTitulo] = useState('')
  const [descripcion, setDescripcion] = useState('')
  const [nombreEvento, setNombreEvento] = useState('')
  const [empresa, setEmpresa] = useState('')
  const [fuenteId, setFuenteId] = useState('')
  const [campana, setCampana] = useState('')
  const [sedeIdDefault, setSedeIdDefault] = useState('')  // V065
  const [asignadoA, setAsignadoA] = useState('')          // Asesor o supervisor opcional
  const [mensajeExito, setMensajeExito] = useState('¡Gracias! Pronto te contactaremos.')
  const [campos, setCampos] = useState(() =>
    FIELD_CATALOG.map(c => ({ key: c.key, enabled: c.default, required: c.key === 'telefono' }))
  )

  const supervisores = useMemo(() => assignees.filter(u => u.role === 'supervisor'), [assignees])
  const asesores = useMemo(() => assignees.filter(u => u.role === 'asesor'), [assignees])
  const otrosUsuarios = useMemo(() => assignees.filter(u => u.role !== 'supervisor' && u.role !== 'asesor'), [assignees])

  // V065: catalogo de sedes — selector solo aparece si hay sedes
  const [sedes, setSedes] = useState([])
  useEffect(() => {
    if (!open) return
    api.get('/api/sedes/lookup?only_active=true')
      .then(res => setSedes(res.data || []))
      .catch(() => {})
  }, [open])

  const resetForm = () => {
    setTitulo(''); setDescripcion(''); setNombreEvento(''); setEmpresa('')
    setFuenteId(''); setCampana(''); setSedeIdDefault(''); setAsignadoA('')
    setMensajeExito('¡Gracias! Pronto te contactaremos.')
    setCampos(FIELD_CATALOG.map(c => ({ key: c.key, enabled: c.default, required: c.key === 'telefono' })))
    setErr('')
  }

  const handleClose = () => {
    if (saving) return
    resetForm()
    onClose()
  }

  const toggleEnabled = (key) => {
    setCampos(prev => prev.map(c =>
      c.key === key ? { ...c, enabled: !c.enabled, required: c.enabled ? false : c.required } : c
    ))
  }

  const toggleRequired = (key) => {
    setCampos(prev => prev.map(c =>
      c.key === key ? { ...c, required: !c.required } : c
    ))
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setErr('')

    if (titulo.trim().length < 3) {
      setErr('El título debe tener al menos 3 caracteres.')
      return
    }
    const activos = campos.filter(c => c.enabled)
    if (activos.length === 0) {
      setErr('Debes habilitar al menos un campo.')
      return
    }
    const contactoRequerido = activos.some(c =>
      (c.key === 'telefono' || c.key === 'email') && c.required
    )
    if (!contactoRequerido) {
      setErr('Al menos un campo de contacto (teléfono o email) debe ser obligatorio.')
      return
    }

    setSaving(true)
    try {
      const payload = {
        titulo: titulo.trim(),
        descripcion: descripcion.trim() || null,
        nombre_evento: nombreEvento.trim() || null,
        empresa: empresa.trim() || null,
        fuente_id: fuenteId ? Number(fuenteId) : null,
        campana: campana.trim() || null,
        sede_id_default: sedeIdDefault || null,  // V065
        asignado_a: asignadoA || null,
        config: {
          campos: activos.map(c => {
            const meta = FIELD_CATALOG.find(f => f.key === c.key)
            return {
              key: c.key,
              label: meta?.label || c.key,
              required: c.required,
              type: c.key === 'observaciones' ? 'textarea' : 'text',
            }
          }),
          mensaje_exito: mensajeExito.trim() || null,
        },
      }
      const res = await api.post('/api/public-forms', payload)
      resetForm()
      onCreated(res.data)
    } catch (error) {
      setErr(formatApiError(error, 'No se pudo crear el formulario.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onClose={handleClose} size="lg">
      {/* Header visual con gradiente + título descriptivo */}
      <div className="relative rounded-t-2xl overflow-hidden">
        <div
          className="absolute inset-0 opacity-[0.07]"
          style={{
            background: 'radial-gradient(circle at 20% 0%, var(--brand-primary), transparent 50%)',
          }}
        />
        <div className="relative flex items-start justify-between px-7 pt-6 pb-5 border-b border-slate-100">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0 shadow-sm"
                 style={{ backgroundColor: 'var(--brand-primary)' }}>
              <Sparkles size={18} className="text-white" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-900 leading-tight">
                Nuevo formulario público
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">
                Crea un link compartible para capturar leads en tu próximo evento.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={handleClose}
            className="text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg p-1.5 transition-colors"
            aria-label="Cerrar"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
      </div>

      {/* Body scroll-able cuando el form se alarga */}
      <form onSubmit={handleSubmit}>
        <div className="px-7 py-6 max-h-[70vh] overflow-y-auto space-y-7">

          {/* ── Sección: Información general ─────────────────────────── */}
          <SectionHeader
            icon={FileText}
            title="Información general"
            hint="Se muestra al público en el encabezado del formulario."
          />
          <div className="space-y-4">
            <div>
              <Label htmlFor="titulo" className="text-slate-700">Título del formulario <span className="text-rose-500">*</span></Label>
              <Input
                id="titulo"
                value={titulo}
                onChange={(e) => setTitulo(e.target.value)}
                placeholder="Ej: Captación Feria Abril"
                required
                className="mt-1.5"
              />
            </div>

            <div>
              <Label htmlFor="descripcion" className="text-slate-700">Descripción <span className="text-slate-400 font-normal">(opcional)</span></Label>
              <textarea
                id="descripcion"
                rows={3}
                value={descripcion}
                onChange={(e) => setDescripcion(e.target.value)}
                placeholder="Déjanos tus datos y te contactaremos con más información del proyecto."
                className="mt-1.5 w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-[var(--brand-primary)] focus:border-transparent transition"
              />
            </div>
          </div>

          {/* ── Sección: Metadata del evento ─────────────────────────── */}
          <div>
            <SectionHeader
              icon={Settings2}
              title="Datos del evento"
              hint="Se asocian automáticamente a cada lead capturado."
            />
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-4">
              <div>
                <Label htmlFor="nombre_evento" className="text-slate-700">Nombre del evento</Label>
                <Input
                  id="nombre_evento"
                  value={nombreEvento}
                  onChange={(e) => setNombreEvento(e.target.value)}
                  placeholder="Feria Plaza San Miguel"
                  className="mt-1.5"
                />
              </div>
              <div>
                <Label htmlFor="empresa" className="text-slate-700">Empresa</Label>
                <Input
                  id="empresa"
                  value={empresa}
                  onChange={(e) => setEmpresa(e.target.value)}
                  placeholder="Constructora XYZ"
                  className="mt-1.5"
                />
              </div>
              <div>
                <Label htmlFor="fuente" className="text-slate-700">Fuente</Label>
                <select
                  id="fuente"
                  value={fuenteId}
                  onChange={(e) => setFuenteId(e.target.value)}
                  className="mt-1.5 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-[var(--brand-primary)] focus:border-transparent transition"
                >
                  <option value="">— Sin fuente —</option>
                  {fuentes.map(f => (
                    <option key={f.id} value={f.id}>{f.nombre}</option>
                  ))}
                </select>
              </div>
              <div>
                <Label htmlFor="campana" className="text-slate-700">Campaña</Label>
                {/* UAT v3.1: era texto libre y se ensuciaba el catalogo
                    con variantes ("FB Mayo", "fb-mayo", "FB_mayo26").
                    Ahora dropdown del catalogo gestionado en Configuracion. */}
                {campanas.length > 0 ? (
                  <select
                    id="campana"
                    value={campana}
                    onChange={(e) => setCampana(e.target.value)}
                    className="w-full mt-1.5 text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  >
                    <option value="">— Sin campaña —</option>
                    {campanas.map(c => (
                      <option key={c.id} value={c.nombre}>{c.nombre}</option>
                    ))}
                  </select>
                ) : (
                  <Input
                    id="campana"
                    value={campana}
                    onChange={(e) => setCampana(e.target.value)}
                    placeholder="Carga campañas en Configuración → Campañas"
                    className="mt-1.5"
                    disabled
                  />
                )}
              </div>
            </div>

            {/* V065: Sede default — solo aparece si hay sedes configuradas */}
            {sedes.length > 0 && (
              <div className="mt-4">
                <Label htmlFor="sede" className="text-slate-700">Sede de destino</Label>
                <select
                  id="sede"
                  value={sedeIdDefault}
                  onChange={(e) => setSedeIdDefault(e.target.value)}
                  className="mt-1.5 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-[var(--brand-primary)] focus:border-transparent transition"
                >
                  <option value="">— Sin sede —</option>
                  {sedes.map(s => (
                    <option key={s.id} value={s.id}>
                      {s.ciudad ? `${s.nombre} · ${s.ciudad}` : s.nombre}
                    </option>
                  ))}
                </select>
                <p className="text-[11px] text-slate-500 mt-1">
                  Los leads que entren por este formulario quedarán asignados a esta sede.
                </p>
              </div>
            )}

            {/* Asignación directa a Asesor o Supervisor */}
            {assignees.length > 0 && (
              <div className="mt-4">
                <Label htmlFor="asignado_a" className="text-slate-700 flex items-center gap-1.5">
                  <UserCheck size={14} className="text-indigo-600" />
                  <span>Asignar leads directamente a</span>
                  <span className="text-slate-400 font-normal text-xs">(opcional)</span>
                </Label>
                <select
                  id="asignado_a"
                  value={asignadoA}
                  onChange={(e) => setAsignadoA(e.target.value)}
                  className="mt-1.5 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-[var(--brand-primary)] focus:border-transparent transition"
                >
                  <option value="">
                    — Asignar a mí por defecto {currentUser ? `(${[currentUser.first_name, currentUser.last_name].filter(Boolean).join(' ') || currentUser.email})` : ''} —
                  </option>
                  {supervisores.length > 0 && (
                    <optgroup label="Supervisores">
                      {supervisores.map(u => (
                        <option key={u.id} value={u.id}>
                          {u.nombre || u.email} {u.id === currentUser?.user_id ? '(Tú)' : ''}
                        </option>
                      ))}
                    </optgroup>
                  )}
                  {asesores.length > 0 && (
                    <optgroup label="Asesores">
                      {asesores.map(u => (
                        <option key={u.id} value={u.id}>
                          {u.nombre || u.email} {u.id === currentUser?.user_id ? '(Tú)' : ''}
                        </option>
                      ))}
                    </optgroup>
                  )}
                  {otrosUsuarios.length > 0 && (
                    <optgroup label="Administración">
                      {otrosUsuarios.map(u => (
                        <option key={u.id} value={u.id}>
                          {u.nombre || u.email} {u.id === currentUser?.user_id ? '(Tú)' : ''}
                        </option>
                      ))}
                    </optgroup>
                  )}
                </select>
                <p className="text-[11px] text-slate-500 mt-1">
                  Si seleccionas un asesor o supervisor, cada lead que se registre mediante este formulario o su código QR le llegará directamente a él junto con una notificación push.
                </p>
              </div>
            )}
          </div>

          {/* ── Sección: Campos del formulario ───────────────────────── */}
          <div>
            <SectionHeader
              icon={ListChecks}
              title="Campos que verá el lead"
              hint="Activa los campos a solicitar y marca cuáles son obligatorios."
            />
            <div className="mt-4 border border-slate-200 rounded-xl overflow-hidden bg-white">
              {/* Mini-header de la grilla */}
              <div className="grid grid-cols-[1fr_auto] gap-4 px-4 py-2.5 bg-slate-50 border-b border-slate-200 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                <span>Campo</span>
                <span>Obligatorio</span>
              </div>

              {FIELD_CATALOG.map(meta => {
                const state = campos.find(c => c.key === meta.key)
                const enabled = state.enabled
                return (
                  <div
                    key={meta.key}
                    className={`grid grid-cols-[1fr_auto] gap-4 items-center px-4 py-3 border-b border-slate-100 last:border-b-0 transition-colors ${
                      enabled ? 'bg-white' : 'bg-slate-50/40'
                    }`}
                  >
                    <label className="flex items-center gap-3 cursor-pointer select-none">
                      <CheckboxVisual checked={enabled} />
                      <input
                        type="checkbox"
                        checked={enabled}
                        onChange={() => toggleEnabled(meta.key)}
                        className="sr-only"
                      />
                      <span className={`text-sm font-medium ${enabled ? 'text-slate-800' : 'text-slate-400'}`}>
                        {meta.label}
                      </span>
                    </label>
                    <label className={`flex items-center gap-2 text-xs cursor-pointer select-none ${
                      enabled ? 'text-slate-600' : 'text-slate-300 cursor-not-allowed'
                    }`}>
                      <input
                        type="checkbox"
                        checked={state.required}
                        disabled={!enabled}
                        onChange={() => toggleRequired(meta.key)}
                        className="sr-only"
                      />
                      <SwitchVisual checked={state.required} disabled={!enabled} />
                    </label>
                  </div>
                )
              })}
            </div>
            <p className="text-[11px] text-slate-400 mt-2 flex items-center gap-1">
              <CheckCircle2 size={11} />
              Al menos un canal de contacto (teléfono o correo) debe ser obligatorio.
            </p>
          </div>

          {/* ── Sección: Mensaje de éxito ────────────────────────────── */}
          <div>
            <SectionHeader
              icon={MessageSquare}
              title="Mensaje tras el envío"
              hint="Lo verá el lead después de enviar el formulario."
            />
            <Input
              id="mensaje_exito"
              value={mensajeExito}
              onChange={(e) => setMensajeExito(e.target.value)}
              className="mt-4"
            />
          </div>

          {err && (
            <div className="rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-sm p-3.5 flex gap-2">
              <svg className="shrink-0 mt-0.5" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
              <span>{err}</span>
            </div>
          )}
        </div>

        {/* Footer fijo con acciones */}
        <div className="flex justify-end gap-2 px-7 py-4 bg-slate-50 border-t border-slate-100 rounded-b-2xl">
          <Button type="button" variant="outline" onClick={handleClose} disabled={saving}>
            Cancelar
          </Button>
          <Button
            type="submit"
            disabled={saving}
            style={{ backgroundColor: 'var(--brand-primary)' }}
          >
            {saving ? 'Creando…' : 'Crear formulario'}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}


/* ── Helpers visuales del wizard ─────────────────────────────────────────── */

function SectionHeader({ icon: Icon, title, hint }) {
  return (
    <div className="flex items-start gap-2.5">
      <div className="w-7 h-7 rounded-lg bg-slate-100 flex items-center justify-center shrink-0 mt-0.5">
        <Icon size={14} className="text-slate-600" />
      </div>
      <div>
        <h3 className="text-sm font-semibold text-slate-800 leading-tight">{title}</h3>
        {hint && <p className="text-xs text-slate-500 mt-0.5">{hint}</p>}
      </div>
    </div>
  )
}

function CheckboxVisual({ checked }) {
  return (
    <span
      className={`w-[18px] h-[18px] rounded-md border-2 flex items-center justify-center shrink-0 transition-all ${
        checked
          ? 'border-[var(--brand-primary)] bg-[var(--brand-primary)]'
          : 'border-slate-300 bg-white'
      }`}
    >
      {checked && (
        <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="20 6 9 17 4 12"></polyline>
        </svg>
      )}
    </span>
  )
}

function SwitchVisual({ checked, disabled }) {
  return (
    <span
      className={`relative inline-block w-8 h-[18px] rounded-full transition-colors ${
        disabled ? 'bg-slate-200' : checked ? 'bg-[var(--brand-primary)]' : 'bg-slate-300'
      }`}
    >
      <span
        className={`absolute top-0.5 w-[14px] h-[14px] bg-white rounded-full shadow-sm transition-all ${
          checked ? 'left-[16px]' : 'left-0.5'
        }`}
      />
    </span>
  )
}


/* ── Dialogo: detalle ────────────────────────────────────────────────────── */

function FormDetailDialog({ form, onClose, onEdit, onArchive, onRestore, onDelete }) {
  const [qrUrl, setQrUrl] = useState(null)
  const [copied, setCopied] = useState(false)
  // V093 — desglose total/nuevos/recontactos. Antes el modal mostraba
  // solo `form.leads_creados` bajo el label "Leads capturados" y el card
  // mostraba `submission_count` bajo el mismo label — dos numeros distintos
  // con el mismo nombre. Ahora pedimos el breakdown al endpoint /detail.
  const [breakdown, setBreakdown] = useState(null)

  const publicUrl = useMemo(() => form ? buildPublicUrl(form.slug) : '', [form])

  useEffect(() => {
    // Guard: si no hay form, la dialog no se renderiza (ver early return abajo),
    // pero por seguridad salimos temprano sin tocar estado.
    if (!form) return undefined
    let active = true
    let objectUrl = null
    api.get(`/api/public-forms/${form.id}/qr`, { responseType: 'blob' })
      .then(res => {
        if (!active) return
        objectUrl = URL.createObjectURL(res.data)
        setQrUrl(objectUrl)
      })
      .catch(() => { /* fallo silencioso: el UI mostrará placeholder */ })

    // V093 — fetch del desglose en paralelo con el QR
    api.get(`/api/public-forms/${form.id}`)
      .then(res => {
        if (!active) return
        if (res.data?.captures_breakdown) {
          setBreakdown(res.data.captures_breakdown)
        }
      })
      .catch(() => { /* breakdown opcional, fallback a form.leads_creados */ })

    return () => {
      active = false
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [form])

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(publicUrl)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      // fallback: prompt manual
      window.prompt('Copia este link:', publicUrl)
    }
  }

  const handleDownloadQr = () => {
    if (!qrUrl) return
    const a = document.createElement('a')
    a.href = qrUrl
    a.download = `qr-${form.slug}.png`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
  }

  if (!form) return null

  return (
    <Dialog open={!!form} onClose={onClose} size="lg">
      {/* Header visual con gradiente + ícono de marca */}
      <div className="relative rounded-t-2xl overflow-hidden">
        <div
          className="absolute inset-0 opacity-[0.07]"
          style={{
            background: 'radial-gradient(circle at 20% 0%, var(--brand-primary), transparent 50%)',
          }}
        />
        <div className="relative flex items-start justify-between px-7 pt-6 pb-5 border-b border-slate-100">
          <div className="flex items-start gap-3">
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0 shadow-sm"
              style={{ backgroundColor: 'var(--brand-primary)' }}
            >
              <QrCode size={18} className="text-white" />
            </div>
            <div className="min-w-0">
              <h2 className="text-lg font-semibold text-slate-900 leading-tight truncate">
                {form.titulo}
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">
                {form.empresa ? form.empresa : 'Formulario público'} · /f/{form.slug}
              </p>
              {form.creador_nombre && (
                <p className="text-xs text-slate-400 mt-0.5">
                  Creado por <span className="font-medium text-slate-500">{form.creador_nombre}</span>
                </p>
              )}
              {form.asignado_nombre && (
                <p className="text-xs text-slate-600 mt-0.5 flex items-center gap-1">
                  <UserCheck size={12} className="text-indigo-600 shrink-0" />
                  <span>Leads asignados a: <strong className="font-medium text-slate-700">{form.asignado_nombre}</strong></span>
                  {form.asignado_rol && (
                    <span className="text-[10px] font-semibold uppercase tracking-wider px-1.5 py-0.2 rounded bg-slate-100 text-slate-600 border border-slate-200">
                      {form.asignado_rol}
                    </span>
                  )}
                </p>
              )}
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg p-1.5 transition-colors"
            aria-label="Cerrar"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
      </div>

      {/* Body */}
      <div className="px-7 py-6 max-h-[70vh] overflow-y-auto space-y-7">

        {/* ── KPIs resumen ───────────────────────────────────────────
            V093 — desglose en 3 cards en vez de 1 ambiguo. Resuelve
            el bug "3 vs 0": el card de la lista (`submission_count`)
            mostraba un numero y el modal (`leads_creados`) mostraba otro,
            ambos bajo "Leads capturados". Ahora separados con claridad. */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">Submissions</div>
            <div className="text-2xl font-semibold text-slate-900 mt-1">
              {breakdown?.total_submissions ?? form.submission_count ?? 0}
            </div>
            <div className="text-[10px] text-slate-400 mt-0.5">veces que se envió</div>
          </div>
          <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4">
            <div className="text-[11px] uppercase tracking-wider text-emerald-700 font-semibold">Leads nuevos</div>
            <div className="text-2xl font-semibold text-emerald-900 mt-1">
              {breakdown?.leads_nuevos ?? form.leads_creados ?? 0}
            </div>
            <div className="text-[10px] text-emerald-700/70 mt-0.5">creados solo aquí</div>
          </div>
          <div className="rounded-xl border border-amber-200 bg-amber-50 p-4">
            <div className="text-[11px] uppercase tracking-wider text-amber-700 font-semibold">Recontactos</div>
            <div className="text-2xl font-semibold text-amber-900 mt-1">
              {breakdown?.recontactos ?? 0}
            </div>
            <div className="text-[10px] text-amber-700/70 mt-0.5">lead ya existía</div>
          </div>
          <div className="rounded-xl border border-slate-200 bg-white p-4">
            <div className="text-[11px] uppercase tracking-wider text-slate-500 font-semibold">Estado</div>
            <div className="mt-1 flex items-center gap-2">
              <span
                className={`inline-block w-2 h-2 rounded-full ${
                  form.activo ? 'bg-emerald-500' : 'bg-slate-400'
                }`}
              />
              <span className="text-base font-semibold text-slate-800">
                {form.activo ? 'Activo' : 'Archivado'}
              </span>
            </div>
          </div>
        </div>

        {/* ── Sección: QR code ─────────────────────────────────────── */}
        <div>
          <SectionHeader
            icon={QrCode}
            title="Código QR"
            hint="Imprímelo o compártelo en pantalla durante el evento."
          />
          <div className="mt-4 flex flex-col items-center gap-3 py-4 rounded-xl bg-slate-50 border border-slate-200">
            {qrUrl ? (
              <img
                src={qrUrl}
                alt="QR del formulario"
                className="w-52 h-52 bg-white p-3 border border-slate-200 rounded-xl shadow-sm"
              />
            ) : (
              <div className="w-52 h-52 border border-dashed border-slate-300 rounded-xl flex items-center justify-center text-xs text-slate-400 bg-white">
                Generando QR…
              </div>
            )}
            {qrUrl && (
              <Button variant="outline" size="sm" onClick={handleDownloadQr}>
                <QrCode size={14} />
                <span className="ml-1.5">Descargar QR</span>
              </Button>
            )}
          </div>
        </div>

        {/* ── Sección: Link público ────────────────────────────────── */}
        <div>
          <SectionHeader
            icon={ExternalLink}
            title="Link público"
            hint="Compártelo por WhatsApp, email o en redes sociales."
          />
          <div className="flex gap-2 mt-4">
            <Input value={publicUrl} readOnly className="font-mono text-xs" />
            <Button variant="outline" onClick={handleCopy} title="Copiar link">
              {copied ? <CheckCircle2 size={16} className="text-emerald-600" /> : <Copy size={16} />}
            </Button>
            <Button
              variant="outline"
              onClick={() => window.open(publicUrl, '_blank', 'noopener,noreferrer')}
              title="Abrir en nueva pestaña"
            >
              <ExternalLink size={16} />
            </Button>
          </div>
          {copied && (
            <p className="text-[11px] text-emerald-600 mt-1.5 flex items-center gap-1">
              <CheckCircle2 size={11} /> Link copiado al portapapeles
            </p>
          )}
        </div>
      </div>

      {/* Footer fijo con acciones */}
      <div className="flex justify-between items-center gap-2 px-7 py-4 bg-slate-50 border-t border-slate-100 rounded-b-2xl flex-wrap">
        <div className="flex gap-2 flex-wrap">
          {form.activo && onEdit && (
            <Button variant="outline" onClick={onEdit}>
              <Pencil size={14} />
              <span className="ml-1.5">Editar</span>
            </Button>
          )}
          {form.activo ? (
            <Button variant="outline" onClick={onArchive}>
              <Archive size={14} />
              <span className="ml-1.5">Archivar</span>
            </Button>
          ) : (
            <>
              {onRestore && (
                <Button variant="outline" onClick={onRestore}>
                  <RefreshCw size={14} />
                  <span className="ml-1.5">Reactivar</span>
                </Button>
              )}
              {onDelete && (
                <Button
                  variant="outline"
                  onClick={onDelete}
                  className="text-rose-700 border-rose-300 hover:bg-rose-50"
                >
                  <Trash2 size={14} />
                  <span className="ml-1.5">Borrar</span>
                </Button>
              )}
            </>
          )}
        </div>
        <Button
          type="button"
          onClick={onClose}
          style={{ backgroundColor: 'var(--brand-primary)' }}
        >
          Cerrar
        </Button>
      </div>
    </Dialog>
  )
}


/* ── Dialogo: confirmación de archivo ────────────────────────────────────── */

function ConfirmArchiveDialog({ form, saving, error, onClose, onConfirm }) {
  if (!form) return null

  return (
    <Dialog open={!!form} onClose={onClose} size="sm">
      {/* Header destacado con ícono de advertencia */}
      <div className="relative rounded-t-2xl overflow-hidden">
        <div
          className="absolute inset-0 opacity-[0.06]"
          style={{ background: 'radial-gradient(circle at 20% 0%, #f59e0b, transparent 50%)' }}
        />
        <div className="relative flex items-start gap-3 px-6 pt-6 pb-4">
          <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0 bg-amber-100 border border-amber-200">
            <AlertTriangle size={20} className="text-amber-600" />
          </div>
          <div className="flex-1 min-w-0">
            <h2 className="text-base font-semibold text-slate-900 leading-tight">
              ¿Archivar este formulario?
            </h2>
            <p className="text-xs text-slate-500 mt-1 line-clamp-2">
              {form.titulo}
            </p>
          </div>
        </div>
      </div>

      {/* Body: consecuencias + nota de reversibilidad */}
      <div className="px-6 pb-5 space-y-3">
        <div className="rounded-lg bg-amber-50 border border-amber-200 p-3.5 space-y-2">
          <p className="text-xs text-amber-900 font-semibold uppercase tracking-wide">
            Al archivar
          </p>
          <ul className="text-xs text-amber-800 space-y-1 leading-relaxed">
            <li className="flex gap-1.5">
              <span className="text-amber-600 shrink-0">•</span>
              El link público <span className="font-mono">/f/{form.slug}</span> dejará de funcionar
            </li>
            <li className="flex gap-1.5">
              <span className="text-amber-600 shrink-0">•</span>
              El QR dejará de abrir el formulario
            </li>
            <li className="flex gap-1.5">
              <span className="text-amber-600 shrink-0">•</span>
              Los leads capturados <strong>se conservan intactos</strong>
            </li>
          </ul>
        </div>

        <div className="rounded-lg bg-emerald-50 border border-emerald-200 p-3 flex gap-2">
          <CheckCircle2 size={14} className="text-emerald-600 shrink-0 mt-0.5" />
          <p className="text-xs text-emerald-800 leading-relaxed">
            <strong>Es reversible.</strong> Puedes reactivarlo después desde la pestaña
            <span className="font-semibold"> “Todos”</span> con el botón Reactivar.
          </p>
        </div>

        {error && (
          <div className="rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-xs p-3 flex gap-2">
            <AlertTriangle size={14} className="shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}
      </div>

      {/* Footer con acciones */}
      <div className="flex justify-end gap-2 px-6 py-4 bg-slate-50 border-t border-slate-100 rounded-b-2xl">
        <Button variant="outline" onClick={onClose} disabled={saving}>
          Cancelar
        </Button>
        <Button
          onClick={onConfirm}
          disabled={saving}
          className="bg-amber-600 hover:bg-amber-700"
        >
          <Archive size={14} />
          <span className="ml-1.5">{saving ? 'Archivando…' : 'Sí, archivar'}</span>
        </Button>
      </div>
    </Dialog>
  )
}


/* ── Dialogo: edición de formulario ──────────────────────────────────────── */

/**
 * EditFormDialog — permite modificar metadata + campos de un form existente.
 *
 * El slug NO es editable (rompería QRs impresos / links compartidos).
 * Los leads ya capturados NO se ven afectados — cada uno tiene su snapshot.
 * Solo las próximas submissions usan la nueva config.
 */
function EditFormDialog({ form, onClose, onSaved, fuentes, campanas = [], assignees = [], currentUser }) {
  // Inicialización a partir del form — usamos lazy initializer para no
  // recalcular en cada render.
  const [titulo, setTitulo] = useState(() => form.titulo || '')
  const [descripcion, setDescripcion] = useState(() => form.descripcion || '')
  const [nombreEvento, setNombreEvento] = useState(() => form.nombre_evento || '')
  const [empresa, setEmpresa] = useState(() => form.empresa || '')
  const [fuenteId, setFuenteId] = useState(() =>
    form.fuente_id != null ? String(form.fuente_id) : ''
  )
  const [campana, setCampana] = useState(() => form.campana || '')
  const [sedeIdDefault, setSedeIdDefault] = useState(() => form.sede_id_default || '')  // V065
  const [asignadoA, setAsignadoA] = useState(() => form.asignado_a ? String(form.asignado_a) : '')
  const [mensajeExito, setMensajeExito] = useState(() =>
    form.config?.mensaje_exito || '¡Gracias! Pronto te contactaremos.'
  )

  const supervisores = useMemo(() => assignees.filter(u => u.role === 'supervisor'), [assignees])
  const asesores = useMemo(() => assignees.filter(u => u.role === 'asesor'), [assignees])
  const otrosUsuarios = useMemo(() => assignees.filter(u => u.role !== 'supervisor' && u.role !== 'asesor'), [assignees])

  // V065: sedes para el selector
  const [sedes, setSedes] = useState([])
  useEffect(() => {
    api.get('/api/sedes/lookup?only_active=true')
      .then(res => setSedes(res.data || []))
      .catch(() => {})
  }, [])

  // Construir estado de campos a partir del config existente, respetando el
  // orden del catálogo canónico. Campos que ya están en el form se marcan
  // como enabled; los que no, quedan disponibles para activar.
  const [campos, setCampos] = useState(() => {
    const existingByKey = new Map(
      (form.config?.campos || []).map(c => [c.key, c])
    )
    return FIELD_CATALOG.map(meta => {
      const existing = existingByKey.get(meta.key)
      return {
        key: meta.key,
        enabled: !!existing,
        required: existing ? !!existing.required : (meta.key === 'telefono'),
      }
    })
  })

  const [saving, setSaving] = useState(false)
  const [err, setErr] = useState('')

  const toggleEnabled = (key) => {
    setCampos(prev => prev.map(c =>
      c.key === key ? { ...c, enabled: !c.enabled, required: c.enabled ? false : c.required } : c
    ))
  }

  const toggleRequired = (key) => {
    setCampos(prev => prev.map(c =>
      c.key === key ? { ...c, required: !c.required } : c
    ))
  }

  const handleClose = () => {
    if (saving) return
    onClose()
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setErr('')

    if (titulo.trim().length < 3) {
      setErr('El título debe tener al menos 3 caracteres.')
      return
    }
    const activos = campos.filter(c => c.enabled)
    if (activos.length === 0) {
      setErr('Debes habilitar al menos un campo.')
      return
    }
    const contactoRequerido = activos.some(c =>
      (c.key === 'telefono' || c.key === 'email') && c.required
    )
    if (!contactoRequerido) {
      setErr('Al menos un campo de contacto (teléfono o email) debe ser obligatorio.')
      return
    }

    setSaving(true)
    try {
      const payload = {
        titulo: titulo.trim(),
        descripcion: descripcion.trim() || null,
        nombre_evento: nombreEvento.trim() || null,
        empresa: empresa.trim() || null,
        fuente_id: fuenteId ? Number(fuenteId) : null,
        campana: campana.trim() || null,
        sede_id_default: sedeIdDefault || null,  // V065
        asignado_a: asignadoA || null,
        config: {
          campos: activos.map(c => {
            const meta = FIELD_CATALOG.find(f => f.key === c.key)
            return {
              key: c.key,
              label: meta?.label || c.key,
              required: c.required,
              type: c.key === 'observaciones' ? 'textarea' : 'text',
            }
          }),
          mensaje_exito: mensajeExito.trim() || null,
        },
      }
      const res = await api.patch(`/api/public-forms/${form.id}`, payload)
      onSaved(res.data)
    } catch (error) {
      setErr(formatApiError(error, 'No se pudo guardar los cambios.'))
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={true} onClose={handleClose} size="lg">
      {/* Header visual con gradiente */}
      <div className="relative rounded-t-2xl overflow-hidden">
        <div
          className="absolute inset-0 opacity-[0.07]"
          style={{
            background: 'radial-gradient(circle at 20% 0%, var(--brand-primary), transparent 50%)',
          }}
        />
        <div className="relative flex items-start justify-between px-7 pt-6 pb-5 border-b border-slate-100">
          <div className="flex items-start gap-3">
            <div
              className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0 shadow-sm"
              style={{ backgroundColor: 'var(--brand-primary)' }}
            >
              <Pencil size={18} className="text-white" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-900 leading-tight">
                Editar formulario
              </h2>
              <p className="text-xs text-slate-500 mt-0.5">
                Modifica los datos, campos o el mensaje del formulario.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={handleClose}
            className="text-slate-400 hover:text-slate-600 hover:bg-slate-100 rounded-lg p-1.5 transition-colors"
            aria-label="Cerrar"
          >
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
          </button>
        </div>
      </div>

      <form onSubmit={handleSubmit}>
        <div className="px-7 py-6 max-h-[70vh] overflow-y-auto space-y-7">

          {/* Info sobre consecuencias de editar */}
          <div className="rounded-lg bg-sky-50 border border-sky-200 p-3.5 flex gap-2">
            <CheckCircle2 size={14} className="text-sky-600 shrink-0 mt-0.5" />
            <div className="text-xs text-sky-900 leading-relaxed space-y-1">
              <p>
                <strong>Los leads ya capturados no se verán afectados</strong> — cada uno
                tiene sus datos guardados del momento en que se registró.
              </p>
              <p>
                El <span className="font-mono">slug</span> (<span className="font-mono">/f/{form.slug}</span>) y el QR ya generado
                <strong> no cambian</strong>.
              </p>
            </div>
          </div>

          {/* ── Información general ──────────────────────────────────── */}
          <SectionHeader
            icon={FileText}
            title="Información general"
            hint="Se muestra al público en el encabezado del formulario."
          />
          <div className="space-y-4">
            <div>
              <Label htmlFor="e-titulo" className="text-slate-700">
                Título del formulario <span className="text-rose-500">*</span>
              </Label>
              <Input
                id="e-titulo"
                value={titulo}
                onChange={(e) => setTitulo(e.target.value)}
                required
                className="mt-1.5"
              />
            </div>
            <div>
              <Label htmlFor="e-descripcion" className="text-slate-700">
                Descripción <span className="text-slate-400 font-normal">(opcional)</span>
              </Label>
              <textarea
                id="e-descripcion"
                rows={3}
                value={descripcion}
                onChange={(e) => setDescripcion(e.target.value)}
                className="mt-1.5 w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-800 placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-[var(--brand-primary)] focus:border-transparent transition"
              />
            </div>
          </div>

          {/* ── Datos del evento ─────────────────────────────────────── */}
          <div>
            <SectionHeader
              icon={Settings2}
              title="Datos del evento"
              hint="Se asocian automáticamente a cada nuevo lead capturado."
            />
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-4">
              <div>
                <Label htmlFor="e-nombre_evento" className="text-slate-700">Nombre del evento</Label>
                <Input
                  id="e-nombre_evento"
                  value={nombreEvento}
                  onChange={(e) => setNombreEvento(e.target.value)}
                  className="mt-1.5"
                />
              </div>
              <div>
                <Label htmlFor="e-empresa" className="text-slate-700">Empresa</Label>
                <Input
                  id="e-empresa"
                  value={empresa}
                  onChange={(e) => setEmpresa(e.target.value)}
                  className="mt-1.5"
                />
              </div>
              <div>
                <Label htmlFor="e-fuente" className="text-slate-700">Fuente</Label>
                <select
                  id="e-fuente"
                  value={fuenteId}
                  onChange={(e) => setFuenteId(e.target.value)}
                  className="mt-1.5 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-[var(--brand-primary)] focus:border-transparent transition"
                >
                  <option value="">— Sin fuente —</option>
                  {fuentes.map(f => (
                    <option key={f.id} value={f.id}>{f.nombre}</option>
                  ))}
                </select>
              </div>
              <div>
                <Label htmlFor="e-campana" className="text-slate-700">Campaña</Label>
                {campanas.length > 0 ? (
                  <select
                    id="e-campana"
                    value={campana}
                    onChange={(e) => setCampana(e.target.value)}
                    className="mt-1.5 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-[var(--brand-primary)] focus:border-transparent transition"
                  >
                    <option value="">— Sin campaña —</option>
                    {campanas.map(c => (
                      <option key={c.id} value={c.nombre}>{c.nombre}</option>
                    ))}
                  </select>
                ) : (
                  <Input
                    id="e-campana"
                    value={campana}
                    onChange={(e) => setCampana(e.target.value)}
                    className="mt-1.5"
                  />
                )}
              </div>
            </div>

            {/* V065: Sede default — solo si hay sedes configuradas */}
            {sedes.length > 0 && (
              <div className="mt-4">
                <Label htmlFor="e-sede" className="text-slate-700">Sede de destino</Label>
                <select
                  id="e-sede"
                  value={sedeIdDefault}
                  onChange={(e) => setSedeIdDefault(e.target.value)}
                  className="mt-1.5 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-[var(--brand-primary)] focus:border-transparent transition"
                >
                  <option value="">— Sin sede —</option>
                  {sedes.map(s => (
                    <option key={s.id} value={s.id}>
                      {s.ciudad ? `${s.nombre} · ${s.ciudad}` : s.nombre}
                    </option>
                  ))}
                </select>
                <p className="text-[11px] text-slate-500 mt-1">
                  Los nuevos leads de este formulario quedarán asignados a esta sede.
                  Los leads ya capturados no se ven afectados.
                </p>
              </div>
            )}

            {/* Asignación directa a Asesor o Supervisor */}
            {assignees.length > 0 && (
              <div className="mt-4">
                <Label htmlFor="e-asignado_a" className="text-slate-700 flex items-center gap-1.5">
                  <UserCheck size={14} className="text-indigo-600" />
                  <span>Asignar leads directamente a</span>
                  <span className="text-slate-400 font-normal text-xs">(opcional)</span>
                </Label>
                <select
                  id="e-asignado_a"
                  value={asignadoA}
                  onChange={(e) => setAsignadoA(e.target.value)}
                  className="mt-1.5 w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-800 focus:outline-none focus:ring-2 focus:ring-[var(--brand-primary)] focus:border-transparent transition"
                >
                  <option value="">
                    — Asignar a mí por defecto {currentUser ? `(${[currentUser.first_name, currentUser.last_name].filter(Boolean).join(' ') || currentUser.email})` : ''} —
                  </option>
                  {supervisores.length > 0 && (
                    <optgroup label="Supervisores">
                      {supervisores.map(u => (
                        <option key={u.id} value={u.id}>
                          {u.nombre || u.email} {u.id === currentUser?.user_id ? '(Tú)' : ''}
                        </option>
                      ))}
                    </optgroup>
                  )}
                  {asesores.length > 0 && (
                    <optgroup label="Asesores">
                      {asesores.map(u => (
                        <option key={u.id} value={u.id}>
                          {u.nombre || u.email} {u.id === currentUser?.user_id ? '(Tú)' : ''}
                        </option>
                      ))}
                    </optgroup>
                  )}
                  {otrosUsuarios.length > 0 && (
                    <optgroup label="Administración">
                      {otrosUsuarios.map(u => (
                        <option key={u.id} value={u.id}>
                          {u.nombre || u.email} {u.id === currentUser?.user_id ? '(Tú)' : ''}
                        </option>
                      ))}
                    </optgroup>
                  )}
                </select>
                <p className="text-[11px] text-slate-500 mt-1">
                  Los nuevos leads que entren por este formulario o su código QR le llegarán directamente al usuario seleccionado.
                </p>
              </div>
            )}
          </div>

          {/* ── Campos del formulario ────────────────────────────────── */}
          <div>
            <SectionHeader
              icon={ListChecks}
              title="Campos que verá el lead"
              hint="Activa los campos y marca cuáles son obligatorios."
            />
            <div className="mt-4 border border-slate-200 rounded-xl overflow-hidden bg-white">
              <div className="grid grid-cols-[1fr_auto] gap-4 px-4 py-2.5 bg-slate-50 border-b border-slate-200 text-[11px] font-semibold uppercase tracking-wider text-slate-500">
                <span>Campo</span>
                <span>Obligatorio</span>
              </div>
              {FIELD_CATALOG.map(meta => {
                const state = campos.find(c => c.key === meta.key)
                const enabled = state.enabled
                return (
                  <div
                    key={meta.key}
                    className={`grid grid-cols-[1fr_auto] gap-4 items-center px-4 py-3 border-b border-slate-100 last:border-b-0 transition-colors ${
                      enabled ? 'bg-white' : 'bg-slate-50/40'
                    }`}
                  >
                    <label className="flex items-center gap-3 cursor-pointer select-none">
                      <CheckboxVisual checked={enabled} />
                      <input
                        type="checkbox"
                        checked={enabled}
                        onChange={() => toggleEnabled(meta.key)}
                        className="sr-only"
                      />
                      <span className={`text-sm font-medium ${enabled ? 'text-slate-800' : 'text-slate-400'}`}>
                        {meta.label}
                      </span>
                    </label>
                    <label className={`flex items-center gap-2 text-xs cursor-pointer select-none ${
                      enabled ? 'text-slate-600' : 'text-slate-300 cursor-not-allowed'
                    }`}>
                      <input
                        type="checkbox"
                        checked={state.required}
                        disabled={!enabled}
                        onChange={() => toggleRequired(meta.key)}
                        className="sr-only"
                      />
                      <SwitchVisual checked={state.required} disabled={!enabled} />
                    </label>
                  </div>
                )
              })}
            </div>
            <p className="text-[11px] text-slate-400 mt-2 flex items-center gap-1">
              <CheckCircle2 size={11} />
              Al menos un canal de contacto (teléfono o correo) debe ser obligatorio.
            </p>
          </div>

          {/* ── Mensaje tras el envío ────────────────────────────────── */}
          <div>
            <SectionHeader
              icon={MessageSquare}
              title="Mensaje tras el envío"
              hint="Lo verá el lead después de enviar el formulario."
            />
            <Input
              id="e-mensaje_exito"
              value={mensajeExito}
              onChange={(e) => setMensajeExito(e.target.value)}
              className="mt-4"
            />
          </div>

          {err && (
            <div className="rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-sm p-3.5 flex gap-2">
              <AlertTriangle size={16} className="shrink-0 mt-0.5" />
              <span>{err}</span>
            </div>
          )}
        </div>

        {/* Footer fijo */}
        <div className="flex justify-end gap-2 px-7 py-4 bg-slate-50 border-t border-slate-100 rounded-b-2xl">
          <Button type="button" variant="outline" onClick={handleClose} disabled={saving}>
            Cancelar
          </Button>
          <Button
            type="submit"
            disabled={saving}
            style={{ backgroundColor: 'var(--brand-primary)' }}
          >
            {saving ? 'Guardando…' : 'Guardar cambios'}
          </Button>
        </div>
      </form>
    </Dialog>
  )
}


/* ── Dialogo: borrado permanente (hard delete) ──────────────────────────── */

/**
 * ConfirmDeleteDialog — borrado físico irreversible.
 *
 * Requiere que el usuario escriba el título del formulario exactamente
 * como aparece — esto evita clicks accidentales y forza consciencia.
 * Solo se muestra desde FormDetailDialog para formularios ya archivados
 * (el backend rechaza intentos sobre forms activos).
 */
function ConfirmDeleteDialog({ form, saving, error, onClose, onConfirm }) {
  const [typed, setTyped] = useState('')

  if (!form) return null

  const matches = typed.trim() === (form.titulo || '').trim()

  return (
    <Dialog open={!!form} onClose={onClose} size="sm">
      {/* Header: ícono destructivo rojo */}
      <div className="relative rounded-t-2xl overflow-hidden">
        <div
          className="absolute inset-0 opacity-[0.08]"
          style={{ background: 'radial-gradient(circle at 20% 0%, #dc2626, transparent 50%)' }}
        />
        <div className="relative flex items-start gap-3 px-6 pt-6 pb-4">
          <div className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0 bg-rose-100 border border-rose-200">
            <Trash2 size={20} className="text-rose-600" />
          </div>
          <div className="flex-1 min-w-0">
            <h2 className="text-base font-semibold text-slate-900 leading-tight">
              Borrar permanentemente
            </h2>
            <p className="text-xs text-slate-500 mt-1 line-clamp-2">
              {form.titulo}
            </p>
          </div>
        </div>
      </div>

      <div className="px-6 pb-5 space-y-3">
        {/* Consecuencias irreversibles */}
        <div className="rounded-lg bg-rose-50 border border-rose-200 p-3.5 space-y-2">
          <p className="text-xs text-rose-900 font-semibold uppercase tracking-wide flex items-center gap-1.5">
            <AlertTriangle size={12} />
            Esta acción es irreversible
          </p>
          <ul className="text-xs text-rose-800 space-y-1 leading-relaxed">
            <li className="flex gap-1.5">
              <span className="text-rose-600 shrink-0">•</span>
              El formulario se borra definitivamente de la base de datos
            </li>
            <li className="flex gap-1.5">
              <span className="text-rose-600 shrink-0">•</span>
              Se borra el historial de envíos (submissions)
            </li>
            <li className="flex gap-1.5">
              <span className="text-rose-600 shrink-0">•</span>
              Los <strong>leads capturados se conservan</strong>, pero pierden el puntero al form de origen
            </li>
            <li className="flex gap-1.5">
              <span className="text-rose-600 shrink-0">•</span>
              <strong>No se puede deshacer</strong>
            </li>
          </ul>
        </div>

        {/* Type-to-confirm */}
        <div>
          <Label htmlFor="del-confirm" className="text-xs text-slate-700">
            Para confirmar, escribe el título del formulario:
          </Label>
          <p className="text-[11px] text-slate-500 mt-0.5 mb-1.5 font-mono bg-slate-50 border border-slate-200 rounded px-2 py-1 select-all">
            {form.titulo}
          </p>
          <Input
            id="del-confirm"
            value={typed}
            onChange={(e) => setTyped(e.target.value)}
            placeholder="Escribe el título aquí"
            autoComplete="off"
            disabled={saving}
            className={matches ? 'border-emerald-400 focus:ring-emerald-500' : ''}
          />
        </div>

        {error && (
          <div className="rounded-lg bg-rose-50 border border-rose-200 text-rose-700 text-xs p-3 flex gap-2">
            <AlertTriangle size={14} className="shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}
      </div>

      <div className="flex justify-end gap-2 px-6 py-4 bg-slate-50 border-t border-slate-100 rounded-b-2xl">
        <Button variant="outline" onClick={onClose} disabled={saving}>
          Cancelar
        </Button>
        <Button
          onClick={onConfirm}
          disabled={saving || !matches}
          className="bg-rose-600 hover:bg-rose-700 disabled:bg-rose-300"
        >
          <Trash2 size={14} />
          <span className="ml-1.5">{saving ? 'Borrando…' : 'Borrar permanentemente'}</span>
        </Button>
      </div>
    </Dialog>
  )
}
