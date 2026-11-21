import React, { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  RotateCcw, PhoneOff, Clock, UserX, Archive, Users, Send,
  CheckCircle2, AlertTriangle, Layers, Filter, Search, Building2,
  Calendar, CheckSquare, Square, X, RefreshCw, ChevronLeft, ChevronRight,
  UserPlus, ExternalLink, History, ArrowRight, UserCheck, Phone, Mail,
  FileSpreadsheet, ChevronDown, Download
} from 'lucide-react'
import api from '@/lib/api'

const CRITERIOS = [
  {
    key: 'no_contesta',
    title: 'No Contesta / Bolsa de Reciclaje',
    desc: 'Leads actualmente en estado "No contesta / Bolsa TMK", "No contesta / Bolsa de reciclaje" o similar',
    icon: PhoneOff,
    color: 'rose',
  },
  {
    key: 'inactivos_30d',
    title: 'Inactivos > 30 Días',
    desc: 'Leads sin avance ni interacciones registradas en el último mes',
    icon: Clock,
    color: 'amber',
  },
  {
    key: 'ex_asesores',
    title: 'Cartera de Ex-asesores',
    desc: 'Leads asignados a cuentas inactivas o dadas de baja',
    icon: UserX,
    color: 'purple',
  },
  {
    key: 'base_historica',
    title: 'Base Histórica / Descarte',
    desc: 'Leads no interesados por motivos recuperables (horarios/precios)',
    icon: Archive,
    color: 'blue',
  },
]

const PAGE_SIZE = 50

export default function BolsaReciclajeTMK() {
  const navigate = useNavigate()
  const [activeTab, setActiveTab] = useState('bolsa') // 'bolsa' | 'lotes'
  const [criterio, setCriterio] = useState('no_contesta')
  const [resumen, setResumen] = useState({})
  const [leads, setLeads] = useState([])
  const [totalLeads, setTotalLeads] = useState(0)
  const [totalPages, setTotalPages] = useState(1)
  const [page, setPage] = useState(1)
  const [search, setSearch] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadingLeads, setLoadingLeads] = useState(false)

  // Filtros
  const [sedeId, setSedeId] = useState('')
  const [sedesList, setSedesList] = useState([])
  const [asesoresList, setAsesoresList] = useState([])
  const [estadosList, setEstadosList] = useState([])

  // Modal de Reasignación Masiva (Lote)
  const [showModal, setShowModal] = useState(false)
  const [nombreLote, setNombreLote] = useState('')
  const [cantidadAsignar, setCantidadAsignar] = useState(50)
  const [selectedAsesores, setSelectedAsesores] = useState([])
  const [submitting, setSubmitting] = useState(false)
  const [successMsg, setSuccessMsg] = useState('')
  const [errorMsg, setErrorMsg] = useState('')

  // Modal de Reasignación Individual Directa
  const [singleReassignTarget, setSingleReassignTarget] = useState(null) // lead object
  const [singleAsesorId, setSingleAsesorId] = useState('')
  const [singleEstadoId, setSingleEstadoId] = useState('')
  const [isReassigningSingle, setIsReassigningSingle] = useState(false)

  // Modal de Reversión Individual a Estado Original
  const [revertTarget, setRevertTarget] = useState(null) // lead object
  const [isReverting, setIsReverting] = useState(false)

  // Modal de Historial de Asignaciones
  const [historyTarget, setHistoryTarget] = useState(null) // lead object

  // Selección múltiple y Desasignación
  const [selectedLeadIds, setSelectedLeadIds] = useState([])
  const [unassignTarget, setUnassignTarget] = useState(null) // lead object para desasignar individual
  const [bulkUnassignConfig, setBulkUnassignConfig] = useState(null) // { mode: 'selected' | 'segment', count?: number }
  const [isUnassigning, setIsUnassigning] = useState(false)

  // Historial de lotes
  const [lotes, setLotes] = useState([])

  // Exportar a Excel
  const [isExporting, setIsExporting] = useState(false)
  const [exportDropdownOpen, setExportDropdownOpen] = useState(false)
  const exportDropdownRef = useRef(null)

  // Debounce para búsqueda
  const debounceRef = useRef(null)
  const handleSearchChange = (val) => {
    setSearchInput(val)
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setSearch(val)
      setPage(1)
    }, 350)
  }

  // Cargar sedes, asesores y estados
  useEffect(() => {
    async function loadData() {
      try {
        const [resSedes, resUsers, resEstados] = await Promise.all([
          api.get('/api/sedes/lookup?only_active=true').catch(() => ({ data: [] })),
          api.get('/auth/users').catch(() => ({ data: [] })),
          api.get('/api/estados').catch(() => ({ data: [] })),
        ])
        setSedesList(resSedes.data || [])
        setAsesoresList((resUsers.data || []).filter(u => (u.role === 'asesor' || u.role === 'supervisor') && u.is_active !== false))
        setEstadosList(resEstados.data || [])
      } catch (err) {
        console.error('Error cargando inicial:', err)
      }
    }
    loadData()
  }, [])

  // Cargar métricas de la bolsa
  const fetchResumen = async () => {
    setLoading(true)
    try {
      const p = sedeId ? `?sede_id=${sedeId}` : ''
      const res = await api.get(`/api/tmk/resumen${p}`)
      setResumen(res.data)
    } catch (err) {
      console.error('Error cargando resumen TMK:', err)
    } finally {
      setLoading(false)
    }
  }

  // Cargar listado de leads paginado
  const fetchLeads = async () => {
    setLoadingLeads(true)
    try {
      const params = new URLSearchParams({
        criterio,
        limit: String(PAGE_SIZE),
        page: String(page),
      })
      if (sedeId) params.append('sede_id', sedeId)
      if (search.trim()) params.append('search', search.trim())

      const res = await api.get(`/api/tmk/leads?${params.toString()}`)
      setLeads(res.data.leads || [])
      setTotalLeads(res.data.total || 0)
      setTotalPages(res.data.total_pages || 1)
    } catch (err) {
      console.error('Error cargando leads:', err)
    } finally {
      setLoadingLeads(false)
    }
  }

  // Cargar historial de lotes
  const fetchLotes = async () => {
    try {
      const res = await api.get('/api/tmk/lotes')
      setLotes(res.data.lotes || [])
    } catch (err) {
      console.error('Error cargando lotes:', err)
    }
  }

  useEffect(() => {
    fetchResumen()
  }, [sedeId])

  useEffect(() => {
    fetchLeads()
  }, [criterio, sedeId, page, search])

  useEffect(() => {
    if (activeTab === 'lotes') {
      fetchLotes()
    }
  }, [activeTab])

  // Manejar selección de asesores para campaña masiva
  const toggleAsesor = (id) => {
    setSelectedAsesores(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    )
  }

  const selectAllAsesores = () => {
    if (selectedAsesores.length === asesoresList.length) {
      setSelectedAsesores([])
    } else {
      setSelectedAsesores(asesoresList.map(a => a.id))
    }
  }

  // Ejecutar Reasignación Masiva por Lote
  const handleReasignarLote = async (e) => {
    e.preventDefault()
    if (!nombreLote.trim()) {
      setErrorMsg('Ingresa un nombre para la campaña/lote.')
      return
    }
    if (selectedAsesores.length === 0) {
      setErrorMsg('Selecciona al menos un asesor o supervisor de TMK.')
      return
    }

    setSubmitting(true)
    setErrorMsg('')
    setSuccessMsg('')

    try {
      const payload = {
        nombre_lote: nombreLote,
        criterio,
        limite_leads: Number(cantidadAsignar),
        asesores_ids: selectedAsesores,
        sede_id: sedeId || null,
      }
      const res = await api.post('/api/tmk/reasignar-lote', payload)
      setSuccessMsg(res.data.message || 'Lote reasignado con éxito.')
      setTimeout(() => {
        setShowModal(false)
        setSuccessMsg('')
        setNombreLote('')
        setSelectedAsesores([])
        fetchResumen()
        fetchLeads()
      }, 1500)
    } catch (err) {
      setErrorMsg(err.response?.data?.detail || 'Error al reasignar lote.')
    } finally {
      setSubmitting(false)
    }
  }

  // Ejecutar Reasignación Individual Directa
  const handleConfirmSingleReassign = async (e) => {
    e.preventDefault()
    if (!singleReassignTarget || !singleAsesorId) return

    setIsReassigningSingle(true)
    try {
      await api.post('/api/tmk/reasignar-lead-individual', {
        lead_id: singleReassignTarget.id,
        asesor_id: singleAsesorId,
        estado_id: singleEstadoId ? Number(singleEstadoId) : null,
        criterio,
      })
      setSingleReassignTarget(null)
      setSingleAsesorId('')
      setSingleEstadoId('')
      fetchResumen()
      fetchLeads()
    } catch (err) {
      alert(err.response?.data?.detail || 'Error al reasignar el lead.')
    } finally {
      setIsReassigningSingle(false)
    }
  }

  // Ejecutar Reversión Individual a Estado Original
  const handleConfirmRevert = async () => {
    if (!revertTarget) return
    setIsReverting(true)
    try {
      await api.post('/api/tmk/revertir', { ids: [revertTarget.id] })
      setRevertTarget(null)
      fetchResumen()
      fetchLeads()
    } catch (err) {
      alert(err.response?.data?.detail || 'Error al revertir el lead.')
    } finally {
      setIsReverting(false)
    }
  }

  // Manejo de Selección de Leads
  const toggleSelectLead = (id) => {
    setSelectedLeadIds(prev =>
      prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id]
    )
  }

  const toggleSelectAllVisible = () => {
    const visibleIds = leads.map(l => l.id)
    const allSelected = visibleIds.length > 0 && visibleIds.every(id => selectedLeadIds.includes(id))
    if (allSelected) {
      setSelectedLeadIds(prev => prev.filter(id => !visibleIds.includes(id)))
    } else {
      setSelectedLeadIds(prev => Array.from(new Set([...prev, ...visibleIds])))
    }
  }

  // Ejecutar Desasignación Individual
  const handleConfirmSingleUnassign = async () => {
    if (!unassignTarget) return
    setIsUnassigning(true)
    try {
      await api.post('/api/tmk/desasignar-leads', { ids: [unassignTarget.id] })
      setUnassignTarget(null)
      fetchResumen()
      fetchLeads()
    } catch (err) {
      alert(err.response?.data?.detail || 'Error al quitar asesor al lead.')
    } finally {
      setIsUnassigning(false)
    }
  }

  // Ejecutar Desasignación Masiva
  const handleConfirmBulkUnassign = async () => {
    if (!bulkUnassignConfig) return
    setIsUnassigning(true)
    try {
      if (bulkUnassignConfig.mode === 'selected') {
        await api.post('/api/tmk/desasignar-leads', { ids: selectedLeadIds })
        setSelectedLeadIds([])
      } else {
        await api.post('/api/tmk/desasignar-leads', {
          criterio,
          sede_id: sedeId || null,
          desasignar_todos_en_filtro: true,
        })
      }
      setBulkUnassignConfig(null)
      fetchResumen()
      fetchLeads()
    } catch (err) {
      alert(err.response?.data?.detail || 'Error al quitar asesores.')
    } finally {
      setIsUnassigning(false)
    }
  }

  // Cerrar dropdown de exportación al hacer click fuera
  useEffect(() => {
    function handleClickOutside(event) {
      if (exportDropdownRef.current && !exportDropdownRef.current.contains(event.target)) {
        setExportDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  // Descarga de contactos en Excel (.xlsx)
  const handleExportExcel = async (exportCriterio = 'todos', targetIds = null) => {
    setIsExporting(true)
    setExportDropdownOpen(false)
    try {
      const params = new URLSearchParams()
      if (targetIds && targetIds.length > 0) {
        params.set('ids', targetIds.join(','))
      } else {
        params.set('criterio', exportCriterio)
        if (sedeId) params.set('sede_id', sedeId)
        if (search.trim()) params.set('search', search.trim())
      }

      const res = await api.get(`/api/tmk/exportar?${params.toString()}`, {
        responseType: 'blob',
      })

      const blob = new Blob([res.data], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      const today = new Date().toISOString().slice(0, 10)
      const suffix = targetIds ? 'seleccionados' : exportCriterio
      a.download = `contactos_bolsa_tmk_${suffix}_${today}.xlsx`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
    } catch (err) {
      console.error('Error al exportar contactos de bolsa TMK:', err)
      alert(err?.response?.data?.detail || 'Error al exportar los contactos a Excel. Intente nuevamente.')
    } finally {
      setIsExporting(false)
    }
  }

  return (
    <div className="p-6 max-w-[1600px] mx-auto space-y-6 animate-fadeIn">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 bg-white p-5 rounded-2xl shadow-sm border border-slate-100">
        <div className="flex items-center gap-3">
          <span className="p-2.5 bg-rose-50 text-rose-600 rounded-2xl">
            <RotateCcw size={26} />
          </span>
          <div>
            <h1 className="text-xl font-bold text-slate-800">Bolsa de Reciclaje y Telemarketing (TMK)</h1>
            <p className="text-xs text-slate-500">
              Concentrador de bases inactivas para reactivación y campañas masivas de televentas
            </p>
          </div>
        </div>

        {/* Pestañas y Filtros */}
        <div className="flex flex-wrap items-center gap-3">
          <div className="inline-flex bg-slate-100 p-1 rounded-xl text-xs font-semibold">
            <button
              onClick={() => setActiveTab('bolsa')}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                activeTab === 'bolsa' ? 'bg-white text-rose-600 shadow-sm' : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              Bolsa de Leads
            </button>
            <button
              onClick={() => setActiveTab('lotes')}
              className={`px-3 py-1.5 rounded-lg transition-all ${
                activeTab === 'lotes' ? 'bg-white text-rose-600 shadow-sm' : 'text-slate-600 hover:text-slate-900'
              }`}
            >
              Historial de Campañas
            </button>
          </div>

          <select
            value={sedeId}
            onChange={e => { setSedeId(e.target.value); setPage(1) }}
            className="text-xs font-medium bg-slate-50 border border-slate-200 rounded-xl px-3 py-2 text-slate-700 outline-none focus:ring-2 focus:ring-rose-500/20"
          >
            <option value="">Todas las Sedes</option>
            {sedesList.map(s => (
              <option key={s.id} value={s.id}>{s.nombre}</option>
            ))}
          </select>

          {/* Botón y Menú de Descarga Excel */}
          <div className="relative" ref={exportDropdownRef}>
            <button
              type="button"
              onClick={() => setExportDropdownOpen(prev => !prev)}
              disabled={isExporting}
              className="inline-flex items-center gap-1.5 px-3.5 py-2 bg-emerald-50 hover:bg-emerald-100 text-emerald-700 border border-emerald-200 text-xs font-bold rounded-xl transition-all shadow-xs cursor-pointer disabled:opacity-50"
              title="Descargar contactos de la bolsa en Excel (.xlsx)"
            >
              <FileSpreadsheet size={15} className={isExporting ? 'animate-bounce text-emerald-600' : 'text-emerald-600'} />
              <span>{isExporting ? 'Descargando...' : 'Descargar Excel'}</span>
              <ChevronDown size={13} className={`text-emerald-500 transition-transform ${exportDropdownOpen ? 'rotate-180' : ''}`} />
            </button>

            {exportDropdownOpen && (
              <div className="absolute right-0 mt-2 w-64 bg-white rounded-2xl shadow-xl border border-slate-100 py-2 z-50 animate-fadeIn text-xs">
                <div className="px-3.5 py-1.5 text-[10px] font-bold text-slate-400 uppercase tracking-wider">
                  Descargar Contactos (.xlsx)
                </div>
                <button
                  type="button"
                  onClick={() => handleExportExcel('todos')}
                  className="w-full text-left px-3.5 py-2.5 hover:bg-emerald-50/60 flex items-center justify-between text-slate-700 hover:text-emerald-700 transition-colors cursor-pointer"
                >
                  <div className="flex items-center gap-2">
                    <Layers size={14} className="text-emerald-600 shrink-0" />
                    <div>
                      <div className="font-bold">Toda la Bolsa</div>
                      <div className="text-[10px] text-slate-400">Todos los segmentos combinados</div>
                    </div>
                  </div>
                  <span className="font-bold text-slate-500 tabular-nums">
                    {(resumen?.total_disponible ?? 0).toLocaleString()}
                  </span>
                </button>

                <button
                  type="button"
                  onClick={() => handleExportExcel(criterio)}
                  className="w-full text-left px-3.5 py-2.5 hover:bg-emerald-50/60 flex items-center justify-between text-slate-700 hover:text-emerald-700 transition-colors cursor-pointer"
                >
                  <div className="flex items-center gap-2">
                    <Filter size={14} className="text-emerald-600 shrink-0" />
                    <div>
                      <div className="font-bold">Segmento Activo</div>
                      <div className="text-[10px] text-slate-400">
                        {CRITERIOS.find(x => x.key === criterio)?.title || 'Segmento actual'}
                      </div>
                    </div>
                  </div>
                  <span className="font-bold text-slate-500 tabular-nums">
                    {(resumen?.[criterio] ?? totalLeads ?? 0).toLocaleString()}
                  </span>
                </button>

                {selectedLeadIds.length > 0 && (
                  <button
                    type="button"
                    onClick={() => handleExportExcel(null, selectedLeadIds)}
                    className="w-full text-left px-3.5 py-2.5 hover:bg-emerald-50/60 flex items-center justify-between text-slate-700 hover:text-emerald-700 transition-colors cursor-pointer border-t border-slate-100"
                  >
                    <div className="flex items-center gap-2">
                      <CheckSquare size={14} className="text-emerald-600 shrink-0" />
                      <div>
                        <div className="font-bold">Leads Seleccionados</div>
                        <div className="text-[10px] text-slate-400">Solo los marcados en la tabla</div>
                      </div>
                    </div>
                    <span className="font-bold text-emerald-600 tabular-nums">
                      {selectedLeadIds.length}
                    </span>
                  </button>
                )}
              </div>
            )}
          </div>

          <button
            onClick={() => { fetchResumen(); fetchLeads(); }}
            className="p-2 bg-slate-50 hover:bg-slate-100 border border-slate-200 text-slate-600 rounded-xl transition-all cursor-pointer"
            title="Refrescar"
          >
            <RefreshCw size={16} className={loading || loadingLeads ? 'animate-spin text-rose-600' : ''} />
          </button>
        </div>
      </div>

      {activeTab === 'bolsa' ? (
        <>
          {/* Tarjetas de Criterios / Segmentos */}
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
            {CRITERIOS.map(c => {
              const Icon = c.icon
              const count = resumen[c.key] ?? 0
              const isSelected = criterio === c.key

              return (
                <div
                  key={c.key}
                  onClick={() => { setCriterio(c.key); setPage(1) }}
                  className={`p-5 rounded-2xl border cursor-pointer transition-all duration-200 flex flex-col justify-between ${
                    isSelected
                      ? 'bg-rose-50/50 border-rose-300 shadow-md ring-2 ring-rose-500/20'
                      : 'bg-white border-slate-100 hover:border-slate-200 hover:shadow-sm'
                  }`}
                >
                  <div className="flex items-center justify-between">
                    <span className={`p-2.5 rounded-xl ${
                      c.color === 'rose' ? 'bg-rose-100 text-rose-600' :
                      c.color === 'amber' ? 'bg-amber-100 text-amber-600' :
                      c.color === 'purple' ? 'bg-purple-100 text-purple-600' : 'bg-blue-100 text-blue-600'
                    }`}>
                      <Icon size={20} />
                    </span>
                    <span className="text-2xl font-black text-slate-800 tabular-nums">
                      {count.toLocaleString()}
                    </span>
                  </div>
                  <div className="mt-3">
                    <h3 className="text-sm font-bold text-slate-800">{c.title}</h3>
                    <p className="text-[11px] text-slate-500 mt-0.5 line-clamp-2">{c.desc}</p>
                  </div>
                </div>
              )
            })}
          </div>

          {/* Barra de Acción Masiva */}
          <div className="bg-gradient-to-r from-rose-500 to-indigo-600 p-5 rounded-2xl text-white shadow-md flex flex-col sm:flex-row items-center justify-between gap-4">
            <div>
              <h2 className="text-base font-bold flex items-center gap-2">
                <Layers size={20} />
                {totalLeads.toLocaleString()} leads disponibles en segmento "{CRITERIOS.find(x => x.key === criterio)?.title}"
              </h2>
              <p className="text-xs text-rose-100 mt-0.5">
                Reasigna a TMK o quita asesores asignados para dejarlos disponibles sin asignar.
              </p>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <button
                onClick={() => handleExportExcel(criterio)}
                disabled={isExporting || totalLeads === 0}
                className="px-4 py-2.5 bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-xs rounded-xl shadow transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 cursor-pointer border border-emerald-400/30"
                title={`Descargar ${totalLeads} contactos de este segmento en Excel (.xlsx)`}
              >
                <FileSpreadsheet size={15} />
                Exportar Excel ({totalLeads})
              </button>
              <button
                onClick={() => setBulkUnassignConfig({ mode: 'segment', count: totalLeads })}
                disabled={totalLeads === 0}
                className="px-4 py-2.5 bg-rose-700/80 hover:bg-rose-800 text-white font-bold text-xs rounded-xl shadow transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 cursor-pointer border border-rose-400/30"
                title="Quitar asesor a todos los leads con asesor en este segmento"
              >
                <UserX size={15} />
                Quitar Asesores del Segmento
              </button>
              <button
                onClick={() => {
                  setNombreLote(`Campaña TMK - ${CRITERIOS.find(x => x.key === criterio)?.title} (${new Date().toLocaleDateString()})`)
                  setCantidadAsignar(Math.min(totalLeads || 50, 50))
                  setShowModal(true)
                }}
                disabled={totalLeads === 0}
                className="px-5 py-2.5 bg-white text-rose-600 hover:bg-rose-50 font-bold text-xs rounded-xl shadow transition-all disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 cursor-pointer"
              >
                <Send size={16} />
                Reasignar Lote a TMK
              </button>
            </div>
          </div>

          {/* Barra Flotante de Selección Múltiple */}
          {selectedLeadIds.length > 0 && (
            <div className="bg-slate-900 text-white p-3.5 rounded-2xl shadow-xl flex flex-wrap items-center justify-between gap-3 animate-fadeIn border border-slate-700">
              <div className="flex items-center gap-2.5">
                <span className="p-1.5 bg-rose-500/20 text-rose-400 rounded-lg">
                  <CheckSquare size={16} />
                </span>
                <span className="text-xs font-bold text-slate-100">
                  {selectedLeadIds.length} lead{selectedLeadIds.length !== 1 ? 's' : ''} seleccionado{selectedLeadIds.length !== 1 ? 's' : ''}
                </span>
              </div>
              <div className="flex items-center gap-2 flex-wrap">
                <button
                  onClick={() => handleExportExcel(null, selectedLeadIds)}
                  disabled={isExporting}
                  className="px-3.5 py-1.5 bg-emerald-600 hover:bg-emerald-700 text-white font-bold text-xs rounded-xl transition-all flex items-center gap-1.5 cursor-pointer shadow-xs disabled:opacity-50"
                  title="Descargar solo los leads seleccionados en Excel"
                >
                  <FileSpreadsheet size={14} />
                  Exportar Excel ({selectedLeadIds.length})
                </button>
                <button
                  onClick={() => setBulkUnassignConfig({ mode: 'selected', count: selectedLeadIds.length })}
                  className="px-3.5 py-1.5 bg-rose-600 hover:bg-rose-700 text-white font-bold text-xs rounded-xl transition-all flex items-center gap-1.5 cursor-pointer shadow-xs"
                  title="Quitar asesor a los leads seleccionados"
                >
                  <UserX size={14} />
                  Quitar Asesor ({selectedLeadIds.length})
                </button>
                <button
                  onClick={() => {
                    setNombreLote(`Campaña TMK - Seleccionados (${new Date().toLocaleDateString()})`)
                    setCantidadAsignar(selectedLeadIds.length)
                    setShowModal(true)
                  }}
                  className="px-3.5 py-1.5 bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-xs rounded-xl transition-all flex items-center gap-1.5 cursor-pointer shadow-xs"
                  title="Crear lote con los leads seleccionados"
                >
                  <Send size={14} />
                  Reasignar Seleccionados
                </button>
                <button
                  onClick={() => setSelectedLeadIds([])}
                  className="p-1.5 text-slate-400 hover:text-white rounded-lg transition-colors cursor-pointer"
                  title="Limpiar selección"
                >
                  <X size={16} />
                </button>
              </div>
            </div>
          )}

          {/* Tabla de Leads del Segmento */}
          <div className="bg-white rounded-2xl border border-slate-100 shadow-sm overflow-hidden space-y-0">
            {/* Cabecera de la tabla con Buscador y Paginación Superior */}
            <div className="p-4 border-b border-slate-100 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              {/* Buscador en vivo */}
              <div className="relative flex-1 max-w-md">
                <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
                <input
                  type="text"
                  placeholder="Buscar por lead, teléfono, email, ID o último asesor..."
                  value={searchInput}
                  onChange={e => handleSearchChange(e.target.value)}
                  className="w-full pl-9 pr-8 py-2 text-xs bg-slate-50 border border-slate-200 rounded-xl text-slate-800 placeholder-slate-400 outline-none focus:ring-2 focus:ring-rose-500/20 focus:border-rose-400"
                />
                {searchInput && (
                  <button
                    onClick={() => { setSearchInput(''); setSearch(''); setPage(1) }}
                    className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600 p-0.5 cursor-pointer"
                  >
                    <X size={13} />
                  </button>
                )}
              </div>

              {/* Indicador y Controles de Paginación */}
              <div className="flex items-center gap-3">
                <span className="text-xs text-slate-500 whitespace-nowrap">
                  {totalLeads > 0 ? (
                    <>
                      Mostrando <strong className="text-slate-800">{(page - 1) * PAGE_SIZE + 1}–{Math.min(page * PAGE_SIZE, totalLeads)}</strong> de <strong className="text-slate-800">{totalLeads.toLocaleString()}</strong>
                    </>
                  ) : (
                    '0 leads'
                  )}
                </span>

                <div className="inline-flex items-center gap-1">
                  <button
                    onClick={() => setPage(p => Math.max(p - 1, 1))}
                    disabled={page <= 1 || loadingLeads}
                    className="w-8 h-8 inline-flex items-center justify-center rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-30 disabled:cursor-not-allowed transition-colors cursor-pointer"
                    title="Página anterior"
                  >
                    <ChevronLeft size={16} />
                  </button>
                  <span className="text-xs font-bold text-slate-700 px-2 select-none">
                    Pág. {page} / {totalPages}
                  </span>
                  <button
                    onClick={() => setPage(p => Math.min(p + 1, totalPages))}
                    disabled={page >= totalPages || loadingLeads}
                    className="w-8 h-8 inline-flex items-center justify-center rounded-lg border border-slate-200 text-slate-600 hover:bg-slate-50 disabled:opacity-30 disabled:cursor-not-allowed transition-colors cursor-pointer"
                    title="Página siguiente"
                  >
                    <ChevronRight size={16} />
                  </button>
                </div>
              </div>
            </div>

            {/* Tabla */}
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="bg-slate-50 text-slate-600 font-semibold border-b border-slate-100">
                  <tr>
                    <th className="py-3.5 px-3 w-10 text-center">
                      <button
                        type="button"
                        onClick={toggleSelectAllVisible}
                        className="text-slate-400 hover:text-slate-700 p-0.5 cursor-pointer inline-flex items-center justify-center"
                        title={leads.length > 0 && leads.every(l => selectedLeadIds.includes(l.id)) ? "Deseleccionar todos" : "Seleccionar visibles"}
                      >
                        {leads.length > 0 && leads.every(l => selectedLeadIds.includes(l.id)) ? (
                          <CheckSquare size={16} className="text-rose-600" />
                        ) : (
                          <Square size={16} className="text-slate-400" />
                        )}
                      </button>
                    </th>
                    <th className="py-3.5 px-4 min-w-[180px]">Lead / Contacto</th>
                    <th className="py-3.5 px-3 min-w-[140px]">Teléfono / Email</th>
                    <th className="py-3.5 px-3 min-w-[110px]">Estado Actual</th>
                    <th className="py-3.5 px-3 min-w-[125px]">Asesor Actual</th>
                    <th className="py-3.5 px-3 min-w-[160px]">Último Asesor (Previo)</th>
                    <th className="py-3.5 px-3 min-w-[110px]">Sede</th>
                    <th className="py-3.5 px-3 min-w-[170px]">Historial de Asignación</th>
                    <th className="py-3.5 px-3 min-w-[95px]">Ingreso</th>
                    <th className="py-3.5 px-4 text-center min-w-[130px]">Acciones</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 text-slate-700 font-medium">
                  {loadingLeads ? (
                    <tr>
                      <td colSpan={10} className="py-16 text-center text-slate-400">
                        <RefreshCw size={24} className="animate-spin text-rose-500 mx-auto mb-2" />
                        Cargando leads de la bolsa...
                      </td>
                    </tr>
                  ) : leads.map(l => {
                    const hist = l.historial_asignaciones || []
                    const isSelected = selectedLeadIds.includes(l.id)
                    return (
                      <tr key={l.id} className={`hover:bg-slate-50/70 transition-colors group ${isSelected ? 'bg-rose-50/30' : ''}`}>
                        {/* Checkbox de fila */}
                        <td className="py-3 px-3 text-center">
                          <button
                            type="button"
                            onClick={() => toggleSelectLead(l.id)}
                            className="text-slate-400 hover:text-slate-700 p-0.5 cursor-pointer inline-flex items-center justify-center"
                          >
                            {isSelected ? (
                              <CheckSquare size={16} className="text-rose-600" />
                            ) : (
                              <Square size={16} className="text-slate-300 group-hover:text-slate-400" />
                            )}
                          </button>
                        </td>

                        {/* Lead */}
                        <td className="py-3 px-4">
                          <div className="font-bold text-slate-900">{l.nombre_completo || 'Sin nombre'}</div>
                          <div className="text-[10px] text-slate-400">ID #{l.id} {l.campana ? `· ${l.campana}` : ''}</div>
                        </td>

                        {/* Teléfono / Email */}
                        <td className="py-3 px-3">
                          <div className="font-mono text-slate-800 flex items-center gap-1">
                            <Phone size={11} className="text-slate-400 shrink-0" />
                            {l.telefono || '—'}
                          </div>
                          {l.email && (
                            <div className="text-[10px] text-slate-400 flex items-center gap-1 truncate max-w-[160px]" title={l.email}>
                              <Mail size={10} className="text-slate-400 shrink-0" />
                              {l.email}
                            </div>
                          )}
                        </td>

                        {/* Estado */}
                        <td className="py-3 px-3">
                          <span
                            className="px-2.5 py-0.5 rounded-full font-semibold text-[10px] border inline-block"
                            style={{
                              backgroundColor: (l.estado_color || '#64748b') + '15',
                              borderColor: (l.estado_color || '#64748b') + '40',
                              color: l.estado_color || '#334155',
                            }}
                          >
                            {l.estado_nombre || 'Nuevo'}
                          </span>
                        </td>

                        {/* Asesor actual */}
                        <td className="py-3 px-3 text-slate-700">
                          {l.asesor_actual ? (
                            <div className="flex items-center gap-1 font-semibold text-slate-800">
                              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 shrink-0" />
                              <span className="truncate max-w-[120px]" title={l.asesor_actual}>{l.asesor_actual}</span>
                            </div>
                          ) : (
                            <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[10px] font-medium bg-slate-100 text-slate-500 border border-slate-200/60">
                              Sin asesor
                            </span>
                          )}
                        </td>

                        {/* Último Asesor Previo (antes de quedar sin asesor) */}
                        <td className="py-3 px-3 text-slate-700">
                          {l.previous_asesor_nombre ? (
                            <div className="flex flex-col">
                              <div className="flex items-center gap-1 font-semibold text-slate-800">
                                <UserCheck size={12} className="text-indigo-600 shrink-0" />
                                <span
                                  className="truncate max-w-[150px]"
                                  title={`Último asesor antes de quedar sin asignar: ${l.previous_asesor_nombre}${l.previous_asesor_email ? ` (${l.previous_asesor_email})` : ''}`}
                                >
                                  {l.previous_asesor_nombre}
                                </span>
                              </div>
                              {l.previous_asesor_email && (
                                <span className="text-[10px] text-slate-400 truncate max-w-[150px] pl-4" title={l.previous_asesor_email}>
                                  {l.previous_asesor_email}
                                </span>
                              )}
                            </div>
                          ) : (
                            <span className="text-slate-400 italic text-[11px]">Sin asesor previo</span>
                          )}
                        </td>

                        {/* Sede */}
                        <td className="py-3 px-3 text-slate-600">
                          {l.sede_nombre || '—'}
                        </td>

                        {/* Columna: Historial de Asignaciones */}
                        <td className="py-3 px-3">
                          {hist.length > 0 ? (
                            <button
                              onClick={() => setHistoryTarget(l)}
                              className="inline-flex items-center gap-1.5 px-2 py-1 rounded-lg text-[11px] font-semibold bg-indigo-50 text-indigo-700 hover:bg-indigo-100 border border-indigo-200/80 transition-colors cursor-pointer"
                              title="Ver historial completo de cambios de asesor"
                            >
                              <History size={12} className="text-indigo-600 shrink-0" />
                              <span>{hist.length} cambio{hist.length !== 1 ? 's' : ''}</span>
                              <span className="text-[10px] opacity-75 font-normal truncate max-w-[100px]">
                                ({hist[0]?.asesor_nuevo_nombre || 'Sin asesor'})
                              </span>
                            </button>
                          ) : (
                            <span className="text-slate-300 text-xs italic">Sin historial</span>
                          )}
                        </td>

                        {/* Ingreso */}
                        <td className="py-3 px-3 text-slate-500 whitespace-nowrap">
                          {new Date(l.fecha_ingreso).toLocaleDateString()}
                        </td>

                        {/* Botones de Acción Directa por Fila */}
                        <td className="py-3 px-4 text-center">
                          <div className="inline-flex items-center justify-center gap-1.5">
                            {/* 1. Reasignar directo a un asesor */}
                            <button
                              onClick={() => {
                                setSingleReassignTarget(l)
                                setSingleAsesorId(asesoresList[0]?.id || '')
                                setSingleEstadoId(estadosList.find(e => e.nombre.toLowerCase().includes('nuevo'))?.id || '')
                              }}
                              className="p-1.5 text-slate-500 hover:text-indigo-600 hover:bg-indigo-50 rounded-lg transition-colors border border-transparent hover:border-indigo-200 cursor-pointer"
                              title="Reasignar directamente a un asesor de TMK"
                            >
                              <UserPlus size={14} />
                            </button>

                            {/* 2. Quitar Asesor Asignado (Volver Sin Asesor) */}
                            <button
                              onClick={() => setUnassignTarget(l)}
                              disabled={!l.asesor_actual_id}
                              className={`p-1.5 rounded-lg transition-colors border border-transparent cursor-pointer ${
                                l.asesor_actual_id
                                  ? 'text-slate-500 hover:text-rose-600 hover:bg-rose-50 hover:border-rose-200'
                                  : 'text-slate-300 opacity-40 cursor-not-allowed'
                              }`}
                              title={l.asesor_actual_id ? `Quitar asesor asignado (${l.asesor_actual}) y dejar como Sin Asesor` : 'Este lead ya está sin asesor asignado'}
                            >
                              <UserX size={14} />
                            </button>

                            {/* 3. Dejar el lead como estaba originalmente (Revertir) */}
                            <button
                              onClick={() => setRevertTarget(l)}
                              className="p-1.5 text-slate-500 hover:text-amber-600 hover:bg-amber-50 rounded-lg transition-colors border border-transparent hover:border-amber-200 cursor-pointer"
                              title="Dejar el lead como estaba originalmente (devolver asignación y estado previo)"
                            >
                              <RotateCcw size={14} />
                            </button>

                            {/* 4. Ver detalle del lead en /leads */}
                            <button
                              onClick={() => navigate(`/leads/${l.id}`)}
                              className="p-1.5 text-slate-500 hover:text-slate-800 hover:bg-slate-100 rounded-lg transition-colors border border-transparent hover:border-slate-200 cursor-pointer"
                              title="Ver ficha completa del lead"
                            >
                              <ExternalLink size={14} />
                            </button>
                          </div>
                        </td>
                      </tr>
                    )
                  })}
                  {!loadingLeads && leads.length === 0 && (
                    <tr>
                      <td colSpan={10} className="py-12 text-center text-slate-400">
                        {search ? 'Sin resultados para la búsqueda aplicada.' : 'No hay leads disponibles en este segmento para la sede seleccionada.'}
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>

            {/* Paginación Inferior */}
            {totalPages > 1 && (
              <div className="p-4 border-t border-slate-100 flex items-center justify-between bg-slate-50/50">
                <span className="text-xs text-slate-500">
                  Página <strong className="text-slate-800">{page}</strong> de <strong className="text-slate-800">{totalPages}</strong> ({totalLeads.toLocaleString()} leads totales)
                </span>
                <div className="inline-flex items-center gap-1.5">
                  <button
                    onClick={() => setPage(p => Math.max(p - 1, 1))}
                    disabled={page <= 1 || loadingLeads}
                    className="px-3 py-1.5 rounded-lg border border-slate-200 bg-white text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
                  >
                    Anterior
                  </button>
                  <button
                    onClick={() => setPage(p => Math.min(p + 1, totalPages))}
                    disabled={page >= totalPages || loadingLeads}
                    className="px-3 py-1.5 rounded-lg border border-slate-200 bg-white text-xs font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-40 disabled:cursor-not-allowed transition-colors cursor-pointer"
                  >
                    Siguiente
                  </button>
                </div>
              </div>
            )}
          </div>
        </>
      ) : (
        /* Pestaña: Historial de Campañas/Lotes */
        <div className="bg-white rounded-2xl border border-slate-100 shadow-sm overflow-hidden">
          <div className="p-5 border-b border-slate-100">
            <h2 className="text-sm font-bold text-slate-800">Historial de Campañas de Reciclaje TMK</h2>
            <p className="text-xs text-slate-500">Registro histórico de lotes creados y distribuidos</p>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 text-slate-500 font-semibold border-b border-slate-100">
                <tr>
                  <th className="py-3 px-4">Campaña / Lote</th>
                  <th className="py-3 px-3">Criterio</th>
                  <th className="py-3 px-3 text-center">Total Leads</th>
                  <th className="py-3 px-3">Asesores Involucrados</th>
                  <th className="py-3 px-3">Creado Por</th>
                  <th className="py-3 px-3">Fecha</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 text-slate-700 font-medium">
                {lotes.map(lt => (
                  <tr key={lt.id} className="hover:bg-slate-50/70 transition-colors">
                    <td className="py-3 px-4">
                      <div className="font-bold text-slate-800">{lt.nombre}</div>
                      <div className="text-[10px] text-slate-400">{lt.descripcion}</div>
                    </td>
                    <td className="py-3 px-3">
                      <span className="px-2 py-0.5 bg-rose-50 text-rose-600 font-semibold rounded-full text-[10px]">
                        {lt.criterio}
                      </span>
                    </td>
                    <td className="py-3 px-3 text-center font-bold text-slate-800">
                      {lt.total_leads}
                    </td>
                    <td className="py-3 px-3 text-slate-600">
                      {Array.isArray(lt.asesores_asignados) ? `${lt.asesores_asignados.length} usuario(s)` : '—'}
                    </td>
                    <td className="py-3 px-3 text-slate-600">
                      {lt.creado_por_nombre || 'Sistema'}
                    </td>
                    <td className="py-3 px-3 text-slate-500">
                      {new Date(lt.created_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
                {lotes.length === 0 && (
                  <tr>
                    <td colSpan={6} className="py-12 text-center text-slate-400">
                      No se han creado lotes de reciclaje todavía.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Modal: Reasignación Masiva por Lote */}
      {showModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-xs p-4 animate-fadeIn">
          <div className="bg-white w-full max-w-lg rounded-2xl shadow-xl border border-slate-100 overflow-hidden">
            <div className="p-5 border-b border-slate-100 flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-800 flex items-center gap-2">
                <RotateCcw size={18} className="text-rose-500" />
                Lanzar Campaña de Reciclaje TMK
              </h3>
              <button
                onClick={() => setShowModal(false)}
                className="text-slate-400 hover:text-slate-600 p-1 cursor-pointer"
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleReasignarLote} className="p-5 space-y-4">
              {errorMsg && (
                <div className="p-3 bg-rose-50 text-rose-700 text-xs rounded-xl border border-rose-200">
                  {errorMsg}
                </div>
              )}
              {successMsg && (
                <div className="p-3 bg-emerald-50 text-emerald-700 text-xs rounded-xl border border-emerald-200 flex items-center gap-2">
                  <CheckCircle2 size={16} />
                  {successMsg}
                </div>
              )}

              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">
                  Nombre de la Campaña / Lote
                </label>
                <input
                  type="text"
                  value={nombreLote}
                  onChange={e => setNombreLote(e.target.value)}
                  className="w-full text-xs bg-slate-50 border border-slate-200 rounded-xl px-3 py-2.5 text-slate-800 outline-none focus:ring-2 focus:ring-rose-500/20"
                  required
                />
              </div>

              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1">
                  Cantidad de Leads a Reciclar (Máx. {totalLeads})
                </label>
                <input
                  type="number"
                  min="1"
                  max={totalLeads || 1}
                  value={cantidadAsignar}
                  onChange={e => setCantidadAsignar(e.target.value)}
                  className="w-full text-xs bg-slate-50 border border-slate-200 rounded-xl px-3 py-2.5 text-slate-800 outline-none focus:ring-2 focus:ring-rose-500/20 font-bold"
                  required
                />
              </div>

              {/* Selector de Asesores y Supervisores TMK */}
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="text-xs font-semibold text-slate-700">
                    Destinatarios TMK (Asesores y Supervisores) ({selectedAsesores.length} seleccionados)
                  </label>
                  <button
                    type="button"
                    onClick={selectAllAsesores}
                    className="text-[11px] font-bold text-indigo-600 hover:underline cursor-pointer"
                  >
                    {selectedAsesores.length === asesoresList.length ? 'Deseleccionar todos' : 'Seleccionar todos'}
                  </button>
                </div>

                <div className="max-h-48 overflow-y-auto border border-slate-200 rounded-xl p-2 space-y-1 bg-slate-50">
                  {asesoresList.map(a => {
                    const isChecked = selectedAsesores.includes(a.id)
                    const isSupervisor = a.role === 'supervisor'
                    return (
                      <div
                        key={a.id}
                        onClick={() => toggleAsesor(a.id)}
                        className={`flex items-center gap-2 p-2 rounded-lg text-xs cursor-pointer transition-colors ${
                          isChecked ? 'bg-white shadow-xs font-semibold text-indigo-700' : 'text-slate-600 hover:bg-white/50'
                        }`}
                      >
                        {isChecked ? (
                          <CheckSquare size={16} className="text-indigo-600 shrink-0" />
                        ) : (
                          <Square size={16} className="text-slate-400 shrink-0" />
                        )}
                        <span className="truncate">{a.first_name} {a.last_name}</span>
                        <span className={`text-[10px] px-1.5 py-0.5 rounded-md font-semibold ${
                          isSupervisor ? 'bg-purple-100 text-purple-700 border border-purple-200' : 'bg-slate-100 text-slate-600'
                        }`}>
                          {isSupervisor ? 'Supervisor' : 'Asesor'}
                        </span>
                        <span className="text-[10px] text-slate-400 ml-auto hidden sm:inline truncate">{a.email}</span>
                      </div>
                    )
                  })}
                </div>
              </div>

              {selectedAsesores.length > 0 && cantidadAsignar > 0 && (
                <div className="p-3 bg-indigo-50 text-indigo-700 text-[11px] rounded-xl font-medium">
                  Reparto Equitativo: Aproximadamente <strong>{Math.ceil(cantidadAsignar / selectedAsesores.length)}</strong> leads por destinatario.
                </div>
              )}

              <div className="pt-2 flex items-center justify-end gap-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setShowModal(false)}
                  disabled={submitting}
                  className="px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-xl transition-all cursor-pointer"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={submitting || selectedAsesores.length === 0}
                  className="px-5 py-2 text-xs font-bold bg-rose-600 hover:bg-rose-700 text-white rounded-xl shadow transition-all disabled:opacity-50 flex items-center gap-1.5 cursor-pointer"
                >
                  {submitting ? 'Procesando...' : 'Confirmar y Reasignar'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Reasignar Lead Individual Directo */}
      {singleReassignTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-xs p-4 animate-fadeIn">
          <div className="bg-white w-full max-w-md rounded-2xl shadow-xl border border-slate-100 overflow-hidden">
            <div className="p-5 border-b border-slate-100 flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-800 flex items-center gap-2">
                <UserPlus size={18} className="text-indigo-600" />
                Reasignar Lead Directamente
              </h3>
              <button
                onClick={() => setSingleReassignTarget(null)}
                className="text-slate-400 hover:text-slate-600 p-1 cursor-pointer"
              >
                <X size={18} />
              </button>
            </div>

            <form onSubmit={handleConfirmSingleReassign} className="p-5 space-y-4">
              {/* Información del Lead */}
              <div className="p-3 bg-slate-50 rounded-xl border border-slate-100 text-xs space-y-1">
                <div className="font-bold text-slate-800">{singleReassignTarget.nombre_completo || 'Sin nombre'}</div>
                <div className="text-slate-500 font-mono">Tel: {singleReassignTarget.telefono || '—'} · ID #{singleReassignTarget.id}</div>
                <div className="text-slate-400">Último Asesor: <span className="font-semibold text-slate-600">{singleReassignTarget.asesor_actual || 'Sin asignar'}</span></div>
              </div>

              {/* Selector de Asesor Destino */}
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1.5">
                  Asignar a Asesor / Supervisor
                </label>
                <select
                  value={singleAsesorId}
                  onChange={e => setSingleAsesorId(e.target.value)}
                  className="w-full text-xs bg-slate-50 border border-slate-200 rounded-xl px-3 py-2.5 text-slate-800 outline-none focus:ring-2 focus:ring-indigo-500/20"
                  required
                >
                  <option value="">Selecciona destinatario…</option>
                  {asesoresList.map(a => (
                    <option key={a.id} value={a.id}>
                      {a.first_name} {a.last_name} ({a.role === 'supervisor' ? 'Supervisor' : 'Asesor'})
                    </option>
                  ))}
                </select>
              </div>

              {/* Selector de Estado Destino */}
              <div>
                <label className="text-xs font-semibold text-slate-700 block mb-1.5">
                  Estado al Reasignar
                </label>
                <select
                  value={singleEstadoId}
                  onChange={e => setSingleEstadoId(e.target.value)}
                  className="w-full text-xs bg-slate-50 border border-slate-200 rounded-xl px-3 py-2.5 text-slate-800 outline-none focus:ring-2 focus:ring-indigo-500/20"
                >
                  <option value="">Mantener estado actual ({singleReassignTarget.estado_nombre || 'Nuevo'})</option>
                  {estadosList.map(e => (
                    <option key={e.id} value={e.id}>{e.nombre}</option>
                  ))}
                </select>
              </div>

              <div className="pt-2 flex items-center justify-end gap-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setSingleReassignTarget(null)}
                  disabled={isReassigningSingle}
                  className="px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-xl transition-all cursor-pointer"
                >
                  Cancelar
                </button>
                <button
                  type="submit"
                  disabled={isReassigningSingle || !singleAsesorId}
                  className="px-5 py-2 text-xs font-bold bg-indigo-600 hover:bg-indigo-700 text-white rounded-xl shadow transition-all disabled:opacity-50 flex items-center gap-1.5 cursor-pointer"
                >
                  {isReassigningSingle ? 'Reasignando...' : 'Reasignar Lead'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal: Confirmación para Dejar Lead como Estaba Originalmente (Revertir) */}
      {revertTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-xs p-4 animate-fadeIn">
          <div className="bg-white w-full max-w-md rounded-2xl shadow-xl border border-slate-100 overflow-hidden">
            <div className="p-5 border-b border-slate-100 flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-800 flex items-center gap-2">
                <RotateCcw size={18} className="text-rose-500" />
                Devolver a Asignación Original
              </h3>
              <button
                onClick={() => setRevertTarget(null)}
                className="text-slate-400 hover:text-slate-600 p-1 cursor-pointer"
              >
                <X size={18} />
              </button>
            </div>

            <div className="p-5 space-y-4">
              <p className="text-xs text-slate-600 leading-relaxed">
                ¿Estás seguro de que deseas devolver el <strong>Lead #{revertTarget.id} ({revertTarget.nombre_completo || 'Sin nombre'})</strong> a su asignación y estado original previos a la Bolsa TMK?
              </p>

              <div className="p-3 bg-rose-50 border border-rose-100 rounded-xl text-[11px] text-rose-800 space-y-1">
                <div>• Se removerá el flag de lead reciclado.</div>
                <div>• Se restaurará el asesor anterior registrado ({revertTarget.previous_asesor_nombre || 'Sin asesor previo'}).</div>
                <div>• Quedará auditado en el historial de asignaciones y contactos.</div>
              </div>

              <div className="pt-2 flex items-center justify-end gap-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setRevertTarget(null)}
                  disabled={isReverting}
                  className="px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-xl transition-all cursor-pointer"
                >
                  Cancelar
                </button>
                <button
                  type="button"
                  onClick={handleConfirmRevert}
                  disabled={isReverting}
                  className="px-5 py-2 text-xs font-bold bg-rose-600 hover:bg-rose-700 text-white rounded-xl shadow transition-all disabled:opacity-50 flex items-center gap-1.5 cursor-pointer"
                >
                  {isReverting ? 'Restaurando...' : 'Sí, Devolver como Estaba'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Historial Completo de Asignaciones (Timeline) */}
      {historyTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-xs p-4 animate-fadeIn">
          <div className="bg-white w-full max-w-lg rounded-2xl shadow-xl border border-slate-100 overflow-hidden flex flex-col max-h-[85vh]">
            <div className="p-5 border-b border-slate-100 flex items-center justify-between shrink-0">
              <div className="flex items-center gap-2.5">
                <span className="p-2 bg-indigo-50 text-indigo-600 rounded-xl">
                  <History size={18} />
                </span>
                <div>
                  <h3 className="text-sm font-bold text-slate-800">
                    Historial de Asignaciones
                  </h3>
                  <p className="text-[11px] text-slate-500">
                    Lead #{historyTarget.id} · {historyTarget.nombre_completo || 'Sin nombre'}
                  </p>
                </div>
              </div>
              <button
                onClick={() => setHistoryTarget(null)}
                className="text-slate-400 hover:text-slate-600 p-1 cursor-pointer"
              >
                <X size={18} />
              </button>
            </div>

            <div className="p-5 overflow-y-auto space-y-4">
              {(historyTarget.historial_asignaciones || []).length === 0 ? (
                <div className="text-center py-8 text-slate-400 text-xs">
                  No hay movimientos de asignación registrados para este lead.
                </div>
              ) : (
                <div className="relative pl-6 space-y-6 before:absolute before:left-2 before:top-2 before:bottom-2 before:w-0.5 before:bg-slate-200">
                  {historyTarget.historial_asignaciones.map((h, idx) => (
                    <div key={h.id || idx} className="relative group">
                      {/* Dot */}
                      <div className="absolute -left-6 top-1 w-2.5 h-2.5 rounded-full bg-indigo-500 border-2 border-white shadow-xs" />

                      <div className="bg-slate-50 p-3 rounded-xl border border-slate-100 text-xs space-y-1.5">
                        <div className="flex items-center justify-between text-[11px] text-slate-500 font-medium">
                          <span>{new Date(h.created_at).toLocaleString()}</span>
                          <span className="px-2 py-0.5 rounded-full bg-slate-200/70 text-slate-700 font-semibold text-[10px]">
                            {h.motivo || 'Reasignación'}
                          </span>
                        </div>

                        {/* De -> A */}
                        <div className="flex items-center gap-2 text-slate-800 font-semibold pt-0.5">
                          <span className="text-slate-500">{h.asesor_anterior_nombre || 'Sin asesor previo'}</span>
                          <ArrowRight size={13} className="text-slate-400 shrink-0" />
                          <span className="text-indigo-600 font-bold">{h.asesor_nuevo_nombre || 'Sin asesor nuevo'}</span>
                        </div>

                        {h.asignado_por_nombre && (
                          <div className="text-[10px] text-slate-400 pt-0.5 border-t border-slate-200/60 flex items-center gap-1">
                            <span>Asignado por:</span>
                            <span className="font-semibold text-slate-600">{h.asignado_por_nombre}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="p-4 bg-slate-50 border-t border-slate-100 flex justify-end shrink-0">
              <button
                onClick={() => setHistoryTarget(null)}
                className="px-4 py-2 text-xs font-semibold bg-white border border-slate-200 hover:bg-slate-100 rounded-xl text-slate-700 transition-colors cursor-pointer"
              >
                Cerrar
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Confirmación para Quitar Asesor Asignado Individual */}
      {unassignTarget && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-xs p-4 animate-fadeIn">
          <div className="bg-white w-full max-w-md rounded-2xl shadow-xl border border-slate-100 overflow-hidden">
            <div className="p-5 border-b border-slate-100 flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-800 flex items-center gap-2">
                <UserX size={18} className="text-rose-600" />
                Quitar Asesor Asignado
              </h3>
              <button
                onClick={() => setUnassignTarget(null)}
                className="text-slate-400 hover:text-slate-600 p-1 cursor-pointer"
              >
                <X size={18} />
              </button>
            </div>

            <div className="p-5 space-y-4">
              <p className="text-xs text-slate-600 leading-relaxed">
                ¿Estás seguro de que deseas quitar el asesor asignado a <strong>Lead #{unassignTarget.id} ({unassignTarget.nombre_completo || 'Sin nombre'})</strong>?
              </p>

              <div className="p-3 bg-amber-50 border border-amber-200 rounded-xl text-[11px] text-amber-900 space-y-1">
                <div>• El lead quedará en estado <strong>Sin asesor</strong> en la Bolsa TMK.</div>
                <div>• Asesor actual a remover: <strong>{unassignTarget.asesor_actual || 'Sin asesor'}</strong>.</div>
                <div>• Se registrará el movimiento en el historial de asignaciones y contactos.</div>
              </div>

              <div className="pt-2 flex items-center justify-end gap-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setUnassignTarget(null)}
                  disabled={isUnassigning}
                  className="px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-xl transition-all cursor-pointer"
                >
                  Cancelar
                </button>
                <button
                  type="button"
                  onClick={handleConfirmSingleUnassign}
                  disabled={isUnassigning}
                  className="px-5 py-2 text-xs font-bold bg-rose-600 hover:bg-rose-700 text-white rounded-xl shadow transition-all disabled:opacity-50 flex items-center gap-1.5 cursor-pointer"
                >
                  {isUnassigning ? 'Procesando...' : 'Sí, Quitar Asesor'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Modal: Confirmación para Quitar Asesores Masivo / Segmento */}
      {bulkUnassignConfig && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 backdrop-blur-xs p-4 animate-fadeIn">
          <div className="bg-white w-full max-w-md rounded-2xl shadow-xl border border-slate-100 overflow-hidden">
            <div className="p-5 border-b border-slate-100 flex items-center justify-between">
              <h3 className="text-sm font-bold text-slate-800 flex items-center gap-2">
                <UserX size={18} className="text-rose-600" />
                Quitar Asesores ({bulkUnassignConfig.mode === 'selected' ? `${bulkUnassignConfig.count} Seleccionados` : 'Todo el Segmento'})
              </h3>
              <button
                onClick={() => setBulkUnassignConfig(null)}
                className="text-slate-400 hover:text-slate-600 p-1 cursor-pointer"
              >
                <X size={18} />
              </button>
            </div>

            <div className="p-5 space-y-4">
              <p className="text-xs text-slate-600 leading-relaxed">
                {bulkUnassignConfig.mode === 'selected' ? (
                  <>¿Estás seguro de que deseas quitar el asesor asignado a los <strong>{bulkUnassignConfig.count} leads seleccionados</strong>?</>
                ) : (
                  <>¿Estás seguro de que deseas quitar el asesor asignado a <strong>todos los leads con asesor</strong> en el segmento <strong>"{CRITERIOS.find(x => x.key === criterio)?.title}"</strong>{sedeId ? ' para la sede seleccionada' : ''}?</>
                )}
              </p>

              <div className="p-3 bg-amber-50 border border-amber-200 rounded-xl text-[11px] text-amber-900 space-y-1">
                <div>• Los leads quedarán como <strong>Sin Asesor</strong> listos para ser reasignados.</div>
                <div>• Quedará auditado en el historial de asignaciones de cada lead.</div>
              </div>

              <div className="pt-2 flex items-center justify-end gap-2 border-t border-slate-100">
                <button
                  type="button"
                  onClick={() => setBulkUnassignConfig(null)}
                  disabled={isUnassigning}
                  className="px-4 py-2 text-xs font-semibold text-slate-600 hover:bg-slate-100 rounded-xl transition-all cursor-pointer"
                >
                  Cancelar
                </button>
                <button
                  type="button"
                  onClick={handleConfirmBulkUnassign}
                  disabled={isUnassigning}
                  className="px-5 py-2 text-xs font-bold bg-rose-600 hover:bg-rose-700 text-white rounded-xl shadow transition-all disabled:opacity-50 flex items-center gap-1.5 cursor-pointer"
                >
                  {isUnassigning ? 'Desasignando...' : 'Confirmar y Quitar Asesores'}
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
