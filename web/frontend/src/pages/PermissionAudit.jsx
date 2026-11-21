/**
 * PermissionAudit — Timeline de cambios sobre permisos y roles.
 *
 * Cumplimiento Ley 29733 PE (auditoria de cambios sobre datos personales).
 * Inspirado en la Setup Audit Trail de patrón estándar y el Activity Log de patrón estándar.
 *
 * Carga GET /api/permission-audit con filtros opcionales y muestra una
 * timeline con: actor, accion, target, diff antes/despues, IP, fecha.
 */
import { useEffect, useState } from 'react'
import { Shield, AlertCircle, Filter, RefreshCw, User as UserIcon } from 'lucide-react'
import { Button } from '@/components/ui/button'
import LoadingSpinner from '@/components/shared/LoadingSpinner'
import api from '@/lib/api'

const ACTION_LABELS = {
  'role.create':       { label: 'Rol creado',           color: 'bg-green-100 text-green-800' },
  'role.update_perms': { label: 'Permisos modificados', color: 'bg-blue-100 text-blue-800' },
  'role.update_meta':  { label: 'Rol actualizado',      color: 'bg-blue-100 text-blue-800' },
  'role.delete':       { label: 'Rol eliminado',        color: 'bg-red-100 text-red-800' },
  'user.role_change':  { label: 'Rol asignado a usuario', color: 'bg-purple-100 text-purple-800' },
}

function formatDate(iso) {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    return d.toLocaleString('es-PE', {
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return iso
  }
}

function diffPermissions(before, after) {
  const beforePerms = (before && before.permissions) || {}
  const afterPerms = (after && after.permissions) || {}
  const added = []
  const removed = []
  const allKeys = new Set([...Object.keys(beforePerms), ...Object.keys(afterPerms)])
  for (const k of allKeys) {
    const wasOn = beforePerms[k] === true
    const isOn = afterPerms[k] === true
    if (!wasOn && isOn) added.push(k)
    if (wasOn && !isOn) removed.push(k)
  }
  return { added, removed }
}

function ActionBadge({ action }) {
  const meta = ACTION_LABELS[action] || { label: action, color: 'bg-gray-100 text-gray-800' }
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded text-xs font-medium ${meta.color}`}>
      {meta.label}
    </span>
  )
}

function EntryDetails({ entry }) {
  // Para role.update_perms mostramos el diff legible.
  if (entry.action === 'role.update_perms') {
    const { added, removed } = diffPermissions(entry.before_state, entry.after_state)
    return (
      <div className="text-xs text-gray-600 space-y-1">
        {added.length > 0 && (
          <div>
            <span className="text-green-700 font-medium">+ Otorgado:</span>{' '}
            {added.join(', ')}
          </div>
        )}
        {removed.length > 0 && (
          <div>
            <span className="text-red-700 font-medium">− Revocado:</span>{' '}
            {removed.join(', ')}
          </div>
        )}
        {added.length === 0 && removed.length === 0 && (
          <div className="text-gray-400 italic">Sin diferencias detectables (re-guardado sin cambios)</div>
        )}
      </div>
    )
  }
  // Para user.role_change mostramos antes/despues legible.
  if (entry.action === 'user.role_change') {
    const before = entry.before_state || {}
    const after = entry.after_state || {}
    return (
      <div className="text-xs text-gray-600">
        <span className="font-medium">{before.role_name || '—'}</span>
        {' → '}
        <span className="font-medium">{after.role_name || '—'}</span>
      </div>
    )
  }
  // Para role.delete mostramos cuantos usuarios quedaron afectados.
  if (entry.action === 'role.delete') {
    const affected = entry.after_state?.users_affected ?? 0
    return (
      <div className="text-xs text-gray-600">
        {affected > 0
          ? `${affected} usuario(s) quedaron desvinculados del rol`
          : 'Sin usuarios afectados'}
      </div>
    )
  }
  // Para role.create mostramos descripcion breve.
  if (entry.action === 'role.create') {
    const after = entry.after_state || {}
    const permCount = Object.values(after.permissions || {}).filter(v => v === true).length
    return (
      <div className="text-xs text-gray-600">
        {permCount > 0
          ? `Rol creado con ${permCount} permiso(s) activos`
          : 'Rol creado sin permisos asignados'}
      </div>
    )
  }
  return null
}

export default function PermissionAudit() {
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [filterAction, setFilterAction] = useState('')

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      const params = { limit: 50, offset: 0 }
      if (filterAction) params.action = filterAction
      const { data } = await api.get('/api/permission-audit', { params })
      setItems(data.items || [])
      setTotal(data.total || 0)
    } catch (e) {
      const detail = e?.response?.data?.detail || 'Error al cargar auditoria'
      setError(detail)
    } finally {
      setLoading(false)
    }
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { load() }, [filterAction])

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 text-sm text-gray-600">
          <Shield size={16} />
          <span>{total} {total === 1 ? 'entrada' : 'entradas'} de auditoria</span>
        </div>
        <div className="flex items-center gap-2">
          <Filter size={14} className="text-gray-400" />
          <select
            value={filterAction}
            onChange={(e) => setFilterAction(e.target.value)}
            className="text-sm border border-gray-200 rounded px-2 py-1"
          >
            <option value="">Todas las acciones</option>
            <option value="role.create">Rol creado</option>
            <option value="role.update_perms">Permisos modificados</option>
            <option value="role.update_meta">Rol actualizado</option>
            <option value="role.delete">Rol eliminado</option>
            <option value="user.role_change">Rol asignado</option>
          </select>
          <Button variant="ghost" size="sm" onClick={load} title="Recargar">
            <RefreshCw size={14} />
          </Button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 text-sm text-red-700 flex items-center gap-2">
          <AlertCircle size={14} />
          {error}
        </div>
      )}

      {loading ? (
        <div className="flex justify-center py-10"><LoadingSpinner /></div>
      ) : items.length === 0 ? (
        <div className="border border-gray-100 rounded-lg p-10 text-center text-gray-400">
          Sin entradas todavia. Los cambios sobre roles y permisos van a aparecer aca.
        </div>
      ) : (
        <ol className="space-y-2">
          {items.map((entry) => (
            <li
              key={entry.id}
              className="border border-gray-100 rounded-lg p-3 hover:border-gray-200 transition"
            >
              <div className="flex items-start gap-3">
                <div className="w-8 h-8 rounded-full bg-gray-100 flex items-center justify-center shrink-0">
                  <UserIcon size={14} className="text-gray-500" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <ActionBadge action={entry.action} />
                    <span className="text-sm font-medium text-gray-900 truncate">
                      {entry.target_label || entry.target_id}
                    </span>
                    <span className="text-xs text-gray-400 ml-auto">
                      {formatDate(entry.created_at)}
                    </span>
                  </div>
                  <div className="text-xs text-gray-500 mt-0.5">
                    Por <span className="font-medium">{entry.actor_email || 'sistema'}</span>
                    {entry.ip_address && (
                      <span className="text-gray-300"> · IP {entry.ip_address}</span>
                    )}
                  </div>
                  <div className="mt-2">
                    <EntryDetails entry={entry} />
                  </div>
                </div>
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}
