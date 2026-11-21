/**
 * Reparto de leads — panel admin con 5 tabs.
 *
 *   Tab 1 — Entre supervisores: round-robin diario (lo que ya existia).
 *   Tab 2 — Del supervisor al asesor: motor de auto-asignacion (V046).
 *   Tab 3 — Reglas avanzadas: routing por fuente / proveedor / campana.
 *   Tab 4 — Asesores: capacity, horarios, vacaciones, peso de rotacion.
 *   Tab 5 — Auditoria: ultimas decisiones del motor + stats.
 *
 * Roles: solo admin (protegido en App.jsx con AdminRoute).
 */
import React, { useEffect, useState, useCallback, useMemo } from 'react'
import {
  RefreshCw, Shuffle, CheckCircle2, XCircle, Users, User, Layers,
  Activity, Plus, Edit2, Trash2, Save, X as XIcon, Power,
  ArrowUp, ArrowDown, AlertCircle, Clock, Calendar as CalIcon,
  Sparkles, FlaskConical, ChevronDown, ChevronRight, Briefcase, Info,
  Inbox, ArrowRight, UserCheck, Lock, UserPlus,
} from 'lucide-react'
import api from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import LoadingSpinner from '@/components/shared/LoadingSpinner'
import EmptyState from '@/components/shared/EmptyState'
import ConfirmDialog from '@/components/shared/ConfirmDialog'
import ApplyChangesPreviewDialog from '@/components/shared/ApplyChangesPreviewDialog'
import { useUndoToast } from '@/components/shared/UndoToast'
import TeamHealthBadge from '@/components/equipos/TeamHealthBadge'
import AdminTeamsBlockedBanner from '@/components/equipos/AdminTeamsBlockedBanner'
import TogglesInconsistencyBanner from '@/components/equipos/TogglesInconsistencyBanner'
import { cn } from '@/lib/utils'

const REFRESH_MS = 30_000

const TABS = [
  { id: 'supervisores', label: '1. Distribución entre supervisores', icon: Shuffle,    desc: 'Decide qué supervisor recibe cada lead nuevo (round-robin diario).' },
  { id: 'auto',         label: '2. Auto-asignación dentro del equipo', icon: Users,    desc: 'Cuando el supervisor recibe un lead, el motor lo reparte al asesor del equipo.' },
  { id: 'reglas',       label: 'Reglas avanzadas',         icon: Layers,   desc: 'Routing condicional por fuente, campaña o proveedor.' },
  { id: 'asesores',     label: 'Asesores',                 icon: Briefcase,desc: 'Capacity, horarios y vacaciones por asesor.' },
  { id: 'auditoria',    label: 'Auditoría',                icon: Activity, desc: 'Decisiones automáticas y métricas del motor.' },
]

export default function Rotacion() {
  const [tab, setTab] = useState(() => {
    const params = new URLSearchParams(window.location.search)
    return params.get('tab') || 'supervisores'
  })

  const changeTab = (next) => {
    setTab(next)
    const params = new URLSearchParams(window.location.search)
    params.set('tab', next)
    window.history.replaceState({}, '', `${window.location.pathname}?${params.toString()}`)
    const main = document.querySelector('main')
    if (main) main.scrollTo({ top: 0, behavior: 'instant' })
  }

  const activeTab = TABS.find(t => t.id === tab) || TABS[0]
  const TabIcon = activeTab.icon

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-4">
      {/* Banner global de equipos bloqueados por circuit breaker */}
      <AdminTeamsBlockedBanner />

      {/* Banner de toggles inconsistentes (issue #59 - patrón estándar) */}
      <TogglesInconsistencyBanner />

      {/* Header dinamico */}
      <div className="flex items-start gap-3 pb-5 mb-2 border-b border-gray-100">
        <div
          className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
          style={{ backgroundColor: 'rgba(var(--brand-primary-rgb), 0.1)' }}
        >
          <TabIcon size={20} style={{ color: 'var(--brand-primary)' }} />
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-semibold text-gray-900 leading-tight">
            Reparto de leads
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">{activeTab.desc}</p>
        </div>
      </div>

      {/* Mini-diagrama de flujo (solo en los 2 tabs operacionales) */}
      {(tab === 'supervisores' || tab === 'auto') && <AssignmentFlowDiagram activeStep={tab} />}

      {/* Tabs nav */}
      <div className="border-b border-gray-200 flex items-center gap-1 overflow-x-auto -mt-1 mb-4">
        {TABS.map(t => {
          const Icon = t.icon
          const active = tab === t.id
          return (
            <button
              key={t.id}
              onClick={() => changeTab(t.id)}
              className={cn(
                'flex items-center gap-2 px-4 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 transition-colors',
                active
                  ? 'border-[var(--brand-primary)] text-[var(--brand-primary)]'
                  : 'border-transparent text-gray-500 hover:text-gray-700'
              )}
            >
              <Icon size={15} />
              {t.label}
            </button>
          )
        })}
      </div>

      {tab === 'supervisores' && <TabSupervisores />}
      {tab === 'auto'         && <TabAutoAsignacion />}
      {tab === 'reglas'       && <TabReglas />}
      {tab === 'asesores'     && <TabAsesores />}
      {tab === 'auditoria'    && <TabAuditoria />}
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────
   Mini-diagrama de flujo del reparto (didactico).
   Muestra los 2 pasos del routing como tarjetas conectadas con
   flechas. El paso correspondiente al tab activo se resalta.
   ───────────────────────────────────────────────────────────────── */
function AssignmentFlowDiagram({ activeStep }) {
  const isStep1 = activeStep === 'supervisores'
  const isStep2 = activeStep === 'auto'

  return (
    <div className="rounded-xl border border-gray-200 bg-gradient-to-br from-gray-50 to-white p-4">
      <div className="flex items-center justify-center gap-1 sm:gap-2 flex-wrap">
        <FlowNode
          icon={Inbox}
          label="Lead nuevo"
          sub="Meta, TikTok, WhatsApp…"
          tone="neutral"
        />
        <FlowConnector
          stepLabel="Paso 1"
          subLabel="Entre supervisores"
          active={isStep1}
        />
        <FlowNode
          icon={User}
          label="Supervisor"
          sub="Round-robin diario"
          tone={isStep1 ? 'accent' : 'neutral'}
          highlight={isStep1}
        />
        <FlowConnector
          stepLabel="Paso 2"
          subLabel="Dentro del equipo"
          active={isStep2}
        />
        <FlowNode
          icon={UserCheck}
          label="Asesor"
          sub="Motor auto-asigna"
          tone={isStep2 ? 'accent' : 'neutral'}
          highlight={isStep2}
        />
      </div>
    </div>
  )
}

function FlowNode({ icon: Icon, label, sub, tone = 'neutral', highlight = false }) {
  const isAccent = tone === 'accent'
  return (
    <div
      className={cn(
        'flex flex-col items-center text-center px-3 py-2.5 rounded-lg border transition-all min-w-[110px]',
        isAccent
          ? 'border-[var(--brand-primary)] bg-orange-50 shadow-sm'
          : 'border-gray-200 bg-white',
        highlight && 'ring-2 ring-[var(--brand-primary)] ring-offset-1'
      )}
    >
      <div
        className={cn(
          'w-9 h-9 rounded-full flex items-center justify-center mb-1.5',
          isAccent ? 'bg-[var(--brand-primary)] text-white' : 'bg-gray-100 text-gray-500'
        )}
      >
        <Icon size={16} />
      </div>
      <p className={cn('text-xs font-semibold leading-tight', isAccent ? 'text-gray-900' : 'text-gray-700')}>
        {label}
      </p>
      <p className="text-[10px] text-gray-400 mt-0.5 leading-tight">{sub}</p>
    </div>
  )
}

function FlowConnector({ stepLabel, subLabel, active }) {
  return (
    <div className="flex flex-col items-center px-1 sm:px-2 min-w-[80px]">
      <span
        className={cn(
          'text-[10px] uppercase tracking-wider font-bold mb-0.5',
          active ? 'text-[var(--brand-primary)]' : 'text-gray-400'
        )}
      >
        {stepLabel}
      </span>
      <ArrowRight
        size={20}
        className={cn(active ? 'text-[var(--brand-primary)]' : 'text-gray-300')}
      />
      <span className={cn('text-[10px] mt-0.5 leading-tight text-center', active ? 'text-gray-700 font-medium' : 'text-gray-400')}>
        {subLabel}
      </span>
    </div>
  )
}

/* ╔════════════════════════════════════════════════════════════════╗
   ║ TAB 1 — Entre supervisores (existente, sin cambios funcionales) ║
   ╚════════════════════════════════════════════════════════════════╝ */

const MODE_OPTIONS = [
  {
    value: 'rotacion',
    label: 'Rotación automática entre supervisores',
    hint:  'Cada lead nuevo se asigna al siguiente supervisor en turno. Reparto justo y parejo. El contador se reinicia cada día a medianoche.',
  },
  {
    value: 'fijo',
    label: 'Asignar todo a un supervisor específico',
    hint:  'Todos los leads entrantes se envían siempre al supervisor que elijas abajo.',
  },
]

function formatHora(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleTimeString('es-PE', {
      hour: '2-digit', minute: '2-digit', hour12: false,
    })
  } catch { return '—' }
}

function TabSupervisores() {
  const [items, setItems] = useState([])
  const [teamHealth, setTeamHealth] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [togglingId, setTogglingId] = useState(null)
  const [mode, setMode] = useState(null)
  const [fijoUserId, setFijoUserId] = useState('')
  const [savingMode, setSavingMode] = useState(false)
  // V087.1 — snapshot del modo guardado en backend para detectar cambios.
  const [savedMode, setSavedMode] = useState(null)
  const [savedFijoUserId, setSavedFijoUserId] = useState('')
  const [showPreview, setShowPreview] = useState(false)
  const { showUndoToast, showToast } = useUndoToast()

  const loadRotacion = useCallback(async () => {
    setLoading(true)
    try {
      const [rot, health] = await Promise.all([
        api.get('/api/ingest/rotacion'),
        api.get('/api/v1/team-health/').catch(() => ({ data: { teams: [] } })),
      ])
      setItems(rot.data?.items || [])
      setTeamHealth(health.data?.teams || [])
      setError(null)
    } catch (err) {
      setError(err.response?.data?.detail || 'Error cargando rotación')
    } finally {
      setLoading(false)
    }
  }, [])

  const loadMode = useCallback(async () => {
    try {
      const res = await api.get('/api/settings/ingest-mode')
      const m = res.data?.mode || 'rotacion'
      const f = res.data?.fijo_user_id || ''
      setMode(m)
      setFijoUserId(f)
      setSavedMode(m)
      setSavedFijoUserId(f)
    } catch {
      setMode(prev => prev ?? 'rotacion')
    }
  }, [])

  useEffect(() => {
    loadRotacion(); loadMode()
    const interval = setInterval(loadRotacion, REFRESH_MS)
    return () => clearInterval(interval)
  }, [loadRotacion, loadMode])

  // V087.1 — detectar si hay cambios efectivos antes de abrir el preview.
  const hasModeChange = mode !== savedMode || (mode === 'fijo' && fijoUserId !== savedFijoUserId)

  const requestSaveMode = () => {
    if (mode === 'fijo' && !fijoUserId) {
      alert('Selecciona un supervisor para el modo Fijo.')
      return
    }
    if (!hasModeChange) return
    setShowPreview(true)
  }

  const applySaveMode = async () => {
    setSavingMode(true)
    // Snapshot para poder ofrecer "Deshacer".
    const previousMode = savedMode
    const previousFijo = savedFijoUserId
    try {
      await api.put('/api/settings/ingest-mode', {
        mode, fijo_user_id: mode === 'fijo' ? fijoUserId : null,
      })
      setSavedMode(mode)
      setSavedFijoUserId(mode === 'fijo' ? fijoUserId : '')
      setShowPreview(false)

      // Toast con "Deshacer" — el admin tiene 8s para revertir si se confundio.
      // El undo reaplica el estado previo con el mismo endpoint (idempotente).
      showUndoToast({
        message: 'Modo de reparto actualizado.',
        onUndo: async () => {
          try {
            await api.put('/api/settings/ingest-mode', {
              mode: previousMode,
              fijo_user_id: previousMode === 'fijo' ? previousFijo : null,
            })
            setMode(previousMode)
            setFijoUserId(previousFijo || '')
            setSavedMode(previousMode)
            setSavedFijoUserId(previousFijo || '')
            showToast('Cambio revertido')
          } catch (err) {
            alert(err.response?.data?.detail || 'No se pudo revertir')
          }
        },
      })
    } catch (err) {
      alert(err.response?.data?.detail || 'Error guardando modo')
    } finally {
      setSavingMode(false)
    }
  }

  // Helpers de preview: describir el estado actual vs el siguiente en lenguaje natural.
  // Nota: `activos` y `totalHoy` se calculan abajo y se reusan en el preview.
  const fijoNombre = (uid) => items.find(s => s.supervisor_id === uid)?.supervisor_nombre || items.find(s => s.supervisor_id === uid)?.email || '—'

  const handleToggle = async (s) => {
    const next = !s.activo_rotacion
    setTogglingId(s.supervisor_id)
    try {
      await api.patch(`/api/ingest/rotacion/${s.supervisor_id}`, { activo_rotacion: next })
      setItems(prev => prev.map(x => x.supervisor_id === s.supervisor_id ? { ...x, activo_rotacion: next } : x))
    } catch (err) {
      alert(err.response?.data?.detail || 'Error actualizando rotación')
    } finally {
      setTogglingId(null)
    }
  }

  const totalHoy = items.reduce((acc, s) => acc + (s.contador || 0), 0)
  // V094.7 — un supervisor con login bloqueado esta saltado del round-robin
  // (V094.6 backend), aunque activo_rotacion sea TRUE. Lo descontamos del
  // KPI "Supervisores activos" para que el numero refleje cuantos realmente
  // participan del reparto.
  const activos = items.filter(s => s.activo_rotacion && !s.login_blocked).length

  // V087.1 — Adds/removes del preview (necesitan `activos` ya calculado).
  const previewAdds = []
  const previewRemoves = []
  if (savedMode === 'rotacion' && mode === 'fijo') {
    previewAdds.push({ label: `Todos los leads nuevos irán a ${fijoNombre(fijoUserId)}`, hint: 'Asignación única' })
    previewRemoves.push({ label: `Round-robin entre ${activos} supervisor${activos === 1 ? '' : 'es'} activo${activos === 1 ? '' : 's'}`, hint: 'Deja de distribuir' })
  } else if (savedMode === 'fijo' && mode === 'rotacion') {
    previewAdds.push({ label: `Round-robin entre ${activos} supervisor${activos === 1 ? '' : 'es'} activo${activos === 1 ? '' : 's'}`, hint: 'Distribución pareja' })
    previewRemoves.push({ label: `Asignación única a ${fijoNombre(savedFijoUserId)}`, hint: 'Deja de concentrar leads en una persona' })
  } else if (savedMode === 'fijo' && mode === 'fijo' && savedFijoUserId !== fijoUserId) {
    previewAdds.push({ label: `Los leads nuevos irán a ${fijoNombre(fijoUserId)}`, hint: 'Supervisor único' })
    previewRemoves.push({ label: `Antes iban a ${fijoNombre(savedFijoUserId)}`, hint: 'Reemplazo del supervisor único' })
  }

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <Button variant="outline" size="sm" onClick={() => { loadRotacion(); loadMode() }} disabled={loading}>
          <RefreshCw size={14} className={loading ? 'animate-spin mr-2' : 'mr-2'} /> Refrescar
        </Button>
      </div>

      {mode === null ? (
        <Card><CardContent className="p-6"><LoadingSpinner /></CardContent></Card>
      ) : (
        <Card>
          <CardHeader><CardTitle>¿Cómo se reparten los leads entrantes?</CardTitle></CardHeader>
          <CardContent className="space-y-3">
            <p className="text-xs text-gray-500">
              Aquí decides qué pasa con los leads que llegan automáticamente desde
              Facebook, TikTok y WhatsApp. Puedes cambiarlo cuando quieras.
            </p>
            <div className="space-y-2">
              {MODE_OPTIONS.map(opt => {
                const selected = mode === opt.value
                return (
                  <label key={opt.value}
                    className={cn(
                      'flex items-start gap-3 p-4 rounded-xl border-2 cursor-pointer transition-all',
                      selected ? 'border-[var(--brand-primary)] bg-orange-50 shadow-sm' : 'border-gray-200 hover:border-gray-300 bg-white'
                    )}
                  >
                    <input type="radio" name="ingest-mode" value={opt.value}
                      checked={selected} onChange={() => setMode(opt.value)} disabled={savingMode}
                      className="mt-0.5 accent-[var(--brand-primary)]"
                    />
                    <div className="flex-1">
                      <div className="text-sm font-bold text-gray-900">{opt.label}</div>
                      <div className="text-xs text-gray-500 mt-1 leading-relaxed">{opt.hint}</div>
                    </div>
                  </label>
                )
              })}
            </div>
            {mode === 'fijo' && (
              <div className="pt-1">
                <label className="text-xs text-gray-500 mb-1 block">¿A qué supervisor le enviamos todo?</label>
                <select value={fijoUserId} onChange={e => setFijoUserId(e.target.value)} disabled={savingMode}
                  className="bg-white border border-gray-300 rounded-lg px-3 py-2 text-sm text-gray-900 w-full focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  <option value="">— Selecciona supervisor —</option>
                  {/* V094.7 — el modo "Fijo" envia TODOS los leads a un solo supervisor;
                      no tiene sentido permitir elegir uno con login bloqueado porque
                      esos leads nunca se procesarian. */}
                  {items.filter(s => s.activo_rotacion && !s.login_blocked).map(s => (
                    <option key={s.supervisor_id} value={s.supervisor_id}>{s.supervisor_nombre || s.email}</option>
                  ))}
                </select>
              </div>
            )}
            <div className="flex justify-end pt-1">
              <Button onClick={requestSaveMode} disabled={savingMode || !hasModeChange}>
                {savingMode ? 'Guardando...' : hasModeChange ? 'Revisar y guardar' : 'Sin cambios'}
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* V087.1 — Preview de impacto del cambio de modo de reparto.
          Cambiar de rotación a supervisor único (o viceversa) es una decisión
          estructural — el admin tiene que verla descripta antes de aplicar. */}
      <ApplyChangesPreviewDialog
        open={showPreview}
        title="Confirmar cambio del reparto de leads"
        subtitle="Este cambio afecta a TODOS los leads entrantes desde ahora."
        adds={previewAdds}
        removes={previewRemoves}
        notes="El cambio aplica de inmediato a los próximos leads. Los ya asignados quedan como están."
        confirmLabel="Sí, aplicar este reparto"
        applying={savingMode}
        onConfirm={applySaveMode}
        onCancel={() => setShowPreview(false)}
      />

      <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
        <KpiSmall label="Leads asignados hoy" value={totalHoy} />
        <KpiSmall label="Supervisores activos" value={`${activos} / ${items.length}`} />
        <KpiSmall label="Auto-refresh" value="30s" />
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            Detalle por supervisor
            <Info
              size={14}
              className="text-gray-400 hover:text-gray-600 cursor-help"
              title={
                'Pausa MANUAL: tú decides si el supervisor entra al round-robin de leads entrantes.\n' +
                'Salud equipo: AUTOMÁTICO. Si la auto-asignación a asesores está activa y ningún asesor está disponible (todos pausados, ausentes o llenos), ' +
                'el sistema deja de enviar leads a ese equipo aunque el supervisor esté activo, y los redirige a otros equipos disponibles.'
              }
            />
          </CardTitle>
        </CardHeader>
        <CardContent>
          {loading && items.length === 0 ? <LoadingSpinner /> :
           error ? <div className="text-red-400 text-sm py-4">{error}</div> :
           items.length === 0 ? <EmptyState icon={Shuffle} title="Sin supervisores" description="No hay supervisores registrados." /> :
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left text-xs uppercase tracking-wide text-gray-500 border-b border-gray-200">
                    <th className="py-2 px-3">Supervisor</th>
                    <th className="py-2 px-3 text-center">Hoy</th>
                    <th className="py-2 px-3 text-center">Último lead</th>
                    <th className="py-2 px-3 text-center">Últ. actualización</th>
                    <th className="py-2 px-3 text-center">Pausa manual</th>
                    <th className="py-2 px-3 text-center">Salud equipo</th>
                    <th className="py-2 px-3 text-right">Acción</th>
                  </tr>
                </thead>
                <tbody>
                  {items.map(s => {
                    const team = teamHealth.find(t => t.supervisor_id === s.supervisor_id)
                    return (
                    <tr key={s.supervisor_id} className={`border-b border-gray-100 hover:bg-gray-50 transition-colors ${s.login_blocked ? 'bg-slate-50/50' : ''}`}>
                      <td className="py-3 px-3">
                        <div className="flex items-center gap-2">
                          <div>
                            <div className="font-medium text-gray-900">{s.supervisor_nombre || '—'}</div>
                            <div className="text-xs text-gray-400">{s.email}</div>
                          </div>
                          {/* V094.7 — badge para distinguir "saltado del round-robin
                              por login bloqueado" (V094.6) de "pausado manualmente"
                              (activo_rotacion=FALSE). Sin esto el admin se confundia
                              porque la columna "Pausa Manual" decia "Activo" aunque
                              el supervisor nunca iba a recibir leads. */}
                          {s.login_blocked && (
                            <span
                              title="Login bloqueado — este supervisor no recibe leads del round-robin aunque la pausa manual diga 'Activo'."
                              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium border border-slate-300 bg-slate-100 text-slate-600 whitespace-nowrap"
                            >
                              <Lock size={11} />
                              Login bloqueado
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="py-3 px-3 text-center">
                        <span className="inline-flex items-center justify-center min-w-[32px] px-2 py-0.5 rounded-full bg-[var(--brand-primary)]/15 text-[var(--brand-primary)] font-semibold">
                          {s.contador || 0}
                        </span>
                      </td>
                      <td className="py-3 px-3 text-center text-gray-700">{s.ultimo_lead_id ? `#${s.ultimo_lead_id}` : '—'}</td>
                      <td className="py-3 px-3 text-center text-gray-500 text-xs">{formatHora(s.updated_at)}</td>
                      <td className="py-3 px-3 text-center">
                        {/* V094.7 — si el login esta bloqueado, el estado efectivo es
                            "Saltado" independiente de activo_rotacion. Decimos la
                            verdad operativa, no el flag de la columna. */}
                        {s.login_blocked ? (
                          <span
                            title="El supervisor esta saltado del round-robin por login bloqueado, no por pausa manual."
                            className="inline-flex items-center gap-1 text-slate-500 text-xs font-medium"
                          >
                            <Lock size={14} /> Saltado
                          </span>
                        ) : s.activo_rotacion ? (
                          <span className="inline-flex items-center gap-1 text-emerald-500 text-xs font-medium"><CheckCircle2 size={14} /> Activo</span>
                        ) : (
                          <span className="inline-flex items-center gap-1 text-gray-400 text-xs font-medium"><XCircle size={14} /> Pausado</span>
                        )}
                      </td>
                      <td className="py-3 px-3 text-center">
                        {team ? <TeamHealthBadge team={team} /> : <span className="text-xs text-gray-300">—</span>}
                      </td>
                      <td className="py-3 px-3 text-right">
                        {/* V094.7 — no tiene sentido pausar manualmente a alguien que
                            ya esta saltado por login bloqueado. Deshabilitamos el
                            boton con un tooltip que dirige al admin a la accion
                            correcta (Usuarios -> Desbloquear inicio de sesion). */}
                        <Button size="sm" variant={s.activo_rotacion ? 'outline' : 'default'}
                          disabled={togglingId === s.supervisor_id || s.login_blocked}
                          title={s.login_blocked
                            ? 'Login bloqueado. Para reactivarlo, desbloquea el inicio de sesion desde Configuracion > Usuarios.'
                            : undefined}
                          onClick={() => handleToggle(s)}
                        >
                          {togglingId === s.supervisor_id ? '...' : s.activo_rotacion ? 'Pausar' : 'Reanudar'}
                        </Button>
                      </td>
                    </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>}
        </CardContent>
      </Card>
    </div>
  )
}

function KpiSmall({ label, value }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-xs text-gray-500 uppercase tracking-wide">{label}</p>
        <p className="text-2xl font-bold text-gray-900 mt-1">{value}</p>
      </CardContent>
    </Card>
  )
}

/* ╔════════════════════════════════════════════════════════════════╗
   ║ TAB 2 — Del supervisor al asesor (motor de auto-asignacion)    ║
   ╚════════════════════════════════════════════════════════════════╝ */

const FALLBACK_HORARIO = [
  { v: 'asignar_igual',       label: 'Asignar de inmediato (ignorar el horario)',
    hint: 'El motor reparte el lead apenas entra. El asesor recibirá la notificación aunque sea fuera de horario.' },
  { v: 'cola_proximo_dia',    label: 'Esperar al próximo horario y asignar automáticamente',
    hint: 'El lead queda en cola; el sistema lo asigna automáticamente cuando vuelva al horario laboral (revisa cada 15 min).' },
  { v: 'asignar_supervisor',  label: 'Dejar al supervisor para que lo asigne manualmente',
    hint: 'El lead queda en la bandeja del supervisor. No se intenta auto-asignar después.' },
]
const FALLBACK_SIN_DISP = [
  { v: 'asignar_supervisor',  label: 'Dejar al supervisor para asignar manualmente' },
  { v: 'asignar_admin',       label: 'Asignar a un administrador del CRM' },
  { v: 'cola_pendiente',      label: 'Dejar en cola pendiente (reintenta cada 15 min)' },
  { v: 'ignorar_capacity',    label: 'Forzar asignación ignorando los límites de capacity' },
]
const CAPACITY_DEF = [
  { v: 'todos_activos',     label: 'Todos los leads activos no terminales' },
  { v: 'sin_contacto_48h',  label: 'Solo leads sin contacto en 48h' },
]

function TabAutoAsignacion() {
  const [config, setConfig] = useState(null)
  const [equipos, setEquipos] = useState([])
  const [teamHealth, setTeamHealth] = useState([])
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [togglingTeam, setTogglingTeam] = useState(null)
  const [error, setError] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [cfg, eq, health] = await Promise.all([
        api.get('/api/admin/assignment/config'),
        api.get('/api/admin/assignment/equipos'),
        api.get('/api/v1/team-health/').catch(() => ({ data: { teams: [] } })),
      ])
      setConfig(cfg.data); setEquipos(eq.data || [])
      setTeamHealth(health.data?.teams || [])
      setError(null)
    } catch (err) {
      setError(err.response?.data?.detail || 'Error cargando configuración')
    } finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  const update = (k, v) => setConfig(prev => ({ ...prev, [k]: v }))

  const save = async () => {
    setSaving(true)
    try {
      await api.patch('/api/admin/assignment/config', {
        auto_asignar_enabled:        config.auto_asignar_enabled,
        estrategia_default:          config.estrategia_default,
        max_leads_abiertos_default:  parseInt(config.max_leads_abiertos_default) || 50,
        horario_inicio:              config.horario_inicio || null,
        horario_fin:                 config.horario_fin || null,
        estrategia_fuera_horario:    config.estrategia_fuera_horario,
        estrategia_sin_disponibles:  config.estrategia_sin_disponibles,
        capacity_definicion:         config.capacity_definicion,
        notificar_supervisor_auto:   config.notificar_supervisor_auto,
        incluir_supervisor_en_rotacion: config.incluir_supervisor_en_rotacion,
      })
      await load()
    } catch (err) {
      alert(err.response?.data?.detail || 'Error guardando')
    } finally { setSaving(false) }
  }

  const toggleEquipo = async (e) => {
    setTogglingTeam(e.supervisor_id)
    try {
      await api.patch(`/api/admin/assignment/equipos/${e.supervisor_id}`, {
        auto_asignar_enabled: !e.auto_asignar_enabled,
      })
      setEquipos(prev => prev.map(x => x.supervisor_id === e.supervisor_id
        ? { ...x, auto_asignar_enabled: !x.auto_asignar_enabled } : x))
    } catch (err) {
      alert(err.response?.data?.detail || 'Error')
    } finally { setTogglingTeam(null) }
  }

  if (loading || !config) return <LoadingSpinner />
  if (error) return <div className="text-red-500 text-sm">{error}</div>

  const activeTeams = equipos.filter(e => e.auto_asignar_enabled).length

  return (
    <div className="space-y-4">
      {/* Master switch */}
      <Card className={cn(
        'border-2',
        config.auto_asignar_enabled ? 'border-emerald-300 bg-emerald-50/30' : 'border-gray-200'
      )}>
        <CardContent className="p-5">
          <div className="flex items-start gap-4">
            <div className={cn(
              'w-11 h-11 rounded-xl flex items-center justify-center shrink-0',
              config.auto_asignar_enabled ? 'bg-emerald-100 text-emerald-700' : 'bg-gray-100 text-gray-500'
            )}>
              <Sparkles size={20} />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="text-base font-semibold text-gray-900">Auto-asignación al asesor</h3>
                {config.auto_asignar_enabled
                  ? <span className="text-[10px] bg-emerald-100 text-emerald-700 border border-emerald-200 px-1.5 py-0.5 rounded font-semibold">ACTIVA</span>
                  : <span className="text-[10px] bg-gray-100 text-gray-600 border border-gray-200 px-1.5 py-0.5 rounded font-semibold">DESACTIVADA</span>
                }
              </div>
              <p className="text-xs text-gray-500 mt-0.5 leading-relaxed">
                Cuando un lead llega al supervisor, el sistema lo reparte automáticamente
                al asesor del equipo según las reglas que configures abajo. El supervisor
                queda más libre y puede dedicarse a supervisar.
              </p>
            </div>
            <Switch checked={config.auto_asignar_enabled} onChange={v => update('auto_asignar_enabled', v)} />
          </div>
        </CardContent>
      </Card>

      {config.auto_asignar_enabled && (
        <>
          {/* Estrategia default */}
          <Card>
            <CardHeader><CardTitle className="text-sm">Estrategia por defecto</CardTitle></CardHeader>
            <CardContent className="space-y-3">
              <p className="text-xs text-gray-500">
                Qué hace el motor cuando ninguna regla avanzada matchea. Recomendado: round-robin del equipo.
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
                <label className={cn(
                  'flex items-start gap-2 p-3 rounded-lg border cursor-pointer transition',
                  config.estrategia_default === 'round_robin_equipo'
                    ? 'border-indigo-300 bg-indigo-50'
                    : 'border-gray-200 hover:border-gray-300'
                )}>
                  <input type="radio" checked={config.estrategia_default === 'round_robin_equipo'}
                    onChange={() => update('estrategia_default', 'round_robin_equipo')}
                    className="mt-0.5 accent-indigo-600" />
                  <div>
                    <div className="text-sm font-semibold text-gray-800">Por carga</div>
                    <div className="text-[11px] text-gray-500 mt-0.5">El asesor con menos leads del día gana. Compensa ausencias automáticamente.</div>
                  </div>
                </label>
                <label className={cn(
                  'flex items-start gap-2 p-3 rounded-lg border cursor-pointer transition',
                  config.estrategia_default === 'round_robin_orden'
                    ? 'border-indigo-300 bg-indigo-50'
                    : 'border-gray-200 hover:border-gray-300'
                )}>
                  <input type="radio" checked={config.estrategia_default === 'round_robin_orden'}
                    onChange={() => update('estrategia_default', 'round_robin_orden')}
                    className="mt-0.5 accent-indigo-600" />
                  <div>
                    <div className="text-sm font-semibold text-gray-800">Por orden</div>
                    <div className="text-[11px] text-gray-500 mt-0.5">Sigue la jerarquía 1-2-3-4 que el supervisor configura. Respeta cap.</div>
                  </div>
                </label>
                <label className={cn(
                  'flex items-start gap-2 p-3 rounded-lg border cursor-pointer transition',
                  config.estrategia_default === 'round_robin_orden_estricto'
                    ? 'border-amber-300 bg-amber-50'
                    : 'border-gray-200 hover:border-gray-300'
                )}>
                  <input type="radio" checked={config.estrategia_default === 'round_robin_orden_estricto'}
                    onChange={() => update('estrategia_default', 'round_robin_orden_estricto')}
                    className="mt-0.5 accent-amber-600" />
                  <div>
                    <div className="text-sm font-semibold text-gray-800 flex items-center gap-1">
                      Por orden estricto
                      <span className="text-[9px] font-medium text-amber-700 bg-amber-100 rounded px-1 py-0.5">SIN CAP</span>
                    </div>
                    <div className="text-[11px] text-gray-500 mt-0.5">Igual que "por orden" pero ignora capacidad. El primero recibe aunque tenga 200 leads abiertos.</div>
                  </div>
                </label>
                <label className={cn(
                  'flex items-start gap-2 p-3 rounded-lg border cursor-pointer transition',
                  config.estrategia_default === 'round_robin_balanceado'
                    ? 'border-emerald-300 bg-emerald-50'
                    : 'border-gray-200 hover:border-gray-300'
                )}>
                  <input type="radio" checked={config.estrategia_default === 'round_robin_balanceado'}
                    onChange={() => update('estrategia_default', 'round_robin_balanceado')}
                    className="mt-0.5 accent-emerald-600" />
                  <div>
                    <div className="text-sm font-semibold text-gray-800 flex items-center gap-1">
                      Balanceado 7d
                      <span className="text-[9px] font-medium text-emerald-700 bg-emerald-100 rounded px-1 py-0.5">JUSTO</span>
                    </div>
                    <div className="text-[11px] text-gray-500 mt-0.5">Compensa skips: el que menos recibió en últimos 7 días gana. Empate → orden manual.</div>
                  </div>
                </label>
                <label className={cn(
                  'flex items-start gap-2 p-3 rounded-lg border cursor-pointer transition',
                  config.estrategia_default === 'manual'
                    ? 'border-indigo-300 bg-indigo-50'
                    : 'border-gray-200 hover:border-gray-300'
                )}>
                  <input type="radio" checked={config.estrategia_default === 'manual'}
                    onChange={() => update('estrategia_default', 'manual')}
                    className="mt-0.5 accent-indigo-600" />
                  <div>
                    <div className="text-sm font-semibold text-gray-800">Manual</div>
                    <div className="text-[11px] text-gray-500 mt-0.5">Solo aplica reglas explícitas. Si ninguna matchea, deja al supervisor.</div>
                  </div>
                </label>
              </div>

              {/* V057: Hint cuando usa "por orden" — el modo orden puro
                  puede dejar al ultimo de la jerarquia con menos leads
                  si el volumen diario < cantidad de asesores. El modo
                  balanceado compensa eso con la ventana de 7 dias. */}
              {config.estrategia_default === 'round_robin_orden' && (
                <div className="mt-3 flex items-start gap-2 bg-emerald-50 border border-emerald-200 rounded-lg px-3 py-2.5 text-[11px] text-emerald-800">
                  <span className="text-base leading-none mt-0.5">💡</span>
                  <div>
                    <strong>Tip de balance:</strong> si tu equipo recibe menos leads
                    al día que cantidad de asesores tiene (por ejemplo 7 leads / 8
                    asesores), el último de la jerarquía puede acumular menos leads
                    a la larga. Considerá <button
                      type="button"
                      onClick={() => update('estrategia_default', 'round_robin_balanceado')}
                      className="underline font-semibold hover:text-emerald-900"
                    >cambiar a Balanceado 7d</button> para
                    compensar automáticamente.
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Capacity + horario */}
          <Card>
            <CardHeader><CardTitle className="text-sm">Capacity y horario</CardTitle></CardHeader>
            <CardContent className="space-y-4">
              <div>
                <Label className="text-xs">Definición de "lead abierto"</Label>
                <select value={config.capacity_definicion}
                  onChange={e => update('capacity_definicion', e.target.value)}
                  className="w-full mt-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:ring-2 focus:ring-indigo-500"
                >
                  {CAPACITY_DEF.map(o => <option key={o.v} value={o.v}>{o.label}</option>)}
                </select>
                <p className="text-[10px] text-gray-400 mt-1">
                  Define qué leads se cuentan en el "máximo abiertos por asesor".
                </p>
              </div>
              <div>
                <Label className="text-xs">Máximo de leads abiertos por asesor (default global)</Label>
                <Input type="number" min="1" max="500" value={config.max_leads_abiertos_default}
                  onChange={e => update('max_leads_abiertos_default', e.target.value)} className="mt-1" />
                <p className="text-[10px] text-gray-400 mt-1">
                  Cada asesor puede tener un valor individual en el tab "Asesores" que sobrescribe este.
                </p>
              </div>

              <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                <div>
                  <Label className="text-xs flex items-center gap-1"><Clock size={11} /> Horario laboral inicio</Label>
                  <Input type="time" value={config.horario_inicio || ''}
                    onChange={e => update('horario_inicio', e.target.value)} className="mt-1" />
                </div>
                <div>
                  <Label className="text-xs flex items-center gap-1"><Clock size={11} /> Horario laboral fin</Label>
                  <Input type="time" value={config.horario_fin || ''}
                    onChange={e => update('horario_fin', e.target.value)} className="mt-1" />
                </div>
              </div>
              <div>
                <Label className="text-xs">Si un lead llega fuera del horario laboral</Label>
                <select value={config.estrategia_fuera_horario}
                  onChange={e => update('estrategia_fuera_horario', e.target.value)}
                  className="w-full mt-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:ring-2 focus:ring-indigo-500"
                >
                  {FALLBACK_HORARIO.map(o => <option key={o.v} value={o.v}>{o.label}</option>)}
                </select>
                {(() => {
                  const opt = FALLBACK_HORARIO.find(o => o.v === config.estrategia_fuera_horario)
                  return opt?.hint && (
                    <p className="text-[10px] text-gray-500 mt-1 leading-relaxed bg-indigo-50/50 border border-indigo-100 rounded p-2">
                      {opt.hint}
                    </p>
                  )
                })()}
              </div>
              <div>
                <Label className="text-xs">Si todos los asesores están sin disponibilidad o llenos</Label>
                <select value={config.estrategia_sin_disponibles}
                  onChange={e => update('estrategia_sin_disponibles', e.target.value)}
                  className="w-full mt-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:ring-2 focus:ring-indigo-500"
                >
                  {FALLBACK_SIN_DISP.map(o => <option key={o.v} value={o.v}>{o.label}</option>)}
                </select>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={config.notificar_supervisor_auto}
                  onChange={e => update('notificar_supervisor_auto', e.target.checked)}
                  className="rounded" />
                <span className="text-gray-700">Notificar al supervisor cada vez que el motor asigne uno de sus leads</span>
              </label>
              <div className="pt-2 border-t border-gray-100">
                <label className="flex items-center gap-2 text-sm">
                  <input type="checkbox" checked={!!config.incluir_supervisor_en_rotacion}
                    onChange={e => update('incluir_supervisor_en_rotacion', e.target.checked)}
                    className="rounded text-indigo-600 focus:ring-indigo-500" />
                  <span className="text-gray-800 font-medium">Incluir al supervisor en la rotación del equipo</span>
                </label>
                <p className="text-[11px] text-gray-500 pl-6 mt-0.5">
                  Cuando está activo, el supervisor también participará como un candidato más en la rotación automática junto con sus asesores.
                </p>
              </div>
            </CardContent>
          </Card>

          {/* Toggle por equipo (auto-asignacion intra-equipo) */}
          <Card>
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <Users size={14} /> Auto-asignar al asesor (por equipo)
                <span className="text-[10px] bg-indigo-50 text-indigo-700 border border-indigo-200 px-1.5 py-0.5 rounded">
                  {activeTeams} de {equipos.length} activos
                </span>
                <Info
                  size={14}
                  className="text-gray-400 hover:text-gray-600 cursor-help"
                  title={
                    'Este toggle decide qué hace el sistema cuando un supervisor recibe un lead nuevo:\n' +
                    '  • ON  → el motor reparte el lead al asesor del equipo automáticamente.\n' +
                    '  • OFF → el lead se queda en la bandeja del supervisor para asignar manualmente.\n\n' +
                    'NO es lo mismo que "Pausar supervisor" del tab anterior:\n' +
                    '  • Pausar supervisor → el supervisor NO recibe leads (queda fuera del round-robin).\n' +
                    '  • Auto-asignar al asesor → el supervisor SI recibe, pero controla si el motor reparte solo.\n\n' +
                    'El badge "Bloqueado" significa que el sistema pausó el equipo automáticamente porque no tiene asesores disponibles para recibir leads (todos están pausados, ausentes o llenos).'
                  }
                />
              </CardTitle>
            </CardHeader>
            <CardContent>
              <p className="text-xs text-gray-500 mb-3">
                Activa la auto-asignación equipo por equipo. Permite probar gradualmente sin
                afectar a todos a la vez. Si está desactivado, los leads llegan al supervisor y los reparte manualmente.
              </p>
              <div className="space-y-2">
                {equipos.map(e => {
                  const team = teamHealth.find(t => t.supervisor_id === e.supervisor_id)
                  return (
                  <div key={e.supervisor_id} className="flex items-center gap-3 p-3 rounded-lg border border-gray-100 bg-white hover:border-gray-200 transition">
                    <div className="w-9 h-9 rounded-full bg-purple-50 text-purple-600 flex items-center justify-center text-sm font-semibold shrink-0">
                      {(e.supervisor_nombre || '?')[0]?.toUpperCase()}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <p className="text-sm font-medium text-gray-800 truncate">Equipo de {e.supervisor_nombre || '—'}</p>
                        {team && <TeamHealthBadge team={team} />}
                      </div>
                      <p className="text-[11px] text-gray-400">
                        {e.num_asesores || 0} asesor{e.num_asesores === 1 ? '' : 'es'} ·{' '}
                        {e.activo_rotacion ? 'recibe leads' : 'pausado en rotación'}
                      </p>
                    </div>
                    <Switch
                      checked={!!e.auto_asignar_enabled}
                      disabled={togglingTeam === e.supervisor_id}
                      onChange={() => toggleEquipo(e)}
                    />
                  </div>
                  )
                })}
                {equipos.length === 0 && (
                  <p className="text-sm text-gray-400 text-center py-6">No hay supervisores configurados.</p>
                )}
              </div>
            </CardContent>
          </Card>
        </>
      )}

      <div className="flex justify-end gap-2 sticky bottom-0 bg-gradient-to-t from-white via-white to-transparent py-3">
        <Button onClick={save} disabled={saving} className="gap-1.5 shadow-lg">
          <Save size={14} /> {saving ? 'Guardando...' : 'Guardar configuración'}
        </Button>
      </div>
    </div>
  )
}

function Switch({ checked, onChange, disabled }) {
  return (
    <button type="button" disabled={disabled} onClick={() => !disabled && onChange(!checked)}
      className={cn(
        'relative inline-flex h-6 w-11 items-center rounded-full transition-colors',
        checked ? 'bg-emerald-500' : 'bg-gray-300',
        disabled && 'opacity-50 cursor-not-allowed'
      )}
    >
      <span className={cn(
        'inline-block h-4 w-4 transform rounded-full bg-white transition',
        checked ? 'translate-x-6' : 'translate-x-1'
      )} />
    </button>
  )
}

/* ╔════════════════════════════════════════════════════════════════╗
   ║ TAB 3 — Reglas avanzadas                                        ║
   ╚════════════════════════════════════════════════════════════════╝ */

function TabReglas() {
  const [rules, setRules] = useState([])
  const [fuentes, setFuentes] = useState([])
  const [apiClients, setApiClients] = useState([])
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState(null)
  const [confirmDel, setConfirmDel] = useState(null)
  const [confirmApply, setConfirmApply] = useState(null)
  const [applyingRule, setApplyingRule] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [r, f, ac, u] = await Promise.all([
        api.get('/api/admin/assignment/rules'),
        api.get('/api/fuentes'),
        api.get('/api/admin/api-clients').catch(() => ({ data: [] })),
        api.get('/auth/users'),
      ])
      setRules(r.data || [])
      setFuentes(f.data || [])
      setApiClients(ac.data || [])
      setUsers((u.data || []).filter(x => x.is_active && ['asesor','supervisor'].includes(x.role)))
    } finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  const move = async (idx, delta) => {
    const j = idx + delta
    if (j < 0 || j >= rules.length) return
    const next = [...rules]
    ;[next[idx], next[j]] = [next[j], next[idx]]
    setRules(next)
    await api.post('/api/admin/assignment/rules/reorder', { orden: next.map(r => r.id) })
  }

  const del = async () => {
    if (!confirmDel) return
    try {
      await api.delete(`/api/admin/assignment/rules/${confirmDel.id}`)
      setConfirmDel(null); load()
    } catch (err) { alert(err.response?.data?.detail || 'Error') }
  }

  const applyRuleToUnassigned = async () => {
    if (!confirmApply) return
    setApplyingRule(true)
    try {
      const res = await api.post(`/api/admin/assignment/rules/${confirmApply.id}/apply-unassigned`)
      alert(res.data?.message || 'Proceso completado')
      setConfirmApply(null)
      load()
    } catch (err) {
      alert(err.response?.data?.detail || 'Error al aplicar regla a los leads sin asignar')
    } finally {
      setApplyingRule(false)
    }
  }

  if (loading) return <LoadingSpinner />

  return (
    <div className="space-y-4">
      <div className="flex justify-between items-start">
        <div>
          <p className="text-sm text-gray-600 max-w-2xl">
            Las reglas se evalúan en orden de prioridad. La primera que matchee
            decide a quién se asigna el lead. Si ninguna matchea, se aplica la
            estrategia por defecto.
          </p>
        </div>
        <Button onClick={() => { setEditing(null); setShowForm(true) }} className="gap-1.5 shrink-0">
          <Plus size={14} /> Nueva regla
        </Button>
      </div>

      <Card>
        <CardContent className="p-0">
          {rules.length === 0 ? (
            <div className="p-12 text-center">
              <Layers size={36} className="mx-auto text-gray-300 mb-2" />
              <p className="text-sm text-gray-500 mb-3">No hay reglas configuradas todavía.</p>
              <Button size="sm" onClick={() => { setEditing(null); setShowForm(true) }} className="gap-1.5">
                <Plus size={14} /> Crear primera regla
              </Button>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-100">
                    <th className="w-10 px-2 py-3"></th>
                    <th className="text-left px-3 py-3 text-xs font-semibold text-gray-500 uppercase">Regla</th>
                    <th className="text-left px-3 py-3 text-xs font-semibold text-gray-500 uppercase">Cuándo</th>
                    <th className="text-left px-3 py-3 text-xs font-semibold text-gray-500 uppercase">Asigna a</th>
                    <th className="text-left px-3 py-3 text-xs font-semibold text-gray-500 uppercase">Aplicada</th>
                    <th className="text-left px-3 py-3 text-xs font-semibold text-gray-500 uppercase">Estado</th>
                    <th className="px-3 py-3"></th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {rules.map((r, idx) => (
                    <tr key={r.id} className={cn('hover:bg-gray-50', !r.activo && 'opacity-60')}>
                      <td className="px-2 py-3 text-center">
                        <div className="flex flex-col gap-0.5">
                          <button onClick={() => move(idx, -1)} disabled={idx === 0}
                            className="p-0.5 rounded hover:bg-gray-200 disabled:opacity-30">
                            <ArrowUp size={12} />
                          </button>
                          <button onClick={() => move(idx, +1)} disabled={idx === rules.length - 1}
                            className="p-0.5 rounded hover:bg-gray-200 disabled:opacity-30">
                            <ArrowDown size={12} />
                          </button>
                        </div>
                      </td>
                      <td className="px-3 py-3">
                        <div className="flex items-center gap-2">
                          <span className="text-[10px] font-mono bg-gray-100 px-1.5 py-0.5 rounded text-gray-600">#{r.prioridad}</span>
                          <div className="min-w-0">
                            <p className="font-medium text-gray-800 truncate">{r.nombre}</p>
                            {r.descripcion && <p className="text-[10px] text-gray-400 truncate">{r.descripcion}</p>}
                          </div>
                        </div>
                      </td>
                      <td className="px-3 py-3 text-xs text-gray-600">
                        <RuleConditionBadges r={r} />
                      </td>
                      <td className="px-3 py-3 text-xs text-gray-700">
                        <RuleTargetBadge r={r} />
                      </td>
                      <td className="px-3 py-3 text-xs text-gray-600">
                        <span className="font-semibold">{r.total_aplicaciones || 0}</span>
                        {r.ultima_aplicacion && (
                          <span className="text-[10px] text-gray-400 block">{formatRelativeTime(r.ultima_aplicacion)}</span>
                        )}
                      </td>
                      <td className="px-3 py-3">
                        {r.activo
                          ? <span className="text-[10px] bg-emerald-50 text-emerald-700 border border-emerald-200 px-1.5 py-0.5 rounded font-semibold">ACTIVA</span>
                          : <span className="text-[10px] bg-gray-50 text-gray-600 border border-gray-200 px-1.5 py-0.5 rounded font-semibold">INACTIVA</span>}
                      </td>
                      <td className="px-3 py-3 text-right whitespace-nowrap">
                        <button
                          onClick={() => setConfirmApply(r)}
                          disabled={!r.activo || applyingRule}
                          className="p-1.5 rounded hover:bg-emerald-50 text-gray-400 hover:text-emerald-600 disabled:opacity-30 mr-1"
                          title="Asignar leads sin asignar con esta regla"
                        >
                          <UserPlus size={13} />
                        </button>
                        <button onClick={() => { setEditing(r); setShowForm(true) }} className="p-1.5 rounded hover:bg-indigo-50 text-gray-400 hover:text-indigo-500" title="Editar"><Edit2 size={13} /></button>
                        <button onClick={() => setConfirmDel(r)} className="p-1.5 rounded hover:bg-red-50 text-gray-400 hover:text-red-500" title="Eliminar"><Trash2 size={13} /></button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {showForm && (
        <RuleFormModal
          editing={editing}
          fuentes={fuentes}
          apiClients={apiClients}
          users={users}
          onClose={() => { setShowForm(false); setEditing(null) }}
          onSaved={() => { setShowForm(false); setEditing(null); load() }}
        />
      )}
      <ConfirmDialog open={!!confirmDel}
        title="Eliminar regla"
        message={confirmDel ? `¿Eliminar la regla "${confirmDel.nombre}"? Esta acción no se puede deshacer.` : ''}
        onConfirm={del} onCancel={() => setConfirmDel(null)} />

      <ConfirmDialog open={!!confirmApply}
        title="Asignar leads sin asignar con esta regla"
        message={confirmApply ? `¿Deseas evaluar y asignar los leads sin asesor asignado que cumplan con la regla "${confirmApply.nombre}"?` : ''}
        confirmLabel={applyingRule ? "Asignando..." : "Asignar leads"}
        variant="warning"
        onConfirm={applyRuleToUnassigned} onCancel={() => setConfirmApply(null)} />
    </div>
  )
}

function RuleConditionBadges({ r }) {
  const badges = []
  if (r.fuente_nombre) badges.push({ label: r.fuente_nombre, color: 'sky' })
  if (r.api_client_nombre) badges.push({ label: r.api_client_nombre, color: 'violet' })
  if (r.campana_pattern) badges.push({ label: `campaña: ${r.campana_pattern}`, color: 'amber' })
  if (r.campana_exclude_pattern) badges.push({ label: `excluye: ${r.campana_exclude_pattern}`, color: 'rose' })
  if (r.palabras_clave?.length) badges.push({ label: `palabras: ${r.palabras_clave.length}`, color: 'rose' })
  if (r.horario_inicio && r.horario_fin) badges.push({ label: `${r.horario_inicio}-${r.horario_fin}`, color: 'emerald' })
  if (badges.length === 0) return <span className="text-gray-400">Cualquier lead</span>
  const colorMap = {
    sky: 'bg-sky-50 text-sky-700 border-sky-200',
    violet: 'bg-violet-50 text-violet-700 border-violet-200',
    amber: 'bg-amber-50 text-amber-700 border-amber-200',
    rose: 'bg-rose-50 text-rose-700 border-rose-200',
    emerald: 'bg-emerald-50 text-emerald-700 border-emerald-200',
  }
  return (
    <div className="flex flex-wrap gap-1">
      {badges.map((b, i) => (
        <span key={i} className={cn('text-[10px] px-1.5 py-0.5 rounded border', colorMap[b.color])}>{b.label}</span>
      ))}
    </div>
  )
}

function RuleTargetBadge({ r }) {
  if (r.asignar_a_tipo === 'asesor_especifico') {
    return <span className="inline-flex items-center gap-1"><User size={11} /> {r.target_nombre || '—'}</span>
  }
  if (r.asignar_a_tipo === 'equipo_round_robin') {
    return <span className="inline-flex items-center gap-1"><Users size={11} className="text-purple-500" /> Equipo de {r.target_nombre || '—'}</span>
  }
  return <span className="inline-flex items-center gap-1"><Shuffle size={11} /> Round-robin global</span>
}

function RuleFormModal({ editing, fuentes, apiClients, users, onClose, onSaved }) {
  // V088 — excluye supervisores deshabilitados del selector.
  const supervisores = users.filter(u => u.role === 'supervisor' && u.is_active !== false)
  const [form, setForm] = useState(() => ({
    nombre:                  editing?.nombre || '',
    descripcion:             editing?.descripcion || '',
    prioridad:               editing?.prioridad ?? (10),
    activo:                  editing?.activo ?? true,
    fuente_id:               editing?.fuente_id || '',
    api_client_id:           editing?.api_client_id || '',
    campana_pattern:         editing?.campana_pattern || '',
    campana_exclude_pattern: editing?.campana_exclude_pattern || '',
    palabras_clave:          (editing?.palabras_clave || []).join(', '),
    horario_inicio:          editing?.horario_inicio || '',
    horario_fin:             editing?.horario_fin || '',
    asignar_a_tipo:          editing?.asignar_a_tipo || 'equipo_round_robin',
    asignar_a_id:            editing?.asignar_a_id || '',
    fallback_si_lleno:       editing?.fallback_si_lleno || 'siguiente_regla',
  }))
  const [saving, setSaving] = useState(false)

  const submit = async () => {
    if (!form.nombre.trim()) return alert('Nombre requerido')
    if (form.asignar_a_tipo !== 'asesor_round_robin_global' && !form.asignar_a_id) {
      return alert('Selecciona el target (asesor o supervisor)')
    }
    setSaving(true)
    const payload = {
      nombre: form.nombre,
      descripcion: form.descripcion || null,
      prioridad: parseInt(form.prioridad) || 10,
      activo: form.activo,
      fuente_id: form.fuente_id ? parseInt(form.fuente_id) : null,
      api_client_id: form.api_client_id || null,
      campana_pattern: form.campana_pattern || null,
      campana_exclude_pattern: form.campana_exclude_pattern || null,
      palabras_clave: form.palabras_clave
        ? form.palabras_clave.split(',').map(s => s.trim()).filter(Boolean)
        : null,
      horario_inicio: form.horario_inicio || null,
      horario_fin: form.horario_fin || null,
      asignar_a_tipo: form.asignar_a_tipo,
      asignar_a_id: form.asignar_a_id || null,
      fallback_si_lleno: form.fallback_si_lleno,
    }
    try {
      if (editing) await api.patch(`/api/admin/assignment/rules/${editing.id}`, payload)
      else await api.post('/api/admin/assignment/rules', payload)
      onSaved()
    } catch (err) {
      alert(err.response?.data?.detail || 'Error guardando')
    } finally { setSaving(false) }
  }

  const targetOptions = useMemo(() => {
    if (form.asignar_a_tipo === 'asesor_especifico') return users
    if (form.asignar_a_tipo === 'equipo_round_robin') return supervisores
    return []
  }, [form.asignar_a_tipo, users, supervisores])

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-start sm:items-center justify-center p-4 overflow-y-auto" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-2xl my-auto flex flex-col max-h-[90vh]" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 pt-5 pb-3 border-b border-gray-100 shrink-0">
          <h3 className="text-base font-semibold text-gray-900 flex items-center gap-2">
            <Layers size={16} className="text-indigo-500" />
            {editing ? `Editar regla: ${editing.nombre}` : 'Nueva regla de asignación'}
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><XIcon size={16} /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          <div className="grid grid-cols-3 gap-3">
            <div className="col-span-2">
              <Label className="text-xs">Nombre <span className="text-red-500">*</span></Label>
              <Input value={form.nombre} onChange={e => setForm(p => ({ ...p, nombre: e.target.value }))}
                placeholder="Ej: Leads de Inmuebles24 → Carlos" className="mt-1" />
            </div>
            <div>
              <Label className="text-xs">Prioridad</Label>
              <Input type="number" min="1" max="999" value={form.prioridad}
                onChange={e => setForm(p => ({ ...p, prioridad: e.target.value }))} className="mt-1" />
            </div>
          </div>
          <div>
            <Label className="text-xs">Descripción</Label>
            <Input value={form.descripcion} onChange={e => setForm(p => ({ ...p, descripcion: e.target.value }))}
              placeholder="Opcional" className="mt-1" />
          </div>

          <FieldsetCard title="Cuándo aplicar (todas deben matchear)">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-xs">Fuente</Label>
                <select value={form.fuente_id} onChange={e => setForm(p => ({ ...p, fuente_id: e.target.value }))}
                  className="w-full mt-1 text-sm border border-gray-200 rounded-md px-2 py-1.5">
                  <option value="">— Cualquiera —</option>
                  {fuentes.map(f => <option key={f.id} value={f.id}>{f.nombre}</option>)}
                </select>
              </div>
              <div>
                <Label className="text-xs">Proveedor API</Label>
                <select value={form.api_client_id} onChange={e => setForm(p => ({ ...p, api_client_id: e.target.value }))}
                  className="w-full mt-1 text-sm border border-gray-200 rounded-md px-2 py-1.5">
                  <option value="">— Cualquiera —</option>
                  {apiClients.map(c => <option key={c.id} value={c.id}>{c.nombre}</option>)}
                </select>
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-xs">Patrones a incluir (separados por coma)</Label>
                <Input value={form.campana_pattern} onChange={e => setForm(p => ({ ...p, campana_pattern: e.target.value }))}
                  placeholder="ej: %virtual%, %online%" className="mt-1 font-mono text-xs" />
              </div>
              <div>
                <Label className="text-xs">Patrones a excluir (separados por coma)</Label>
                <Input value={form.campana_exclude_pattern} onChange={e => setForm(p => ({ ...p, campana_exclude_pattern: e.target.value }))}
                  placeholder="ej: %presencial%, %hibrido%" className="mt-1 font-mono text-xs text-red-600" />
              </div>
            </div>
            <div>
              <Label className="text-xs">Palabras clave en observaciones (separadas por coma)</Label>
              <Input value={form.palabras_clave} onChange={e => setForm(p => ({ ...p, palabras_clave: e.target.value }))}
                placeholder="ej: urgente, premium, vip" className="mt-1" />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-xs">Horario inicio</Label>
                <Input type="time" value={form.horario_inicio} onChange={e => setForm(p => ({ ...p, horario_inicio: e.target.value }))} className="mt-1" />
              </div>
              <div>
                <Label className="text-xs">Horario fin</Label>
                <Input type="time" value={form.horario_fin} onChange={e => setForm(p => ({ ...p, horario_fin: e.target.value }))} className="mt-1" />
              </div>
            </div>
          </FieldsetCard>

          <FieldsetCard title="Asignar a">
            <div>
              <Label className="text-xs">Tipo de asignación</Label>
              <select value={form.asignar_a_tipo} onChange={e => setForm(p => ({ ...p, asignar_a_tipo: e.target.value, asignar_a_id: '' }))}
                className="w-full mt-1 text-sm border border-gray-200 rounded-md px-2 py-1.5">
                <option value="asesor_especifico">Asesor específico</option>
                <option value="equipo_round_robin">Round-robin del equipo (de un supervisor)</option>
                <option value="asesor_round_robin_global">Round-robin global de asesores</option>
              </select>
            </div>
            {form.asignar_a_tipo !== 'asesor_round_robin_global' && (
              <div>
                <Label className="text-xs">{form.asignar_a_tipo === 'asesor_especifico' ? 'Asesor' : 'Supervisor (su equipo)'}</Label>
                <select value={form.asignar_a_id} onChange={e => setForm(p => ({ ...p, asignar_a_id: e.target.value }))}
                  className="w-full mt-1 text-sm border border-gray-200 rounded-md px-2 py-1.5">
                  <option value="">— Selecciona —</option>
                  {targetOptions.map(u => (
                    <option key={u.id} value={u.id}>
                      {[u.first_name, u.last_name].filter(Boolean).join(' ') || u.email} ({u.role})
                    </option>
                  ))}
                </select>
              </div>
            )}
            <div>
              <Label className="text-xs">Si el target está lleno o no disponible</Label>
              <select value={form.fallback_si_lleno} onChange={e => setForm(p => ({ ...p, fallback_si_lleno: e.target.value }))}
                className="w-full mt-1 text-sm border border-gray-200 rounded-md px-2 py-1.5">
                <option value="siguiente_regla">Probar siguiente regla</option>
                <option value="estrategia_default">Aplicar estrategia por defecto</option>
                <option value="asignar_igual">Forzar asignación (ignorar capacity)</option>
              </select>
            </div>
          </FieldsetCard>

          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={form.activo} onChange={e => setForm(p => ({ ...p, activo: e.target.checked }))} className="rounded" />
            <span>Regla activa</span>
          </label>
        </div>
        <div className="flex justify-end gap-2 px-6 py-3 border-t border-gray-100 bg-gray-50 rounded-b-2xl shrink-0">
          <Button variant="outline" onClick={onClose}>Cancelar</Button>
          <Button onClick={submit} disabled={saving} className="gap-1.5">
            <Save size={14} /> {saving ? 'Guardando...' : 'Guardar regla'}
          </Button>
        </div>
      </div>
    </div>
  )
}

function FieldsetCard({ title, children }) {
  return (
    <div className="border border-gray-200 rounded-lg p-3 space-y-3 bg-gray-50/30">
      <p className="text-[10px] uppercase tracking-wide font-semibold text-gray-500">{title}</p>
      {children}
    </div>
  )
}

/* ╔════════════════════════════════════════════════════════════════╗
   ║ TAB 4 — Asesores (capacity, horarios, vacaciones)              ║
   ╚════════════════════════════════════════════════════════════════╝ */

function TabAsesores() {
  const [items, setItems] = useState([])
  const [config, setConfig] = useState(null)
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(null)
  const [savingConfig, setSavingConfig] = useState(false)
  const [showConfirmFix, setShowConfirmFix] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [r, c] = await Promise.all([
        api.get('/api/admin/assignment/asesores'),
        api.get('/api/admin/assignment/config'),
      ])
      setItems(r.data || [])
      setConfig(c.data)
    } finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  // Aplicar fix rapido: cambiar definicion a "sin contacto 48h" + cap 200.
  // Default presente ('todos_activos' + 50) suele ser el que satura el sistema
  // al activar auto-asignacion en CRMs con mucho historico.
  const aplicarFixCapacity = async () => {
    setShowConfirmFix(false)
    setSavingConfig(true)
    try {
      await api.patch('/api/admin/assignment/config', {
        capacity_definicion: 'sin_contacto_48h',
        max_leads_abiertos_default: 200,
      })
      await load()
    } catch (err) {
      alert(err.response?.data?.detail || 'Error')
    } finally { setSavingConfig(false) }
  }

  if (loading) return <LoadingSpinner />

  // Cuenta solo asesores (no supervisores) para el banner
  const asesoresOnly = items.filter(a => a.role === 'asesor')
  const llenos = asesoresOnly.filter(a => !a.elegible && a.motivo_no_elegible?.startsWith('capacity'))
  const elegibles = asesoresOnly.filter(a => a.elegible)
  const saturado = asesoresOnly.length > 0 && llenos.length / asesoresOnly.length >= 0.5

  return (
    <div className="space-y-4">
      <p className="text-sm text-gray-600">
        Configura capacity, horarios, vacaciones y peso de rotación por asesor. La barra
        muestra cuántos leads abiertos tiene cada uno respecto a su máximo configurado.
      </p>

      {/* Banner: saturacion de capacity */}
      {saturado && (
        <Card className="border-amber-300 bg-amber-50/50">
          <CardContent className="p-4">
            <div className="flex items-start gap-3">
              <AlertCircle size={20} className="text-amber-600 shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <p className="text-sm font-semibold text-amber-900">
                  {llenos.length} de {asesoresOnly.length} asesores están con capacity llena
                </p>
                <p className="text-xs text-amber-800 mt-1 leading-relaxed">
                  El motor solo puede asignar a {elegibles.length} asesor{elegibles.length === 1 ? '' : 'es'} elegible{elegibles.length === 1 ? '' : 's'}.
                  Esto suele pasar al activar la auto-asignación en CRMs con mucho histórico:
                  el cap de <strong>{config?.max_leads_abiertos_default || 50} leads abiertos</strong> con la definición
                  "<strong>{config?.capacity_definicion === 'sin_contacto_48h' ? 'sin contacto en 48h' : 'todos los activos'}</strong>"
                  cuenta leads viejos que ya nadie atiende.
                </p>
                <div className="flex flex-wrap gap-2 mt-3">
                  <Button size="sm" onClick={() => setShowConfirmFix(true)} disabled={savingConfig} className="gap-1.5 bg-amber-600 hover:bg-amber-700 text-white">
                    <Sparkles size={12} /> {savingConfig ? 'Aplicando...' : 'Cambiar a "sin contacto 48h" + cap 200'}
                  </Button>
                  <span className="text-[11px] text-amber-700 self-center">
                    o ajusta manualmente desde el tab "Del supervisor al asesor"
                  </span>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
      <Card>
        <CardContent className="p-0">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-100">
                  <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase">Asesor</th>
                  <th className="text-left px-3 py-3 text-xs font-semibold text-gray-500 uppercase min-w-[200px]">
                    <span className="inline-flex items-center gap-1">
                      Capacity
                      <span title="Pasa el mouse por el ícono ⓘ de cada fila para ver la fórmula exacta de 'leads abiertos'." className="cursor-help">
                        <Info size={10} className="text-gray-300" />
                      </span>
                    </span>
                  </th>
                  <th className="text-left px-3 py-3 text-xs font-semibold text-gray-500 uppercase">Horario</th>
                  <th className="text-left px-3 py-3 text-xs font-semibold text-gray-500 uppercase">Estado real</th>
                  <th className="text-left px-3 py-3 text-xs font-semibold text-gray-500 uppercase">Peso</th>
                  <th className="px-3 py-3"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {items.map(a => (
                  <tr key={a.asesor_id} className="hover:bg-gray-50/50">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2.5">
                        <div className={cn(
                          'w-9 h-9 rounded-full flex items-center justify-center text-sm font-semibold shrink-0',
                          a.role === 'supervisor' ? 'bg-purple-100 text-purple-600' : 'bg-indigo-100 text-indigo-600'
                        )}>
                          {(a.nombre || '?')[0].toUpperCase()}
                        </div>
                        <div className="min-w-0">
                          <p className="font-medium text-gray-800 truncate">{a.nombre || '—'}</p>
                          <p className="text-[10px] text-gray-400">
                            {a.role} {a.supervisor_nombre && `· equipo ${a.supervisor_nombre}`}
                          </p>
                        </div>
                      </div>
                    </td>
                    <td className="px-3 py-3">
                      <CapacityBar
                        leads={a.leads_abiertos}
                        max={a.max_leads_efectivo}
                        pct={a.pct_capacity}
                        capacityDef={config?.capacity_definicion}
                        hasOverride={a.max_leads_abiertos != null}
                      />
                    </td>
                    <td className="px-3 py-3 text-xs text-gray-600">
                      {a.horario_inicio && a.horario_fin
                        ? `${a.horario_inicio} - ${a.horario_fin}`
                        : <span className="text-gray-400">global</span>}
                    </td>
                    <td className="px-3 py-3">
                      <ElegibilidadBadge a={a} />
                    </td>
                    <td className="px-3 py-3 text-sm font-mono text-gray-700">{Number(a.peso_rotacion).toFixed(1)}x</td>
                    <td className="px-3 py-3 text-right">
                      <button onClick={() => setEditing(a)} className="p-1.5 rounded hover:bg-indigo-50 text-gray-400 hover:text-indigo-500" title="Editar">
                        <Edit2 size={13} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>

      {editing && (
        <AsesorSettingsModal asesor={editing} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load() }} />
      )}

      <ConfirmDialog
        open={showConfirmFix}
        variant="warning"
        title="Recalibrar capacity del equipo"
        message='La definición de "lead abierto" cambiará a "sin contacto en 48h" y el cap subirá a 200 leads por asesor. Los asesores con cap individual configurado no se ven afectados. La mayoría debería pasar a estado ELEGIBLE.'
        confirmLabel="Aplicar cambios"
        onConfirm={aplicarFixCapacity}
        onCancel={() => setShowConfirmFix(false)}
      />
    </div>
  )
}

function ElegibilidadBadge({ a }) {
  // Usa elegible/motivo_no_elegible del backend (lo mismo que evalua el motor).
  // Para supervisores mostramos un estado neutro ya que no reciben via auto-asignacion.
  if (a.role === 'supervisor') {
    return (
      <span className="text-[10px] bg-purple-50 text-purple-700 border border-purple-200 px-1.5 py-0.5 rounded font-semibold" title="Los supervisores reciben leads del round-robin entre supervisores, no del motor de auto-asignación al asesor.">
        SUPERVISOR
      </span>
    )
  }
  if (a.elegible) {
    return (
      <span className="text-[10px] bg-emerald-50 text-emerald-700 border border-emerald-200 px-1.5 py-0.5 rounded font-semibold" title="Recibe leads automáticamente.">
        ELEGIBLE
      </span>
    )
  }
  const motivo = a.motivo_no_elegible || ''
  if (motivo.startsWith('capacity')) {
    return (
      <span className="text-[10px] bg-red-50 text-red-700 border border-red-200 px-1.5 py-0.5 rounded font-semibold" title={`No recibe leads automáticamente: ${motivo}`}>
        LLENO
      </span>
    )
  }
  if (motivo.startsWith('en ausencia')) {
    return (
      <span className="text-[10px] bg-amber-50 text-amber-700 border border-amber-200 px-1.5 py-0.5 rounded font-semibold" title={motivo}>
        VACACIONES
      </span>
    )
  }
  if (motivo.startsWith('marcado')) {
    return (
      <span className="text-[10px] bg-gray-100 text-gray-600 border border-gray-200 px-1.5 py-0.5 rounded font-semibold" title="Toggle 'disponible' apagado.">
        PAUSADO
      </span>
    )
  }
  if (motivo.includes('horario')) {
    return (
      <span className="text-[10px] bg-sky-50 text-sky-700 border border-sky-200 px-1.5 py-0.5 rounded font-semibold" title={motivo}>
        FUERA DE HORARIO
      </span>
    )
  }
  return (
    <span className="text-[10px] bg-gray-100 text-gray-600 border border-gray-200 px-1.5 py-0.5 rounded font-semibold" title={motivo || 'No elegible'}>
      NO ELEGIBLE
    </span>
  )
}

function CapacityBar({ leads, max, pct, capacityDef, hasOverride }) {
  const color = pct >= 100 ? 'bg-red-500' : pct >= 80 ? 'bg-amber-500' : 'bg-emerald-500'
  const width = Math.min(pct || 0, 100)
  return (
    <div className="space-y-1">
      <div className="flex items-baseline gap-1.5">
        <span className="text-sm font-bold text-gray-800">{leads || 0}</span>
        <span className="text-[10px] text-gray-400">/ {max} leads abiertos</span>
        <CapacityInfoTooltip leads={leads} max={max} capacityDef={capacityDef} hasOverride={hasOverride} />
        <span className={cn('ml-auto text-[10px] font-semibold',
          pct >= 100 ? 'text-red-600' : pct >= 80 ? 'text-amber-600' : 'text-emerald-600'
        )}>{pct || 0}%</span>
      </div>
      <div className="w-full h-1.5 bg-gray-100 rounded-full overflow-hidden">
        <div className={cn('h-full transition-all', color)} style={{ width: `${width}%` }} />
      </div>
    </div>
  )
}

function CapacityInfoTooltip({ leads, max, capacityDef, hasOverride }) {
  const sinContacto = capacityDef === 'sin_contacto_48h'
  return (
    <span className="relative group/cap inline-flex items-center">
      <Info size={11} className="text-gray-300 hover:text-indigo-500 transition-colors cursor-help" />
      <div className="absolute left-0 top-full mt-1 z-30 w-72 p-3 rounded-lg bg-white border border-gray-200 shadow-xl
                      text-[11px] text-gray-700 leading-relaxed
                      opacity-0 pointer-events-none group-hover/cap:opacity-100 group-hover/cap:pointer-events-auto
                      transition-opacity duration-150">
        <p className="font-semibold text-gray-900 mb-1.5 flex items-center gap-1">
          <Info size={11} className="text-indigo-500" /> ¿Qué cuenta como "lead abierto"?
        </p>
        {sinContacto ? (
          <>
            <p className="mb-1.5">Modo activo: <strong>solo leads sin contacto en 48h</strong>.</p>
            <p className="text-gray-600 text-[10px] mb-1">Se cuenta el lead si:</p>
            <ul className="list-disc list-inside text-gray-600 text-[10px] space-y-0.5 mb-2">
              <li>Está activo (no archivado)</li>
              <li>Su estado <strong>NO</strong> es Ganado / Perdido / No interesado</li>
              <li>El asesor <strong>NO</strong> registró ningún contacto (llamada, WA, email, etc.) en las últimas 48h</li>
            </ul>
            <p className="text-gray-500 text-[10px]">
              Si el asesor llama hoy a un lead, deja de pesar por 48h en su capacity. Premia atender, no acumular.
            </p>
          </>
        ) : (
          <>
            <p className="mb-1.5">Modo activo: <strong>todos los leads activos no terminales</strong>.</p>
            <p className="text-gray-600 text-[10px] mb-1">Se cuenta el lead si:</p>
            <ul className="list-disc list-inside text-gray-600 text-[10px] space-y-0.5 mb-2">
              <li>Está activo (no archivado)</li>
              <li>Su estado <strong>NO</strong> es Ganado / Perdido / No interesado</li>
            </ul>
            <p className="text-gray-500 text-[10px]">
              Cuenta todo el pipeline, incluso leads viejos sin tocar. Para CRMs con mucho histórico considera cambiar a "sin contacto en 48h".
            </p>
          </>
        )}
        <hr className="my-2 border-gray-100" />
        <p className="text-[10px]">
          <strong>{leads}</strong> de <strong>{max}</strong> ocupados ·{' '}
          <span className="text-gray-500">
            {hasOverride ? 'cap individual configurado' : 'cap default global'}
          </span>
        </p>
      </div>
    </span>
  )
}

function AsesorSettingsModal({ asesor, onClose, onSaved }) {
  const [form, setForm] = useState({
    disponible_rotacion: asesor.disponible_rotacion,
    max_leads_abiertos:  asesor.max_leads_abiertos ?? '',
    horario_inicio:      asesor.horario_inicio || '',
    horario_fin:         asesor.horario_fin || '',
    ausencia_desde:      asesor.ausencia_desde || '',
    ausencia_hasta:      asesor.ausencia_hasta || '',
    motivo_ausencia:     asesor.motivo_ausencia || '',
    peso_rotacion:       asesor.peso_rotacion || 1.0,
    notas:               asesor.notas || '',
  })
  const [saving, setSaving] = useState(false)

  const submit = async () => {
    setSaving(true)
    try {
      await api.patch(`/api/admin/assignment/asesores/${asesor.asesor_id}`, {
        disponible_rotacion: form.disponible_rotacion,
        max_leads_abiertos:  form.max_leads_abiertos === '' ? null : parseInt(form.max_leads_abiertos),
        horario_inicio:      form.horario_inicio || null,
        horario_fin:         form.horario_fin || null,
        ausencia_desde:      form.ausencia_desde || null,
        ausencia_hasta:      form.ausencia_hasta || null,
        motivo_ausencia:     form.motivo_ausencia || null,
        peso_rotacion:       parseFloat(form.peso_rotacion) || 1.0,
        notas:               form.notas || null,
      })
      onSaved()
    } catch (err) {
      alert(err.response?.data?.detail || 'Error guardando')
    } finally { setSaving(false) }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-start sm:items-center justify-center p-4 overflow-y-auto" onClick={onClose}>
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg my-auto flex flex-col max-h-[90vh]" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 pt-5 pb-3 border-b border-gray-100 shrink-0">
          <h3 className="text-base font-semibold text-gray-900 flex items-center gap-2">
            <Briefcase size={16} className="text-indigo-500" /> {asesor.nombre}
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600"><XIcon size={16} /></button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
          <label className="flex items-center justify-between gap-3 p-3 rounded-lg border border-gray-200">
            <div className="flex-1">
              <p className="text-sm font-medium text-gray-800">Disponible para rotación</p>
              <p className="text-[11px] text-gray-500">Si se desactiva, el motor no le asigna leads automáticamente.</p>
            </div>
            <Switch checked={form.disponible_rotacion} onChange={v => setForm(p => ({ ...p, disponible_rotacion: v }))} />
          </label>

          <div>
            <Label className="text-xs">Máximo de leads abiertos (override individual)</Label>
            <Input type="number" min="0" value={form.max_leads_abiertos}
              onChange={e => setForm(p => ({ ...p, max_leads_abiertos: e.target.value }))}
              placeholder="Vacío = usar default global" className="mt-1" />
          </div>

          <div>
            <Label className="text-xs">Peso de rotación</Label>
            <Input type="number" min="0" max="10" step="0.1" value={form.peso_rotacion}
              onChange={e => setForm(p => ({ ...p, peso_rotacion: e.target.value }))} className="mt-1" />
            <p className="text-[10px] text-gray-400 mt-1">
              1.0 = normal · 2.0 = recibe el doble que un peso 1 · 0.5 = recibe la mitad.
            </p>
          </div>

          <FieldsetCard title="Horario (override del global)">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-xs">Inicio</Label>
                <Input type="time" value={form.horario_inicio} onChange={e => setForm(p => ({ ...p, horario_inicio: e.target.value }))} className="mt-1" />
              </div>
              <div>
                <Label className="text-xs">Fin</Label>
                <Input type="time" value={form.horario_fin} onChange={e => setForm(p => ({ ...p, horario_fin: e.target.value }))} className="mt-1" />
              </div>
            </div>
          </FieldsetCard>

          <FieldsetCard title="Ausencia / vacaciones programadas">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-xs flex items-center gap-1"><CalIcon size={11} /> Desde</Label>
                <Input type="date" value={form.ausencia_desde} onChange={e => setForm(p => ({ ...p, ausencia_desde: e.target.value }))} className="mt-1" />
              </div>
              <div>
                <Label className="text-xs flex items-center gap-1"><CalIcon size={11} /> Hasta</Label>
                <Input type="date" value={form.ausencia_hasta} onChange={e => setForm(p => ({ ...p, ausencia_hasta: e.target.value }))} className="mt-1" />
              </div>
            </div>
            <div>
              <Label className="text-xs">Motivo</Label>
              <Input value={form.motivo_ausencia} onChange={e => setForm(p => ({ ...p, motivo_ausencia: e.target.value }))}
                placeholder="Ej: Vacaciones programadas / licencia" className="mt-1" />
            </div>
          </FieldsetCard>

          <div>
            <Label className="text-xs">Notas</Label>
            <textarea value={form.notas} onChange={e => setForm(p => ({ ...p, notas: e.target.value }))} rows={2}
              className="w-full mt-1 text-sm border border-gray-200 rounded-md px-3 py-2 resize-none" />
          </div>
        </div>
        <div className="flex justify-end gap-2 px-6 py-3 border-t border-gray-100 bg-gray-50 rounded-b-2xl shrink-0">
          <Button variant="outline" onClick={onClose}>Cancelar</Button>
          <Button onClick={submit} disabled={saving} className="gap-1.5">
            <Save size={14} /> {saving ? 'Guardando...' : 'Guardar cambios'}
          </Button>
        </div>
      </div>
    </div>
  )
}

/* ╔════════════════════════════════════════════════════════════════╗
   ║ TAB 5 — Auditoría                                               ║
   ╚════════════════════════════════════════════════════════════════╝ */

function TabAuditoria() {
  const [audit, setAudit] = useState([])
  const [stats, setStats] = useState(null)
  const [queue, setQueue] = useState([])
  const [loading, setLoading] = useState(true)
  const [expanded, setExpanded] = useState(new Set())
  const [processing, setProcessing] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const [a, s, q] = await Promise.all([
        api.get('/api/admin/assignment/audit?limit=100'),
        api.get('/api/admin/assignment/stats?dias=30'),
        api.get('/api/admin/assignment/queue?limit=50'),
      ])
      setAudit(a.data?.items || [])
      setStats(s.data)
      setQueue(q.data?.items || [])
    } finally { setLoading(false) }
  }, [])
  useEffect(() => { load() }, [load])

  const forceProcess = async () => {
    setProcessing(true)
    try {
      const r = await api.post('/api/admin/assignment/queue/process-now')
      alert(`Procesado:\nAsignados: ${r.data?.asignados || 0}\nReagendados: ${r.data?.reagendados || 0}\nDescartados: ${r.data?.descartados || 0}`)
      load()
    } catch (err) {
      alert(err.response?.data?.detail || 'Error procesando cola')
    } finally { setProcessing(false) }
  }

  const toggle = (id) => {
    const n = new Set(expanded)
    n.has(id) ? n.delete(id) : n.add(id)
    setExpanded(n)
  }

  if (loading) return <LoadingSpinner />

  return (
    <div className="space-y-4">
      {/* KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <KpiSmall label="% auto-asignado (30d)" value={`${stats?.auto_vs_total?.pct_auto ?? 0}%`} />
        <KpiSmall label="Leads del periodo" value={stats?.auto_vs_total?.total ?? 0} />
        <KpiSmall label="Asignaciones automáticas" value={stats?.auto_vs_total?.auto ?? 0} />
        <KpiSmall label="Tiempo promedio" value={`${stats?.avg_duracion_ms ?? 0} ms`} />
      </div>

      {/* Cola pendiente (V047) */}
      <Card>
        <CardHeader className="flex flex-row items-center justify-between">
          <CardTitle className="text-sm flex items-center gap-2">
            <Clock size={14} className="text-amber-500" />
            Cola en espera
            <span className="text-[10px] bg-amber-50 text-amber-700 border border-amber-200 px-1.5 py-0.5 rounded font-semibold">
              {queue.length}
            </span>
          </CardTitle>
          {queue.length > 0 && (
            <Button size="sm" variant="outline" onClick={forceProcess} disabled={processing} className="gap-1.5">
              <RefreshCw size={12} className={processing ? 'animate-spin' : ''} />
              {processing ? 'Procesando...' : 'Procesar ahora'}
            </Button>
          )}
        </CardHeader>
        <CardContent className="p-0">
          {queue.length === 0 ? (
            <div className="px-6 py-8 text-center">
              <CheckCircle2 size={28} className="mx-auto text-emerald-300 mb-2" />
              <p className="text-sm text-gray-500">No hay leads en cola.</p>
              <p className="text-[10px] text-gray-400 mt-1">El sistema revisa cada 15 minutos automáticamente.</p>
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-amber-50/50 border-b border-amber-100">
                    <th className="text-left px-3 py-2 text-[10px] font-semibold text-amber-700 uppercase">Lead</th>
                    <th className="text-left px-3 py-2 text-[10px] font-semibold text-amber-700 uppercase">Supervisor</th>
                    <th className="text-left px-3 py-2 text-[10px] font-semibold text-amber-700 uppercase">Motivo</th>
                    <th className="text-left px-3 py-2 text-[10px] font-semibold text-amber-700 uppercase">Próximo intento</th>
                    <th className="text-left px-3 py-2 text-[10px] font-semibold text-amber-700 uppercase">Intentos</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-amber-50">
                  {queue.map(q => (
                    <tr key={q.id} className="hover:bg-amber-50/30">
                      <td className="px-3 py-2">
                        <span className="font-mono text-[10px] bg-gray-100 px-1.5 py-0.5 rounded">#{q.lead_id}</span>
                        <span className="ml-2 text-gray-700">{q.nombres} {q.apellidos}</span>
                        {q.fuente_nombre && <span className="ml-2 text-[10px] text-gray-400">· {q.fuente_nombre}</span>}
                      </td>
                      <td className="px-3 py-2 text-gray-600">{q.supervisor_nombre || '—'}</td>
                      <td className="px-3 py-2">
                        {q.motivo === 'fuera_horario'
                          ? <span className="text-[10px] bg-indigo-50 text-indigo-700 border border-indigo-200 px-1.5 py-0.5 rounded">fuera de horario</span>
                          : <span className="text-[10px] bg-rose-50 text-rose-700 border border-rose-200 px-1.5 py-0.5 rounded">{q.motivo}</span>}
                      </td>
                      <td className="px-3 py-2 text-gray-600">{formatRelativeTime(q.proximo_intento)}</td>
                      <td className="px-3 py-2 text-gray-500">{q.intentos}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Por estrategia */}
      {stats?.por_estrategia?.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-sm">Por estrategia (últimos 30 días)</CardTitle></CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {stats.por_estrategia.map(e => (
                <div key={e.estrategia} className="px-3 py-1.5 bg-gray-50 border border-gray-200 rounded-lg text-xs">
                  <span className="font-semibold text-gray-700">{e.estrategia}</span>
                  <span className="ml-2 text-gray-500">{e.total}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Top reglas */}
      {stats?.top_reglas?.length > 0 && (
        <Card>
          <CardHeader><CardTitle className="text-sm">Top reglas más aplicadas</CardTitle></CardHeader>
          <CardContent>
            <table className="w-full text-sm">
              <tbody className="divide-y divide-gray-50">
                {stats.top_reglas.map(r => (
                  <tr key={r.id}>
                    <td className="py-2 text-gray-700">{r.nombre}</td>
                    <td className="py-2 text-right font-bold text-indigo-600">{r.total_aplicaciones}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {/* Audit log */}
      <Card>
        <CardHeader>
          <CardTitle className="text-sm flex items-center gap-2">
            <Activity size={14} /> Últimas decisiones del motor
            <span className="text-[10px] text-gray-400">({audit.length} eventos)</span>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {audit.length === 0
            ? <p className="text-center text-sm text-gray-400 py-8">Sin decisiones automáticas registradas todavía.</p>
            : <div className="divide-y divide-gray-50">
                {audit.map(row => {
                  const isOpen = expanded.has(row.id)
                  return (
                    <div key={row.id} className="hover:bg-gray-50/50">
                      <div className="px-4 py-3 cursor-pointer flex items-start gap-3" onClick={() => toggle(row.id)}>
                        <ChevronDown size={14} className={cn('text-gray-400 mt-1 transition-transform', !isOpen && '-rotate-90')} />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-baseline gap-2 flex-wrap">
                            <span className="font-mono text-[10px] bg-gray-100 px-1.5 py-0.5 rounded">#{row.lead_id}</span>
                            <span className="text-sm font-medium text-gray-800">→ {row.asignado_a_nombre || '—'}</span>
                            <span className="text-[10px] bg-indigo-50 text-indigo-700 border border-indigo-200 px-1.5 py-0.5 rounded">
                              {row.estrategia}
                            </span>
                            {row.regla_nombre && (
                              <span className="text-[10px] bg-violet-50 text-violet-700 border border-violet-200 px-1.5 py-0.5 rounded">
                                regla: {row.regla_nombre}
                              </span>
                            )}
                            <span className="text-[10px] text-gray-400 ml-auto">{formatRelativeTime(row.fecha)}</span>
                          </div>
                          <p className="text-xs text-gray-500 mt-0.5 truncate">{row.razon}</p>
                        </div>
                      </div>
                      {isOpen && (
                        <div className="px-12 pb-3 bg-gray-50/40 text-xs">
                          <p className="text-gray-600 mb-2"><strong>Tiempo de cálculo:</strong> {row.duracion_ms} ms</p>
                          <p className="text-gray-600 mb-2"><strong>Supervisor que recibió:</strong> {row.supervisor_nombre || '—'}</p>
                          {row.candidatos_evaluados?.length > 0 && (
                            <div>
                              <p className="text-gray-600 font-semibold mb-1">Candidatos evaluados:</p>
                              <table className="w-full">
                                <tbody>
                                  {row.candidatos_evaluados.map((c, i) => (
                                    <tr key={i} className="border-b border-gray-100 last:border-0">
                                      <td className="py-1 text-gray-700">{c.nombre || c.user_id?.slice(0, 8)}</td>
                                      <td className="py-1 text-right text-gray-500">
                                        {c.elegido && <span className="text-emerald-600 font-semibold">✓ elegido</span>}
                                        {!c.elegido && c.motivo_descarte && <span className="text-amber-600">descarte: {c.motivo_descarte}</span>}
                                        {!c.elegido && !c.motivo_descarte && c.leads_abiertos != null && (
                                          <span className="text-gray-500">{c.leads_abiertos} abiertos · {c.leads_hoy ?? 0} hoy</span>
                                        )}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          )}
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
          }
        </CardContent>
      </Card>
    </div>
  )
}

/* ─── Utils ──────────────────────────────────────────────────────────── */

function formatRelativeTime(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return 'hace ' + Math.round(diff) + 's'
  if (diff < 3600) return 'hace ' + Math.round(diff / 60) + 'm'
  if (diff < 86400) return 'hace ' + Math.round(diff / 3600) + 'h'
  if (diff < 86400 * 7) return 'hace ' + Math.round(diff / 86400) + 'd'
  return d.toLocaleDateString('es-PE', { day: '2-digit', month: 'short' })
}
