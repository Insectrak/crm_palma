import { useState, useRef, useEffect } from 'react'
import {
  User, Phone, Mail, IdCard, MapPin, Briefcase, Calendar,
  Tag, Megaphone, FileText, Clock, ExternalLink, Shield,
} from 'lucide-react'

/**
 * Formatea fecha ISO a legible en español (Perú).
 */
function formatDate(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('es-PE', {
      timeZone: 'America/Lima',
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return String(iso)
  }
}

/**
 * LeadSummaryPopover: Muestra un popup flotante con el resumen de un lead
 * previo al pasar el cursor encima o al hacer clic.
 *
 * Props:
 * - lead: Objeto con datos del lead (id, nombre, nombres, apellidos, telefono, email, dni, asesor_nombre, estado_nombre, fuente_nombre, campana, created_at, observaciones).
 * - children: Elemento disparador (ej. chip con el nombre del lead).
 * - titlePrefix: Texto contextual ("Lead Principal", "Lead Fusionado", etc.).
 */
export default function LeadSummaryPopover({
  lead,
  children,
  titlePrefix = 'Lead anterior',
  className = '',
}) {
  const [isOpen, setIsOpen] = useState(false)
  const [coords, setCoords] = useState({ top: 0, left: 0 })
  const triggerRef = useRef(null)
  const popoverRef = useRef(null)
  const timeoutRef = useRef(null)

  if (!lead) {
    return <span className={className}>{children}</span>
  }

  const fullName = lead.nombre || [lead.nombres, lead.apellidos].filter(Boolean).join(' ') || `Lead #${lead.id || '—'}`

  const updatePosition = () => {
    if (!triggerRef.current) return
    const rect = triggerRef.current.getBoundingClientRect()
    const popoverWidth = 320
    const popoverHeight = 300

    let left = rect.left + rect.width / 2 - popoverWidth / 2
    // Evitar desbordes horizontales de pantalla
    if (left < 10) left = 10
    if (left + popoverWidth > window.innerWidth - 10) {
      left = window.innerWidth - popoverWidth - 10
    }

    // Posición vertical: preferir arriba, si no cabe abajo
    let top = rect.top - popoverHeight - 8
    if (top < 10) {
      top = rect.bottom + 8
    }

    setCoords({ top, left })
  }

  const handleMouseEnter = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current)
    timeoutRef.current = setTimeout(() => {
      updatePosition()
      setIsOpen(true)
    }, 150)
  }

  const handleMouseLeave = () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current)
    timeoutRef.current = setTimeout(() => {
      setIsOpen(false)
    }, 200)
  }

  const handleClick = (e) => {
    e.stopPropagation()
    updatePosition()
    setIsOpen((prev) => !prev)
  }

  // Cerrar al hacer clic fuera o scrollear
  useEffect(() => {
    if (!isOpen) return
    const handleScrollOrClickOutside = (e) => {
      if (
        popoverRef.current &&
        !popoverRef.current.contains(e.target) &&
        triggerRef.current &&
        !triggerRef.current.contains(e.target)
      ) {
        setIsOpen(false)
      }
    }
    window.addEventListener('scroll', handleScrollOrClickOutside, true)
    document.addEventListener('mousedown', handleScrollOrClickOutside)
    return () => {
      window.removeEventListener('scroll', handleScrollOrClickOutside, true)
      document.removeEventListener('mousedown', handleScrollOrClickOutside)
    }
  }, [isOpen])

  return (
    <div
      ref={triggerRef}
      className={`inline-flex items-center ${className}`}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onClick={handleClick}
    >
      {children}

      {isOpen && (
        <div
          ref={popoverRef}
          style={{
            position: 'fixed',
            top: `${coords.top}px`,
            left: `${coords.left}px`,
            zIndex: 9999,
          }}
          className="w-80 rounded-xl bg-white dark:bg-slate-900 border border-indigo-200 dark:border-indigo-900/80 shadow-2xl p-4 text-left animate-in fade-in zoom-in-95 duration-150 pointer-events-auto"
          onMouseEnter={() => {
            if (timeoutRef.current) clearTimeout(timeoutRef.current)
          }}
          onMouseLeave={handleMouseLeave}
        >
          {/* Header del popover */}
          <div className="flex items-start justify-between gap-2 border-b border-gray-100 dark:border-slate-800 pb-2.5 mb-2.5">
            <div>
              <span className="inline-flex items-center gap-1 text-[10px] font-bold uppercase tracking-wider text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-950/80 px-2 py-0.5 rounded-md border border-indigo-100 dark:border-indigo-900/60 mb-1">
                {titlePrefix} {lead.id ? `· ID #${lead.id}` : ''}
              </span>
              <h4 className="text-sm font-bold text-gray-900 dark:text-slate-100 leading-tight">
                {fullName}
              </h4>
            </div>
            {lead.id && (
              <a
                href={`/leads/${lead.id}`}
                target="_blank"
                rel="noreferrer"
                className="text-gray-400 hover:text-indigo-600 dark:hover:text-indigo-400 transition-colors p-1"
                title="Abrir ficha original en nueva pestaña"
                onClick={(e) => e.stopPropagation()}
              >
                <ExternalLink size={13} />
              </a>
            )}
          </div>

          {/* Cuerpo con datos clave */}
          <div className="space-y-2 text-xs">
            {/* Dueño / Asesor original */}
            <div className="flex items-center gap-2 text-gray-700 dark:text-slate-300">
              <User size={13} className="text-indigo-500 shrink-0" />
              <span className="text-gray-500 dark:text-slate-400">Dueño/Asesor:</span>
              <span className="font-semibold text-gray-900 dark:text-slate-100 truncate">
                {lead.asesor_nombre || 'Sin asesor'}
              </span>
            </div>

            {/* Estado original */}
            <div className="flex items-center gap-2 text-gray-700 dark:text-slate-300">
              <Tag size={13} className="text-amber-500 shrink-0" />
              <span className="text-gray-500 dark:text-slate-400">Estado:</span>
              <span className="font-medium px-2 py-0.5 rounded-full bg-amber-50 text-amber-800 border border-amber-200 dark:bg-amber-950/60 dark:text-amber-300 dark:border-amber-900 text-[11px]">
                {lead.estado_nombre || '—'}
              </span>
            </div>

            {/* Teléfono */}
            {lead.telefono && (
              <div className="flex items-center gap-2 text-gray-700 dark:text-slate-300">
                <Phone size={13} className="text-emerald-500 shrink-0" />
                <span className="text-gray-500 dark:text-slate-400">Teléfono:</span>
                <span className="font-mono text-[11px] font-medium text-gray-900 dark:text-slate-100">
                  {lead.telefono}
                </span>
              </div>
            )}

            {/* Email */}
            {lead.email && (
              <div className="flex items-center gap-2 text-gray-700 dark:text-slate-300">
                <Mail size={13} className="text-sky-500 shrink-0" />
                <span className="text-gray-500 dark:text-slate-400">Email:</span>
                <span className="truncate text-gray-900 dark:text-slate-100">
                  {lead.email}
                </span>
              </div>
            )}

            {/* Documento / DNI */}
            {lead.dni && (
              <div className="flex items-center gap-2 text-gray-700 dark:text-slate-300">
                <IdCard size={13} className="text-slate-500 shrink-0" />
                <span className="text-gray-500 dark:text-slate-400">
                  {lead.tipo_documento || 'Documento'}:
                </span>
                <span className="font-mono text-gray-900 dark:text-slate-100 font-medium">
                  {lead.dni}
                </span>
              </div>
            )}

            {/* Fuente y Campaña */}
            {(lead.fuente_nombre || lead.campana) && (
              <div className="flex items-center gap-2 text-gray-700 dark:text-slate-300">
                <Megaphone size={13} className="text-teal-500 shrink-0" />
                <span className="text-gray-500 dark:text-slate-400">Origen:</span>
                <span className="truncate text-gray-800 dark:text-slate-200">
                  {[lead.fuente_nombre, lead.campana].filter(Boolean).join(' · ')}
                </span>
              </div>
            )}

            {/* Fecha de creación / registro */}
            <div className="flex items-center gap-2 text-gray-500 dark:text-slate-400 text-[11px] pt-1 border-t border-gray-100 dark:border-slate-800">
              <Calendar size={12} className="text-gray-400 shrink-0" />
              <span>Registrado: {formatDate(lead.created_at || lead.fecha_ingreso)}</span>
            </div>

            {/* Observaciones previas si existen */}
            {lead.observaciones && (
              <div className="mt-2 pt-2 border-t border-gray-100 dark:border-slate-800">
                <p className="text-[10px] font-semibold text-gray-400 uppercase tracking-wider mb-0.5">
                  Observaciones previas:
                </p>
                <p className="text-[11px] text-gray-600 dark:text-slate-300 line-clamp-3 bg-gray-50 dark:bg-slate-800/60 p-1.5 rounded border border-gray-200/60 dark:border-slate-700/60">
                  {lead.observaciones}
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

