import { ChevronRight, Sun, Moon, PhoneCall } from 'lucide-react'
import { useNavigate, useLocation, useSearchParams } from 'react-router-dom'
import useBrandStore from '@/store/brandStore'
import useThemeStore from '@/store/themeStore'
import useManualApoyoStore from '@/store/manualApoyoStore'
import NotificationsMenu from './NotificationsMenu'
import UserMenu from './UserMenu'

const ROUTE_LABELS = {
  '/dashboard':    'Dashboard',
  '/leads':        'Leads',
  '/leads/nuevo':  'Leads',
  '/asignacion':   'Asignación',
  '/carga-masiva': 'Carga Masiva',
  '/reportes':     'Reportes',
  '/supervision-control': 'Supervisión y Control',
  '/configuracion':'Configuración',
}

const TAB_LABELS = {
  usuarios: 'Usuarios',
  correo: 'Correo',
  seguridad: 'Seguridad',
}

function useBreadcrumb(pathname, tab, fallbackLabel) {
  let label = ROUTE_LABELS[pathname]
  if (!label && pathname.startsWith('/leads/') && pathname !== '/leads/nuevo') {
    return [
      { label: 'Leads', path: '/leads' },
      { label: 'Detalle', path: null },
    ]
  }
  if (!label && pathname.startsWith('/leads/')) {
    label = ROUTE_LABELS['/leads/nuevo']
  }
  if (label && tab && TAB_LABELS[tab]) {
    return [
      { label, path: pathname },
      { label: TAB_LABELS[tab], path: null },
    ]
  }
  return label ? [{ label, path: null }] : [{ label: fallbackLabel, path: null }]
}

export default function Header() {
  const brand = useBrandStore((s) => s.brand)
  const { isDark, toggleTheme } = useThemeStore()
  const navigate = useNavigate()
  const location = useLocation()
  const [searchParams] = useSearchParams()
  const breadcrumb = useBreadcrumb(
    location.pathname,
    searchParams.get('tab'),
    brand?.company_name || 'CRM',
  )

  const isDemoMode = import.meta.env.VITE_DEMO_MODE === 'true'
  const toggleManual = useManualApoyoStore((s) => s.toggleManual)

  return (
    <header className="relative h-14 bg-white border-b border-gray-100 shadow-[0_1px_3px_rgba(0,0,0,0.04)] flex items-center justify-between px-6 shrink-0 z-30 transition-colors">
      {/* Breadcrumb */}
      <div className="flex items-center gap-1.5 text-sm">
        <span className="text-gray-400 font-medium">{brand.company_name}</span>
        {breadcrumb.map((crumb, index) => (
          <span key={index} className="flex items-center gap-1.5">
            <ChevronRight size={14} className="text-gray-300" />
            {crumb.path ? (
              <button onClick={() => navigate(crumb.path)} className="text-[var(--brand-primary)] hover:opacity-80 font-medium transition-colors">
                {crumb.label}
              </button>
            ) : (
              <span className="font-semibold text-gray-800">{crumb.label}</span>
            )}
          </span>
        ))}
      </div>

      {/* Right side: manual button + notifications + dark mode toggle + badge demo (si aplica) + user menu */}
      <div className="flex items-center gap-2">
        {/* Botón Manual de Guiones Telefónicos */}
        <button
          type="button"
          onClick={toggleManual}
          title="Manual de Apoyo Telefónico (Alt+M)"
          className="flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl text-xs font-semibold text-[#df2029] dark:text-[#ff6b72] bg-red-50 hover:bg-red-100 dark:bg-[#df2029]/15 dark:hover:bg-[#df2029]/25 border border-red-200 dark:border-[#df2029]/30 transition-all focus:outline-none focus-visible:ring-2 focus-visible:ring-[#df2029]/40 active:scale-95 cursor-pointer shadow-xs"
        >
          <PhoneCall size={14} className="text-[#df2029] dark:text-[#ff6b72]" />
          <span className="hidden sm:inline">Guiones</span>
        </button>

        {isDemoMode && (
          <span className="bg-amber-50 text-amber-700 text-xs font-semibold px-2.5 py-1 rounded-full border border-amber-200">
            Modo Demo
          </span>
        )}

        {/* Centro de notificaciones */}
        <NotificationsMenu />

        {/* Botón para cambiar versión oscura / clara */}
        <button
          type="button"
          onClick={toggleTheme}
          aria-label={isDark ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro'}
          title={isDark ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro'}
          className="p-2 rounded-xl text-gray-500 hover:text-gray-900 hover:bg-gray-100 transition-all duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)]/40 active:scale-95 flex items-center justify-center cursor-pointer"
        >
          {isDark ? (
            <Sun size={18} className="text-amber-400" />
          ) : (
            <Moon size={18} className="text-slate-600 hover:text-indigo-600 transition-colors" />
          )}
        </button>

        <UserMenu />
      </div>
    </header>
  )
}
