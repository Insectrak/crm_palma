import { useState, useEffect } from 'react'
import { Shield, X, Info } from 'lucide-react'
import { safeLocal } from '@/lib/safeStorage'

const ACK_STORAGE_KEY = 'security_policy_ack_v2'  // V061: bump key (banner rediseñado)

/**
 * Banner informativo de política de protección de datos.
 *
 * V061 — Rediseño world-class (patrón estándar/patrón premium):
 *   - Banner SLIM de 1 línea (antes ocupaba 80px de alto y dominaba la
 *     vista). Ahora ~32px y se integra al flujo de la página.
 *   - "Ver detalles" expande la explicación completa en un popover
 *     in-place (sin modal pesado), para usuarios que quieran leer todo.
 *   - Dismiss persistente vía localStorage — una vez aceptado no
 *     reaparece. La info sigue accesible vía Configuración → Política
 *     de privacidad si el admin la documenta ahí.
 *
 * Propósito:
 *   - Informar al usuario que la sección tiene medidas de seguridad
 *     (marca de agua, bloqueo de copia, audit log) ANTES de que las
 *     descubra frustrado intentando Ctrl+C.
 *   - Reducir reclamos al soporte ("no puedo copiar", "¿por qué no hay
 *     botón de Excel?").
 *   - Dejar claro que la política la dicta la empresa, no un bug.
 *
 * Props:
 *   role — rol del usuario actual ('admin' | 'supervisor' | 'asesor').
 *          Cambia el mensaje sobre exportación Excel.
 */
export default function SecurityPolicyBanner({ role = 'asesor' }) {
  const [visible, setVisible] = useState(false)
  const [expanded, setExpanded] = useState(false)

  useEffect(() => {
    // Solo mostrar si el usuario no lo ha reconocido antes.
    const ack = safeLocal.getItem(ACK_STORAGE_KEY)
    if (!ack) setVisible(true)
  }, [])

  const handleDismiss = () => {
    safeLocal.setItem(ACK_STORAGE_KEY, new Date().toISOString())
    setVisible(false)
  }

  if (!visible) return null

  const canExport = role === 'admin' || role === 'supervisor'

  return (
    <div className="relative bg-blue-50/60 border border-blue-100 rounded-lg overflow-hidden">
      {/* Línea principal: compacta, una sola línea (truncate en móvil) */}
      <div className="flex items-center gap-2 px-3 py-2">
        <Shield size={13} className="text-blue-600 shrink-0" />
        <p className="flex-1 min-w-0 text-xs text-blue-900 truncate">
          <strong>Datos protegidos:</strong>
          <span className="text-blue-800 ml-1">
            marca de agua + sin copia + auditoría completa.
          </span>
          <button
            onClick={() => setExpanded(e => !e)}
            className="ml-2 text-blue-600 hover:text-blue-800 underline underline-offset-2 font-medium"
            type="button"
          >
            {expanded ? 'Ocultar' : 'Ver detalles'}
          </button>
        </p>
        <button
          onClick={handleDismiss}
          className="shrink-0 p-1 rounded text-blue-500 hover:text-blue-700 hover:bg-blue-100 transition-colors"
          aria-label="Entendido"
          title="Entendido — no volver a mostrar"
          type="button"
        >
          <X size={13} />
        </button>
      </div>

      {/* Detalle expandible — solo cuando el user pide ver más */}
      {expanded && (
        <div className="border-t border-blue-100 bg-white/40 px-3 py-2.5 text-[11px] text-blue-900 leading-relaxed">
          <ul className="space-y-1 ml-1">
            <li className="flex items-start gap-1.5">
              <Info size={10} className="mt-0.5 shrink-0 text-blue-500" />
              <span>
                Cada vista muestra una <strong>marca de agua</strong> con tu nombre y email
                superpuesta a los datos. Sirve para rastrear capturas de pantalla.
              </span>
            </li>
            <li className="flex items-start gap-1.5">
              <Info size={10} className="mt-0.5 shrink-0 text-blue-500" />
              <span>
                <strong>Copiar al portapapeles está deshabilitado</strong> en esta sección.
                Si necesitas un dato puntual, abre el lead y usa los botones de acción.
              </span>
            </li>
            <li className="flex items-start gap-1.5">
              <Info size={10} className="mt-0.5 shrink-0 text-blue-500" />
              <span>
                Cada acción (búsqueda, filtro, exportación, edición) queda registrada en
                el <strong>historial de auditoría</strong> con tu identificación, IP y timestamp.
              </span>
            </li>
            <li className="flex items-start gap-1.5">
              <Info size={10} className="mt-0.5 shrink-0 text-blue-500" />
              {canExport ? (
                <span>
                  La descarga a Excel está <strong>limitada a 10 000 registros</strong> por consulta
                  — para volúmenes mayores, segmentá con filtros.
                </span>
              ) : (
                <span>
                  La descarga a Excel está reservada a <strong>supervisores y administración</strong>.
                  Si necesitás info específica, contactá a tu supervisor.
                </span>
              )}
            </li>
          </ul>
        </div>
      )}
    </div>
  )
}
