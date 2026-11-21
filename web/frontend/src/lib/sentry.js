/**
 * sentry.js — inicialización de Sentry para el frontend React.
 *
 * V070.99 — patrón estándar observabilidad en frontend. Captura errores
 * de UI (render crashes, network 5xx no-handled, promesas rotas) y los
 * manda al mismo Sentry del backend (proyecto separado por DSN).
 *
 * Diseño:
 *   - Si VITE_SENTRY_DSN no está seteada, NO inicializa (no-op).
 *   - PII scrubbing antes de enviar (telefonos, emails, DNI, tokens).
 *   - Etiqueta cada evento con tenant (host) para multi-cliente.
 *   - Filtra errores conocidos benignos: network offline, abortos,
 *     errores de extensiones del navegador.
 *   - Sample rate bajo en prod (10% traces) para no saturar el free tier.
 */
import * as Sentry from '@sentry/react'

const PHONE_KEYS = new Set(['telefono', 'phone', 'wa_phone', 'to', 'from', 'msisdn', 'asesor_telefono', 'celular'])
const EMAIL_KEYS = new Set(['email', 'correo', 'user_email'])
const DNI_KEYS   = new Set(['dni', 'doc', 'documento'])
const SECRET_KEYS = new Set(['password', 'password_hash', 'secret', 'api_key',
  'x-api-key', 'authorization', 'token', 'refresh_token'])

function maskPhone(v) {
  if (!v) return 'none'
  const digits = String(v).replace(/\D/g, '')
  if (digits.length <= 4) return digits || 'none'
  return `***${digits.slice(-4)}`
}

function maskEmail(v) {
  if (!v || typeof v !== 'string') return 'none'
  const s = v.trim()
  if (!s.includes('@')) return '***'
  const [local, domain] = s.split('@')
  const masked = local.length <= 2
    ? (local[0] || '*') + '*'
    : `${local[0]}${'*'.repeat(local.length - 2)}${local[local.length - 1]}`
  return `${masked}@${domain}`
}

function maskDni(v) {
  if (!v) return 'none'
  const digits = String(v).replace(/\D/g, '')
  if (digits.length <= 4) return digits || 'none'
  return `${'*'.repeat(digits.length - 4)}${digits.slice(-4)}`
}

function scrubValue(key, value) {
  if (value == null) return value
  const k = String(key).toLowerCase()
  if (SECRET_KEYS.has(k)) return '[REDACTED]'
  if (PHONE_KEYS.has(k) && typeof value === 'string') return maskPhone(value)
  if (EMAIL_KEYS.has(k) && typeof value === 'string') return maskEmail(value)
  if (DNI_KEYS.has(k) && typeof value === 'string') return maskDni(value)
  return value
}

function scrubRecursive(obj, depth = 0) {
  if (depth > 8 || obj == null) return obj
  if (Array.isArray(obj)) return obj.map(v => scrubRecursive(v, depth + 1))
  if (typeof obj === 'object') {
    const out = {}
    for (const [k, v] of Object.entries(obj)) {
      out[k] = scrubRecursive(scrubValue(k, v), depth + 1)
    }
    return out
  }
  return obj
}

// Errores benignos que NO valen un evento (ruido de navegador / red).
const IGNORE_PATTERNS = [
  /ResizeObserver loop/i,
  /Non-Error promise rejection captured/i,
  /Network request failed/i,           // offline temporal
  /Load failed/i,                       // navegacion durante fetch
  /AbortError/i,                        // cancelaciones intencionales
  /ChunkLoadError/i,                    // deploy mid-session — se resuelve solo
  /chrome-extension:/i,                  // extensiones del usuario
  /moz-extension:/i,
  /Script error\.?$/i,                   // CORS de scripts externos
]

function beforeSend(event, hint) {
  // 1. Filtrar errores benignos por mensaje
  const msg = event.message
    || hint?.originalException?.message
    || ''
  for (const pat of IGNORE_PATTERNS) {
    if (pat.test(msg)) return null
  }

  // 2. PII scrubbing comprehensivo
  try {
    if (event.request) {
      const req = event.request
      if (req.data) req.data = scrubRecursive(req.data)
      if (req.query_string) req.query_string = scrubRecursive(req.query_string)
      if (req.headers) req.headers = scrubRecursive(req.headers)
      if (req.cookies) req.cookies = scrubRecursive(req.cookies)
    }
    if (event.extra) event.extra = scrubRecursive(event.extra)
    if (event.contexts) event.contexts = scrubRecursive(event.contexts)
    if (event.breadcrumbs?.length) {
      event.breadcrumbs = event.breadcrumbs.map(b => ({
        ...b,
        data: b.data ? scrubRecursive(b.data) : b.data,
      }))
    }
  } catch {
    // Si el scrubbing falla, descartamos el evento (mejor perder visibilidad
    // que mandar PII al exterior).
    return null
  }
  return event
}

/**
 * V070.99 — Lee config inyectada por el backend en runtime (preferida)
 * con fallback a las VITE_* vars del build time. Esto evita depender de
 * build-args en EasyPanel para inyectar el DSN.
 *
 * El backend renderiza un <script id="__app_config__" type="application/json">
 * en el index.html con los valores actuales de las env vars.
 */
function readRuntimeConfig() {
  try {
    const el = document.getElementById('__app_config__')
    if (el && el.textContent) {
      const cfg = JSON.parse(el.textContent)
      return cfg?.sentry || {}
    }
  } catch {
    // si el JSON esta malformado, caemos al fallback Vite
  }
  return {}
}

/**
 * Inicializa Sentry. Llamar desde main.jsx ANTES de createRoot.
 * Si VITE_SENTRY_DSN está vacío, no hace nada (no-op).
 */
export function initSentry() {
  const runtime = readRuntimeConfig()
  const dsn = runtime.dsn || import.meta.env.VITE_SENTRY_DSN
  if (!dsn || !String(dsn).trim()) {
    // eslint-disable-next-line no-console
    console.info('[sentry] deshabilitado (sin DSN)')
    return false
  }
  const environment = runtime.environment
    || import.meta.env.VITE_SENTRY_ENVIRONMENT
    || import.meta.env.MODE
    || 'production'
  const release = runtime.release || import.meta.env.VITE_APP_VERSION || undefined
  const tracesSampleRate = Number(
    runtime.tracesSampleRate ?? import.meta.env.VITE_SENTRY_TRACES_SAMPLE_RATE ?? 0.1
  )
  const replaysOnErrorSampleRate = Number(
    runtime.replaysOnErrorRate ?? import.meta.env.VITE_SENTRY_REPLAYS_ON_ERROR_RATE ?? 1.0
  )

  try {
    Sentry.init({
      dsn,
      environment,
      release,
      tracesSampleRate,
      integrations: [
        Sentry.browserTracingIntegration(),
        Sentry.replayIntegration({
          maskAllText: true,    // Ley 29733 PE: enmascara TODO el texto
          blockAllMedia: true,
        }),
      ],
      replaysSessionSampleRate: 0,        // no grabar sesiones random
      replaysOnErrorSampleRate,
      beforeSend,
      sendDefaultPii: false,
      initialScope: {
        tags: { tenant: window.location.hostname },
      },
    })
    // V070.99 — exponer Sentry globalmente para debugging / smoke tests:
    //   window.Sentry.captureMessage('test', 'info')
    //   window.Sentry.captureException(new Error('test'))
    // No es secreto (el SDK ya esta en el bundle publico). Patron usado por
    // sentry.io official samples y muchos SaaS.
    if (typeof window !== 'undefined') {
      window.Sentry = Sentry
    }
    // eslint-disable-next-line no-console
    console.info('[sentry] inicializado', {
      environment, release, source: runtime.dsn ? 'runtime' : 'build',
    })
    return true
  } catch (err) {
    // eslint-disable-next-line no-console
    console.warn('[sentry] init fallo:', err)
    return false
  }
}

/**
 * Setea info del usuario autenticado en el scope (id + role).
 * Llamar desde authStore tras login.
 */
export function setSentryUser(user) {
  try {
    if (!user) {
      Sentry.setUser(null)
      return
    }
    Sentry.setUser({
      id: String(user.user_id || user.id || ''),
      // NUNCA email — para no romper la regla de PII en Sentry.
      role: user.role || 'unknown',
    })
  } catch {
    // no-op
  }
}

/**
 * Error boundary HOC para encapsular toda la app con fallback amigable.
 */
export const SentryErrorBoundary = Sentry.ErrorBoundary
