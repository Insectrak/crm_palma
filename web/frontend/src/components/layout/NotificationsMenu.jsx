import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Bell,
  AlertTriangle,
  Calendar,
  RefreshCw,
  Clock,
  UserCheck,
  CheckCircle2,
  ExternalLink,
  Flame,
  UserPlus,
  X
} from 'lucide-react'
import api from '@/lib/api'

export default function NotificationsMenu() {
  const navigate = useNavigate()
  const [isOpen, setIsOpen] = useState(false)
  const [notifications, setNotifications] = useState([])
  const [loading, setLoading] = useState(false)
  const [activeFilter, setActiveFilter] = useState('todas')
  const [dismissedIds, setDismissedIds] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('crm_dismissed_notifs') || '[]')
    } catch {
      return []
    }
  })
  const menuRef = useRef(null)

  const fetchNotifications = async () => {
    try {
      setLoading(true)
      const res = await api.get('/api/notifications/inbox')
      setNotifications(res.data?.items || [])
    } catch (err) {
      // fail-soft
    } finally {
      setLoading(false)
    }
  }

  // Carga inicial y sondeo periódico cada 60s
  useEffect(() => {
    fetchNotifications()
    const interval = setInterval(fetchNotifications, 60000)
    return () => clearInterval(interval)
  }, [])

  // Cerrar al hacer clic afuera
  useEffect(() => {
    function handleClickOutside(e) {
      if (menuRef.current && !menuRef.current.contains(e.target)) {
        setIsOpen(false)
      }
    }
    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside)
    }
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [isOpen])

  // Descartar una notificación
  const handleDismiss = (e, id) => {
    e.stopPropagation()
    const updated = [...dismissedIds, id]
    setDismissedIds(updated)
    try {
      localStorage.setItem('crm_dismissed_notifs', JSON.stringify(updated))
    } catch {}
  }

  // Limpiar todas
  const handleDismissAll = () => {
    const allIds = notifications.map(n => n.id)
    const merged = Array.from(new Set([...dismissedIds, ...allIds]))
    setDismissedIds(merged)
    try {
      localStorage.setItem('crm_dismissed_notifs', JSON.stringify(merged))
    } catch {}
  }

  const activeNotifications = notifications.filter(n => !dismissedIds.includes(n.id))

  const filteredNotifications = activeNotifications.filter(n => {
    if (activeFilter === 'todas') return true
    if (activeFilter === 'nuevos') return n.type === 'lead_nuevo'
    if (activeFilter === 'proxima') return n.type === 'proxima_gestion'
    if (activeFilter === 'sla') return n.type === 'sla_15m'
    if (activeFilter === 'citas') return n.type === 'cita' || n.type === 'cita_vencida'
    if (activeFilter === 'recontactos') return n.type === 'recontacto' || n.type === 'cola_estancada'
    return true
  })

  const count = activeNotifications.length

  const getIcon = (type) => {
    switch (type) {
      case 'lead_nuevo':
        return <UserPlus size={16} className="text-emerald-500 shrink-0 mt-0.5" />
      case 'proxima_gestion':
        return <Clock size={16} className="text-amber-500 shrink-0 mt-0.5" />
      case 'sla_15m':
        return <Flame size={16} className="text-red-500 shrink-0 mt-0.5" />
      case 'cita':
        return <Calendar size={16} className="text-blue-500 shrink-0 mt-0.5" />
      case 'cita_vencida':
        return <AlertTriangle size={16} className="text-rose-500 shrink-0 mt-0.5" />
      case 'recontacto':
        return <UserCheck size={16} className="text-amber-500 shrink-0 mt-0.5" />
      case 'cola_estancada':
        return <Clock size={16} className="text-orange-500 shrink-0 mt-0.5" />
      default:
        return <AlertTriangle size={16} className="text-indigo-500 shrink-0 mt-0.5" />
    }
  }

  const formatRelativeTime = (isoString, type) => {
    if (!isoString) return ''
    try {
      const d = new Date(isoString)
      const now = new Date()
      const diffMinutes = Math.round((d - now) / 60000)

      if (type === 'proxima_gestion' || type === 'cita') {
        if (diffMinutes > 0) {
          if (diffMinutes < 60) return `en ${diffMinutes} min`
          const hours = Math.floor(diffMinutes / 60)
          const mins = diffMinutes % 60
          return mins > 0 ? `en ${hours}h ${mins}m` : `en ${hours}h`
        } else if (diffMinutes >= -30) {
          return `hace ${Math.abs(diffMinutes)} min`
        }
      }

      const pastMinutes = Math.floor((now - d) / 60000)
      if (pastMinutes < 1) return 'ahora'
      if (pastMinutes < 60) return `hace ${pastMinutes}m`
      const diffHours = Math.floor(pastMinutes / 60)
      if (diffHours < 24) return `hace ${diffHours}h`
      return d.toLocaleDateString([], { day: '2-digit', month: '2-digit' })
    } catch {
      return ''
    }
  }

  return (
    <div className="relative" ref={menuRef}>
      {/* Botón de Campana */}
      <button
        type="button"
        onClick={() => {
          setIsOpen(p => !p)
          if (!isOpen) fetchNotifications()
        }}
        aria-label="Notificaciones"
        title="Centro de notificaciones y alertas"
        className={`relative p-2 rounded-xl transition-all duration-150 focus:outline-none focus-visible:ring-2 focus-visible:ring-[var(--brand-primary)]/40 active:scale-95 flex items-center justify-center cursor-pointer ${
          isOpen
            ? 'bg-indigo-50 text-indigo-600 dark:bg-indigo-950/50 dark:text-indigo-400'
            : 'text-gray-500 hover:text-gray-900 hover:bg-gray-100 dark:text-slate-400 dark:hover:text-slate-100 dark:hover:bg-slate-800/60'
        }`}
      >
        <Bell size={18} />

        {/* Badge contador */}
        {count > 0 && (
          <span className="absolute top-1.5 right-1.5 flex h-4 min-w-4 px-1 items-center justify-center rounded-full bg-red-500 text-[10px] font-bold text-white shadow-sm ring-2 ring-white dark:ring-[#090d16] animate-in fade-in zoom-in duration-200">
            {count > 99 ? '99+' : count}
          </span>
        )}
      </button>

      {/* Popover / Panel de Notificaciones */}
      {isOpen && (
        <div className="absolute right-0 mt-2 w-80 sm:w-96 rounded-2xl bg-white dark:bg-[#121a29] border border-gray-200/80 dark:border-slate-800 shadow-2xl z-50 overflow-hidden flex flex-col max-h-[520px] animate-in fade-in slide-in-from-top-2 duration-150">
          {/* Header del panel */}
          <div className="p-3.5 border-b border-gray-100 dark:border-slate-800/80 bg-gray-50/50 dark:bg-[#0c121e]/60 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="flex items-center justify-center w-7 h-7 rounded-lg bg-indigo-50 dark:bg-indigo-950/50 text-indigo-600 dark:text-indigo-400">
                <Bell size={14} />
              </span>
              <div>
                <h3 className="text-sm font-semibold text-gray-900 dark:text-slate-100 leading-tight">
                  Notificaciones
                </h3>
                <p className="text-[11px] text-gray-500 dark:text-slate-400">
                  {count === 0 ? 'Al día sin alertas' : `${count} alerta${count > 1 ? 's' : ''} pendiente${count > 1 ? 's' : ''}`}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-1">
              <button
                type="button"
                onClick={fetchNotifications}
                disabled={loading}
                title="Actualizar"
                className="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 dark:text-slate-400 dark:hover:text-slate-200 hover:bg-gray-100 dark:hover:bg-slate-800 transition-colors disabled:opacity-50"
              >
                <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
              </button>
              {count > 0 && (
                <button
                  type="button"
                  onClick={handleDismissAll}
                  className="text-[11px] font-medium text-indigo-600 hover:text-indigo-700 dark:text-indigo-400 dark:hover:text-indigo-300 px-2 py-1 rounded-md hover:bg-indigo-50 dark:hover:bg-indigo-950/40 transition-colors"
                >
                  Limpiar todo
                </button>
              )}
            </div>
          </div>

          {/* Filtros rápidos */}
          <div className="flex items-center gap-1 px-3 py-2 border-b border-gray-100 dark:border-slate-800 bg-white dark:bg-[#121a29] overflow-x-auto text-xs scrollbar-none">
            {[
              { id: 'todas', label: 'Todas' },
              { id: 'nuevos', label: 'Nuevos' },
              { id: 'proxima', label: 'Próx. Acción' },
              { id: 'sla', label: 'SLA' },
              { id: 'citas', label: 'Citas' },
              { id: 'recontactos', label: 'Recontactos' },
            ].map(tab => (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveFilter(tab.id)}
                className={`px-2.5 py-1 rounded-full text-xs font-medium transition-colors shrink-0 ${
                  activeFilter === tab.id
                    ? 'bg-gray-900 text-white dark:bg-slate-100 dark:text-slate-900'
                    : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100 dark:text-slate-400 dark:hover:text-slate-200 dark:hover:bg-slate-800/60'
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>

          {/* Lista de Notificaciones */}
          <div className="flex-1 overflow-y-auto divide-y divide-gray-100/80 dark:divide-slate-800/60">
            {filteredNotifications.length === 0 ? (
              <div className="py-12 px-4 text-center flex flex-col items-center justify-center text-gray-400 dark:text-slate-500">
                <CheckCircle2 size={36} className="text-emerald-500/80 mb-2.5" />
                <p className="text-sm font-medium text-gray-700 dark:text-slate-300">
                  Todo está al día
                </p>
                <p className="text-xs text-gray-400 dark:text-slate-500 max-w-[200px] mt-0.5">
                  No hay alertas ni recordatorios pendientes en esta sección.
                </p>
              </div>
            ) : (
              filteredNotifications.map(item => (
                <div
                  key={item.id}
                  onClick={() => {
                    setIsOpen(false)
                    if (item.link) navigate(item.link)
                  }}
                  className="p-3 hover:bg-gray-50/80 dark:hover:bg-slate-800/40 transition-colors cursor-pointer flex items-start justify-between gap-3 group relative"
                >
                  <div className="flex items-start gap-2.5 min-w-0">
                    {getIcon(item.type)}
                    <div className="min-w-0">
                      <div className="flex items-center gap-1.5">
                        <span className="text-xs font-semibold text-gray-900 dark:text-slate-100 truncate">
                          {item.title}
                        </span>
                        {item.severity === 'urgent' && (
                          <span className="shrink-0 inline-flex items-center px-1.5 py-0.2 text-[9px] font-bold rounded-full bg-red-100 text-red-700 dark:bg-red-950/60 dark:text-red-300 border border-red-200 dark:border-red-900/50">
                            Urgente
                          </span>
                        )}
                      </div>
                      <p className="text-xs text-gray-600 dark:text-slate-300 mt-0.5 line-clamp-2 leading-relaxed">
                        {item.message}
                      </p>
                      <span className="text-[10px] text-gray-400 dark:text-slate-500 mt-1 block">
                        {formatRelativeTime(item.created_at, item.type)}
                      </span>
                    </div>
                  </div>

                  <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity shrink-0">
                    <button
                      type="button"
                      onClick={(e) => handleDismiss(e, item.id)}
                      title="Descartar notificación"
                      className="p-1 rounded-md text-gray-400 hover:text-gray-600 dark:hover:text-slate-200 hover:bg-gray-200/60 dark:hover:bg-slate-700/60 transition-colors"
                    >
                      <X size={13} />
                    </button>
                    <ExternalLink size={12} className="text-gray-400 dark:text-slate-500" />
                  </div>
                </div>
              ))
            )}
          </div>

          {/* Footer del panel */}
          <div className="p-2 border-t border-gray-100 dark:border-slate-800 bg-gray-50/50 dark:bg-[#0c121e]/60 flex flex-col gap-1 items-center justify-center text-center">
            {(activeFilter === 'sla' || activeNotifications.some(n => n.type === 'sla_15m')) && (
              <button
                type="button"
                onClick={() => {
                  setIsOpen(false)
                  navigate('/leads?alerta=sla_15m')
                }}
                className="text-xs font-semibold text-rose-600 hover:text-rose-700 dark:text-rose-400 dark:hover:text-rose-300 hover:underline inline-flex items-center gap-1 cursor-pointer"
              >
                ⏱️ Ver leads con SLA vencido en tabla →
              </button>
            )}
            <button
              type="button"
              onClick={() => {
                setIsOpen(false)
                navigate('/dashboard')
              }}
              className="text-xs font-medium text-indigo-600 hover:text-indigo-700 dark:text-indigo-400 dark:hover:text-indigo-300 hover:underline inline-flex items-center gap-1 cursor-pointer"
            >
              Ver panel completo de alertas en Dashboard →
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
