import React from 'react'
import { useSearchParams } from 'react-router-dom'
import { Building2, FileSpreadsheet, GitBranch, BadgeCheck } from 'lucide-react'
import Separaciones from '@/pages/Separaciones'
import CierresLotesTab from '@/components/gestion-lotes/CierresLotesTab'

export default function GestionLotes() {
  const [searchParams, setSearchParams] = useSearchParams()
  const rawTab = searchParams.get('tab')
  const activeTab = rawTab === 'cierres' ? 'cierres' : 'separaciones'

  const setTab = (tabId) => {
    setSearchParams({ tab: tabId }, { replace: true })
  }

  return (
    <div className="p-6 max-w-[1680px] mx-auto space-y-6 animate-fadeIn text-slate-900 dark:text-slate-100">
      {/* Encabezado Principal Gestión de Lotes */}
      <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm flex flex-col lg:flex-row lg:items-center justify-between gap-4">
        <div className="flex items-start gap-3">
          <span className="p-2.5 bg-[#1F1D5C]/10 text-[#1F1D5C] dark:bg-[#1F1D5C]/40 dark:text-indigo-300 rounded-xl border border-[#1F1D5C]/20">
            <Building2 size={24} />
          </span>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h1 className="text-xl font-bold text-slate-900 dark:text-white">
                Gestión de Lotes
              </h1>
              <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-slate-900 text-white dark:bg-slate-800 dark:text-amber-300">
                Solo Admin · Respaldado en Servidor
              </span>
            </div>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1 flex items-center gap-1.5 flex-wrap">
              <GitBranch size={12} className="text-indigo-500" />
              Control centralizado en PostgreSQL con comparación estilo Git desde Google Drive o archivo Excel (.xlsx / .csv)
            </p>
          </div>
        </div>

        {/* Selector de Pestañas: Separaciones | Cierres */}
        <div className="inline-flex bg-slate-100 dark:bg-[#0c121d] p-1.5 rounded-xl border border-slate-200/70 dark:border-slate-800 self-start lg:self-auto">
          <button
            type="button"
            onClick={() => setTab('separaciones')}
            className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold transition-all cursor-pointer ${
              activeTab === 'separaciones'
                ? 'bg-[#1F1D5C] text-white shadow-sm'
                : 'text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            <FileSpreadsheet size={15} />
            <span>Separaciones</span>
          </button>

          <button
            type="button"
            onClick={() => setTab('cierres')}
            className={`inline-flex items-center gap-2 px-4 py-2 rounded-lg text-xs font-bold transition-all cursor-pointer ${
              activeTab === 'cierres'
                ? 'bg-[#1F1D5C] text-white shadow-sm'
                : 'text-slate-600 dark:text-slate-300 hover:text-slate-900 dark:hover:text-white'
            }`}
          >
            <BadgeCheck size={15} />
            <span>Cierres</span>
          </button>
        </div>
      </div>

      {/* Contenido de la pestaña activa */}
      {activeTab === 'separaciones' ? <Separaciones embedded /> : <CierresLotesTab />}
    </div>
  )
}
