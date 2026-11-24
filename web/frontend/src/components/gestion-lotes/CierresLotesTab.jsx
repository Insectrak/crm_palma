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
  AlertTriangle,
  Settings,
  X,
  ExternalLink,
  Layers,
} from 'lucide-react'
import api from '@/lib/api'
import {
  DriveConfigModal,
  GitDiffModal,
  GitRevisionsModal,
  formatDateTimeLima,
} from '@/components/gestion-lotes/GitSyncModals'

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

function formatMoney(val, moneda = 'SOLES') {
  if (val === null || val === undefined || val === '') return '—'
  const num = Number(val)
  if (Number.isNaN(num)) return String(val)
  const prefix = String(moneda).toUpperCase().includes('DOLAR') ? '$ ' : 'S/ '
  return `${prefix}${num.toLocaleString('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`
}

export default function CierresLotesTab() {
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
  const [selectedPeriodo, setSelectedPeriodo] = useState('')
  const [activeView, setActiveView] = useState('tabla') // 'tabla' | 'resumen'
  const [proyectoFilter, setProyectoFilter] = useState('')
  const [asesorFilter, setAsesorFilter] = useState('')
  const [monedaFilter, setMonedaFilter] = useState('')
  const [estrategiaFilter, setEstrategiaFilter] = useState('')
  const [search, setSearch] = useState('')

  // Modales Git & Drive
  const [showDiffModal, setShowDiffModal] = useState(false)
  const [diffFilter, setDiffFilter] = useState('todos')
  const [selectedDiffKeys, setSelectedDiffKeys] = useState(new Set())
  const [commitMsg, setCommitMsg] = useState('')
  const [approving, setApproving] = useState(false)

  const [showHistoryModal, setShowHistoryModal] = useState(false)
  const [revisions, setRevisions] = useState([])
  const [loadingHistory, setLoadingHistory] = useState(false)
  const [expandedRevId, setExpandedRevId] = useState(null)

  const [showDriveCfgModal, setShowDriveCfgModal] = useState(false)
  const [driveUrlDraft, setDriveUrlDraft] = useState('')
  const [savingCfg, setSavingCfg] = useState(false)

  // Form Crear / Editar cierre
  const [showFormModal, setShowFormModal] = useState(false)
  const [editingRow, setEditingRow] = useState(null)
  const [savingForm, setSavingForm] = useState(false)
  const [formState, setFormState] = useState({
    anio: 2026,
    mes: 10,
    asesor: '',
    proyecto: '',
    lote: '',
    cliente_nombre: '',
    distrito: '',
    fecha_ingreso_inicial: '',
    monto_total: '',
    moneda: 'SOLES',
    pct_inicial_raw: '',
    cantidad_inicial: '',
    tipo_cambio: '3.5',
    estrategia: '',
    area: '',
    edad: '',
    observaciones: '',
  })

  const showToastMsg = (text, kind = 'success') => {
    setToast({ text, kind })
    setTimeout(() => setToast(null), 4500)
  }

  const fetchAll = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const metaRes = await api.get('/api/cierres-lotes/meta')
      const m = metaRes.data
      setMeta(m)
      setDriveUrlDraft(m?.drive_config?.sheet_url || '')

      const params = new URLSearchParams()
      if (selectedPeriodo) {
        const [y, mm] = selectedPeriodo.split('-')
        if (y) params.append('anio', y)
        if (mm) params.append('mes', mm)
      }
      if (proyectoFilter) params.append('proyecto', proyectoFilter)
      if (asesorFilter) params.append('asesor', asesorFilter)
      if (monedaFilter) params.append('moneda', monedaFilter)
      if (estrategiaFilter) params.append('estrategia', estrategiaFilter)
      if (search.trim()) params.append('search', search.trim())

      const listRes = await api.get(`/api/cierres-lotes?${params.toString()}`)
      setItems(listRes.data?.items || [])
      setResumen(listRes.data?.resumen || {})
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo cargar el módulo de Cierres.')
    } finally {
      setLoading(false)
    }
  }, [selectedPeriodo, proyectoFilter, asesorFilter, monedaFilter, estrategiaFilter, search])

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
      const res = await api.post('/api/cierres-lotes/drive/check')
      await fetchAll()
      if (res.data?.has_changes && res.data?.pending_revision) {
        showToastMsg('Se detectaron cambios en Drive listos para revisar.', 'info')
        if (openModalIfChanges) openDiffModalWithRev(res.data.pending_revision)
      } else {
        showToastMsg('Drive verificado: no hay cambios respecto al servidor.')
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al verificar Google Drive de Cierres.')
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
      const res = await api.post('/api/cierres-lotes/upload', fd, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      await fetchAll()
      if (res.data?.has_changes && res.data?.pending_revision) {
        showToastMsg(
          `Excel leído (${res.data.parsed_rows} cierres). Revisa el comparativo y aprueba los cambios.`,
          'info',
        )
        openDiffModalWithRev(res.data.pending_revision)
      } else {
        showToastMsg(`Excel comparado (${res.data.parsed_rows} cierres): no hay diferencias respecto al servidor.`)
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo procesar el archivo Excel de Cierres.')
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
      const res = await api.post(`/api/cierres-lotes/revisions/${pendingRevision.id}/approve`, {
        selected_keys: Array.from(selectedDiffKeys),
        message: commitMsg.trim() || undefined,
      })
      setShowDiffModal(false)
      const c = res.data?.applied_counts || {}
      showToastMsg(`Cierres aprobados: +${c.added || 0} nuevos, ~${c.modified || 0} modificados, -${c.removed || 0} quitados.`)
      await fetchAll()
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudieron aprobar los cambios de Cierres.')
    } finally {
      setApproving(false)
    }
  }

  const handleRejectDiff = async () => {
    if (!pendingRevision) return
    setApproving(true)
    try {
      await api.post(`/api/cierres-lotes/revisions/${pendingRevision.id}/reject`, {
        reason: 'Descartado manualmente por el administrador',
      })
      setShowDiffModal(false)
      showToastMsg('Revisión descartada. Prevalece el respaldo del servidor.')
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
      const res = await api.get('/api/cierres-lotes/revisions?limit=60')
      setRevisions(res.data?.items || [])
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo cargar el historial de Cierres.')
    } finally {
      setLoadingHistory(false)
    }
  }

  const handleOpenCreate = () => {
    let defaultAnio = 2026
    let defaultMes = new Date().getMonth() + 1
    if (selectedPeriodo) {
      const [y, m] = selectedPeriodo.split('-')
      if (y) defaultAnio = Number(y)
      if (m) defaultMes = Number(m)
    }
    setEditingRow(null)
    setFormState({
      anio: defaultAnio,
      mes: defaultMes,
      asesor: '',
      proyecto: '',
      lote: '',
      cliente_nombre: '',
      distrito: '',
      fecha_ingreso_inicial: '',
      monto_total: '',
      moneda: 'SOLES',
      pct_inicial_raw: '',
      cantidad_inicial: '',
      tipo_cambio: '3.5',
      estrategia: '',
      area: '',
      edad: '',
      observaciones: '',
    })
    setShowFormModal(true)
  }

  const handleOpenEdit = (row) => {
    setEditingRow(row)
    setFormState({
      anio: row.anio || 2026,
      mes: row.mes || 10,
      asesor: row.asesor || '',
      proyecto: row.proyecto || '',
      lote: row.lote || '',
      cliente_nombre: row.cliente_nombre || '',
      distrito: row.distrito || '',
      fecha_ingreso_inicial: row.fecha_ingreso_inicial || '',
      monto_total: row.monto_total != null ? String(row.monto_total) : '',
      moneda: row.moneda || 'SOLES',
      pct_inicial_raw: row.pct_inicial_raw || '',
      cantidad_inicial: row.cantidad_inicial != null ? String(row.cantidad_inicial) : '',
      tipo_cambio: row.tipo_cambio != null ? String(row.tipo_cambio) : '',
      estrategia: row.estrategia || '',
      area: row.area || '',
      edad: row.edad != null ? String(row.edad) : '',
      observaciones: row.observaciones || '',
    })
    setShowFormModal(true)
  }

  const handleSaveForm = async (e) => {
    e.preventDefault()
    setSavingForm(true)
    setError(null)
    try {
      const payload = {
        anio: Number(formState.anio),
        mes: Number(formState.mes),
        asesor: formState.asesor.trim() || null,
        proyecto: formState.proyecto.trim(),
        lote: formState.lote.trim(),
        cliente_nombre: formState.cliente_nombre.trim(),
        distrito: formState.distrito.trim() || null,
        fecha_ingreso_inicial: formState.fecha_ingreso_inicial.trim() || null,
        monto_total: formState.monto_total !== '' ? Number(formState.monto_total) : null,
        moneda: formState.moneda,
        pct_inicial_raw: formState.pct_inicial_raw.trim() || null,
        cantidad_inicial: formState.cantidad_inicial !== '' ? Number(formState.cantidad_inicial) : null,
        tipo_cambio: formState.tipo_cambio !== '' ? Number(formState.tipo_cambio) : null,
        estrategia: formState.estrategia.trim() || null,
        area: formState.area.trim() || null,
        edad: formState.edad !== '' ? parseInt(formState.edad, 10) : null,
        observaciones: formState.observaciones.trim() || null,
      }
      if (editingRow) {
        await api.patch(`/api/cierres-lotes/${editingRow.id}`, payload)
        showToastMsg('Cierre actualizado y guardado en el historial.')
      } else {
        await api.post('/api/cierres-lotes', payload)
        showToastMsg('Nuevo cierre creado y respaldado en el servidor.')
      }
      setShowFormModal(false)
      await fetchAll()
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo guardar el cierre.')
    } finally {
      setSavingForm(false)
    }
  }

  const handleDeleteRow = async (row) => {
    if (!window.confirm(`¿Eliminar cierre de "${row.cliente_nombre || row.lote}" (${row.proyecto} ${row.lote})? Quedará registrado en Versiones.`)) {
      return
    }
    try {
      await api.delete(`/api/cierres-lotes/${row.id}`)
      showToastMsg('Cierre eliminado (registrado en historial).')
      await fetchAll()
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al eliminar cierre.')
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
      const res = await api.get(`/api/cierres-lotes/export?${params.toString()}`, { responseType: 'blob' })
      const url = window.URL.createObjectURL(new Blob([res.data]))
      const link = document.createElement('a')
      link.href = url
      link.setAttribute('download', `cierres_lotes_${selectedPeriodo || '2026'}.xlsx`)
      document.body.appendChild(link)
      link.click()
      link.remove()
      window.URL.revokeObjectURL(url)
    } catch {
      setError('No se pudo exportar el archivo Excel de Cierres.')
    }
  }

  const handleSaveDriveCfg = async (e) => {
    e.preventDefault()
    setSavingCfg(true)
    try {
      await api.put('/api/cierres-lotes/drive/config', { sheet_url: driveUrlDraft })
      setShowDriveCfgModal(false)
      showToastMsg('Enlace de Google Drive para Cierres actualizado.')
      await fetchAll()
    } catch (err) {
      setError(err.response?.data?.detail || 'No se pudo actualizar la URL de Drive.')
    } finally {
      setSavingCfg(false)
    }
  }

  const diffChanges = useMemo(() => {
    const all = pendingRevision?.diff_json || []
    if (diffFilter === 'todos') return all
    return all.filter((c) => c.change_type === diffFilter)
  }, [pendingRevision, diffFilter])

  const catalogos = meta?.catalogos || {}
  const periodos = meta?.periodos || []

  return (
    <div className="space-y-6 animate-fadeIn text-slate-900 dark:text-slate-100">
      <input
        ref={fileInputRef}
        type="file"
        accept=".xlsx,.xlsm,.csv"
        className="hidden"
        onChange={handleExcelFileSelected}
      />

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

      {/* Barra de Control */}
      <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm flex flex-col xl:flex-row xl:items-center justify-between gap-4">
        <div className="flex items-start gap-3">
          <span className="p-2.5 bg-emerald-500/10 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300 rounded-xl border border-emerald-500/20">
            <FileSpreadsheet size={22} />
          </span>
          <div>
            <h2 className="text-lg font-bold text-slate-900 dark:text-white">
              Cuadro de Cierre de Ventas (PDR-FO-GC-17)
            </h2>
            <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500 dark:text-slate-400 mt-1">
              <span className="inline-flex items-center gap-1">
                <GitBranch size={12} className="text-emerald-600" />
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
            <span>{checkingDrive ? 'Comparando Drive…' : 'Verificar Drive'}</span>
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
            onClick={handleOpenCreate}
            className="inline-flex items-center gap-1.5 px-3 py-2 rounded-xl text-xs font-bold bg-emerald-600 hover:bg-emerald-700 text-white shadow-sm cursor-pointer"
          >
            <Plus size={14} />
            <span>Nuevo cierre</span>
          </button>

          <button
            type="button"
            onClick={() => setShowDriveCfgModal(true)}
            className="p-2 rounded-xl bg-white dark:bg-[#0f1624] border border-slate-200 dark:border-slate-700 text-slate-500 hover:text-slate-800 dark:hover:text-white cursor-pointer"
            title="Configurar enlace de Google Drive de Cierres"
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
          <button type="button" onClick={() => setError(null)} className="text-xs font-bold underline cursor-pointer">
            Cerrar
          </button>
        </div>
      )}

      {/* Banner: Base vacía */}
      {!loading && (meta?.total_registros || 0) === 0 && !pendingRevision && (
        <div className="bg-gradient-to-r from-indigo-50 via-white to-emerald-50 dark:from-indigo-950/40 dark:via-[#121a29] dark:to-emerald-950/30 border-2 border-indigo-200 dark:border-indigo-800 rounded-2xl p-5 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div className="flex items-start gap-3">
            <GitPullRequest size={22} className="text-[#1F1D5C] dark:text-indigo-400 shrink-0 mt-0.5" />
            <div>
              <h3 className="text-sm font-bold text-slate-900 dark:text-white">
                La tabla de Cierres aún no tiene registros en el servidor
              </h3>
              <p className="text-xs text-slate-600 dark:text-slate-300 mt-0.5">
                Puedes <strong>Subir Excel (.xlsx / .csv)</strong> descargado desde Drive para previsualizar el comparativo e importar todos los cierres, o usar <strong>Verificar Drive</strong> si el enlace tiene acceso público.
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploadingExcel}
              className="px-4 py-2 rounded-xl text-xs font-bold bg-[#1F1D5C] hover:bg-[#161444] text-white cursor-pointer"
            >
              Subir Excel ahora
            </button>
          </div>
        </div>
      )}

      {/* Banner: Diff pendiente */}
      {pendingRevision && (
        <div className="bg-amber-50 dark:bg-amber-950/30 border-2 border-amber-300 dark:border-amber-700 rounded-2xl p-4 flex flex-col md:flex-row md:items-center justify-between gap-3">
          <div className="flex items-start gap-3">
            <GitPullRequest size={20} className="text-amber-600 shrink-0 mt-0.5" />
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h3 className="text-sm font-bold text-amber-950 dark:text-amber-100">
                  Cambios pendientes ({pendingRevision.source === 'excel_upload' ? 'Archivo Excel' : 'Google Drive'} · Rev #{pendingRevision.revision_number})
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
                {pendingRevision.message} — Revisa el comparativo y aprueba qué registros guardar en el servidor.
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

      {/* KPIs */}
      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">Total Cierres</span>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="text-3xl font-extrabold text-slate-900 dark:text-white">
              {resumen.total_cierres ?? 0}
            </span>
            <span className="text-xs text-slate-500">ventas cerradas</span>
          </div>
          <p className="mt-2 text-[11px] text-slate-500">
            Promedio Inicial: <strong className="text-slate-700 dark:text-slate-200">{resumen.promedio_pct_inicial ?? 0}%</strong>
          </p>
        </div>

        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">Ventas en Soles (PEN)</span>
          <div className="mt-2 text-2xl font-extrabold text-emerald-700 dark:text-emerald-400">
            S/ {Number(resumen.monto_total_soles || 0).toLocaleString('es-PE', { minimumFractionDigits: 2 })}
          </div>
          <p className="mt-2 text-[11px] text-slate-500">
            Inicial recaudada: <strong>S/ {Number(resumen.inicial_total_soles || 0).toLocaleString('es-PE', { minimumFractionDigits: 2 })}</strong>
          </p>
        </div>

        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">Ventas en Dólares (USD)</span>
          <div className="mt-2 text-2xl font-extrabold text-indigo-700 dark:text-indigo-400">
            $ {Number(resumen.monto_total_dolares || 0).toLocaleString('es-PE', { minimumFractionDigits: 2 })}
          </div>
          <p className="mt-2 text-[11px] text-slate-500">
            Inicial recaudada: <strong>$ {Number(resumen.inicial_total_dolares || 0).toLocaleString('es-PE', { minimumFractionDigits: 2 })}</strong>
          </p>
        </div>

        <div className="bg-white dark:bg-[#121a29] p-5 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm">
          <span className="text-xs font-bold text-slate-500 uppercase tracking-wider">Top Estrategias</span>
          <div className="mt-2 space-y-1 text-xs">
            {(resumen.resumen_estrategias || []).slice(0, 3).map((e) => (
              <div key={e.estrategia} className="flex items-center justify-between">
                <span className="text-slate-600 dark:text-slate-300 truncate max-w-[170px]">{e.estrategia}</span>
                <span className="font-bold text-slate-900 dark:text-white">{e.total}</span>
              </div>
            ))}
            {(resumen.resumen_estrategias || []).length === 0 && <span className="text-slate-400">Sin datos</span>}
          </div>
        </div>
      </div>

      {/* Filtros + Sub-vista */}
      <div className="bg-white dark:bg-[#121a29] p-4 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm space-y-3">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="inline-flex bg-slate-100 dark:bg-[#0c121d] p-1 rounded-xl">
            {[
              { id: 'tabla', label: `Tabla de Cierres (${items.length})` },
              { id: 'resumen', label: 'Resumen por Asesor y Proyecto' },
            ].map((t) => (
              <button
                key={t.id}
                type="button"
                onClick={() => setActiveView(t.id)}
                className={`px-3.5 py-1.5 rounded-lg text-xs font-bold transition-all cursor-pointer ${
                  activeView === t.id
                    ? 'bg-white dark:bg-slate-800 text-slate-900 dark:text-white shadow-sm'
                    : 'text-slate-500 hover:text-slate-800 dark:hover:text-slate-200'
                }`}
              >
                {t.label}
              </button>
            ))}
          </div>

          <div className="relative min-w-[260px] flex-1 max-w-sm">
            <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Buscar cliente, asesor, proyecto, lote, distrito..."
              className="w-full pl-9 pr-3 py-2 text-xs rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d] focus:outline-none focus:ring-2 focus:ring-indigo-500/30"
            />
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-2 pt-1">
          <select
            value={selectedPeriodo}
            onChange={(e) => setSelectedPeriodo(e.target.value)}
            className="text-xs px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
          >
            <option value="">Todos los meses</option>
            {periodos.map((p) => (
              <option key={`${p.anio}-${p.mes}`} value={`${p.anio}-${p.mes}`}>
                {p.mes_nombre} {p.anio}
              </option>
            ))}
          </select>

          <select
            value={proyectoFilter}
            onChange={(e) => setProyectoFilter(e.target.value)}
            className="text-xs px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
          >
            <option value="">Todos los proyectos</option>
            {(catalogos.proyectos || []).map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>

          <select
            value={asesorFilter}
            onChange={(e) => setAsesorFilter(e.target.value)}
            className="text-xs px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
          >
            <option value="">Todos los asesores</option>
            {(catalogos.asesores || []).map((a) => (
              <option key={a} value={a}>{a}</option>
            ))}
          </select>

          <select
            value={monedaFilter}
            onChange={(e) => setMonedaFilter(e.target.value)}
            className="text-xs px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
          >
            <option value="">Todas las monedas</option>
            <option value="SOLES">SOLES</option>
            <option value="DOLARES">DÓLARES</option>
          </select>

          <select
            value={estrategiaFilter}
            onChange={(e) => setEstrategiaFilter(e.target.value)}
            className="text-xs px-3 py-1.5 rounded-lg border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
          >
            <option value="">Todas las estrategias</option>
            {(catalogos.estrategias || []).map((es) => (
              <option key={es} value={es}>{es}</option>
            ))}
          </select>

          {(selectedPeriodo || proyectoFilter || asesorFilter || monedaFilter || estrategiaFilter || search) && (
            <button
              type="button"
              onClick={() => {
                setSelectedPeriodo('')
                setProyectoFilter('')
                setAsesorFilter('')
                setMonedaFilter('')
                setEstrategiaFilter('')
                setSearch('')
              }}
              className="text-xs font-semibold text-indigo-600 hover:underline px-2 cursor-pointer"
            >
              Limpiar filtros
            </button>
          )}
        </div>
      </div>

      {/* Contenido */}
      <div className="bg-white dark:bg-[#121a29] rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden">
        {loading ? (
          <div className="p-12 text-center text-sm text-slate-500">Cargando cuadro de cierres...</div>
        ) : activeView === 'tabla' ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs border-collapse">
              <thead className="bg-slate-50 dark:bg-[#0e1522] text-slate-600 dark:text-slate-300 border-b border-slate-200 dark:border-slate-800">
                <tr>
                  <th className="px-3 py-3 font-bold">Mes</th>
                  <th className="px-3 py-3 font-bold">Asesor</th>
                  <th className="px-3 py-3 font-bold">Proyecto / Lote</th>
                  <th className="px-3 py-3 font-bold">Cliente</th>
                  <th className="px-3 py-3 font-bold">Distrito</th>
                  <th className="px-3 py-3 font-bold">Ingreso Inicial</th>
                  <th className="px-3 py-3 font-bold text-right">Monto Venta</th>
                  <th className="px-3 py-3 font-bold text-center">% Ini.</th>
                  <th className="px-3 py-3 font-bold text-right">Cant. Inicial</th>
                  <th className="px-3 py-3 font-bold text-center">T.C.</th>
                  <th className="px-3 py-3 font-bold">Estrategia</th>
                  <th className="px-3 py-3 font-bold">Área / Edad</th>
                  <th className="px-3 py-3 font-bold">Obs.</th>
                  <th className="px-3 py-3 font-bold text-center">Origen</th>
                  <th className="px-3 py-3 font-bold text-right">Acciones</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {items.length === 0 ? (
                  <tr>
                    <td colSpan={15} className="p-8 text-center text-slate-400">
                      No hay cierres para los filtros seleccionados.
                    </td>
                  </tr>
                ) : (
                  items.map((r) => (
                    <tr key={r.id} className="hover:bg-slate-50/70 dark:hover:bg-slate-800/30 transition-colors">
                      <td className="px-3 py-2.5 whitespace-nowrap">
                        <span className="font-semibold text-slate-800 dark:text-slate-200">{r.mes_nombre}</span>
                        <span className="text-[10px] text-slate-400 ml-1">{r.anio}</span>
                      </td>
                      <td className="px-3 py-2.5 font-semibold whitespace-nowrap">{r.asesor || '—'}</td>
                      <td className="px-3 py-2.5 whitespace-nowrap">
                        <div className="font-bold text-slate-900 dark:text-white">{r.proyecto || '—'}</div>
                        <div className="text-[11px] font-mono text-indigo-700 dark:text-indigo-300">{r.lote || '—'}</div>
                      </td>
                      <td className="px-3 py-2.5 max-w-[200px]">
                        <div className="font-medium text-slate-800 dark:text-slate-100 truncate" title={r.cliente_nombre || ''}>
                          {r.cliente_nombre || '—'}
                        </div>
                      </td>
                      <td className="px-3 py-2.5 text-slate-600 dark:text-slate-300 whitespace-nowrap">{r.distrito || '—'}</td>
                      <td className="px-3 py-2.5 whitespace-nowrap font-mono text-[11px]">{r.fecha_ingreso_inicial || '—'}</td>
                      <td className="px-3 py-2.5 whitespace-nowrap text-right font-bold text-slate-900 dark:text-white">
                        {formatMoney(r.monto_total, r.moneda)}
                      </td>
                      <td className="px-3 py-2.5 text-center whitespace-nowrap">
                        <span className="px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 font-semibold text-[11px]">
                          {r.pct_inicial_raw || '—'}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 whitespace-nowrap text-right font-semibold text-emerald-700 dark:text-emerald-400">
                        {formatMoney(r.cantidad_inicial, r.moneda)}
                      </td>
                      <td className="px-3 py-2.5 text-center font-mono text-[11px] text-slate-500">
                        {r.tipo_cambio != null ? r.tipo_cambio : '—'}
                      </td>
                      <td className="px-3 py-2.5 whitespace-nowrap">{r.estrategia || '—'}</td>
                      <td className="px-3 py-2.5 whitespace-nowrap text-[11px] text-slate-500">
                        {[r.area, r.edad ? `${r.edad} años` : null].filter(Boolean).join(' · ') || '—'}
                      </td>
                      <td className="px-3 py-2.5 max-w-[150px] truncate text-slate-500" title={r.observaciones || ''}>
                        {r.observaciones || '—'}
                      </td>
                      <td className="px-3 py-2.5 text-center">
                        <span
                          className={`text-[10px] font-bold uppercase px-1.5 py-0.5 rounded ${
                            r.origen === 'crm'
                              ? 'bg-indigo-50 text-indigo-700'
                              : r.origen === 'excel'
                                ? 'bg-violet-50 text-violet-700'
                                : 'bg-slate-100 text-slate-600'
                          }`}
                        >
                          {r.origen}
                        </span>
                      </td>
                      <td className="px-3 py-2.5 text-right whitespace-nowrap">
                        <div className="inline-flex items-center gap-1">
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
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="p-6 grid grid-cols-1 lg:grid-cols-3 gap-6">
            <div className="border border-slate-200 dark:border-slate-800 rounded-xl p-4 space-y-2">
              <h3 className="text-xs font-bold uppercase text-slate-500 flex items-center gap-1.5">
                <Layers size={14} className="text-indigo-500" />
                Cierres por Asesor
              </h3>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="text-slate-400 border-b border-slate-100 dark:border-slate-800">
                    <tr>
                      <th className="py-1.5">Asesor</th>
                      <th className="py-1.5 text-center">Cierres</th>
                      <th className="py-1.5 text-right">Soles</th>
                      <th className="py-1.5 text-right">Dólares</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                    {(resumen.resumen_asesores || []).map((a) => (
                      <tr key={a.asesor}>
                        <td className="py-1.5 font-semibold">{a.asesor}</td>
                        <td className="py-1.5 text-center font-bold">{a.total}</td>
                        <td className="py-1.5 text-right text-emerald-700 font-semibold">
                          {a.monto_soles ? `S/ ${a.monto_soles.toLocaleString('es-PE')}` : '—'}
                        </td>
                        <td className="py-1.5 text-right text-indigo-700 font-semibold">
                          {a.monto_dolares ? `$ ${a.monto_dolares.toLocaleString('es-PE')}` : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="border border-slate-200 dark:border-slate-800 rounded-xl p-4 space-y-2">
              <h3 className="text-xs font-bold uppercase text-slate-500">Cierres por Proyecto</h3>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-xs">
                  <thead className="text-slate-400 border-b border-slate-100 dark:border-slate-800">
                    <tr>
                      <th className="py-1.5">Proyecto</th>
                      <th className="py-1.5 text-center">Tot.</th>
                      <th className="py-1.5 text-right">Soles</th>
                      <th className="py-1.5 text-right">Dólares</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                    {(resumen.resumen_proyectos || []).map((p) => (
                      <tr key={p.proyecto}>
                        <td className="py-1.5 font-semibold">{p.proyecto}</td>
                        <td className="py-1.5 text-center font-bold">{p.total}</td>
                        <td className="py-1.5 text-right text-emerald-700 font-semibold">
                          {p.monto_soles ? `S/ ${p.monto_soles.toLocaleString('es-PE')}` : '—'}
                        </td>
                        <td className="py-1.5 text-right text-indigo-700 font-semibold">
                          {p.monto_dolares ? `$ ${p.monto_dolares.toLocaleString('es-PE')}` : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>

            <div className="border border-slate-200 dark:border-slate-800 rounded-xl p-4 space-y-2">
              <h3 className="text-xs font-bold uppercase text-slate-500">Cierres por Estrategia</h3>
              <div className="divide-y divide-slate-100 dark:divide-slate-800 text-xs">
                {(resumen.resumen_estrategias || []).map((e) => (
                  <div key={e.estrategia} className="py-2 flex items-center justify-between">
                    <span className="font-medium">{e.estrategia}</span>
                    <span className="font-bold text-indigo-600">{e.total}</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Modales Compartidos Git / Drive */}
      {showDiffModal && (
        <GitDiffModal
          pendingRevision={pendingRevision}
          diffFilter={diffFilter}
          setDiffFilter={setDiffFilter}
          diffChanges={diffChanges}
          selectedDiffKeys={selectedDiffKeys}
          setSelectedDiffKeys={setSelectedDiffKeys}
          commitMsg={commitMsg}
          setCommitMsg={setCommitMsg}
          approving={approving}
          onApprove={handleApproveDiff}
          onReject={handleRejectDiff}
          onClose={() => setShowDiffModal(false)}
          renderAddedSummary={(a) =>
            `+ ${a.mes_nombre} ${a.anio} | Asesor: ${a.asesor || '—'} | ${a.proyecto || '—'} ${a.lote || ''} | Cliente: ${a.cliente_nombre || '—'} | Total: ${formatMoney(a.monto_total, a.moneda)} (${a.pct_inicial_raw || '—'})`
          }
        />
      )}

      {showHistoryModal && (
        <GitRevisionsModal
          title="Historial de Versiones — Cierres de Ventas"
          loadingHistory={loadingHistory}
          revisions={revisions}
          expandedRevId={expandedRevId}
          setExpandedRevId={setExpandedRevId}
          onClose={() => setShowHistoryModal(false)}
        />
      )}

      {showDriveCfgModal && (
        <DriveConfigModal
          title="Configurar Google Drive de Cierres"
          sheetUrl={driveUrlDraft}
          setSheetUrl={setDriveUrlDraft}
          saving={savingCfg}
          onSave={handleSaveDriveCfg}
          onClose={() => setShowDriveCfgModal(false)}
        />
      )}

      {/* Modal Crear / Editar Cierre */}
      {showFormModal && (
        <div className="fixed inset-0 z-50 bg-slate-950/60 backdrop-blur-xs flex items-center justify-center p-4">
          <form
            onSubmit={handleSaveForm}
            className="bg-white dark:bg-[#121a29] rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl w-full max-w-2xl overflow-hidden max-h-[92vh] flex flex-col"
          >
            <div className="px-5 py-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
              <h3 className="text-base font-bold">
                {editingRow ? 'Editar Cierre de Venta (Servidor CRM)' : 'Nuevo Cierre de Venta en Servidor'}
              </h3>
              <button type="button" onClick={() => setShowFormModal(false)} className="p-1.5 rounded-lg hover:bg-slate-100 cursor-pointer">
                <X size={18} />
              </button>
            </div>

            <div className="p-5 overflow-y-auto grid grid-cols-1 sm:grid-cols-3 gap-3 text-xs">
              <div>
                <label className="block font-bold text-slate-600 mb-1">Año</label>
                <input
                  type="number"
                  required
                  value={formState.anio}
                  onChange={(e) => setFormState({ ...formState, anio: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
                />
              </div>

              <div>
                <label className="block font-bold text-slate-600 mb-1">Mes</label>
                <select
                  value={formState.mes}
                  onChange={(e) => setFormState({ ...formState, mes: Number(e.target.value) })}
                  className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
                >
                  {MONTHS.map((m) => (
                    <option key={m.num} value={m.num}>{m.label}</option>
                  ))}
                </select>
              </div>

              <div>
                <label className="block font-bold text-slate-600 mb-1">Asesor</label>
                <input
                  type="text"
                  value={formState.asesor}
                  onChange={(e) => setFormState({ ...formState, asesor: e.target.value })}
                  placeholder="Ej. FABIOLA"
                  className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
                />
              </div>

              <div>
                <label className="block font-bold text-slate-600 mb-1">Proyecto *</label>
                <input
                  type="text"
                  required
                  value={formState.proyecto}
                  onChange={(e) => setFormState({ ...formState, proyecto: e.target.value })}
                  placeholder="Ej. PUERTO PALMERAS"
                  className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
                />
              </div>

              <div>
                <label className="block font-bold text-slate-600 mb-1">Lote *</label>
                <input
                  type="text"
                  required
                  value={formState.lote}
                  onChange={(e) => setFormState({ ...formState, lote: e.target.value })}
                  placeholder="Ej. A1"
                  className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
                />
              </div>

              <div>
                <label className="block font-bold text-slate-600 mb-1">Distrito Origen</label>
                <input
                  type="text"
                  value={formState.distrito}
                  onChange={(e) => setFormState({ ...formState, distrito: e.target.value })}
                  placeholder="Ej. Paucarpata"
                  className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
                />
              </div>

              <div className="sm:col-span-2">
                <label className="block font-bold text-slate-600 mb-1">Nombre del Cliente *</label>
                <input
                  type="text"
                  required
                  value={formState.cliente_nombre}
                  onChange={(e) => setFormState({ ...formState, cliente_nombre: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
                />
              </div>

              <div>
                <label className="block font-bold text-slate-600 mb-1">Fecha Ingreso Inicial</label>
                <input
                  type="text"
                  value={formState.fecha_ingreso_inicial}
                  onChange={(e) => setFormState({ ...formState, fecha_ingreso_inicial: e.target.value })}
                  placeholder="DD/MM/YYYY"
                  className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
                />
              </div>

              <div>
                <label className="block font-bold text-slate-600 mb-1">Monto Total Venta</label>
                <input
                  type="number"
                  step="0.01"
                  value={formState.monto_total}
                  onChange={(e) => setFormState({ ...formState, monto_total: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
                />
              </div>

              <div>
                <label className="block font-bold text-slate-600 mb-1">Moneda</label>
                <select
                  value={formState.moneda}
                  onChange={(e) => setFormState({ ...formState, moneda: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
                >
                  <option value="SOLES">SOLES</option>
                  <option value="DOLARES">DOLARES</option>
                </select>
              </div>

              <div>
                <label className="block font-bold text-slate-600 mb-1">% Inicial</label>
                <input
                  type="text"
                  value={formState.pct_inicial_raw}
                  onChange={(e) => setFormState({ ...formState, pct_inicial_raw: e.target.value })}
                  placeholder="Ej. 10% o CONTADO"
                  className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
                />
              </div>

              <div>
                <label className="block font-bold text-slate-600 mb-1">Cantidad de Inicial</label>
                <input
                  type="number"
                  step="0.01"
                  value={formState.cantidad_inicial}
                  onChange={(e) => setFormState({ ...formState, cantidad_inicial: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
                />
              </div>

              <div>
                <label className="block font-bold text-slate-600 mb-1">Tipo de Cambio</label>
                <input
                  type="number"
                  step="0.001"
                  value={formState.tipo_cambio}
                  onChange={(e) => setFormState({ ...formState, tipo_cambio: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
                />
              </div>

              <div>
                <label className="block font-bold text-slate-600 mb-1">Estrategia</label>
                <input
                  type="text"
                  value={formState.estrategia}
                  onChange={(e) => setFormState({ ...formState, estrategia: e.target.value })}
                  placeholder="Ej. WEDO, RALLY..."
                  className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
                />
              </div>

              <div>
                <label className="block font-bold text-slate-600 mb-1">Área</label>
                <input
                  type="text"
                  value={formState.area}
                  onChange={(e) => setFormState({ ...formState, area: e.target.value })}
                  placeholder="Ej. COMERCIAL"
                  className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
                />
              </div>

              <div>
                <label className="block font-bold text-slate-600 mb-1">Edad Cliente</label>
                <input
                  type="number"
                  value={formState.edad}
                  onChange={(e) => setFormState({ ...formState, edad: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
                />
              </div>

              <div className="sm:col-span-3">
                <label className="block font-bold text-slate-600 mb-1">Observaciones</label>
                <textarea
                  rows={2}
                  value={formState.observaciones}
                  onChange={(e) => setFormState({ ...formState, observaciones: e.target.value })}
                  className="w-full px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
                />
              </div>
            </div>

            <div className="px-5 py-4 border-t border-slate-200 dark:border-slate-800 flex justify-end gap-2 bg-slate-50 dark:bg-[#0e1522]">
              <button
                type="button"
                onClick={() => setShowFormModal(false)}
                className="px-4 py-2 rounded-xl text-xs font-semibold border border-slate-200 cursor-pointer"
              >
                Cancelar
              </button>
              <button
                type="submit"
                disabled={savingForm}
                className="px-4 py-2 rounded-xl text-xs font-bold bg-emerald-600 hover:bg-emerald-700 text-white cursor-pointer disabled:opacity-50"
              >
                {savingForm ? 'Guardando…' : editingRow ? 'Guardar Cambios' : 'Crear Cierre'}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  )
}
