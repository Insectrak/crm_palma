/**
 * AdminTeamsBlockedBanner — banner unificado para admins.
 *
 * Muestra al inicio de Reparto de leads (/rotacion) un resumen rojo cuando
 * UNO O MAS equipos estan blocked por el circuit breaker (ADR-0010).
 *
 * Diferencia con TeamBlockedBanner (que se muestra al supervisor en su
 * Dashboard): este es para el admin y agrega todos los equipos bloqueados.
 *
 * Auto-refresh cada 30s para que desaparezca cuando los equipos se desbloquean.
 */
import { useCallback, useEffect, useState } from 'react'
import { ShieldOff, X } from 'lucide-react'

import api from '../../lib/api'

const REFRESH_MS = 30_000

export default function AdminTeamsBlockedBanner({ dismissable = true }) {
  const [teams, setTeams] = useState([])
  const [dismissed, setDismissed] = useState(false)

  const load = useCallback(async () => {
    try {
      const res = await api.get('/api/v1/team-health/')
      const all = res.data?.teams || []
      const blocked = all.filter(t => t.status === 'blocked')
      setTeams(blocked)
      if (blocked.length === 0) setDismissed(false)
    } catch {
      setTeams([])
    }
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, REFRESH_MS)
    return () => clearInterval(id)
  }, [load])

  if (teams.length === 0 || dismissed) return null

  return (
    <div className="relative flex items-start gap-3 p-4 bg-red-50 border-2 border-red-300 rounded-lg shadow-sm">
      <ShieldOff className="text-red-600 shrink-0 mt-0.5" size={20} />
      <div className="flex-1">
        <div className="font-semibold text-red-900 mb-1">
          {teams.length === 1
            ? '1 equipo pausado automáticamente'
            : `${teams.length} equipos pausados automáticamente`}
        </div>
        <p className="text-sm text-red-800 mb-2">
          Los nuevos leads se están enviando a otros equipos disponibles. Estos equipos
          no tienen asesores disponibles para recibir leads (todos están pausados, ausentes o llenos). Reactiva asesores en{' '}
          <span className="font-semibold">Configuración → Equipos</span> o avísale al supervisor.
        </p>
        <div className="flex flex-wrap gap-2">
          {teams.map(t => {
            const pct = Math.round((t.pct_pausados || 0) * 100)
            return (
              <span
                key={t.supervisor_id}
                className="inline-flex items-center gap-1.5 px-2.5 py-1 bg-white border border-red-200 rounded-md text-xs text-red-900"
                title={`${t.asesores_pausados}/${t.total_asesores} asesores pausados`}
              >
                <span className="w-1.5 h-1.5 rounded-full bg-red-500" />
                <strong>{t.supervisor_nombre || 'Supervisor'}</strong>
                <span className="opacity-70">· {t.asesores_pausados}/{t.total_asesores} pausados · {pct}%</span>
              </span>
            )
          })}
        </div>
      </div>
      {dismissable && (
        <button
          onClick={() => setDismissed(true)}
          className="text-red-400 hover:text-red-600 transition-colors"
          aria-label="Cerrar"
        >
          <X size={16} />
        </button>
      )}
    </div>
  )
}
