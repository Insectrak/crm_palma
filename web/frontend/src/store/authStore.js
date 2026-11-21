import { create } from 'zustand'
import api from '@/lib/api'
import { setSentryUser } from '@/lib/sentry'

/**
 * Store de autenticación con Zustand.
 *
 * Persistencia dual:
 *  - remember=true  → localStorage (sobrevive cierre del navegador).
 *  - remember=false → sessionStorage (se borra al cerrar la pestaña).
 *
 * Al arrancar leemos ambos, dando prioridad a sessionStorage (sesión
 * activa en curso) y cayendo a localStorage (sesión recordada).
 */
const STORAGE_KEY_TOKEN = 'access_token'
const STORAGE_KEY_USER = 'user'

function readInitial(key) {
  return sessionStorage.getItem(key) || localStorage.getItem(key) || null
}

function persistSession(token, user, remember) {
  const primary = remember ? localStorage : sessionStorage
  const secondary = remember ? sessionStorage : localStorage
  primary.setItem(STORAGE_KEY_TOKEN, token)
  primary.setItem(STORAGE_KEY_USER, JSON.stringify(user))
  // Limpiamos el otro storage para evitar sesiones huerfanas
  secondary.removeItem(STORAGE_KEY_TOKEN)
  secondary.removeItem(STORAGE_KEY_USER)
}

function clearSession() {
  localStorage.removeItem(STORAGE_KEY_TOKEN)
  localStorage.removeItem(STORAGE_KEY_USER)
  sessionStorage.removeItem(STORAGE_KEY_TOKEN)
  sessionStorage.removeItem(STORAGE_KEY_USER)
}

// V070.99 — Restaurar contexto Sentry al boot si hay sesion persistida.
const _bootUser = (() => {
  try {
    return JSON.parse(readInitial(STORAGE_KEY_USER) || 'null')
  } catch {
    return null
  }
})()
if (_bootUser) setSentryUser(_bootUser)

const useAuthStore = create((set) => ({
  token: readInitial(STORAGE_KEY_TOKEN),
  user: _bootUser,
  isLoading: false,
  error: null,

  /**
   * Realiza el login contra la API y persiste la sesion segun `remember`.
   * Retorna true si el login fue exitoso, false si fallo.
   */
  login: async (email, password, remember = true) => {
    set({ isLoading: true, error: null })
    try {
      const response = await api.post('/auth/login', { email, password })
      const {
        access_token,
        role,
        nombre_completo,
        user_id,
        default_wa_number_id,
        // ADR-0011 — sistema de permisos granulares
        permissions,
        role_id,
        role_is_external,
        api_client_id,
      } = response.data

      const userData = {
        email,
        user_id,
        role: role || 'asesor',
        nombre_completo,
        default_wa_number_id: default_wa_number_id ?? null,
        // ADR-0011 — snapshot de permisos del rol al login
        permissions: permissions || {},
        role_id: role_id ?? null,
        role_is_external: !!role_is_external,
        api_client_id: api_client_id ?? null,
      }

      persistSession(access_token, userData, remember)

      // V070.99 — tag Sentry con user_id + role (sin PII).
      setSentryUser(userData)

      set({
        token: access_token,
        user: userData,
        isLoading: false,
        error: null,
      })
      return true
    } catch (error) {
      const message =
        error.response?.data?.detail || 'Error al iniciar sesión. Verifica tus credenciales.'
      set({ isLoading: false, error: message, token: null, user: null })
      return false
    }
  },

  /**
   * Cierra la sesión limpiando el estado y localStorage.
   */
  logout: () => {
    clearSession()
    setSentryUser(null)  // V070.99 — limpia user del scope de Sentry
    set({ token: null, user: null, error: null })
  },

  /**
   * Live Permission Refresh (ADR-0011).
   *
   * Re-lee el snapshot de permisos actual desde el backend y rehidrata
   * el user en el store. Sirve para que un cambio de permisos hecho por
   * un admin se refleje en sesiones activas sin forzar logout.
   *
   * Retorna uno de tres strings:
   *  - 'ok'              → refresco exitoso, user actualizado en store
   *  - 'session_invalid' → 401 del backend (usuario eliminado/desactivado).
   *                        El caller DEBE llamar logout() para limpiar.
   *  - 'transient_error' → red caida, 5xx, etc. NO llamar logout; el
   *                        siguiente tick del poller volvera a intentar.
   */
  refreshPermissions: async () => {
    const { token, user } = useAuthStore.getState()
    if (!token || !user) return 'session_invalid'
    try {
      const response = await api.get('/auth/me/permissions')
      const fresh = response.data || {}
      const newUser = {
        ...user,
        role: fresh.role ?? user.role,
        role_id: fresh.role_id ?? null,
        role_is_external: !!fresh.role_is_external,
        permissions: fresh.permissions || {},
        api_client_id: fresh.api_client_id ?? null,
      }
      // CRITICAL: reemplazar el access_token tambien. Sin esto, el backend
      // sigue leyendo permisos del JWT viejo en mask_record/check_permission
      // (decision de no consultar DB por request). El bug visible era: Live
      // Refresh actualiza la UI pero /api/leads sigue devolviendo telefono
      // enmascarable porque el JWT no tiene la key field.leads.telefono.read.
      const newToken = fresh.access_token || token
      // Detectar storage actual (session o local) y reescribir mismo lado
      const inSession = sessionStorage.getItem(STORAGE_KEY_USER) !== null
      const storage = inSession ? sessionStorage : localStorage
      storage.setItem(STORAGE_KEY_USER, JSON.stringify(newUser))
      storage.setItem(STORAGE_KEY_TOKEN, newToken)
      set({ user: newUser, token: newToken })
      return 'ok'
    } catch (error) {
      if (error?.response?.status === 401) return 'session_invalid'
      return 'transient_error'
    }
  },

  /**
   * Limpia el mensaje de error del store.
   */
  clearError: () => set({ error: null }),

  /**
   * Helpers de rol para uso fuera de React (ej: interceptores de axios).
   */
  isAdmin: () => useAuthStore.getState().user?.role === 'admin',
  isSupervisor: () => useAuthStore.getState().user?.role === 'supervisor',
  isAsesor: () => useAuthStore.getState().user?.role === 'asesor',
  canManageTeam: () => {
    const role = useAuthStore.getState().user?.role
    return role === 'admin' || role === 'supervisor'
  },
}))

export default useAuthStore
