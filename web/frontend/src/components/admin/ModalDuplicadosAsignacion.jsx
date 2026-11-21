import { useState, useMemo } from 'react'
import {
  X, AlertTriangle, ExternalLink, Search, UserCheck, ShieldAlert,
  Phone, Mail, CheckCircle2
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'

export default function ModalDuplicadosAsignacion({
  open,
  onClose,
  duplicates = [],
  promotedCount = 0,
  asesorNombre = '',
  onGoToDuplicatesTab = null,
}) {
  const [searchTerm, setSearchTerm] = useState('')

  const filteredDuplicates = useMemo(() => {
    if (!searchTerm.trim()) return duplicates
    const term = searchTerm.toLowerCase().trim()
    return duplicates.filter(d =>
      (d.nombre || '').toLowerCase().includes(term) ||
      (d.telefono || '').toLowerCase().includes(term) ||
      (d.email || '').toLowerCase().includes(term) ||
      (d.crm_lead_nombre || '').toLowerCase().includes(term) ||
      (d.crm_asesor_nombre || '').toLowerCase().includes(term) ||
      String(d.crm_lead_id || '').includes(term)
    )
  }, [duplicates, searchTerm])

  if (!open) return null

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div className="bg-white dark:bg-[#121a29] border border-gray-200 dark:border-slate-800 rounded-2xl shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col overflow-hidden animate-in zoom-in-95 duration-200">
        
        {/* Header */}
        <div className="p-5 border-b border-gray-100 dark:border-slate-800 bg-amber-50/50 dark:bg-amber-950/20 flex items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="p-2.5 bg-amber-100 dark:bg-amber-900/40 text-amber-600 dark:text-amber-400 rounded-xl mt-0.5 shrink-0">
              <ShieldAlert size={24} />
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="text-lg font-bold text-gray-900 dark:text-slate-100">
                  Leads Duplicados Omitidos
                </h3>
                <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-amber-100 text-amber-800 dark:bg-amber-900/50 dark:text-amber-300 border border-amber-200 dark:border-amber-800/60">
                  {duplicates.length} {duplicates.length === 1 ? 'duplicado detectado' : 'duplicados detectados'}
                </span>
              </div>
              <p className="text-xs text-gray-600 dark:text-slate-300 mt-1 leading-relaxed">
                Estos registros ya existen actualmente en la página principal de <strong>Leads</strong>.
                La asignación fue <strong>omitida automáticamente</strong> para evitar crear leads repetidos en el CRM.
              </p>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 rounded-lg text-gray-400 hover:text-gray-600 dark:hover:text-slate-200 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Resumen de éxito si hubo asignados */}
        {promotedCount > 0 && (
          <div className="px-5 py-3 bg-emerald-50 dark:bg-emerald-950/30 border-b border-emerald-100 dark:border-emerald-900/40 flex items-center gap-2 text-xs text-emerald-800 dark:text-emerald-300 font-medium">
            <CheckCircle2 size={16} className="text-emerald-600 shrink-0" />
            <span>
              <strong>{promotedCount} lead(s)</strong> no duplicados fueron asignados a <strong>{asesorNombre}</strong> exitosamente.
            </span>
          </div>
        )}

        {/* Buscador interno */}
        <div className="p-4 border-b border-gray-100 dark:border-slate-800 bg-white dark:bg-[#121a29] flex items-center justify-between gap-3">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={15} />
            <input
              type="text"
              placeholder="Buscar por nombre, teléfono o asesor…"
              value={searchTerm}
              onChange={e => setSearchTerm(e.target.value)}
              className="w-full pl-9 pr-3 py-1.5 text-xs bg-gray-50 dark:bg-slate-900/60 border border-gray-200 dark:border-slate-800 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500 text-gray-800 dark:text-slate-200"
            />
          </div>
          <span className="text-xs text-gray-500 dark:text-slate-400">
            Mostrando {filteredDuplicates.length} de {duplicates.length}
          </span>
        </div>

        {/* Tabla de duplicados */}
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {filteredDuplicates.length === 0 ? (
            <div className="py-10 text-center text-xs text-gray-500">
              No se encontraron duplicados con el término de búsqueda.
            </div>
          ) : (
            <div className="border border-gray-200 dark:border-slate-800 rounded-xl overflow-hidden shadow-sm">
              <table className="w-full text-left text-xs border-collapse">
                <thead className="bg-gray-50 dark:bg-slate-900/80 text-gray-600 dark:text-slate-400 font-semibold border-b border-gray-200 dark:border-slate-800">
                  <tr>
                    <th className="p-3">Lead Histórico</th>
                    <th className="p-3">Coincidencia</th>
                    <th className="p-3">Lead Existente en CRM</th>
                    <th className="p-3">Asesor Actual en CRM</th>
                    <th className="p-3 text-center">Acción</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100 dark:divide-slate-800 bg-white dark:bg-[#121a29]">
                  {filteredDuplicates.map((item, idx) => (
                    <tr key={item.historico_id || idx} className="hover:bg-amber-50/30 dark:hover:bg-amber-950/10 transition-colors">
                      <td className="p-3">
                        <div className="font-semibold text-gray-900 dark:text-slate-100">
                          {item.nombre || 'Sin nombre'}
                        </div>
                        <div className="flex items-center gap-2 text-[11px] text-gray-500 dark:text-slate-400 mt-0.5">
                          {item.telefono && (
                            <span className="flex items-center gap-1 font-mono">
                              <Phone size={10} /> {item.telefono}
                            </span>
                          )}
                          {item.email && (
                            <span className="flex items-center gap-1">
                              <Mail size={10} /> {item.email}
                            </span>
                          )}
                        </div>
                      </td>

                      <td className="p-3">
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-[11px] font-medium bg-amber-100 text-amber-800 dark:bg-amber-950/60 dark:text-amber-300 border border-amber-200 dark:border-amber-900/50">
                          <AlertTriangle size={11} />
                          {item.match_field ? `Por ${item.match_field}` : 'Duplicado'}
                        </span>
                        <p className="text-[10px] text-gray-500 dark:text-slate-400 mt-0.5 line-clamp-1" title={item.motivo}>
                          {item.motivo}
                        </p>
                      </td>

                      <td className="p-3">
                        <div className="font-semibold text-indigo-600 dark:text-indigo-400">
                          {item.crm_lead_nombre || `Lead #${item.crm_lead_id}`}
                        </div>
                        <div className="text-[11px] text-gray-500 dark:text-slate-400 flex items-center gap-1.5 mt-0.5">
                          <span>ID: #{item.crm_lead_id}</span>
                          <span>•</span>
                          <Badge variant="outline" className="text-[10px] px-1 py-0 h-4">
                            {item.crm_estado_nombre || 'Activo'}
                          </Badge>
                        </div>
                      </td>

                      <td className="p-3">
                        <div className="flex items-center gap-1 text-gray-800 dark:text-slate-200 font-medium">
                          <UserCheck size={12} className="text-gray-400" />
                          <span>{item.crm_asesor_nombre || 'Sin asesor'}</span>
                        </div>
                      </td>

                      <td className="p-3 text-center">
                        {item.crm_lead_id && (
                          <a
                            href={`/leads/${item.crm_lead_id}`}
                            target="_blank"
                            rel="noreferrer"
                            className="inline-flex items-center gap-1 px-2 py-1 bg-indigo-50 hover:bg-indigo-100 text-indigo-700 dark:bg-indigo-950/50 dark:hover:bg-indigo-900/60 dark:text-indigo-300 rounded text-xs font-medium transition-colors"
                            title="Abrir lead en CRM en una pestaña nueva"
                          >
                            <ExternalLink size={12} />
                            Ver lead
                          </a>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-gray-100 dark:border-slate-800 bg-gray-50/50 dark:bg-[#0c121e]/60 flex items-center justify-between gap-3">
          <div>
            {onGoToDuplicatesTab && (
              <button
                type="button"
                onClick={() => {
                  onClose()
                  onGoToDuplicatesTab()
                }}
                className="text-xs font-medium text-amber-700 hover:text-amber-800 dark:text-amber-400 hover:underline inline-flex items-center gap-1"
              >
                Ver todos en la pestaña &quot;Duplicados&quot; →
              </button>
            )}
          </div>
          <Button variant="default" onClick={onClose}>
            Entendido
          </Button>
        </div>

      </div>
    </div>
  )
}
