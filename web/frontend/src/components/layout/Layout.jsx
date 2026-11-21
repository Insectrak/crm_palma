import { useEffect } from 'react'
import { Outlet, useLocation } from 'react-router-dom'
import Sidebar from './Sidebar'
import Header from './Header'
import ManualApoyoDrawer from './ManualApoyoDrawer'
import ErrorBoundary from '@/components/shared/ErrorBoundary'
import useAuthStore from '@/store/authStore'

// ADR-0011 — Live Permission Refresh. Re-lee el snapshot de permisos cada
// REFRESH_MS desde /auth/me/permissions para que cambios hechos por un admin
// se propaguen a sesiones activas sin forzar relogin. 60s es el sweet spot
// del modelo patrón estándar (Permission Set cache).
const REFRESH_MS = 60 * 1000

function usePermissionRefresh() {
  const token = useAuthStore((s) => s.token)
  const refreshPermissions = useAuthStore((s) => s.refreshPermissions)
  const logout = useAuthStore((s) => s.logout)
  useEffect(() => {
    if (!token) return undefined
    let cancelled = false
    const tick = async () => {
      if (cancelled) return
      const result = await refreshPermissions()
      if (cancelled) return
      // 401 explicito = sesion invalidada (usuario desactivado/eliminado).
      // Solo en este caso forzamos logout. transient_error se ignora para no
      // tirar sesiones por caidas de red.
      if (result === 'session_invalid') logout()
    }
    tick()
    const id = setInterval(tick, REFRESH_MS)
    return () => {
      cancelled = true
      clearInterval(id)
    }
  // Solo re-armamos cuando cambia el token (login/logout). refreshPermissions
  // y logout son referencias estables del store de Zustand.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])
}

export default function Layout() {
  const location = useLocation()
  usePermissionRefresh()
  return (
    <div className="flex h-screen bg-slate-50 dark:bg-[#090d16] text-slate-900 dark:text-slate-100 overflow-hidden transition-colors" style={{ overflowX: 'hidden', maxWidth: '100vw' }}>
      <Sidebar />
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        <Header />
        {/* overflow-y-scroll (no auto): reserva el espacio del scrollbar
            siempre. Asi cuando una pagina cambia de altura (ej. al refrescar
            filtros la tabla colapsa a un spinner momentaneo), el ancho NO
            cambia y el sidebar no parpadea.  */}
        <main className="flex-1 overflow-y-scroll wa-scrollbar px-4 py-5">
          {/*
            ErrorBoundary con key basada en pathname:
            si una página crashea, el sidebar y header siguen visibles.
            Al navegar a otra ruta, el boundary se remonta (reset automático).
          */}
          <ErrorBoundary key={location.pathname}>
            <Outlet />
          </ErrorBoundary>
        </main>
      </div>

      {/* Manual de apoyo y guiones telefónicos (botón flotante a la derecha + drawer) */}
      <ManualApoyoDrawer />
    </div>
  )
}
