/**
 * TogglesInconsistencyBanner — alerta UX cuando dos toggles de routing
 * estan en configuracion inusual.
 *
 * Issue #59 — Toggles independientes con visualizacion de inconsistencias.
 *
 * Hay 2 toggles que controlan el routing de un supervisor:
 *  - activo_rotacion (auth.users): si participa en distribucion entre supervisores
 *  - auto_asignar_enabled (crm.equipos): si su equipo recibe leads auto-asignados al asesor
 *
 * Son independientes a proposito (soporta casos como "supervisor en escalation").
 * Pero ciertas combinaciones tienen consecuencias no obvias para el admin:
 *
 *   Combinacion        | Resultado                                    | Severidad
 *   -------------------+----------------------------------------------+-----------
 *   Sup ON  + Team ON  | Normal: lead se distribuye al asesor         | OK
 *   Sup OFF + Team OFF | Pausa total — equipo NO recibe nada          | OK
 *   Sup ON  + Team OFF | Leads llegan al supervisor pero se acumulan  | WARNING
 *                      | en su cola (no van al asesor)                |
 *   Sup OFF + Team ON  | Equipo configurado para auto-asignar pero    | WARNING
 *                      | el supervisor no recibe leads nuevos         |
 *
 * Auto-refresh cada 30s para alinearse con la pantalla Reparto.
 */
import { useCallback, useEffect, useState } from 'react'
import { AlertTriangle } from 'lucide-react'

import api from '../../lib/api'

const REFRESH_MS = 30_000

export default function TogglesInconsistencyBanner() {
  const [supervisores, setSupervisores] = useState([])
  const [equipos, setEquipos] = useState([])

  const load = useCallback(async () => {
    try {
      const [supRes, eqRes] = await Promise.all([
        api.get('/api/ingest/rotacion'),
        api.get('/api/admin/assignment/equipos'),
      ])
      setSupervisores(supRes.data?.items || [])
      setEquipos(eqRes.data || [])
    } catch {
      // best-effort: si falla, no mostramos nada
      setSupervisores([])
      setEquipos([])
    }
  }, [])

  useEffect(() => {
    load()
    const id = setInterval(load, REFRESH_MS)
    return () => clearInterval(id)
  }, [load])

  // Detecta inconsistencias matcheando supervisor vs equipo por supervisor_id.
  const inconsistencias = supervisores.flatMap((s) => {
    const equipo = equipos.find((e) => e.supervisor_id === s.supervisor_id)
    if (!equipo) return []

    const supActivo = s.activo_rotacion
    const teamActivo = equipo.auto_asignar_enabled
    const nombre = s.supervisor_nombre || equipo.supervisor_nombre || '—'

    if (supActivo && !teamActivo) {
      return [{
        supervisor_id: s.supervisor_id,
        nombre,
        tipo: 'sup_on_team_off',
        mensaje: `${nombre}: supervisor activo pero su equipo pausado. Los leads se acumulan en su cola sin asignarse al asesor.`,
      }]
    }
    if (!supActivo && teamActivo) {
      return [{
        supervisor_id: s.supervisor_id,
        nombre,
        tipo: 'sup_off_team_on',
        mensaje: `${nombre}: equipo configurado para recibir pero el supervisor está pausado. El equipo no recibirá leads nuevos.`,
      }]
    }
    return []
  })

  if (inconsistencias.length === 0) return null

  return (
    <div className="rounded-xl border border-amber-300 bg-amber-50 p-4 mb-4">
      <div className="flex items-start gap-3">
        <div className="w-8 h-8 rounded-lg bg-amber-100 flex items-center justify-center shrink-0 mt-0.5">
          <AlertTriangle size={16} className="text-amber-700" />
        </div>
        <div className="flex-1 min-w-0">
          <h3 className="text-sm font-semibold text-amber-900">
            Configuración inusual detectada
          </h3>
          <p className="text-xs text-amber-800 mt-0.5 leading-relaxed">
            Los toggles de distribución entre supervisores y auto-asignación dentro del equipo
            son independientes. Estas combinaciones tienen consecuencias no obvias:
          </p>
          <ul className="mt-2 space-y-1.5">
            {inconsistencias.map((i) => (
              <li key={`${i.supervisor_id}-${i.tipo}`} className="text-xs text-amber-900 flex items-start gap-2">
                <span className="inline-block w-1 h-1 rounded-full bg-amber-700 mt-1.5 shrink-0" />
                <span>{i.mensaje}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  )
}
