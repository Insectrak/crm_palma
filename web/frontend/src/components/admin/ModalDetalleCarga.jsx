import { useState, useEffect, useMemo } from 'react'
import {
  X, Search, Download, Copy, Check, AlertTriangle, XCircle,
  FileSpreadsheet, User, Calendar, RefreshCw, FileText
} from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import api from '@/lib/api'

export default function ModalDetalleCarga({
  open,
  onClose,
  historialId,
  endpoint = '/api/leads/carga-masiva/historial',
  initialTab = 'duplicates',
  cargaPreview = null,
}) {
  const [activeTab, setActiveTab] = useState(initialTab)
  const [data, setData] = useState(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState(null)
  const [searchTerm, setSearchTerm] = useState('')
  const [copiedPhone, setCopiedPhone] = useState(null)

  useEffect(() => {
    if (open) {
      setActiveTab(initialTab)
      setSearchTerm('')
      setError(null)
      fetchDetails()
    } else {
      setData(null)
    }
  }, [open, historialId, initialTab])

  const fetchDetails = async () => {
    if (!historialId) return
    setIsLoading(true)
    setError(null)
    try {
      const res = await api.get(`${endpoint}/${historialId}/detalles`)
      setData(res.data)
    } catch (err) {
      console.error('Error fetching historial details:', err)
      setError(err?.response?.data?.detail || 'No se pudieron cargar los detalles del historial.')
    } finally {
      setIsLoading(false)
    }
  }

  const duplicatesList = useMemo(() => {
    return Array.isArray(data?.duplicates_details) ? data.duplicates_details : []
  }, [data])

  const errorsList = useMemo(() => {
    return Array.isArray(data?.error_details) ? data.error_details : []
  }, [data])

  const currentList = activeTab === 'duplicates' ? duplicatesList : errorsList

  const filteredList = useMemo(() => {
    if (!searchTerm.trim()) return currentList
    const q = searchTerm.toLowerCase().trim()
    return currentList.filter(item => {
      const nombres = (item.nombres || '').toLowerCase()
      const apellidos = (item.apellidos || '').toLowerCase()
      const telefono = (item.telefono || '').toLowerCase()
      const email = (item.email || '').toLowerCase()
      const dni = (item.dni || '').toLowerCase()
      const motivo = (item.motivo || item.error || '').toLowerCase()
      return (
        nombres.includes(q) ||
        apellidos.includes(q) ||
        telefono.includes(q) ||
        email.includes(q) ||
        dni.includes(q) ||
        motivo.includes(q)
      )
    })
  }, [currentList, searchTerm])

  const handleCopy = (text) => {
    if (!text) return
    navigator.clipboard.writeText(text)
    setCopiedPhone(text)
    setTimeout(() => setCopiedPhone(null), 1800)
  }

  const handleExportCsv = () => {
    if (!currentList || currentList.length === 0) return
    const isDup = activeTab === 'duplicates'
    const headers = ['Fila', 'Nombres', 'Apellidos', 'Telefono', 'Email', 'DNI', isDup ? 'Motivo Duplicado' : 'Motivo Error']
    const csvRows = [headers.join(';')]

    currentList.forEach(r => {
      const rowData = [
        r.row || '—',
        `"${(r.nombres || '').replace(/"/g, '""')}"`,
        `"${(r.apellidos || '').replace(/"/g, '""')}"`,
        `"${(r.telefono || '').replace(/"/g, '""')}"`,
        `"${(r.email || '').replace(/"/g, '""')}"`,
        `"${(r.dni || '').replace(/"/g, '""')}"`,
        `"${(r.motivo || r.error || '').replace(/"/g, '""')}"`,
      ]
      csvRows.push(rowData.join(';'))
    })

    const filename = data?.filename || cargaPreview?.filename || 'carga'
    const cleanName = filename.replace(/\.[^/.]+$/, '')
    const blob = new Blob(['\uFEFF' + csvRows.join('\n')], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${cleanName}_${isDup ? 'duplicados' : 'errores'}.csv`
    document.body.appendChild(a)
    a.click()
    document.body.removeChild(a)
    URL.revokeObjectURL(url)
  }

  if (!open) return null

  const info = data || cargaPreview || {}
  const dupCount = info.duplicates ?? duplicatesList.length
  const errCount = info.errors ?? errorsList.length

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-900/60 backdrop-blur-xs animate-in fade-in duration-150">
      <div
        className="relative w-full max-w-4xl bg-white dark:bg-slate-900 rounded-xl shadow-2xl border border-slate-200 dark:border-slate-800 flex flex-col max-h-[90vh] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between p-4 border-b border-slate-100 dark:border-slate-800 bg-slate-50/80 dark:bg-slate-900/80">
          <div className="flex items-center gap-3">
            <div className="p-2.5 bg-indigo-50 dark:bg-indigo-950/60 text-indigo-600 dark:text-indigo-400 rounded-lg border border-indigo-100 dark:border-indigo-900">
              <FileSpreadsheet size={20} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h3 className="text-base font-bold text-slate-800 dark:text-slate-100 truncate max-w-md" title={info.filename}>
                  {info.filename || 'Archivo de Carga'}
                </h3>
                <Badge variant="outline" className="text-[11px] font-mono border-slate-300 dark:border-slate-700">
                  ID: #{info.id || historialId}
                </Badge>
              </div>
              <div className="flex flex-wrap items-center gap-x-4 gap-y-1 mt-1 text-xs text-slate-500 dark:text-slate-400">
                {info.uploaded_by_nombre && (
                  <span className="flex items-center gap-1">
                    <User size={12} className="text-slate-400" />
                    {info.uploaded_by_nombre}
                  </span>
                )}
                {info.uploaded_at && (
                  <span className="flex items-center gap-1">
                    <Calendar size={12} className="text-slate-400" />
                    {new Date(info.uploaded_at).toLocaleString('es-PE')}
                  </span>
                )}
                <span className="font-medium text-slate-700 dark:text-slate-300">
                  Total: {info.total_rows ?? 0} filas | Importados: {info.inserted ?? 0}
                </span>
              </div>
            </div>
          </div>
          <button
            onClick={onClose}
            className="p-1.5 text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Tabs and Search Bar */}
        <div className="flex flex-col sm:flex-row items-center justify-between gap-3 p-3 bg-white dark:bg-slate-900 border-b border-slate-100 dark:border-slate-800">
          <div className="flex items-center gap-1.5 w-full sm:w-auto">
            <button
              onClick={() => setActiveTab('duplicates')}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                activeTab === 'duplicates'
                  ? 'bg-amber-500 text-white shadow-xs'
                  : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700'
              }`}
            >
              <AlertTriangle size={14} />
              Duplicados
              <span className={`px-1.5 py-0.2 rounded-full text-[10px] font-bold ${
                activeTab === 'duplicates' ? 'bg-amber-600 text-white' : 'bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300'
              }`}>
                {dupCount}
              </span>
            </button>
            <button
              onClick={() => setActiveTab('errors')}
              className={`flex items-center gap-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors ${
                activeTab === 'errors'
                  ? 'bg-red-600 text-white shadow-xs'
                  : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200 dark:hover:bg-slate-700'
              }`}
            >
              <XCircle size={14} />
              Con Errores
              <span className={`px-1.5 py-0.2 rounded-full text-[10px] font-bold ${
                activeTab === 'errors' ? 'bg-red-700 text-white' : 'bg-slate-200 dark:bg-slate-700 text-slate-700 dark:text-slate-300'
              }`}>
                {errCount}
              </span>
            </button>
          </div>

          <div className="flex items-center gap-2 w-full sm:w-auto justify-end">
            <div className="relative flex-1 sm:w-64">
              <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
              <input
                type="text"
                placeholder="Buscar por teléfono, nombre..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-full pl-8 pr-3 py-1.5 text-xs bg-slate-50 dark:bg-slate-800 border border-slate-200 dark:border-slate-700 rounded-lg text-slate-800 dark:text-slate-200 focus:outline-hidden focus:ring-1 focus:ring-indigo-500"
              />
              {searchTerm && (
                <button
                  onClick={() => setSearchTerm('')}
                  className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
                >
                  <X size={12} />
                </button>
              )}
            </div>

            <Button
              variant="outline"
              size="sm"
              onClick={handleExportCsv}
              disabled={currentList.length === 0}
              className="text-xs h-8 gap-1.5 border-slate-200 dark:border-slate-700 text-slate-700 dark:text-slate-300"
              title="Descargar lista en formato CSV"
            >
              <Download size={13} />
              Exportar
            </Button>
          </div>
        </div>

        {/* Content Body */}
        <div className="flex-1 overflow-y-auto p-4 min-h-[250px]">
          {isLoading ? (
            <div className="flex flex-col items-center justify-center py-16 text-slate-500">
              <RefreshCw size={24} className="animate-spin text-indigo-600 mb-2" />
              <p className="text-xs">Cargando registros detallados…</p>
            </div>
          ) : error ? (
            <div className="flex flex-col items-center justify-center py-12 text-center">
              <XCircle size={32} className="text-red-500 mb-2" />
              <p className="text-sm font-medium text-slate-800 dark:text-slate-200">{error}</p>
              <Button variant="outline" size="sm" onClick={fetchDetails} className="mt-3 text-xs">
                Reintentar
              </Button>
            </div>
          ) : currentList.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 text-center text-slate-400">
              {activeTab === 'duplicates' ? (
                <>
                  <AlertTriangle size={32} className="text-slate-300 mb-2" />
                  <p className="text-sm font-medium text-slate-600 dark:text-slate-300">No hay duplicados registrados en esta carga</p>
                  <p className="text-xs text-slate-400 mt-1 max-w-sm">
                    {info.duplicates > 0
                      ? 'Los registros detallados no están disponibles para cargas previas a esta actualización.'
                      : 'Todos los registros procesados fueron importados sin duplicidad.'}
                  </p>
                </>
              ) : (
                <>
                  <XCircle size={32} className="text-slate-300 mb-2" />
                  <p className="text-sm font-medium text-slate-600 dark:text-slate-300">No hay errores registrados en esta carga</p>
                  <p className="text-xs text-slate-400 mt-1 max-w-sm">
                    {info.errors > 0
                      ? 'Los registros detallados no están disponibles para cargas previas a esta actualización.'
                      : 'Todas las filas procesadas cumplieron con los requerimientos de validación.'}
                  </p>
                </>
              )}
            </div>
          ) : filteredList.length === 0 ? (
            <div className="text-center py-10 text-xs text-slate-400">
              No se encontraron registros que coincidan con "{searchTerm}".
            </div>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-slate-50 dark:bg-slate-800/80 border-b border-slate-200 dark:border-slate-700 text-slate-600 dark:text-slate-400">
                    <th className="px-3 py-2.5 text-center font-semibold w-14">Fila</th>
                    <th className="px-3 py-2.5 text-left font-semibold">Nombre / Apellidos</th>
                    <th className="px-3 py-2.5 text-left font-semibold">Teléfono</th>
                    <th className="px-3 py-2.5 text-left font-semibold">Email / DNI</th>
                    <th className="px-3 py-2.5 text-left font-semibold">
                      {activeTab === 'duplicates' ? 'Motivo de Duplicado' : 'Detalle del Error'}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                  {filteredList.map((item, idx) => {
                    const fullName = `${item.nombres || ''} ${item.apellidos || ''}`.trim() || '—'
                    const motivo = item.motivo || item.error || '—'
                    const phone = item.telefono || '—'

                    return (
                      <tr key={idx} className="hover:bg-slate-50/80 dark:hover:bg-slate-800/50 transition-colors">
                        <td className="px-3 py-2 text-center text-slate-500 font-mono text-[11px]">
                          {item.row ?? (idx + 1)}
                        </td>
                        <td className="px-3 py-2 text-slate-800 dark:text-slate-200 font-medium whitespace-nowrap">
                          {fullName}
                        </td>
                        <td className="px-3 py-2 text-slate-700 dark:text-slate-300 font-mono text-[11px] whitespace-nowrap">
                          <div className="flex items-center gap-1.5">
                            <span>{phone}</span>
                            {phone !== '—' && (
                              <button
                                onClick={() => handleCopy(phone)}
                                className="text-slate-400 hover:text-slate-600 dark:hover:text-slate-200 transition-colors"
                                title="Copiar teléfono"
                              >
                                {copiedPhone === phone ? <Check size={11} className="text-emerald-500" /> : <Copy size={11} />}
                              </button>
                            )}
                          </div>
                        </td>
                        <td className="px-3 py-2 text-slate-600 dark:text-slate-400 whitespace-nowrap">
                          <div className="flex flex-col">
                            {item.email && <span className="truncate max-w-[160px]" title={item.email}>{item.email}</span>}
                            {item.dni && <span className="font-mono text-[10px] text-slate-400">DNI: {item.dni}</span>}
                            {!item.email && !item.dni && <span>—</span>}
                          </div>
                        </td>
                        <td className="px-3 py-2">
                          <span
                            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-[11px] font-medium leading-tight ${
                              activeTab === 'duplicates'
                                ? 'bg-amber-50 dark:bg-amber-950/40 text-amber-800 dark:text-amber-300 border border-amber-200/60 dark:border-amber-900/60'
                                : 'bg-red-50 dark:bg-red-950/40 text-red-800 dark:text-red-300 border border-red-200/60 dark:border-red-900/60'
                            }`}
                          >
                            {motivo}
                          </span>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between p-3 border-t border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/50 text-xs text-slate-500">
          <span>
            Mostrando {filteredList.length} de {currentList.length} registros
          </span>
          <Button variant="secondary" size="sm" onClick={onClose} className="text-xs h-7">
            Cerrar
          </Button>
        </div>
      </div>
    </div>
  )
}
