/**
 * reportesV2.js — Cliente HTTP para los 5 reportes V070.103.
 *
 * Backend: web/backend/app/routers/reportes_v2.py
 */
import api from './api'

function qs(params) {
  const cleaned = Object.fromEntries(
    Object.entries(params).filter(([, v]) => v != null && v !== '')
  )
  const sp = new URLSearchParams(cleaned).toString()
  return sp ? `?${sp}` : ''
}

export async function fetchEficienciaLlamadas({ fecha_desde, fecha_hasta, asesor_id } = {}) {
  const res = await api.get(`/api/reportes/v2/eficiencia-llamadas${qs({ fecha_desde, fecha_hasta, asesor_id })}`)
  return res.data
}

export async function fetchLeadtime({ fecha_desde, fecha_hasta } = {}) {
  const res = await api.get(`/api/reportes/v2/leadtime${qs({ fecha_desde, fecha_hasta })}`)
  return res.data
}

export async function fetchFunnel({ fecha_desde, fecha_hasta, fuente_id } = {}) {
  const res = await api.get(`/api/reportes/v2/funnel${qs({ fecha_desde, fecha_hasta, fuente_id })}`)
  return res.data
}

export async function fetchControl({ fecha_desde, fecha_hasta, dias_sin_contacto } = {}) {
  const res = await api.get(`/api/reportes/v2/control${qs({ fecha_desde, fecha_hasta, dias_sin_contacto })}`)
  return res.data
}

export async function fetchEstrategico({ fecha_desde, fecha_hasta } = {}) {
  const res = await api.get(`/api/reportes/v2/estrategico${qs({ fecha_desde, fecha_hasta })}`)
  return res.data
}

// V095.4 — Stage Velocity: dias promedio que llevan los leads en su estado actual.
export async function fetchStageVelocity() {
  const res = await api.get('/api/reportes/v2/stage-velocity')
  return res.data
}

// V095.5 — Cohort mensual heatmap.
export async function fetchCohortMensual({ meses = 6 } = {}) {
  const res = await api.get(`/api/reportes/v2/cohort-mensual${qs({ meses })}`)
  return res.data
}
