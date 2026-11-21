/**
 * TeamBlockedBanner — banner rojo prominente para el dashboard del supervisor
 * cuando su equipo entero esta bloqueado por el circuit breaker.
 *
 * V070.78 (ADR-0010 — Team Circuit Breaker).
 *
 * Consume GET /api/v1/team-health (filtra a solo el equipo del current_user)
 * y muestra el banner solo si status === 'blocked'.
 *
 * Cuando aparece, ofrece CTA directo a la pagina de configuracion del equipo
 * (donde el supervisor puede reactivar asesores).
 *
 * Auto-refresh cada 30s para que desaparezca apenas el equipo se desbloquea.
 *
 * Props:
 *   - dismissable    bool  (default true) si true, permite cerrar manualmente
 *                          (se reabre tras refresh si sigue blocked).
 */
import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ShieldOff, X } from 'lucide-react'

import api from '../../lib/api'

const REFRESH_MS = 30_000

export default function TeamBlockedBanner({ dismissable = true }) {
  const [status, setStatus] = useState(null)
  const [dismissed, setDismissed] = useState(false)

  const load = useCallback(async () => {
    try {
      const res = await api.get('/api/v1/team-health/')
      const teams = res.data?.teams || []
      // El backend para supervisor devuelve solo SU equipo
      const myTeam = teams[0] || null
      setStatus(myTeam)
      // Si el equipo dejo de estar blocked, resetear el dismiss
      if (myTeam?.status !== 'blocked') setDismissed(false)
    } catch {
      setStatus(null)
    }
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, REFRESH_MS)
    return () => clearInterval(id)
  }, [load])

  if (!status || status.status !== 'blocked' || dismissed) return null

  const pct = Math.round((status.pct_pausados || 0) * 100)

  return (
    <div className="relative flex items-start gap-3 p-4 bg-red-50 border-2 border-red-300 rounded-lg shadow-sm">
      <ShieldOff className="text-red-600 shrink-0 mt-0.5" size={20} />
      <div className="flex-1">
        <div className="font-semibold text-red-900 mb-1">
          Tu equipo esta BLOQUEADO
        </div>
        <p className="text-sm text-red-800 mb-2">
          No tienes asesores disponibles para recibir leads ({status.asesores_pausados} de {status.total_asesores} asesores están pausados, ausentes o llenos).
          Los nuevos leads se están asignando a otros equipos hasta que reactives asesores. Tu cola actual sigue siendo tu responsabilidad.
        </p>
        <Link
          to="/configuracion?tab=equipos"
          className="inline-flex items-center gap-1 px-3 py-1.5 bg-red-600 hover:bg-red-700 text-white text-sm font-medium rounded-md transition-colors"
        >
          Reactivar asesores →
        </Link>
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
