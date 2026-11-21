import axios from 'axios'
import { safeLocal, safeSession } from '@/lib/safeStorage'

// Instancia de axios con baseURL leída de las variables de entorno de Vite.
//
// IMPORTANTE: NO seteamos Content-Type por defecto a nivel de instancia.
// Axios detecta automáticamente:
//   - application/json      cuando el body es un objeto/plain
//   - multipart/form-data   (con boundary correcto) cuando es FormData
// Si forzamos 'application/json' aquí, FormData se rompe y FastAPI devuelve
// 422 "Field required" porque no puede parsear el multipart.
const api = axios.create({
  baseURL: import.meta.env.VITE_API_URL || 'http://localhost:8000',
})

// Interceptor de request: agrega el token JWT a cada petición si existe
api.interceptors.request.use(
  (config) => {
    // V070.66 — safeStorage en lugar de window.{session,local}Storage:
    // no crashea en modo privado de Firefox/Safari ni en iframes con
    // privacy strict. Devuelve null silenciosamente si el storage falla.
    // Session primero (sesion en curso sin "recordar"), luego local.
    const token = safeSession.getItem('access_token') || safeLocal.getItem('access_token')
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
    return config
  },
  (error) => Promise.reject(error)
)

// Interceptor de response: redirige al login si el token es inválido (401)
// IMPORTANTE: ignoramos los 401 que vienen del propio /auth/login porque no son
// "sesión expirada" sino "credenciales incorrectas" — esos los maneja Login.jsx.
// Hacer window.location.href en ese caso provocaba un full-reload que flasheaba
// el brand por defecto antes de que loadBrand() recargase el real.
api.interceptors.response.use(
  (response) => response,
  (error) => {
    const url = error.config?.url || ''
    const isAuthEndpoint = url.includes('/auth/login') || url.includes('/auth/refresh')
    if (error.response?.status === 401 && !isAuthEndpoint) {
      safeLocal.removeItem('access_token')
      safeLocal.removeItem('user')
      safeSession.removeItem('access_token')
      safeSession.removeItem('user')
      window.location.href = '/login'
    }
    return Promise.reject(error)
  }
)

/**
 * Registra en el backend un intento bloqueado de copiar información sensible.
 * Best-effort: si el endpoint no existe o falla, NO se propaga error al caller
 * — la protección en el frontend ya hizo lo suyo (preventDefault), este log es
 * solo para trazabilidad/investigación.
 *
 * Payload:
 *   page   — identificador de la página ('leads' | 'asignacion' | ...)
 *   action — tipo de evento bloqueado ('copy' | 'cut' | 'contextmenu')
 */
export async function logCopyAttempt({ page, action }) {
  try {
    await api.post('/api/audit/copy-attempt', { page, action })
  } catch {
    // Silencioso: el audit es secundario, nunca debe romper la UX.
  }
}

export default api
