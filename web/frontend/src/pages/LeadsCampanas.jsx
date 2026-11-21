import React, { useState, useEffect, useCallback, useMemo } from 'react'
import {
  Megaphone, RefreshCw, Search, Filter, Users, UserCheck, Shield,
  Layers, CheckCircle2, XCircle, AlertCircle, Plus, Copy, Check,
  ExternalLink, Sparkles, SlidersHorizontal, ArrowUpDown, ChevronDown, ChevronUp,
  Info, BarChart3, ArrowRight, ToggleLeft, ToggleRight, Trash2,
  Scale, Percent, Star, UserPlus,
} from 'lucide-react'
import api from '@/lib/api'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import LoadingSpinner from '@/components/shared/LoadingSpinner'
import EmptyState from '@/components/shared/EmptyState'
import { useUndoToast } from '@/components/shared/UndoToast'
import { cn } from '@/lib/utils'

export default function LeadsCampanas() {
  const { showUndoToast } = useUndoToast() || { showUndoToast: () => {} }

  // Estados principales de datos
  const [items, setItems] = useState([])
  const [stats, setStats] = useState({
    total: 0,
    meta_count: 0,
    tiktok_count: 0,
    active_count: 0,
    inactive_count: 0,
    assigned_count: 0,
    unassigned_count: 0,
    direct_count: 0,
    team_count: 0,
    all_count: 0,
  })
  const [supervisors, setSupervisors] = useState([])
  const [loading, setLoading] = useState(true)
  const [syncing, setSyncing] = useState(false)
  const [syncResult, setSyncResult] = useState(null)

  // Filtros
  const [search, setSearch] = useState('')
  const [providerFilter, setProviderFilter] = useState('all') // all | meta | tiktok
  const [statusFilter, setStatusFilter] = useState('all') // all | ACTIVE | PAUSED
  const [assignmentFilter, setAssignmentFilter] = useState('all') // all | assigned | unassigned
  const [supervisorFilter, setSupervisorFilter] = useState('all')

  // Selección múltiple para acciones masivas
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [bulkSupervisorIds, setBulkSupervisorIds] = useState([])
  const [bulkDistributionMode, setBulkDistributionMode] = useState('supervisor') // supervisor | equipo | todos
  const [bulkUpdating, setBulkUpdating] = useState(false)
  const [bulkModalOpen, setBulkModalOpen] = useState(false)
  const [bulkSupSearch, setBulkSupSearch] = useState('')

  // Modal para designar supervisores a una campaña
  const [supervisorModalCampaign, setSupervisorModalCampaign] = useState(null)
  const [modalSupervisorIds, setModalSupervisorIds] = useState([])
  const [modalDistMode, setModalDistMode] = useState('supervisor') // 'supervisor' | 'equipo' | 'todos'
  const [modalDistType, setModalDistType] = useState('equitativo') // 'equitativo' | 'personalizado'
  const [modalPercentages, setModalPercentages] = useState({}) // { [supId]: number }
  const [savingSupervisors, setSavingSupervisors] = useState(false)
  const [supervisorSearch, setSupervisorSearch] = useState('')

  // Configuración personalizada por equipo
  const [modalTeamModes, setModalTeamModes] = useState({}) // { [supId]: 'heredar' | 'supervisor' | 'equipo' | 'todos' }
  const [modalTeamDistType, setModalTeamDistType] = useState({}) // { [supId]: 'equitativo' | 'personalizado' }
  const [modalTeamMemberPercentages, setModalTeamMemberPercentages] = useState({}) // { [supId]: { [userId]: number } }
  const [expandedTeams, setExpandedTeams] = useState(new Set())

  // Helper para repartir 100% de forma pareja entre supervisores
  const autoBalancePercentages = useCallback((supIds) => {
    if (!supIds || supIds.length === 0) return {}
    const count = supIds.length
    const equalShare = Math.floor(100 / count)
    const remainder = 100 - (equalShare * count)
    const res = {}
    supIds.forEach((id, idx) => {
      res[id] = equalShare + (idx === 0 ? remainder : 0)
    })
    return res
  }, [])

  // Helper para repartir 100% parejo entre integrantes de un equipo
  const autoBalanceTeamMemberPercentages = useCallback((members) => {
    if (!members || members.length === 0) return {}
    const count = members.length
    const equalShare = Math.floor(100 / count)
    const remainder = 100 - (equalShare * count)
    const res = {}
    members.forEach((m, idx) => {
      res[m.id] = equalShare + (idx === 0 ? remainder : 0)
    })
    return res
  }, [])

  const toggleTeamAccordion = useCallback((supId) => {
    setExpandedTeams(prev => {
      const next = new Set(prev)
      if (next.has(supId)) {
        next.delete(supId)
      } else {
        next.add(supId)
      }
      return next
    })
  }, [])

  // Suma total actual de los porcentajes entre supervisores en el modal
  const modalTotalPercentage = useMemo(() => {
    if (!modalSupervisorIds || modalSupervisorIds.length === 0) return 0
    return modalSupervisorIds.reduce((sum, id) => {
      const val = modalPercentages[id]
      return sum + (val === '' || val === undefined ? 0 : parseInt(val, 10) || 0)
    }, 0)
  }, [modalSupervisorIds, modalPercentages])

  // Modal nueva campaña manual
  const [modalOpen, setModalOpen] = useState(false)
  const [newCampaign, setNewCampaign] = useState({
    provider: 'meta',
    campaign_id: '',
    campaign_name: '',
    supervisor_ids: [],
    distribution_mode: 'supervisor',
    is_active: true,
    status: 'ACTIVE',
  })
  const [savingManual, setSavingManual] = useState(false)

  // Feedback de copiado de ID
  const [copiedId, setCopiedId] = useState(null)

  // ── Cargar supervisores ──────────────────────────────────────────────────
  const fetchSupervisors = useCallback(async () => {
    try {
      const res = await api.get('/api/campaign-assignments/supervisors')
      setSupervisors(res.data?.items || [])
    } catch (err) {
      console.error('Error cargando supervisores:', err)
    }
  }, [])

  // ── Cargar campañas ──────────────────────────────────────────────────────
  const fetchCampaigns = useCallback(async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (providerFilter !== 'all') params.append('provider', providerFilter)
      if (statusFilter !== 'all') params.append('status', statusFilter)
      if (assignmentFilter === 'assigned') params.append('is_assigned', 'true')
      if (assignmentFilter === 'unassigned') params.append('is_assigned', 'false')
      if (supervisorFilter !== 'all') params.append('supervisor_id', supervisorFilter)
      if (search.trim()) params.append('search', search.trim())
      params.append('limit', '300')

      const res = await api.get(`/api/campaign-assignments?${params.toString()}`)
      setItems(res.data?.items || [])
      if (res.data?.stats) {
        setStats(res.data.stats)
      }
    } catch (err) {
      console.error('Error cargando asignaciones de campañas:', err)
    } finally {
      setLoading(false)
    }
  }, [providerFilter, statusFilter, assignmentFilter, supervisorFilter, search])

  useEffect(() => {
    fetchSupervisors()
  }, [fetchSupervisors])

  useEffect(() => {
    const timer = setTimeout(() => {
      fetchCampaigns()
    }, 200)
    return () => clearTimeout(timer)
  }, [fetchCampaigns])

  // ── Disparar Sincronización en vivo con Meta y TikTok ────────────────────
  const handleSync = async () => {
    setSyncing(true)
    setSyncResult(null)
    try {
      const res = await api.post('/api/campaign-assignments/sync')
      setSyncResult(res.data)
      await fetchCampaigns()
      if (showUndoToast) {
        showUndoToast({
          title: 'Sincronización completada',
          message: `Se sincronizaron ${res.data?.total_synced || 0} campañas (${res.data?.meta_synced || 0} Meta, ${res.data?.tiktok_synced || 0} TikTok).`,
          type: 'success',
        })
      }
    } catch (err) {
      console.error('Error en sync:', err)
      if (showUndoToast) {
        showUndoToast({
          title: 'Error de sincronización',
          message: err.response?.data?.detail || 'No se pudo sincronizar con las APIs externas.',
          type: 'error',
        })
      }
    } finally {
      setSyncing(false)
    }
  }

  // ── Abrir modal de supervisores para una campaña ─────────────────────────
  const handleOpenSupervisorModal = (campaign) => {
    setSupervisorModalCampaign(campaign)
    const currentIds = campaign.supervisor_ids?.length
      ? campaign.supervisor_ids
      : campaign.supervisor_id ? [campaign.supervisor_id] : []
    setModalSupervisorIds(currentIds)
    setModalDistMode(campaign.distribution_mode || 'supervisor')
    setSupervisorSearch('')

    // Verificar si ya tiene porcentajes personalizados asignados
    const initialPercentages = {}
    let hasCustom = false
    const initialTeamModes = {}
    const initialTeamDistTypes = {}
    const initialTeamMemberPcts = {}
    const initialExpanded = new Set()

    if (campaign.supervisors?.length) {
      campaign.supervisors.forEach(s => {
        if (s.porcentaje !== null && s.porcentaje !== undefined && Number(s.porcentaje) > 0) {
          initialPercentages[s.id] = Number(s.porcentaje)
          hasCustom = true
        }

        // Modo específico del equipo (o 'heredar')
        if (s.distribution_mode && ['supervisor', 'equipo', 'todos'].includes(s.distribution_mode)) {
          initialTeamModes[s.id] = s.distribution_mode
        } else {
          initialTeamModes[s.id] = 'heredar'
        }

        // Porcentajes de miembros del equipo
        if (s.member_percentages && Object.keys(s.member_percentages).length > 0) {
          initialTeamDistTypes[s.id] = 'personalizado'
          const mPcts = {}
          Object.entries(s.member_percentages).forEach(([uid, val]) => {
            mPcts[uid] = Number(val) || 0
          })
          initialTeamMemberPcts[s.id] = mPcts
          initialExpanded.add(s.id)
        } else {
          initialTeamDistTypes[s.id] = 'equitativo'
        }
      })
    }

    if (initialExpanded.size === 0 && currentIds.length > 0) {
      initialExpanded.add(currentIds[0])
    }
    setExpandedTeams(initialExpanded)
    setModalTeamModes(initialTeamModes)
    setModalTeamDistType(initialTeamDistTypes)
    setModalTeamMemberPercentages(initialTeamMemberPcts)

    setModalDistType(hasCustom ? 'personalizado' : 'equitativo')
    if (hasCustom) {
      currentIds.forEach(id => {
        if (initialPercentages[id] === undefined) {
          initialPercentages[id] = 0
        }
      })
      setModalPercentages(initialPercentages)
    } else {
      setModalPercentages(autoBalancePercentages(currentIds))
    }
  }

  // ── Guardar supervisores desde el modal ──────────────────────────────────
  const handleSaveSupervisorsModal = async () => {
    if (!supervisorModalCampaign) return
    const isCustom = modalDistType === 'personalizado' && modalSupervisorIds.length > 1
    if (isCustom) {
      if (modalTotalPercentage !== 100) {
        alert(`La suma de los porcentajes entre supervisores debe ser exactamente 100%. Actualmente suma ${modalTotalPercentage}%.`)
        return
      }
    }

    // Validar suma de porcentajes de integrantes por equipo si está en personalizado
    for (const supId of modalSupervisorIds) {
      const supObj = supervisors.find(s => s.id === supId)
      const tMode = (modalTeamModes[supId] && modalTeamModes[supId] !== 'heredar')
        ? modalTeamModes[supId]
        : modalDistMode

      if ((tMode === 'equipo' || tMode === 'todos') && modalTeamDistType[supId] === 'personalizado') {
        const cands = tMode === 'todos'
          ? [{ id: supId }, ...(supObj?.team_members || [])]
          : (supObj?.team_members || [])

        if (cands.length > 1) {
          const mPcts = modalTeamMemberPercentages[supId] || {}
          const sumM = cands.reduce((acc, c) => acc + (parseInt(mPcts[c.id], 10) || 0), 0)
          if (sumM !== 100) {
            alert(`El equipo de "${supObj?.display_name || 'Supervisor'}" tiene una suma de cuotas de ${sumM}% (debe ser exactamente 100%).`)
            return
          }
        }
      }
    }

    setSavingSupervisors(true)
    try {
      const payloadPercentages = isCustom
        ? modalSupervisorIds.reduce((acc, id) => {
            acc[id] = parseInt(modalPercentages[id], 10) || 0
            return acc
          }, {})
        : null

      const payloadTeamModes = {}
      const payloadTeamMemberPcts = {}

      modalSupervisorIds.forEach(id => {
        if (modalTeamModes[id] && ['supervisor', 'equipo', 'todos'].includes(modalTeamModes[id])) {
          payloadTeamModes[id] = modalTeamModes[id]
        }
        if (modalTeamDistType[id] === 'personalizado' && modalTeamMemberPercentages[id]) {
          const supObj = supervisors.find(s => s.id === id)
          const tMode = (modalTeamModes[id] && modalTeamModes[id] !== 'heredar')
            ? modalTeamModes[id]
            : modalDistMode
          const cands = tMode === 'todos'
            ? [{ id }, ...(supObj?.team_members || [])]
            : (supObj?.team_members || [])

          const pcts = {}
          cands.forEach(c => {
            pcts[c.id] = parseInt(modalTeamMemberPercentages[id]?.[c.id], 10) || 0
          })
          payloadTeamMemberPcts[id] = pcts
        }
      })

      const res = await api.put(`/api/campaign-assignments/${supervisorModalCampaign.id}`, {
        supervisor_ids: modalSupervisorIds,
        distribution_mode: modalDistMode,
        percentages: payloadPercentages,
        team_distribution_modes: Object.keys(payloadTeamModes).length > 0 ? payloadTeamModes : null,
        team_member_percentages: Object.keys(payloadTeamMemberPcts).length > 0 ? payloadTeamMemberPcts : null,
      })
      if (res.data?.ok) {
        await fetchCampaigns()
        setSupervisorModalCampaign(null)
        if (showUndoToast) {
          const count = modalSupervisorIds.length
          showUndoToast({
            title: 'Asignación de campaña actualizada',
            message: count > 1
              ? `Designados ${count} supervisores/equipos con configuración personalizada guardada.`
              : count === 1
                ? 'Supervisor/equipo asignado correctamente.'
                : 'Campaña devuelta a la rotación general.',
            type: 'success',
          })
        }
      }
    } catch (err) {
      console.error('Error al actualizar supervisores:', err)
      fetchCampaigns()
    } finally {
      setSavingSupervisors(false)
    }
  }

  // ── Cambiar Modo de Reparto en la fila (Directo vs En Equipo vs A Todos) ───
  const handleDistributionModeChange = async (assignmentId, nextMode) => {
    const currentItem = items.find(i => i.id === assignmentId)
    const prevMode = currentItem?.distribution_mode || 'supervisor'

    // Optimistic update
    setItems(prev => prev.map(item => {
      if (item.id === assignmentId) {
        return { ...item, distribution_mode: nextMode }
      }
      return item
    }))
    try {
      const res = await api.put(`/api/campaign-assignments/${assignmentId}`, {
        distribution_mode: nextMode,
      })
      if (res.data?.ok) {
        setStats(prev => {
          let direct = prev.direct_count || 0
          let team = prev.team_count || 0
          let all = prev.all_count || 0

          if (prevMode === 'supervisor') direct = Math.max(0, direct - 1)
          else if (prevMode === 'equipo') team = Math.max(0, team - 1)
          else if (prevMode === 'todos') all = Math.max(0, all - 1)

          if (nextMode === 'supervisor') direct += 1
          else if (nextMode === 'equipo') team += 1
          else if (nextMode === 'todos') all += 1

          return { ...prev, direct_count: direct, team_count: team, all_count: all }
        })
        if (showUndoToast) {
          const messages = {
            supervisor: '👤 Los leads se repartirán directamente entre los supervisores designados.',
            equipo: '👥 Los leads se repartirán alternando entre los asesores del equipo de cada supervisor.',
            todos: '🌟 Los leads se repartirán rotando entre el supervisor y todos los integrantes de su equipo.',
          }
          showUndoToast({
            title: 'Modo de reparto actualizado',
            message: messages[nextMode] || 'Modo de reparto actualizado.',
            type: 'success',
          })
        }
      }
    } catch (err) {
      console.error('Error al cambiar modo de reparto:', err)
      fetchCampaigns()
    }
  }

  // ── Toggle activo / inactivo de la regla ─────────────────────────────────
  const handleToggleActive = async (assignmentId, currentActive) => {
    try {
      const nextActive = !currentActive
      const res = await api.put(`/api/campaign-assignments/${assignmentId}`, {
        is_active: nextActive,
      })
      if (res.data?.ok) {
        setItems(prev => prev.map(item => item.id === assignmentId ? { ...item, is_active: nextActive } : item))
      }
    } catch (err) {
      console.error('Error al cambiar estado activo:', err)
      fetchCampaigns()
    }
  }

  // ── Selección masiva ─────────────────────────────────────────────────────
  const toggleSelectAll = () => {
    if (selectedIds.size === items.length && items.length > 0) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(items.map(i => i.id)))
    }
  }

  const toggleSelectRow = (id) => {
    const next = new Set(selectedIds)
    if (next.has(id)) {
      next.delete(id)
    } else {
      next.add(id)
    }
    setSelectedIds(next)
  }

  // ── Asignación en Lote ───────────────────────────────────────────────────
  const handleBulkAssign = async () => {
    if (selectedIds.size === 0) return
    setBulkUpdating(true)
    try {
      const res = await api.post('/api/campaign-assignments/bulk-assign', {
        assignment_ids: Array.from(selectedIds),
        supervisor_ids: bulkSupervisorIds,
        distribution_mode: bulkSupervisorIds.length > 0 ? bulkDistributionMode : undefined,
      })
      if (res.data?.ok) {
        setSelectedIds(new Set())
        setBulkSupervisorIds([])
        setBulkDistributionMode('supervisor')
        setBulkModalOpen(false)
        await fetchCampaigns()
        if (showUndoToast) {
          showUndoToast({
            title: 'Asignación masiva exitosa',
            message: `Se actualizaron ${res.data.updated_count} campañas con los supervisores designados.`,
            type: 'success',
          })
        }
      }
    } catch (err) {
      console.error('Error en asignación masiva:', err)
    } finally {
      setBulkUpdating(false)
    }
  }

  // ── Eliminar campaña / regla ─────────────────────────────────────────────
  const handleDeleteCampaign = async (id, campaignName) => {
    const ok = window.confirm(`¿Estás seguro de eliminar la campaña "${campaignName || id}"? Esta acción borrará la regla de asignación.`)
    if (!ok) return

    try {
      const res = await api.delete(`/api/campaign-assignments/${id}`)
      if (res.data?.ok) {
        setItems(prev => prev.filter(item => item.id !== id))
        setStats(prev => ({
          ...prev,
          total: Math.max(0, prev.total - 1),
        }))
        if (showUndoToast) {
          showUndoToast({
            title: 'Campaña eliminada',
            message: 'La campaña fue removida exitosamente.',
            type: 'success',
          })
        }
      }
    } catch (err) {
      console.error('Error eliminando campaña:', err)
      if (showUndoToast) {
        showUndoToast({
          title: 'Error al eliminar',
          message: err.response?.data?.detail || 'No se pudo eliminar la campaña.',
          type: 'error',
        })
      }
    }
  }

  // ── Crear campaña manual ─────────────────────────────────────────────────
  const handleCreateManual = async (e) => {
    e.preventDefault()
    if (!newCampaign.campaign_id.trim()) return
    setSavingManual(true)
    try {
      const res = await api.post('/api/campaign-assignments', {
        provider: newCampaign.provider,
        campaign_id: newCampaign.campaign_id,
        campaign_name: newCampaign.campaign_name,
        supervisor_ids: newCampaign.supervisor_ids,
        distribution_mode: newCampaign.supervisor_ids.length > 0 ? newCampaign.distribution_mode : 'supervisor',
        is_active: newCampaign.is_active,
        status: newCampaign.status,
      })
      if (res.data?.ok) {
        setModalOpen(false)
        setNewCampaign({
          provider: 'meta',
          campaign_id: '',
          campaign_name: '',
          supervisor_ids: [],
          distribution_mode: 'supervisor',
          is_active: true,
          status: 'ACTIVE',
        })
        await fetchCampaigns()
        if (showUndoToast) {
          showUndoToast({
            title: 'Campaña registrada',
            message: 'La campaña fue creada exitosamente.',
            type: 'success',
          })
        }
      }
    } catch (err) {
      console.error('Error creando campaña manual:', err)
    } finally {
      setSavingManual(false)
    }
  }

  const copyToClipboard = (text, id) => {
    navigator.clipboard.writeText(text)
    setCopiedId(id)
    setTimeout(() => setCopiedId(null), 2000)
  }

  return (
    <div className="p-4 sm:p-6 lg:p-8 max-w-[1600px] mx-auto space-y-6">
      {/* ── CABECERA ────────────────────────────────────────────────────────── */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-gray-200 dark:border-slate-800 pb-5">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="p-2 rounded-xl bg-gradient-to-tr from-blue-600 to-indigo-500 text-white shadow-md shadow-blue-500/20">
              <Megaphone size={22} />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-gray-900 dark:text-white tracking-tight">
                Leads Campañas
              </h1>
              <p className="text-sm text-gray-500 dark:text-slate-400">
                Extracción de campañas activas e inactivas de Meta y TikTok para asignación exclusiva a supervisores
              </p>
            </div>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            onClick={() => setModalOpen(true)}
            className="flex items-center gap-2 text-sm font-medium border-gray-300 dark:border-slate-700 hover:bg-gray-100 dark:hover:bg-slate-800"
          >
            <Plus size={16} />
            <span>Agregar Campaña</span>
          </Button>

          <Button
            onClick={handleSync}
            disabled={syncing}
            className="flex items-center gap-2 bg-[var(--brand-primary,#2563eb)] hover:opacity-90 text-white shadow-sm"
          >
            <RefreshCw size={16} className={cn(syncing && "animate-spin")} />
            <span>{syncing ? 'Sincronizando...' : 'Sincronizar Meta & TikTok'}</span>
          </Button>
        </div>
      </div>

      {/* ── BANNER DE RESULTADO DE SYNC (SI HUBO) ───────────────────────────── */}
      {syncResult && (
        <div className="p-4 rounded-xl bg-blue-50/80 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-900 flex items-start gap-3">
          <Sparkles className="w-5 h-5 text-blue-600 dark:text-blue-400 shrink-0 mt-0.5" />
          <div className="flex-1 text-sm text-blue-900 dark:text-blue-200">
            <span className="font-semibold">Sincronización finalizada:</span> Se procesaron {syncResult.total_synced} campañas en total ({syncResult.meta_synced} de Meta Ads, {syncResult.tiktok_synced} de TikTok Ads, {syncResult.discovered_synced} descubiertas en el sistema).
            {syncResult.errors?.length > 0 && (
              <ul className="mt-1.5 list-disc list-inside text-xs text-amber-700 dark:text-amber-300 space-y-0.5">
                {syncResult.errors.map((e, idx) => <li key={idx}>{e}</li>)}
              </ul>
            )}
          </div>
          <button onClick={() => setSyncResult(null)} className="text-blue-500 hover:text-blue-700 text-xs font-semibold">
            Cerrar
          </button>
        </div>
      )}

      {/* ── KPI METRIC CARDS ──────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-3.5">
        {/* Total Campañas */}
        <Card className="bg-white dark:bg-slate-900/80 border-gray-200 dark:border-slate-800 shadow-sm">
          <CardContent className="p-4 flex items-center justify-between">
            <div>
              <p className="text-xs font-medium text-gray-500 dark:text-slate-400">Total Campañas</p>
              <p className="text-2xl font-bold text-gray-900 dark:text-white mt-1">{stats.total}</p>
              <div className="flex items-center gap-1.5 mt-1 text-[11px] text-emerald-600 dark:text-emerald-400">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                <span>{stats.active_count} activas</span>
                <span className="text-gray-300 dark:text-slate-700">•</span>
                <span className="text-gray-400 dark:text-slate-500">{stats.inactive_count} inactivas</span>
              </div>
            </div>
            <div className="w-10 h-10 rounded-xl bg-blue-50 dark:bg-blue-950/60 text-blue-600 dark:text-blue-400 flex items-center justify-center">
              <Layers size={20} />
            </div>
          </CardContent>
        </Card>

        {/* Campañas Meta */}
        <Card className="bg-white dark:bg-slate-900/80 border-gray-200 dark:border-slate-800 shadow-sm">
          <CardContent className="p-4 flex items-center justify-between">
            <div>
              <p className="text-xs font-medium text-gray-500 dark:text-slate-400">Meta (FB & IG)</p>
              <p className="text-2xl font-bold text-blue-600 dark:text-blue-400 mt-1">{stats.meta_count}</p>
              <p className="text-[11px] text-gray-500 dark:text-slate-400 mt-1">Facebook / Instagram Ads</p>
            </div>
            <div className="w-10 h-10 rounded-xl bg-blue-100/70 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 flex items-center justify-center font-bold text-xs">
              META
            </div>
          </CardContent>
        </Card>

        {/* Campañas TikTok */}
        <Card className="bg-white dark:bg-slate-900/80 border-gray-200 dark:border-slate-800 shadow-sm">
          <CardContent className="p-4 flex items-center justify-between">
            <div>
              <p className="text-xs font-medium text-gray-500 dark:text-slate-400">TikTok Ads</p>
              <p className="text-2xl font-bold text-cyan-600 dark:text-cyan-400 mt-1">{stats.tiktok_count}</p>
              <p className="text-[11px] text-gray-500 dark:text-slate-400 mt-1">Lead Generation</p>
            </div>
            <div className="w-10 h-10 rounded-xl bg-cyan-100/70 dark:bg-cyan-950/60 text-cyan-700 dark:text-cyan-300 flex items-center justify-center font-bold text-xs">
              TT
            </div>
          </CardContent>
        </Card>

        {/* Asignadas a Supervisor */}
        <Card className="bg-white dark:bg-slate-900/80 border-gray-200 dark:border-slate-800 shadow-sm">
          <CardContent className="p-4 flex items-center justify-between">
            <div>
              <p className="text-xs font-medium text-gray-500 dark:text-slate-400">Supervisor Exclusivo</p>
              <p className="text-2xl font-bold text-purple-600 dark:text-purple-400 mt-1">{stats.assigned_count}</p>
              <div className="flex items-center gap-1.5 mt-1 text-[11px] font-medium text-gray-500 dark:text-slate-400 flex-wrap">
                <span className="text-purple-700 dark:text-purple-300 font-semibold" title="Directo al Supervisor">
                  👤 {stats.direct_count || 0} Directo
                </span>
                <span>•</span>
                <span className="text-indigo-700 dark:text-indigo-300 font-semibold" title="Reparto en Equipo">
                  👥 {stats.team_count || 0} Equipo
                </span>
                <span>•</span>
                <span className="text-amber-700 dark:text-amber-300 font-semibold" title="A Todos (Supervisor y Equipo)">
                  🌟 {stats.all_count || 0} A Todos
                </span>
              </div>
            </div>
            <div className="w-10 h-10 rounded-xl bg-purple-50 dark:bg-purple-950/60 text-purple-600 dark:text-purple-400 flex items-center justify-center">
              <UserCheck size={20} />
            </div>
          </CardContent>
        </Card>

        {/* En Rotación General */}
        <Card className="bg-white dark:bg-slate-900/80 border-gray-200 dark:border-slate-800 shadow-sm col-span-2 sm:col-span-1">
          <CardContent className="p-4 flex items-center justify-between">
            <div>
              <p className="text-xs font-medium text-gray-500 dark:text-slate-400">Rotación General</p>
              <p className="text-2xl font-bold text-gray-700 dark:text-slate-300 mt-1">{stats.unassigned_count}</p>
              <p className="text-[11px] text-gray-500 dark:text-slate-400 mt-1">Reparto estándar</p>
            </div>
            <div className="w-10 h-10 rounded-xl bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-400 flex items-center justify-center">
              <Users size={20} />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* ── BARRA DE FILTROS ───────────────────────────────────────────────── */}
      <Card className="bg-white dark:bg-slate-900 border-gray-200 dark:border-slate-800 shadow-sm">
        <CardContent className="p-4 space-y-3.5">
          <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-3">
            {/* Buscador */}
            <div className="relative flex-1 min-w-[280px]">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 dark:text-slate-500" size={17} />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Buscar por nombre o ID de campaña..."
                className="pl-9 bg-gray-50 dark:bg-slate-950/60 border-gray-200 dark:border-slate-800 text-sm h-10"
              />
              {search && (
                <button
                  onClick={() => setSearch('')}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 dark:hover:text-slate-200 text-xs"
                >
                  ✕
                </button>
              )}
            </div>

            {/* Selector de plataforma */}
            <div className="flex items-center bg-gray-100 dark:bg-slate-800 p-1 rounded-lg text-xs font-medium shrink-0">
              <button
                onClick={() => setProviderFilter('all')}
                className={cn(
                  "px-3 py-1.5 rounded-md transition-all",
                  providerFilter === 'all'
                    ? "bg-white dark:bg-slate-900 text-gray-900 dark:text-white shadow-xs font-semibold"
                    : "text-gray-600 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white"
                )}
              >
                Todas
              </button>
              <button
                onClick={() => setProviderFilter('meta')}
                className={cn(
                  "px-3 py-1.5 rounded-md transition-all flex items-center gap-1.5",
                  providerFilter === 'meta'
                    ? "bg-blue-600 text-white shadow-xs font-semibold"
                    : "text-gray-600 dark:text-slate-400 hover:text-blue-600 dark:hover:text-blue-400"
                )}
              >
                <span>Meta Ads</span>
              </button>
              <button
                onClick={() => setProviderFilter('tiktok')}
                className={cn(
                  "px-3 py-1.5 rounded-md transition-all flex items-center gap-1.5",
                  providerFilter === 'tiktok'
                    ? "bg-slate-950 dark:bg-cyan-600 text-white shadow-xs font-semibold"
                    : "text-gray-600 dark:text-slate-400 hover:text-cyan-600 dark:hover:text-cyan-400"
                )}
              >
                <span>TikTok Ads</span>
              </button>
            </div>

            {/* Selector de Estado */}
            <div className="flex items-center bg-gray-100 dark:bg-slate-800 p-1 rounded-lg text-xs font-medium shrink-0">
              <button
                onClick={() => setStatusFilter('all')}
                className={cn(
                  "px-3 py-1.5 rounded-md transition-all",
                  statusFilter === 'all'
                    ? "bg-white dark:bg-slate-900 text-gray-900 dark:text-white shadow-xs font-semibold"
                    : "text-gray-600 dark:text-slate-400 hover:text-gray-900"
                )}
              >
                Todos Estados
              </button>
              <button
                onClick={() => setStatusFilter('ACTIVE')}
                className={cn(
                  "px-3 py-1.5 rounded-md transition-all flex items-center gap-1.5",
                  statusFilter === 'ACTIVE'
                    ? "bg-emerald-600 text-white shadow-xs font-semibold"
                    : "text-emerald-700 dark:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-950/40"
                )}
              >
                <span className="w-1.5 h-1.5 rounded-full bg-current" />
                <span>Activas</span>
              </button>
              <button
                onClick={() => setStatusFilter('PAUSED')}
                className={cn(
                  "px-3 py-1.5 rounded-md transition-all flex items-center gap-1.5",
                  statusFilter === 'PAUSED'
                    ? "bg-amber-600 text-white shadow-xs font-semibold"
                    : "text-amber-700 dark:text-amber-400 hover:bg-amber-50 dark:hover:bg-amber-950/40"
                )}
              >
                <span>Inactivas / Pausadas</span>
              </button>
            </div>

            {/* Selector de Asignación */}
            <div className="flex items-center gap-2">
              <select
                value={assignmentFilter}
                onChange={(e) => setAssignmentFilter(e.target.value)}
                className="h-10 px-3 rounded-lg bg-gray-50 dark:bg-slate-950/60 border border-gray-200 dark:border-slate-800 text-xs font-medium text-gray-700 dark:text-slate-300 outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="all">Todas las asignaciones</option>
                <option value="assigned">Solo con supervisor asignado</option>
                <option value="unassigned">Solo sin asignar (Rotación)</option>
              </select>

              {/* Selector por Supervisor específico */}
              <select
                value={supervisorFilter}
                onChange={(e) => setSupervisorFilter(e.target.value)}
                className="h-10 px-3 rounded-lg bg-gray-50 dark:bg-slate-950/60 border border-gray-200 dark:border-slate-800 text-xs font-medium text-gray-700 dark:text-slate-300 outline-none focus:ring-2 focus:ring-blue-500 max-w-[200px]"
              >
                <option value="all">Cualquier supervisor</option>
                <option value="unassigned">Sin asignar</option>
                {supervisors.map(s => (
                  <option key={s.id} value={s.id}>
                    {s.display_name} ({s.role})
                  </option>
                ))}
              </select>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ── BARRA DE ACCIÓN MASIVA (VISIBLE AL SELECCIONAR FILAS) ─────────── */}
      {selectedIds.size > 0 && (
        <div className="sticky top-4 z-20 p-3.5 bg-gradient-to-r from-blue-900 to-indigo-900 text-white rounded-xl shadow-xl flex flex-wrap items-center justify-between gap-3 animate-in fade-in slide-in-from-top-2 duration-200">
          <div className="flex items-center gap-3">
            <span className="bg-white/20 text-white text-xs font-bold px-2.5 py-1 rounded-full">
              {selectedIds.size} seleccionadas
            </span>
            <span className="text-sm font-medium">Asignar supervisores a estas campañas:</span>
          </div>

          <div className="flex items-center gap-2 flex-wrap">
            <Button
              type="button"
              variant="outline"
              onClick={() => { setBulkSupSearch(''); setBulkModalOpen(true); }}
              className="h-9 px-3 rounded-lg bg-white text-gray-900 border-0 text-xs font-semibold hover:bg-gray-100 flex items-center gap-1.5 shadow-xs"
            >
              <Users size={14} className="text-blue-700" />
              <span>
                {bulkSupervisorIds.length === 0
                  ? "Elegir Supervisores..."
                  : `${bulkSupervisorIds.length} supervisor(es) seleccionado(s)`}
              </span>
              <ChevronDown size={13} className="text-gray-500" />
            </Button>

            {bulkSupervisorIds.length > 0 && (
              <div className="flex items-center bg-blue-950/80 p-0.5 rounded-lg border border-blue-700/60 text-xs">
                <button
                  type="button"
                  onClick={() => setBulkDistributionMode('supervisor')}
                  className={cn(
                    "px-2.5 py-1 rounded-md font-medium text-xs transition-all flex items-center gap-1 cursor-pointer",
                    bulkDistributionMode === 'supervisor'
                      ? "bg-white text-blue-950 font-bold shadow-xs"
                      : "text-blue-200 hover:text-white"
                  )}
                  title="Reparto equitativo directo entre los supervisores designados"
                >
                  <span>👤 Directo</span>
                </button>
                <button
                  type="button"
                  onClick={() => setBulkDistributionMode('equipo')}
                  className={cn(
                    "px-2.5 py-1 rounded-md font-medium text-xs transition-all flex items-center gap-1 cursor-pointer",
                    bulkDistributionMode === 'equipo'
                      ? "bg-white text-blue-950 font-bold shadow-xs"
                      : "text-blue-200 hover:text-white"
                  )}
                  title="Reparto equitativo alternando entre los equipos de cada supervisor (1 lead por persona alternadamente)"
                >
                  <span>👥 En Equipo</span>
                </button>
                <button
                  type="button"
                  onClick={() => setBulkDistributionMode('todos')}
                  className={cn(
                    "px-2.5 py-1 rounded-md font-medium text-xs transition-all flex items-center gap-1 cursor-pointer",
                    bulkDistributionMode === 'todos'
                      ? "bg-white text-blue-950 font-bold shadow-xs"
                      : "text-blue-200 hover:text-white"
                  )}
                  title="Reparto equitativo entre el supervisor y todos los asesores de su equipo"
                >
                  <span>🌟 A Todos</span>
                </button>
              </div>
            )}

            <Button
              onClick={handleBulkAssign}
              disabled={bulkUpdating || bulkSupervisorIds.length === 0}
              size="sm"
              className="bg-emerald-500 hover:bg-emerald-600 text-white font-semibold text-xs h-9 px-4 shadow-sm"
            >
              {bulkUpdating ? 'Aplicando...' : 'Aplicar a Selección'}
            </Button>

            <Button
              variant="ghost"
              onClick={() => {
                if (window.confirm(`¿Devolver las ${selectedIds.size} campañas seleccionadas a Rotación General?`)) {
                  setBulkSupervisorIds([]);
                  handleBulkAssign();
                }
              }}
              size="sm"
              className="text-amber-200 hover:text-white hover:bg-white/10 text-xs h-9"
              title="Devolver a rotación general sin supervisores exclusivos"
            >
              🔄 Rotación General
            </Button>

            <Button
              variant="ghost"
              onClick={() => setSelectedIds(new Set())}
              size="sm"
              className="text-white/80 hover:text-white hover:bg-white/10 text-xs h-9"
            >
              Cancelar
            </Button>
          </div>
        </div>
      )}

      {/* ── TABLA DE CAMPAÑAS Y ASIGNACIONES ───────────────────────────────── */}
      <Card className="bg-white dark:bg-slate-900 border-gray-200 dark:border-slate-800 shadow-sm overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="bg-gray-50/80 dark:bg-slate-950/60 text-gray-500 dark:text-slate-400 text-xs uppercase tracking-wider border-b border-gray-200 dark:border-slate-800">
              <tr>
                <th className="py-3.5 pl-4 pr-2 w-10">
                  <input
                    type="checkbox"
                    checked={items.length > 0 && selectedIds.size === items.length}
                    onChange={toggleSelectAll}
                    className="rounded border-gray-300 dark:border-slate-700 text-blue-600 focus:ring-blue-500 cursor-pointer"
                  />
                </th>
                <th className="py-3.5 px-3">Plataforma</th>
                <th className="py-3.5 px-3">Campaña / ID</th>
                <th className="py-3.5 px-3 text-center">Estado</th>
                <th className="py-3.5 px-3 text-center">Leads</th>
                <th className="py-3.5 px-3">Supervisor Designado (Exclusivo)</th>
                <th className="py-3.5 px-3 text-center">Modo de Reparto</th>
                <th className="py-3.5 px-3 text-center">Regla</th>
                <th className="py-3.5 px-3 text-center w-12">Acciones</th>
              </tr>
            </thead>

            <tbody className="divide-y divide-gray-100 dark:divide-slate-800/60">
              {loading ? (
                <tr>
                  <td colSpan={9} className="py-12 text-center text-gray-400 dark:text-slate-500">
                    <LoadingSpinner className="mx-auto mb-2" />
                    <span>Cargando campañas...</span>
                  </td>
                </tr>
              ) : items.length === 0 ? (
                <tr>
                  <td colSpan={9} className="py-12 text-center">
                    <EmptyState
                      icon={Megaphone}
                      title="No se encontraron campañas"
                      description="Haz clic en 'Sincronizar Meta & TikTok' para extraer las campañas de tus cuentas conectadas, o ajusta los filtros."
                    />
                  </td>
                </tr>
              ) : (
                items.map((item) => {
                  const isSelected = selectedIds.has(item.id)
                  const isMeta = item.provider === 'meta'
                  const isActiveStatus = item.status === 'ACTIVE'
                  const hasSupervisor = Boolean(item.supervisor_id)

                  return (
                    <tr
                      key={item.id}
                      className={cn(
                        "transition-colors hover:bg-gray-50/60 dark:hover:bg-slate-800/40",
                        isSelected && "bg-blue-50/40 dark:bg-blue-950/20"
                      )}
                    >
                      {/* Checkbox */}
                      <td className="py-3.5 pl-4 pr-2">
                        <input
                          type="checkbox"
                          checked={isSelected}
                          onChange={() => toggleSelectRow(item.id)}
                          className="rounded border-gray-300 dark:border-slate-700 text-blue-600 focus:ring-blue-500 cursor-pointer"
                        />
                      </td>

                      {/* Plataforma */}
                      <td className="py-3.5 px-3 whitespace-nowrap">
                        {isMeta ? (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold bg-blue-50 dark:bg-blue-950/70 text-blue-700 dark:text-blue-300 border border-blue-200/60 dark:border-blue-900/60">
                            <span className="w-1.5 h-1.5 rounded-full bg-blue-500" />
                            Meta Ads
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-semibold bg-slate-100 dark:bg-cyan-950/70 text-slate-800 dark:text-cyan-300 border border-slate-300/60 dark:border-cyan-900/60">
                            <span className="w-1.5 h-1.5 rounded-full bg-cyan-400" />
                            TikTok Ads
                          </span>
                        )}
                      </td>

                      {/* Campaña y Detalles */}
                      <td className="py-3.5 px-3">
                        <div className="space-y-1">
                          <p className="font-semibold text-gray-900 dark:text-white line-clamp-1 max-w-[340px]" title={item.campaign_name}>
                            {item.campaign_name || item.campaign_id}
                          </p>
                          <div className="flex items-center gap-2 text-xs text-gray-500 dark:text-slate-400">
                            <button
                              onClick={() => copyToClipboard(item.campaign_id, item.id)}
                              className="inline-flex items-center gap-1 font-mono text-[11px] bg-gray-100 dark:bg-slate-800 hover:bg-gray-200 dark:hover:bg-slate-700 px-1.5 py-0.5 rounded transition-colors text-gray-700 dark:text-slate-300"
                              title="Copiar ID de campaña"
                            >
                              {copiedId === item.id ? (
                                <Check size={11} className="text-emerald-500" />
                              ) : (
                                <Copy size={11} />
                              )}
                              <span>{item.campaign_id}</span>
                            </button>

                            {item.objective && (
                              <span className="text-[10px] uppercase tracking-wider text-gray-400 dark:text-slate-500 font-medium">
                                {item.objective}
                              </span>
                            )}
                          </div>
                        </div>
                      </td>

                      {/* Estado */}
                      <td className="py-3.5 px-3 text-center whitespace-nowrap">
                        {isActiveStatus ? (
                          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-[11px] font-semibold bg-emerald-50 dark:bg-emerald-950/60 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-900">
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                            Activa
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-[11px] font-medium bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-400 border border-gray-200 dark:border-slate-700">
                            Pausada / Inactiva
                          </span>
                        )}
                      </td>

                      {/* Contador de Leads */}
                      <td className="py-3.5 px-3 text-center whitespace-nowrap">
                        <span className="inline-flex items-center gap-1 font-bold text-gray-800 dark:text-slate-200">
                          {item.leads_count || 0}
                        </span>
                        {item.last_lead_at && (
                          <p className="text-[10px] text-gray-400 dark:text-slate-500">
                            Último: {new Date(item.last_lead_at).toLocaleDateString()}
                          </p>
                        )}
                      </td>

                      {/* Selector de Supervisor Designado (Multi-supervisor) */}
                      <td className="py-3.5 px-3 min-w-[260px]">
                        {item.supervisors && item.supervisors.length > 0 ? (
                          <div className="space-y-1.5">
                            <div className="flex items-center gap-1.5 flex-wrap">
                              {item.supervisors.map((sup) => {
                                const hasCustomPct = item.supervisors.some(s => s.porcentaje !== null && s.porcentaje !== undefined && Number(s.porcentaje) > 0)
                                return (
                                  <span
                                    key={sup.id}
                                    className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg text-xs font-semibold bg-purple-50 dark:bg-purple-950/70 text-purple-700 dark:text-purple-300 border border-purple-200/70 dark:border-purple-800/80 shadow-xs"
                                    title={`${sup.nombre} (${sup.email})`}
                                  >
                                    <Shield size={11} className="text-purple-600 dark:text-purple-400 shrink-0" />
                                    <span className="max-w-[130px] truncate">{sup.nombre}</span>
                                    {hasCustomPct && sup.porcentaje !== null && sup.porcentaje !== undefined && (
                                      <span className="text-[10px] font-extrabold px-1.5 py-0.2 rounded-md bg-purple-200/80 dark:bg-purple-800/70 text-purple-900 dark:text-purple-100">
                                        {sup.porcentaje}%
                                      </span>
                                    )}
                                  </span>
                                )
                              })}
                              <button
                                type="button"
                                onClick={() => handleOpenSupervisorModal(item)}
                                className="p-1 rounded-md text-gray-400 hover:text-purple-600 hover:bg-purple-50 dark:hover:bg-purple-950/50 transition-colors cursor-pointer"
                                title="Editar supervisores asignados y porcentajes de reparto"
                              >
                                <SlidersHorizontal size={13} />
                              </button>
                            </div>
                            {item.supervisors.length > 1 && (
                              <div className="flex items-center gap-1 text-[10px] font-bold text-indigo-600 dark:text-indigo-400">
                                <span className="w-1.5 h-1.5 rounded-full bg-indigo-500 animate-pulse" />
                                {item.supervisors.some(s => s.porcentaje !== null && s.porcentaje !== undefined && Number(s.porcentaje) > 0) ? (
                                  <span>
                                    {item.supervisors.length} supervisores · Reparto personalizado ({item.supervisors.map(s => `${s.porcentaje ?? 0}%`).join(' / ')})
                                  </span>
                                ) : (
                                  <span>
                                    {item.supervisors.length} supervisores · Reparto equitativo ({Math.round(100 / item.supervisors.length)}% c/u)
                                  </span>
                                )}
                              </div>
                            )}
                          </div>
                        ) : (
                          <button
                            type="button"
                            onClick={() => handleOpenSupervisorModal(item)}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg border border-dashed border-gray-300 dark:border-slate-700 hover:border-blue-400 dark:hover:border-blue-500 bg-gray-50/60 dark:bg-slate-950/40 text-gray-500 dark:text-slate-400 hover:text-blue-600 dark:hover:text-blue-400 text-xs font-medium transition-all cursor-pointer"
                          >
                            <span>🔄 Rotación General</span>
                            <span className="text-[10px] text-blue-600 dark:text-blue-400 font-bold ml-1">+ Designar</span>
                          </button>
                        )}
                      </td>

                      {/* Modo de Reparto */}
                      <td className="py-3.5 px-3 text-center whitespace-nowrap">
                        {hasSupervisor ? (
                          <div className="flex flex-col items-center gap-1">
                            <div className="inline-flex items-center bg-gray-100 dark:bg-slate-800 p-0.5 rounded-lg border border-gray-200 dark:border-slate-700 text-xs">
                              <button
                                type="button"
                                onClick={() => handleDistributionModeChange(item.id, 'supervisor')}
                                className={cn(
                                  "px-2 py-1 rounded-md font-medium text-[11px] transition-all flex items-center gap-1 cursor-pointer",
                                  (item.distribution_mode || 'supervisor') === 'supervisor'
                                    ? "bg-white dark:bg-slate-900 text-purple-700 dark:text-purple-300 font-bold shadow-xs"
                                    : "text-gray-500 dark:text-slate-400 hover:text-gray-900 dark:hover:text-white"
                                )}
                                title="El lead llega directamente a la bandeja del supervisor (reparto equitativo entre ellos)"
                              >
                                <span>👤 Directo</span>
                              </button>
                              <button
                                type="button"
                                onClick={() => handleDistributionModeChange(item.id, 'equipo')}
                                className={cn(
                                  "px-2 py-1 rounded-md font-medium text-[11px] transition-all flex items-center gap-1 cursor-pointer",
                                  item.distribution_mode === 'equipo'
                                    ? "bg-indigo-600 text-white font-bold shadow-xs"
                                    : "text-gray-500 dark:text-slate-400 hover:text-indigo-600 dark:hover:text-indigo-400"
                                )}
                                title="Reparto entre los asesores del equipo de cada supervisor"
                              >
                                <span>👥 En Equipo</span>
                              </button>
                              <button
                                type="button"
                                onClick={() => handleDistributionModeChange(item.id, 'todos')}
                                className={cn(
                                  "px-2 py-1 rounded-md font-medium text-[11px] transition-all flex items-center gap-1 cursor-pointer",
                                  item.distribution_mode === 'todos'
                                    ? "bg-amber-600 text-white font-bold shadow-xs"
                                    : "text-gray-500 dark:text-slate-400 hover:text-amber-600 dark:hover:text-amber-400"
                                )}
                                title="Reparto rotativo entre el supervisor y todos los integrantes de su equipo"
                              >
                                <span>🌟 A Todos</span>
                              </button>
                            </div>
                            {item.supervisors?.some(s => (s.distribution_mode && s.distribution_mode !== item.distribution_mode) || (s.member_percentages && Object.keys(s.member_percentages).length > 0)) ? (
                              <span className="text-[10px] text-amber-700 dark:text-amber-300 font-bold flex items-center gap-1 bg-amber-50 dark:bg-amber-950/60 px-1.5 py-0.5 rounded border border-amber-200 dark:border-amber-900/80" title="Configuración de reparto personalizada para los equipos de esta campaña">
                                <Percent size={10} />
                                <span>Equipos con ajuste propio</span>
                              </span>
                            ) : item.supervisors?.length > 1 && item.distribution_mode !== 'supervisor' ? (
                              <span className="text-[10px] text-indigo-600 dark:text-indigo-400 font-semibold flex items-center gap-0.5">
                                <span>🔄 Intercalado</span>
                              </span>
                            ) : null}
                          </div>
                        ) : (
                          <span className="text-gray-400 dark:text-slate-600 text-xs italic">
                            No aplica
                          </span>
                        )}
                      </td>

                      {/* Toggle Activo */}
                      <td className="py-3.5 px-3 text-center whitespace-nowrap">
                        <button
                          onClick={() => handleToggleActive(item.id, item.is_active)}
                          className={cn(
                            "p-1 rounded-md transition-colors text-xs inline-flex items-center gap-1",
                            item.is_active
                              ? "text-emerald-600 dark:text-emerald-400 hover:bg-emerald-50 dark:hover:bg-emerald-950/40"
                              : "text-gray-400 dark:text-slate-500 hover:bg-gray-100 dark:hover:bg-slate-800"
                          )}
                          title={item.is_active ? "Regla activa: enrutando leads a este supervisor" : "Regla desactivada"}
                        >
                          {item.is_active ? (
                            <CheckCircle2 size={18} className="text-emerald-500" />
                          ) : (
                            <XCircle size={18} className="text-gray-400" />
                          )}
                        </button>
                      </td>

                      {/* Acciones (Eliminar) */}
                      <td className="py-3.5 px-3 text-center whitespace-nowrap">
                        <button
                          onClick={() => handleDeleteCampaign(item.id, item.campaign_name)}
                          className="p-1.5 rounded-lg text-gray-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-950/40 transition-colors"
                          title="Eliminar campaña"
                        >
                          <Trash2 size={16} />
                        </button>
                      </td>
                    </tr>
                  )
                })
              )}
            </tbody>
          </table>
        </div>
      </Card>

      {/* ── MODAL AGREGAR CAMPAÑA MANUAL ───────────────────────────────────── */}
      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/60 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="bg-white dark:bg-slate-900 rounded-2xl max-w-md w-full p-6 shadow-2xl border border-gray-200 dark:border-slate-800 space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-gray-200 dark:border-slate-800">
              <div className="flex items-center gap-2">
                <div className="p-1.5 rounded-lg bg-blue-100 dark:bg-blue-950 text-blue-600 dark:text-blue-400">
                  <Plus size={18} />
                </div>
                <h3 className="font-bold text-gray-900 dark:text-white text-base">
                  Registrar Campaña Manual
                </h3>
              </div>
              <button
                onClick={() => setModalOpen(false)}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-slate-200 text-sm"
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleCreateManual} className="space-y-4 text-sm">
              <div>
                <Label className="text-xs font-semibold text-gray-700 dark:text-slate-300">
                  Plataforma Publicitaria
                </Label>
                <div className="grid grid-cols-2 gap-2 mt-1.5">
                  <button
                    type="button"
                    onClick={() => setNewCampaign(p => ({ ...p, provider: 'meta' }))}
                    className={cn(
                      "py-2 px-3 rounded-lg border text-xs font-semibold text-center transition-all",
                      newCampaign.provider === 'meta'
                        ? "bg-blue-50 border-blue-500 text-blue-700 dark:bg-blue-950/70 dark:text-blue-300 dark:border-blue-500 shadow-xs"
                        : "border-gray-200 dark:border-slate-800 text-gray-600 dark:text-slate-400 hover:bg-gray-50"
                    )}
                  >
                    Meta (Facebook/IG)
                  </button>
                  <button
                    type="button"
                    onClick={() => setNewCampaign(p => ({ ...p, provider: 'tiktok' }))}
                    className={cn(
                      "py-2 px-3 rounded-lg border text-xs font-semibold text-center transition-all",
                      newCampaign.provider === 'tiktok'
                        ? "bg-slate-100 border-slate-800 text-slate-900 dark:bg-cyan-950/70 dark:text-cyan-300 dark:border-cyan-500 shadow-xs"
                        : "border-gray-200 dark:border-slate-800 text-gray-600 dark:text-slate-400 hover:bg-gray-50"
                    )}
                  >
                    TikTok Ads
                  </button>
                </div>
              </div>

              <div>
                <Label className="text-xs font-semibold text-gray-700 dark:text-slate-300">
                  ID de Campaña *
                </Label>
                <Input
                  required
                  placeholder="ej. 120202938484920 o nombre identificador"
                  value={newCampaign.campaign_id}
                  onChange={(e) => setNewCampaign(p => ({ ...p, campaign_id: e.target.value }))}
                  className="mt-1 font-mono text-xs bg-gray-50 dark:bg-slate-950"
                />
              </div>

              <div>
                <Label className="text-xs font-semibold text-gray-700 dark:text-slate-300">
                  Nombre de Campaña (opcional)
                </Label>
                <Input
                  placeholder="ej. Campaña Palma del Río - Verano"
                  value={newCampaign.campaign_name}
                  onChange={(e) => setNewCampaign(p => ({ ...p, campaign_name: e.target.value }))}
                  className="mt-1 text-xs bg-gray-50 dark:bg-slate-950"
                />
              </div>

              <div>
                <div className="flex items-center justify-between mb-1">
                  <Label className="text-xs font-semibold text-gray-700 dark:text-slate-300">
                    Supervisores Designados
                  </Label>
                  <span className="text-[11px] text-gray-500 font-medium">
                    {newCampaign.supervisor_ids.length === 0
                      ? 'Rotación General'
                      : `${newCampaign.supervisor_ids.length} supervisor(es) (${Math.round(100 / newCampaign.supervisor_ids.length)}% c/u)`}
                  </span>
                </div>
                <div className="space-y-1 max-h-[160px] overflow-y-auto p-1.5 border border-gray-200 dark:border-slate-800 rounded-xl bg-gray-50/50 dark:bg-slate-950">
                  {supervisors.map(s => {
                    const isChecked = newCampaign.supervisor_ids.includes(s.id)
                    return (
                      <label
                        key={s.id}
                        className={cn(
                          "flex items-center justify-between px-2.5 py-1.5 rounded-lg text-xs cursor-pointer transition-colors",
                          isChecked
                            ? "bg-purple-50 dark:bg-purple-950/60 font-semibold text-purple-900 dark:text-purple-200 border border-purple-200 dark:border-purple-800"
                            : "hover:bg-gray-100 dark:hover:bg-slate-800/60 text-gray-700 dark:text-slate-300"
                        )}
                      >
                        <div className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            checked={isChecked}
                            onChange={() => {
                              if (isChecked) {
                                setNewCampaign(p => ({ ...p, supervisor_ids: p.supervisor_ids.filter(id => id !== s.id) }))
                              } else {
                                setNewCampaign(p => ({ ...p, supervisor_ids: [...p.supervisor_ids, s.id] }))
                              }
                            }}
                            className="rounded border-gray-300 text-purple-600 focus:ring-purple-500 cursor-pointer"
                          />
                          <span>{s.display_name}</span>
                        </div>
                        <span className="text-[10px] text-gray-400">{s.role}</span>
                      </label>
                    )
                  })}
                </div>
              </div>

              {newCampaign.supervisor_ids.length > 0 && (
                <div>
                  <Label className="text-xs font-semibold text-gray-700 dark:text-slate-300">
                    Modo de Reparto
                  </Label>
                  <div className="grid grid-cols-3 gap-1.5 mt-1.5">
                    <button
                      type="button"
                      onClick={() => setNewCampaign(p => ({ ...p, distribution_mode: 'supervisor' }))}
                      className={cn(
                        "py-2 px-2 rounded-lg border text-[11px] font-semibold text-center transition-all flex flex-col items-center justify-center gap-1 cursor-pointer",
                        newCampaign.distribution_mode === 'supervisor'
                          ? "bg-purple-50 border-purple-500 text-purple-700 dark:bg-purple-950/70 dark:text-purple-300 dark:border-purple-500 shadow-xs"
                          : "border-gray-200 dark:border-slate-800 text-gray-600 dark:text-slate-400 hover:bg-gray-50"
                      )}
                    >
                      <span>👤 Directo</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setNewCampaign(p => ({ ...p, distribution_mode: 'equipo' }))}
                      className={cn(
                        "py-2 px-2 rounded-lg border text-[11px] font-semibold text-center transition-all flex flex-col items-center justify-center gap-1 cursor-pointer",
                        newCampaign.distribution_mode === 'equipo'
                          ? "bg-indigo-50 border-indigo-500 text-indigo-700 dark:bg-indigo-950/70 dark:text-indigo-300 dark:border-indigo-500 shadow-xs"
                          : "border-gray-200 dark:border-slate-800 text-gray-600 dark:text-slate-400 hover:bg-gray-50"
                      )}
                    >
                      <span>👥 En Equipo</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => setNewCampaign(p => ({ ...p, distribution_mode: 'todos' }))}
                      className={cn(
                        "py-2 px-2 rounded-lg border text-[11px] font-semibold text-center transition-all flex flex-col items-center justify-center gap-1 cursor-pointer",
                        newCampaign.distribution_mode === 'todos'
                          ? "bg-amber-50 border-amber-500 text-amber-700 dark:bg-amber-950/70 dark:text-amber-300 dark:border-amber-500 shadow-xs"
                          : "border-gray-200 dark:border-slate-800 text-gray-600 dark:text-slate-400 hover:bg-gray-50"
                      )}
                    >
                      <span>🌟 A Todos</span>
                    </button>
                  </div>
                </div>
              )}

              <div className="flex items-center justify-end gap-2.5 pt-3 border-t border-gray-200 dark:border-slate-800">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setModalOpen(false)}
                  className="text-xs"
                >
                  Cancelar
                </Button>
                <Button
                  type="submit"
                  disabled={savingManual || !newCampaign.campaign_id.trim()}
                  className="bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold"
                >
                  {savingManual ? 'Guardando...' : 'Guardar Campaña'}
                </Button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* ── MODAL DESIGNAR SUPERVISORES A UNA CAMPAÑA ─────────────────────── */}
      {supervisorModalCampaign && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/60 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="bg-white dark:bg-slate-900 rounded-2xl max-w-2xl w-full p-6 shadow-2xl border border-gray-200 dark:border-slate-800 flex flex-col max-h-[92vh]">
            {/* Cabecera Modal */}
            <div className="flex items-center justify-between pb-3 border-b border-gray-200 dark:border-slate-800 shrink-0">
              <div className="flex items-center gap-2.5">
                <div className="p-2 rounded-xl bg-purple-100 dark:bg-purple-950 text-purple-700 dark:text-purple-300">
                  <UserCheck size={20} />
                </div>
                <div>
                  <h3 className="font-bold text-gray-900 dark:text-white text-base">
                    Designar Supervisores y Equipos
                  </h3>
                  <p className="text-xs text-gray-500 dark:text-slate-400 line-clamp-1 max-w-[420px]">
                    {supervisorModalCampaign.campaign_name || supervisorModalCampaign.campaign_id}
                  </p>
                </div>
              </div>
              <button
                onClick={() => setSupervisorModalCampaign(null)}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-slate-200 text-sm cursor-pointer"
              >
                ✕
              </button>
            </div>

            {/* Cuerpo Scrollable */}
            <div className="flex-1 overflow-y-auto pr-1 space-y-4 my-2">
              {/* Buscador de supervisores */}
              <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={15} />
                <Input
                  value={supervisorSearch}
                  onChange={(e) => setSupervisorSearch(e.target.value)}
                  placeholder="Buscar supervisor..."
                  className="pl-8 text-xs h-9 bg-gray-50 dark:bg-slate-950"
                />
              </div>

              {/* Lista de supervisores con checkboxes */}
              <div className="space-y-1.5 max-h-[190px] overflow-y-auto pr-1">
                {supervisors
                  .filter(s =>
                    !supervisorSearch.trim() ||
                    s.display_name.toLowerCase().includes(supervisorSearch.toLowerCase()) ||
                    s.email.toLowerCase().includes(supervisorSearch.toLowerCase())
                  )
                  .map((s) => {
                    const isChecked = modalSupervisorIds.includes(s.id)
                    const memberCount = s.team_members?.length || 0
                    return (
                      <label
                        key={s.id}
                        className={cn(
                          "flex items-center justify-between p-2.5 rounded-xl border transition-all cursor-pointer text-xs",
                          isChecked
                            ? "bg-purple-50/80 dark:bg-purple-950/50 border-purple-300 dark:border-purple-800 text-purple-950 dark:text-purple-200 font-semibold"
                            : "bg-gray-50/50 dark:bg-slate-950/40 border-gray-200 dark:border-slate-800 text-gray-700 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-800/50"
                        )}
                      >
                        <div className="flex items-center gap-2.5">
                          <input
                            type="checkbox"
                            checked={isChecked}
                            onChange={() => {
                              if (isChecked) {
                                setModalSupervisorIds(prev => prev.filter(id => id !== s.id))
                              } else {
                                setModalSupervisorIds(prev => [...prev, s.id])
                              }
                            }}
                            className="rounded border-gray-300 text-purple-600 focus:ring-purple-500 cursor-pointer"
                          />
                          <div>
                            <div className="flex items-center gap-1.5">
                              <p className="font-semibold">{s.display_name}</p>
                              <span className="text-[10px] px-1.5 py-0.2 rounded-md bg-gray-100 dark:bg-slate-800 text-gray-600 dark:text-slate-400 font-normal">
                                {memberCount} asesor(es)
                              </span>
                            </div>
                            <p className="text-[11px] text-gray-400 dark:text-slate-500 font-normal">{s.email} • {s.role}</p>
                          </div>
                        </div>
                        {isChecked && (
                          <span className="text-[11px] font-bold text-purple-600 dark:text-purple-400">
                            Designado
                          </span>
                        )}
                      </label>
                    )
                  })}
              </div>

              {/* Criterio de Reparto entre Supervisores (cuando hay más de 1) */}
              {modalSupervisorIds.length > 1 && (
                <div className="space-y-2 pt-2 border-t border-gray-200 dark:border-slate-800">
                  <div className="flex items-center justify-between">
                    <Label className="text-xs font-bold text-gray-700 dark:text-slate-300 flex items-center gap-1.5">
                      <Scale size={13} className="text-indigo-600 dark:text-indigo-400" />
                      <span>Criterio de Reparto entre Supervisores</span>
                    </Label>
                    {modalDistType === 'personalizado' && (
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        onClick={() => setModalPercentages(autoBalancePercentages(modalSupervisorIds))}
                        className="h-6 px-2 text-[11px] font-semibold text-indigo-600 hover:text-indigo-700 hover:bg-indigo-50 dark:hover:bg-indigo-950/50 cursor-pointer"
                      >
                        ⚖️ Auto-nivelar
                      </Button>
                    )}
                  </div>

                  <div className="grid grid-cols-2 gap-2">
                    <button
                      type="button"
                      onClick={() => setModalDistType('equitativo')}
                      className={cn(
                        "p-2.5 rounded-xl border text-xs text-left transition-all cursor-pointer",
                        modalDistType === 'equitativo'
                          ? "bg-purple-50 dark:bg-purple-950/70 border-purple-400 dark:border-purple-700 text-purple-900 dark:text-purple-200 font-bold shadow-xs"
                          : "border-gray-200 dark:border-slate-800 text-gray-600 dark:text-slate-400 hover:bg-gray-50 dark:hover:bg-slate-800/40"
                      )}
                    >
                      <div className="flex items-center gap-1.5 font-semibold">
                        <span>⚖️ Reparto Equitativo</span>
                      </div>
                      <p className="text-[11px] text-gray-500 dark:text-slate-400 font-normal mt-0.5">
                        Partes iguales ({Math.round(100 / modalSupervisorIds.length)}% cada uno)
                      </p>
                    </button>

                    <button
                      type="button"
                      onClick={() => {
                        setModalDistType('personalizado')
                        setModalPercentages(prev => {
                          const hasKeys = Object.keys(prev).length > 0 && modalSupervisorIds.every(id => prev[id] !== undefined)
                          return hasKeys ? prev : autoBalancePercentages(modalSupervisorIds)
                        })
                      }}
                      className={cn(
                        "p-2.5 rounded-xl border text-xs text-left transition-all cursor-pointer",
                        modalDistType === 'personalizado'
                          ? "bg-indigo-50 dark:bg-indigo-950/70 border-indigo-400 dark:border-indigo-700 text-indigo-900 dark:text-indigo-200 font-bold shadow-xs"
                          : "border-gray-200 dark:border-slate-800 text-gray-600 dark:text-slate-400 hover:bg-gray-50 dark:hover:bg-slate-800/40"
                      )}
                    >
                      <div className="flex items-center gap-1.5 font-semibold">
                        <span>🎯 Personalizado (%)</span>
                      </div>
                      <p className="text-[11px] text-gray-500 dark:text-slate-400 font-normal mt-0.5">
                        Ajustar cuota exacta (ej. 45%, 45%, 10%)
                      </p>
                    </button>
                  </div>

                  {/* Editor de porcentajes entre supervisores */}
                  {modalDistType === 'personalizado' && (
                    <div className="p-3 rounded-xl bg-slate-50 dark:bg-slate-950/60 border border-indigo-200 dark:border-indigo-900/60 space-y-2.5">
                      <div className="flex items-center justify-between text-xs">
                        <span className="font-bold text-gray-700 dark:text-slate-300">
                          Porcentajes por Supervisor:
                        </span>
                        <span
                          className={cn(
                            "px-2 py-0.5 rounded-full text-[11px] font-bold border transition-colors",
                            modalTotalPercentage === 100
                              ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300 border-emerald-300 dark:border-emerald-800"
                              : modalTotalPercentage < 100
                                ? "bg-amber-100 text-amber-800 dark:bg-amber-950/80 dark:text-amber-300 border-amber-300 dark:border-amber-800"
                                : "bg-rose-100 text-rose-800 dark:bg-rose-950/80 dark:text-rose-300 border-rose-300 dark:border-rose-800"
                          )}
                        >
                          Total: {modalTotalPercentage}% {modalTotalPercentage === 100 ? '✓' : `(faltan ${100 - modalTotalPercentage}%)`}
                        </span>
                      </div>

                      {/* Barra visual de distribución proporcional */}
                      <div className="h-2 w-full rounded-full bg-gray-200 dark:bg-slate-800 overflow-hidden flex">
                        {modalSupervisorIds.map((id, idx) => {
                          const supObj = supervisors.find(s => s.id === id)
                          const pct = Number(modalPercentages[id]) || 0
                          if (pct <= 0) return null
                          const colors = [
                            'bg-purple-500',
                            'bg-indigo-500',
                            'bg-amber-500',
                            'bg-emerald-500',
                            'bg-pink-500',
                            'bg-cyan-500',
                          ]
                          const colorClass = colors[idx % colors.length]
                          return (
                            <div
                              key={id}
                              style={{ width: `${Math.min(100, pct)}%` }}
                              className={cn("h-full transition-all duration-300", colorClass)}
                              title={`${supObj?.display_name || 'Supervisor'}: ${pct}%`}
                            />
                          )
                        })}
                      </div>

                      {/* Lista de inputs con colores */}
                      <div className="space-y-1.5 max-h-[140px] overflow-y-auto pr-1">
                        {modalSupervisorIds.map((id, idx) => {
                          const supObj = supervisors.find(s => s.id === id)
                          const pct = modalPercentages[id] ?? ''
                          const dotColors = [
                            'bg-purple-500',
                            'bg-indigo-500',
                            'bg-amber-500',
                            'bg-emerald-500',
                            'bg-pink-500',
                            'bg-cyan-500',
                          ]
                          const dotColor = dotColors[idx % dotColors.length]
                          return (
                            <div
                              key={id}
                              className="flex items-center justify-between p-2 rounded-lg bg-white dark:bg-slate-900 border border-gray-200 dark:border-slate-800"
                            >
                              <div className="flex items-center gap-2 min-w-0 pr-2">
                                <span className={cn("w-2 h-2 rounded-full shrink-0", dotColor)} />
                                <Shield size={12} className="text-purple-600 dark:text-purple-400 shrink-0" />
                                <span className="text-xs font-semibold truncate text-gray-800 dark:text-slate-200">
                                  {supObj?.display_name || id}
                                </span>
                              </div>
                              <div className="flex items-center gap-1.5 shrink-0">
                                <Input
                                  type="number"
                                  min="0"
                                  max="100"
                                  value={pct}
                                  onChange={(e) => {
                                    const raw = e.target.value
                                    const parsed = raw === '' ? '' : Math.max(0, Math.min(100, parseInt(raw, 10) || 0))
                                    setModalPercentages(prev => ({ ...prev, [id]: parsed }))
                                  }}
                                  className="w-16 h-7 text-center text-xs font-bold bg-gray-50 dark:bg-slate-950 px-1"
                                />
                                <span className="text-xs font-bold text-gray-500">%</span>
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Modo General de Entrega de Leads de la Campaña (3 opciones) */}
              {modalSupervisorIds.length > 0 && (
                <div className="space-y-1.5 pt-2 border-t border-gray-200 dark:border-slate-800">
                  <Label className="text-xs font-bold text-gray-700 dark:text-slate-300">
                    Modo General de Entrega de Leads
                  </Label>
                  <div className="grid grid-cols-3 gap-2">
                    <button
                      type="button"
                      onClick={() => setModalDistMode('supervisor')}
                      className={cn(
                        "p-2.5 rounded-xl border text-xs text-left transition-all cursor-pointer",
                        modalDistMode === 'supervisor'
                          ? "bg-purple-50 dark:bg-purple-950/70 border-purple-400 dark:border-purple-700 text-purple-900 dark:text-purple-200 font-bold shadow-xs"
                          : "border-gray-200 dark:border-slate-800 text-gray-600 dark:text-slate-400 hover:bg-gray-50"
                      )}
                    >
                      <div className="flex items-center gap-1 font-semibold text-[11px]">
                        <span>👤 Directo al Supervisor</span>
                      </div>
                      <p className="text-[10px] text-gray-500 dark:text-slate-400 font-normal mt-0.5">
                        Llega a la bandeja personal del supervisor.
                      </p>
                    </button>
                    <button
                      type="button"
                      onClick={() => setModalDistMode('equipo')}
                      className={cn(
                        "p-2.5 rounded-xl border text-xs text-left transition-all cursor-pointer",
                        modalDistMode === 'equipo'
                          ? "bg-indigo-50 dark:bg-indigo-950/70 border-indigo-400 dark:border-indigo-700 text-indigo-900 dark:text-indigo-200 font-bold shadow-xs"
                          : "border-gray-200 dark:border-slate-800 text-gray-600 dark:text-slate-400 hover:bg-gray-50"
                      )}
                    >
                      <div className="flex items-center gap-1 font-semibold text-[11px]">
                        <span>👥 Solo al Equipo</span>
                      </div>
                      <p className="text-[10px] text-gray-500 dark:text-slate-400 font-normal mt-0.5">
                        Reparto entre los asesores del equipo.
                      </p>
                    </button>
                    <button
                      type="button"
                      onClick={() => setModalDistMode('todos')}
                      className={cn(
                        "p-2.5 rounded-xl border text-xs text-left transition-all cursor-pointer",
                        modalDistMode === 'todos'
                          ? "bg-amber-50 dark:bg-amber-950/70 border-amber-400 dark:border-amber-700 text-amber-900 dark:text-amber-200 font-bold shadow-xs"
                          : "border-gray-200 dark:border-slate-800 text-gray-600 dark:text-slate-400 hover:bg-gray-50"
                      )}
                    >
                      <div className="flex items-center gap-1 font-semibold text-[11px]">
                        <span>🌟 A Todos (Sup + Equipo)</span>
                      </div>
                      <p className="text-[10px] text-gray-500 dark:text-slate-400 font-normal mt-0.5">
                        Reparto entre supervisor y sus asesores.
                      </p>
                    </button>
                  </div>
                </div>
              )}

              {/* ── SECCIÓN: REPARTO PERSONALIZADO POR EQUIPO ── */}
              {modalSupervisorIds.length > 0 && (
                <div className="space-y-3 pt-3 border-t border-gray-200 dark:border-slate-800">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <Users size={15} className="text-indigo-600 dark:text-indigo-400" />
                      <Label className="text-xs font-bold text-gray-800 dark:text-slate-200">
                        Configuración de Reparto por Equipo
                      </Label>
                    </div>
                    <span className="text-[11px] text-gray-500 dark:text-slate-400">
                      Personaliza el modo y cuotas (%) de cada equipo individualmente
                    </span>
                  </div>

                  <div className="space-y-2.5">
                    {modalSupervisorIds.map((supId) => {
                      const supObj = supervisors.find(s => s.id === supId)
                      const isExpanded = expandedTeams.has(supId)
                      const teamMembers = supObj?.team_members || []
                      const tMode = modalTeamModes[supId] || 'heredar'
                      const effectiveMode = tMode === 'heredar' ? modalDistMode : tMode
                      const distType = modalTeamDistType[supId] || 'equitativo'
                      const memberPcts = modalTeamMemberPercentages[supId] || {}

                      // Determinar candidatos elegibles para reparto de este equipo
                      const candidates = []
                      if (effectiveMode === 'todos') {
                        candidates.push({
                          id: supId,
                          display_name: `${supObj?.display_name || 'Supervisor'}`,
                          email: supObj?.email,
                          is_supervisor: true,
                          role: 'supervisor',
                        })
                      }
                      if (effectiveMode === 'todos' || effectiveMode === 'equipo') {
                        teamMembers.forEach(m => {
                          candidates.push({
                            id: m.id,
                            display_name: m.display_name,
                            email: m.email,
                            is_supervisor: false,
                            role: 'asesor',
                          })
                        })
                      }

                      // Suma de porcentajes del equipo
                      const teamTotalPct = candidates.reduce((sum, c) => {
                        const v = memberPcts[c.id]
                        return sum + (v === '' || v === undefined ? 0 : parseInt(v, 10) || 0)
                      }, 0)

                      return (
                        <div
                          key={supId}
                          className="rounded-xl border border-gray-200 dark:border-slate-800 bg-gray-50/50 dark:bg-slate-950/40 overflow-hidden transition-all shadow-xs"
                        >
                          {/* Cabecera del Equipo / Supervisor */}
                          <div
                            onClick={() => toggleTeamAccordion(supId)}
                            className="p-3 bg-white dark:bg-slate-900 flex items-center justify-between cursor-pointer hover:bg-gray-50 dark:hover:bg-slate-800/50 transition-colors"
                          >
                            <div className="flex items-center gap-2.5 min-w-0">
                              <div className="w-7 h-7 rounded-lg bg-indigo-50 dark:bg-indigo-950/80 text-indigo-600 dark:text-indigo-400 flex items-center justify-center font-bold text-xs shrink-0">
                                <Shield size={14} />
                              </div>
                              <div className="min-w-0">
                                <p className="text-xs font-bold text-gray-900 dark:text-white truncate">
                                  Equipo de {supObj?.display_name || supId}
                                </p>
                                <div className="flex items-center gap-1.5 text-[10px] text-gray-500 dark:text-slate-400">
                                  <span>{teamMembers.length} asesor(es) registrado(s)</span>
                                  <span>•</span>
                                  <span className={cn(
                                    "font-semibold",
                                    effectiveMode === 'todos' ? "text-amber-600 dark:text-amber-400" :
                                    effectiveMode === 'equipo' ? "text-indigo-600 dark:text-indigo-400" :
                                    "text-purple-600 dark:text-purple-400"
                                  )}>
                                    {effectiveMode === 'todos' ? '🌟 A Todos (Sup + Equipo)' :
                                     effectiveMode === 'equipo' ? '👥 Solo Equipo' :
                                     '👤 Directo a Sup'}
                                  </span>
                                  {tMode !== 'heredar' && (
                                    <span className="text-[9px] bg-blue-100 dark:bg-blue-900/60 text-blue-700 dark:text-blue-300 px-1 py-0.2 rounded font-bold">
                                      Modo Propio
                                    </span>
                                  )}
                                  {distType === 'personalizado' && (
                                    <span className="text-[9px] bg-purple-100 dark:bg-purple-900/60 text-purple-700 dark:text-purple-300 px-1 py-0.2 rounded font-bold">
                                      Cuota %
                                    </span>
                                  )}
                                </div>
                              </div>
                            </div>

                            <div className="flex items-center gap-2 shrink-0">
                              {isExpanded ? (
                                <ChevronUp size={16} className="text-gray-400" />
                              ) : (
                                <ChevronDown size={16} className="text-gray-400" />
                              )}
                            </div>
                          </div>

                          {/* Contenido Expandido del Equipo */}
                          {isExpanded && (
                            <div className="p-3.5 space-y-3 border-t border-gray-100 dark:border-slate-800/80 bg-gray-50/70 dark:bg-slate-950/60 text-xs">
                              {/* Selector de modo para este equipo */}
                              <div>
                                <Label className="text-[11px] font-bold text-gray-700 dark:text-slate-300 block mb-1">
                                  Modo de reparto para este equipo:
                                </Label>
                                <div className="grid grid-cols-4 gap-1.5">
                                  <button
                                    type="button"
                                    onClick={() => setModalTeamModes(prev => ({ ...prev, [supId]: 'heredar' }))}
                                    className={cn(
                                      "p-1.5 rounded-lg border text-[11px] font-medium text-center transition-all cursor-pointer",
                                      tMode === 'heredar'
                                        ? "bg-white dark:bg-slate-900 border-indigo-400 text-indigo-700 dark:text-indigo-300 font-bold shadow-xs"
                                        : "border-gray-200 dark:border-slate-800 text-gray-600 dark:text-slate-400 hover:bg-white"
                                    )}
                                  >
                                    🔄 Heredar ({modalDistMode === 'todos' ? 'A Todos' : modalDistMode === 'equipo' ? 'Equipo' : 'Directo'})
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => setModalTeamModes(prev => ({ ...prev, [supId]: 'supervisor' }))}
                                    className={cn(
                                      "p-1.5 rounded-lg border text-[11px] font-medium text-center transition-all cursor-pointer",
                                      tMode === 'supervisor'
                                        ? "bg-purple-50 dark:bg-purple-950/70 border-purple-400 text-purple-700 dark:text-purple-300 font-bold shadow-xs"
                                        : "border-gray-200 dark:border-slate-800 text-gray-600 dark:text-slate-400 hover:bg-white"
                                    )}
                                  >
                                    👤 Directo
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => setModalTeamModes(prev => ({ ...prev, [supId]: 'equipo' }))}
                                    className={cn(
                                      "p-1.5 rounded-lg border text-[11px] font-medium text-center transition-all cursor-pointer",
                                      tMode === 'equipo'
                                        ? "bg-indigo-50 dark:bg-indigo-950/70 border-indigo-400 text-indigo-700 dark:text-indigo-300 font-bold shadow-xs"
                                        : "border-gray-200 dark:border-slate-800 text-gray-600 dark:text-slate-400 hover:bg-white"
                                    )}
                                  >
                                    👥 Solo Equipo
                                  </button>
                                  <button
                                    type="button"
                                    onClick={() => setModalTeamModes(prev => ({ ...prev, [supId]: 'todos' }))}
                                    className={cn(
                                      "p-1.5 rounded-lg border text-[11px] font-medium text-center transition-all cursor-pointer",
                                      tMode === 'todos'
                                        ? "bg-amber-50 dark:bg-amber-950/70 border-amber-400 text-amber-700 dark:text-amber-300 font-bold shadow-xs"
                                        : "border-gray-200 dark:border-slate-800 text-gray-600 dark:text-slate-400 hover:bg-white"
                                    )}
                                  >
                                    🌟 A Todos
                                  </button>
                                </div>
                              </div>

                              {/* Si el modo del equipo es directo al supervisor */}
                              {effectiveMode === 'supervisor' && (
                                <p className="text-[11px] text-gray-500 dark:text-slate-400 bg-white dark:bg-slate-900 p-2 rounded-lg border border-gray-200 dark:border-slate-800">
                                  ℹ️ Los leads asignados a este equipo llegarán 100% directamente a la bandeja de <b>{supObj?.display_name}</b>.
                                </p>
                              )}

                              {/* Si el modo es equipo o todos, permitir configurar criterio entre sus integrantes */}
                              {(effectiveMode === 'equipo' || effectiveMode === 'todos') && (
                                <div className="space-y-2 pt-1 border-t border-gray-200/80 dark:border-slate-800">
                                  {candidates.length === 0 ? (
                                    <div className="p-2.5 rounded-lg bg-amber-50 dark:bg-amber-950/40 border border-amber-200 dark:border-amber-900 text-[11px] text-amber-800 dark:text-amber-300">
                                      ⚠️ Este supervisor no tiene asesores activos asignados en su equipo. Se recomienda añadir asesores en el módulo Equipos o usar el modo "🌟 A Todos" para que el supervisor también reciba leads.
                                    </div>
                                  ) : (
                                    <>
                                      <div className="flex items-center justify-between">
                                        <Label className="text-[11px] font-bold text-gray-700 dark:text-slate-300 flex items-center gap-1">
                                          <Scale size={12} className="text-indigo-600" />
                                          <span>Criterio interno ({candidates.length} integrante{candidates.length > 1 ? 's' : ''}):</span>
                                        </Label>
                                        {distType === 'personalizado' && candidates.length > 1 && (
                                          <Button
                                            type="button"
                                            variant="ghost"
                                            size="sm"
                                            onClick={() => {
                                              const balanced = autoBalanceTeamMemberPercentages(candidates)
                                              setModalTeamMemberPercentages(prev => ({
                                                ...prev,
                                                [supId]: balanced,
                                              }))
                                            }}
                                            className="h-5 px-2 text-[10px] font-bold text-indigo-600 hover:bg-indigo-50 dark:hover:bg-indigo-950/50 cursor-pointer"
                                          >
                                            ⚖️ Auto-nivelar
                                          </Button>
                                        )}
                                      </div>

                                      <div className="grid grid-cols-2 gap-2">
                                        <button
                                          type="button"
                                          onClick={() => setModalTeamDistType(prev => ({ ...prev, [supId]: 'equitativo' }))}
                                          className={cn(
                                            "p-2 rounded-lg border text-left transition-all cursor-pointer",
                                            distType === 'equitativo'
                                              ? "bg-white dark:bg-slate-900 border-indigo-400 text-indigo-900 dark:text-indigo-200 font-bold shadow-xs"
                                              : "border-gray-200 dark:border-slate-800 text-gray-600 dark:text-slate-400 hover:bg-white"
                                          )}
                                        >
                                          <div className="font-semibold text-[11px]">⚖️ Equitativo</div>
                                          <div className="text-[10px] text-gray-400 font-normal">
                                            Rotación parejo ({Math.round(100 / candidates.length)}% c/u)
                                          </div>
                                        </button>
                                        <button
                                          type="button"
                                          onClick={() => {
                                            setModalTeamDistType(prev => ({ ...prev, [supId]: 'personalizado' }))
                                            setModalTeamMemberPercentages(prev => {
                                              const existing = prev[supId] || {}
                                              const allPresent = candidates.every(c => existing[c.id] !== undefined)
                                              if (allPresent && Object.keys(existing).length > 0) return prev
                                              return {
                                                ...prev,
                                                [supId]: autoBalanceTeamMemberPercentages(candidates),
                                              }
                                            })
                                          }}
                                          className={cn(
                                            "p-2 rounded-lg border text-left transition-all cursor-pointer",
                                            distType === 'personalizado'
                                              ? "bg-white dark:bg-slate-900 border-indigo-400 text-indigo-900 dark:text-indigo-200 font-bold shadow-xs"
                                              : "border-gray-200 dark:border-slate-800 text-gray-600 dark:text-slate-400 hover:bg-white"
                                          )}
                                        >
                                          <div className="font-semibold text-[11px]">🎯 Personalizado (%)</div>
                                          <div className="text-[10px] text-gray-400 font-normal">
                                            Cuotas exactas por miembro
                                          </div>
                                        </button>
                                      </div>

                                      {/* Inputs de porcentajes si es personalizado */}
                                      {distType === 'personalizado' && (
                                        <div className="p-2.5 rounded-lg bg-white dark:bg-slate-900 border border-indigo-200 dark:border-indigo-900/60 space-y-2">
                                          <div className="flex items-center justify-between text-[11px]">
                                            <span className="font-bold text-gray-700 dark:text-slate-300">
                                              Cuotas por Integrante:
                                            </span>
                                            <span className={cn(
                                              "px-1.5 py-0.2 rounded-full text-[10px] font-bold border",
                                              teamTotalPct === 100
                                                ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/80 dark:text-emerald-300 border-emerald-300"
                                                : "bg-amber-100 text-amber-800 dark:bg-amber-950/80 dark:text-amber-300 border-amber-300"
                                            )}>
                                              Total: {teamTotalPct}% {teamTotalPct === 100 ? '✓' : `(faltan ${100 - teamTotalPct}%)`}
                                            </span>
                                          </div>

                                          {/* Barra de progreso de porcentajes */}
                                          <div className="h-1.5 w-full rounded-full bg-gray-100 dark:bg-slate-800 overflow-hidden flex">
                                            {candidates.map((cand, cIdx) => {
                                              const pctVal = Number(memberPcts[cand.id]) || 0
                                              if (pctVal <= 0) return null
                                              const colClasses = ['bg-indigo-500', 'bg-purple-500', 'bg-amber-500', 'bg-emerald-500', 'bg-rose-500', 'bg-cyan-500']
                                              return (
                                                <div
                                                  key={cand.id}
                                                  style={{ width: `${Math.min(100, pctVal)}%` }}
                                                  className={cn("h-full transition-all duration-300", colClasses[cIdx % colClasses.length])}
                                                  title={`${cand.display_name}: ${pctVal}%`}
                                                />
                                              )
                                            })}
                                          </div>

                                          <div className="space-y-1.5 max-h-[140px] overflow-y-auto pr-1">
                                            {candidates.map((cand, cIdx) => {
                                              const val = memberPcts[cand.id] ?? ''
                                              const dotClasses = ['bg-indigo-500', 'bg-purple-500', 'bg-amber-500', 'bg-emerald-500', 'bg-rose-500', 'bg-cyan-500']
                                              return (
                                                <div
                                                  key={cand.id}
                                                  className="flex items-center justify-between p-1.5 rounded-md bg-gray-50/80 dark:bg-slate-950/60 border border-gray-200 dark:border-slate-800"
                                                >
                                                  <div className="flex items-center gap-1.5 min-w-0 pr-2">
                                                    <span className={cn("w-1.5 h-1.5 rounded-full shrink-0", dotClasses[cIdx % dotClasses.length])} />
                                                    <span className="truncate font-semibold text-gray-800 dark:text-slate-200 text-[11px]">
                                                      {cand.display_name}
                                                    </span>
                                                    {cand.is_supervisor && (
                                                      <span className="text-[9px] bg-purple-100 dark:bg-purple-900/60 text-purple-700 dark:text-purple-300 px-1 py-0.2 rounded font-bold shrink-0">
                                                        Supervisor
                                                      </span>
                                                    )}
                                                  </div>
                                                  <div className="flex items-center gap-1 shrink-0">
                                                    <Input
                                                      type="number"
                                                      min="0"
                                                      max="100"
                                                      value={val}
                                                      onChange={(e) => {
                                                        const raw = e.target.value
                                                        const parsed = raw === '' ? '' : Math.max(0, Math.min(100, parseInt(raw, 10) || 0))
                                                        setModalTeamMemberPercentages(prev => ({
                                                          ...prev,
                                                          [supId]: {
                                                            ...(prev[supId] || {}),
                                                            [cand.id]: parsed,
                                                          },
                                                        }))
                                                      }}
                                                      className="w-14 h-6 text-center text-xs font-bold bg-white dark:bg-slate-900 px-1"
                                                    />
                                                    <span className="text-gray-400 font-bold text-[10px]">%</span>
                                                  </div>
                                                </div>
                                              )
                                            })}
                                          </div>
                                        </div>
                                      )}
                                    </>
                                  )}
                                </div>
                              )}
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}

              {/* Mensaje explicativo del reparto */}
              <div className="p-3 rounded-xl bg-blue-50/70 dark:bg-blue-950/40 border border-blue-200 dark:border-blue-900 text-xs text-blue-900 dark:text-blue-200 space-y-1">
                {modalSupervisorIds.length === 0 ? (
                  <p>🔄 <b>Rotación General:</b> Los leads de esta campaña no tendrán supervisor exclusivo y se repartirán según la rotación estándar del CRM.</p>
                ) : (
                  <>
                    <div className="flex items-center gap-1.5 font-bold text-indigo-800 dark:text-indigo-300">
                      <Sparkles size={14} />
                      <span>
                        {modalDistType === 'personalizado' && modalSupervisorIds.length > 1
                          ? `Reparto entre Supervisores: Personalizado (${modalSupervisorIds.length} supervisores · ${modalTotalPercentage}%):`
                          : modalSupervisorIds.length > 1
                            ? `Reparto entre Supervisores: Equitativo (${modalSupervisorIds.length} supervisores · ${Math.round(100 / modalSupervisorIds.length)}% cada uno):`
                            : `1 Supervisor / Equipo asignado:`}
                      </span>
                    </div>
                    {modalDistMode === 'todos' ? (
                      <p className="text-[11px] leading-relaxed text-amber-900 dark:text-amber-200">
                        🌟 <b>Modo A Todos (Supervisor y Equipo):</b> Los leads se repartirán rotando entre el supervisor y los integrantes de su equipo (equitativamente o según las cuotas individuales configuradas).
                      </p>
                    ) : modalDistMode === 'equipo' ? (
                      <p className="text-[11px] leading-relaxed text-indigo-900 dark:text-indigo-200">
                        👥 <b>Modo En Equipo:</b> Los leads se repartirán rotando entre los asesores activos del equipo (excluyendo la bandeja del supervisor, salvo que se personalice para un equipo específico).
                      </p>
                    ) : (
                      <p className="text-[11px] leading-relaxed text-purple-900 dark:text-purple-200">
                        👤 <b>Modo Directo:</b> Los leads se asignarán directamente al supervisor designado.
                      </p>
                    )}
                  </>
                )}
              </div>
            </div>

            {/* Botones de acción */}
            <div className="flex items-center justify-between pt-3 border-t border-gray-200 dark:border-slate-800 shrink-0">
              <Button
                type="button"
                variant="ghost"
                onClick={() => setModalSupervisorIds([])}
                className="text-xs text-gray-500 hover:text-amber-700 dark:hover:text-amber-400 cursor-pointer"
              >
                Limpiar (Rotación General)
              </Button>
              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  variant="outline"
                  onClick={() => setSupervisorModalCampaign(null)}
                  className="text-xs cursor-pointer"
                >
                  Cancelar
                </Button>
                <Button
                  type="button"
                  onClick={handleSaveSupervisorsModal}
                  disabled={savingSupervisors || (modalDistType === 'personalizado' && modalSupervisorIds.length > 1 && modalTotalPercentage !== 100)}
                  className="bg-purple-600 hover:bg-purple-700 text-white text-xs font-semibold cursor-pointer disabled:opacity-50"
                >
                  {savingSupervisors ? 'Guardando...' : 'Guardar Asignación'}
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ── MODAL ASIGNACIÓN MASIVA DE SUPERVISORES ────────────────────────── */}
      {bulkModalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-slate-950/60 backdrop-blur-xs animate-in fade-in duration-150">
          <div className="bg-white dark:bg-slate-900 rounded-2xl max-w-md w-full p-6 shadow-2xl border border-gray-200 dark:border-slate-800 space-y-4">
            <div className="flex items-center justify-between pb-3 border-b border-gray-200 dark:border-slate-800">
              <div className="flex items-center gap-2">
                <div className="p-1.5 rounded-lg bg-blue-100 dark:bg-blue-950 text-blue-600 dark:text-blue-400">
                  <Users size={18} />
                </div>
                <h3 className="font-bold text-gray-900 dark:text-white text-base">
                  Asignar a {selectedIds.size} Campañas
                </h3>
              </div>
              <button
                onClick={() => setBulkModalOpen(false)}
                className="text-gray-400 hover:text-gray-600 dark:hover:text-slate-200 text-sm cursor-pointer"
              >
                ✕
              </button>
            </div>

            <p className="text-xs text-gray-500 dark:text-slate-400">
              Selecciona uno o más supervisores para designarlos a todas las campañas seleccionadas. Si seleccionas más de uno, los leads se repartirán de forma equitativa.
            </p>

            {/* Buscador */}
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={15} />
              <Input
                value={bulkSupSearch}
                onChange={(e) => setBulkSupSearch(e.target.value)}
                placeholder="Buscar supervisor..."
                className="pl-8 text-xs h-9 bg-gray-50 dark:bg-slate-950"
              />
            </div>

            {/* Lista con checkboxes */}
            <div className="space-y-1.5 max-h-[220px] overflow-y-auto pr-1">
              {supervisors
                .filter(s =>
                  !bulkSupSearch.trim() ||
                  s.display_name.toLowerCase().includes(bulkSupSearch.toLowerCase()) ||
                  s.email.toLowerCase().includes(bulkSupSearch.toLowerCase())
                )
                .map((s) => {
                  const isChecked = bulkSupervisorIds.includes(s.id)
                  return (
                    <label
                      key={s.id}
                      className={cn(
                        "flex items-center justify-between p-2.5 rounded-xl border transition-all cursor-pointer text-xs",
                        isChecked
                          ? "bg-blue-50/80 dark:bg-blue-950/50 border-blue-300 dark:border-blue-800 text-blue-950 dark:text-blue-200 font-semibold"
                          : "bg-gray-50/50 dark:bg-slate-950/40 border-gray-200 dark:border-slate-800 text-gray-700 dark:text-slate-300 hover:bg-gray-100"
                      )}
                    >
                      <div className="flex items-center gap-2.5">
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={() => {
                            if (isChecked) {
                              setBulkSupervisorIds(prev => prev.filter(id => id !== s.id))
                            } else {
                              setBulkSupervisorIds(prev => [...prev, s.id])
                            }
                          }}
                          className="rounded border-gray-300 text-blue-600 focus:ring-blue-500 cursor-pointer"
                        />
                        <div>
                          <p className="font-semibold">{s.display_name}</p>
                          <p className="text-[11px] text-gray-400 dark:text-slate-500 font-normal">{s.email} • {s.role}</p>
                        </div>
                      </div>
                      {isChecked && (
                        <span className="text-[11px] font-bold text-blue-600 dark:text-blue-400">
                          Seleccionado
                        </span>
                      )}
                    </label>
                  )
                })}
            </div>

            <div className="flex items-center justify-between pt-3 border-t border-gray-200 dark:border-slate-800">
              <Button
                type="button"
                variant="ghost"
                onClick={() => setBulkSupervisorIds([])}
                className="text-xs text-gray-500 cursor-pointer"
              >
                Limpiar Selección
              </Button>
              <Button
                type="button"
                onClick={() => setBulkModalOpen(false)}
                className="bg-blue-600 hover:bg-blue-700 text-white text-xs font-semibold cursor-pointer"
              >
                Listo ({bulkSupervisorIds.length} seleccionados)
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
