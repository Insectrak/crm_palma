/**
 * ApiClients.jsx — Gestion de proveedores externos via API key.
 *
 * Patron apps conectadas (patrón estándar) / apps privadas (patrón estándar):
 * cada proveedor tiene su propia key, fuente fija, rate limit, IP whitelist
 * y trazabilidad por lead.
 *
 * SEGURIDAD UI:
 *   - La key plain SOLO se muestra al crear/regenerar (modal "guarda ahora").
 *   - Despues solo se ve el prefix (cli_xxxxxxxx).
 *   - Boton "copiar" con feedback visual.
 *   - Confirm dialog antes de regenerar (rompe integraciones activas) y revocar.
 */
import React, { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Plug, Plus, Copy, Check, Trash2, RefreshCw, Power, Shield,
  AlertTriangle, BarChart3, Eye, EyeOff, Activity, Lock,
  X as XIcon, Edit2, AlertCircle, BookOpen, Terminal, Webhook,
  ExternalLink, Unlink,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import Switch from '@/components/ui/switch'
import { Card, CardContent } from '@/components/ui/card'
import LoadingSpinner from '@/components/shared/LoadingSpinner'
import ConfirmDialog from '@/components/shared/ConfirmDialog'
import InfoDialog from '@/components/shared/InfoDialog'
import api from '@/lib/api'

const RATE_PRESETS = [
  { v: 30,  label: '30/min — bajo' },
  { v: 60,  label: '60/min — normal' },
  { v: 120, label: '120/min — alto' },
  { v: 300, label: '300/min — masivo' },
]

export default function ApiClients({ embedded = false }) {
  const navigate = useNavigate()
  const [clients, setClients]     = useState([])
  const [fuentes, setFuentes]     = useState([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState(null)

  // Modales
  const [showForm, setShowForm]         = useState(false)
  const [editing, setEditing]           = useState(null)
  const [showSecret, setShowSecret]     = useState(null)   // {key, client}
  const [confirmRegen, setConfirmRegen] = useState(null)
  const [confirmRevoke, setConfirmRevoke] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(null)
  const [confirmUnlink, setConfirmUnlink] = useState(null) // V061: desvincular leads
  const [statsClient, setStatsClient]   = useState(null)
  const [webhookClient, setWebhookClient] = useState(null)   // V060: modal independiente
  const [showDoc, setShowDoc]           = useState(false)
  const [curlClient, setCurlClient]     = useState(null)
  // V061: InfoDialog premium reemplaza alert() nativo en errores recuperables
  const [infoDialog, setInfoDialog]     = useState(null)    // {variant, title, message}

  // V075.x — refs para los modales que abren panel grande (stats, webhook,
  // doc, curl) para que el auto-refresh silencioso no pise estados focales.
  // Los modales chicos (regenerar/revocar/borrar) son rapidos y NO bloquean.
  const blockingRef = useRef(false)
  // V076.x — timestamp del ultimo refresh exitoso + IDs que cambiaron en el
  // ultimo tick para resaltar filas (UX paridad patrón premium: "ves" que algo paso).
  const [lastSyncAt, setLastSyncAt] = useState(null)
  const [changedIds, setChangedIds] = useState(() => new Set())
  const prevClientsRef = useRef([])

  const load = useCallback(async ({ silent = false } = {}) => {
    if (!silent) setLoading(true)
    try {
      const [c, f] = await Promise.all([
        api.get('/api/admin/api-clients'),
        api.get('/api/fuentes'),
      ])
      const next = c.data || []
      // Detectar filas cuyo total_leads o ultimo_lead_at cambiaron desde
      // el ultimo poll. Solo lo hacemos en refreshes silenciosos para no
      // resaltar todo en el load inicial.
      if (silent) {
        const prevById = new Map((prevClientsRef.current || []).map(x => [x.id, x]))
        const diff = new Set()
        for (const row of next) {
          const prev = prevById.get(row.id)
          if (!prev) continue
          if ((prev.total_leads || 0) !== (row.total_leads || 0)) diff.add(row.id)
          else if ((prev.ultimo_lead_at || null) !== (row.ultimo_lead_at || null)) diff.add(row.id)
        }
        if (diff.size > 0) {
          setChangedIds(diff)
          // Limpiar el highlight a los 2.5s (suficiente para que el ojo lo capte).
          setTimeout(() => setChangedIds(new Set()), 2500)
        }
      }
      prevClientsRef.current = next
      setClients(next)
      setFuentes(f.data || [])
      setLastSyncAt(Date.now())
      setError(null)
    } catch (err) {
      // Silent refresh NO debe sobrescribir el banner de error visible: si
      // ya hay data en pantalla preferimos ignorar un blip de red y dejar
      // la UI tal cual. Solo escalamos el error en el load inicial.
      if (!silent) {
        setError(err.response?.data?.detail || 'Error al cargar')
      }
    } finally {
      if (!silent) setLoading(false)
    }
  }, [])

  useEffect(() => { load() }, [load])

  // Auto-refresh silencioso (10 s) para que el conteo de leads, "ultimo lead"
  // y badge de estado se actualicen sin que el admin recargue la pagina.
  // Pausamos cuando:
  //   - La tab no esta visible (battery / red).
  //   - Hay un modal de panel grande abierto — son flows con foco.
  const REFRESH_MS = 10_000
  useEffect(() => {
    blockingRef.current = !!(
      statsClient || webhookClient || curlClient || showDoc || showForm || showSecret
    )
  }, [statsClient, webhookClient, curlClient, showDoc, showForm, showSecret])

  useEffect(() => {
    let timerId = null
    const tick = () => {
      if (document.hidden) return
      if (blockingRef.current) return
      load({ silent: true })
    }
    timerId = setInterval(tick, REFRESH_MS)
    // Refresh inmediato al volver el foco a la tab — UX premium tipo patrón premium.
    const onVisible = () => { if (!document.hidden && !blockingRef.current) load({ silent: true }) }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('focus', onVisible)
    return () => {
      if (timerId) clearInterval(timerId)
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('focus', onVisible)
    }
  }, [load])

  const handleSave = async (form) => {
    try {
      if (editing) {
        await api.patch(`/api/admin/api-clients/${editing.id}`, {
          nombre: form.nombre,
          fuente_id: form.fuente_id,
          rate_limit_per_minute: form.rate_limit_per_minute,
          ip_whitelist: form.ip_whitelist,
          contacto_email: form.contacto_email,
          contacto_telefono: form.contacto_telefono,
          notas: form.notas,
          activo: form.activo,
        })
        setShowForm(false)
        setEditing(null)
        load()
      } else {
        const r = await api.post('/api/admin/api-clients', form)
        setShowForm(false)
        // Mostrar la key plana UNA SOLA VEZ
        setShowSecret({ key: r.data.api_key_plain, client: r.data })
        load()
      }
    } catch (err) {
      setInfoDialog({
        variant: 'error',
        title: 'No se pudo guardar',
        message: err.response?.data?.detail || 'Error al guardar el proveedor.',
      })
    }
  }

  const handleRegenerate = async () => {
    if (!confirmRegen) return
    try {
      const r = await api.post(`/api/admin/api-clients/${confirmRegen.id}/regenerate`)
      setConfirmRegen(null)
      setShowSecret({ key: r.data.api_key_plain, client: r.data, isRegen: true })
      load()
    } catch (err) {
      setInfoDialog({
        variant: 'error',
        title: 'No se pudo regenerar la key',
        message: err.response?.data?.detail || 'Error al regenerar.',
      })
    }
  }

  const handleRevoke = async () => {
    if (!confirmRevoke) return
    try {
      await api.post(`/api/admin/api-clients/${confirmRevoke.id}/revoke`)
      setConfirmRevoke(null)
      load()
    } catch (err) {
      setInfoDialog({
        variant: 'error',
        title: 'No se pudo revocar',
        message: err.response?.data?.detail || 'Error al revocar.',
      })
    }
  }

  const handleDelete = async () => {
    if (!confirmDelete) return
    const clientToDelete = confirmDelete   // capturar antes de setNull
    try {
      await api.delete(`/api/admin/api-clients/${clientToDelete.id}`)
      setConfirmDelete(null)
      load()
    } catch (err) {
      setConfirmDelete(null)
      const detail = err.response?.data?.detail || 'Error al eliminar'
      // V061: caso especial — el backend bloquea con 409 cuando hay leads
      // asociados. En vez de mostrar el alert feo, ofrecemos accion clara:
      // "Desvincular y eliminar" o "Cancelar".
      if (err.response?.status === 409 && detail.includes('leads asociados')) {
        setInfoDialog({
          variant: 'warning',
          title: 'No se puede eliminar todavía',
          message: [
            detail,
            'Tienes 2 opciones:',
            '1) Revocá la key (icono ⏻) — mantiene los leads vinculados al proveedor (recomendado)',
            '2) Desvinculá los leads (icono 🔗 en la fila del proveedor) y después podrás eliminar',
          ],
        })
      } else {
        setInfoDialog({
          variant: 'error',
          title: 'No se pudo eliminar',
          message: detail,
        })
      }
    }
  }

  // V061: desvincular leads del proveedor (api_client_id = NULL en bulk)
  const handleUnlinkLeads = async () => {
    if (!confirmUnlink) return
    const target = confirmUnlink
    try {
      const r = await api.post(`/api/admin/api-clients/${target.id}/unlink-leads`)
      setConfirmUnlink(null)
      load()
      setInfoDialog({
        variant: 'success',
        title: 'Leads desvinculados',
        message: [
          `Se desvincularon ${r.data?.unlinked || 0} leads del proveedor "${target.nombre}".`,
          'Los leads siguen activos pero ya no tienen atribución comercial al proveedor.',
          'Ahora puedes eliminar el proveedor con el botón 🗑.',
        ],
      })
    } catch (err) {
      setConfirmUnlink(null)
      setInfoDialog({
        variant: 'error',
        title: 'No se pudieron desvincular',
        message: err.response?.data?.detail || 'Error al desvincular leads.',
      })
    }
  }

  return (
    <div className={embedded ? 'space-y-4' : 'space-y-5 max-w-7xl'}>
      {/* Header solo en modo standalone — embed reutiliza el header de Integraciones */}
      {!embedded && (
        <div className="flex items-center justify-between gap-3 flex-wrap">
          <div>
            <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
              <Plug size={22} className="text-indigo-500" /> Proveedores externos (API)
            </h1>
            <p className="text-sm text-gray-400 mt-0.5">
              Cada proveedor tiene su propia API key, fuente asignada, rate limit y trazabilidad por lead.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => setShowDoc(true)} className="gap-1.5">
              <BookOpen size={14} /> Documentación
            </Button>
            <Button onClick={() => { setEditing(null); setShowForm(true) }} className="gap-1.5">
              <Plus size={14} /> Nuevo proveedor
            </Button>
          </div>
        </div>
      )}
      {embedded && (
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={() => setShowDoc(true)} className="gap-1.5">
            <BookOpen size={14} /> Documentación
          </Button>
          <Button onClick={() => { setEditing(null); setShowForm(true) }} size="sm" className="gap-1.5">
            <Plus size={14} /> Nuevo proveedor
          </Button>
        </div>
      )}

      {/* Aviso de seguridad */}
      <div className="bg-indigo-50 border border-indigo-100 rounded-lg p-3 text-xs flex items-start gap-2">
        <Shield size={14} className="text-indigo-600 shrink-0 mt-0.5" />
        <div className="text-indigo-800">
          <strong>Seguridad:</strong> guardamos solo el hash SHA-256 de cada key. La clave plana se muestra
          una única vez al crearla o regenerarla — no podemos recuperarla después. Cada lead queda
          trazado al proveedor que lo envió.
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700 flex items-center gap-2">
          <AlertCircle size={14} /> {error}
        </div>
      )}

      {/* V076.x: indicador "live" del auto-refresh + boton manual. Patron herramientas premium:
          el usuario ve que la lista se mantiene fresca sin recargar la página. */}
      {!loading && clients.length > 0 && (
        <div className="flex items-center justify-between gap-2 text-xs text-gray-500">
          <LiveSyncIndicator lastSyncAt={lastSyncAt} />
          <button
            type="button"
            onClick={() => load({ silent: true })}
            className="inline-flex items-center gap-1 text-gray-500 hover:text-indigo-600 font-medium px-2 py-1 rounded-md hover:bg-indigo-50 transition-colors"
            title="Actualizar ahora"
          >
            <RefreshCw size={12} /> Actualizar
          </button>
        </div>
      )}

      {loading ? <LoadingSpinner /> : (
        <Card>
          <CardContent className="p-0">
            {clients.length === 0 ? (
              <div className="p-12 text-center">
                <Plug size={36} className="mx-auto text-gray-300 mb-2" />
                <p className="text-sm text-gray-500 mb-3">Aún no hay proveedores externos configurados.</p>
                <Button size="sm" onClick={() => { setEditing(null); setShowForm(true) }} className="gap-1.5">
                  <Plus size={14} /> Crear primer proveedor
                </Button>
              </div>
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-gray-50 border-b border-gray-100">
                      <th className="text-left px-4 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Proveedor</th>
                      <th className="text-left px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">API Key</th>
                      <th className="text-left px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Fuente</th>
                      <th className="text-left px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Leads</th>
                      <th className="text-left px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Rate</th>
                      <th className="text-left px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Último lead</th>
                      <th className="text-left px-3 py-3 text-xs font-semibold text-gray-500 uppercase tracking-wide">Estado</th>
                      <th className="px-3 py-3"></th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-50">
                    {clients.map(c => (
                      <ClientRow
                        key={c.id}
                        client={c}
                        highlight={changedIds.has(c.id)}
                        onEdit={() => { setEditing(c); setShowForm(true) }}
                        onRegen={() => setConfirmRegen(c)}
                        onRevoke={() => setConfirmRevoke(c)}
                        onDelete={() => setConfirmDelete(c)}
                        onUnlink={() => setConfirmUnlink(c)}
                        onStats={() => setStatsClient(c)}
                        onCurl={() => setCurlClient(c)}
                        onWebhook={() => setWebhookClient(c)}
                      />
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </CardContent>
        </Card>
      )}

      {/* Modal crear/editar */}
      {showForm && (
        <ClientFormModal
          editing={editing}
          fuentes={fuentes}
          onClose={() => { setShowForm(false); setEditing(null) }}
          onSave={handleSave}
        />
      )}

      {/* Modal "key recien creada — copiala ahora" */}
      {showSecret && (
        <SecretRevealModal
          secret={showSecret.key}
          client={showSecret.client}
          isRegen={showSecret.isRegen}
          onClose={() => setShowSecret(null)}
        />
      )}

      {/* Stats panel — solo analytics + logs (V060: webhook se movio a modal propio) */}
      {statsClient && (
        <StatsModal
          client={statsClient}
          onClose={() => setStatsClient(null)}
          // V061: deep-link a Leads filtrados por este proveedor
          onViewLeads={() => {
            const id = statsClient.id
            setStatsClient(null)
            navigate(`/leads?api_client_id=${id}`)
          }}
        />
      )}

      {/* V060: Webhook config — modal independiente, patron APIs profesionales */}
      {webhookClient && (
        <WebhookModal
          client={webhookClient}
          onClose={() => setWebhookClient(null)}
          onClientUpdate={(updated) => {
            setWebhookClient(updated)
            setClients(list => list.map(c => c.id === updated.id ? updated : c))
          }}
        />
      )}

      {/* Documentacion del API */}
      {showDoc && (
        <DocViewerModal onClose={() => setShowDoc(false)} />
      )}

      {/* Curl ejemplo por proveedor */}
      {curlClient && (
        <CurlExampleModal client={curlClient} onClose={() => setCurlClient(null)} />
      )}

      <ConfirmDialog
        open={!!confirmRegen}
        title="Regenerar API key"
        message={confirmRegen
          ? `Vas a regenerar la key de "${confirmRegen.nombre}". La key actual quedará invalidada al instante y todas las integraciones que la usen dejarán de funcionar hasta actualizar.\n\n¿Continuar?`
          : ''}
        onConfirm={handleRegenerate}
        onCancel={() => setConfirmRegen(null)}
      />
      <ConfirmDialog
        open={!!confirmRevoke}
        title="Revocar acceso"
        message={confirmRevoke
          ? `Vas a revocar a "${confirmRevoke.nombre}". La key dejará de funcionar de inmediato. El historial de leads y logs se conserva.\n\n¿Confirmar?`
          : ''}
        onConfirm={handleRevoke}
        onCancel={() => setConfirmRevoke(null)}
      />
      <ConfirmDialog
        open={!!confirmDelete}
        title="Eliminar proveedor"
        message={confirmDelete
          ? `Eliminar definitivamente a "${confirmDelete.nombre}". Solo se permite si no tiene leads asociados — si los tiene, usa Revocar.`
          : ''}
        onConfirm={handleDelete}
        onCancel={() => setConfirmDelete(null)}
      />

      {/* V061: Confirmación destructiva para desvincular leads */}
      <ConfirmDialog
        open={!!confirmUnlink}
        title="Desvincular leads del proveedor"
        confirmLabel="Sí, desvincular"
        cancelLabel="Cancelar"
        variant="danger"
        message={confirmUnlink
          ? `Vas a desvincular TODOS los leads del proveedor "${confirmUnlink.nombre}".\n\n• Los leads NO se borran (asesor, estado, contactos quedan intactos).\n• El nombre y slug del proveedor quedan registrados como "Proveedor original" en cada lead — vas a poder filtrarlos después.\n• Esto permite eliminar el proveedor del catálogo activo.`
          : ''}
        onConfirm={handleUnlinkLeads}
        onCancel={() => setConfirmUnlink(null)}
      />

      {/* V061: InfoDialog premium reemplaza alert() nativo */}
      <InfoDialog
        open={!!infoDialog}
        variant={infoDialog?.variant}
        title={infoDialog?.title}
        message={infoDialog?.message}
        onClose={() => setInfoDialog(null)}
      />
    </div>
  )
}

// ─── Indicador "live" del auto-refresh ───────────────────────────────────
// V076.x: muestra "Actualizado ahora", "hace Xs", etc. con un punto verde
// que pulsa cuando un poll esta corriendo. Patron patrón premium / patrón premium / patrón estándar.

function LiveSyncIndicator({ lastSyncAt }) {
  // Re-calculamos el label en un effect (no en render) para no romper la
  // pureza del componente — el reloj se actualiza vía setInterval.
  const [display, setDisplay] = useState({ label: 'Sincronizando…', pulse: true })
  useEffect(() => {
    const recompute = () => {
      if (!lastSyncAt) {
        setDisplay({ label: 'Sincronizando…', pulse: true })
        return
      }
      const ageMs = Date.now() - lastSyncAt
      if (ageMs < 1500)         setDisplay({ label: 'Actualizado ahora', pulse: true })
      else if (ageMs < 60_000)  setDisplay({ label: `Actualizado hace ${Math.round(ageMs/1000)}s`, pulse: false })
      else                      setDisplay({ label: `Actualizado hace ${Math.round(ageMs/60_000)}m`, pulse: false })
    }
    recompute()
    const id = setInterval(recompute, 1000)
    return () => clearInterval(id)
  }, [lastSyncAt])
  return (
    <div className="inline-flex items-center gap-1.5">
      <span className="relative flex h-2 w-2">
        {display.pulse && (
          <span className="absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75 animate-ping" />
        )}
        <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500" />
      </span>
      <span>{display.label} · auto cada 10s</span>
    </div>
  )
}


// ─── Fila de la tabla ────────────────────────────────────────────────────

function ClientRow({ client, highlight, onEdit, onRegen, onRevoke, onDelete, onUnlink, onStats, onCurl, onWebhook }) {
  const isRevoked = !!client.revoked_at
  const isInactive = !client.activo
  const dedupeRate = client.total_leads > 0
    ? Math.round(client.leads_duplicados * 100 / (client.total_leads + client.leads_duplicados))
    : 0
  return (
    <tr className={[
      'hover:bg-gray-50/50 transition-colors duration-700',
      isRevoked ? 'opacity-60' : '',
      // V076.x: flash sutil cuando el contador cambia en el poll silencioso.
      highlight ? 'bg-emerald-50 ring-1 ring-emerald-200' : '',
    ].filter(Boolean).join(' ')}>
      <td className="px-4 py-3">
        <div className="flex items-center gap-2.5">
          <div className="w-9 h-9 rounded-lg bg-indigo-50 text-indigo-600 flex items-center justify-center shrink-0">
            <Plug size={15} />
          </div>
          <div className="min-w-0">
            <p className="font-medium text-gray-800 truncate">{client.nombre}</p>
            <span className="text-[10px] text-gray-400">{client.slug}</span>
          </div>
        </div>
      </td>
      <td className="px-3 py-3">
        <code className="text-[11px] font-mono bg-gray-100 text-gray-700 px-1.5 py-0.5 rounded">
          {client.api_key_prefix}…
        </code>
      </td>
      <td className="px-3 py-3 text-xs text-gray-700">
        {client.fuente_nombre || '—'}
      </td>
      <td className="px-3 py-3">
        <div className="flex items-baseline gap-1">
          <span className="text-sm font-bold text-gray-800">{client.total_leads || 0}</span>
          {dedupeRate > 0 && (
            <span className="text-[10px] text-gray-400" title={`${client.leads_duplicados} duplicados`}>
              · {dedupeRate}% dup
            </span>
          )}
        </div>
      </td>
      <td className="px-3 py-3 text-xs text-gray-500">{client.rate_limit_per_minute}/min</td>
      <td className="px-3 py-3 text-xs text-gray-500">
        {client.ultimo_lead_at ? formatRelative(client.ultimo_lead_at) : '—'}
      </td>
      <td className="px-3 py-3">
        {isRevoked ? (
          <span className="text-[10px] bg-red-50 text-red-700 border border-red-200 px-1.5 py-0.5 rounded font-semibold">REVOCADA</span>
        ) : isInactive ? (
          <span className="text-[10px] bg-gray-50 text-gray-600 border border-gray-200 px-1.5 py-0.5 rounded font-semibold">INACTIVA</span>
        ) : (
          <span className="text-[10px] bg-emerald-50 text-emerald-700 border border-emerald-200 px-1.5 py-0.5 rounded font-semibold">ACTIVA</span>
        )}
      </td>
      <td className="px-3 py-3 text-right whitespace-nowrap">
        <button onClick={onCurl} className="p-1.5 rounded hover:bg-emerald-50 text-gray-400 hover:text-emerald-500" title="Ver ejemplo curl">
          <Terminal size={13} />
        </button>
        <button onClick={onStats} className="p-1.5 rounded hover:bg-purple-50 text-gray-400 hover:text-purple-500" title="Ver stats">
          <BarChart3 size={13} />
        </button>
        {/* V060: Webhook config — modal independiente. Punto verde si está
            habilitado, gris si está apagado o sin configurar. Patron
            APIs profesionales: webhooks como entrada de primer nivel. */}
        <button
          onClick={onWebhook}
          className={`p-1.5 rounded hover:bg-sky-50 transition-colors relative ${
            client.webhook_enabled
              ? 'text-sky-600 hover:text-sky-700'
              : 'text-gray-400 hover:text-sky-500'
          }`}
          title={client.webhook_enabled ? 'Webhook activo — configurar' : 'Configurar webhook'}
        >
          <Webhook size={13} />
          {client.webhook_enabled && (
            <span className="absolute top-0.5 right-0.5 w-1.5 h-1.5 bg-emerald-500 rounded-full ring-1 ring-white" />
          )}
        </button>
        <button onClick={onEdit} className="p-1.5 rounded hover:bg-indigo-50 text-gray-400 hover:text-indigo-500" title="Editar">
          <Edit2 size={13} />
        </button>
        {!isRevoked && (
          <button onClick={onRegen} className="p-1.5 rounded hover:bg-amber-50 text-gray-400 hover:text-amber-500" title="Regenerar key">
            <RefreshCw size={13} />
          </button>
        )}
        {!isRevoked && (
          <button onClick={onRevoke} className="p-1.5 rounded hover:bg-orange-50 text-gray-400 hover:text-orange-500" title="Revocar acceso">
            <Power size={13} />
          </button>
        )}
        {/* V062: Desvincular leads — solo aparece si hay leads vinculados.
            Patron: las acciones admin viven todas en la fila del proveedor
            (no en el modal de Stats, que es read-only). Color ambar para
            diferenciarlo del Eliminar (rojo) — son acciones distintas. */}
        {(client.total_leads || 0) > 0 && (
          <button
            onClick={onUnlink}
            className="p-1.5 rounded hover:bg-amber-50 text-gray-400 hover:text-amber-600"
            title={`Desvincular los ${client.total_leads} leads del proveedor (snapshot legacy + permite eliminar)`}
          >
            <Unlink size={13} />
          </button>
        )}
        <button onClick={onDelete} className="p-1.5 rounded hover:bg-red-50 text-gray-400 hover:text-red-500" title="Eliminar">
          <Trash2 size={13} />
        </button>
      </td>
    </tr>
  )
}

// ─── Modal: crear / editar ────────────────────────────────────────────────

function ClientFormModal({ editing, fuentes, onClose, onSave }) {
  const [form, setForm] = useState(() => ({
    nombre: editing?.nombre || '',
    slug: editing?.slug || '',
    fuente_id: editing?.fuente_id || (fuentes[0]?.id ?? ''),
    rate_limit_per_minute: editing?.rate_limit_per_minute || 60,
    ip_whitelist: editing?.ip_whitelist?.join('\n') || '',
    contacto_email: editing?.contacto_email || '',
    contacto_telefono: editing?.contacto_telefono || '',
    notas: editing?.notas || '',
    activo: editing?.activo ?? true,
    sede_id_default: editing?.sede_id_default || '',  // V065
  }))

  // V065: catalogo de sedes (lookup publico). Si no hay sedes, el
  // selector no se renderiza — single-sede no la necesita.
  const [sedes, setSedes] = useState([])
  useEffect(() => {
    api.get('/api/sedes/lookup?only_active=true')
      .then(res => setSedes(res.data || []))
      .catch(() => {})
  }, [])

  const submit = () => {
    if (!form.nombre.trim()) return alert('Nombre es requerido')
    if (!editing && !form.slug.trim()) return alert('Slug es requerido (a-z, 0-9, _, -)')
    if (!form.fuente_id) return alert('Fuente es requerida')

    const ipList = form.ip_whitelist
      .split('\n').map(s => s.trim()).filter(Boolean)

    onSave({
      ...form,
      slug: form.slug.toLowerCase(),
      fuente_id: parseInt(form.fuente_id),
      rate_limit_per_minute: parseInt(form.rate_limit_per_minute) || 60,
      ip_whitelist: ipList.length > 0 ? ipList : null,
      sede_id_default: form.sede_id_default || null,  // V065: null limpia la sede
    })
  }

  return (
    <div
      className="fixed inset-0 z-50 bg-black/40 flex items-start sm:items-center justify-center p-4 overflow-y-auto"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-2xl w-full max-w-lg my-auto flex flex-col max-h-[90vh]"
        onClick={e => e.stopPropagation()}
      >
        {/* Header sticky */}
        <div className="flex items-center justify-between px-6 pt-5 pb-3 border-b border-gray-100 shrink-0">
          <h3 className="text-base font-semibold text-gray-900 flex items-center gap-2">
            <Plug size={16} className="text-indigo-500" />
            {editing ? `Editar "${editing.nombre}"` : 'Nuevo proveedor externo'}
          </h3>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <XIcon size={16} />
          </button>
        </div>

        {/* Body scroll */}
        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        <div>
          <Label className="text-xs">Nombre <span className="text-red-500">*</span></Label>
          <Input
            value={form.nombre}
            onChange={e => setForm(p => ({ ...p, nombre: e.target.value }))}
            placeholder="Ej: Wedo, Agencia X, Portal Z…"
            className="mt-1"
          />
        </div>

        {!editing && (
          <div>
            <Label className="text-xs">Slug (identificador único) <span className="text-red-500">*</span></Label>
            <Input
              value={form.slug}
              onChange={e => setForm(p => ({ ...p, slug: e.target.value.toLowerCase().replace(/[^a-z0-9_-]/g, '') }))}
              placeholder="proveedor-x"
              className="mt-1 font-mono"
            />
            <p className="text-[10px] text-gray-400 mt-0.5">a-z, 0-9, _, - · No se puede cambiar después</p>
          </div>
        )}

        <div>
          <Label className="text-xs">Fuente default <span className="text-red-500">*</span></Label>
          <select
            value={form.fuente_id}
            onChange={e => setForm(p => ({ ...p, fuente_id: e.target.value }))}
            className="w-full mt-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            {fuentes.map(f => <option key={f.id} value={f.id}>{f.nombre}</option>)}
          </select>
          <p className="text-[10px] text-gray-500 mt-1 leading-snug">
            <strong className="text-gray-700">Fallback:</strong> se usa si el proveedor <em>no declara</em>{' '}
            <code className="text-[9px] bg-gray-100 px-1 py-0.5 rounded">fuente</code> en el body.
            <br />
            Si el proveedor entrega leads de múltiples canales (TikTok, Facebook, Instagram, etc.),
            puede declarar <code className="text-[9px] bg-gray-100 px-1 py-0.5 rounded">fuente</code> en cada
            lead y esa prevalece. Patrón APIs profesionales: el body manda &gt; el default es fallback.
          </p>
        </div>

        {/* V065: sede default — solo se muestra si hay sedes configuradas. */}
        {sedes.length > 0 && (
          <div>
            <Label className="text-xs">Sede default</Label>
            <select
              value={form.sede_id_default}
              onChange={e => setForm(p => ({ ...p, sede_id_default: e.target.value }))}
              className="w-full mt-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="">— Sin sede por defecto —</option>
              {sedes.map(s => (
                <option key={s.id} value={s.id}>
                  {s.ciudad ? `${s.nombre} · ${s.ciudad}` : s.nombre}
                </option>
              ))}
            </select>
            <p className="text-[10px] text-gray-400 mt-0.5">
              Los leads que entren por esta key recibirán esta sede.
              El payload puede sobrescribirla con <code className="bg-gray-50 px-1 rounded">"sede"</code>.
            </p>
          </div>
        )}

        <div>
          <Label className="text-xs">Rate limit (requests por minuto)</Label>
          <div className="flex gap-1 mt-1">
            {RATE_PRESETS.map(p => (
              <button
                key={p.v}
                onClick={() => setForm(prev => ({ ...prev, rate_limit_per_minute: p.v }))}
                className={`flex-1 text-[10px] py-1.5 rounded font-medium transition-colors ${
                  parseInt(form.rate_limit_per_minute) === p.v
                    ? 'bg-indigo-100 text-indigo-700 ring-1 ring-indigo-300'
                    : 'bg-gray-50 text-gray-500 hover:bg-gray-100'
                }`}
              >
                {p.label}
              </button>
            ))}
          </div>
        </div>

        <div>
          <Label className="text-xs flex items-center gap-1">
            <Shield size={11} /> IP whitelist (opcional)
          </Label>
          <textarea
            value={form.ip_whitelist}
            onChange={e => setForm(p => ({ ...p, ip_whitelist: e.target.value }))}
            rows={3}
            placeholder="Una IP o CIDR por línea&#10;Ej:&#10;200.10.20.30&#10;192.168.0.0/24"
            className="w-full mt-1 text-xs font-mono border border-gray-200 rounded-md px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
          />
          <p className="text-[10px] text-gray-400 mt-0.5">Si está vacío, se acepta desde cualquier IP. Recomendado para integraciones server-to-server.</p>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <Label className="text-xs">Email contacto</Label>
            <Input
              value={form.contacto_email}
              onChange={e => setForm(p => ({ ...p, contacto_email: e.target.value }))}
              placeholder="ops@proveedor.com"
              className="mt-1"
            />
          </div>
          <div>
            <Label className="text-xs">Teléfono contacto</Label>
            <Input
              value={form.contacto_telefono}
              onChange={e => setForm(p => ({ ...p, contacto_telefono: e.target.value }))}
              placeholder="+51 999 999 999"
              className="mt-1"
            />
          </div>
        </div>

        <div>
          <Label className="text-xs">Notas</Label>
          <textarea
            value={form.notas}
            onChange={e => setForm(p => ({ ...p, notas: e.target.value }))}
            rows={2}
            placeholder="Contexto del proveedor, condiciones comerciales…"
            className="w-full mt-1 text-sm border border-gray-200 rounded-md px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
          />
        </div>

        {editing && (
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={form.activo}
              onChange={e => setForm(p => ({ ...p, activo: e.target.checked }))}
              className="rounded"
            />
            <span>Proveedor activo</span>
          </label>
        )}
        </div>
        {/* Footer sticky */}
        <div className="flex gap-2 justify-end px-6 py-3 border-t border-gray-100 bg-gray-50 rounded-b-2xl shrink-0">
          <Button variant="outline" onClick={onClose}>Cancelar</Button>
          <Button onClick={submit} className="gap-1.5">
            <Check size={14} /> {editing ? 'Guardar cambios' : 'Crear y generar key'}
          </Button>
        </div>
      </div>
    </div>
  )
}

// ─── Modal: revelacion de la key (UNICA VEZ) ──────────────────────────────

function SecretRevealModal({ secret, client, isRegen, onClose }) {
  const [copied, setCopied] = useState(false)
  const [copiedCurl, setCopiedCurl] = useState(false)
  const [revealed, setRevealed] = useState(false)
  // Snapshot del timestamp al montar — usamos una funcion lazy en useState
  // para evitar 'Date.now()' impuro en el render.
  const [exampleId] = useState(() => Date.now())

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(secret)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch (err) {
      console.warn('clipboard copy failed', err)
    }
  }

  // URL portable: usa el origin del frontend (mismo dominio que el API).
  const baseUrl = window.location.origin
  // V054: 'fuente' = canal de origen del lead (instagram/facebook/tiktok/
  // whatsapp/manual). El valor depende de cada lead — el proveedor lo
  // ajusta segun de donde venga el cliente. Usamos 'instagram' como
  // ejemplo representativo (el canal mas comun en Lead Ads de Meta).
  const fuenteEjemplo = 'instagram'
  // V068.7 — incluimos fuente_externa_id y external_created_at en el
  // ejemplo rapido para que el proveedor los implemente desde el primer
  // momento (idempotencia + backfill protection).
  const curlText = `curl -X POST ${baseUrl}/api/ingest/leads \\
  -H "X-Api-Key: ${secret}" \\
  -H "Content-Type: application/json" \\
  -H "Idempotency-Key: lead-${exampleId}" \\
  -d '{
    "fuente": "${fuenteEjemplo}",
    "telefono": "999999999",
    "nombres": "Juan",
    "fuente_externa_id": "${exampleId}",
    "external_created_at": "2026-05-13T14:32:18Z"
  }'`

  const copyCurl = async () => {
    try {
      await navigator.clipboard.writeText(curlText)
      setCopiedCurl(true)
      setTimeout(() => setCopiedCurl(false), 2000)
    } catch { /* noop */ }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-start sm:items-center justify-center p-4 overflow-y-auto">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-lg my-auto flex flex-col max-h-[90vh]">
        <div className="flex items-start gap-3 px-6 pt-5 pb-3 border-b border-gray-100 shrink-0">
          <div className="w-10 h-10 rounded-full bg-amber-100 text-amber-700 flex items-center justify-center shrink-0">
            <AlertTriangle size={18} />
          </div>
          <div className="flex-1">
            <h3 className="text-base font-semibold text-gray-900">
              {isRegen ? 'Nueva API key generada' : 'API key generada'}
            </h3>
            <p className="text-xs text-gray-500 mt-0.5">
              Para <strong className="text-gray-700">{client.nombre}</strong>. Esta es la única vez
              que verás la clave completa — guárdala en un lugar seguro ahora.
            </p>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        <div className="bg-gray-900 rounded-lg p-3 font-mono text-xs">
          <div className="flex items-center gap-2">
            <code className="flex-1 text-emerald-300 break-all select-all">
              {revealed ? secret : '•'.repeat(secret.length)}
            </code>
            <button
              onClick={() => setRevealed(!revealed)}
              className="text-gray-400 hover:text-white p-1"
              title={revealed ? 'Ocultar' : 'Mostrar'}
            >
              {revealed ? <EyeOff size={14} /> : <Eye size={14} />}
            </button>
            <button
              onClick={copy}
              className={`p-1 rounded transition-colors ${copied ? 'bg-emerald-500 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-800'}`}
              title="Copiar"
            >
              {copied ? <Check size={14} /> : <Copy size={14} />}
            </button>
          </div>
          {copied && <p className="text-emerald-400 text-[10px] mt-1.5">¡Copiado al portapapeles!</p>}
        </div>

        <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-800 space-y-1.5">
          <p className="font-semibold flex items-center gap-1.5"><Shield size={12} /> Seguridad</p>
          <ul className="list-disc list-inside space-y-0.5">
            <li>Nunca compartas esta clave por chat o email en texto plano. Usa un gestor de secretos.</li>
            <li>El proveedor debe enviarla en el header <code className="bg-white px-1 rounded">X-Api-Key</code>.</li>
            <li>Si se compromete, regenérala desde aquí — la actual deja de funcionar al instante.</li>
            {isRegen && <li className="text-amber-900 font-semibold">La key anterior ya quedó invalidada.</li>}
          </ul>
        </div>

        <div className="bg-gray-50 border border-gray-200 rounded-lg p-3 text-[11px] text-gray-700">
          <div className="flex items-center justify-between mb-1.5">
            <p className="font-semibold">Ejemplo de uso:</p>
            <button
              onClick={copyCurl}
              className="text-[10px] flex items-center gap-1 px-2 py-1 rounded bg-slate-700 text-white hover:bg-slate-600 transition-colors"
            >
              {copiedCurl ? <Check size={10} /> : <Copy size={10} />}
              {copiedCurl ? 'Copiado' : 'Copiar curl'}
            </button>
          </div>
          <pre className="font-mono whitespace-pre-wrap break-all bg-white border border-gray-200 rounded p-2 text-[10px]">
{revealed
  ? curlText
  : curlText.replace(secret, 'cli_••••••••_••••••••••••••••••••••••••••••••')}
          </pre>
          <p className="text-[10px] text-gray-500 mt-1.5">
            Para más opciones (DNI, anuncio, conjunto, resumen IA, etc.), ver
            <strong> Documentación</strong> desde el listado de proveedores.
          </p>
        </div>
        </div>
        <div className="flex justify-end px-6 py-3 border-t border-gray-100 bg-gray-50 rounded-b-2xl shrink-0">
          <Button onClick={onClose}>Ya guardé la clave</Button>
        </div>
      </div>
    </div>
  )
}

// ─── Modal: stats ─────────────────────────────────────────────────────────

function StatsModal({ client, onClose, onViewLeads }) {
  const [stats, setStats] = useState(null)
  const [logs, setLogs]   = useState([])
  const [loading, setLoading] = useState(true)
  const [tab, setTab] = useState('stats')

  useEffect(() => {
    Promise.all([
      api.get(`/api/admin/api-clients/${client.id}/stats?dias=30`),
      api.get(`/api/admin/api-clients/${client.id}/logs?limit=50`),
    ])
      .then(([s, l]) => { setStats(s.data); setLogs(l.data?.logs || []) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [client.id])

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl max-h-[88vh] overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-gray-100 px-6 py-4 flex items-center justify-between z-10">
          <div>
            <h3 className="text-base font-semibold text-gray-900 flex items-center gap-2">
              <Activity size={16} className="text-purple-500" /> {client.nombre}
            </h3>
            <p className="text-[11px] text-gray-400">{client.api_key_prefix}…  ·  {client.slug}</p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <XIcon size={16} />
          </button>
        </div>

        <div className="border-b border-gray-100 flex gap-1 px-6">
          <TabBtn active={tab === 'stats'} onClick={() => setTab('stats')}>Estadísticas</TabBtn>
          <TabBtn active={tab === 'logs'}  onClick={() => setTab('logs')}>Logs ({logs.length})</TabBtn>
        </div>

        <div className="p-6">
          {loading ? <LoadingSpinner /> : tab === 'stats' ? (
            <StatsView
              stats={stats}
              client={client}
              onViewLeads={onViewLeads}
            />
          ) : (
            <LogsView logs={logs} />
          )}
        </div>
      </div>
    </div>
  )
}


// ─── V060: Modal independiente Webhook (patron APIs profesionales) ─────────────

function WebhookModal({ client, onClose, onClientUpdate }) {
  const [localClient, setLocalClient] = useState(client)

  const handleClientPatch = async (patch) => {
    try {
      const { data } = await api.patch(`/api/admin/api-clients/${client.id}`, patch)
      setLocalClient(data)
      onClientUpdate?.(data)
      return data
    } catch (err) {
      alert(err?.response?.data?.detail || 'No se pudo guardar.')
      return null
    }
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl max-h-[88vh] overflow-y-auto">
        <div className="sticky top-0 bg-white border-b border-gray-100 px-6 py-4 flex items-center justify-between z-10">
          <div>
            <h3 className="text-base font-semibold text-gray-900 flex items-center gap-2">
              <Webhook size={16} className="text-sky-500" />
              Webhook · {localClient.nombre}
              {localClient.webhook_enabled && (
                <span className="inline-flex items-center gap-1 text-[10px] font-semibold uppercase tracking-wide text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-full px-2 py-0.5">
                  <span className="w-1.5 h-1.5 bg-emerald-500 rounded-full" /> Activo
                </span>
              )}
            </h3>
            <p className="text-[11px] text-gray-400 mt-0.5">
              Notifica al proveedor cuando se asigna, reasigna o cambia de estado un lead suyo.
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600">
            <XIcon size={16} />
          </button>
        </div>

        <div className="p-6">
          <WebhookView client={localClient} onPatch={handleClientPatch} />
        </div>
      </div>
    </div>
  )
}

function TabBtn({ active, children, onClick }) {
  return (
    <button
      onClick={onClick}
      className={`text-xs font-semibold px-3 py-2.5 border-b-2 transition-colors ${
        active ? 'border-purple-500 text-purple-700' : 'border-transparent text-gray-500 hover:text-gray-700'
      }`}
    >
      {children}
    </button>
  )
}

function StatsView({ stats, client, onViewLeads }) {
  const conv = stats?.conversion || {}
  const porDia = stats?.leads_por_dia || []
  const max = Math.max(1, ...porDia.map(d => d.total))
  const dedupePct = client.total_leads > 0
    ? Math.round(client.leads_duplicados * 100 / (client.total_leads + client.leads_duplicados))
    : 0
  const totalLeads = client.total_leads || 0

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-4 gap-3">
        <KpiBlock label="Leads totales"  value={totalLeads}                    color="indigo" />
        <KpiBlock label="Duplicados"     value={client.leads_duplicados || 0} color="amber"  hint={`${dedupePct}% del total`} />
        <KpiBlock label="Convertidos"    value={conv.ganados || 0}             color="emerald" hint={`${conv.tasa_pct || 0}% conversión`} />
        <KpiBlock label="Rechazados"     value={client.leads_rechazados || 0}  color="red" />
      </div>

      {/* V062: deep-link a /leads (acciones destructivas como Desvincular
          ya NO viven aca — un panel de Estadisticas debe ser read-only.
          Para gestion van a las acciones del card del proveedor.) */}
      {totalLeads > 0 && onViewLeads && (
        <button
          onClick={onViewLeads}
          className="w-full inline-flex items-center justify-center gap-1.5 text-xs px-3 py-2 rounded-lg bg-gray-50 border border-gray-100 text-gray-700 hover:border-indigo-300 hover:text-indigo-700 hover:bg-indigo-50/60 transition-colors"
          type="button"
        >
          <ExternalLink size={12} />
          Ver los {totalLeads} leads de este proveedor
        </button>
      )}

      <div>
        <p className="text-[10px] uppercase tracking-wide font-semibold text-gray-500 mb-2">
          Leads enviados — últimos 30 días
        </p>
        {porDia.length === 0 ? (
          <p className="text-xs text-gray-400 text-center py-8">Sin actividad en el período.</p>
        ) : (
          <div className="flex items-end gap-0.5 h-32 bg-gray-50 rounded-lg p-2">
            {porDia.map(d => (
              <div
                key={d.dia}
                className="flex-1 bg-indigo-500 rounded-sm transition-all hover:bg-indigo-600 relative group"
                style={{ height: `${(d.total / max) * 100}%`, minHeight: '2px' }}
                title={`${d.dia}: ${d.total} leads`}
              >
                <div className="hidden group-hover:block absolute -top-7 left-1/2 -translate-x-1/2 bg-gray-900 text-white text-[10px] px-1.5 py-0.5 rounded whitespace-nowrap">
                  {d.total}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      <div>
        <p className="text-[10px] uppercase tracking-wide font-semibold text-gray-500 mb-2">
          Respuestas HTTP (últimos 30 días)
        </p>
        {(stats?.por_status || []).length === 0 ? (
          <p className="text-xs text-gray-400">Sin requests registrados.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {stats.por_status.map(s => (
              <div
                key={s.status_code}
                className={`text-xs px-2.5 py-1 rounded-full border ${
                  s.status_code < 300 ? 'bg-emerald-50 text-emerald-700 border-emerald-200'
                  : s.status_code < 500 ? 'bg-amber-50 text-amber-700 border-amber-200'
                  : 'bg-red-50 text-red-700 border-red-200'
                }`}
              >
                <strong>{s.status_code}</strong>: {s.total} {s.duplicados > 0 && `(${s.duplicados} dup)`}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

function KpiBlock({ label, value, color, hint }) {
  const cls = {
    indigo:  { bg: 'bg-indigo-50',  text: 'text-indigo-700',  ring: 'ring-indigo-100' },
    emerald: { bg: 'bg-emerald-50', text: 'text-emerald-700', ring: 'ring-emerald-100' },
    amber:   { bg: 'bg-amber-50',   text: 'text-amber-700',   ring: 'ring-amber-100' },
    red:     { bg: 'bg-red-50',     text: 'text-red-700',     ring: 'ring-red-100' },
  }[color] || { bg: 'bg-gray-50', text: 'text-gray-700', ring: 'ring-gray-100' }
  return (
    <div className={`${cls.bg} ring-1 ${cls.ring} rounded-lg px-3 py-2.5`}>
      <p className={`text-[10px] uppercase tracking-wide font-semibold ${cls.text}`}>{label}</p>
      <p className="text-2xl font-bold text-gray-900 mt-0.5">{value}</p>
      {hint && <p className="text-[10px] text-gray-500">{hint}</p>}
    </div>
  )
}

function LogsView({ logs }) {
  if (logs.length === 0) {
    return <p className="text-xs text-gray-400 text-center py-8">No hay requests registrados todavía.</p>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="bg-gray-50 border-b border-gray-100">
            <th className="text-left px-3 py-2 text-[10px] font-semibold text-gray-500 uppercase">Cuándo</th>
            <th className="text-left px-3 py-2 text-[10px] font-semibold text-gray-500 uppercase">IP</th>
            <th className="text-left px-3 py-2 text-[10px] font-semibold text-gray-500 uppercase">Status</th>
            <th className="text-left px-3 py-2 text-[10px] font-semibold text-gray-500 uppercase">Lead</th>
            <th className="text-left px-3 py-2 text-[10px] font-semibold text-gray-500 uppercase">Detalle</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {logs.map(l => (
            <tr key={l.id} className="hover:bg-gray-50/50">
              <td className="px-3 py-2 text-gray-500 whitespace-nowrap">{formatRelative(l.created_at)}</td>
              <td className="px-3 py-2 font-mono text-gray-600 text-[10px]">{l.ip || '—'}</td>
              <td className="px-3 py-2">
                <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold ${
                  l.status_code < 300 ? 'bg-emerald-100 text-emerald-700'
                  : l.status_code < 500 ? 'bg-amber-100 text-amber-700'
                  : 'bg-red-100 text-red-700'
                }`}>{l.status_code}</span>
              </td>
              <td className="px-3 py-2 text-gray-600">
                {l.lead_id ? `#${l.lead_id}` : '—'}
                {l.duplicated && <span className="ml-1 text-[10px] text-amber-600">dup</span>}
              </td>
              <td className="px-3 py-2 text-gray-500 max-w-[200px] truncate" title={l.error_msg || l.idempotency_key || ''}>
                {l.error_msg || (l.idempotency_key && `idem: ${l.idempotency_key}`) || '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ─── V058: Webhook view (config + deliveries) ────────────────────────────

const WEBHOOK_EVENTS = [
  { v: 'lead.received',       label: 'Lead recibido',           desc: 'El CRM recibió el lead desde tu sistema (con o sin asesor)' },
  { v: 'lead.assigned',       label: 'Lead asignado',           desc: 'Primera asignación a un asesor' },
  { v: 'lead.reassigned',     label: 'Lead reasignado',         desc: 'Cambio de asesor (manual o automático)' },
  { v: 'lead.status_changed', label: 'Cambio de estado',        desc: 'Nuevo → Contactado, etc.' },
  { v: 'lead.recontacto',     label: 'Lead recontacto',         desc: 'Un lead existente volvió a mostrar interés por una nueva campaña/anuncio/conjunto' },
]

function PrivacyToggle({ checked, onChange, title, desc, color = 'emerald', disabled = false }) {
  const colorClasses = {
    emerald: 'accent-emerald-600',
    indigo:  'accent-indigo-600',
    amber:   'accent-amber-600',
  }[color] || 'accent-emerald-600'

  return (
    <label className={`flex items-start gap-2 p-2 rounded-md hover:bg-white transition-colors ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}>
      <input
        type="checkbox"
        checked={!!checked}
        onChange={e => onChange(e.target.checked)}
        disabled={disabled}
        className={`mt-0.5 ${colorClasses}`}
      />
      <div className="flex-1 min-w-0">
        <div className="text-xs font-semibold text-gray-700">{title}</div>
        <div className="text-[10px] text-gray-500 leading-snug">{desc}</div>
      </div>
    </label>
  )
}

function WebhookView({ client, onPatch }) {
  const [url, setUrl]           = useState(client.webhook_url || '')
  const [enabled, setEnabled]   = useState(!!client.webhook_enabled)
  const [events, setEvents]     = useState(client.webhook_events || [])
  // V059: privacy toggles
  const [incAsesorContact, setIncAsesorContact]         = useState(client.webhook_include_asesor_contact !== false)
  const [incSupervisor, setIncSupervisor]               = useState(client.webhook_include_supervisor !== false)
  const [incSupervisorContact, setIncSupervisorContact] = useState(!!client.webhook_include_supervisor_contact)
  const [saving, setSaving]     = useState(false)
  const [revealedSecret, setRevealedSecret] = useState(null)
  const [deliveries, setDeliveries] = useState([])
  const [loadingDel, setLoadingDel] = useState(false)
  const [statusFilter, setStatusFilter] = useState('')
  // V060.1: confirm premium para regenerar secret (reemplaza confirm() nativo)
  const [confirmRegenSecret, setConfirmRegenSecret] = useState(false)

  // V060.1: sincronizar state local cuando el padre actualiza el client
  // (despues de un PATCH exitoso) — sin esto el toggle visual se desincronizaba
  // del backend en algunos flujos.
  useEffect(() => {
    setUrl(client.webhook_url || '')
    setEnabled(!!client.webhook_enabled)
    setEvents(client.webhook_events || [])
    setIncAsesorContact(client.webhook_include_asesor_contact !== false)
    setIncSupervisor(client.webhook_include_supervisor !== false)
    setIncSupervisorContact(!!client.webhook_include_supervisor_contact)
  }, [client.id, client.webhook_enabled, client.webhook_url,
      client.webhook_include_asesor_contact, client.webhook_include_supervisor,
      client.webhook_include_supervisor_contact]) // eslint-disable-line react-hooks/exhaustive-deps

  const loadDeliveries = async () => {
    setLoadingDel(true)
    try {
      const qs = statusFilter ? `?status=${statusFilter}&limit=50` : '?limit=50'
      const { data } = await api.get(`/api/admin/api-clients/${client.id}/webhook/deliveries${qs}`)
      setDeliveries(data?.deliveries || [])
    } catch { /* noop */ } finally { setLoadingDel(false) }
  }

  useEffect(() => { loadDeliveries() }, [statusFilter]) // eslint-disable-line react-hooks/exhaustive-deps

  const toggleEvent = (v) => {
    setEvents(prev => prev.includes(v) ? prev.filter(x => x !== v) : [...prev, v])
  }

  const save = async () => {
    setSaving(true)
    await onPatch({
      webhook_url:                        url || null,
      webhook_events:                     events,
      webhook_enabled:                    enabled,
      webhook_include_asesor_contact:     incAsesorContact,
      webhook_include_supervisor:         incSupervisor,
      webhook_include_supervisor_contact: incSupervisorContact,
    })
    setSaving(false)
  }

  // Trigger del modal de confirmacion. Si nunca hubo secret (primera vez)
  // generamos directo sin pedir confirmacion — no hay nada que invalidar.
  const requestGenerateSecret = () => {
    if (!client.has_webhook_secret) {
      doGenerateSecret()
    } else {
      setConfirmRegenSecret(true)
    }
  }

  const doGenerateSecret = async () => {
    setConfirmRegenSecret(false)
    try {
      const { data } = await api.post(`/api/admin/api-clients/${client.id}/webhook/regenerate-secret`)
      setRevealedSecret(data.webhook_secret)
    } catch (err) {
      alert(err?.response?.data?.detail || 'Error al regenerar secret')
    }
  }

  const retryDelivery = async (id) => {
    try {
      await api.post(`/api/admin/api-clients/${client.id}/webhook/deliveries/${id}/retry`)
      await loadDeliveries()
    } catch (err) {
      alert(err?.response?.data?.detail || 'Error al reintentar')
    }
  }

  // V076: enviar evento sintetico para verificar la conexion (patron estandar).
  const [sendingTest, setSendingTest] = useState(false)
  const [testResult, setTestResult]   = useState(null)
  const sendTestEvent = async () => {
    if (sendingTest) return
    setSendingTest(true)
    setTestResult(null)
    try {
      const { data } = await api.post(`/api/admin/api-clients/${client.id}/webhook/test`)
      setTestResult({
        kind: 'ok',
        msg:  data?.message || 'Evento de prueba enviado.',
      })
      // Refrescar deliveries para que el admin vea el resultado al toque.
      setTimeout(() => loadDeliveries(), 800)
    } catch (err) {
      setTestResult({
        kind: 'error',
        msg:  err?.response?.data?.detail || 'No se pudo enviar el evento de prueba.',
      })
    } finally {
      setSendingTest(false)
    }
  }

  const dirty = (
    url !== (client.webhook_url || '') ||
    enabled !== !!client.webhook_enabled ||
    JSON.stringify([...events].sort()) !== JSON.stringify([...(client.webhook_events || [])].sort()) ||
    incAsesorContact !== (client.webhook_include_asesor_contact !== false) ||
    incSupervisor !== (client.webhook_include_supervisor !== false) ||
    incSupervisorContact !== !!client.webhook_include_supervisor_contact
  )

  return (
    <div className="space-y-6">
      {/* V060.1: Switch prominente estilo estilo moderno — antes era un
          checkbox chico en la esquina y era facil pasarlo por alto. */}
      <div className={`rounded-xl border p-4 transition-colors ${
        enabled
          ? 'border-emerald-200 bg-emerald-50/40'
          : 'border-amber-200 bg-amber-50/40'
      }`}>
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <Switch
              checked={enabled}
              onChange={() => setEnabled(v => !v)}
              ariaLabel={enabled ? 'Webhook habilitado' : 'Webhook deshabilitado'}
            />
            <div>
              <div className={`text-sm font-semibold ${enabled ? 'text-emerald-800' : 'text-amber-800'}`}>
                {enabled ? 'Webhook habilitado' : 'Webhook deshabilitado'}
              </div>
              <div className="text-[11px] text-gray-600 mt-0.5">
                {enabled
                  ? 'El CRM enviará eventos al proveedor automáticamente.'
                  : 'Activá el switch para empezar a enviar eventos al proveedor.'}
              </div>
            </div>
          </div>
          {dirty && enabled && !client.webhook_enabled && (
            <span className="text-[10px] font-semibold text-emerald-700 bg-emerald-100 border border-emerald-200 rounded-full px-2 py-1 whitespace-nowrap">
              Cambio sin guardar
            </span>
          )}
        </div>
      </div>

      {/* Config */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <div>
            <h4 className="text-sm font-semibold text-gray-800">Configuración del webhook</h4>
            <p className="text-[11px] text-gray-500 mt-0.5">
              POST con HMAC-SHA256 firmado en header <code className="text-[10px] bg-gray-100 px-1 rounded">X-Crm-Signature</code>.
            </p>
          </div>
        </div>

        <div className="space-y-3">
          <div>
            <label className="text-[11px] font-semibold text-gray-500 uppercase">URL</label>
            <input
              type="url"
              value={url}
              onChange={e => setUrl(e.target.value)}
              placeholder="https://proveedor.com/webhooks/crm"
              className="w-full text-sm border border-gray-200 rounded-md px-3 py-2 mt-1 font-mono focus:ring-2 focus:ring-purple-500 focus:border-purple-500"
            />
          </div>

          <div>
            <label className="text-[11px] font-semibold text-gray-500 uppercase">Eventos suscriptos</label>
            <div className="mt-2 space-y-1.5">
              {WEBHOOK_EVENTS.map(ev => (
                <label key={ev.v} className="flex items-start gap-2 p-2 rounded-md hover:bg-gray-50 cursor-pointer">
                  <input
                    type="checkbox" checked={events.includes(ev.v)}
                    onChange={() => toggleEvent(ev.v)}
                    className="mt-0.5 accent-purple-600"
                  />
                  <div>
                    <div className="text-xs font-semibold text-gray-700">{ev.label}</div>
                    <div className="text-[10px] text-gray-500 font-mono">{ev.v}</div>
                    <div className="text-[10px] text-gray-400">{ev.desc}</div>
                  </div>
                </label>
              ))}
            </div>
          </div>

          {/* V059: Privacy toggles — qué datos del asesor/supervisor incluir */}
          <div>
            <label className="text-[11px] font-semibold text-gray-500 uppercase">
              Privacidad del payload
            </label>
            <p className="text-[10px] text-gray-400 mt-0.5 mb-2">
              Controla qué datos del asesor y supervisor verá el proveedor en cada evento.
              El nombre y el ID siempre se envían — solo se filtran email y teléfono.
            </p>
            <div className="space-y-1.5 bg-gray-50/60 border border-gray-100 rounded-md p-2">
              <PrivacyToggle
                checked={incAsesorContact}
                onChange={setIncAsesorContact}
                title="Incluir contacto del asesor"
                desc="Email y teléfono del vendedor asignado. Necesario si el proveedor IA entrega el lead 'en mano' al humano."
                color="emerald"
              />
              <PrivacyToggle
                checked={incSupervisor}
                onChange={(v) => {
                  setIncSupervisor(v)
                  if (!v) setIncSupervisorContact(false)
                }}
                title="Incluir bloque del supervisor"
                desc="Si está OFF, el payload omite por completo la sección supervisor."
                color="indigo"
              />
              <PrivacyToggle
                checked={incSupervisorContact}
                onChange={setIncSupervisorContact}
                title="Incluir contacto del supervisor"
                desc="Email y teléfono del supervisor. Solo aplica si 'Incluir bloque del supervisor' está activo."
                color="amber"
                disabled={!incSupervisor}
              />
            </div>
          </div>

          <div>
            <label className="text-[11px] font-semibold text-gray-500 uppercase">Secret HMAC</label>
            <div className="flex items-center gap-2 mt-1">
              {revealedSecret ? (
                <input
                  type="text"
                  value={revealedSecret}
                  readOnly
                  className="flex-1 text-xs border border-amber-300 bg-amber-50 rounded-md px-3 py-2 font-mono"
                  onFocus={e => e.target.select()}
                />
              ) : (
                <div className="flex-1 text-xs text-gray-500 px-3 py-2 border border-gray-200 rounded-md bg-gray-50">
                  {client.has_webhook_secret ? '•••••• (configurado, no visible)' : 'No configurado'}
                </div>
              )}
              <button
                onClick={requestGenerateSecret}
                className="text-xs px-3 py-2 rounded-md bg-amber-100 text-amber-800 hover:bg-amber-200 font-semibold whitespace-nowrap"
                type="button"
              >
                {client.has_webhook_secret ? 'Regenerar' : 'Generar'}
              </button>
            </div>
            {revealedSecret && (
              <p className="text-[10px] text-amber-700 mt-1.5 font-medium">
                ⚠️ Guárdalo ahora — al cerrar este modal no se vuelve a mostrar.
              </p>
            )}
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <button
              onClick={save}
              disabled={!dirty || saving}
              className="text-xs px-4 py-2 rounded-md bg-purple-600 text-white font-semibold hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed"
              type="button"
            >
              {saving ? 'Guardando…' : 'Guardar'}
            </button>
          </div>
        </div>
      </div>

      {/* V076: Probar webhook — patron estandar. Permite verificar
          el wiring sin tener que asignar un lead real. */}
      <div className="border-t border-gray-100 pt-5">
        <div className="rounded-lg border border-purple-100 bg-purple-50/40 p-3">
          <div className="flex items-center justify-between gap-3 flex-wrap">
            <div className="min-w-0 flex-1">
              <div className="text-xs font-semibold text-gray-800">Probar webhook</div>
              <div className="text-[11px] text-gray-600 leading-snug">
                Envía un evento sintético (<code className="px-1 py-0.5 bg-white border border-purple-200 rounded text-purple-700 text-[10px]">event=&quot;webhook.test&quot;</code>) al endpoint para verificar que está bien conectado, sin tocar leads reales.
              </div>
            </div>
            <button
              onClick={sendTestEvent}
              disabled={sendingTest || !enabled || !url}
              className="shrink-0 inline-flex items-center gap-1.5 text-xs font-semibold px-3 py-1.5 rounded-md bg-purple-600 text-white hover:bg-purple-700 disabled:opacity-50 disabled:cursor-not-allowed"
              type="button"
              title={!enabled ? 'Activa el webhook primero' : !url ? 'Configura una URL primero' : 'Enviar evento de prueba'}
            >
              {sendingTest ? 'Enviando…' : 'Enviar evento de prueba'}
            </button>
          </div>
          {testResult && (
            <div className={`mt-2 text-[11px] px-2 py-1.5 rounded-md ${
              testResult.kind === 'ok'
                ? 'bg-emerald-50 text-emerald-800 border border-emerald-200'
                : 'bg-red-50 text-red-800 border border-red-200'
            }`}>
              {testResult.msg}
            </div>
          )}
        </div>
      </div>

      {/* Deliveries */}
      <div className="border-t border-gray-100 pt-5">
        <div className="flex items-center justify-between mb-3">
          <h4 className="text-sm font-semibold text-gray-800">
            Deliveries recientes
            <span className="ml-2 text-[10px] font-normal text-gray-400">(últimos 50)</span>
          </h4>
          <div className="flex items-center gap-2">
            <select
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value)}
              className="text-[11px] border border-gray-200 rounded-md px-2 py-1 bg-white"
            >
              <option value="">Todos</option>
              <option value="success">Success</option>
              <option value="retrying">Retrying</option>
              <option value="dead">Dead</option>
              <option value="pending">Pending</option>
            </select>
            <button
              onClick={loadDeliveries}
              className="text-[11px] text-gray-500 hover:text-purple-600 px-1.5 py-1"
              title="Recargar"
              type="button"
            >↻</button>
          </div>
        </div>

        {loadingDel ? (
          <div className="text-center text-xs text-gray-400 py-6">Cargando…</div>
        ) : deliveries.length === 0 ? (
          <p className="text-xs text-gray-400 text-center py-6">
            {client.webhook_enabled
              ? 'Aún no hay deliveries.'
              : 'Webhook deshabilitado — no se está enviando nada.'}
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-gray-50 border-b border-gray-100">
                  <th className="text-left px-3 py-2 text-[10px] font-semibold text-gray-500 uppercase">Cuándo</th>
                  <th className="text-left px-3 py-2 text-[10px] font-semibold text-gray-500 uppercase">Evento</th>
                  <th className="text-left px-3 py-2 text-[10px] font-semibold text-gray-500 uppercase">Lead</th>
                  <th className="text-left px-3 py-2 text-[10px] font-semibold text-gray-500 uppercase">Status</th>
                  <th className="text-left px-3 py-2 text-[10px] font-semibold text-gray-500 uppercase">HTTP</th>
                  <th className="text-left px-3 py-2 text-[10px] font-semibold text-gray-500 uppercase">ms</th>
                  <th className="text-left px-3 py-2 text-[10px] font-semibold text-gray-500 uppercase">Intento</th>
                  <th className="text-left px-3 py-2 text-[10px] font-semibold text-gray-500 uppercase"></th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {deliveries.map(d => (
                  <tr key={d.id} className="hover:bg-gray-50/50">
                    <td className="px-3 py-2 text-gray-500 whitespace-nowrap">{formatRelative(d.created_at)}</td>
                    <td className="px-3 py-2 font-mono text-[10px] text-gray-700">{d.event_type}</td>
                    <td className="px-3 py-2 text-gray-600">{d.lead_id ? `#${d.lead_id}` : '—'}</td>
                    <td className="px-3 py-2">
                      <span className={`text-[10px] px-1.5 py-0.5 rounded font-semibold ${
                        d.status === 'success' ? 'bg-emerald-100 text-emerald-700'
                        : d.status === 'retrying' ? 'bg-amber-100 text-amber-700'
                        : d.status === 'dead' ? 'bg-red-100 text-red-700'
                        : d.status === 'pending' ? 'bg-blue-100 text-blue-700'
                        : 'bg-gray-100 text-gray-600'
                      }`}>{d.status}</span>
                    </td>
                    <td className="px-3 py-2 text-gray-600 font-mono text-[10px]">
                      {d.http_status ?? (d.error_message ? <span className="text-red-500" title={d.error_message}>err</span> : '—')}
                    </td>
                    <td className="px-3 py-2 text-gray-500 text-[10px]">{d.duration_ms ?? '—'}</td>
                    <td className="px-3 py-2 text-gray-500 text-[10px]">{d.attempt}/{d.max_attempts}</td>
                    <td className="px-3 py-2">
                      {(d.status === 'dead' || d.status === 'failed') && (
                        <button
                          onClick={() => retryDelivery(d.id)}
                          className="text-[10px] text-purple-600 hover:underline font-semibold"
                          type="button"
                        >Reintentar</button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* V060.1: ConfirmDialog premium para regenerar secret (reemplaza
          el confirm() nativo del browser que rompia la identidad visual). */}
      <ConfirmDialog
        open={confirmRegenSecret}
        title="Regenerar secret HMAC"
        message="El secret actual se invalida al instante. El proveedor tendrá que actualizar su configuración con el nuevo valor — los webhooks que envíe con el secret viejo van a fallar la verificación."
        confirmLabel="Sí, regenerar"
        cancelLabel="Cancelar"
        variant="warning"
        onConfirm={doGenerateSecret}
        onCancel={() => setConfirmRegenSecret(false)}
      />
    </div>
  )
}


// ─── Helpers ──────────────────────────────────────────────────────────────

function formatRelative(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  const diff = (Date.now() - d.getTime()) / 1000
  if (diff < 60) return 'hace ' + Math.round(diff) + 's'
  if (diff < 3600) return 'hace ' + Math.round(diff / 60) + 'm'
  if (diff < 86400) return 'hace ' + Math.round(diff / 3600) + 'h'
  if (diff < 86400 * 7) return 'hace ' + Math.round(diff / 86400) + 'd'
  return d.toLocaleDateString('es-PE', { day: '2-digit', month: 'short', year: '2-digit' })
}

// ─── DocViewer modal — sirve INTEGRACION_PROVEEDORES.md ──────────────────

function DocViewerModal({ onClose }) {
  const [content, setContent] = useState(null)
  const [error, setError] = useState(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    api.get('/api/docs/integracion-proveedores', { responseType: 'text' })
      .then(res => setContent(res.data || ''))
      .catch(err => setError(err?.response?.data?.detail || 'No se pudo cargar el doc.'))
  }, [])

  const copyAll = async () => {
    if (!content) return
    try {
      await navigator.clipboard.writeText(content)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch { /* noop */ }
  }

  return (
    <div
      className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-2xl w-full max-w-4xl max-h-[88vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        <div className="sticky top-0 bg-white border-b border-gray-100 px-6 py-4 flex items-center justify-between rounded-t-2xl">
          <div>
            <h3 className="text-base font-semibold text-gray-900 flex items-center gap-2">
              <BookOpen size={16} className="text-indigo-500" /> Documentación para proveedores
            </h3>
            <p className="text-[11px] text-gray-400 mt-0.5">
              Compártela con el proveedor para que sepa cómo enviar leads a tu CRM
            </p>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={copyAll}
              disabled={!content}
              className="text-xs flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-indigo-50 text-indigo-700 hover:bg-indigo-100 disabled:opacity-40 disabled:cursor-not-allowed transition-colors font-medium"
            >
              {copied ? <Check size={13} /> : <Copy size={13} />}
              {copied ? 'Copiado' : 'Copiar todo'}
            </button>
            <button onClick={onClose} className="text-gray-400 hover:text-gray-600 ml-1 p-1">
              <XIcon size={16} />
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 wa-scrollbar">
          {error ? (
            <div className="bg-red-50 border border-red-200 rounded-lg p-4 text-sm text-red-700">
              {error}
            </div>
          ) : content === null ? (
            <LoadingSpinner />
          ) : (
            <pre className="whitespace-pre-wrap break-words text-xs leading-relaxed text-gray-700 font-mono">
              {content}
            </pre>
          )}
        </div>
      </div>
    </div>
  )
}

// ─── CurlExample modal — muestra un curl listo para mandar al proveedor ──

function CurlExampleModal({ client, onClose }) {
  const [copied, setCopied] = useState(false)
  const [example, setExample] = useState('basico')   // 'basico' | 'completo'

  const baseUrl = window.location.origin
  // Solo tenemos el prefix de la key (no la full key porque esta hasheada).
  // Mostramos un placeholder para que el usuario sepa dónde poner la key real.
  const keyDisplay = `${client.api_key_prefix}...<TU_SECRET>`
  // V054: 'fuente' = canal de origen del lead (instagram/facebook/tiktok/
  // whatsapp/manual). NO usamos client.fuente_nombre como default porque
  // puede contener un nombre de proveedor (ej. 'Wedo') si el admin creo
  // una fuente fake antes del fix de semantica. Siempre usamos
  // 'instagram' como ejemplo representativo — el proveedor cambia este
  // valor segun el canal real del lead.
  const fuenteEjemplo = 'instagram'

  const curlBasico = `curl -X POST ${baseUrl}/api/ingest/leads \\
  -H "X-Api-Key: ${keyDisplay}" \\
  -H "Content-Type: application/json" \\
  -H "Idempotency-Key: lead-12345" \\
  -d '{
    "fuente": "${fuenteEjemplo}",
    "telefono": "+51999888777",
    "nombres": "Juan",
    "apellidos": "Pérez",
    "email": "juan@ejemplo.com",
    "campana": "Promo Mayo 2026",
    "fuente_externa_id": "lead-12345",
    "external_created_at": "2026-05-13T14:32:18Z"
  }'`

  const curlCompleto = `curl -X POST ${baseUrl}/api/ingest/leads \\
  -H "X-Api-Key: ${keyDisplay}" \\
  -H "Content-Type: application/json" \\
  -H "Idempotency-Key: 1533626621867548" \\
  -d '{
    "fuente":              "${fuenteEjemplo}",
    "telefono":            "+51999888777",
    "nombres":             "Juan",
    "apellidos":           "Pérez",
    "email":               "juan@ejemplo.com",
    "dni":                 "10607829",

    "campana":             "Promo Mayo 2026",
    "conjunto":            "Geolocalizado interés",
    "anuncio":             "LEAD AD - FACHADA",
    "fuente_externa_id":   "1533626621867548",
    "external_created_at": "2026-05-13T14:32:18Z",
    "form_name":           "Entrega 2027 - Nuevo precio",

    "sede":                "centro",

    "nivel":               "Contactado",
    "asesor_telefono":     "51987291111",
    "resumen_ia":          "El cliente mostró interés inicial por el producto X...",

    "extra": {
      "campo_custom_1":    "valor1",
      "campo_custom_2":    "valor2"
    }
  }'`

  const text = example === 'basico' ? curlBasico : curlCompleto

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch { /* noop */ }
  }

  return (
    <div
      className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-2xl shadow-2xl w-full max-w-3xl max-h-[88vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        <div className="border-b border-gray-100 px-6 py-4 flex items-center justify-between">
          <div>
            <h3 className="text-base font-semibold text-gray-900 flex items-center gap-2">
              <Terminal size={16} className="text-emerald-500" /> Ejemplo de uso — {client.nombre}
            </h3>
            <p className="text-[11px] text-gray-400 mt-0.5">
              Reemplaza <code className="bg-gray-100 px-1 rounded">&lt;TU_SECRET&gt;</code> por la
              parte secreta de la API key (la que se mostró al crearla o regenerarla).
            </p>
          </div>
          <button onClick={onClose} className="text-gray-400 hover:text-gray-600 p-1">
            <XIcon size={16} />
          </button>
        </div>

        <div className="border-b border-gray-100 flex gap-1 px-6">
          <TabBtn active={example === 'basico'} onClick={() => setExample('basico')}>
            Básico
          </TabBtn>
          <TabBtn active={example === 'completo'} onClick={() => setExample('completo')}>
            Completo (con IA pre-calificadora)
          </TabBtn>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-4 wa-scrollbar">
          <div className="relative">
            <button
              onClick={copy}
              className="absolute top-2 right-2 text-xs flex items-center gap-1.5 px-3 py-1.5 rounded-md bg-slate-700 text-white hover:bg-slate-600 transition-colors font-medium z-10"
            >
              {copied ? <Check size={12} /> : <Copy size={12} />}
              {copied ? 'Copiado' : 'Copiar'}
            </button>
            <pre className="bg-slate-900 text-slate-100 rounded-lg p-4 pr-24 text-[11px] leading-relaxed font-mono overflow-x-auto whitespace-pre">
              {text}
            </pre>
          </div>

          <div className="mt-3 space-y-2 text-[11px] text-gray-500 leading-relaxed">
            <p>
              <strong>Nota sobre <code>fuente</code>:</strong> es el canal de origen del lead
              (<code>instagram</code>, <code>facebook</code>, <code>tiktok</code>, <code>whatsapp</code>,
              <code>manual</code>...) — no el nombre del proveedor. Tu identidad como proveedor
              se preserva automáticamente vía la API key, así que no se pierde nada.
            </p>
            <p>
              <strong><code>Idempotency-Key</code> vs <code>fuente_externa_id</code>:</strong>{' '}
              <span className="text-amber-700 font-medium">no son lo mismo, son complementarios</span>.
              Envía siempre los dos (patrón pasarelas profesionales):
              <br />
              • <code>Idempotency-Key</code> (header HTTP) — protege contra <em>retries de red</em>{' '}
              (timeouts, 5xx). Scope: 24 h. Si tu HTTP cliente reintenta el mismo POST por timeout,
              el CRM detecta la repetición y devuelve la misma respuesta sin re-procesar.
              <br />
              • <code>fuente_externa_id</code> (campo del body) — protege contra <em>retries
              semánticos</em> (re-polling, re-import, backfill nocturno). Scope: permanente. El CRM
              lo guarda en la fila del lead. Si re-entregás el mismo ID días o meses después, el
              CRM detecta el dedupe y no infla el contador de reactivaciones.
            </p>
            <p>
              <strong>Sobre <code>external_created_at</code> (recomendado):</strong> timestamp
              ISO 8601 (ej. <code>"2026-05-13T14:32:18Z"</code>) de cuándo el cliente realmente
              llenó el formulario. Habilita el <em>Backfill Protection</em>: si re-entregás un
              lead viejo, el CRM no lo cuenta como reactivación falsa.
            </p>
            {example === 'completo' && (
              <>
                <p>
                  <strong>Sobre <code>sede</code>:</strong> opcional. Slug de la sede de destino
                  (case-insensitive, ej: <code>centro</code>, <code>norte</code>). Si tu CRM tiene
                  sedes configuradas, puedes mandar este campo para asignar el lead automáticamente.
                  Si no lo mandas, se usa la "sede default" configurada al crear la API key (si la
                  hay). Si tampoco hay default, el lead queda sin sede.
                </p>
                <p>
                  <strong>Sobre los campos avanzados:</strong> <code>nivel</code>, <code>asesor_telefono</code>,
                  <code>resumen_ia</code> y <code>extra</code> son para proveedores que pre-califican
                  leads con IA antes de entregarlos. Si tu proveedor solo manda leads "crudos" desde
                  Meta/TikTok, usá el ejemplo básico.
                </p>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
