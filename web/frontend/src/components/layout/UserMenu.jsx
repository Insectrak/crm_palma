import { useState, useRef, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Settings, LogOut, ChevronDown, Sun, Moon } from 'lucide-react'
import { cn } from '@/lib/utils'
import useAuthStore from '@/store/authStore'
import useThemeStore from '@/store/themeStore'

/**
 * UserMenu — Avatar + popup desplegable que vive en la esquina superior
 * derecha del Header. Paridad patrón premium/patrón estándar/patrón estándar Lightning,
 * donde el menu del usuario siempre vive en el top-right global.
 *
 * Antes vivia en el footer del Sidebar, ocupando espacio que ahora puede
 * usarse para mas items de navegacion.
 */
export default function UserMenu() {
  const navigate = useNavigate()
  const { user, logout } = useAuthStore()
  const { isDark, toggleTheme } = useThemeStore()
  const [open, setOpen] = useState(false)
  const btnRef = useRef(null)
  const menuRef = useRef(null)

  // Click fuera cierra el menu.
  useEffect(() => {
    const handleClick = (e) => {
      if (btnRef.current?.contains(e.target)) return
      if (menuRef.current && !menuRef.current.contains(e.target)) setOpen(false)
    }
    document.addEventListener('mousedown', handleClick)
    return () => document.removeEventListener('mousedown', handleClick)
  }, [])

  // Cierra con tecla Escape (accesibilidad).
  useEffect(() => {
    if (!open) return
    const handleKey = (e) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [open])

  const displayName = user?.nombre_completo || user?.username || 'Usuario'
  const initials = displayName
    .split(' ')
    .map((w) => w[0])
    .slice(0, 2)
    .join('')
    .toUpperCase() || 'U'

  const items = [
    {
      icon: isDark ? Sun : Moon,
      label: isDark ? 'Modo claro' : 'Modo oscuro',
      onClick: () => { toggleTheme(); setOpen(false) },
    },
    {
      icon: Settings,
      label: 'Configuración',
      onClick: () => { navigate('/configuracion'); setOpen(false) },
    },
    { separator: true },
    {
      icon: LogOut,
      label: 'Cerrar sesión',
      onClick: () => { logout(); navigate('/login') },
      danger: true,
    },
  ]

  return (
    <div className="relative">
      <button
        ref={btnRef}
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'flex items-center gap-2 h-9 pl-1 pr-2 rounded-lg transition-colors',
          'hover:bg-gray-100 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)]/30'
        )}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Menú de usuario, ${displayName}`}
      >
        <div className="w-7 h-7 bg-[var(--brand-primary)] rounded-full flex items-center justify-center text-white text-[11px] font-bold shadow-sm">
          {initials}
        </div>
        <div className="hidden sm:flex flex-col items-start leading-tight max-w-[140px]">
          <span className="text-[12px] font-semibold text-gray-800 truncate w-full">
            {displayName}
          </span>
          <span className="text-[10px] text-gray-500 capitalize truncate w-full">
            {user?.role || 'usuario'}
          </span>
        </div>
        <ChevronDown
          size={14}
          className={cn(
            'text-gray-400 transition-transform duration-150',
            open && 'rotate-180'
          )}
        />
      </button>

      {open && (
        <div
          ref={menuRef}
          role="menu"
          className={cn(
            'absolute top-full right-0 mt-2 w-64 z-[999]',
            'bg-white rounded-2xl border border-gray-100 py-2 overflow-hidden',
            'shadow-[0_8px_40px_rgba(0,0,0,0.16)]'
          )}
        >
          {/* Header del popup con avatar grande + role badge */}
          <div className="px-4 py-3 mb-1">
            <div className="flex items-center gap-3">
              <div className="w-10 h-10 bg-gradient-to-br from-indigo-500 to-indigo-700 rounded-xl flex items-center justify-center text-white text-sm font-bold shrink-0 shadow-md">
                {initials}
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold text-gray-900 truncate leading-tight">
                  {displayName}
                </p>
                <span className="inline-flex items-center mt-0.5 px-1.5 py-0.5 rounded text-[10px] font-semibold bg-indigo-50 text-indigo-600 capitalize">
                  {user?.role || 'usuario'}
                </span>
              </div>
            </div>
          </div>

          <div className="border-t border-gray-100 mb-1" />

          {items.map((item, i) =>
            item.separator ? (
              <div key={i} className="border-t border-gray-100 my-1" />
            ) : (
              <button
                key={i}
                role="menuitem"
                onClick={item.onClick}
                className={cn(
                  'w-[calc(100%-8px)] mx-1 text-left px-3 py-2 text-[13px] flex items-center gap-2.5 rounded-lg transition-colors',
                  item.danger
                    ? 'text-red-600 hover:bg-red-50'
                    : 'text-gray-700 hover:bg-gray-50'
                )}
              >
                <item.icon
                  size={14}
                  className={item.danger ? 'text-red-400' : 'text-gray-400'}
                />
                {item.label}
              </button>
            )
          )}

          {/* V070.57 — Footer del popup con la versión.
              Patrón patrón estándar: la versión vive en el menú del
              usuario, no en el sidebar principal. Visible solo al abrir
              este popup → sin contaminar la UI principal. */}
          <div className="border-t border-gray-100 mt-1 pt-2 pb-1 px-4">
            <p className="text-[10px] text-gray-400 text-center">
              CRM v3.0
            </p>
          </div>
        </div>
      )}
    </div>
  )
}
