/**
 * TeamRotationPanel — Panel para gestionar la jerarquía y disponibilidad
 * de un equipo (round-robin por orden manual, V055).
 *
 * Patrón: patrón estándar Queue Round Robin / patrón estándar Workflow Rotation.
 *
 * Drag & drop NATIVO HTML5 (sin dependencias externas) — accesible y
 * estable. Cada miembro tiene:
 *   - Posición numérica (1, 2, 3...)
 *   - Nombre + email
 *   - Toggle "Disponible / Pausado" (modifica asesor_settings.disponible_rotacion)
 *   - Badge "🎯 Próximo" si es el siguiente en recibir lead
 *
 * Permisos:
 *   - Admin: cualquier equipo (props.supervisorId opcional)
 *   - Supervisor: solo su equipo (auto-restricción backend)
 *
 * Props:
 *   - supervisorId   string?  UUID del supervisor (admin lo pasa). Si null, el
 *                             backend usa el supervisor del current_user.
 *   - title          string?  Título de la card (default: "Jerarquía del equipo")
 *   - readOnly       bool?    Si true, no permite drag ni toggles (solo vista)
 */
import { useEffect, useState, useCallback, useRef } from 'react'
import {
  GripVertical, User, AlertCircle, Pause, Play, Crown, RefreshCw,
  Loader2, CheckCircle2, Ban, History, X, ArrowRight,
} from 'lucide-react'
import api from '@/lib/api'
import ConfirmDialog from '@/components/shared/ConfirmDialog'
import TeamHealthBadge from '@/components/equipos/TeamHealthBadge'

// Auto-refresh cada N segundos para que el panel siempre muestre el
// estado real del cursor + filtros (cap, horario, ausencia). Sin esto,
// el supervisor ve datos viejos cuando llegan leads desde otro tab.
const AUTO_REFRESH_MS = 15000

export default function TeamRotationPanel({ supervisorId, title, readOnly = false }) {
  const [members, setMembers]       = useState([])
  const [loading, setLoading]       = useState(true)
  const [saving, setSaving]         = useState(false)
  const [error, setError]           = useState(null)
  const [savedFlash, setSavedFlash] = useState(false)
  const [nextUp, setNextUp]         = useState(null)         // {next_user_id, next_orden, ...}
  const [auditOpen, setAuditOpen]   = useState(false)
  const [auditLog, setAuditLog]     = useState([])
  const [auditLoading, setAuditLoading] = useState(false)
  const [confirmResetOpen, setConfirmResetOpen] = useState(false)
  const dragIndexRef = useRef(null)

  const load = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setLoading(true)
    setError(null)
    try {
      const params = supervisorId ? `?supervisor_id=${supervisorId}` : ''
      const res = await api.get(`/api/equipos/by-supervisor${params}`)
      setMembers(res.data || [])

      // Indicador "🎯 próximo" — solo si la estrategia es round_robin_orden
      try {
        const nextRes = await api.get(`/api/equipos/next-up${params}`)
        setNextUp(nextRes.data?.deterministic ? nextRes.data : null)
      } catch { setNextUp(null) }
    } catch (err) {
      setError(err?.response?.data?.detail || 'No se pudo cargar el equipo.')
    } finally {
      if (!silent) setLoading(false)
    }
  }, [supervisorId])

  useEffect(() => { load() }, [load])

  // Auto-refresh silencioso cada AUTO_REFRESH_MS para reflejar leads que
  // llegan desde otro tab/Postman/Meta sin que el supervisor recargue.
  useEffect(() => {
    if (readOnly) return
    const id = setInterval(() => load({ silent: true }), AUTO_REFRESH_MS)
    return () => clearInterval(id)
  }, [load, readOnly])

  // Refresh inmediato al volver el foco a la tab (UX premium)
  useEffect(() => {
    const onFocus = () => load({ silent: true })
    window.addEventListener('focus', onFocus)
    return () => window.removeEventListener('focus', onFocus)
  }, [load])

  // ── Drag & drop handlers (HTML5 nativo) ──────────────────────────────────

  const onDragStart = (idx) => (e) => {
    if (readOnly) return
    dragIndexRef.current = idx
    e.dataTransfer.effectAllowed = 'move'
    e.dataTransfer.setData('text/plain', idx)
  }

  const onDragOver = (e) => {
    if (readOnly) return
    e.preventDefault()
    e.dataTransfer.dropEffect = 'move'
  }

  const onDrop = (idx) => async (e) => {
    if (readOnly) return
    e.preventDefault()
    const from = dragIndexRef.current
    const to = idx
    if (from == null || from === to) return
    dragIndexRef.current = null

    // Reorder local optimista
    const next = [...members]
    const [moved] = next.splice(from, 1)
    next.splice(to, 0, moved)
    // Recalcula orden 1..N basado en nueva posición
    const reordered = next.map((m, i) => ({ ...m, orden: i + 1 }))
    setMembers(reordered)

    // Persistir
    await persistOrder(reordered)
  }

  const persistOrder = async (list) => {
    if (list.length === 0) return
    const sup = list[0].supervisor_id
    setSaving(true)
    setError(null)
    try {
      await api.put('/api/equipos/reorder', {
        supervisor_id: sup,
        items: list.map(m => ({ equipo_id: m.equipo_id, orden: m.orden })),
      })
      setSavedFlash(true)
      setTimeout(() => setSavedFlash(false), 2000)
      // Refresh next-up
      try {
        const params = supervisorId ? `?supervisor_id=${supervisorId}` : ''
        const nextRes = await api.get(`/api/equipos/next-up${params}`)
        setNextUp(nextRes.data?.deterministic ? nextRes.data : null)
      } catch { /* noop */ }
    } catch (err) {
      setError(err?.response?.data?.detail || 'No se pudo guardar el nuevo orden.')
      // Revertir cargando del server
      load()
    } finally {
      setSaving(false)
    }
  }

  const toggleDisponibilidad = async (m) => {
    if (readOnly) return
    const newVal = !m.disponible_rotacion
    setMembers(prev => prev.map(x => x.equipo_id === m.equipo_id
      ? { ...x, disponible_rotacion: newVal }
      : x
    ))
    try {
      await api.patch(`/api/equipos/${m.equipo_id}/disponibilidad`, {
        disponible_rotacion: newVal,
      })
      // Refresh next-up tras pausar/reanudar
      try {
        const params = supervisorId ? `?supervisor_id=${supervisorId}` : ''
        const nextRes = await api.get(`/api/equipos/next-up${params}`)
        setNextUp(nextRes.data?.deterministic ? nextRes.data : null)
      } catch { /* noop */ }
    } catch (err) {
      setError(err?.response?.data?.detail || 'No se pudo actualizar disponibilidad.')
      // Revertir
      setMembers(prev => prev.map(x => x.equipo_id === m.equipo_id
        ? { ...x, disponible_rotacion: !newVal }
        : x
      ))
    }
  }

  // ── V056: Historial de auditoría (reorder, pausar, reset) ────────────────

  const openAudit = async () => {
    if (members.length === 0) return
    const sup = members[0].supervisor_id
    setAuditOpen(true)
    setAuditLoading(true)
    try {
      const res = await api.get(`/api/equipos/audit-log?supervisor_id=${sup}&limit=30`)
      setAuditLog(res.data || [])
    } catch (err) {
      setError(err?.response?.data?.detail || 'No se pudo cargar el historial.')
    } finally {
      setAuditLoading(false)
    }
  }

  const requestReset = () => {
    if (readOnly || members.length === 0) return
    setConfirmResetOpen(true)
  }

  const doResetRotacion = async () => {
    setConfirmResetOpen(false)
    if (members.length === 0) return
    const sup = members[0].supervisor_id
    setSaving(true)
    try {
      await api.post(`/api/equipos/reset-rotacion?supervisor_id=${sup}`)
      try {
        const params = supervisorId ? `?supervisor_id=${supervisorId}` : ''
        const nextRes = await api.get(`/api/equipos/next-up${params}`)
        setNextUp(nextRes.data?.deterministic ? nextRes.data : null)
      } catch { /* noop */ }
      setSavedFlash(true)
      setTimeout(() => setSavedFlash(false), 1500)
    } catch (err) {
      setError(err?.response?.data?.detail || 'No se pudo reiniciar.')
    } finally {
      setSaving(false)
    }
  }

  // ── Render ────────────────────────────────────────────────────────────────

  if (loading) {
    return (
      <div className="flex items-center justify-center py-10 text-gray-400">
        <Loader2 size={20} className="animate-spin" />
      </div>
    )
  }

  if (members.length === 0) {
    return (
      <div className="text-center py-8 text-sm text-gray-400">
        No hay miembros en este equipo.
      </div>
    )
  }

  return (
    <div className="space-y-3">
      {/* Header con info y acciones */}
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <div className="flex items-center gap-2 flex-wrap">
            {title && <h3 className="text-sm font-semibold text-gray-800">{title}</h3>}
            {/* V070.78 (ADR-0010): badge de salud del equipo (active/at_risk/blocked) */}
            <TeamHealthBadge supervisorId={supervisorId} />
          </div>
          <p className="text-xs text-gray-500 mt-0.5">
            {readOnly
              ? 'Vista de solo lectura'
              : 'Arrastrá los asesores para reordenar la jerarquía. El cambio se guarda automáticamente.'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          {saving && (
            <span className="inline-flex items-center gap-1 text-xs text-indigo-600">
              <Loader2 size={12} className="animate-spin" /> Guardando…
            </span>
          )}
          {savedFlash && !saving && (
            <span className="inline-flex items-center gap-1 text-xs text-emerald-600">
              <CheckCircle2 size={12} /> Guardado
            </span>
          )}
          <button
            onClick={openAudit}
            className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-md text-gray-500 hover:text-indigo-600 hover:bg-indigo-50 transition-colors"
            title="Ver historial de cambios en la jerarquía"
          >
            <History size={11} /> Historial
          </button>
          {!readOnly && (
            <button
              onClick={requestReset}
              className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-md text-gray-500 hover:text-indigo-600 hover:bg-indigo-50 transition-colors"
              title="Reiniciar el cursor: el siguiente lead irá a la posición #1"
            >
              <RefreshCw size={11} /> Reiniciar rotación
            </button>
          )}
        </div>
      </div>

      {/* V056: Modal de historial de auditoría */}
      {auditOpen && (
        <AuditLogModal
          log={auditLog}
          loading={auditLoading}
          onClose={() => setAuditOpen(false)}
        />
      )}

      {/* V056: Modal de confirmación premium (reemplaza confirm() nativo) */}
      <ConfirmDialog
        open={confirmResetOpen}
        title="Reiniciar rotación"
        message="El cursor del round-robin volverá al inicio. El siguiente lead irá a la posición #1 del equipo."
        confirmLabel="Sí, reiniciar"
        cancelLabel="Cancelar"
        variant="warning"
        onConfirm={doResetRotacion}
        onCancel={() => setConfirmResetOpen(false)}
      />

      {/* Indicador "🎯 Próximo" */}
      {nextUp && nextUp.next_user_id && (
        <div className="flex items-center gap-2 text-xs bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-amber-800">
          <Crown size={14} className="text-amber-600 shrink-0" />
          <span>
            Próximo lead → <strong>{nextUp.next_nombre}</strong> (posición #{nextUp.next_orden})
          </span>
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 bg-red-50 border border-red-200 rounded-lg px-3 py-2 text-xs text-red-700">
          <AlertCircle size={13} /> {error}
        </div>
      )}

      {/* Lista sortable */}
      <ul className="space-y-1.5">
        {members.map((m, idx) => {
          const isNext = nextUp?.next_user_id === m.asesor_id
          const isPaused = !m.disponible_rotacion
          const isElegible = m.elegible !== false   // default true si backend no lo manda
          // Estado visual prioridad: pausado manual > descartado por filtro > elegible
          const statusBadge = isPaused
            ? { label: 'PAUSADO', cls: 'bg-gray-200 text-gray-600' }
            : (!isElegible
                ? { label: motivoCorto(m.motivo_descarte), cls: 'bg-orange-100 text-orange-700' }
                : null)
          return (
            <li
              key={m.equipo_id}
              draggable={!readOnly}
              onDragStart={onDragStart(idx)}
              onDragOver={onDragOver}
              onDrop={onDrop(idx)}
              className={`group flex items-center gap-2.5 px-3 py-2 rounded-lg border transition-all ${
                isNext
                  ? 'border-amber-300 bg-amber-50/40'
                  : (isPaused || !isElegible)
                    ? 'border-gray-200 bg-gray-50/60 opacity-75'
                    : 'border-gray-200 bg-white hover:border-indigo-200 hover:bg-indigo-50/30'
              } ${!readOnly ? 'cursor-move' : ''}`}
              title={!isElegible && m.motivo_descarte ? `Descartado por motor: ${m.motivo_descarte}` : undefined}
            >
              {!readOnly && (
                <GripVertical size={14} className="text-gray-300 group-hover:text-gray-500 shrink-0" />
              )}

              {/* Posición */}
              <span className={`text-xs font-bold w-6 h-6 rounded-full flex items-center justify-center shrink-0 ${
                isNext ? 'bg-amber-400 text-white' : 'bg-gray-100 text-gray-500'
              }`}>
                {m.orden}
              </span>

              {/* Avatar */}
              <div className="w-8 h-8 rounded-full bg-indigo-50 text-indigo-600 flex items-center justify-center shrink-0">
                <User size={14} />
              </div>

              {/* Datos */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-1.5 flex-wrap">
                  <span className={`text-sm font-medium truncate ${isPaused || !isElegible ? 'text-gray-500' : 'text-gray-800'}`}>
                    {m.asesor_nombre}
                  </span>
                  {isNext && (
                    <span className="text-[10px] inline-flex items-center gap-0.5 bg-amber-100 text-amber-700 px-1.5 py-0.5 rounded font-semibold">
                      🎯 PRÓXIMO
                    </span>
                  )}
                  {statusBadge && (
                    <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold ${statusBadge.cls}`}>
                      {statusBadge.label}
                    </span>
                  )}
                </div>
                <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                  {m.asesor_email && (
                    <p className="text-[11px] text-gray-400 truncate">{m.asesor_email}</p>
                  )}
                  {/* Ratio leads_abiertos / cap — color segun saturación */}
                  {m.leads_abiertos != null && m.max_leads_abiertos && (
                    <span
                      className={`text-[10px] font-medium ${
                        m.leads_abiertos >= m.max_leads_abiertos
                          ? 'text-orange-600'
                          : m.leads_abiertos >= m.max_leads_abiertos * 0.8
                            ? 'text-amber-600'
                            : 'text-gray-400'
                      }`}
                      title={`${m.leads_abiertos} leads abiertos de ${m.max_leads_abiertos} permitidos`}
                    >
                      · {m.leads_abiertos}/{m.max_leads_abiertos}
                    </span>
                  )}
                  {m.leads_hoy != null && m.leads_hoy > 0 && (
                    <span className="text-[10px] text-gray-400">· {m.leads_hoy} hoy</span>
                  )}
                </div>
              </div>

              {/* Toggle disponibilidad */}
              {!readOnly && (
                <button
                  onClick={() => toggleDisponibilidad(m)}
                  className={`shrink-0 inline-flex items-center gap-1 text-xs px-2.5 py-1 rounded-md transition-colors ${
                    isPaused
                      ? 'bg-emerald-50 text-emerald-700 hover:bg-emerald-100 border border-emerald-200'
                      : 'bg-white text-gray-500 hover:bg-amber-50 hover:text-amber-700 border border-gray-200 hover:border-amber-300'
                  }`}
                  title={isPaused ? 'Reanudar — vuelve a recibir leads' : 'Pausar — deja de recibir leads'}
                >
                  {isPaused ? <Play size={11} /> : <Pause size={11} />}
                  {isPaused ? 'Reanudar' : 'Pausar'}
                </button>
              )}
            </li>
          )
        })}
      </ul>
    </div>
  )
}

// Acorta el motivo del backend a un label corto para el badge
function motivoCorto(motivo) {
  if (!motivo) return 'NO ELEGIBLE'
  const m = motivo.toLowerCase()
  if (m.includes('capacity')) return 'LLENO'
  if (m.includes('horario'))  return 'FUERA DE HORARIO'
  if (m.includes('ausencia')) return 'EN AUSENCIA'
  if (m.includes('dia') || m.includes('semana')) return 'NO TRABAJA HOY'
  if (m.includes('disponible')) return 'NO DISPONIBLE'
  return 'NO ELEGIBLE'
}

// ─── V056: Modal con historial de auditoría ────────────────────────────────

const ACCION_LABEL = {
  reorder:          { label: 'Reordenamiento', color: 'bg-indigo-100 text-indigo-700' },
  pausar_asesor:    { label: 'Pausa de asesor', color: 'bg-amber-100 text-amber-700' },
  reanudar_asesor:  { label: 'Reanudación', color: 'bg-emerald-100 text-emerald-700' },
  reset_rotacion:   { label: 'Reset rotación', color: 'bg-purple-100 text-purple-700' },
  agregar_asesor:   { label: 'Asesor agregado', color: 'bg-sky-100 text-sky-700' },
  quitar_asesor:    { label: 'Asesor removido', color: 'bg-rose-100 text-rose-700' },
}

function fmtTime(iso) {
  if (!iso) return ''
  try {
    const d = new Date(iso)
    return d.toLocaleString('es-PE', {
      day: '2-digit', month: '2-digit', year: '2-digit',
      hour: '2-digit', minute: '2-digit',
    })
  } catch { return iso }
}

function diffOrdenes(antes, despues) {
  if (!Array.isArray(antes) || !Array.isArray(despues)) return []
  const antesMap = new Map(antes.map(a => [a.asesor_id, a]))
  const cambios = []
  for (const d of despues) {
    const a = antesMap.get(d.asesor_id)
    if (a && a.orden !== d.orden) {
      cambios.push({ nombre: d.nombre, antes: a.orden, despues: d.orden })
    }
  }
  return cambios
}

function AuditLogModal({ log, loading, onClose }) {
  return (
    <div
      className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-xl shadow-2xl max-w-2xl w-full max-h-[80vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-100">
          <div className="flex items-center gap-2">
            <History size={16} className="text-indigo-600" />
            <h3 className="text-sm font-semibold text-gray-800">Historial del equipo</h3>
            <span className="text-[10px] text-gray-400">últimos 30 cambios</span>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-700 p-1 rounded-md hover:bg-gray-100 transition-colors"
            aria-label="Cerrar"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="overflow-y-auto flex-1 px-5 py-4">
          {loading ? (
            <div className="flex items-center justify-center py-10 text-gray-400">
              <Loader2 size={18} className="animate-spin" />
            </div>
          ) : log.length === 0 ? (
            <div className="text-center py-10 text-sm text-gray-400">
              Aún no hay cambios registrados en este equipo.
            </div>
          ) : (
            <ul className="space-y-2">
              {log.map(entry => {
                const meta = ACCION_LABEL[entry.accion] || {
                  label: entry.accion, color: 'bg-gray-100 text-gray-700',
                }
                const cambios = entry.accion === 'reorder'
                  ? diffOrdenes(entry.orden_antes, entry.orden_despues)
                  : []
                return (
                  <li
                    key={entry.id}
                    className="border border-gray-100 rounded-lg p-3 hover:bg-gray-50/50 transition-colors"
                  >
                    <div className="flex items-start justify-between gap-3">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className={`text-[10px] font-semibold rounded px-1.5 py-0.5 ${meta.color}`}>
                            {meta.label}
                          </span>
                          <span className="text-[11px] text-gray-500">
                            por <strong className="text-gray-700">{entry.actor_nombre || entry.actor_email || '—'}</strong>
                            {entry.actor_role && (
                              <span className="text-gray-400"> · {entry.actor_role}</span>
                            )}
                          </span>
                        </div>
                        {entry.detalle && (
                          <p className="text-xs text-gray-600 mt-1">{entry.detalle}</p>
                        )}
                        {cambios.length > 0 && (
                          <ul className="mt-2 space-y-0.5">
                            {cambios.slice(0, 5).map((c, i) => (
                              <li key={i} className="text-[11px] text-gray-500 flex items-center gap-1.5">
                                <span className="font-medium text-gray-700">{c.nombre}</span>
                                <span className="text-gray-400">#{c.antes}</span>
                                <ArrowRight size={10} className="text-gray-400" />
                                <span className="font-semibold text-indigo-600">#{c.despues}</span>
                              </li>
                            ))}
                            {cambios.length > 5 && (
                              <li className="text-[10px] text-gray-400 italic">
                                + {cambios.length - 5} cambio(s) más…
                              </li>
                            )}
                          </ul>
                        )}
                      </div>
                      <span className="text-[10px] text-gray-400 whitespace-nowrap shrink-0">
                        {fmtTime(entry.created_at)}
                      </span>
                    </div>
                  </li>
                )
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  )
}
