import { useEffect, useState, useCallback, useRef } from 'react'
import { Phone, RefreshCw, ChevronLeft, ChevronRight, Trash2, Users } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import DataTable from '@/components/shared/DataTable'
import ConfirmDialog from '@/components/shared/ConfirmDialog'
import useAuthStore from '@/store/authStore'
import api from '@/lib/api'

const PAGE_SIZE = 50

/**
 * Formatea segundos a "Xm Ys" o "—" si es 0 o nulo.
 */
function formatDuracion(segundos) {
  if (!segundos || segundos <= 0) return '—'
  const m = Math.floor(segundos / 60)
  const s = segundos % 60
  if (m === 0) return `${s}s`
  if (s === 0) return `${m}m`
  return `${m}m ${s}s`
}

/**
 * Formatea ISO datetime a fecha y hora local peruana.
 */
function formatFecha(iso) {
  if (!iso) return '—'
  return new Date(iso).toLocaleString('es-PE', {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}

/** Badge de tipo de llamada */
function TipoBadge({ tipo }) {
  const config = {
    saliente: { label: 'Saliente', cls: 'bg-indigo-100 text-indigo-700 border border-indigo-200' },
    entrante: { label: 'Entrante', cls: 'bg-green-100 text-green-700 border border-green-200' },
    perdida:  { label: 'Perdida',  cls: 'bg-red-100 text-red-700 border border-red-200' },
  }
  const { label, cls } = config[tipo] || { label: tipo, cls: 'bg-gray-100 text-gray-600 border border-gray-200' }
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded-full text-xs font-semibold ${cls}`}>
      {label}
    </span>
  )
}

/** Tarjeta de stat */
function StatCard({ label, value, sub }) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm">
      <p className="text-xs font-medium text-gray-500 uppercase tracking-wide mb-1">{label}</p>
      <p className="text-2xl font-bold text-gray-900 leading-tight">{value}</p>
      {sub && <p className="text-xs text-gray-400 mt-0.5">{sub}</p>}
    </div>
  )
}

/** Checkbox con soporte indeterminate via ref callback */
function Checkbox({ checked, indeterminate, onChange, onClick, className = '' }) {
  const ref = useRef(null)
  useEffect(() => {
    if (ref.current) ref.current.indeterminate = indeterminate ?? false
  }, [indeterminate])
  return (
    <input
      ref={ref}
      type="checkbox"
      checked={checked}
      onChange={onChange}
      onClick={onClick}
      className={`w-4 h-4 accent-indigo-600 cursor-pointer rounded ${className}`}
    />
  )
}

const TABLE_HEADERS_BASE = [
  { key: 'asesor_nombre',      label: 'Asesor' },
  { key: 'telefono',           label: 'Teléfono' },
  { key: 'lead_nombre',        label: 'Lead' },
  { key: 'tipo',               label: 'Tipo' },
  { key: 'duracion_segundos',  label: 'Duración' },
  { key: 'fecha_llamada',      label: 'Fecha y hora' },
]

export default function Llamadas() {
  const { user } = useAuthStore()
  const role      = user?.role || 'asesor'
  const canAssign = role === 'admin' || role === 'supervisor'

  // Estado de la tabla
  const [llamadas, setLlamadas]     = useState([])
  const [total, setTotal]           = useState(0)
  const [isLoading, setIsLoading]   = useState(true)
  const [error, setError]           = useState(null)
  const [page, setPage]             = useState(1)

  // Selección múltiple
  const [selectedIds, setSelectedIds] = useState(new Set())

  // Stats
  const [stats, setStats]               = useState(null)
  const [isLoadingStats, setIsLoadingStats] = useState(true)

  // Filtros
  const [filterAsesor, setFilterAsesor]         = useState('')
  const [filterTipo, setFilterTipo]             = useState('')
  const [filterFechaDesde, setFilterFechaDesde] = useState('')
  const [filterFechaHasta, setFilterFechaHasta] = useState('')
  const [soloConLead, setSoloConLead]           = useState(true)

  // Asesores para el select
  const [asesores, setAsesores]   = useState([])
  const [deletingId, setDeletingId] = useState(null)

  // Confirm dialog unificado: { open, id, bulk }
  const [confirmDialog, setConfirmDialog] = useState({ open: false, id: null, bulk: false })

  // -------------------------------------------------------------------
  // Computed: selección de página
  // -------------------------------------------------------------------
  const allPageSelected  = llamadas.length > 0 && llamadas.every(l => selectedIds.has(l.id))
  const somePageSelected = !allPageSelected && llamadas.some(l => selectedIds.has(l.id))

  const toggleSelect = useCallback((id) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }, [])

  const toggleSelectAll = useCallback(() => {
    if (allPageSelected) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(llamadas.map(l => l.id)))
    }
  }, [allPageSelected, llamadas])

  // -------------------------------------------------------------------
  // Headers dinámicos con checkbox para admin/supervisor
  // -------------------------------------------------------------------
  const tableHeaders = canAssign
    ? [
        {
          key: '_select',
          label: (
            <Checkbox
              checked={allPageSelected}
              indeterminate={somePageSelected}
              onChange={toggleSelectAll}
            />
          ),
          className: 'w-10 pr-0',
        },
        ...TABLE_HEADERS_BASE,
        { key: '_acciones', label: '' },
      ]
    : TABLE_HEADERS_BASE

  // -------------------------------------------------------------------
  // Data loading
  // -------------------------------------------------------------------
  useEffect(() => {
    if (!canAssign) return
    api.get('/auth/users')
      .then(res => setAsesores(
        (res.data || [])
          .filter(u => u.role === 'asesor')
          .map(u => ({
            ...u,
            nombre_completo: [u.first_name, u.last_name].filter(Boolean).join(' ') || u.email,
          }))
      ))
      .catch(() => {})
  }, [canAssign])

  const fetchStats = useCallback(() => {
    setIsLoadingStats(true)
    api.get('/api/llamadas/stats')
      .then(res => setStats(res.data))
      .catch(() => setStats(null))
      .finally(() => setIsLoadingStats(false))
  }, [])

  useEffect(() => { fetchStats() }, [fetchStats])

  const fetchLlamadas = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const params = new URLSearchParams()
      params.set('limit', PAGE_SIZE)
      params.set('offset', (page - 1) * PAGE_SIZE)
      if (filterAsesor)     params.set('asesor_id', filterAsesor)
      if (filterTipo)       params.set('tipo', filterTipo)
      if (filterFechaDesde) params.set('fecha_desde', filterFechaDesde)
      if (filterFechaHasta) params.set('fecha_hasta', filterFechaHasta)
      if (soloConLead)      params.set('solo_con_lead', 'true')

      const res = await api.get(`/api/llamadas?${params.toString()}`)
      setLlamadas(res.data.items || [])
      setTotal(res.data.total || 0)
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al cargar las llamadas.')
    } finally {
      setIsLoading(false)
    }
  }, [page, filterAsesor, filterTipo, filterFechaDesde, filterFechaHasta, soloConLead])

  useEffect(() => { fetchLlamadas() }, [fetchLlamadas])

  // Resetear página y selección al cambiar filtros
  useEffect(() => { setPage(1) }, [filterAsesor, filterTipo, filterFechaDesde, filterFechaHasta, soloConLead])
  useEffect(() => { setSelectedIds(new Set()) }, [page, filterAsesor, filterTipo, filterFechaDesde, filterFechaHasta, soloConLead])

  // -------------------------------------------------------------------
  // Delete handlers
  // -------------------------------------------------------------------
  const handleDelete = (id) => {
    setConfirmDialog({ open: true, id, bulk: false })
  }

  const handleBulkDelete = () => {
    setConfirmDialog({ open: true, id: null, bulk: true })
  }

  const handleConfirmDelete = async () => {
    if (confirmDialog.bulk) {
      const ids = [...selectedIds]
      setConfirmDialog({ open: false, id: null, bulk: false })
      setIsLoading(true)
      try {
        await api.delete('/api/llamadas/bulk', { data: { ids } })
        setSelectedIds(new Set())
        fetchLlamadas()   // recarga la lista desde el servidor
        fetchStats()      // actualiza las estadísticas
      } catch (err) {
        setIsLoading(false)
        alert(err.response?.data?.detail || 'Error al eliminar.')
      }
    } else {
      const id = confirmDialog.id
      setConfirmDialog({ open: false, id: null, bulk: false })
      setDeletingId(id)
      try {
        await api.delete(`/api/llamadas/${id}`)
        setLlamadas(prev => prev.filter(l => l.id !== id))
        setTotal(prev => prev - 1)
      } catch (err) {
        alert(err.response?.data?.detail || 'Error al eliminar.')
      } finally {
        setDeletingId(null)
      }
    }
  }

  // -------------------------------------------------------------------
  // Render de celda
  // -------------------------------------------------------------------
  const renderCell = (row, key) => {
    switch (key) {
      case '_select':
        return (
          <Checkbox
            checked={selectedIds.has(row.id)}
            onChange={() => toggleSelect(row.id)}
            onClick={e => e.stopPropagation()}
          />
        )
      case 'asesor_nombre':
        return <span className="text-sm font-medium text-gray-800">{row.asesor_nombre || '—'}</span>
      case 'telefono':
        return <span className="font-mono text-sm text-gray-700">{row.telefono || '—'}</span>
      case 'lead_nombre':
        return row.lead_nombre && row.lead_nombre.trim()
          ? <span className="text-sm text-indigo-600 font-medium">{row.lead_nombre.trim()}</span>
          : <span className="text-gray-400 text-sm">—</span>
      case 'tipo':
        return <TipoBadge tipo={row.tipo} />
      case 'duracion_segundos':
        return <span className="text-sm text-gray-700 tabular-nums">{formatDuracion(row.duracion_segundos)}</span>
      case 'fecha_llamada':
        return <span className="text-sm text-gray-500 whitespace-nowrap">{formatFecha(row.fecha_llamada)}</span>
      case '_acciones':
        return canAssign ? (
          <button
            onClick={() => handleDelete(row.id)}
            disabled={deletingId === row.id}
            className="p-1.5 rounded hover:bg-red-50 text-gray-300 hover:text-red-400 disabled:opacity-50 transition-colors"
            title="Eliminar llamada"
          >
            <Trash2 size={14} />
          </button>
        ) : null
      default:
        return row[key] ?? '—'
    }
  }

  const totalPages   = Math.ceil(total / PAGE_SIZE)
  const showPagination = total > 0
  const hasFilters   = filterAsesor || filterTipo || filterFechaDesde || filterFechaHasta || soloConLead
  const perdidaSemana = stats?.por_tipo?.perdida ?? 0

  return (
    <div className="space-y-5">
      {/* Encabezado */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Llamadas</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {total.toLocaleString()} llamada{total !== 1 ? 's' : ''}
            {hasFilters && ' filtradas'}
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => { fetchLlamadas(); fetchStats() }}
          disabled={isLoading}
          className="gap-1.5"
        >
          <RefreshCw size={13} className={isLoading ? 'animate-spin' : ''} />
          Actualizar
        </Button>
      </div>

      {/* Tarjetas de stats */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard
          label="Total hoy"
          value={isLoadingStats ? '…' : (stats?.total_hoy ?? 0).toLocaleString()}
        />
        <StatCard
          label="Total semana"
          value={isLoadingStats ? '…' : (stats?.total_semana ?? 0).toLocaleString()}
          sub="últimos 7 días"
        />
        <StatCard
          label="Duración promedio"
          value={isLoadingStats ? '…' : formatDuracion(stats?.duracion_promedio_segundos ?? 0)}
          sub="llamadas completadas"
        />
        <StatCard
          label="Perdidas semana"
          value={isLoadingStats ? '…' : perdidaSemana.toLocaleString()}
          sub="sin respuesta"
        />
      </div>

      {/* Barra de filtros + paginación correo profesional-style */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2 flex-wrap">
          {/* Filtro asesor */}
          {canAssign && (
            <select
              value={filterAsesor}
              onChange={e => setFilterAsesor(e.target.value)}
              className="text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="">Todos los asesores</option>
              {asesores.map(a => (
                <option key={a.id} value={a.id}>{a.nombre_completo}</option>
              ))}
            </select>
          )}

          {/* Filtro tipo */}
          <select
            value={filterTipo}
            onChange={e => setFilterTipo(e.target.value)}
            className="text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <option value="">Todos los tipos</option>
            <option value="saliente">Saliente</option>
            <option value="entrante">Entrante</option>
            <option value="perdida">Perdida</option>
          </select>

          {/* Filtro fecha desde */}
          <input
            type="date"
            value={filterFechaDesde}
            onChange={e => setFilterFechaDesde(e.target.value)}
            className="text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
            title="Desde"
          />

          {/* Filtro fecha hasta */}
          <input
            type="date"
            value={filterFechaHasta}
            onChange={e => setFilterFechaHasta(e.target.value)}
            className="text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
            title="Hasta"
          />

          {/* Toggle: solo con lead */}
          <button
            onClick={() => setSoloConLead(p => !p)}
            className={`inline-flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-md border transition-colors ${
              soloConLead
                ? 'bg-[var(--brand-primary)] text-white border-[var(--brand-primary)]'
                : 'bg-white text-gray-600 border-gray-200 hover:bg-gray-50'
            }`}
          >
            <Users size={13} />
            Solo con lead
          </button>

          {/* Limpiar filtros */}
          {hasFilters && (
            <button
              onClick={() => {
                setFilterAsesor('')
                setFilterTipo('')
                setFilterFechaDesde('')
                setFilterFechaHasta('')
                setSoloConLead(false)
              }}
              className="text-xs text-gray-500 hover:text-gray-700 underline"
            >
              Limpiar
            </button>
          )}
        </div>

        {/* Paginación correo profesional-style */}
        {showPagination && totalPages > 1 && (
          <div className="flex items-center gap-2 shrink-0">
            <span className="text-sm text-gray-500 select-none">
              {((page - 1) * PAGE_SIZE + 1).toLocaleString()}–{Math.min(page * PAGE_SIZE, total).toLocaleString()} de {total.toLocaleString()}
            </span>
            <div className="flex gap-1">
              <button
                onClick={() => setPage(p => p - 1)}
                disabled={page <= 1 || isLoading}
                className="w-8 h-8 flex items-center justify-center rounded-full border border-gray-200 text-gray-500 hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                <ChevronLeft size={16} />
              </button>
              <button
                onClick={() => setPage(p => p + 1)}
                disabled={page >= totalPages || isLoading}
                className="w-8 h-8 flex items-center justify-center rounded-full border border-gray-200 text-gray-500 hover:bg-gray-100 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
              >
                <ChevronRight size={16} />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* Barra de acción en masa — visible cuando hay selección */}
      {canAssign && selectedIds.size > 0 && (
        <div className="flex items-center gap-3 px-4 py-2.5 bg-indigo-50 border border-indigo-200 rounded-xl">
          <span className="text-sm font-medium text-indigo-700">
            {selectedIds.size} {selectedIds.size === 1 ? 'llamada seleccionada' : 'llamadas seleccionadas'}
          </span>
          <Button
            size="sm"
            onClick={handleBulkDelete}
            className="gap-1.5 bg-red-600 hover:bg-red-700 text-white ml-2"
          >
            <Trash2 size={13} />
            Eliminar seleccionadas
          </Button>
          <button
            onClick={() => setSelectedIds(new Set())}
            className="text-xs text-indigo-500 hover:text-indigo-700 underline ml-auto"
          >
            Cancelar selección
          </button>
        </div>
      )}

      {/* Tabla principal */}
      <Card>
        <DataTable
          headers={tableHeaders}
          rows={llamadas}
          renderCell={renderCell}
          columnOrderKey="llamadas_columns_order"
          isLoading={isLoading}
          error={error}
          emptyTitle="No hay llamadas"
          emptyDescription={
            hasFilters
              ? 'Prueba ajustando los filtros.'
              : 'Las llamadas sincronizadas desde la app Android aparecerán aquí.'
          }
          emptyIcon={Phone}
          pagination={null}
          onPageChange={setPage}
        />
      </Card>

      <ConfirmDialog
        open={confirmDialog.open}
        title={confirmDialog.bulk ? 'Eliminar llamadas seleccionadas' : 'Eliminar llamada'}
        message={
          confirmDialog.bulk
            ? `¿Estás seguro de que deseas eliminar las ${selectedIds.size} llamadas seleccionadas? Esta acción no se puede deshacer.`
            : '¿Estás seguro de que deseas eliminar este registro de llamada? Esta acción no se puede deshacer.'
        }
        onConfirm={handleConfirmDelete}
        onCancel={() => setConfirmDialog({ open: false, id: null, bulk: false })}
      />
    </div>
  )
}
