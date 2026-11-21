/**
 * safeStorage.js — wrapper seguro de localStorage / sessionStorage.
 *
 * Razón de existir (V070.66):
 *   - localStorage lanza excepción en modo privado de Firefox/Safari y
 *     en iframes cross-origin con privacidad strict (algunos navegadores).
 *   - sessionStorage idem.
 *   - Quota exceeded también lanza excepción.
 *
 * Acceder directamente con `localStorage.getItem(...)` sin try/catch hace
 * que la app entera crashee en pantallas tan tontas como Login o Sidebar.
 *
 * Principio SOLID aplicado: SRP (Single Responsibility).
 *   - Esta función UNA cosa: leer/escribir storage de forma segura.
 *   - El resto del frontend la usa sin pensar en navegadores raros.
 *
 * Patrón: misma API que Window.Storage (getItem, setItem, removeItem)
 * para drop-in replacement transparente. Logs en console.warn si falla
 * (no es silencioso — el dev se entera en DevTools).
 */

const isAvailable = (storage) => {
  if (!storage) return false
  try {
    const k = '__safe_storage_test__'
    storage.setItem(k, '1')
    storage.removeItem(k)
    return true
  } catch {
    return false
  }
}

const makeSafe = (storage, label) => {
  const ok = typeof window !== 'undefined' && isAvailable(storage)

  return {
    /** Indica si el storage está disponible en este browser/contexto */
    isAvailable: () => ok,

    /**
     * getItem(key, fallback?) — devuelve el valor o `fallback` (null por defecto).
     * NUNCA lanza. Si el storage falla, devuelve fallback y loguea warn.
     */
    getItem(key, fallback = null) {
      if (!ok) return fallback
      try {
        const v = storage.getItem(key)
        return v === null ? fallback : v
      } catch (err) {
        console.warn(`[safeStorage:${label}] getItem("${key}") falló:`, err?.message)
        return fallback
      }
    },

    /**
     * setItem(key, value) — guarda. Devuelve true si OK, false si falló
     * (ej. quota exceeded). NUNCA lanza.
     */
    setItem(key, value) {
      if (!ok) return false
      try {
        storage.setItem(key, value)
        return true
      } catch (err) {
        console.warn(`[safeStorage:${label}] setItem("${key}") falló:`, err?.message)
        return false
      }
    },

    /** removeItem(key) — borra. NUNCA lanza. */
    removeItem(key) {
      if (!ok) return false
      try {
        storage.removeItem(key)
        return true
      } catch (err) {
        console.warn(`[safeStorage:${label}] removeItem("${key}") falló:`, err?.message)
        return false
      }
    },

    /** clear() — borra TODO. Usar con cuidado. NUNCA lanza. */
    clear() {
      if (!ok) return false
      try {
        storage.clear()
        return true
      } catch (err) {
        console.warn(`[safeStorage:${label}] clear() falló:`, err?.message)
        return false
      }
    },
  }
}

export const safeLocal   = makeSafe(typeof window !== 'undefined' ? window.localStorage   : null, 'local')
export const safeSession = makeSafe(typeof window !== 'undefined' ? window.sessionStorage : null, 'session')

// Aliases prácticos
export default safeLocal
