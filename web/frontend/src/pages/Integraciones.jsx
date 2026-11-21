/**
 * Integraciones — panel admin.
 *
 * Registra credenciales para los proveedores externos (Meta, TikTok) que
 * el backend ya sabe procesar. Sigue el patrón de patrón estándar "Named
 * Credentials" / patrón estándar "Connected Apps": una tarjeta por proveedor,
 * cada key con su input, secretos enmascarados mostrando solo sufijo
 * + fingerprint (nunca plaintext).
 *
 * Endpoints consumidos (todos admin-only):
 *   GET    /api/integrations/providers
 *   GET    /api/integrations/{provider}/credentials
 *   PUT    /api/integrations/{provider}/credentials
 *   DELETE /api/integrations/{provider}/credentials/{key}?account_id=...
 *   GET    /api/integrations/{provider}/events
 *
 * Roles: admin (protegido en App.jsx con AdminRoute).
 */
import { useEffect, useState, useCallback, useMemo } from 'react'
import { Link } from 'react-router-dom'
import {
  Plug, Save, Trash2, RefreshCw, Eye, EyeOff, Plus,
  CheckCircle2, AlertTriangle, Clock, MessageCircle, Layers, Music2,
  ChevronRight, Zap, SlidersHorizontal, Sparkles,
} from 'lucide-react'
import api from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import LoadingSpinner from '@/components/shared/LoadingSpinner'
import EmptyState from '@/components/shared/EmptyState'
import ConfirmDialog from '@/components/shared/ConfirmDialog'
import { cn } from '@/lib/utils'
import { WhatsAppSettings } from './Configuracion'
import ApiClients from './ApiClients'

const GLOBAL_ACCOUNT = '_global'

function formatDateTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('es-PE', {
      day: '2-digit', month: '2-digit', year: 'numeric',
      hour: '2-digit', minute: '2-digit', hour12: false,
    })
  } catch {
    return '—'
  }
}

function StatusBadge({ counts }) {
  const total = (counts?.ok || 0) + (counts?.error || 0) + (counts?.skipped || 0)
  if (total === 0) {
    return <span className="text-xs text-gray-400">Sin actividad 24h</span>
  }
  return (
    <div className="flex items-center gap-2 text-xs">
      {counts.ok > 0 && (
        <span className="inline-flex items-center gap-1 text-emerald-600">
          <CheckCircle2 size={12} /> {counts.ok} ok
        </span>
      )}
      {counts.error > 0 && (
        <span className="inline-flex items-center gap-1 text-red-600">
          <AlertTriangle size={12} /> {counts.error} err
        </span>
      )}
      {counts.skipped > 0 && (
        <span className="inline-flex items-center gap-1 text-amber-600">
          <Clock size={12} /> {counts.skipped} skip
        </span>
      )}
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────── */
/* Formulario por key (global o per-account)                                */
/* ─────────────────────────────────────────────────────────────────────── */

function KeyField({ provider, spec, credential, accountId, onSaved, onDeleted }) {
  const [value, setValue] = useState('')
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [show, setShow] = useState(false)
  const [confirmOpen, setConfirmOpen] = useState(false)

  const hasValue = credential?.has_value
  const mask = credential?.mask
  const fingerprint = credential?.fingerprint

  const effectiveAccount = spec.per_account ? (accountId || '') : GLOBAL_ACCOUNT

  const inputType = spec.is_secret && !show ? 'password' : 'text'
  // Placeholder refleja qué está guardado:
  //  - secreto con valor   → mask + fingerprint (no revela plaintext)
  //  - no-secreto con valor → "Actual: <valor>"
  //  - sin valor           → prompt genérico
  // Sin esto, las keys no-secretas (ej. app_id) no mostraban señal visual
  // de que ya estaban guardadas y generaban confusión.
  const placeholder = hasValue
    ? (spec.is_secret
        ? `${mask}  ·  fp:${fingerprint}`
        : `Actual: ${credential?.value ?? ''}`)
    : 'Ingresa el valor…'

  const handleSave = async () => {
    if (!value.trim()) {
      alert('El valor no puede estar vacío.')
      return
    }
    if (spec.per_account && !accountId) {
      alert('Selecciona una cuenta antes de guardar.')
      return
    }
    setSaving(true)
    try {
      await api.put(`/api/integrations/${provider}/credentials`, {
        key: spec.key,
        value: value.trim(),
        account_id: effectiveAccount,
      })
      setValue('')
      onSaved?.()
    } catch (err) {
      alert(err.response?.data?.detail || 'Error guardando credencial.')
    } finally {
      setSaving(false)
    }
  }

  const handleDelete = async () => {
    if (!hasValue) return
    setConfirmOpen(false)
    setDeleting(true)
    try {
      await api.delete(`/api/integrations/${provider}/credentials/${spec.key}`, {
        params: { account_id: effectiveAccount },
      })
      onDeleted?.()
    } catch (err) {
      alert(err.response?.data?.detail || 'Error eliminando credencial.')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-[1fr_auto] gap-2 items-start py-2">
      <div>
        <label className="block text-xs font-semibold text-gray-700">
          {spec.label}
          {spec.is_secret && (
            <span className="ml-2 text-[10px] font-normal text-amber-600 uppercase">
              Secreto · cifrado
            </span>
          )}
        </label>
        {spec.help && (
          <p className="text-[11px] text-gray-500 mt-0.5 leading-snug">{spec.help}</p>
        )}
        <div className="flex items-center gap-2 mt-1">
          <div className="relative flex-1">
            <Input
              type={inputType}
              value={value}
              onChange={(e) => setValue(e.target.value)}
              placeholder={placeholder}
              className="pr-9"
              autoComplete="off"
              spellCheck={false}
              disabled={saving}
            />
            {spec.is_secret && (
              <button
                type="button"
                onClick={() => setShow(!show)}
                className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                tabIndex={-1}
              >
                {show ? <EyeOff size={14} /> : <Eye size={14} />}
              </button>
            )}
          </div>
          {hasValue && (
            <span className="text-[10px] text-gray-500 whitespace-nowrap">
              {formatDateTime(credential?.updated_at)}
            </span>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2 md:pt-5">
        <Button size="sm" onClick={handleSave} disabled={saving || !value.trim()}>
          <Save size={13} className="mr-1" />
          {saving ? '...' : 'Guardar'}
        </Button>
        {hasValue && (
          <Button
            size="sm"
            variant="outline"
            onClick={() => setConfirmOpen(true)}
            disabled={deleting}
            className="text-red-600 hover:text-red-700"
          >
            <Trash2 size={13} />
          </Button>
        )}
      </div>
      <ConfirmDialog
        open={confirmOpen}
        title={`Eliminar ${spec.label}`}
        message={`¿Seguro que quieres eliminar el valor guardado de "${spec.label}"? Esta acción no se puede deshacer.`}
        confirmLabel="Eliminar"
        onConfirm={handleDelete}
        onCancel={() => setConfirmOpen(false)}
      />
    </div>
  )
}

/* ─────────────────────────────────────────────────────────────────────── */
/* Bloque por proveedor                                                    */
/* ─────────────────────────────────────────────────────────────────────── */

function ProviderCard({ provider }) {
  const [credentials, setCredentials] = useState([])
  const [accounts, setAccounts] = useState([])
  const [events, setEvents] = useState([])
  const [loading, setLoading] = useState(true)
  const [loadingEvents, setLoadingEvents] = useState(false)
  const [newAccount, setNewAccount] = useState('')
  const [addError, setAddError] = useState('')
  const [showAddInput, setShowAddInput] = useState(false)
  const [showEvents, setShowEvents] = useState(false)
  const [eventsRefreshedAt, setEventsRefreshedAt] = useState(null)
  const [confirmRemoveAcc, setConfirmRemoveAcc] = useState(null)
  const [subscribing, setSubscribing] = useState(null)   // page_id en curso, o null
  const [subscribeMsg, setSubscribeMsg] = useState({})   // { [page_id]: {kind, text} }
  const [polling, setPolling] = useState(null)           // advertiser_id en curso, o null
  const [pollMsg, setPollMsg] = useState({})             // { [advertiser_id]: {kind, text} }
  const [backfilling, setBackfilling] = useState(null)   // advertiser_id en curso, o null
  const [backfillDays, setBackfillDays] = useState({})   // { [advertiser_id]: 30 }
  const [backfillMsg, setBackfillMsg] = useState({})     // { [advertiser_id]: {kind, text} }
  const [backfillConfirm, setBackfillConfirm] = useState(null)  // { advertiser_id, days } | null
  const [connecting, setConnecting] = useState(false)    // OAuth TikTok en curso
  const [connectMsg, setConnectMsg] = useState(null)     // {kind, text} — resultado OAuth
  const [reprocessingMeta, setReprocessingMeta] = useState(false)

  // Cadencia del polling automatico de TikTok (solo para provider=tiktok).
  // Backend acepta 5-60 min; default del servicio es 10.
  const [pollInterval, setPollInterval] = useState(10)
  const [pollIntervalSaved, setPollIntervalSaved] = useState(10)
  const [pollIntervalSaving, setPollIntervalSaving] = useState(false)
  const [pollIntervalMsg, setPollIntervalMsg] = useState(null)

  const globalKeys = provider.keys.filter(k => !k.per_account)
  const perAccountKeys = provider.keys.filter(k => k.per_account)

  const credByKey = useMemo(() => {
    const out = new Map()
    for (const c of credentials) {
      out.set(`${c.account_id}::${c.key}`, c)
    }
    return out
  }, [credentials])

  // `silent=true` evita togglear `loading` y con ello el desmontaje de los
  // <KeyField/> hijos. Sin esto, guardar un campo reemplazaba la tarjeta
  // por el spinner y reseteaba el input de cualquier hermano en edición.
  const loadCredentials = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setLoading(true)
    try {
      const res = await api.get(`/api/integrations/${provider.provider}/credentials`)
      setCredentials(res.data?.items || [])
      setAccounts((res.data?.accounts || []).filter(a => a !== GLOBAL_ACCOUNT))
    } catch (err) {
      alert(err.response?.data?.detail || 'Error cargando credenciales.')
    } finally {
      if (!silent) setLoading(false)
    }
  }, [provider.provider])

  const reloadAfterSave = useCallback(() => loadCredentials({ silent: true }), [loadCredentials])

  // `silent=true` evita togglear el spinner en refrescos automáticos —
  // la tabla se actualiza in-place sin parpadeos.
  const loadEvents = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setLoadingEvents(true)
    try {
      const res = await api.get(`/api/integrations/${provider.provider}/events`, {
        params: { limit: 30 },
      })
      setEvents(res.data?.items || [])
      setEventsRefreshedAt(new Date())
    } catch {
      setEvents([])
    } finally {
      if (!silent) setLoadingEvents(false)
    }
  }, [provider.provider])

  useEffect(() => {
    loadCredentials()
  }, [loadCredentials])

  // Cargar cadencia actual del polling automatico (solo para TikTok).
  // El scheduler relee este valor cada ciclo, asi que cambiarlo no requiere
  // reiniciar el servicio.
  useEffect(() => {
    if (provider.provider !== 'tiktok') return
    let cancelled = false
    api.get('/api/integrations/tiktok/settings')
      .then(res => {
        if (cancelled) return
        const v = Number(res.data?.polling_interval_min) || 10
        setPollInterval(v)
        setPollIntervalSaved(v)
      })
      .catch(() => {
        // Silencioso: el default del backend (10 min) ya es razonable.
      })
    return () => { cancelled = true }
  }, [provider.provider])

  const handleSavePollInterval = useCallback(async () => {
    const v = Math.max(5, Math.min(60, Math.round(Number(pollInterval) || 10)))
    setPollIntervalSaving(true)
    setPollIntervalMsg(null)
    try {
      const res = await api.patch('/api/integrations/tiktok/settings', {
        polling_interval_min: v,
      })
      const saved = Number(res.data?.polling_interval_min) || v
      setPollInterval(saved)
      setPollIntervalSaved(saved)
      setPollIntervalMsg({
        kind: 'ok',
        text: `Cadencia guardada: cada ${saved} min. Toma efecto en el proximo ciclo.`,
      })
    } catch (err) {
      setPollIntervalMsg({
        kind: 'error',
        text: err.response?.data?.detail || 'No se pudo guardar la cadencia.',
      })
    } finally {
      setPollIntervalSaving(false)
    }
  }, [pollInterval])

  // Auto-refresh del historial cada 15s mientras el panel esté abierto.
  // Se pausa al colapsarlo para no consumir API en segundo plano.
  useEffect(() => {
    if (!showEvents) return
    loadEvents()
    const id = setInterval(() => loadEvents({ silent: true }), 15_000)
    return () => clearInterval(id)
  }, [showEvents, loadEvents])

  const handleAddAccount = () => {
    setAddError('')
    const clean = newAccount.trim()
    if (!clean) {
      setAddError(provider.provider === 'meta'
        ? 'Ingresa el page_id de la fan page.'
        : 'Ingresa el advertiser_id.')
      return
    }
    // page_id de Meta y advertiser_id de TikTok son numéricos.
    if (!/^\d+$/.test(clean)) {
      setAddError('Solo se permiten dígitos (ej. 627713130435101).')
      return
    }
    if (clean === GLOBAL_ACCOUNT) {
      setAddError(`"${GLOBAL_ACCOUNT}" es un identificador reservado.`)
      return
    }
    if (accounts.includes(clean)) {
      setAddError('Esa cuenta ya está registrada.')
      return
    }
    setAccounts([...accounts, clean])
    setNewAccount('')
    setShowAddInput(false)
  }

  const cancelAddAccount = () => {
    setNewAccount('')
    setAddError('')
    setShowAddInput(false)
  }

  const handleSubscribeWebhook = async (accId) => {
    setSubscribing(accId)
    setSubscribeMsg(prev => ({ ...prev, [accId]: null }))
    try {
      const res = await api.post(`/api/integrations/meta/accounts/${accId}/subscribe`)
      if (res.data?.ok) {
        setSubscribeMsg(prev => ({
          ...prev,
          [accId]: { kind: 'ok', text: 'Página suscrita al campo leadgen. Ya puedes generar leads de prueba.' },
        }))
      } else {
        setSubscribeMsg(prev => ({
          ...prev,
          [accId]: { kind: 'error', text: res.data?.error || 'No se pudo suscribir la página.' },
        }))
      }
    } catch (err) {
      const detail = err.response?.data?.error
        || err.response?.data?.detail
        || err.message
        || 'No se pudo suscribir la página.'
      setSubscribeMsg(prev => ({ ...prev, [accId]: { kind: 'error', text: detail } }))
    } finally {
      setSubscribing(null)
    }
  }

  const handleManualPoll = async (advertiserId) => {
    setPolling(advertiserId)
    setPollMsg(prev => ({ ...prev, [advertiserId]: null }))
    try {
      const res = await api.post(
        `/api/integrations/tiktok/advertisers/${advertiserId}/poll`,
      )
      const r = res.data || {}
      if (r.ok) {
        const created = r.created ?? 0
        const dup = r.duplicated ?? 0
        const skipped = r.skipped ?? 0
        const errors = r.errors ?? 0
        const fetched = r.fetched ?? 0
        // V068.5 — breakdown del bucket "duplicated"
        const skipFext    = r.skip_fext ?? 0
        const skipSameDay = r.skip_same_day ?? 0
        const skipBackfill= r.skip_backfill ?? 0
        const recontReal  = r.recontacto_real ?? 0
        // Detalle entre paréntesis si hubo duplicados, para que el admin
        // pueda auditar visualmente qué pasó con cada lead procesado.
        const dupDetail = dup > 0
          ? ` (${skipFext} re-imports · ${skipSameDay} mismo día · ${skipBackfill} backfill · ${recontReal} reactivaciones reales)`
          : ''
        const text = fetched === 0
          ? 'Sin leads nuevos desde el último polling.'
          : `Polled ${fetched} lead${fetched === 1 ? '' : 's'} · ${created} nuevo${created === 1 ? '' : 's'}, ${dup} duplicado${dup === 1 ? '' : 's'}${dupDetail}, ${skipped} saltado${skipped === 1 ? '' : 's'}, ${errors} error${errors === 1 ? '' : 'es'}.`
        setPollMsg(prev => ({
          ...prev,
          [advertiserId]: { kind: errors > 0 ? 'warn' : 'ok', text },
        }))
      } else {
        const reason = r.reason === 'missing_access_token'
          ? 'Falta el access_token para este advertiser. Guárdalo arriba e intenta de nuevo.'
          : r.reason === 'fetch_failed'
            ? `No se pudo consultar la API de TikTok: ${r.error || 'sin detalle'}`
            : (r.error || 'No se pudo correr el polling.')
        setPollMsg(prev => ({ ...prev, [advertiserId]: { kind: 'error', text: reason } }))
      }
    } catch (err) {
      const detail = err.response?.data?.error
        || err.response?.data?.detail
        || err.message
        || 'No se pudo correr el polling.'
      setPollMsg(prev => ({ ...prev, [advertiserId]: { kind: 'error', text: detail } }))
    } finally {
      setPolling(null)
    }
  }

  // Backfill: dos pasos para usar ConfirmDialog del DS en vez de window.confirm.
  // Step 1: validar input y abrir modal de confirmación.
  const requestBackfill = (advertiserId) => {
    const days = Number(backfillDays[advertiserId] || 30)
    if (!days || days < 1 || days > 90) {
      setBackfillMsg(prev => ({
        ...prev,
        [advertiserId]: { kind: 'error', text: 'Días debe estar entre 1 y 90.' },
      }))
      return
    }
    setBackfillConfirm({ advertiserId, days })
  }

  // Step 2: ejecuta el backfill cuando el usuario confirma en el modal.
  // Resetea checkpoint y trae leads de los últimos N días pasando
  // start_time/end_time a TikTok (bypassea su lógica delta — recupera leads
  // ya consumidos por otros sistemas, ej. n8n viejo).
  const executeBackfill = async () => {
    if (!backfillConfirm) return
    const { advertiserId, days } = backfillConfirm
    setBackfillConfirm(null)
    setBackfilling(advertiserId)
    setBackfillMsg(prev => ({ ...prev, [advertiserId]: null }))
    try {
      const res = await api.post(
        `/api/integrations/tiktok/advertisers/${advertiserId}/backfill`,
        { lookback_days: days },
      )
      const r = res.data || {}
      if (r.ok) {
        const fetched = r.fetched ?? 0
        const created = r.created ?? 0
        const dup = r.duplicated ?? 0
        const errors = r.errors ?? 0
        const text = fetched === 0
          ? `Backfill OK — sin leads en los últimos ${days} días.`
          : `Backfill OK — ${fetched} traídos · ${created} nuevos, ${dup} duplicados${errors ? `, ${errors} errores` : ''}.`
        setBackfillMsg(prev => ({
          ...prev,
          [advertiserId]: { kind: errors > 0 ? 'warn' : 'ok', text, created },
        }))
      } else {
        const reason = r.error || r.reason || 'No se pudo correr el backfill.'
        setBackfillMsg(prev => ({ ...prev, [advertiserId]: { kind: 'error', text: reason } }))
      }
    } catch (err) {
      const detail = err.response?.data?.error
        || err.response?.data?.detail
        || err.message
        || 'No se pudo correr el backfill.'
      setBackfillMsg(prev => ({ ...prev, [advertiserId]: { kind: 'error', text: detail } }))
    } finally {
      setBackfilling(null)
    }
  }

  // OAuth TikTok: pide authorize_url al backend, redirige la misma pestaña.
  // El callback vuelve a /integraciones?tab=tiktok&oauth=ok|error&...
  const handleConnectTikTok = async () => {
    setConnecting(true)
    setConnectMsg(null)
    try {
      const res = await api.post('/api/integrations/tiktok/oauth/authorize')
      const url = res.data?.authorize_url
      if (url) {
        window.location.href = url
      } else {
        setConnectMsg({ kind: 'error', text: 'No se recibió la URL de autorización.' })
      }
    } catch (err) {
      const detail = err.response?.data?.detail || err.message || 'No se pudo iniciar OAuth.'
      setConnectMsg({ kind: 'error', text: detail })
    } finally {
      setConnecting(false)
    }
  }

  // Lee el resultado del callback (?oauth=ok|error) cuando la tarjeta es
  // de TikTok y la URL trae esos params. Muestra el banner y limpia la
  // query para no repetir el mensaje en refrescos posteriores.
  useEffect(() => {
    if (provider.provider !== 'tiktok') return
    const params = new URLSearchParams(window.location.search)
    const oauth = params.get('oauth')
    if (!oauth) return
    if (oauth === 'ok') {
      const n = parseInt(params.get('advertiser') ?? params.get('advertisers') ?? '0', 10) || 0
      setConnectMsg({
        kind: 'ok',
        text: n > 0
          ? `TikTok autorizado. Se conectaron ${n} advertiser${n === 1 ? '' : 's'}. El access_token ya está guardado.`
          : 'TikTok autorizado, pero la respuesta no incluyó advertisers. Revisa los permisos del app.',
      })
    } else if (oauth === 'error') {
      const reason = params.get('reason') || 'desconocido'
      setConnectMsg({
        kind: 'error',
        text: `TikTok rechazó la autorización (${reason}). Revisa App ID / Secret y vuelve a intentar.`,
      })
    }
    // Limpia los query params del OAuth dejando el tab.
    params.delete('oauth'); params.delete('advertisers'); params.delete('advertiser'); params.delete('reason')
    const qs = params.toString()
    window.history.replaceState({}, '', qs
      ? `${window.location.pathname}?${qs}`
      : window.location.pathname)
    loadCredentials({ silent: true })
  }, [provider.provider, loadCredentials])

  const handleRemoveAccount = async (accId) => {
    setConfirmRemoveAcc(null)
    for (const k of perAccountKeys) {
      const entry = credByKey.get(`${accId}::${k.key}`)
      if (!entry?.has_value) continue
      try {
        await api.delete(`/api/integrations/${provider.provider}/credentials/${k.key}`, {
          params: { account_id: accId },
        })
      } catch {
        /* best-effort */
      }
    }
    await loadCredentials()
  }

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <div className="w-10 h-10 rounded-lg bg-indigo-50 text-indigo-600 flex items-center justify-center shrink-0">
              <Plug size={20} />
            </div>
            <div>
              <CardTitle className="text-lg">{provider.label}</CardTitle>
              <CardDescription className="mt-1">{provider.description}</CardDescription>
              <div className="mt-1.5">
                <StatusBadge counts={provider.events_24h} />
              </div>
            </div>
          </div>
          <Button size="sm" variant="outline" onClick={loadCredentials} disabled={loading}>
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {loading ? (
          <LoadingSpinner />
        ) : (
          <>
            {/* Keys globales */}
            {globalKeys.length > 0 && (
              <div>
                <h4 className="text-xs font-bold uppercase tracking-wide text-gray-500 mb-1">
                  Configuración global
                </h4>
                <div className="divide-y divide-gray-100 border border-gray-100 rounded-lg px-3">
                  {globalKeys.map(k => (
                    <KeyField
                      key={k.key}
                      provider={provider.provider}
                      spec={k}
                      credential={credByKey.get(`${GLOBAL_ACCOUNT}::${k.key}`)}
                      onSaved={reloadAfterSave}
                      onDeleted={reloadAfterSave}
                    />
                  ))}
                </div>
              </div>
            )}

            {/* Conectar vía OAuth — solo TikTok. Meta no expone OAuth de app
                hacia terceros para leads, y WhatsApp usa su propio tab. */}
            {provider.provider === 'tiktok' && (() => {
              const appIdSaved = credByKey.get(`${GLOBAL_ACCOUNT}::app_id`)?.has_value
              const appSecretSaved = credByKey.get(`${GLOBAL_ACCOUNT}::app_secret`)?.has_value
              const canConnect = appIdSaved && appSecretSaved
              return (
                <div>
                  <h4 className="text-xs font-bold uppercase tracking-wide text-gray-500 mb-1">
                    Conectar cuenta TikTok Ads
                  </h4>
                  <div className="border border-gray-100 rounded-lg px-3 py-2.5">
                    <p className="text-[11px] text-gray-500 leading-snug mb-2">
                      En vez de pegar manualmente el <code className="font-mono">access_token</code>, autorizá tu cuenta de TikTok Business desde el portal oficial.
                      Al aprobar, el CRM guarda el token y detecta todos los advertisers disponibles automáticamente.
                    </p>
                    <div className="flex items-center gap-2">
                      <Button size="sm" onClick={handleConnectTikTok} disabled={!canConnect || connecting}>
                        <Zap size={13} className={cn('mr-1', connecting && 'animate-pulse')} />
                        {connecting ? 'Abriendo TikTok…' : 'Conectar con TikTok'}
                      </Button>
                      {!canConnect && (
                        <span className="text-[11px] text-amber-600">
                          Guarda primero el App ID y el App Secret.
                        </span>
                      )}
                    </div>
                    {connectMsg && (
                      <p className={cn(
                        'text-[11px] mt-1.5',
                        connectMsg.kind === 'ok'    && 'text-emerald-600',
                        connectMsg.kind === 'warn'  && 'text-amber-600',
                        connectMsg.kind === 'error' && 'text-red-600',
                      )}>
                        {connectMsg.text}
                      </p>
                    )}
                  </div>
                </div>
              )
            })()}

            {/* Cadencia del polling automatico — solo TikTok */}
            {provider.provider === 'tiktok' && (() => {
              const dirty = pollInterval !== pollIntervalSaved
              const invalid = !Number.isFinite(Number(pollInterval)) ||
                Number(pollInterval) < 5 || Number(pollInterval) > 60
              return (
                <div>
                  <h4 className="text-xs font-bold uppercase tracking-wide text-gray-500 mb-1">
                    Cadencia del polling automatico
                  </h4>
                  <div className="border border-gray-100 rounded-lg px-3 py-2.5">
                    <p className="text-[11px] text-gray-500 leading-snug mb-2">
                      Cada cuantos minutos el CRM consulta TikTok por leads nuevos.
                      Default: 10. Rango permitido: 5 a 60. El cambio toma efecto en
                      el siguiente ciclo (sin reiniciar el servicio).
                    </p>
                    <div className="flex items-center gap-2 flex-wrap">
                      <input
                        type="number"
                        min={5}
                        max={60}
                        value={pollInterval}
                        onChange={e => setPollInterval(e.target.value === '' ? '' : Number(e.target.value))}
                        className="w-20 h-8 px-2 rounded-md border border-gray-200 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                      />
                      <span className="text-xs text-gray-600">minutos</span>
                      <Button
                        size="sm"
                        onClick={handleSavePollInterval}
                        disabled={!dirty || invalid || pollIntervalSaving}
                      >
                        {pollIntervalSaving ? 'Guardando…' : 'Guardar'}
                      </Button>
                      {/* Presets rapidos */}
                      <div className="flex items-center gap-1 ml-auto">
                        {[5, 10, 15, 30].map(p => (
                          <button
                            key={p}
                            onClick={() => setPollInterval(p)}
                            className={cn(
                              'text-[11px] px-2 py-1 rounded border transition-colors',
                              pollInterval === p
                                ? 'border-indigo-500 bg-indigo-50 text-indigo-700'
                                : 'border-gray-200 text-gray-600 hover:bg-gray-50',
                            )}
                          >
                            {p}m
                          </button>
                        ))}
                      </div>
                    </div>
                    {pollIntervalMsg && (
                      <p className={cn(
                        'text-[11px] mt-1.5',
                        pollIntervalMsg.kind === 'ok'    && 'text-emerald-600',
                        pollIntervalMsg.kind === 'warn'  && 'text-amber-600',
                        pollIntervalMsg.kind === 'error' && 'text-red-600',
                      )}>
                        {pollIntervalMsg.text}
                      </p>
                    )}
                  </div>
                </div>
              )
            })()}

            {/* Cuentas per-account */}
            {perAccountKeys.length > 0 && (
              <div>
                <div className="flex items-center justify-between mb-1 gap-2 flex-wrap">
                  <h4 className="text-xs font-bold uppercase tracking-wide text-gray-500">
                    Cuentas registradas
                  </h4>
                  {!showAddInput && (
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => { setAddError(''); setShowAddInput(true) }}
                    >
                      <Plus size={13} className="mr-1" /> Registrar cuenta
                    </Button>
                  )}
                </div>

                {/* Form inline — solo visible tras click en "Registrar cuenta".
                    Pattern CRMs profesionales: acción primaria colapsada,
                    el form aparece al solicitarlo y vuelve a colapsarse al
                    guardar o cancelar. */}
                {showAddInput && (
                  <div className="mb-3 border border-indigo-100 bg-indigo-50/40 rounded-lg px-3 py-2.5">
                    <label className="block text-[11px] font-semibold text-gray-700 mb-1">
                      {provider.provider === 'meta' ? 'Page ID de la fan page' : 'Advertiser ID'}
                    </label>
                    <div className="flex items-center gap-2">
                      <Input
                        autoFocus
                        value={newAccount}
                        onChange={(e) => { setNewAccount(e.target.value); setAddError('') }}
                        placeholder={provider.provider === 'meta' ? 'ej. 627713130435101' : 'ej. 7123456789012345678'}
                        className={cn('h-8 flex-1 text-xs', addError && 'border-red-400 focus:border-red-500')}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') handleAddAccount()
                          if (e.key === 'Escape') cancelAddAccount()
                        }}
                      />
                      <Button size="sm" onClick={handleAddAccount} disabled={!newAccount.trim()}>
                        <Save size={13} className="mr-1" /> Guardar
                      </Button>
                      <Button size="sm" variant="outline" onClick={cancelAddAccount}>
                        Cancelar
                      </Button>
                    </div>
                    {addError && (
                      <p className="text-[11px] text-red-600 mt-1.5">{addError}</p>
                    )}
                    <p className="text-[10px] text-gray-500 mt-1.5">
                      {provider.provider === 'meta'
                        ? 'Pega el ID numérico de la página. Luego registrarás su Page Access Token y nombre abajo.'
                        : 'Pega el ID numérico del advertiser. Luego registrarás su access_token y nombre abajo.'}
                    </p>
                  </div>
                )}

                {accounts.length === 0 ? (
                  <EmptyState
                    icon={Plug}
                    title="Sin cuentas"
                    description={
                      provider.provider === 'meta'
                        ? 'Agrega el page_id de cada fan page de Facebook que quieras conectar.'
                        : 'Agrega el advertiser_id de cada cuenta de TikTok Ads.'
                    }
                  />
                ) : (
                  <div className="space-y-2">
                    {accounts.map((accId) => {
                      const idLabel = provider.provider === 'meta' ? 'Page ID' : 'Advertiser ID'
                      const idHelp = provider.provider === 'meta'
                        ? 'Identificador numérico de la fan page. Para cambiarlo, eliminá esta cuenta y registrá otra.'
                        : 'Identificador numérico del advertiser. Para cambiarlo, eliminá esta cuenta y registrá otra.'
                      return (
                        <div key={accId} className="border border-gray-100 rounded-lg px-3">
                          <div className="divide-y divide-gray-100">
                            {/* Page ID / Advertiser ID — readonly, mismo layout que KeyField */}
                            <div className="grid grid-cols-1 md:grid-cols-[1fr_auto] gap-2 items-start py-2">
                              <div>
                                <label className="block text-xs font-semibold text-gray-700">
                                  {idLabel}
                                  <span className="ml-2 text-[10px] font-normal text-gray-500 uppercase">
                                    Identificador · readonly
                                  </span>
                                </label>
                                <p className="text-[11px] text-gray-500 mt-0.5 leading-snug">{idHelp}</p>
                                <div className="mt-1">
                                  <div className="h-9 flex items-center px-3 rounded-md bg-gray-50 border border-gray-200 font-mono text-xs text-gray-700 select-all">
                                    {accId}
                                  </div>
                                </div>
                              </div>
                              <div className="flex items-center gap-2 md:pt-5">
                                <Button
                                  size="sm"
                                  variant="outline"
                                  onClick={() => setConfirmRemoveAcc(accId)}
                                  className="text-red-600 hover:text-red-700"
                                  title="Eliminar cuenta"
                                >
                                  <Trash2 size={13} />
                                </Button>
                              </div>
                            </div>
                            {perAccountKeys.map(k => (
                              <KeyField
                                key={k.key}
                                provider={provider.provider}
                                spec={k}
                                accountId={accId}
                                credential={credByKey.get(`${accId}::${k.key}`)}
                                onSaved={reloadAfterSave}
                                onDeleted={reloadAfterSave}
                              />
                            ))}
                            {provider.provider === 'meta' && (() => {
                              const patSaved = credByKey.get(`${accId}::page_access_token`)?.has_value
                              const msg = subscribeMsg[accId]
                              const isBusy = subscribing === accId
                              return (
                                <div className="py-2">
                                  <label className="block text-xs font-semibold text-gray-700">
                                    Suscripción del webhook
                                    <span className="ml-2 text-[10px] font-normal text-indigo-600 uppercase">
                                      Acción one-shot
                                    </span>
                                  </label>
                                  <p className="text-[11px] text-gray-500 mt-0.5 leading-snug">
                                    Registra esta página en la app para recibir eventos <code className="font-mono">leadgen</code>.
                                    Reemplaza el paso manual en Graph API Explorer.
                                  </p>
                                  <div className="flex items-center gap-2 mt-2">
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      onClick={() => handleSubscribeWebhook(accId)}
                                      disabled={!patSaved || isBusy}
                                      title={patSaved ? 'Suscribir esta página al webhook' : 'Guarda primero el Page Access Token'}
                                    >
                                      <Zap size={13} className="mr-1" />
                                      {isBusy ? 'Suscribiendo…' : 'Suscribir webhook'}
                                    </Button>
                                    {!patSaved && (
                                      <span className="text-[11px] text-amber-600">
                                        Guarda el Page Access Token primero.
                                      </span>
                                    )}
                                  </div>
                                  {msg && (
                                    <p className={cn(
                                      'text-[11px] mt-1.5',
                                      msg.kind === 'ok' ? 'text-emerald-600' : 'text-red-600',
                                    )}>
                                      {msg.text}
                                    </p>
                                  )}
                                </div>
                              )
                            })()}
                            {provider.provider === 'tiktok' && (() => {
                              const tokenSaved = credByKey.get(`${accId}::access_token`)?.has_value
                              const msg = pollMsg[accId]
                              const isBusy = polling === accId
                              return (
                                <div className="py-2">
                                  <label className="block text-xs font-semibold text-gray-700">
                                    Probar polling ahora
                                    <span className="ml-2 text-[10px] font-normal text-indigo-600 uppercase">
                                      Acción on-demand
                                    </span>
                                  </label>
                                  <p className="text-[11px] text-gray-500 mt-0.5 leading-snug">
                                    TikTok no manda webhooks: el CRM consulta la API por intervalos.
                                    Este botón fuerza una corrida inmediata para validar credenciales o recoger leads de prueba sin esperar al ciclo automático.
                                  </p>
                                  <div className="flex items-center gap-2 mt-2">
                                    <Button
                                      size="sm"
                                      variant="outline"
                                      onClick={() => handleManualPoll(accId)}
                                      disabled={!tokenSaved || isBusy}
                                      title={tokenSaved ? 'Disparar un polling inmediato a TikTok' : 'Guarda primero el Access Token'}
                                    >
                                      <Zap size={13} className={cn('mr-1', isBusy && 'animate-pulse')} />
                                      {isBusy ? 'Consultando TikTok…' : 'Probar ahora'}
                                    </Button>
                                    {!tokenSaved && (
                                      <span className="text-[11px] text-amber-600">
                                        Guarda el Access Token primero.
                                      </span>
                                    )}
                                  </div>
                                  {msg && (
                                    <p className={cn(
                                      'text-[11px] mt-1.5',
                                      msg.kind === 'ok'    && 'text-emerald-600',
                                      msg.kind === 'warn'  && 'text-amber-600',
                                      msg.kind === 'error' && 'text-red-600',
                                    )}>
                                      {msg.text}
                                    </p>
                                  )}

                                  {/* Backfill — para recuperar leads viejos
                                       que el polling delta no trae */}
                                  {tokenSaved && (() => {
                                    const bfMsg = backfillMsg[accId]
                                    const bfBusy = backfilling === accId
                                    const days = backfillDays[accId] ?? 30
                                    return (
                                      <div className="mt-3 pt-3 border-t border-gray-200">
                                        <label className="block text-xs font-semibold text-gray-700">
                                          Backfill manual
                                          <span className="ml-2 text-[10px] font-normal text-amber-600 uppercase">
                                            Recuperar leads históricos
                                          </span>
                                        </label>
                                        <p className="text-[11px] text-gray-500 mt-0.5 leading-snug">
                                          Trae todos los leads de los últimos N días bypaseando la
                                          lógica delta de TikTok. Útil si borraste leads por error o si
                                          otro sistema (ej. n8n viejo) ya los consumió y los quieres re-traer.
                                          Resetea el cursor del polling automático.
                                        </p>
                                        <div className="flex items-center gap-2 mt-2">
                                          <input
                                            type="number"
                                            min={1}
                                            max={90}
                                            value={days}
                                            onChange={(e) => setBackfillDays(prev => ({
                                              ...prev, [accId]: e.target.value,
                                            }))}
                                            disabled={bfBusy}
                                            className="w-20 px-2 py-1 text-xs border border-gray-300 rounded-md focus:outline-none focus:ring-1 focus:ring-amber-500"
                                            placeholder="30"
                                          />
                                          <span className="text-xs text-gray-600">días hacia atrás</span>
                                          <Button
                                            size="sm"
                                            variant="outline"
                                            onClick={() => requestBackfill(accId)}
                                            disabled={bfBusy}
                                            title="Resetear checkpoint + traer leads del rango con start_time/end_time"
                                            className="ml-auto text-amber-700 border-amber-300 hover:bg-amber-50"
                                          >
                                            <Zap size={13} className={cn('mr-1', bfBusy && 'animate-pulse')} />
                                            {bfBusy ? 'Backfilleando…' : 'Ejecutar backfill'}
                                          </Button>
                                        </div>
                                        {bfMsg && (
                                          <p className={cn(
                                            'text-[11px] mt-1.5 flex items-center gap-2 flex-wrap',
                                            bfMsg.kind === 'ok'    && 'text-emerald-600',
                                            bfMsg.kind === 'warn'  && 'text-amber-600',
                                            bfMsg.kind === 'error' && 'text-red-600',
                                          )}>
                                            <span>{bfMsg.text}</span>
                                            {bfMsg.kind === 'ok' && bfMsg.created > 0 && (
                                              <Link
                                                to="/leads?fuente=tiktok"
                                                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md bg-emerald-50 border border-emerald-200 text-emerald-700 hover:bg-emerald-100 font-medium"
                                              >
                                                Ver leads →
                                              </Link>
                                            )}
                                          </p>
                                        )}
                                      </div>
                                    )
                                  })()}
                                </div>
                              )
                            })()}
                          </div>
                        </div>
                      )
                    })}
                  </div>
                )}
              </div>
            )}

            {/* Historial de eventos */}
            <div>
              <div className="flex items-center gap-3 flex-wrap">
                <button
                  onClick={() => setShowEvents(v => !v)}
                  className="text-xs text-indigo-600 hover:text-indigo-800 font-semibold"
                >
                  {showEvents ? 'Ocultar' : 'Ver'} historial de eventos (24h)
                </button>
                {showEvents && (
                  <>
                    <button
                      onClick={() => loadEvents()}
                      className="text-xs text-gray-500 hover:text-gray-700 inline-flex items-center gap-1"
                      title="Refrescar ahora"
                    >
                      <RefreshCw size={11} className={loadingEvents ? 'animate-spin' : ''} />
                      Refrescar
                    </button>
                    {provider.provider === 'meta' && (
                      <button
                        onClick={async () => {
                          setReprocessingMeta(true)
                          try {
                            const res = await api.post('/api/integrations/meta/reprocess-skipped')
                            await loadEvents()
                            const okCount = res.data?.success || 0
                            const total = res.data?.total_skipped_found || 0
                            if (total === 0) {
                              alert('No hay leads omitidos pendientes por re-procesar.')
                            } else {
                              alert(`¡Éxito! Se han recuperado y re-procesado ${okCount} de ${total} leads omitidos. Ya figuran en tu lista de Leads.`)
                            }
                          } catch (err) {
                            alert(err.response?.data?.detail || 'Error al re-procesar leads.')
                          } finally {
                            setReprocessingMeta(false)
                          }
                        }}
                        disabled={reprocessingMeta}
                        className="text-xs bg-emerald-600 hover:bg-emerald-700 text-white font-semibold px-3 py-1 rounded-md inline-flex items-center gap-1.5 transition-colors shadow-2xs disabled:opacity-50"
                        title="Vuelve a procesar e ingestar los leads que Meta envió y fueron omitidos anteriormente por falta de teléfono"
                      >
                        <RefreshCw size={11} className={reprocessingMeta ? 'animate-spin' : ''} />
                        {reprocessingMeta ? 'Recuperando leads…' : 'Recuperar / Re-procesar leads omitidos'}
                      </button>
                    )}
                    {eventsRefreshedAt && (
                      <span className="text-[10px] text-gray-400">
                        Actualizado {eventsRefreshedAt.toLocaleTimeString('es-PE', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })} · auto cada 15s
                      </span>
                    )}
                  </>
                )}
              </div>
              {showEvents && (
                <div className="mt-2 border border-gray-100 rounded-lg overflow-hidden">
                  {loadingEvents ? (
                    <LoadingSpinner />
                  ) : events.length === 0 ? (
                    <div className="text-xs text-gray-500 p-3 text-center">Sin eventos recientes.</div>
                  ) : (
                    <table className="w-full text-xs">
                      <thead className="bg-gray-50">
                        <tr>
                          <th className="text-left py-2 px-2 font-medium text-gray-500">Hora</th>
                          <th className="text-left py-2 px-2 font-medium text-gray-500">Tipo</th>
                          <th className="text-left py-2 px-2 font-medium text-gray-500">Estado</th>
                          <th className="text-left py-2 px-2 font-medium text-gray-500">Cuenta</th>
                          <th className="text-left py-2 px-2 font-medium text-gray-500">Detalle</th>
                        </tr>
                      </thead>
                      <tbody>
                        {events.map(e => (
                          <tr key={e.id} className="border-t border-gray-100">
                            <td className="py-1.5 px-2 text-gray-600 whitespace-nowrap">
                              {formatDateTime(e.created_at)}
                            </td>
                            <td className="py-1.5 px-2 font-mono text-[10px] text-gray-700">
                              {e.event_type}
                            </td>
                            <td className="py-1.5 px-2">
                              <span className={
                                e.status === 'ok' ? 'text-emerald-600' :
                                e.status === 'error' ? 'text-red-600' : 'text-amber-600'
                              }>
                                {e.status}
                              </span>
                            </td>
                            <td className="py-1.5 px-2 font-mono text-[10px] text-gray-500">
                              {e.account_id || '—'}
                            </td>
                            <td className="py-1.5 px-2 text-gray-600 max-w-md truncate">
                              {e.error_message || e.external_id || '—'}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )}
                </div>
              )}
            </div>
          </>
        )}
      </CardContent>
      <ConfirmDialog
        open={!!confirmRemoveAcc}
        title="Eliminar cuenta"
        message={`¿Seguro que quieres eliminar todas las credenciales de la cuenta "${confirmRemoveAcc}"? Esta acción borra el Page Access Token, el nombre y desvincula la cuenta del CRM. No se puede deshacer.`}
        confirmLabel="Eliminar cuenta"
        onConfirm={() => handleRemoveAccount(confirmRemoveAcc)}
        onCancel={() => setConfirmRemoveAcc(null)}
      />

      <ConfirmDialog
        open={!!backfillConfirm}
        variant="warning"
        title={`Backfill de ${backfillConfirm?.days ?? ''} días`}
        message={
          `Esto va a:\n\n` +
          `• Resetear el cursor de polling automático de este advertiser.\n` +
          `• Pedir a TikTok TODOS los leads de los últimos ${backfillConfirm?.days ?? ''} días, ignorando su lógica delta.\n` +
          `• Insertar los nuevos en el CRM (los duplicados se omiten).\n\n` +
          `Es una operación segura: no borra nada, solo trae datos. ¿Continuar?`
        }
        confirmLabel="Ejecutar backfill"
        cancelLabel="Cancelar"
        onConfirm={executeBackfill}
        onCancel={() => setBackfillConfirm(null)}
      />
    </Card>
  )
}

/* ─────────────────────────────────────────────────────────────────────── */
/* Página                                                                  */
/* ─────────────────────────────────────────────────────────────────────── */

// Mapea cada proveedor al icono/label de su tab. Si agregas uno nuevo en
// el registry del backend, completa esta tabla para que salga en la UI.
const PROVIDER_TAB_META = {
  meta:   { label: 'Meta',   icon: Layers },
  tiktok: { label: 'TikTok', icon: Music2 },
}

/**
 * Banner de acceso al panel de "Propiedades & Mapeos" (patrón estándar).
 * Se muestra en la tab de Meta y destaca cuando hay campos sin mapear.
 */
function FieldMappingsBanner() {
  const [unmapped, setUnmapped] = useState(null)

  useEffect(() => {
    let cancelled = false
    api.get('/api/integrations/field-mappings/unmapped', {
      params: { provider: 'meta', days_back: 90, limit: 200 },
    }).then(res => {
      if (!cancelled) setUnmapped(res.data?.total ?? 0)
    }).catch(() => {
      if (!cancelled) setUnmapped(0)
    })
    return () => { cancelled = true }
  }, [])

  const hasUnmapped = unmapped != null && unmapped > 0

  return (
    <Link
      to="/integraciones/campos"
      className={cn(
        'group flex items-center gap-3 rounded-xl border p-4 mb-4 transition-all',
        hasUnmapped
          ? 'border-amber-200 bg-amber-50/60 hover:border-amber-300 hover:shadow-sm'
          : 'border-gray-200 bg-white hover:border-[var(--brand-primary)] hover:shadow-sm'
      )}
    >
      <div
        className={cn(
          'w-10 h-10 rounded-lg flex items-center justify-center shrink-0',
          hasUnmapped ? 'bg-amber-100' : 'bg-gray-50'
        )}
      >
        <SlidersHorizontal
          size={18}
          className={hasUnmapped ? 'text-amber-700' : 'text-gray-700'}
        />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <h3 className="text-sm font-semibold text-gray-900">
            Propiedades & Mapeos de Campos
          </h3>
          <span className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-violet-50 text-violet-700 text-[10px] font-medium ring-1 ring-violet-200">
            <Sparkles size={10} /> Avanzado
          </span>
          {hasUnmapped && (
            <span className="inline-flex items-center px-1.5 py-0.5 rounded bg-amber-100 text-amber-800 text-[10px] font-semibold ring-1 ring-amber-200">
              {unmapped} sin mapear
            </span>
          )}
        </div>
        <p className="text-xs text-gray-500 mt-0.5">
          {hasUnmapped
            ? 'Hay campos nuevos detectados en formularios de Meta que aún no tienen una regla asignada.'
            : 'Gestiona propiedades custom y define cómo se mapean los campos de formularios al CRM.'}
        </p>
      </div>
      <ChevronRight size={18} className="text-gray-400 shrink-0 group-hover:translate-x-0.5 transition-transform" />
    </Link>
  )
}

const WHATSAPP_TAB_ID = 'whatsapp'
const API_CLIENTS_TAB_ID = 'api-clients'

export default function Integraciones() {
  const [providers, setProviders] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const tabs = useMemo(() => {
    const providerTabs = providers.map(p => ({
      id: p.provider,
      label: PROVIDER_TAB_META[p.provider]?.label || p.label || p.provider,
      icon: PROVIDER_TAB_META[p.provider]?.icon || Plug,
      kind: 'provider',
    }))
    return [
      ...providerTabs,
      { id: WHATSAPP_TAB_ID, label: 'WhatsApp Business', icon: MessageCircle, kind: 'whatsapp' },
      { id: API_CLIENTS_TAB_ID, label: 'Proveedores externos', icon: Plug, kind: 'api-clients' },
    ]
  }, [providers])

  const [tab, setTab] = useState(() => {
    const params = new URLSearchParams(window.location.search)
    return params.get('tab') || ''
  })

  const loadProviders = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.get('/api/integrations/providers')
      setProviders(res.data?.items || [])
      setError(null)
    } catch (err) {
      setError(err.response?.data?.detail || 'Error cargando proveedores.')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => { loadProviders() }, [loadProviders])

  // Si no hay tab seleccionada (o la pedida ya no existe), fija la primera.
  // Esperamos a que terminen de cargar los providers: si corremos antes,
  // `tabs` solo contiene el WhatsApp hardcodeado y se auto-selecciona
  // whatsapp como default — no lo que el usuario espera (empieza en Meta).
  useEffect(() => {
    if (loading) return
    if (!tabs.length) return
    if (!tab || !tabs.some(t => t.id === tab)) {
      setTab(tabs[0].id)
    }
  }, [tabs, tab, loading])

  const changeTab = (next) => {
    setTab(next)
    const params = new URLSearchParams(window.location.search)
    params.set('tab', next)
    window.history.replaceState({}, '', `${window.location.pathname}?${params.toString()}`)
    // Scroll-to-top del main cuando cambia el tab, para que el header
    // y las primeras filas del nuevo proveedor siempre queden visibles.
    const mainEl = document.querySelector('main')
    if (mainEl) mainEl.scrollTo({ top: 0, behavior: 'instant' })
    else window.scrollTo({ top: 0, behavior: 'instant' })
  }

  const activeProvider = providers.find(p => p.provider === tab)
  const isProviderTab = !!activeProvider
  const isWhatsAppTab = tab === WHATSAPP_TAB_ID
  const isApiClientsTab = tab === API_CLIENTS_TAB_ID
  const activeTabMeta = tabs.find(t => t.id === tab)
  const TabIcon = activeTabMeta?.icon || Plug

  const tabDescription = (() => {
    if (isWhatsAppTab) return 'Configura tu número de WhatsApp Business y el token de Evolution API.'
    if (isApiClientsTab) return 'Genera API keys individuales para agencias, portales y partners. Cada lead queda atribuído al proveedor que lo envió.'
    if (isProviderTab) {
      return activeProvider?.description
        || `Credenciales y cuentas conectadas a ${activeTabMeta?.label || 'este proveedor'}.`
    }
    return 'Conecta Meta, TikTok Ads y WhatsApp Business al CRM.'
  })()

  return (
    <div className="p-6 max-w-5xl mx-auto">
      {/* Breadcrumb — el shell ya muestra "PDR › Integraciones", por eso
          arrancamos desde el proveedor activo. */}
      {activeTabMeta && (
        <nav className="flex items-center gap-1.5 text-xs text-gray-500 mb-3" aria-label="Ruta de navegación">
          <span className="text-gray-700 font-medium">{activeTabMeta.label}</span>
        </nav>
      )}

      {/* Encabezado premium dinámico: refleja el tab activo. */}
      <div className="flex items-start gap-3 pb-5 mb-6 border-b border-gray-100">
        <div
          className="w-11 h-11 rounded-xl flex items-center justify-center shrink-0"
          style={{ backgroundColor: 'rgba(var(--brand-primary-rgb), 0.1)' }}
        >
          <TabIcon size={20} style={{ color: 'var(--brand-primary)' }} />
        </div>
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-semibold text-gray-900 leading-tight">
            {activeTabMeta?.label || 'Integraciones'}
          </h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {tabDescription}
          </p>
        </div>
        {isProviderTab && (
          <Button variant="outline" size="sm" onClick={loadProviders} disabled={loading}>
            <RefreshCw size={14} className={loading ? 'animate-spin mr-2' : 'mr-2'} />
            Refrescar
          </Button>
        )}
      </div>

      <div className="border-b border-gray-200 flex items-center gap-1 overflow-x-auto mb-4">
        {tabs.map(t => {
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

      {/* Acceso al panel patrón estándar solo en el tab Meta (único
          proveedor con mapeos configurables por ahora). */}
      {tab === 'meta' && <FieldMappingsBanner />}

      {/* Framing premium del contenido. ProviderCard trae su propio
          <Card/> con el mismo estilo, por eso lo dejamos sin wrapper
          extra para evitar cards anidadas. WhatsApp sí se envuelve. */}
      {isProviderTab && (
        loading && providers.length === 0 ? (
          <Card><CardContent className="p-8"><LoadingSpinner /></CardContent></Card>
        ) : error ? (
          <Card><CardContent className="p-6 text-red-500 text-sm">{error}</CardContent></Card>
        ) : (
          <ProviderCard provider={activeProvider} />
        )
      )}

      {isWhatsAppTab && (
        <div className="bg-white border border-gray-100 rounded-xl shadow-sm p-5 sm:p-7">
          <WhatsAppSettings />
        </div>
      )}

      {/* API Clients (multi-tenant) — embed inline cuando la tab esta activa */}
      {isApiClientsTab && <ApiClients embedded />}
    </div>
  )
}
