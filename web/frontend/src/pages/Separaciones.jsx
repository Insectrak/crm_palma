import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  FileSpreadsheet,
  RefreshCw,
  GitBranch,
  GitCommit,
  GitPullRequest,
  Plus,
  Edit2,
  Trash2,
  Download,
  Upload,
  Search,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  Settings,
  X,
  Check,
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Layers,
} from 'lucide-react'
import api from '@/lib/api'

const MONTHS = [
  { num: 1, name: 'ENERO', label: 'Enero' },
  { num: 2, name: 'FEBRERO', label: 'Febrero' },
  { num: 3, name: 'MARZO', label: 'Marzo' },
  { num: 4, name: 'ABRIL', label: 'Abril' },
  { num: 5, name: 'MAYO', label: 'Mayo' },
  { num: 6, name: 'JUNIO', label: 'Junio' },
  { num: 7, name: 'JULIO', label: 'Julio' },
  { num: 8, name: 'AGOSTO', label: 'Agosto' },
  { num: 9, name: 'SETIEMBRE', label: 'Setiembre' },
  { num: 10, name: 'OCTUBRE', label: 'Octubre' },
  { num: 11, name: 'NOVIEMBRE', label: 'Noviembre' },
  { num: 12, name: 'DICIEMBRE', label: 'Diciembre' },
]

const ESTADOS_SUGERIDOS = [
  'SEPARADO',
  'VENDIDO',
  'LIBERADO',
  'NO VA',
  'SOLICITUD DE DEVOLUCIÓN',
  'VENTAS',
]

function formatDateTimeLima(iso) {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return '—'
    return d.toLocaleString('es-PE', {
      timeZone: 'America/Lima',
      day: '2-digit',
      month: '2-digit',
      year: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return '—'
  }
}

function getEstadoBadgeStyle(estado) {
  const est = (estado || '').toUpperCase()
  if (est === 'VENDIDO' || est === 'VENTA' || est === 'VENTAS') {
    return 'bg-emerald-50 text-emerald-700 border-emerald-200 dark:bg-emerald-950/50 dark:text-emerald-300 dark:border-emerald-800'
  }
  if (est === 'SEPARADO') {
    return 'bg-sky-50 text-sky-700 border-sky-200 dark:bg-sky-950/50 dark:text-sky-300 dark:border-sky-800'
  }
  if (est === 'LIBERADO' || est === 'NO VA' || est.includes('DEVOLUCI')) {
    return 'bg-slate-100 text-slate-600 border-slate-200 dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700'
  }
  return 'bg-amber-50 text-amber-700 border-amber-200 dark:bg-amber-950/50 dark:text-amber-300 dark:border-amber-800'
}

export default function Separaciones({ embedded = false }) {
  const [meta, setMeta] = useState(null)
  const [items, setItems] = useState([])
  const [resumen, setResumen] = useState({})
  const [loading, setLoading] = useState(true)
  const [checkingDrive, setCheckingDrive] = useState(false)
  const [uploadingExcel, setUploadingExcel] = useState(false)
  const [error, setError] = useState(null)
  const [toast, setToast] = useState(null)
  const fileInputRef = useRef(null)

  // Filtros
  const [selectedPeriodo, setSelectedPeriodo] = useState('') // '' = todos o 'YYYY-M'
  const [activeSubTab, setActiveSubTab] = useState('separaciones') // 'separaciones' | 'cierres' | 'resumen'
  const [vigenciaFilter, setVigenciaFilter] = useState('')
  const [estadoFilter, setEstadoFilter] = useState('')
  const [proyectoFilter, setProyectoFilter] = useState('')
  const [asesorFilter, setAsesorFilter] = useState('')
  const [estrategiaFilter, setEstrategiaFilter] = useState('')
  const [search, setSearch] = useState('')

  // Modales
  const [showDiffModal, setShowDiffModal] = useState(false)
  const [diffFilter, setDiffFilter] = useState('todos')
  const [selectedDiffKeys, setSelectedDiffKeys] = useState(new Set())
  const [commitMsg, setCommitMsg] = useState('')
  const [approving, setApproving] = useState(false)

  const [showHistoryModal, setShowHistoryModal] = useState(false)
  const [revisions, setRevisions] = useState([])
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [expandedRevId, setExpandedRevId] = useState(null)

  const [showFormModal, setShowFormModal] = useState(false)
  const [editingRow, setEditingRow] = useState(null)
  const [savingForm, setSavingForm] = useState(false)
  const [formState, setFormState] = useState({
    tipo: 'separacion',
    anio: 2026,
    mes: 10,
    asesor: '',
    proyecto: '',
    lote: '',
    fecha_ingreso: '',
    fecha_vencimiento: '',
    monto_raw: '',
    estrategia: '',
    estado: 'SEPARADO',
    observaciones: '',
  })

  const [showDriveCfgModal, setShowDriveCfgModal] = useState(false)
  const [driveUrlDraft, setDriveUrlDraft] = useState('')
  const [savingCfg, setSavingCfg] = useState(false)

  const showToastMsg = (text, kind = 'success') => {
    setToast({ text, kind })
    setTimeout(() => setToast(null), 4000)
  }

  const fetchAll = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const metaRes = await api.get('/api/separaciones/meta')
      const m = metaRes.data
      setMeta(m)
      setDriveUrlDraft(m?.drive_config?.sheet_url || '')

      const params = new URLSearchParams()
      if (selectedPeriodo) {
        const [y, mm] = selectedPeriodo.split('-')
        if (y) params.append('anio', y)
        if (mm) params.append('mes', mm)
      }
      if (vigenciaFilter) params.append('vigencia', vigenciaFilter)
      if (estadoFilter) params.append('estado', estadoFilter)
      if (proyectoFilter) params.append('proyecto', proyectoFilter)
      if (asesorFilter) params.append('asesor', asesorFilter)
      if (estrategiaFilter) params.append('estrategia', estrategiaFilter)
      if (search.trim()) params.append('search', search.trim())

      const listRes = await api.get(`/api/separaciones?${params.toString()}`)
      setItems(listRes.data?.items || [])
      setResumen(listRes.data?.resumen || {})
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo cargar el módulo de Separaciones.')
    } finally {
      setLoading(false)
    }
  }, [selectedPeriodo, vigenciaFilter, estadoFilter, proyectoFilter, asesorFilter, estrategiaFilter, search])

  useEffect(() => {
    fetchAll()
  }, [fetchAll])

  const pendingRevision = meta?.pending_revision || null
  const driveConfig = meta?.drive_config || null

  const openDiffModalWithRev = (rev) => {
    const changes = rev?.diff_json || []
    setSelectedDiffKeys(new Set(changes.map((c) => c.sync_key)))
    setCommitMsg(rev?.message || '')
    setDiffFilter('todos')
    setShowDiffModal(true)
  }

  const handleCheckDrive = async (openModalIfChanges = true) => {
    setCheckingDrive(true)
    setError(null)
    try {
      const res = await api.post('/api/separaciones/drive/check')
      await fetchAll()
      if (res.data?.has_changes && res.data?.pending_revision) {
        showToastMsg('Se detectaron cambios en Google Drive listos para revisar.', 'info')
        if (openModalIfChanges) {
          openDiffModalWithRev(res.data.pending_revision)
        }
      } else {
        showToastMsg('Drive verificado: no hay cambios respecto al servidor.')
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al verificar Google Drive.')
    } finally {
      setCheckingDrive(false)
    }
  }

  const handleExcelFileSelected = async (e) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    setUploadingExcel(true)
    setError(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const res = await api.post('/api/separaciones/upload', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      await fetchAll()
      if (res.data?.has_changes && res.data?.pending_revision) {
        showToastMsg(
          `Excel comparado (${res.data.parsed_rows} registros). Revisa el Diff antes de aprobar.`,
          'info',
        )
        openDiffModalWithRev(res.data.pending_revision)
      } else {
        showToastMsg(`Excel comparado (${res.data.parsed_rows} registros): sin diferencias respecto al servidor.`)
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo procesar el archivo Excel subido.')
    } finally {
      setUploadingExcel(false)
    }
  }

  const handleApproveDiff = async () => {
    if (!pendingRevision) return
    if (selectedDiffKeys.size === 0) {
      showToastMsg('Selecciona al menos un cambio para aprobar.', 'error')
      return
    }
    setApproving(true)
    try {
      const res = await api.post(`/api/separaciones/revisions/${pendingRevision.id}/approve`, {
        selected_keys: Array.from(selectedDiffKeys),
        message: commitMsg.trim() || undefined,
      })
      setShowDiffModal(false)
      const c = res.data?.applied_counts || {}
      showToastMsg(`Aprobado: +${c.added || 0} nuevos, ~${c.modified || 0} modificados, -${c.removed || 0} quitados.`)
      await fetchAll()
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudieron aprobar los cambios.')
    } finally {
      setApproving(false)
    }
  }

  const handleRejectDiff = async () => {
    if (!pendingRevision) return
    setApproving(true)
    try {
      await api.post(`/api/separaciones/revisions/${pendingRevision.id}/reject`, {
        reason: 'Descartado manualmente por el administrador',
      })
      setShowDiffModal(false)
      showToastMsg('Revisión descartada. Se conservan los datos del servidor.')
      await fetchAll()
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo descartar la revisión.')
    } finally {
      setApproving(false)
    }
  }

  const handleOpenHistory = async () => {
    setShowHistoryModal(true)
    setLoadingHistory(true)
    try {
      const res = await api.get('/api/separaciones/revisions?limit=60')
      setRevisions(res.data?.items || [])
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo cargar el historial de versiones.')
    } finally {
      setLoadingHistory(false)
    }
  }

  const handleOpenCreate = (defaultTipo = 'separacion') => {
    let defaultAnio = 2026
    let defaultMes = new Date().getMonth() + 1
    if (selectedPeriodo) {
      const [y, m] = selectedPeriodo.split('-')
      if (y) defaultAnio = Number(y)
      if (m) defaultMes = Number(m)
    }
    setEditingRow(null)
    setFormState({
      tipo: defaultTipo,
      anio: defaultAnio,
      mes: defaultMes,
      asesor: '',
      proyecto: '',
      lote: '',
      fecha_ingreso: '',
      fecha_vencimiento: '',
      monto_raw: '',
      estrategia: '',
      estado: defaultTipo === 'separacion' ? 'SEPARADO' : 'VENDIDO',
      observaciones: '',
    })
    setShowFormModal(true)
  }

  const handleOpenEdit = (row) => {
    setEditingRow(row)
    setFormState({
      tipo: row.tipo || 'separacion',
      anio: row.anio || 2026,
      mes: row.mes || 10,
      asesor: row.asesor || '',
      proyecto: row.proyecto || '',
      lote: row.lote || '',
      fecha_ingreso: row.fecha_ingreso || '',
      fecha_vencimiento: row.fecha_vencimiento || '',
      monto_raw: row.monto_raw || (row.monto_numerico != null ? String(row.monto_numerico) : ''),
      estrategia: row.estrategia || '',
      estado: row.estado || 'SEPARADO',
      observaciones: row.observaciones || '',
    })
    setShowFormModal(true)
  }

  const handleSaveForm = async (e) => {
    e.preventDefault()
    if (!formState.proyecto.trim() || !formState.lote.trim()) {
      showToastMsg('Proyecto y Lote son obligatorios.', 'error')
      return
    }
    setSavingForm(true)
    try {
      const payload = {
        ...formState,
        anio: Number(formState.anio),
        mes: Number(formState.mes),
      }
      if (editingRow) {
        await api.patch(`/api/separaciones/${editingRow.id}`, payload)
        showToastMsg('Registro actualizado y versionado en el servidor.')
      } else {
        await api.post('/api/separaciones', payload)
        showToastMsg('Registro creado y respaldado en el servidor.')
      }
      setShowFormModal(false)
      await fetchAll()
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo guardar el registro.')
    } finally {
      setSavingForm(false)
    }
  }

  const handleQuickEstado = async (row, newEstado) => {
    try {
      await api.patch(`/api/separaciones/${row.id}`, { estado: newEstado })
      showToastMsg(`Estado actualizado a ${newEstado}`)
      await fetchAll()
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al actualizar estado.')
    }
  }

  const handleDeleteRow = async (row) => {
    if (!window.confirm(`¿Eliminar ${row.tipo} ${row.proyecto || ''} Lote ${row.lote || ''}? Quedará registrado en el historial.`)) {
      return
    }
    try {
      await api.delete(`/api/separaciones/${row.id}`)
      showToastMsg('Registro eliminado (registrado en historial).')
      await fetchAll()
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al eliminar registro.')
    }
  }

  const handleExport = async () => {
    try {
      const params = new URLSearchParams()
      if (selectedPeriodo) {
        const [y, mm] = selectedPeriodo.split('-')
        if (y) params.append('anio', y)
        if (mm) params.append('mes', mm)
      }
      const res = await api.get(`/api/separaciones/export?${params.toString()}`, { responseType: 'blob' })
      const url = window.URL.createObjectURL(new Blob([res.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `separaciones_palma_${selectedPeriodo || '2026'}.xlsx`)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch (err) {
      setError('No se pudo exportar el archivo Excel.')
    }
  }

  const handleSaveDriveCfg = async (e) => {
    e.preventDefault()
    setSavingCfg(true)
    try {
      await api.put('/api/separaciones/drive/config', { sheet_url: driveUrlDraft })
      setShowDriveCfgModal(false)
      showToastMsg('Enlace de Google Drive actualizado.')
      await fetchAll()
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo actualizar la URL de Drive.')
    } finally {
      setSavingCfg(false)
    }
  }

  const separacionesList = useMemo(() => items.filter((r) => r.tipo === 'separacion'), [items])
  const cierresList = useMemo(() => items.filter((r) => r.tipo === 'cierre'), [items])

  const diffChanges = useMemo(() => {
    const all = pendingRevision?.diff_json || []
    if (diffFilter === 'todos') return all
    return all.filter((c) => c.change_type === diffFilter)
  }, [pendingRevision, diffFilter])

  const catalogos = meta?.catalogos || {}
  const periodos = meta?.periodos || []

  return (
    <div className={`${embedded ? '' : 'p-6 max-w-[1680px] mx-auto'} space-y-6 animate-fadeIn text-slate-900 dark:text-slate-100`}>
      <input
        ref={fileInputRef}
        type="file"
        accept=".xlsx,.xlsm,.csv"
        className="hidden"
        onChange={handleExcelFileSelected}
      />
      {/* Toast */}
      {toast && (
        <div
          className={`fixed bottom-5 right-5 z-[60] px-4 py-3 rounded-xl shadow-lg border text-xs font-semibold flex items-center gap-2 ${
            toast.kind === 'error'
              ? 'bg-red-50 text-red-800 border-red-200'
              : toast.kind === 'info'
                ? 'bg-indigo-50 text-indigo-800 border-indigo-200'
                : 'bg-emerald-50 text-emerald-800 border-emerald-200'
          }`}
        >
          <CheckCircle2 size={15} />
          <span>{toast.text}</span>
        </div>
      )}

      {/* Encabezado */}
      <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm flex flex-col xl:flex-row xl:items-center justify-between gap-4">
        <div className="flex items-start gap-3">
          <span className="p-2.5 bg-[#1F1D5C]/10 text-[#1F1D5C] dark:bg-[#1F1D5C]/40 dark:text-indigo-300 rounded-xl border border-[#1F1D5C]/20">
            <FileSpreadsheet size={24} />
          </span>
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-lg font-bold text-slate-900 dark:text-white">
                Control de Separaciones
              </h2>
              {!embedded && (
                <span className="text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full bg-slate-900 text-white dark:bg-slate-800 dark:text-amber-300">
                  Solo Admin · Respaldado en Servidor
                </span>
              )}
            </div>
            <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400 mt-1">
              <span className="inline-flex items-center gap-1">
                <GitBranch size={12} className="text-indigo-500" />
                Fuente oficial: <strong>PostgreSQL CRM</strong>
              </span>
              <span>·</span>
              <span>
                Última revisión Drive:{' '}
                <strong>{formatDateTimeLima(driveConfig?.last_checked_at)}</strong>
              </span>
              {driveConfig?.sheet_url && (
                <a
                  href={driveConfig.sheet_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="inline-flex items-center gap-1 text-indigo-600 dark:text-indigo-400 hover:underline font-medium"
                >
                  Abrir Drive <ExternalLink size={11} />
                </a>
              )}
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={uploadingExcel}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-bold bg-[#1F1D5C] hover:bg-[#161444] text-white shadow-sm transition-colors cursor-pointer disabled:opacity-60"
          >
            <Upload size={14} />
            <span>{uploadingExcel ? 'Analizando Excel…' : 'Subir Excel (.xlsx / .csv)'}</span>
          </button>

          <button
            type="button"
            onClick={() => handleCheckDrive(true)}
            disabled={checkingDrive}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-700 text-white shadow-sm transition-colors cursor-pointer disabled:opacity-60"
          >
            <RefreshCw size={14} className={checkingDrive ? 'animate-spin' : ''} />
            <span>{checkingDrive ? 'Comparando Drive…' : 'Verificar cambios en Drive'}</span>
          </button>

          <button
            type="button"
            onClick={handleOpenHistory}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold bg-white dark:bg-[#0f1624] border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800 cursor-pointer"
          >
            <GitCommit size={14} className="text-purple-600" />
            <span>Versiones ({meta?.total_revisions ?? 0})</span>
          </button>

          <button
            type="button"
            onClick={handleExport}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-semibold bg-white dark:bg-[#0f1624] border border-slate-200 dark:border-slate-700 hover:bg-slate-50 dark:hover:bg-slate-800 cursor-pointer"
          >
            <Download size={14} className="text-emerald-600" />
            <span>Exportar .xlsx</span>
          </button>

          <button
            type="button"
            onClick={() => handleOpenCreate(activeSubTab === 'cierres' ? 'cierre' : 'separacion')}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-bold bg-emerald-600 hover:bg-emerald-700 text-white shadow-sm cursor-pointer"
          >
            <Plus size={14} />
            <span>Nuevo registro</span>
          </button>

          <button
            type="button"
            onClick={() => setShowDriveCfgModal(true)}
            className="p-2 rounded-xl bg-white dark:bg-[#0f1624] border border-slate-200 dark:border-slate-700 text-slate-500 hover:text-slate-800 dark:hover:text-white cursor-pointer"
            title="Configurar enlace de Google Drive"
          >
            <Settings size={15} />
          </button>
        </div>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 text-red-700 p-4 rounded-xl text-sm flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <AlertTriangle size={18} />
            <span>{error}</span>
          </div>
          <button type="button" onClick={() => setError(null)} className="text-xs font-bold underline">
            Cerrar
          </button>
        </div>
      )}

      {/* Banner: Base vacía (primera sincronización) */}
      {!loading && (meta?.total_registros || 0) === 0 && !pendingRevision && (
        <div className="bg-gradient-to-r from-indigo-50 via-white to-amber-50 dark:from-indigo-950/40 dark:via-[#121a29] dark:to-amber-950/30 border-2 border-indigo-200 dark:border-indigo-800 rounded-2xl p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-start gap-3">
            <GitPullRequest size={22} className="text-indigo-600 shrink-0 mt-0.5" />
            <div>
              <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                La base del servidor aún no tiene registros importados
              </h3>
              <p className="text-xs text-slate-600 dark:text-slate-300 mt-0.5">
                Haz clic en <strong>Verificar cambios en Drive</strong> para leer tu Google Sheet, previsualizar todos los registros y aprobar la importación inicial al servidor.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => handleCheckDrive(true)}
            disabled={checkingDrive}
            className="px-4 py-2 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-700 text-white shrink-0 cursor-pointer"
          >
            Importar desde Drive ahora
          </button>
        </div>
      )}

      {/* Banner: Revisión pendiente estilo Git */}
      {pendingRevision && (
        <div className="bg-amber-50 dark:bg-amber-950/30 border-2 border-amber-300 dark:border-amber-700 rounded-2xl p-4 flex flex-col md:flex-row md:items-center justify-between gap-3">
          <div className="flex items-start gap-3">
            <GitPullRequest size={20} className="text-amber-600 shrink-0 mt-0.5" />
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="text-sm font-bold text-amber-950 dark:text-amber-100">
                  Cambios pendientes ({pendingRevision.source === 'excel_upload' ? 'Archivo Excel' : 'Google Drive'} · Revisión #{pendingRevision.revision_number})
                </h3>
                <span className="text-[11px] font-bold px-2 py-0.5 rounded-full bg-emerald-100 text-emerald-800">
                  +{pendingRevision.summary_json?.added ?? 0} nuevos
                </span>
                <span className="text-[11px] font-bold px-2 py-0.5 rounded-full bg-amber-200 text-amber-900">
                  ~{pendingRevision.summary_json?.modified ?? 0} modificados
                </span>
                <span className="text-[11px] font-bold px-2 py-0.5 rounded-full bg-rose-100 text-rose-800">
                  -{pendingRevision.summary_json?.removed ?? 0} quitados
                </span>
              </div>
              <p className="text-xs text-amber-800 dark:text-amber-300 mt-0.5">
                Los cambios no se aplican automáticamente: revisa el comparativo (CRM actual vs. Drive) y aprueba los que correspondan.
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={() => openDiffModalWithRev(pendingRevision)}
            className="px-4 py-2 rounded-xl text-xs font-bold bg-amber-600 hover:bg-amber-700 text-white shrink-0 cursor-pointer shadow-sm"
          >
            Revisar y Aprobar Diff
          </button>
        </div>
      )}

      {/* KPIs Resumen */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
            Total Separaciones
          </span>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-slate-900 dark:text-white">
              {resumen.total_separaciones ?? 0}
            </span>
            <span className="text-xs text-slate-500">en filtro actual</span>
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5 text-[11px] font-semibold">
            <span className="px-2 py-0.5 rounded-md bg-emerald-50 text-emerald-700">
              Vigentes: {resumen.separaciones_vigentes ?? 0}
            </span>
            <span className="px-2 py-0.5 rounded-md bg-rose-50 text-rose-700">
              Vencidas: {resumen.separaciones_vencidas ?? 0}
            </span>
          </div>
        </div>

        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
            Conversión y Liberación
          </span>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-emerald-600">
              {resumen.separaciones_vendidas ?? 0}
            </span>
            <span className="text-xs text-slate-500">separaciones vendidas</span>
          </div>
          <div className="mt-3 text-[11px] text-slate-500 flex items-center justify-between">
            <span>Liberadas / No va:</span>
            <strong className="text-slate-700 dark:text-slate-200">{resumen.separaciones_liberadas ?? 0}</strong>
          </div>
        </div>

        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
            Cierres / Ventas Registradas
          </span>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-indigo-600 dark:text-indigo-400">
              {resumen.total_cierres ?? 0}
            </span>
            <span className="text-xs text-slate-500">bloque Cierres Palma</span>
          </div>
          <div className="mt-3 text-[11px] text-slate-500">
            Estrategia top:{' '}
            <strong className="text-slate-700 dark:text-slate-200">
              {resumen.resumen_estrategia_cierres?.[0]
                ? `${resumen.resumen_estrategia_cierres[0].estrategia} (${resumen.resumen_estrategia_cierres[0].total})`
                : '—'}
            </strong>
          </div>
        </div>

        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">
            Monto Separado
          </span>
          <div className="mt-2 space-y-0.5">
            <div className="text-2xl font-extrabold text-slate-900 dark:text-white">
              S/ {(resumen.monto_total_pen ?? 0).toLocaleString('es-PE', { minimumFractionDigits: 2 })}
            </div>
            {(resumen.monto_total_usd ?? 0) > 0 && (
              <div className="text-sm font-bold text-emerald-600">
                $ {(resumen.monto_total_usd ?? 0).toLocaleString('en-US', { minimumFractionDigits: 2 })} USD
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Selector de Meses + Filtros */}
      <div className="bg-white dark:bg-[#121a29] p-4 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm space-y-3">
        {/* Pills de mes */}
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => setSelectedPeriodo('')}
            className={`px-3 py-1.5 rounded-xl text-xs font-bold transition-colors cursor-pointer ${
              selectedPeriodo === ''
                ? 'bg-[#1F1D5C] text-white'
                : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200'
            }`}
          >
            Todos los meses
          </button>
          {periodos.map((p) => {
            const key = `${p.anio}-${p.mes}`
            const active = selectedPeriodo === key
            return (
              <button
                key={key}
                type="button"
                onClick={() => setSelectedPeriodo(active ? '' : key)}
                className={`px-3 py-1.5 rounded-xl text-xs font-semibold transition-colors cursor-pointer ${
                  active
                    ? 'bg-[#1F1D5C] text-white'
                    : 'bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 hover:bg-slate-200'
                }`}
              >
                {p.mes_nombre} {p.anio}
              </button>
            )
          })}
        </div>

        {/* Barra de filtros */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-2">
          <div className="relative lg:col-span-2">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Buscar asesor, proyecto, lote, estrategia..."
              className="w-full pl-8 pr-3 py-2 text-xs bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 rounded-xl outline-none"
            />
          </div>

          <select
            value={proyectoFilter}
            onChange={(e) => setProyectoFilter(e.target.value)}
            className="text-xs bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 rounded-xl px-2.5 py-2"
          >
            <option value="">Todos los proyectos</option>
            {(catalogos.proyectos || []).map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>

          <select
            value={asesorFilter}
            onChange={(e) => setAsesorFilter(e.target.value)}
            className="text-xs bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 rounded-xl px-2.5 py-2"
          >
            <option value="">Todos los asesores</option>
            {(catalogos.asesores || []).map((a) => (
              <option key={a} value={a}>{a}</option>
            ))}
          </select>

          <select
            value={estadoFilter}
            onChange={(e) => setEstadoFilter(e.target.value)}
            className="text-xs bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 rounded-xl px-2.5 py-2"
          >
            <option value="">Todos los estados</option>
            {(catalogos.estados || []).map((es) => (
              <option key={es} value={es}>{es}</option>
            ))}
          </select>

          <select
            value={vigenciaFilter}
            onChange={(e) => setVigenciaFilter(e.target.value)}
            className="text-xs bg-slate-50 dark:bg-slate-900/60 border border-slate-200 dark:border-slate-700 rounded-xl px-2.5 py-2"
          >
            <option value="">Toda vigencia</option>
            <option value="vigente">Vigentes</option>
            <option value="vencida">Vencidas</option>
            <option value="vendida">Vendidas</option>
            <option value="liberada">Liberadas</option>
          </select>
        </div>
      </div>

      {/* Pestañas de Tabla */}
      <div className="bg-white dark:bg-[#121a29] rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden">
        <div className="px-5 py-3 border-b border-slate-100 dark:border-slate-800 flex flex-wrap items-center justify-between gap-2">
          <div className="inline-flex bg-slate-100 dark:bg-slate-800 p-1 rounded-xl text-xs font-bold">
            <button
              type="button"
              onClick={() => setActiveSubTab('separaciones')}
              className={`px-3 py-1.5 rounded-lg cursor-pointer transition-colors ${
                activeSubTab === 'separaciones'
                  ? 'bg-white dark:bg-[#0c121d] text-[#1F1D5C] dark:text-indigo-300 shadow-xs'
                  : 'text-slate-500'
              }`}
            >
              Separaciones ({separacionesList.length})
            </button>
            <button
              type="button"
              onClick={() => setActiveSubTab('cierres')}
              className={`px-3 py-1.5 rounded-lg cursor-pointer transition-colors ${
                activeSubTab === 'cierres'
                  ? 'bg-white dark:bg-[#0c121d] text-[#1F1D5C] dark:text-indigo-300 shadow-xs'
                  : 'text-slate-500'
              }`}
            >
              Cierres y Ventas ({cierresList.length})
            </button>
            <button
              type="button"
              onClick={() => setActiveSubTab('resumen')}
              className={`px-3 py-1.5 rounded-lg cursor-pointer transition-colors ${
                activeSubTab === 'resumen'
                  ? 'bg-white dark:bg-[#0c121d] text-[#1F1D5C] dark:text-indigo-300 shadow-xs'
                  : 'text-slate-500'
              }`}
            >
              Resumen Estrategias y Asesores
            </button>
          </div>

          {(vigenciaFilter || estadoFilter || proyectoFilter || asesorFilter || estrategiaFilter || search) && (
            <button
              type="button"
              onClick={() => {
                setVigenciaFilter('')
                setEstadoFilter('')
                setProyectoFilter('')
                setAsesorFilter('')
                setEstrategiaFilter('')
                setSearch('')
              }}
              className="text-xs font-semibold text-indigo-600 hover:underline cursor-pointer"
            >
              Limpiar filtros
            </button>
          )}
        </div>

        {/* Vista Tab 1: SEPARACIONES */}
        {activeSubTab === 'separaciones' && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 dark:bg-[#0b101b] text-slate-500 font-semibold border-b border-slate-200 dark:border-slate-800">
                <tr>
                  <th className="py-3 px-3">Mes</th>
                  <th className="py-3 px-3">Asesor</th>
                  <th className="py-3 px-3">Proyecto</th>
                  <th className="py-3 px-3">Lote</th>
                  <th className="py-3 px-3">Ingreso</th>
                  <th className="py-3 px-3">Vencimiento</th>
                  <th className="py-3 px-3">Monto</th>
                  <th className="py-3 px-3">Estrategia</th>
                  <th className="py-3 px-3">Estado</th>
                  <th className="py-3 px-3">Origen</th>
                  <th className="py-3 px-3 text-right">Acciones</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
                {separacionesList.map((r) => (
                  <tr key={r.id} className="hover:bg-slate-50/70 dark:hover:bg-slate-800/30">
                    <td className="py-2.5 px-3 font-semibold text-slate-600 dark:text-slate-300 whitespace-nowrap">
                      {r.mes_nombre} {r.anio}
                    </td>
                    <td className="py-2.5 px-3 font-bold text-slate-900 dark:text-white">
                      {r.asesor || '—'}
                    </td>
                    <td className="py-2.5 px-3">{r.proyecto || '—'}</td>
                    <td className="py-2.5 px-3 font-mono font-bold">{r.lote || '—'}</td>
                    <td className="py-2.5 px-3 whitespace-nowrap">{r.fecha_ingreso || '—'}</td>
                    <td className="py-2.5 px-3 whitespace-nowrap">
                      <div className="flex items-center gap-1.5">
                        <span>{r.fecha_vencimiento || '—'}</span>
                        {r.vigencia_status === 'vencida' && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-rose-100 text-rose-700">
                            Vencida
                          </span>
                        )}
                        {r.vigencia_status === 'vigente' && r.fecha_vencimiento && (
                          <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-100 text-emerald-700">
                            Vigente
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="py-2.5 px-3 font-semibold whitespace-nowrap">
                      {r.monto_raw || (r.monto_numerico != null ? `S/ ${r.monto_numerico}` : '—')}
                    </td>
                    <td className="py-2.5 px-3">{r.estrategia || '—'}</td>
                    <td className="py-2.5 px-3">
                      <select
                        value={r.estado || 'SEPARADO'}
                        onChange={(e) => handleQuickEstado(r, e.target.value)}
                        className={`text-[11px] font-bold px-2 py-1 rounded-lg border outline-none cursor-pointer ${getEstadoBadgeStyle(r.estado)}`}
                      >
                        {Array.from(new Set([...ESTADOS_SUGERIDOS, ...(r.estado ? [r.estado] : [])])).map((es) => (
                          <option key={es} value={es}>{es}</option>
                        ))}
                      </select>
                      {r.observaciones && (
                        <div className="text-[10px] text-amber-700 dark:text-amber-300 mt-0.5 max-w-[200px] truncate" title={r.observaciones}>
                          {r.observaciones}
                        </div>
                      )}
                    </td>
                    <td className="py-2.5 px-3">
                      <span
                        className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                          r.origen === 'crm'
                            ? 'bg-indigo-50 text-indigo-700'
                            : 'bg-slate-100 text-slate-600'
                        }`}
                      >
                        {r.origen === 'crm' ? 'CRM' : 'Drive'}
                      </span>
                    </td>
                    <td className="py-2.5 px-3 text-right whitespace-nowrap">
                      <button
                        type="button"
                        onClick={() => handleOpenEdit(r)}
                        className="p-1.5 rounded-lg text-slate-500 hover:text-indigo-600 hover:bg-indigo-50 cursor-pointer"
                        title="Editar"
                      >
                        <Edit2 size={13} />
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDeleteRow(r)}
                        className="p-1.5 rounded-lg text-slate-500 hover:text-rose-600 hover:bg-rose-50 cursor-pointer"
                        title="Eliminar"
                      >
                        <Trash2 size={13} />
                      </button>
                    </td>
                  </tr>
                ))}
                {!loading && separacionesList.length === 0 && (
                  <tr>
                    <td colSpan={11} className="py-10 text-center text-slate-400">
                      No hay separaciones para mostrar con los filtros actuales.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* Vista Tab 2: CIERRES */}
        {activeSubTab === 'cierres' && (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead className="bg-slate-50 dark:bg-[#0b101b] text-slate-500 font-semibold border-b border-slate-200 dark:border-slate-800">
                <tr>
                  <th className="py-3 px-4">Mes</th>
                  <th className="py-3 px-3">Proyecto</th>
                  <th className="py-3 px-3">Lote</th>
                  <th className="py-3 px-3">Estrategia / Fuente</th>
                  <th className="py-3 px-3">Asesor</th>
                  <th className="py-3 px-3">Estado</th>
                  <th className="py-3 px-3">Origen</th>
                  <th className="py-3 px-4 text-right">Acciones</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800/60">
                {cierresList.map((r) => (
                  <tr key={r.id} className="hover:bg-slate-50/70 dark:hover:bg-slate-800/30">
                    <td className="py-2.5 px-4 font-semibold text-slate-600 dark:text-slate-300">
                      {r.mes_nombre} {r.anio}
                    </td>
                    <td className="py-2.5 px-3 font-bold text-slate-900 dark:text-white">{r.proyecto || '—'}</td>
                    <td className="py-2.5 px-3 font-mono font-bold">{r.lote || '—'}</td>
                    <td className="py-2.5 px-3">{r.estrategia || '—'}</td>
                    <td className="py-2.5 px-3">{r.asesor || '—'}</td>
                    <td className="py-2.5 px-3">
                      <span className={`px-2 py-0.5 rounded-md text-[11px] font-bold border ${getEstadoBadgeStyle(r.estado)}`}>
                        {r.estado || 'VENDIDO'}
                      </span>
                    </td>
                    <td className="py-2.5 px-3">
                      <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-slate-100 text-slate-600">
                        {r.origen === 'crm' ? 'CRM' : 'Drive'}
                      </span>
                    </td>
                    <td className="py-2.5 px-4 text-right whitespace-nowrap">
                      <button
                        type="button"
                        onClick={() => handleOpenEdit(r)}
                        className="p-1.5 rounded-lg text-slate-500 hover:text-indigo-600 hover:bg-indigo-50 cursor-pointer"
                      >
                        <Edit2 size={13} />
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDeleteRow(r)}
                        className="p-1.5 rounded-lg text-slate-500 hover:text-rose-600 hover:bg-rose-50 cursor-pointer"
                      >
                        <Trash2 size={13} />
                      </button>
                    </td>
                  </tr>
                ))}
                {!loading && cierresList.length === 0 && (
                  <tr>
                    <td colSpan={8} className="py-10 text-center text-slate-400">
                      No hay cierres registrados para este filtro.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}

        {/* Vista Tab 3: RESUMEN ESTRATEGIAS Y ASESORES */}
        {activeSubTab === 'resumen' && (
          <div className="p-5 grid grid-cols-1 lg:grid-cols-3 gap-5">
            <div className="border border-slate-200 dark:border-slate-800 rounded-xl p-4 space-y-2">
              <h3 className="text-xs font-bold uppercase text-slate-500 flex items-center gap-1.5">
                <Layers size={14} className="text-indigo-500" />
                Separaciones por Estrategia
              </h3>
              <div className="divide-y divide-slate-100 dark:divide-slate-800 text-xs">
                {(resumen.resumen_estrategia_separaciones || []).map((e) => (
                  <div key={e.estrategia} className="py-2 flex items-center justify-between">
                    <span className="font-medium">{e.estrategia}</span>
                    <span className="font-bold text-indigo-600">{e.total}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="border border-slate-200 dark:border-slate-800 rounded-xl p-4 space-y-2">
              <h3 className="text-xs font-bold uppercase text-slate-500 flex items-center gap-1.5">
                <CheckCircle2 size={14} className="text-emerald-500" />
                Cierres / Ventas por Estrategia
              </h3>
              <div className="divide-y divide-slate-100 dark:divide-slate-800 text-xs">
                {(resumen.resumen_estrategia_cierres || []).map((e) => (
                  <div key={e.estrategia} className="py-2 flex items-center justify-between">
                    <span className="font-medium">{e.estrategia}</span>
                    <span className="font-bold text-emerald-600">{e.total}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="border border-slate-200 dark:border-slate-800 rounded-xl p-4 space-y-2">
              <h3 className="text-xs font-bold uppercase text-slate-500">
                Separaciones por Asesor
              </h3>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="text-slate-400 border-b border-slate-100 dark:border-slate-800">
                    <tr>
                      <th className="py-1.5">Asesor</th>
                      <th className="py-1.5 text-center">Tot.</th>
                      <th className="py-1.5 text-center">Vend.</th>
                      <th className="py-1.5 text-center">Vig.</th>
                      <th className="py-1.5 text-center">Venc.</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                    {(resumen.resumen_asesores || []).map((a) => (
                      <tr key={a.asesor}>
                        <td className="py-1.5 font-semibold">{a.asesor}</td>
                        <td className="py-1.5 text-center font-bold">{a.total}</td>
                        <td className="py-1.5 text-center text-emerald-600 font-bold">{a.vendidas}</td>
                        <td className="py-1.5 text-center text-sky-600 font-bold">{a.vigentes}</td>
                        <td className="py-1.5 text-center text-rose-600 font-bold">{a.vencidas}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ─────────────────────────────────────────────────────────────
          MODAL GIT DIFF (REVISIÓN Y APROBACIÓN DE CAMBIOS DE DRIVE)
          ───────────────────────────────────────────────────────────── */}
      {showDiffModal && pendingRevision && (
        <div className="fixed inset-0 z-50 bg-slate-950/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white dark:bg-[#121a29] rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between gap-3">
              <div>
                <h3 className="text-base font-bold flex items-center gap-2">
                  <GitPullRequest size={18} className="text-indigo-600" />
                  Comparativo Git: {pendingRevision.source === 'excel_upload' ? 'Archivo Excel' : 'Google Drive'} vs. Servidor CRM (Rev #{pendingRevision.revision_number})
                </h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  Marca o desmarca qué cambios deseas fusionar al servidor. Los registros creados en el CRM no se borran.
                </p>
              </div>
              <button type="button" onClick={() => setShowDiffModal(false)} className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800">
                <X size={18} />
              </button>
            </div>

            <div className="px-5 py-2.5 border-b border-slate-100 dark:border-slate-800 flex flex-wrap items-center justify-between gap-2 bg-slate-50 dark:bg-[#0e1522] text-xs">
              <div className="flex items-center gap-1.5">
                {[
                  { id: 'todos', label: `Todos (${(pendingRevision.diff_json || []).length})` },
                  { id: 'added', label: `+ Nuevos (${pendingRevision.summary_json?.added ?? 0})` },
                  { id: 'modified', label: `~ Modificados (${pendingRevision.summary_json?.modified ?? 0})` },
                  { id: 'removed', label: `- Quitados (${pendingRevision.summary_json?.removed ?? 0})` },
                ].map((f) => (
                  <button
                    key={f.id}
                    type="button"
                    onClick={() => setDiffFilter(f.id)}
                    className={`px-2.5 py-1 rounded-lg font-semibold cursor-pointer ${
                      diffFilter === f.id
                        ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900'
                        : 'text-slate-600 dark:text-slate-300 hover:bg-slate-200/60'
                    }`}
                  >
                    {f.label}
                  </button>
                ))}
              </div>

              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={() => setSelectedDiffKeys(new Set((pendingRevision.diff_json || []).map((c) => c.sync_key)))}
                  className="font-semibold text-indigo-600 hover:underline cursor-pointer"
                >
                  Seleccionar todo
                </button>
                <button
                  type="button"
                  onClick={() => setSelectedDiffKeys(new Set())}
                  className="font-semibold text-slate-500 hover:underline cursor-pointer"
                >
                  Limpiar
                </button>
              </div>
            </div>

            <div className="flex-1 overflow-y-auto p-5 space-y-2.5">
              {diffChanges.map((item) => {
                const checked = selectedDiffKeys.has(item.sync_key)
                const isAdd = item.change_type === 'added'
                const isMod = item.change_type === 'modified'
                return (
                  <label
                    key={item.sync_key}
                    className={`block p-3 rounded-xl border cursor-pointer transition-all ${
                      isAdd
                        ? 'border-emerald-200 bg-emerald-50/40 dark:bg-emerald-950/20'
                        : isMod
                          ? 'border-amber-200 bg-amber-50/40 dark:bg-amber-950/20'
                          : 'border-rose-200 bg-rose-50/40 dark:bg-rose-950/20'
                    }`}
                  >
                    <div className="flex items-start gap-3">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => {
                          const next = new Set(selectedDiffKeys)
                          if (next.has(item.sync_key)) next.delete(item.sync_key)
                          else next.add(item.sync_key)
                          setSelectedDiffKeys(next)
                        }}
                        className="mt-1"
                      />
                      <div className="flex-1 text-xs space-y-1.5">
                        <div className="flex items-center justify-between gap-2">
                          <span className="font-bold text-slate-900 dark:text-white">{item.label}</span>
                          <span
                            className={`text-[10px] font-extrabold uppercase px-2 py-0.5 rounded ${
                              isAdd
                                ? 'bg-emerald-100 text-emerald-800'
                                : isMod
                                  ? 'bg-amber-200 text-amber-900'
                                  : 'bg-rose-100 text-rose-800'
                            }`}
                          >
                            {isAdd ? '+ Nuevo en Drive' : isMod ? '~ Modificado' : '- Eliminado en Drive'}
                          </span>
                        </div>

                        {isAdd && item.after && (
                          <div className="text-[11px] text-emerald-900 dark:text-emerald-200 font-mono bg-white/80 dark:bg-slate-900/60 p-2 rounded-lg border border-emerald-200/70">
                            {item.after.tipo === 'separacion'
                              ? `+ Asesor: ${item.after.asesor || '—'} | Proyecto: ${item.after.proyecto || '—'} | Lote: ${item.after.lote || '—'} | Ing: ${item.after.fecha_ingreso || '—'} | Venc: ${item.after.fecha_vencimiento || '—'} | Monto: ${item.after.monto_raw || '—'} | Estado: ${item.after.estado || '—'}`
                              : `+ Cierre: ${item.after.proyecto || '—'} | Lote: ${item.after.lote || '—'} | Estrategia: ${item.after.estrategia || '—'}`}
                          </div>
                        )}

                        {isMod && (item.changed_fields || []).length > 0 && (
                          <div className="space-y-1 font-mono text-[11px]">
                            {item.changed_fields.map((cf) => (
                              <div key={cf.field} className="bg-white/90 dark:bg-slate-900/60 p-1.5 rounded border border-amber-200/60 flex flex-wrap items-center gap-2">
                                <span className="font-sans font-bold text-slate-600 dark:text-slate-300">{cf.label}:</span>
                                <span className="px-1.5 py-0.5 rounded bg-rose-100 text-rose-800 line-through">
                                  - {cf.before || 'vacío'}
                                </span>
                                <span className="px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800 font-bold">
                                  + {cf.after || 'vacío'}
                                </span>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    </div>
                  </label>
                )
              })}
            </div>

            <div className="px-5 py-4 border-t border-slate-200 dark:border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-slate-50 dark:bg-[#0e1522]">
              <input
                type="text"
                value={commitMsg}
                onChange={(e) => setCommitMsg(e.target.value)}
                placeholder="Nota o comentario de esta versión..."
                className="flex-1 text-xs px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-[#0c121d]"
              />
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={handleRejectDiff}
                  disabled={approving}
                  className="px-3 py-2 rounded-xl text-xs font-semibold text-rose-700 bg-rose-50 hover:bg-rose-100 border border-rose-200 cursor-pointer"
                >
                  Descartar
                </button>
                <button
                  type="button"
                  onClick={handleApproveDiff}
                  disabled={approving}
                  className="px-4 py-2 rounded-xl text-xs font-bold text-white bg-emerald-600 hover:bg-emerald-700 cursor-pointer inline-flex items-center gap-1.5"
                >
                  <Check size={14} />
                  <span>{approving ? 'Guardando…' : `Aprobar y guardar (${selectedDiffKeys.size})`}</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ─────────────────────────────────────────────────────────────
          MODAL HISTORIAL DE VERSIONES (GIT LOG)
          ───────────────────────────────────────────────────────────── */}
      {showHistoryModal && (
        <div className="fixed inset-0 z-50 bg-slate-950/60 backdrop-blur-xs flex items-center justify-center p-4">
          <div className="bg-white dark:bg-[#121a29] rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl w-full max-w-3xl max-h-[85vh] flex flex-col overflow-hidden">
            <div className="px-5 py-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
              <h3 className="text-base font-bold flex items-center gap-2">
                <GitCommit size={18} className="text-purple-600" />
                Historial de Versiones (Commits)
              </h3>
              <button type="button" onClick={() => setShowHistoryModal(false)} className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800">
                <X size={18} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-5 space-y-3">
              {loadingHistory ? (
                <p className="text-xs text-slate-400 text-center py-6">Cargando versiones…</p>
              ) : revisions.length === 0 ? (
                <p className="text-xs text-slate-400 text-center py-6">Aún no hay revisiones registradas.</p>
              ) : (
                revisions.map((rev) => {
                  const open = expandedRevId === rev.id
                  return (
                    <div key={rev.id} className="border border-slate-200 dark:border-slate-800 rounded-xl p-3 text-xs space-y-2">
                      <div
                        className="flex items-start justify-between gap-2 cursor-pointer"
                        onClick={() => setExpandedRevId(open ? null : rev.id)}
                      >
                        <div className="space-y-0.5">
                          <div className="flex items-center gap-2 flex-wrap">
                            <span className="font-mono font-bold text-purple-600">v{rev.revision_number}</span>
                            <span className="font-bold text-slate-900 dark:text-white">{rev.message || 'Sin descripción'}</span>
                            <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-slate-100 dark:bg-slate-800">
                              {rev.status}
                            </span>
                          </div>
                          <div className="text-[11px] text-slate-500">
                            {rev.reviewed_by_name || rev.created_by_name || 'Admin'} · {formatDateTimeLima(rev.reviewed_at || rev.created_at)}
                            {' · '}+{rev.summary_json?.added ?? 0} / ~{rev.summary_json?.modified ?? 0} / -{rev.summary_json?.removed ?? 0}
                          </div>
                        </div>
                        {open ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
                      </div>

                      {open && (
                        <div className="pt-2 border-t border-slate-100 dark:border-slate-800 space-y-1 max-h-56 overflow-y-auto font-mono text-[11px]">
                          {(rev.diff_json || []).slice(0, 50).map((d, i) => (
                            <div key={i} className="text-slate-600 dark:text-slate-300">
                              [{d.change_type}] {d.label}
                            </div>
                          ))}
                          {(rev.diff_json || []).length > 50 && (
                            <div className="text-slate-400">... y {(rev.diff_json || []).length - 50} más</div>
                          )}
                        </div>
                      )}
                    </div>
                  )
                })
              )}
            </div>
          </div>
        </div>
      )}

      {/* ─────────────────────────────────────────────────────────────
          MODAL CREAR / EDITAR REGISTRO EN SERVIDOR
          ───────────────────────────────────────────────────────────── */}
      {showFormModal && (
        <div className="fixed inset-0 z-50 bg-slate-950/60 backdrop-blur-xs flex items-center justify-center p-4">
          <form
            onSubmit={handleSaveForm}
            className="bg-white dark:bg-[#121a29] rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl w-full max-w-xl p-5 space-y-4"
          >
            <div className="flex items-center justify-between border-b border-slate-100 dark:border-slate-800 pb-3">
              <h3 className="text-base font-bold">
                {editingRow ? 'Editar Registro en Servidor' : 'Nuevo Registro'}
              </h3>
              <button type="button" onClick={() => setShowFormModal(false)} className="p-1 rounded-lg hover:bg-slate-100">
                <X size={18} />
              </button>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
              <div>
                <label className="block font-semibold mb-1">Tipo</label>
                <select
                  value={formState.tipo}
                  onChange={(e) => setFormState((p) => ({ ...p, tipo: e.target.value }))}
                  className="w-full px-2.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900"
                >
                  <option value="separacion">Separación</option>
                  <option value="cierre">Cierre / Venta</option>
                </select>
              </div>
              <div>
                <label className="block font-semibold mb-1">Año</label>
                <input
                  type="number"
                  value={formState.anio}
                  onChange={(e) => setFormState((p) => ({ ...p, anio: e.target.value }))}
                  className="w-full px-2.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900"
                />
              </div>
              <div>
                <label className="block font-semibold mb-1">Mes</label>
                <select
                  value={formState.mes}
                  onChange={(e) => setFormState((p) => ({ ...p, mes: Number(e.target.value) }))}
                  className="w-full px-2.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900"
                >
                  {MONTHS.map((m) => (
                    <option key={m.num} value={m.num}>{m.label}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block font-semibold mb-1">Asesor</label>
                <input
                  type="text"
                  value={formState.asesor}
                  onChange={(e) => setFormState((p) => ({ ...p, asesor: e.target.value }))}
                  placeholder="Ej: FABIOLA"
                  className="w-full px-2.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900"
                />
              </div>
              <div>
                <label className="block font-semibold mb-1">Proyecto *</label>
                <input
                  type="text"
                  required
                  value={formState.proyecto}
                  onChange={(e) => setFormState((p) => ({ ...p, proyecto: e.target.value }))}
                  placeholder="Ej: PUERTO PALMERAS"
                  className="w-full px-2.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900"
                />
              </div>
              <div>
                <label className="block font-semibold mb-1">Lote *</label>
                <input
                  type="text"
                  required
                  value={formState.lote}
                  onChange={(e) => setFormState((p) => ({ ...p, lote: e.target.value }))}
                  placeholder="Ej: A1"
                  className="w-full px-2.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900"
                />
              </div>

              <div>
                <label className="block font-semibold mb-1">Fecha Ingreso (DD/MM/YYYY)</label>
                <input
                  type="text"
                  value={formState.fecha_ingreso}
                  onChange={(e) => setFormState((p) => ({ ...p, fecha_ingreso: e.target.value }))}
                  placeholder="24/10/2026"
                  className="w-full px-2.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900"
                />
              </div>
              <div>
                <label className="block font-semibold mb-1">Fecha Vencimiento</label>
                <input
                  type="text"
                  value={formState.fecha_vencimiento}
                  onChange={(e) => setFormState((p) => ({ ...p, fecha_vencimiento: e.target.value }))}
                  placeholder="07/11/2026"
                  className="w-full px-2.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900"
                />
              </div>
              <div>
                <label className="block font-semibold mb-1">Monto (ej. S/500.00)</label>
                <input
                  type="text"
                  value={formState.monto_raw}
                  onChange={(e) => setFormState((p) => ({ ...p, monto_raw: e.target.value }))}
                  placeholder="S/500.00"
                  className="w-full px-2.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900"
                />
              </div>

              <div>
                <label className="block font-semibold mb-1">Estrategia</label>
                <input
                  type="text"
                  value={formState.estrategia}
                  onChange={(e) => setFormState((p) => ({ ...p, estrategia: e.target.value }))}
                  placeholder="LEAD WEDO / REFERIDOS / FIA"
                  className="w-full px-2.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900"
                />
              </div>
              <div className="sm:col-span-2">
                <label className="block font-semibold mb-1">Estado</label>
                <select
                  value={formState.estado}
                  onChange={(e) => setFormState((p) => ({ ...p, estado: e.target.value }))}
                  className="w-full px-2.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900"
                >
                  {ESTADOS_SUGERIDOS.map((es) => (
                    <option key={es} value={es}>{es}</option>
                  ))}
                </select>
              </div>

              <div className="sm:col-span-3">
                <label className="block font-semibold mb-1">Observaciones</label>
                <textarea
                  rows={2}
                  value={formState.observaciones}
                  onChange={(e) => setFormState((p) => ({ ...p, observaciones: e.target.value }))}
                  className="w-full px-2.5 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900"
                />
              </div>
            </div>

            <div className="flex justify-end gap-2 pt-2 border-t border-slate-100 dark:border-slate-800">
              <button
                type="button"
                onClick={() => setShowFormModal(false)}
                className="px-3 py-2 rounded-xl text-xs font-semibold text-slate-600 hover:bg-slate-100 cursor-pointer"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={savingForm}
                className="px-4 py-2 rounded-xl text-xs font-bold text-white bg-[#1F1D5C] hover:brightness-110 cursor-pointer"
              >
                {savingForm ? 'Guardando…' : 'Guardar en Servidor'}
              </button>
            </div>
          </form>
        </div>
      )}

      {/* ─────────────────────────────────────────────────────────────
          MODAL CONFIGURAR ENLACE DE GOOGLE DRIVE
          ───────────────────────────────────────────────────────────── */}
      {showDriveCfgModal && (
        <div className="fixed inset-0 z-50 bg-slate-950/60 backdrop-blur-xs flex items-center justify-center p-4">
          <form
            onSubmit={handleSaveDriveCfg}
            className="bg-white dark:bg-[#121a29] rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl w-full max-w-lg p-5 space-y-4"
          >
            <div className="flex items-center justify-between">
              <h3 className="text-base font-bold">Enlace de Google Drive Monitoreado</h3>
              <button type="button" onClick={() => setShowDriveCfgModal(false)} className="p-1 rounded-lg hover:bg-slate-100">
                <X size={18} />
              </button>
            </div>
            <div className="text-xs space-y-1.5">
              <label className="block font-semibold">URL de Google Sheets (debe tener lectura pública)</label>
              <input
                type="url"
                required
                value={driveUrlDraft}
                onChange={(e) => setDriveUrlDraft(e.target.value)}
                className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-900 font-mono text-[11px]"
              />
            </div>
            <div className="flex justify-end gap-2">
              <button type="button" onClick={() => setShowDriveCfgModal(false)} className="px-3 py-2 rounded-xl text-xs font-semibold text-slate-600">
                Cancelar
              </button>
              <button type="submit" disabled={savingCfg} className="px-4 py-2 rounded-xl text-xs font-bold text-white bg-indigo-600 cursor-pointer">
                {savingCfg ? 'Guardando…' : 'Guardar enlace'}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  )
}
