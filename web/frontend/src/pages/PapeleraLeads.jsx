import React, { useState, useEffect, useCallback, useMemo, useRef } from 'react'
import {
  Trash2, RotateCcw, Search, Filter, AlertTriangle, CheckCircle2,
  XCircle, ChevronLeft, ChevronRight, ChevronDown, Check, X,
  Layers, RefreshCw, UserCheck, ShieldAlert, Sparkles, Phone, Mail,
  Calendar, ArrowUpDown, UserX
} from 'lucide-react'
import api from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import ConfirmDialog from '@/components/shared/ConfirmDialog'
import InfoDialog from '@/components/shared/InfoDialog'
import LoadingSpinner from '@/components/shared/LoadingSpinner'
import EmptyState from '@/components/shared/EmptyState'
import { useUndoToast } from '@/components/shared/UndoToast'
import useCrmStore from '@/store/crmStore'
import { cn } from '@/lib/utils'
import { EstadoSubinfo } from '@/pages/Leads'
import { getSubestadosForEstado } from '@/components/leads/CambioEstadoModal'

const PAGE_SIZE = 50

function formatDate(iso) {
  if (!iso) return '—'
  const d = new Date(iso)
  const dd = String(d.getDate()).padStart(2, '0')
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const yy = String(d.getFullYear()).slice(-2)
  const hh = String(d.getHours()).padStart(2, '0')
  const mi = String(d.getMinutes()).padStart(2, '0')
  return `${dd}/${mm}/${yy} ${hh}:${mi}`
}

export default function PapeleraLeads() {
  const { showUndoToast } = useUndoToast() || { showUndoToast: () => { } }
  const { estados, loadCatalogs } = useCrmStore()

  const [leads, setLeads] = useState([])
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState({ total: 0, total_recientes: 0, por_estado: [] })
  const [loading, setLoading] = useState(true)
  const [loadingStats, setLoadingStats] = useState(false)
  const [page, setPage] = useState(1)

  // Filtros
  const [search, setSearch] = useState('')
  const [searchInput, setSearchInput] = useState('')
  const [estadoFilter, setEstadoFilter] = useState('')
  const [subestadoFilter, setSubestadoFilter] = useState('')
  const [fechaDesde, setFechaDesde] = useState('')
  const [fechaHasta, setFechaHasta] = useState('')

  const selectedEstadoObj = estados.find(e => String(e.id) === String(estadoFilter))
  const subestadosDisponibles = getSubestadosForEstado(selectedEstadoObj?.nombre)

  // Selección múltiple
  const [selectedIds, setSelectedIds] = useState(new Set())

  // Diálogos y Modales
  const [infoDialog, setInfoDialog] = useState(null)
  const [confirmPermanentDelete, setConfirmPermanentDelete] = useState(null) // null | { ids: number[], isBulk?: boolean }
  const [restoreModal, setRestoreModal] = useState(null) // null | { ids: number[], isBulk?: boolean }
  const [bulkEstadoModal, setBulkEstadoModal] = useState(null) // null | { ids: number[] }
  const [targetEstadoId, setTargetEstadoId] = useState('')
  const [isProcessing, setIsProcessing] = useState(false)

  // Cargar catálogos
  useEffect(() => {
    loadCatalogs()
  }, [loadCatalogs])

  // Cargar estadísticas
  const fetchStats = useCallback(async () => {
    setLoadingStats(true)
    try {
      const res = await api.get('/api/leads-inactivos/stats')
      setStats(res.data || { total: 0, total_recientes: 0, por_estado: [] })
    } catch (err) {
      console.error('Error cargando estadísticas de inactivos:', err)
    } finally {
      setLoadingStats(false)
    }
  }, [])

  // Cargar leads inactivos
  const fetchLeads = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      params.append('limit', String(PAGE_SIZE))
      params.append('offset', String((page - 1) * PAGE_SIZE))
      if (search.trim()) params.append('search', search.trim())
      if (estadoFilter) params.append('estado_id', estadoFilter)
      if (subestadoFilter) params.append('subestado', subestadoFilter)
      if (fechaDesde) params.append('fecha_desde', fechaDesde)
      if (fechaHasta) params.append('fecha_hasta', fechaHasta)

      const res = await api.get(`/api/leads-inactivos?${params.toString()}`)
      setLeads(res.data?.items || [])
      setTotal(res.data?.total || 0)
    } catch (err) {
      console.error('Error cargando leads inactivos:', err)
      setInfoDialog({
        variant: 'error',
        title: 'Error al cargar leads',
        message: err?.response?.data?.detail || 'No se pudieron obtener los leads inactivos.',
      })
    } finally {
      setLoading(false)
    }
  }, [page, search, estadoFilter, subestadoFilter, fechaDesde, fechaHasta])

  useEffect(() => {
    fetchStats()
  }, [fetchStats])

  useEffect(() => {
    fetchLeads()
  }, [fetchLeads])

  // Debounce buscador
  const debounceTimer = useRef(null)
  const handleSearchChange = (e) => {
    const val = e.target.value
    setSearchInput(val)
    clearTimeout(debounceTimer.current)
    debounceTimer.current = setTimeout(() => {
      setSearch(val)
      setPage(1)
    }, 350)
  }

  // Selección
  const toggleSelectAll = () => {
    if (selectedIds.size === leads.length && leads.length > 0) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(leads.map(l => l.id)))
    }
  }

  const toggleSelectOne = (id) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  // Restaurar Leads
  const handleRestoreConfirm = async () => {
    if (!restoreModal?.ids?.length) return
    setIsProcessing(true)
    try {
      const res = await api.post('/api/leads-inactivos/restaurar', {
        ids: restoreModal.ids,
        nuevo_estado_id: targetEstadoId ? Number(targetEstadoId) : null,
      })
      setRestoreModal(null)
      setTargetEstadoId('')
      setSelectedIds(new Set())
      setInfoDialog({
        variant: 'success',
        title: 'Leads restaurados',
        message: res.data?.message || 'Los leads han sido reactivados exitosamente.',
      })
      fetchLeads()
      fetchStats()
    } catch (err) {
      setInfoDialog({
        variant: 'error',
        title: 'Error al restaurar',
        message: err?.response?.data?.detail || 'No se pudieron restaurar los leads seleccionados.',
      })
    } finally {
      setIsProcessing(false)
    }
  }

  // Cambiar estado individual rápido
  const handleChangeEstado = async (leadId, newEstadoId) => {
    try {
      await api.patch(`/api/leads-inactivos/${leadId}/estado`, {
        estado_id: newEstadoId ? Number(newEstadoId) : null,
      })
      setLeads(prev => prev.map(l => {
        if (l.id === leadId) {
          const matched = estados.find(e => e.id === Number(newEstadoId))
          return {
            ...l,
            estado_id: newEstadoId ? Number(newEstadoId) : null,
            estado_nombre: matched?.nombre || 'Sin estado',
            estado_color: matched?.color_hex || '#6b7280',
          }
        }
        return l
      }))
      fetchStats()
    } catch (err) {
      setInfoDialog({
        variant: 'error',
        title: 'Error al cambiar estado',
        message: err?.response?.data?.detail || 'No se pudo actualizar el estado del lead inactivo.',
      })
    }
  }

  // Cambiar estado masivo
  const handleBulkEstadoConfirm = async () => {
    if (!bulkEstadoModal?.ids?.length) return
    setIsProcessing(true)
    try {
      const res = await api.patch('/api/leads-inactivos/bulk-estado', {
        ids: bulkEstadoModal.ids,
        estado_id: targetEstadoId ? Number(targetEstadoId) : null,
      })
      setBulkEstadoModal(null)
      setTargetEstadoId('')
      setSelectedIds(new Set())
      setInfoDialog({
        variant: 'success',
        title: 'Estados actualizados',
        message: res.data?.message || 'Se actualizó el estado de los leads seleccionados.',
      })
      fetchLeads()
      fetchStats()
    } catch (err) {
      setInfoDialog({
        variant: 'error',
        title: 'Error al cambiar estados',
        message: err?.response?.data?.detail || 'No se pudo actualizar el estado de los leads.',
      })
    } finally {
      setIsProcessing(false)
    }
  }

  // Eliminar permanente
  const handlePermanentDeleteConfirm = async () => {
    if (!confirmPermanentDelete?.ids?.length) return
    setIsProcessing(true)
    try {
      const res = await api.delete('/api/leads-inactivos/permanente', {
        data: { ids: confirmPermanentDelete.ids },
      })
      setConfirmPermanentDelete(null)
      setSelectedIds(new Set())
      setInfoDialog({
        variant: 'success',
        title: 'Eliminación completada',
        message: res.data?.message || 'Los leads han sido eliminados de forma definitiva.',
      })
      fetchLeads()
      fetchStats()
    } catch (err) {
      setInfoDialog({
        variant: 'error',
        title: 'Error al eliminar',
        message: err?.response?.data?.detail || 'No se pudieron eliminar permanentemente los leads.',
      })
    } finally {
      setIsProcessing(false)
    }
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  return (
    <div className="p-4 sm:p-6 max-w-[1600px] mx-auto space-y-6 animate-fadeIn">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="p-2 bg-red-100 dark:bg-red-950/50 text-red-600 dark:text-red-400 rounded-xl">
              <Trash2 size={24} />
            </div>
            <div>
              <h1 className="text-2xl font-bold tracking-tight text-gray-900 dark:text-gray-100">
                Papelera de Leads
              </h1>
              <p className="text-xs sm:text-sm text-gray-500 dark:text-gray-400">
                Gestión, reactivación manual y depuración de leads inactivos o eliminados
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => { fetchLeads(); fetchStats() }}
            disabled={loading}
            className="gap-1.5 cursor-pointer shadow-xs"
          >
            <RefreshCw size={14} className={loading ? 'animate-spin' : ''} />
            Actualizar
          </Button>
        </div>
      </div>

      {/* KPI Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card className="border-gray-200 dark:border-slate-800 shadow-xs">
          <CardContent className="p-4 flex items-center gap-3">
            <div className="p-3 bg-red-50 dark:bg-red-950/30 text-red-600 dark:text-red-400 rounded-xl">
              <UserX size={20} />
            </div>
            <div>
              <p className="text-xs font-medium text-gray-500 dark:text-gray-400">Total en Papelera</p>
              <p className="text-xl font-bold text-gray-900 dark:text-gray-100">
                {stats.total.toLocaleString()}
              </p>
            </div>
          </CardContent>
        </Card>

        <Card className="border-gray-200 dark:border-slate-800 shadow-xs">
          <CardContent className="p-4 flex items-center gap-3">
            <div className="p-3 bg-amber-50 dark:bg-amber-950/30 text-amber-600 dark:text-amber-400 rounded-xl">
              <Calendar size={20} />
            </div>
            <div>
              <p className="text-xs font-medium text-gray-500 dark:text-gray-400">Inactivos últimos 30 días</p>
              <p className="text-xl font-bold text-gray-900 dark:text-gray-100">
                {stats.total_recientes.toLocaleString()}
              </p>
            </div>
          </CardContent>
        </Card>

        <Card className="border-gray-200 dark:border-slate-800 shadow-xs">
          <CardContent className="p-4 flex items-center gap-3">
            <div className="p-3 bg-indigo-50 dark:bg-indigo-950/30 text-indigo-600 dark:text-indigo-400 rounded-xl">
              <Layers size={20} />
            </div>
            <div>
              <p className="text-xs font-medium text-gray-500 dark:text-gray-400">Estados Afectados</p>
              <p className="text-xl font-bold text-gray-900 dark:text-gray-100">
                {stats.por_estado.length}
              </p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Toolbar / Filtros */}
      <Card className="border-gray-200 dark:border-slate-800 shadow-xs">
        <CardContent className="p-4">
          <div className="flex flex-col md:flex-row items-center gap-3">
            {/* Search */}
            <div className="relative w-full md:w-80">
              <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
              <Input
                type="text"
                placeholder="Buscar por nombre, celular o email..."
                value={searchInput}
                onChange={handleSearchChange}
                className="pl-9 h-9 text-xs"
              />
              {searchInput && (
                <button
                  onClick={() => { setSearchInput(''); setSearch(''); setPage(1) }}
                  className="absolute right-2.5 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 p-0.5"
                >
                  <X size={13} />
                </button>
              )}
            </div>

            {/* Filtro por Estado */}
            <div className="w-full md:w-56">
              <select
                value={estadoFilter}
                onChange={(e) => {
                  setEstadoFilter(e.target.value)
                  setSubestadoFilter('')
                  setPage(1)
                }}
                className="w-full h-9 rounded-md border border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 text-xs text-gray-800 dark:text-gray-200 focus:outline-hidden focus:ring-2 focus:ring-indigo-500"
              >
                <option value="">Todos los estados</option>
                {estados.map(e => (
                  <option key={e.id} value={e.id}>
                    {e.nombre}
                  </option>
                ))}
              </select>
            </div>

            {/* Filtro por Subestado (solo visible cuando el estado tiene subestados) */}
            {subestadosDisponibles.length > 0 && (
              <div className="w-full md:w-56 animate-in fade-in">
                <select
                  value={subestadoFilter}
                  onChange={(e) => { setSubestadoFilter(e.target.value); setPage(1) }}
                  className="w-full h-9 rounded-md border border-indigo-300 dark:border-indigo-700 bg-indigo-50/50 dark:bg-indigo-950/30 px-3 text-xs text-indigo-950 dark:text-indigo-200 font-medium focus:outline-hidden focus:ring-2 focus:ring-indigo-500"
                >
                  <option value="">Todos los subestados ({selectedEstadoObj?.nombre})</option>
                  {subestadosDisponibles.map(sub => (
                    <option key={sub} value={sub} className="text-gray-900 bg-white">
                      {sub}
                    </option>
                  ))}
                </select>
              </div>
            )}

            {/* Fecha Desde */}
            <div className="w-full md:w-40">
              <Input
                type="date"
                value={fechaDesde}
                onChange={(e) => { setFechaDesde(e.target.value); setPage(1) }}
                title="Fecha eliminación desde"
                className="h-9 text-xs"
              />
            </div>

            {/* Fecha Hasta */}
            <div className="w-full md:w-40">
              <Input
                type="date"
                value={fechaHasta}
                onChange={(e) => { setFechaHasta(e.target.value); setPage(1) }}
                title="Fecha eliminación hasta"
                className="h-9 text-xs"
              />
            </div>

            {/* Limpiar filtros */}
            {(search || estadoFilter || subestadoFilter || fechaDesde || fechaHasta) && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  setSearch('')
                  setSearchInput('')
                  setEstadoFilter('')
                  setSubestadoFilter('')
                  setFechaDesde('')
                  setFechaHasta('')
                  setPage(1)
                }}
                className="text-xs text-gray-500 hover:text-gray-800 dark:hover:text-gray-200 shrink-0"
              >
                <X size={13} className="mr-1" />
                Limpiar
              </Button>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Floating Bulk Actions Bar */}
      {selectedIds.size > 0 && (
        <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-40 bg-slate-900 text-white rounded-2xl shadow-2xl px-5 py-3 flex items-center gap-4 border border-slate-700 animate-slideUp">
          <span className="text-xs font-semibold bg-indigo-500/30 text-indigo-300 px-2.5 py-1 rounded-full">
            {selectedIds.size} seleccionados
          </span>

          <div className="h-4 w-px bg-slate-700" />

          <Button
            size="sm"
            onClick={() => setRestoreModal({ ids: Array.from(selectedIds), isBulk: true })}
            className="bg-emerald-600 hover:bg-emerald-700 text-white text-xs h-8 gap-1.5 cursor-pointer"
          >
            <RotateCcw size={14} />
            Restaurar
          </Button>

          <Button
            size="sm"
            variant="outline"
            onClick={() => setBulkEstadoModal({ ids: Array.from(selectedIds) })}
            className="border-slate-700 hover:bg-slate-800 text-slate-200 text-xs h-8 gap-1.5 cursor-pointer"
          >
            <Layers size={14} />
            Cambiar estado
          </Button>

          <Button
            size="sm"
            variant="outline"
            onClick={() => setConfirmPermanentDelete({ ids: Array.from(selectedIds), isBulk: true })}
            className="border-red-900/60 bg-red-950/40 text-red-300 hover:bg-red-900/60 text-xs h-8 gap-1.5 cursor-pointer"
          >
            <Trash2 size={14} />
            Eliminar permanente
          </Button>

          <button
            onClick={() => setSelectedIds(new Set())}
            className="text-slate-400 hover:text-white p-1 rounded-lg ml-1 cursor-pointer"
            title="Deseleccionar todos"
          >
            <X size={16} />
          </button>
        </div>
      )}

      {/* Tabla de Leads Inactivos */}
      <Card className="border-gray-200 dark:border-slate-800 shadow-xs overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead className="bg-gray-50 dark:bg-slate-800/60 text-gray-500 dark:text-gray-400 border-b border-gray-200 dark:border-slate-800 select-none">
              <tr>
                <th className="w-10 px-4 py-3 text-center">
                  <input
                    type="checkbox"
                    checked={leads.length > 0 && selectedIds.size === leads.length}
                    onChange={toggleSelectAll}
                    className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                  />
                </th>
                <th className="px-4 py-3 font-semibold">ID / Nombre</th>
                <th className="px-4 py-3 font-semibold">Contacto</th>
                <th className="px-4 py-3 font-semibold">Estado Previo</th>
                <th className="px-4 py-3 font-semibold">Asesor Asignado</th>
                <th className="px-4 py-3 font-semibold">Fecha Inactivación</th>
                <th className="px-4 py-3 font-semibold text-right">Acciones</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-slate-800">
              {loading ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center">
                    <LoadingSpinner size="md" />
                  </td>
                </tr>
              ) : leads.length === 0 ? (
                <tr>
                  <td colSpan={7} className="py-12 text-center text-gray-500 dark:text-gray-400">
                    <EmptyState
                      title="No hay leads inactivos"
                      description={
                        search || estadoFilter || fechaDesde || fechaHasta
                          ? 'No se encontraron resultados con los filtros aplicados.'
                          : 'La papelera de leads está vacía.'
                      }
                      icon={Trash2}
                    />
                  </td>
                </tr>
              ) : (
                leads.map((lead) => {
                  const isSelected = selectedIds.has(lead.id)
                  return (
                    <tr
                      key={lead.id}
                      className={cn(
                        'hover:bg-gray-50/75 dark:hover:bg-slate-800/40 transition-colors',
                        isSelected && 'bg-indigo-50/50 dark:bg-indigo-950/20'
                      )}
                    >
                      {/* Checkbox */}
                      <td className="px-4 py-3 text-center">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleSelectOne(lead.id)}
                          className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                        />
                      </td>

                      {/* Nombre / ID */}
                      <td className="px-4 py-3">
                        <div className="font-semibold text-gray-900 dark:text-gray-100 flex items-center gap-1.5">
                          <span className="text-gray-400 font-normal">#{lead.id}</span>
                          <span>{lead.nombre_completo || 'Sin nombre'}</span>
                        </div>
                        {lead.fuente_nombre && (
                          <div className="text-[11px] text-gray-400 mt-0.5">
                            Fuente: {lead.fuente_nombre} {lead.campana ? `(${lead.campana})` : ''}
                          </div>
                        )}
                      </td>

                      {/* Contacto */}
                      <td className="px-4 py-3 space-y-0.5">
                        {lead.telefono ? (
                          <div className="flex items-center gap-1 text-gray-700 dark:text-gray-300 font-mono">
                            <Phone size={12} className="text-gray-400" />
                            {lead.telefono}
                          </div>
                        ) : (
                          <span className="text-gray-400">—</span>
                        )}
                        {lead.email && (
                          <div className="flex items-center gap-1 text-[11px] text-gray-500 truncate max-w-[180px]">
                            <Mail size={11} className="text-gray-400" />
                            {lead.email}
                          </div>
                        )}
                      </td>

                      {/* Estado Dropdown */}
                      <td className="px-4 py-3">
                        <div className="flex flex-col items-start gap-0.5 max-w-[140px] min-w-0">
                          <select
                            value={lead.estado_id || ''}
                            onChange={(e) => handleChangeEstado(lead.id, e.target.value)}
                            className="text-xs rounded-full px-2.5 py-1 font-semibold border cursor-pointer transition-opacity hover:opacity-90"
                            style={{
                              backgroundColor: (lead.estado_color || '#6b7280') + '20',
                              color: lead.estado_color || '#6b7280',
                              borderColor: (lead.estado_color || '#6b7280') + '40',
                            }}
                          >
                            <option value="">Sin estado</option>
                            {estados.map(e => (
                              <option key={e.id} value={e.id} className="text-gray-900 bg-white">
                                {e.nombre}
                              </option>
                            ))}
                          </select>
                          <EstadoSubinfo lead={lead} estadoNombre={lead.estado_nombre} />
                        </div>
                      </td>

                      {/* Asesor */}
                      <td className="px-4 py-3 text-gray-600 dark:text-gray-300">
                        {lead.asesor_nombre || <span className="text-gray-400 italic">Sin asesor</span>}
                      </td>

                      {/* Fecha de Inactivación */}
                      <td className="px-4 py-3 text-gray-500 text-[11px]">
                        {formatDate(lead.fecha_inactivacion || lead.fecha_ingreso)}
                      </td>

                      {/* Acciones */}
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-1.5">
                          {/* Restaurar */}
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setRestoreModal({ ids: [lead.id], isBulk: false })}
                            title="Restaurar / Reactivar lead"
                            className="h-7 px-2 text-emerald-600 hover:text-emerald-700 hover:bg-emerald-50 dark:hover:bg-emerald-950/50 gap-1 text-xs cursor-pointer"
                          >
                            <RotateCcw size={13} />
                            Restaurar
                          </Button>

                          {/* Eliminar permanente */}
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => setConfirmPermanentDelete({ ids: [lead.id], isBulk: false })}
                            title="Eliminar de forma permanente"
                            className="h-7 px-2 text-red-500 hover:text-red-700 hover:bg-red-50 dark:hover:bg-red-950/50 text-xs cursor-pointer"
                          >
                            <Trash2 size={13} />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Paginación */}
        {total > 0 && (
          <div className="flex items-center justify-between px-4 py-3 border-t border-gray-200 dark:border-slate-800 text-xs text-gray-500">
            <div>
              Mostrando {((page - 1) * PAGE_SIZE + 1).toLocaleString()} a {Math.min(page * PAGE_SIZE, total).toLocaleString()} de {total.toLocaleString()} leads inactivos
            </div>
            <div className="flex items-center gap-1.5">
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page <= 1 || loading}
                className="h-7 px-2.5 text-xs gap-1"
              >
                <ChevronLeft size={13} />
                Anterior
              </Button>
              <span className="px-2 font-medium text-gray-700 dark:text-gray-300">
                {page} / {totalPages}
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages || loading}
                className="h-7 px-2.5 text-xs gap-1"
              >
                Siguiente
                <ChevronRight size={13} />
              </Button>
            </div>
          </div>
        )}
      </Card>

      {/* Modal Confirmar Restauración */}
      {restoreModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-xs animate-fadeIn">
          <div className="bg-white dark:bg-slate-900 rounded-2xl border border-gray-200 dark:border-slate-800 shadow-2xl max-w-md w-full p-6 animate-scaleIn space-y-4">
            <div className="flex items-center gap-3">
              <div className="p-2.5 bg-emerald-100 dark:bg-emerald-950/50 rounded-xl text-emerald-700 dark:text-emerald-400">
                <RotateCcw size={22} />
              </div>
              <div>
                <h3 className="text-base font-bold text-gray-900 dark:text-gray-100">
                  Restaurar {restoreModal.ids.length === 1 ? 'Lead' : `${restoreModal.ids.length} Leads`}
                </h3>
                <p className="text-xs text-gray-500">
                  El lead volverá a estar activo y visible en el panel principal
                </p>
              </div>
            </div>

            <div className="space-y-2 py-1">
              <label className="text-xs font-semibold text-gray-700 dark:text-gray-300">
                Estado destino al reactivar (opcional):
              </label>
              <select
                value={targetEstadoId}
                onChange={(e) => setTargetEstadoId(e.target.value)}
                className="w-full h-9 rounded-md border border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 text-xs text-gray-800 dark:text-gray-200 focus:outline-hidden focus:ring-2 focus:ring-emerald-500"
              >
                <option value="">Mantener estado original del lead</option>
                {estados.map(e => (
                  <option key={e.id} value={e.id}>
                    {e.nombre}
                  </option>
                ))}
              </select>
              <p className="text-[11px] text-gray-400">
                Si no seleccionas un nuevo estado, conservará el que tenía al momento de ser inactivado.
              </p>
            </div>

            <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-gray-100 dark:border-slate-800">
              <Button
                variant="outline"
                size="sm"
                onClick={() => { setRestoreModal(null); setTargetEstadoId('') }}
                disabled={isProcessing}
              >
                Cancelar
              </Button>
              <Button
                size="sm"
                onClick={handleRestoreConfirm}
                disabled={isProcessing}
                className="bg-emerald-600 hover:bg-emerald-700 text-white gap-1.5 cursor-pointer"
              >
                <RotateCcw size={14} className={isProcessing ? 'animate-spin' : ''} />
                {isProcessing ? 'Restaurando...' : 'Confirmar Restauración'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Cambiar Estado Masivo */}
      {bulkEstadoModal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-xs animate-fadeIn">
          <div className="bg-white dark:bg-slate-900 rounded-2xl border border-gray-200 dark:border-slate-800 shadow-2xl max-w-md w-full p-6 animate-scaleIn space-y-4">
            <div className="flex items-center gap-3">
              <div className="p-2.5 bg-indigo-100 dark:bg-indigo-950/50 rounded-xl text-indigo-700 dark:text-indigo-400">
                <Layers size={22} />
              </div>
              <div>
                <h3 className="text-base font-bold text-gray-900 dark:text-gray-100">
                  Cambiar Estado en Bloque
                </h3>
                <p className="text-xs text-gray-500">
                  Actualizar el estado de {bulkEstadoModal.ids.length} leads inactivos seleccionados
                </p>
              </div>
            </div>

            <div className="space-y-2 py-1">
              <label className="text-xs font-semibold text-gray-700 dark:text-gray-300">
                Nuevo estado:
              </label>
              <select
                value={targetEstadoId}
                onChange={(e) => setTargetEstadoId(e.target.value)}
                className="w-full h-9 rounded-md border border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-900 px-3 text-xs text-gray-800 dark:text-gray-200 focus:outline-hidden focus:ring-2 focus:ring-indigo-500"
              >
                <option value="">Selecciona un estado...</option>
                {estados.map(e => (
                  <option key={e.id} value={e.id}>
                    {e.nombre}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-gray-100 dark:border-slate-800">
              <Button
                variant="outline"
                size="sm"
                onClick={() => { setBulkEstadoModal(null); setTargetEstadoId('') }}
                disabled={isProcessing}
              >
                Cancelar
              </Button>
              <Button
                size="sm"
                onClick={handleBulkEstadoConfirm}
                disabled={isProcessing || !targetEstadoId}
                className="bg-indigo-600 hover:bg-indigo-700 text-white gap-1.5 cursor-pointer"
              >
                {isProcessing ? 'Guardando...' : 'Aplicar Cambio'}
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Modal Confirmar Eliminación Permanente */}
      <ConfirmDialog
        open={!!confirmPermanentDelete}
        variant="danger"
        title="Eliminar de forma permanente"
        message={
          confirmPermanentDelete?.ids?.length === 1
            ? '¿Estás seguro de que deseas eliminar este lead definitivamente de la base de datos? Esta acción es irreversible y eliminará todos sus registros asociados.'
            : `¿Estás seguro de que deseas eliminar permanentemente ${confirmPermanentDelete?.ids?.length} leads de la base de datos? Esta acción es irreversible.`
        }
        confirmLabel={isProcessing ? 'Eliminando...' : 'Sí, eliminar definitivamente'}
        cancelLabel="Cancelar"
        onConfirm={handlePermanentDeleteConfirm}
        onCancel={() => setConfirmPermanentDelete(null)}
      />

      {/* Info Dialog */}
      {infoDialog && (
        <InfoDialog
          open={!!infoDialog}
          variant={infoDialog.variant}
          title={infoDialog.title}
          message={infoDialog.message}
          onClose={() => setInfoDialog(null)}
        />
      )}
    </div>
  )
}
