import { useEffect, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import useAuthStore from '@/store/authStore'
import useBrandStore from '@/store/brandStore'
import { hasPermission } from '@/lib/permissions'
import { lazyWithReload } from '@/lib/lazyWithReload'
import Layout from '@/components/layout/Layout'
import Login from '@/pages/Login'
import Dashboard from '@/pages/Dashboard'
import Leads from '@/pages/Leads'
import { UndoToastProvider } from '@/components/shared/UndoToast'

// V088 — lazyWithReload auto-recupera del error "Failed to fetch dynamically
// imported module" recargando una sola vez por sesión. Sucede cuando un
// usuario tiene la SPA abierta DESDE ANTES de un deploy y los hashes de
// los chunks ya cambiaron en el server.
const Setup = lazyWithReload(() => import('@/pages/Setup'))
const AcceptInvite = lazyWithReload(() => import('@/pages/AcceptInvite'))
const ResetPassword = lazyWithReload(() => import('@/pages/ResetPassword'))
const PublicForm = lazyWithReload(() => import('@/pages/PublicForm'))
const LeadDetalle = lazyWithReload(() => import('@/pages/LeadDetalle'))
const NuevoLead = lazyWithReload(() => import('@/pages/NuevoLead'))
const NuevoReferido = lazyWithReload(() => import('@/pages/NuevoReferido'))
const Asignacion = lazyWithReload(() => import('@/pages/Asignacion'))
const CargaMasiva = lazyWithReload(() => import('@/pages/CargaMasiva'))
const Reportes = lazyWithReload(() => import('@/pages/Reportes'))
const ReportesV2 = lazyWithReload(() => import('@/pages/ReportesV2'))
const ReportesHome = lazyWithReload(() => import('@/pages/ReportesHome'))
const ReportesEspeciales = lazyWithReload(() => import('@/pages/ReportesEspeciales'))
const Dashboards = lazyWithReload(() => import('@/pages/Dashboards'))
const Metas = lazyWithReload(() => import('@/pages/Metas'))
const Llamadas = lazyWithReload(() => import('@/pages/Llamadas'))
const Agenda = lazyWithReload(() => import('@/pages/Agenda'))
const Rotacion = lazyWithReload(() => import('@/pages/Rotacion'))
const Formularios = lazyWithReload(() => import('@/pages/Formularios'))
const Configuracion = lazyWithReload(() => import('@/pages/Configuracion'))
const Chat = lazyWithReload(() => import('@/pages/Chat'))
const Historicos = lazyWithReload(() => import('@/pages/Historicos'))
const Integraciones = lazyWithReload(() => import('@/pages/Integraciones'))
const Pixel = lazyWithReload(() => import('@/pages/Pixel'))
const FieldMappings = lazyWithReload(() => import('@/pages/FieldMappings'))
const ApiClients = lazyWithReload(() => import('@/pages/ApiClients'))
const DashboardJefatura = lazyWithReload(() => import('@/pages/DashboardJefatura'))
const DashboardSupervisionControl = lazyWithReload(() => import('@/pages/DashboardSupervisionControl'))
const BolsaReciclajeTMK = lazyWithReload(() => import('@/pages/BolsaReciclajeTMK'))
const LeadsCampanas = lazyWithReload(() => import('@/pages/LeadsCampanas'))
const PapeleraLeads = lazyWithReload(() => import('@/pages/PapeleraLeads'))
const GestionLotes = lazyWithReload(() => import('@/pages/GestionLotes'))

/**
 * Ruta protegida: redirige al login si el usuario no está autenticado.
 */
function PrivateRoute({ children }) {
  const { token } = useAuthStore()
  return token ? children : <Navigate to="/login" replace />
}

/**
 * Ruta protegida por permiso granular (ADR-0011 + V088).
 * Pasa si:
 *  - el usuario tiene `permission` en su snapshot (hasPermission cubre admin
 *    legacy + flag _all + key match)
 *  - O su `role` legacy esta en `legacyRoles` Y NO tiene `role_id` custom
 *    asignado (compat para supervisor/asesor sin role custom).
 *
 * V088: si el usuario tiene `role_id` (custom role asignado), ese rol es la
 * fuente de verdad. NO caemos al fallback legacy aunque el perms esté vacío
 * — un rol custom "Sin Acceso" debe bloquear realmente todo, no solo verse
 * como bloqueado.
 */
function PermissionRoute({ children, permission, legacyRoles = [] }) {
  const { user } = useAuthStore()
  if (hasPermission(user, permission)) return children
  const hasCustomRole = user?.role_id != null
  if (!hasCustomRole && user?.role && legacyRoles.includes(user.role)) return children
  return <Navigate to="/dashboard" replace />
}

/**
 * Ruta pública: redirige al dashboard si ya está autenticado.
 */
function PublicRoute({ children }) {
  const { token } = useAuthStore()
  return token ? <Navigate to="/dashboard" replace /> : children
}

export default function App() {
  const loadBrand = useBrandStore((s) => s.loadBrand)
  useEffect(() => { loadBrand() }, [loadBrand])

  return (
    <BrowserRouter>
      <UndoToastProvider>
        <Suspense fallback={<div className="flex items-center justify-center h-screen text-slate-400">Cargando...</div>}>
          <Routes>
            {/* Ruta de setup inicial (solo si no hay usuarios) */}
            <Route path="/setup" element={<Setup />} />

            {/* Ruta pública: aceptar invitación */}
            <Route path="/invite" element={<AcceptInvite />} />

            {/* Ruta pública: restablecer contraseña */}
            <Route path="/reset-password" element={<ResetPassword />} />

            {/* Ruta pública: formulario de captura de leads (sin auth, sin Layout) */}
            <Route path="/f/:slug" element={<PublicForm />} />

            {/* Ruta pública: login */}
            <Route
              path="/login"
              element={
                <PublicRoute>
                  <Login />
                </PublicRoute>
              }
            />

            {/* Rutas protegidas: requieren autenticación */}
            <Route
              path="/"
              element={
                <PrivateRoute>
                  <Layout />
                </PrivateRoute>
              }
            >
              {/* Redirección raíz → dashboard */}
              <Route index element={<Navigate to="/dashboard" replace />} />

              {/* Dashboard principal */}
              <Route path="dashboard" element={<Dashboard />} />

              {/* Módulo de Leads */}
              <Route
                path="leads"
                element={
                  <PermissionRoute permission="leads.view" legacyRoles={['admin', 'supervisor', 'asesor']}>
                    <Leads />
                  </PermissionRoute>
                }
              />
              <Route
                path="leads/nuevo"
                element={
                  <PermissionRoute permission="leads.create" legacyRoles={['admin', 'supervisor', 'asesor']}>
                    <NuevoLead />
                  </PermissionRoute>
                }
              />
              <Route
                path="leads/referido"
                element={
                  <PermissionRoute permission="leads.create" legacyRoles={['admin', 'supervisor', 'asesor']}>
                    <NuevoReferido />
                  </PermissionRoute>
                }
              />
              <Route
                path="leads/:id"
                element={
                  <PermissionRoute permission="leads.view" legacyRoles={['admin', 'supervisor', 'asesor']}>
                    <LeadDetalle />
                  </PermissionRoute>
                }
              />

              {/* Asignación — exclusivo para rol admin */}
              <Route
                path="asignacion"
                element={
                  <PermissionRoute permission="asignacion.manage" legacyRoles={['admin']}>
                    <Asignacion />
                  </PermissionRoute>
                }
              />

              {/* Carga masiva — permiso leads.create */}
              <Route
                path="carga-masiva"
                element={
                  <PermissionRoute permission="leads.create" legacyRoles={['admin', 'supervisor', 'asesor']}>
                    <CargaMasiva />
                  </PermissionRoute>
                }
              />

              {/* Reportes y Dashboards */}
              {/* V070.109 — landing principal de reportes patrón estándar */}
              <Route
                path="reportes"
                element={
                  <PermissionRoute permission="reportes.view" legacyRoles={['admin', 'supervisor']}>
                    <ReportesHome />
                  </PermissionRoute>
                }
              />
              {/* Reportería Especial — exclusivo para rol admin */}
              <Route
                path="reportes-especiales"
                element={
                  <PermissionRoute permission="admin.all" legacyRoles={['admin']}>
                    <ReportesEspeciales />
                  </PermissionRoute>
                }
              />
              <Route
                path="dashboards"
                element={
                  <PermissionRoute permission="dashboards.view" legacyRoles={['admin', 'supervisor']}>
                    <Dashboards />
                  </PermissionRoute>
                }
              />
              <Route
                path="dashboard-jefatura"
                element={
                  <PermissionRoute permission="dashboards.view" legacyRoles={['admin', 'supervisor']}>
                    <DashboardJefatura />
                  </PermissionRoute>
                }
              />
              {/* Dashboard de Supervisión y Control (Alta Dirección) — exclusivo admin */}
              <Route
                path="supervision-control"
                element={
                  <PermissionRoute permission="admin.all" legacyRoles={['admin']}>
                    <DashboardSupervisionControl />
                  </PermissionRoute>
                }
              />
              {/* Gestión de Lotes (Separaciones y Cierres en servidor + sync Git desde Drive/Excel) — exclusivo admin */}
              <Route
                path="gestion-lotes"
                element={
                  <PermissionRoute permission="admin.all" legacyRoles={['admin']}>
                    <GestionLotes />
                  </PermissionRoute>
                }
              />
              <Route path="separaciones" element={<Navigate to="/gestion-lotes" replace />} />
              {/* Bolsa de Reciclaje TMK */}
              <Route
                path="reciclaje-tmk"
                element={
                  <PermissionRoute permission="leads.manage" legacyRoles={['admin', 'supervisor']}>
                    <BolsaReciclajeTMK />
                  </PermissionRoute>
                }
              />
              {/* Rutas de los reportes individuales (mantienen el codigo existente) */}
              <Route
                path="reportes-operativos"
                element={
                  <PermissionRoute permission="reportes.view" legacyRoles={['admin', 'supervisor']}>
                    <Reportes />
                  </PermissionRoute>
                }
              />
              <Route
                path="reportes-avanzados"
                element={
                  <PermissionRoute permission="reportes.view" legacyRoles={['admin', 'supervisor']}>
                    <ReportesV2 />
                  </PermissionRoute>
                }
              />

              {/* Metas mensuales (Quotas / Goals) — admin/supervisor legacy o roles con metas.view */}
              <Route
                path="metas"
                element={
                  <PermissionRoute permission="metas.view" legacyRoles={['admin', 'supervisor']}>
                    <Metas />
                  </PermissionRoute>
                }
              />

              {/* Llamadas — todos los roles (backend filtra por rol) */}
              <Route path="llamadas" element={<Llamadas />} />

              {/* Agenda */}
              <Route
                path="agenda"
                element={
                  <PermissionRoute permission="agenda.view" legacyRoles={['admin', 'supervisor', 'asesor']}>
                    <Agenda />
                  </PermissionRoute>
                }
              />

              {/* Chat WhatsApp — todos los roles (backend filtra por rol) */}
              <Route path="chat" element={<Chat />} />

              {/* Formularios públicos — admin/supervisor legacy o roles con formularios.manage */}
              <Route
                path="formularios"
                element={
                  <PermissionRoute permission="formularios.manage" legacyRoles={['admin', 'supervisor']}>
                    <Formularios />
                  </PermissionRoute>
                }
              />

              {/* Leads historicos — admin exclusivo */}
              <Route
                path="historicos"
                element={
                  <PermissionRoute permission="historicos.view" legacyRoles={['admin']}>
                    <Historicos />
                  </PermissionRoute>
                }
              />

              {/* Papelera de Leads (Leads Inactivos) — admin exclusivo */}
              <Route
                path="leads-inactivos"
                element={
                  <PermissionRoute permission="leads.delete" legacyRoles={['admin']}>
                    <PapeleraLeads />
                  </PermissionRoute>
                }
              />

              {/* Rotación de ingesta (FB/TikTok/WA) — admin legacy o roles con rotacion.manage */}
              <Route
                path="rotacion"
                element={
                  <PermissionRoute permission="rotacion.manage" legacyRoles={['admin']}>
                    <Rotacion />
                  </PermissionRoute>
                }
              />

              {/* Leads Campañas (Meta & TikTok -> Supervisores) — admin exclusivo */}
              <Route
                path="leads-campanas"
                element={
                  <PermissionRoute permission="rotacion.manage" legacyRoles={['admin']}>
                    <LeadsCampanas />
                  </PermissionRoute>
                }
              />

              {/* Integraciones externas (Meta, TikTok) — admin o roles con integraciones.manage */}
              <Route
                path="integraciones"
                element={
                  <PermissionRoute permission="integraciones.manage">
                    <Integraciones />
                  </PermissionRoute>
                }
              />

              {/* Rendimiento de Ads (Meta, TikTok) — admin o roles con dashboards.view */}
              <Route
                path="rendimiento-ads"
                element={
                  <PermissionRoute permission="dashboards.view">
                    <Pixel />
                  </PermissionRoute>
                }
              />

              {/* Campos y propiedades custom (patrón estándar) — admin o roles con integraciones.manage */}
              <Route
                path="integraciones/campos"
                element={
                  <PermissionRoute permission="integraciones.manage">
                    <FieldMappings />
                  </PermissionRoute>
                }
              />

              {/* API Clients (proveedores externos via API key) — admin o roles con integraciones.manage */}
              <Route
                path="integraciones/api-clients"
                element={
                  <PermissionRoute permission="integraciones.manage">
                    <ApiClients />
                  </PermissionRoute>
                }
              />

              {/* Configuración y usuarios */}
              <Route path="configuracion" element={<Configuracion />} />
              <Route path="usuarios" element={<Navigate to="/configuracion?tab=usuarios" replace />} />
            </Route>

            {/* Cualquier ruta desconocida → dashboard */}
            <Route path="*" element={<Navigate to="/dashboard" replace />} />
          </Routes>
        </Suspense>
      </UndoToastProvider>
    </BrowserRouter>
  )
}
