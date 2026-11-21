/**
 * useSavedViews — hook que encapsula la logica de vistas guardadas
 * (V063). Mantiene la lista de vistas del backend, la vista activa,
 * detecta diff con el estado actual y expone acciones CRUD.
 *
 * El caller le pasa:
 *  - scope: 'leads' | 'asignacion' | 'historicos'
 *  - currentState: snapshot serializable del estado actual (filtros,
 *    sort, columns_order, visible_columns). El hook compara este
 *    objeto contra el de la vista activa para decidir si esta "dirty".
 *  - applyState: callback (viewState) => void que el caller usa para
 *    restaurar el estado cuando se selecciona/descarta una vista.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import api from '@/lib/api'

// Normalización y comparación estructural de estados de vistas (V063 / V106)
function normalizeFilters(filters) {
  if (!filters || typeof filters !== 'object') return {}
  const clean = {}
  for (const [k, v] of Object.entries(filters)) {
    if (v === null || v === undefined || v === '' || v === false) continue
    if (typeof v === 'boolean') {
      clean[k] = v
    } else if (typeof v === 'number') {
      clean[k] = String(v)
    } else if (typeof v === 'string') {
      const trimmed = v.trim()
      if (trimmed === '') continue
      clean[k] = trimmed
    } else {
      clean[k] = v
    }
  }
  return clean
}

function normalizeArray(arr, sort = false) {
  if (!Array.isArray(arr)) return []
  const list = arr.filter(item => item !== null && item !== undefined && item !== '')
  return sort ? [...list].sort() : list
}

function stableStringify(obj) {
  if (obj === null || typeof obj !== 'object') return JSON.stringify(obj)
  if (Array.isArray(obj)) return '[' + obj.map(stableStringify).join(',') + ']'
  const keys = Object.keys(obj).sort()
  return '{' + keys.map(k => JSON.stringify(k) + ':' + stableStringify(obj[k])).join(',') + '}'
}

function statesEqual(a, b) {
  if (!a || !b) return false
  return (
    stableStringify(normalizeFilters(a.filters))             === stableStringify(normalizeFilters(b.filters)) &&
    stableStringify(normalizeArray(a.sort))                  === stableStringify(normalizeArray(b.sort)) &&
    stableStringify(normalizeArray(a.columns_order))         === stableStringify(normalizeArray(b.columns_order)) &&
    stableStringify(normalizeArray(a.visible_columns, true)) === stableStringify(normalizeArray(b.visible_columns, true))
  )
}


export default function useSavedViews({ scope, currentState }) {
  const [views, setViews]               = useState([])
  const [loading, setLoading]           = useState(false)
  const [activeViewId, setActiveViewId] = useState(null)
  const [isMutating, setIsMutating]     = useState(false)

  // Cargar vistas del backend al montar
  const load = useCallback(async () => {
    setLoading(true)
    try {
      const res = await api.get(`/api/views?scope=${scope}`)
      setViews(res.data || [])
      return res.data || []
    } catch {
      setViews([])
      return []
    } finally {
      setLoading(false)
    }
  }, [scope])

  useEffect(() => { load() }, [load])

  const activeView = useMemo(
    () => views.find(v => v.id === activeViewId) || null,
    [views, activeViewId],
  )

  // El estado actual vs la vista guardada → ¿estamos "dirty"?
  const isDirty = useMemo(() => {
    if (!activeView) return false
    return !statesEqual(currentState, {
      filters:         activeView.filters,
      sort:            activeView.sort,
      columns_order:   activeView.columns_order,
      visible_columns: activeView.visible_columns,
    })
  }, [activeView, currentState])

  // ── Acciones ──────────────────────────────────────────────────────────

  const createView = useCallback(async ({ name, share_level, team_supervisor_id, color, is_default }) => {
    setIsMutating(true)
    try {
      const res = await api.post('/api/views', {
        scope,
        name,
        share_level,
        team_supervisor_id: team_supervisor_id || null,
        color,
        is_default: !!is_default,
        filters:         normalizeFilters(currentState?.filters),
        sort:            normalizeArray(currentState?.sort),
        columns_order:   normalizeArray(currentState?.columns_order),
        visible_columns: normalizeArray(currentState?.visible_columns, true),
      })
      const created = res.data
      await load()
      setActiveViewId(created.id)
      return created
    } finally {
      setIsMutating(false)
    }
  }, [scope, currentState, load])

  const updateView = useCallback(async (viewId, patch) => {
    setIsMutating(true)
    try {
      const payload = { ...patch }
      if ('filters' in payload) payload.filters = normalizeFilters(payload.filters)
      if ('sort' in payload) payload.sort = normalizeArray(payload.sort)
      if ('columns_order' in payload) payload.columns_order = normalizeArray(payload.columns_order)
      if ('visible_columns' in payload) payload.visible_columns = normalizeArray(payload.visible_columns, true)
      const res = await api.patch(`/api/views/${viewId}`, payload)
      await load()
      return res.data
    } finally {
      setIsMutating(false)
    }
  }, [load])

  /** Guarda el estado actual sobre la vista activa (save cambios). */
  const saveCurrentToActive = useCallback(async () => {
    if (!activeView) return
    return updateView(activeView.id, {
      filters:         currentState?.filters || {},
      sort:            currentState?.sort || [],
      columns_order:   currentState?.columns_order || [],
      visible_columns: currentState?.visible_columns || [],
    })
  }, [activeView, currentState, updateView])

  const deleteView = useCallback(async (viewId) => {
    setIsMutating(true)
    try {
      await api.delete(`/api/views/${viewId}`)
      if (activeViewId === viewId) setActiveViewId(null)
      await load()
    } finally {
      setIsMutating(false)
    }
  }, [activeViewId, load])

  const setDefault = useCallback(async (viewId) => {
    setIsMutating(true)
    try {
      await api.post(`/api/views/${viewId}/default`)
      await load()
    } finally {
      setIsMutating(false)
    }
  }, [load])

  /** Crea una copia de la vista con sufijo "(copia)". El nuevo dueño
   *  es siempre el usuario actual, sin importar quien creó la original. */
  const duplicateView = useCallback(async (view) => {
    setIsMutating(true)
    try {
      const res = await api.post('/api/views', {
        scope:               view.scope,
        name:                `${view.name} (copia)`,
        share_level:         'personal',  // las copias siempre arrancan personales
        team_supervisor_id:  null,
        color:               view.color,
        icon:                view.icon,
        is_default:          false,
        filters:             view.filters,
        sort:                view.sort,
        columns_order:       view.columns_order,
        visible_columns:     view.visible_columns,
      })
      await load()
      return res.data
    } finally {
      setIsMutating(false)
    }
  }, [load])

  return {
    views,
    loading,
    isMutating,
    activeView,
    activeViewId,
    setActiveViewId,
    isDirty,
    load,
    createView,
    updateView,
    saveCurrentToActive,
    deleteView,
    setDefault,
    duplicateView,
  }
}
