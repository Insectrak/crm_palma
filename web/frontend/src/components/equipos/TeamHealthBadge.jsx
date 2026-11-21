/**
 * TeamHealthBadge — muestra el estado de salud del equipo (active/at_risk/blocked).
 *
 * V070.78 (ADR-0010 — Team Circuit Breaker).
 *
 * Consume GET /api/v1/team-health y muestra:
 *   - Badge con color (verde/amarillo/rojo) + label
 *   - Tooltip con stats (X de Y pausados, %)
 *   - Auto-refresh cada 30s
 *
 * Props:
 *   - supervisorId   string?  UUID del supervisor a consultar. Si null, el
 *                             backend devuelve los equipos visibles para el
 *                             current_user (admin: todos; supervisor: el suyo).
 *   - team           object?  Objeto de team-health ya pre-cargado por el padre.
 *                             Si se pasa, NO se hace fetch (util para tablas
 *                             donde el padre ya tiene la lista completa).
 *   - showLabel      bool     (default true) si false, solo el dot circular.
 *   - className      string?  clases extras de Tailwind.
 */
import { useCallback, useEffect, useState } from 'react'
import { CheckCircle2, AlertTriangle, ShieldOff } from 'lucide-react'

import api from '../../lib/api'

const REFRESH_MS = 30_000

const STATUS_CONFIG = {
  active: {
    label:   'Activo',
    color:   'emerald',
    Icon:    CheckCircle2,
    bgClass: 'bg-emerald-50 border-emerald-200 text-emerald-700',
    dotClass: 'bg-emerald-500',
  },
  at_risk: {
    label:   'En riesgo',
    color:   'amber',
    Icon:    AlertTriangle,
    bgClass: 'bg-amber-50 border-amber-200 text-amber-800',
    dotClass: 'bg-amber-500',
  },
  blocked: {
    label:   'Bloqueado',
    color:   'red',
    Icon:    ShieldOff,
    bgClass: 'bg-red-50 border-red-300 text-red-700',
    dotClass: 'bg-red-500',
  },
}

export default function TeamHealthBadge({ supervisorId, team, showLabel = true, className = '' }) {
  const [status, setStatus] = useState(team || null)
  const [loading, setLoading] = useState(!team)

  const load = useCallback(async () => {
    try {
      const res = await api.get('/api/v1/team-health/')
      const teams = res.data?.teams || []
      const match = supervisorId
        ? teams.find(t => t.supervisor_id === supervisorId)
        : teams[0]  // si el supervisor consulta sin id, devuelve solo el suyo
      setStatus(match || null)
    } catch {
      setStatus(null)
    } finally {
      setLoading(false)
    }
  }, [supervisorId])

  useEffect(() => {
    if (team) {
      setStatus(team)
      setLoading(false)
      return
    }
    load()
    const id = setInterval(load, REFRESH_MS)
    return () => clearInterval(id)
  }, [load, team])

  if (loading || !status) return null

  const cfg = STATUS_CONFIG[status.status] || STATUS_CONFIG.active
  const { Icon, bgClass, dotClass } = cfg
  const pct = Math.round((status.pct_pausados || 0) * 100)
  const tooltip =
    `Equipo de ${status.supervisor_nombre || 'supervisor'}\n` +
    `${status.asesores_pausados}/${status.total_asesores} asesores pausados (${pct}%)`

  if (!showLabel) {
    // Solo el dot (para usar inline en listas compactas)
    return (
      <span
        className={`inline-block w-2 h-2 rounded-full ${dotClass} ${className}`}
        title={tooltip}
        aria-label={`Estado: ${cfg.label}`}
      />
    )
  }

  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-md border text-[11px] font-medium ${bgClass} ${className}`}
      title={tooltip}
    >
      <Icon size={12} />
      <span>{cfg.label}</span>
      <span className="opacity-70">· {pct}%</span>
    </span>
  )
}
