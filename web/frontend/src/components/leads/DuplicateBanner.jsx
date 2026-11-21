/**
 * DuplicateBanner — V067: alerta inline cuando se detecta un lead
 * duplicado (por telefono, email o DNI) en /leads/nuevo.
 *
 * Patron patrón estándar / patrón estándar "Allow user to save duplicate":
 * - No bloquea — informa.
 * - Botones claros: "Ver lead existente" (navega) o "Crear de todos
 *   modos" (pide razon opcional + setea allow_duplicate=true).
 * - Cuando el user ignora y crea con override, el backend registra
 *   created_with_duplicate_override + razon para audit (admin
 *   puede revisar leads creados con override en reportes).
 */
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AlertTriangle, Eye, X } from 'lucide-react'
import { Button } from '@/components/ui/button'

const FIELD_LABELS = {
  telefono: 'teléfono',
  email:    'email',
  dni:      'documento',
}

export default function DuplicateBanner({
  match,           // { id, nombres, apellidos, telefono, email, asesor_nombre, estado_nombre, created_at }
  matchField,      // 'telefono' | 'email' | 'dni'
  overrideActive,  // bool — el user ya hizo click "Crear de todos modos"
  onOverride,      // (reason: string) => void
  onCancelOverride,
  onDismiss,
}) {
  const navigate = useNavigate()
  const [showReason, setShowReason] = useState(false)
  const [reason, setReason] = useState('')

  if (!match) return null

  const fullName = [match.nombres, match.apellidos].filter(Boolean).join(' ') || 'Sin nombre'
  const fieldLabel = FIELD_LABELS[matchField] || 'datos'

  // Si el override ya está activo, mostramos confirmacion sutil
  if (overrideActive) {
    return (
      <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 flex items-center gap-2 text-xs">
        <span className="text-emerald-700">
          ✓ Override activo — se creará un nuevo lead aunque ya exista uno con este {fieldLabel}.
        </span>
        <button
          type="button"
          onClick={onCancelOverride}
          className="ml-auto text-emerald-700 hover:text-emerald-900 font-medium"
        >
          Deshacer
        </button>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
      <div className="flex items-start gap-2.5">
        <AlertTriangle size={16} className="text-amber-600 shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-semibold text-amber-900 mb-1">
            Ya existe un lead con este {fieldLabel}
          </p>
          <div className="text-xs text-amber-800 mb-2.5 space-y-0.5">
            <p>
              <span className="font-medium">{fullName}</span>
              {match.asesor_nombre && (
                <> · asignado a <span className="font-medium">{match.asesor_nombre}</span></>
              )}
              {match.estado_nombre && (
                <> · estado <span className="font-medium">{match.estado_nombre}</span></>
              )}
            </p>
            {match.telefono && (
              <p className="font-mono text-[11px] opacity-80">{match.telefono}</p>
            )}
          </div>
          <div className="flex items-center gap-2 flex-wrap">
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="gap-1.5 bg-white"
              onClick={() => navigate(`/leads/${match.id}`)}
            >
              <Eye size={13} /> Ver lead existente
            </Button>
            {!showReason ? (
              <button
                type="button"
                onClick={() => setShowReason(true)}
                className="text-xs text-amber-700 hover:text-amber-900 underline underline-offset-2 font-medium"
              >
                Crear de todos modos
              </button>
            ) : (
              <div className="flex-1 min-w-[200px] flex items-center gap-1.5">
                <input
                  type="text"
                  value={reason}
                  onChange={e => setReason(e.target.value)}
                  placeholder="Razón (opcional, ej: 'es la esposa, mismo número')"
                  maxLength={255}
                  className="flex-1 text-xs border border-amber-300 rounded-md px-2 py-1 bg-white focus:outline-none focus:ring-2 focus:ring-amber-500"
                  autoFocus
                />
                <Button
                  type="button"
                  size="sm"
                  className="bg-amber-600 hover:bg-amber-700 text-white"
                  onClick={() => { onOverride(reason); setShowReason(false) }}
                >
                  Confirmar
                </Button>
                <button
                  type="button"
                  onClick={() => { setShowReason(false); setReason('') }}
                  className="text-amber-700 hover:text-amber-900 p-1"
                  title="Cancelar"
                >
                  <X size={14} />
                </button>
              </div>
            )}
          </div>
        </div>
        {onDismiss && (
          <button
            type="button"
            onClick={onDismiss}
            className="text-amber-400 hover:text-amber-700 p-0.5 shrink-0"
            title="Ocultar"
          >
            <X size={14} />
          </button>
        )}
      </div>
    </div>
  )
}
