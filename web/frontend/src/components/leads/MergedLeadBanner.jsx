import { useState } from 'react'
import {
  GitMerge, UserCheck, ShieldCheck, Clock, Users,
  ChevronDown, ChevronUp, Info, Phone, ArrowRight,
} from 'lucide-react'
import LeadSummaryPopover from '@/components/leads/LeadSummaryPopover'
import { Button } from '@/components/ui/button'

function formatDateTime(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('es-PE', {
      timeZone: 'America/Lima',
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return String(iso)
  }
}

/**
 * MergedLeadBanner: Aviso visible dentro del lead fusionado informando que
 * su información proviene de dos leads unificados por tener el mismo teléfono.
 */
export default function MergedLeadBanner({
  merges = [],
  currentPhone = '',
  onViewHistory = null,
}) {
  const [isExpanded, setIsExpanded] = useState(true)

  if (!merges || merges.length === 0) return null

  // Tomamos la fusión más reciente
  const latestMerge = merges[0]
  const masterSnap = latestMerge.master_snapshot || {}
  const secondarySnap = latestMerge.secondary_snapshot || {}

  const masterName =
    masterSnap.nombre ||
    [masterSnap.nombres, masterSnap.apellidos].filter(Boolean).join(' ') ||
    `Lead #${latestMerge.master_id}`

  const secondaryName =
    secondarySnap.nombre ||
    [secondarySnap.nombres, secondarySnap.apellidos].filter(Boolean).join(' ') ||
    `Lead #${latestMerge.secondary_id}`

  const chosenOwner = latestMerge.chosen_owner_name || 'Asesor asignado'

  return (
    <div className="mb-5 rounded-xl border border-purple-200 dark:border-purple-800/70 bg-gradient-to-r from-purple-50 via-indigo-50/60 to-purple-50/40 dark:from-purple-950/40 dark:via-indigo-950/30 dark:to-purple-950/20 p-4 shadow-xs">
      <div className="flex items-start justify-between gap-3">
        {/* Cabecera del aviso */}
        <div className="flex items-start gap-3">
          <div className="w-9 h-9 rounded-xl bg-purple-600 text-white flex items-center justify-center shrink-0 shadow-sm mt-0.5">
            <GitMerge size={18} />
          </div>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="text-sm font-bold text-purple-950 dark:text-purple-100 flex items-center gap-2">
                Aviso: Información unificada de leads fusionados
              </h3>
              <span className="text-[11px] font-semibold px-2 py-0.5 rounded-full bg-purple-100 dark:bg-purple-900/70 text-purple-800 dark:text-purple-300 border border-purple-200 dark:border-purple-800">
                Mismo teléfono {currentPhone ? `(${currentPhone})` : ''}
              </span>
            </div>
            <p className="text-xs text-purple-900/90 dark:text-purple-200/90 mt-1 leading-relaxed">
              Este registro consolida la información y el historial de dos leads que compartían el mismo número.
              La autoridad de gestión fue asignada a{' '}
              <strong className="text-purple-950 dark:text-purple-100 underline decoration-purple-300 underline-offset-2">
                {chosenOwner}
              </strong>.
            </p>
          </div>
        </div>

        {/* Toggle para detalles */}
        <button
          type="button"
          onClick={() => setIsExpanded((prev) => !prev)}
          className="text-purple-700 hover:text-purple-950 dark:text-purple-300 p-1 rounded-lg hover:bg-purple-100/60 dark:hover:bg-purple-900/40 transition-colors shrink-0"
          title={isExpanded ? 'Ocultar detalles' : 'Mostrar detalles'}
        >
          {isExpanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
      </div>

      {isExpanded && (
        <div className="mt-3.5 pt-3 border-t border-purple-200/80 dark:border-purple-800/60">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-3">
            {/* Tarjeta de Lead 1 (Principal) con Popover al pasar cursor */}
            <div className="p-2.5 rounded-lg bg-white/90 dark:bg-slate-900/80 border border-purple-100 dark:border-purple-900/60 shadow-2xs">
              <span className="text-[10px] font-bold uppercase tracking-wider text-purple-700 dark:text-purple-300 block mb-1">
                Lead Principal (ID #{latestMerge.master_id})
              </span>
              <div className="flex items-center justify-between gap-2">
                <LeadSummaryPopover
                  lead={{
                    ...masterSnap,
                    id: latestMerge.master_id,
                    nombre: masterName,
                  }}
                  titlePrefix="Lead Principal"
                >
                  <span className="text-xs font-semibold text-gray-900 dark:text-slate-100 hover:text-purple-700 dark:hover:text-purple-300 underline decoration-dotted decoration-purple-400 cursor-help transition-colors">
                    {masterName}
                  </span>
                </LeadSummaryPopover>
                <span className="text-[11px] text-gray-500 dark:text-slate-400 truncate max-w-[140px]">
                  {masterSnap.asesor_nombre ? `Dueño: ${masterSnap.asesor_nombre}` : 'Sin asesor'}
                </span>
              </div>
              <p className="text-[10px] text-gray-400 dark:text-slate-500 mt-1">
                Pasa el cursor sobre el nombre para ver su ficha previa
              </p>
            </div>

            {/* Tarjeta de Lead 2 (Secundario/Absorbido) con Popover al pasar cursor */}
            <div className="p-2.5 rounded-lg bg-white/90 dark:bg-slate-900/80 border border-purple-100 dark:border-purple-900/60 shadow-2xs">
              <span className="text-[10px] font-bold uppercase tracking-wider text-indigo-700 dark:text-indigo-300 block mb-1">
                Lead Fusionado / Absorbido (ID #{latestMerge.secondary_id})
              </span>
              <div className="flex items-center justify-between gap-2">
                <LeadSummaryPopover
                  lead={{
                    ...secondarySnap,
                    id: latestMerge.secondary_id,
                    nombre: secondaryName,
                  }}
                  titlePrefix="Lead Fusionado"
                >
                  <span className="text-xs font-semibold text-gray-900 dark:text-slate-100 hover:text-indigo-700 dark:hover:text-indigo-300 underline decoration-dotted decoration-indigo-400 cursor-help transition-colors">
                    {secondaryName}
                  </span>
                </LeadSummaryPopover>
                <span className="text-[11px] text-gray-500 dark:text-slate-400 truncate max-w-[140px]">
                  {secondarySnap.asesor_nombre ? `Dueño: ${secondarySnap.asesor_nombre}` : 'Sin asesor'}
                </span>
              </div>
              <p className="text-[10px] text-gray-400 dark:text-slate-500 mt-1">
                Pasa el cursor sobre el nombre para ver su ficha previa
              </p>
            </div>
          </div>

          {/* Metadatos de la fusión */}
          <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-purple-900/80 dark:text-purple-300/80 pt-1">
            <div className="flex items-center gap-3 flex-wrap text-[11px]">
              <span className="inline-flex items-center gap-1 font-medium">
                <ShieldCheck size={13} className="text-purple-600 dark:text-purple-400" />
                Autoridad elegida: <span className="font-bold text-purple-950 dark:text-purple-100">{chosenOwner}</span>
              </span>
              <span>·</span>
              <span className="inline-flex items-center gap-1">
                <Clock size={12} className="text-purple-500" />
                Fusionado el {formatDateTime(latestMerge.merged_at)}
                {latestMerge.merged_by_name ? ` por ${latestMerge.merged_by_name}` : ''}
              </span>
              {(latestMerge.contactos_migrated > 0 || latestMerge.llamadas_migrated > 0) && (
                <>
                  <span>·</span>
                  <span className="font-medium text-emerald-700 dark:text-emerald-400">
                    ✓ {latestMerge.contactos_migrated} interacciones y {latestMerge.llamadas_migrated} llamadas integradas
                  </span>
                </>
              )}
            </div>

            {onViewHistory && (
              <button
                type="button"
                onClick={onViewHistory}
                className="text-xs font-semibold text-purple-700 hover:text-purple-900 dark:text-purple-300 dark:hover:text-purple-100 underline underline-offset-2"
              >
                Ver en Historial →
              </button>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

