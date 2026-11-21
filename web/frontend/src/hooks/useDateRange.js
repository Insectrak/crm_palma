/**
 * useDateRange — hook que gestiona la ventana temporal del dashboard.
 *
 * Estado:
 *   - preset:    string key (today / last_7 / last_30 / last_90 / last_365 / custom)
 *   - startDate: ISO YYYY-MM-DD inclusive
 *   - endDate:   ISO YYYY-MM-DD inclusive
 *
 * Persistencia: localStorage por usuario (clave dashboard_date_range_<userId>).
 * Si el usuario nunca eligio, default = last_7 (7 dias rolling).
 *
 * Helpers:
 *   - setPreset(key)         — cambia a un preset, recalcula start/end
 *   - setCustomRange(s, e)   — aplica rango custom (yyyy-mm-dd, yyyy-mm-dd)
 *   - apiParams              — { start_date, end_date } listo para axios params
 *   - rangeLabel             — "del 13 jun – 19 jun 2026" para mostrar al user
 */
import { useCallback, useEffect, useMemo, useState } from 'react'

const PRESETS = {
  today:    { label: 'Hoy',          days: 1   },
  last_7:   { label: '7 días',       days: 7   },
  last_30:  { label: '30 días',      days: 30  },
  last_90:  { label: 'Trimestre',    days: 90  },
  last_365: { label: 'Año',          days: 365 },
}

const PRESET_KEYS  = ['today', 'last_7', 'last_30', 'last_90', 'last_365', 'custom']
const DEFAULT_PRESET = 'last_7'

/** Devuelve la fecha local Lima como Date 'pura' (sin hora). */
function todayLima() {
  // toLocaleString('en-CA', { timeZone: 'America/Lima' }) -> 'YYYY-MM-DD, HH:MM:SS'
  const iso = new Date().toLocaleString('en-CA', {
    timeZone: 'America/Lima',
    year: 'numeric', month: '2-digit', day: '2-digit',
  })
  return iso // 'YYYY-MM-DD'
}

/** Suma days al ISO date (positivo = futuro, negativo = pasado). */
function addDays(iso, days) {
  const [y, m, d] = iso.split('-').map(Number)
  const dt = new Date(Date.UTC(y, m - 1, d))
  dt.setUTCDate(dt.getUTCDate() + days)
  return dt.toISOString().slice(0, 10)
}

/** Convierte un preset key a { startDate, endDate } ISO. */
function presetToRange(key) {
  const end = todayLima()
  if (key === 'today')   return { startDate: end, endDate: end }
  const cfg = PRESETS[key]
  if (!cfg) return { startDate: addDays(end, -6), endDate: end }
  const start = addDays(end, -(cfg.days - 1))
  return { startDate: start, endDate: end }
}

/** Formatea ISO YYYY-MM-DD a "13 jun 2026" en castellano. */
function fmtLabel(iso) {
  if (!iso) return ''
  const [y, m, d] = iso.split('-').map(Number)
  const dt = new Date(Date.UTC(y, m - 1, d))
  return dt.toLocaleDateString('es-PE', {
    day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC',
  }).replace('.', '')
}

/** Lee el state inicial del localStorage. Defensivo ante JSON corrupto. */
function readInitial(userKey) {
  try {
    const raw = localStorage.getItem(userKey)
    if (!raw) return null
    const parsed = JSON.parse(raw)
    if (!parsed?.preset || !PRESET_KEYS.includes(parsed.preset)) return null
    return parsed
  } catch {
    return null
  }
}

export default function useDateRange(userId = 'anon') {
  const userKey = `dashboard_date_range_${userId}`

  const [state, setState] = useState(() => {
    const saved = readInitial(userKey)
    if (saved?.preset === 'custom' && saved.startDate && saved.endDate) {
      return { preset: 'custom', startDate: saved.startDate, endDate: saved.endDate }
    }
    const initialPreset = saved?.preset || DEFAULT_PRESET
    const range = presetToRange(initialPreset)
    return { preset: initialPreset, ...range }
  })

  // Persiste cada cambio en localStorage
  useEffect(() => {
    try {
      localStorage.setItem(userKey, JSON.stringify(state))
    } catch { /* quota / private mode — silencioso */ }
  }, [state, userKey])

  const setPreset = useCallback((key) => {
    if (!PRESET_KEYS.includes(key) || key === 'custom') return
    setState({ preset: key, ...presetToRange(key) })
  }, [])

  const setCustomRange = useCallback((startDate, endDate) => {
    if (!startDate || !endDate) return
    if (startDate > endDate) return
    setState({ preset: 'custom', startDate, endDate })
  }, [])

  const apiParams = useMemo(
    () => ({ start_date: state.startDate, end_date: state.endDate }),
    [state.startDate, state.endDate],
  )

  const rangeLabel = useMemo(() => {
    if (state.startDate === state.endDate) return fmtLabel(state.startDate)
    // Castellano peruano natural: "del X al Y" en vez de "del X – Y".
    // El guion suele leerse como separador ambiguo (el user podia pensar
    // que la primera fecha era "hoy"). "al" deja claro que es rango.
    return `${fmtLabel(state.startDate)} al ${fmtLabel(state.endDate)}`
  }, [state.startDate, state.endDate])

  const activePresetLabel = useMemo(() => {
    if (state.preset === 'custom') return 'Personalizado'
    return PRESETS[state.preset]?.label || ''
  }, [state.preset])

  return {
    preset:    state.preset,
    startDate: state.startDate,
    endDate:   state.endDate,
    setPreset,
    setCustomRange,
    apiParams,
    rangeLabel,
    activePresetLabel,
    PRESETS,
    PRESET_KEYS,
  }
}
