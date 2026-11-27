import { memo, useState, useEffect } from 'react'
import { NavLink } from 'react-router-dom'
import {
  Home, Users2, UserPlus, Upload,
  BarChart2, Phone, CalendarDays, Building2,
  PanelLeftClose, PanelLeftOpen,
  Shuffle, FileText, FileSpreadsheet, MessageCircle, Archive, Plug, Target, LayoutGrid, Activity,
  RotateCcw, LayoutDashboard, Megaphone, Trash2, Sparkles, ShieldCheck, Compass,
} from 'lucide-react'
import { cn } from '@/lib/utils'
import useAuthStore from '@/store/authStore'
import useBrandStore from '@/store/brandStore'
import api from '@/lib/api'
import { safeLocal } from '@/lib/safeStorage'

// Ordenado por frecuencia de uso y agrupado por propósito (UX: Fitts + Gestalt).
// Bloque 1 — Operación diaria (todos los roles).
// Bloque 2 — Gestión administrativa (supervisor/admin).
//
// ADR-0011 — Cada item declara `permissionKey` (formato resource.action).
// Si el usuario tiene `permissions` custom en el JWT, el filtro usa esa
// como fuente de verdad. Si no (usuario legacy sin role_id), cae al
// filtro por `roles` array (comportamiento previo, sin breaking changes).
const ALL_MENU_ITEMS = [
  // ── Operación diaria ─────────────────────────────────────────
  // V070.110 — "Inicio" (no "Dashboard") para no confundir con "Dashboards"
  // (plural). Patron patrón estándar/patrón estándar: el home personal del usuario
  // se llama "Home/Inicio", los paneles combinados son "Dashboards".
  { label: 'Inicio', icon: Home, path: '/dashboard', roles: null, group: 'daily', permissionKey: null },
  { label: 'Leads', icon: Users2, path: '/leads', roles: null, group: 'daily', permissionKey: 'leads.view' },
  { label: 'Agenda', icon: CalendarDays, path: '/agenda', roles: null, group: 'daily', permissionKey: 'agenda.view' },
  { label: 'Chat', icon: MessageCircle, path: '/chat', roles: null, group: 'daily', permissionKey: 'chat.view' },
  { label: 'Llamadas', icon: Phone, path: '/llamadas', roles: null, group: 'daily', permissionKey: 'llamadas.view' },
  { label: 'Carga Masiva', icon: Upload, path: '/carga-masiva', roles: null, group: 'daily', permissionKey: 'carga_masiva.use' },
  // ── Gestión (supervisor/admin) ──────────────────────────────
  { label: 'Supervisión y Control', icon: ShieldCheck, path: '/supervision-control', roles: ['admin'], group: 'mgmt', permissionKey: null },
  { label: 'Gestión de Lotes', icon: FileSpreadsheet, path: '/gestion-lotes', roles: ['admin'], group: 'mgmt', permissionKey: null },
  { label: 'Panel Jefatura', icon: LayoutDashboard, path: '/dashboard-jefatura', roles: ['admin', 'supervisor'], group: 'mgmt', permissionKey: 'dashboards.view' },
  { label: 'Bolsa TMK', icon: RotateCcw, path: '/reciclaje-tmk', roles: ['admin', 'supervisor'], group: 'mgmt', permissionKey: 'leads.manage' },
  { label: 'Histórico', icon: Archive, path: '/historicos', roles: ['admin'], group: 'mgmt', permissionKey: 'historicos.view' },
  { label: 'Papelera Leads', icon: Trash2, path: '/leads-inactivos', roles: ['admin'], group: 'mgmt', permissionKey: 'leads.delete' },
  { label: 'Asignación', icon: UserPlus, path: '/asignacion', roles: ['admin'], group: 'mgmt', permissionKey: null },
  { label: 'Formularios', icon: FileText, path: '/formularios', roles: ['admin', 'supervisor'], group: 'mgmt', permissionKey: 'formularios.manage' },
  // V070.109 — patrón estándar: un solo "Reportes" landing + "Dashboards"
  { label: 'Reportes', icon: BarChart2, path: '/reportes', roles: null, group: 'mgmt', permissionKey: 'reportes.view' },
  { label: 'Reportería Especial', icon: Sparkles, path: '/reportes-especiales', roles: ['admin'], group: 'mgmt', permissionKey: null },
  { label: 'Dashboards', icon: LayoutGrid, path: '/dashboards', roles: ['admin', 'supervisor'], group: 'mgmt', permissionKey: 'dashboards.view' },
  { label: 'Metas', icon: Target, path: '/metas', roles: ['admin', 'supervisor'], group: 'mgmt', permissionKey: 'metas.view' },
  { label: 'Leads Campañas', icon: Megaphone, path: '/leads-campanas', roles: ['admin'], group: 'mgmt', permissionKey: null },
  { label: 'Estrategias externas', icon: Compass, path: '/estrategias-externas', roles: ['admin', 'supervisor'], group: 'mgmt', permissionKey: 'dashboards.view' },
  { label: 'Reparto leads', icon: Shuffle, path: '/rotacion', roles: ['admin'], group: 'mgmt', permissionKey: 'rotacion.manage' },
  { label: 'Rendimiento de Ads', icon: Activity, path: '/rendimiento-ads', roles: ['admin', 'supervisor'], group: 'mgmt', permissionKey: 'dashboards.view' },
  { label: 'Integraciones', icon: Plug, path: '/integraciones', roles: ['admin'], group: 'mgmt', permissionKey: 'integraciones.manage' },
]

// V070.55 — Tooltip rediseñado al patrón estándar:
//   - Fondo blanco con borde sutil + sombra profunda (en lugar de negro
//     instantáneo).
//   - Delay de 250ms en el hover para no aparecer en cada movimiento de
//     mouse al recorrer el menú (estándar patrón estándar).
//   - Flecha apuntando al icono.
function SideTooltip({ text, children }) {
  return (
    <div className="relative group/tip w-full">
      {children}
      <div className="fixed left-16 ml-3 px-3 py-2 bg-white dark:bg-slate-800 text-gray-900 dark:text-slate-100 text-xs font-medium rounded-lg
                      whitespace-nowrap opacity-0 pointer-events-none group-hover/tip:opacity-100
                      transition-opacity duration-200 delay-200 z-[9999]
                      shadow-[0_4px_16px_rgba(0,0,0,0.12)] border border-gray-200 dark:border-slate-700
                      -translate-y-1/2">
        {text}
        <div className="absolute right-full top-1/2 -translate-y-1/2 border-[6px] border-transparent border-r-white dark:border-r-slate-800" />
        <div className="absolute right-full top-1/2 -translate-y-1/2 -mr-[1px] border-[6px] border-transparent border-r-gray-200 dark:border-r-slate-700 -z-10" />
      </div>
    </div>
  )
}

function MenuItem({ icon: Icon, label, path, badge, collapsed }) {
  const link = (
    <NavLink
      to={path}
      className={({ isActive }) =>
        cn(
          // V070.55 — Indicador visual del item activo:
          //   - Barra lateral izquierda de 3px en color brand (estilo
          //     patrón premium/patrón estándar) — visible siempre, no solo en hover.
          //   - Mantiene el bg-brand + sombra cuando expandido.
          //   - Cuando colapsado, la barra lateral es la pista visual
          //     principal (el bg-brand sería opcional, pero lo dejamos para
          //     legibilidad redoble).
          'relative flex items-center rounded-lg text-sm font-medium transition-all duration-150 w-full',
          'outline-none focus:outline-none focus-visible:ring-2 focus-visible:ring-white/30 focus-visible:ring-offset-0',
          collapsed ? 'justify-center p-2.5' : 'gap-3 px-3 py-2',
          isActive
            ? 'bg-[var(--brand-primary)] text-white shadow-[0_2px_8px_rgba(var(--brand-primary-rgb),0.35)] before:absolute before:left-0 before:top-1.5 before:bottom-1.5 before:w-[3px] before:rounded-r-full before:bg-white/90'
            : 'text-slate-400 hover:bg-white/7 hover:text-slate-100'
        )
      }
    >
      {Icon && <Icon size={17} className="shrink-0" />}
      {!collapsed && <span className="flex-1 truncate">{label}</span>}
      {!collapsed && badge > 0 && (
        <span className="bg-red-500 text-white text-[10px] font-bold px-1.5 py-0.5 rounded-full min-w-[18px] text-center leading-tight">
          {badge > 99 ? '99+' : badge}
        </span>
      )}
      {collapsed && badge > 0 && (
        <span className="absolute top-0.5 right-0.5 w-2 h-2 bg-red-500 rounded-full ring-2 ring-[var(--brand-sidebar-bg,#0f172a)]" />
      )}
    </NavLink>
  )

  if (collapsed) {
    return (
      <div className="relative">
        <SideTooltip text={badge > 0 ? `${label} (${badge > 99 ? '99+' : badge})` : label}>
          {link}
        </SideTooltip>
      </div>
    )
  }

  return link
}

// V067.1 — memo: el Sidebar no recibe props, asi que con React.memo y
// comparador default se monta UNA sola vez por sesion y solo se re-renderiza
// cuando cambian sus subscripciones internas (auth store, brand store,
// chatBadge, sinAsignar, collapsed). Antes, cualquier URL change del Router
// hacia que <Layout> re-renderizara, lo que provocaba el "parpadeo" visual
// percibido al crear/eliminar vistas o filtros que tocan el ?view= param.
function Sidebar() {
  const { user } = useAuthStore()
  const brand = useBrandStore((s) => s.brand)
  const [sinAsignar, setSinAsignar] = useState(0)
  const [chatBadge, setChatBadge] = useState(0)

  // V070.55 — Auto-collapse responsive:
  //   - Si el user ya tiene una preferencia guardada (toggled manualmente),
  //     respetarla siempre.
  //   - Si no tiene preferencia (primer mount), default = colapsado en
  //     viewports <1024px (tablets y laptops chicas). Asi entra mas
  //     contenido sin sacrificar la barra lateral.
  //   - Esto matchea el patron patrón premium/patrón estándar/patrón estándar en
  //     responsive breakpoints.
  const [collapsed, setCollapsed] = useState(() => {
    const saved = safeLocal.getItem('sidebar_collapsed')
    if (saved !== null) return saved === 'true'
    return typeof window !== 'undefined' && window.innerWidth < 1024
  })

  // Marca "user-touched" para no override la preferencia explicita del user
  // si después cambia el tamaño del viewport.
  const toggleCollapsed = () => {
    const next = !collapsed
    setCollapsed(next)
    safeLocal.setItem('sidebar_collapsed', String(next))
  }

  // Solo aplica auto-collapse si el user NO ha tocado el toggle manualmente.
  useEffect(() => {
    if (safeLocal.getItem('sidebar_collapsed') !== null) return // user touched
    const handleResize = () => {
      const shouldCollapse = window.innerWidth < 1024
      setCollapsed(shouldCollapse)
    }
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  const role = user?.role || 'asesor'
  const perms = user?.permissions || {}
  // ADR-0011 + V088 — Si el usuario tiene `role_id` asignado (rol custom del
  // nuevo sistema), ESE es la fuente de verdad SIEMPRE, incluso si su
  // permissions JSONB está vacío. Asignarle un rol custom "Sin Acceso" con
  // permissions={} debe BLOQUEARLE TODO, no caer al filtro legacy.
  //
  // V5.73.6 — Adicionalmente, si el user tiene permissions JSONB no vacío
  // (vino del fallback al rol built-in en /auth/me/permissions cuando
  // u.role_id IS NULL, fix V5.73.4), también entramos al branch estricto.
  // Sin esta condición, usuarios legacy seguían viendo módulos a los que
  // el admin les quito permisos porque role_id seguía NULL.
  //
  // El fallback al filtro por roles legacy solo aplica para usuarios SIN
  // role_id Y SIN permissions efectivos (caso raro, usuario completamente
  // huérfano del sistema de permisos).
  const hasCustomRole =
    user?.role_id != null ||
    (perms && Object.keys(perms).length > 0)
  const allBypass = role === 'admin' || perms._all === true

  const [jefaturaAcceso, setJefaturaAcceso] = useState(false)

  useEffect(() => {
    if (role === 'supervisor') {
      api.get('/api/dashboard/jefatura/mi-acceso')
        .then(res => setJefaturaAcceso(res.data?.acceso === true))
        .catch(() => setJefaturaAcceso(false))
    }
  }, [role])

  const visibleItems = ALL_MENU_ITEMS.filter(item => {
    if (item.path === '/supervision-control') {
      return role === 'admin'
    }
    if (item.path === '/gestion-lotes') {
      return role === 'admin'
    }
    if (item.path === '/dashboard-jefatura') {
      return role === 'admin' || jefaturaAcceso
    }
    if (item.path === '/asignacion') {
      return role === 'admin'
    }
    if (item.path === '/leads-campanas') {
      return role === 'admin'
    }
    if (item.path === '/reportes-especiales') {
      return role === 'admin'
    }
    if (allBypass) return true
    if (hasCustomRole) {
      // Usuario con rol custom: el rol es la fuente de verdad. Item sin
      // permissionKey (Inicio) es universal para autenticados; el resto
      // requiere permiso explícito = true.
      if (!item.permissionKey) return true
      return perms[item.permissionKey] === true
    }
    // Fallback legacy: filtro por roles array (usuarios sin role_id).
    return !item.roles || item.roles.includes(role)
  })

  // V070.79 — UX fix: badge de "sin asignar" responsive (solo para admin).
  useEffect(() => {
    if (role !== 'admin') return
    const fetchSinAsignar = () => {
      api.get('/api/leads?sin_asesor=true&limit=1')
        .then(res => setSinAsignar(res.data?.total || 0))
        .catch(() => { })
    }
    fetchSinAsignar()
    const interval = setInterval(fetchSinAsignar, 15_000)
    const onVisible = () => {
      if (document.visibilityState === 'visible') fetchSinAsignar()
    }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('leads:assignment-changed', fetchSinAsignar)
    return () => {
      clearInterval(interval)
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('leads:assignment-changed', fetchSinAsignar)
    }
  }, [role])

  // Chat: badge de chats no leidos (todos los roles). 10s + refresh al
  // volver a la pestaña + refresh inmediato cuando Chat.jsx dispara el
  // evento 'chat:unread-changed' al abrir una conversacion (evita el lag
  // de hasta 15s en que el badge rojo seguia apareciendo aunque el usuario
  // ya habia entrado al chat).
  useEffect(() => {
    const fetchUnread = () => {
      api.get('/api/whatsapp/unread_summary')
        .then(res => setChatBadge(res.data?.badge_total || 0))
        .catch(() => { })
    }
    fetchUnread()
    const interval = setInterval(fetchUnread, 10000)
    const onVisible = () => {
      if (document.visibilityState === 'visible') fetchUnread()
    }
    document.addEventListener('visibilitychange', onVisible)
    window.addEventListener('chat:unread-changed', fetchUnread)
    return () => {
      clearInterval(interval)
      document.removeEventListener('visibilitychange', onVisible)
      window.removeEventListener('chat:unread-changed', fetchUnread)
    }
  }, [])

  return (
    <aside
      // V067.6 — REVERT parcial de V067.5: `isolation: isolate` + `contain:
      // layout paint` cortaban la cascada de repaints pero rompieron el
      // posicionamiento de los popups que se montan via createPortal a
      // document.body (FilterBuilder, PortalSelect, etc): el popup se
      // renderizaba en coordenadas erroneas, encimando el sidebar.
      // Aceptamos un parpadeo minimo a cambio de tener todos los dropdowns
      // funcionando. La memo(Sidebar) sigue activa y absorbe los re-renders
      // de React; el residual visual es solo paint del browser y es leve.
      style={{ backgroundColor: brand.sidebar_bg }}
      className={cn(
        'h-screen flex flex-col shrink-0 shadow-[4px_0_24px_rgba(0,0,0,0.25)] transition-[width] duration-300 ease-in-out overflow-hidden',
        collapsed ? 'w-16' : 'w-64'
      )}
    >
      {/* Logo + toggle */}
      <div className={cn(
        'border-b border-white/8 flex items-center',
        collapsed ? 'p-3 justify-center flex-col gap-2' : 'px-4 py-3 justify-between'
      )}>
        {!collapsed && (
          <div className="flex items-center gap-3 min-w-0">
            <div
              className="w-9 h-9 rounded-xl flex items-center justify-center shadow-[0_2px_8px_rgba(0,0,0,0.4)] shrink-0 overflow-hidden"
              style={{ backgroundColor: brand.logo_data_url ? 'transparent' : brand.primary_color }}
            >
              {brand.logo_data_url
                ? <img src={brand.logo_data_url} alt="logo" className="w-full h-full object-contain" />
                : <Building2 size={20} className="text-white" />}
            </div>
            <div className="min-w-0">
              <p className="text-white font-bold text-sm leading-tight truncate">{brand.company_name}</p>
              <p className="text-white/60 text-xs truncate">{brand.company_subtitle}</p>
            </div>
          </div>
        )}

        {collapsed && (
          <div
            className="w-9 h-9 rounded-xl flex items-center justify-center shadow-[0_2px_8px_rgba(0,0,0,0.4)] overflow-hidden"
            style={{ backgroundColor: brand.logo_data_url ? 'transparent' : brand.primary_color }}
          >
            {brand.logo_data_url
              ? <img src={brand.logo_data_url} alt="logo" className="w-full h-full object-contain" />
              : <Building2 size={20} className="text-white" />}
          </div>
        )}

        {/* V070.55 — Toggle con icono dinámico (patrón estándar Lightning):
              - PanelLeftClose cuando expandido → indica "lo voy a cerrar"
              - PanelLeftOpen cuando colapsado → indica "lo voy a abrir"
            Feedback visual claro de qué pasará al hacer click. */}
        <button
          onClick={toggleCollapsed}
          className={cn(
            'text-slate-400 hover:text-white hover:bg-white/10 rounded-lg transition-all p-1.5',
            collapsed && 'mt-1'
          )}
          title={collapsed ? 'Expandir menú lateral' : 'Colapsar menú lateral'}
          aria-label={collapsed ? 'Expandir menú lateral' : 'Colapsar menú lateral'}
        >
          {collapsed ? <PanelLeftOpen size={16} /> : <PanelLeftClose size={16} />}
        </button>
      </div>

      {/* Navegación — agrupada por propósito con separador visual */}
      <nav
        className={cn(
          'flex-1 overflow-y-auto overflow-x-hidden [&::-webkit-scrollbar]:hidden',
          collapsed ? 'p-2 space-y-1' : 'p-3 space-y-0.5'
        )}
        style={{ scrollbarWidth: 'none', msOverflowStyle: 'none' }}
      >
        {visibleItems.map((item, idx) => {
          const prev = visibleItems[idx - 1]
          const needsDivider = prev && prev.group !== item.group
          return (
            <div key={item.path}>
              {needsDivider && (
                collapsed ? (
                  <div className="my-2 mx-auto h-px w-6 bg-white/10" />
                ) : (
                  <div className="mt-2 mb-0.5 px-3 text-[10px] font-semibold uppercase tracking-wider text-slate-500">
                    Gestión
                  </div>
                )
              )}
              <MenuItem
                {...item}
                badge={
                  item.path === '/asignacion' ? sinAsignar
                    : item.path === '/chat' ? chatBadge
                      : 0
                }
                collapsed={collapsed}
              />
            </div>
          )
        })}
      </nav>

      {/* V070.57 — Sin footer.
          El sidebar de CRMs profesionales/patrón premium se dedica 100% a
          navegación. La versión del producto vive en el UserMenu popup
          (top-right) — visible solo cuando el usuario explicitamente la
          consulta, sin contaminar la UI principal. */}
    </aside>
  )
}

export default memo(Sidebar)
