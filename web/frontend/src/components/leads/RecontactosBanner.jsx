/**
 * RecontactosBanner — V094.1 re-engagement workflow con escalacion de severidad.
 *
 * Patron CRMs profesionales "SLA escalation":
 *
 *   amber: recontactos en ultimas 48h sin atender → "Atender ahora"
 *   red:   recontactos hace >=48h sin atender    → "URGENTE, ya se debio haber atendido"
 *
 * Si hay ambos tiers, el rojo es predominante (mas urgente). Se muestra
 * el conteo amber como contexto secundario en el mismo banner.
 *
 * Sin tier: no renderiza nada.
 *
 * Click → activa filtro recontacto_sin_atender (devuelve AMBOS tiers
 * juntos, sin cap de tiempo). El user ve la lista completa pendiente.
 *
 * V095.6 — banner compacto (de card 70px a pill 36px) para no empujar
 * la tabla fuera del viewport y dejar el scroll horizontal accesible
 * sin tener que scrollear vertical primero. Patron patrón estándar header alerts.
 */
import { AlertCircle, AlertTriangle } from 'lucide-react'

export default function RecontactosBanner({ amber = 0, red = 0, oldestDays = 0, isLoading, onActivateFilter }) {
  if (isLoading) return null
  if (!amber && !red) return null

  // ── Tier RED predominante (>=48h sin atender) ─────────────────────────────
  if (red > 0) {
    const diasLabel = oldestDays >= 1
      ? `hace ${oldestDays} ${oldestDays === 1 ? 'día' : 'días'}`
      : 'hace más de 48 h'
    return (
      <div
        role="alert"
        className="rounded-lg border px-3 py-1.5 flex items-center gap-2 bg-red-50 border-red-300 text-xs"
      >
        <AlertTriangle size={14} className="shrink-0 text-red-600" />
        <span className="font-bold text-red-900 whitespace-nowrap">
          {red} {red === 1 ? 'cliente esperando' : 'clientes esperando'} {diasLabel}
        </span>
        <span className="text-red-700/80 truncate flex-1 min-w-0">
          · superó SLA 48 h
          {amber > 0 && <> · {amber} reciente{amber !== 1 ? 's' : ''} (&lt;48 h)</>}
        </span>
        <button
          onClick={onActivateFilter}
          className="font-bold px-2.5 py-1 rounded-md transition-colors shrink-0 bg-red-600 hover:bg-red-700 text-white"
        >
          Atender →
        </button>
      </div>
    )
  }

  // ── Tier AMBER (solo recientes <48h) ──────────────────────────────────────
  return (
    <div
      role="status"
      className="rounded-lg border px-3 py-1.5 flex items-center gap-2 bg-amber-50 border-amber-200 text-xs"
    >
      <AlertCircle size={14} className="shrink-0 text-amber-600" />
      <span className="font-semibold text-amber-900 whitespace-nowrap">
        {amber} {amber === 1 ? 'cliente volvió' : 'clientes volvieron'} a interesarse
      </span>
      <span className="text-amber-700/80 truncate flex-1 min-w-0">
        · últimas 48 h sin contacto
      </span>
      <button
        onClick={onActivateFilter}
        className="font-semibold px-2.5 py-1 rounded-md transition-colors shrink-0 bg-amber-200 hover:bg-amber-300 text-amber-900"
      >
        Ver →
      </button>
    </div>
  )
}
