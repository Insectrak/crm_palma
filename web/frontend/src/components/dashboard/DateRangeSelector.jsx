/**
 * DateRangeSelector — segmented control para el rango temporal del dashboard.
 *
 * Patron UX clase mundial (patrón estándar / patrón premium / patrón estándar):
 * - Pills horizontales agrupadas (`role=radiogroup`)
 * - Default visible (no escondido en dropdown)
 * - Custom abre popover con 2 inputs HTML5 date
 * - Sub-label dinamico "Mostrando datos del 13 jun – 19 jun 2026"
 * - Keyboard nav: arrows ←→ + Home/End + Enter/Space
 * - Responsive: en mobile el control hace scroll horizontal con snap
 * - A11y: ARIA radiogroup + aria-live para anunciar cambios
 *
 * Sticky por default para que el rango siempre sea visible al scrollear.
 */
import { useEffect, useRef, useState } from 'react'
import { Calendar, X } from 'lucide-react'
import { cn } from '@/lib/utils'

const PRESETS = [
  { key: 'today',    label: 'Hoy'       },
  { key: 'last_7',   label: '7 días'    },
  { key: 'last_30',  label: '30 días'   },
  { key: 'last_90',  label: 'Trimestre' },
  { key: 'last_365', label: 'Año'       },
]

export default function DateRangeSelector({
  preset,
  startDate,
  endDate,
  rangeLabel,
  setPreset,
  setCustomRange,
  className,
}) {
  const [customOpen, setCustomOpen] = useState(false)
  const [draftStart, setDraftStart] = useState(startDate)
  const [draftEnd,   setDraftEnd]   = useState(endDate)
  const popoverRef = useRef(null)
  const groupRef   = useRef(null)
  const customBtnRef = useRef(null)

  // Sincroniza el draft al abrir el popover
  useEffect(() => {
    if (customOpen) {
      setDraftStart(startDate)
      setDraftEnd(endDate)
    }
  }, [customOpen, startDate, endDate])

  // Cierra el popover al click afuera
  useEffect(() => {
    if (!customOpen) return
    const onClick = (e) => {
      if (popoverRef.current && !popoverRef.current.contains(e.target) &&
          customBtnRef.current && !customBtnRef.current.contains(e.target)) {
        setCustomOpen(false)
      }
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [customOpen])

  // Cierra con Escape
  useEffect(() => {
    if (!customOpen) return
    const onKey = (e) => {
      if (e.key === 'Escape') setCustomOpen(false)
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [customOpen])

  /** Keyboard nav segun WAI-ARIA radiogroup pattern. */
  const onKeyDown = (e, idx) => {
    const items = ['today', 'last_7', 'last_30', 'last_90', 'last_365', 'custom']
    let target
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
      target = (idx + 1) % items.length
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      target = (idx - 1 + items.length) % items.length
    } else if (e.key === 'Home') {
      target = 0
    } else if (e.key === 'End') {
      target = items.length - 1
    } else {
      return
    }
    e.preventDefault()
    const key = items[target]
    if (key === 'custom') {
      setCustomOpen(true)
    } else {
      setPreset(key)
    }
    // mover focus al nuevo pill
    if (groupRef.current) {
      const btns = groupRef.current.querySelectorAll('[role="radio"]')
      btns[target]?.focus()
    }
  }

  const applyCustom = () => {
    if (!draftStart || !draftEnd) return
    if (draftStart > draftEnd) return
    setCustomRange(draftStart, draftEnd)
    setCustomOpen(false)
  }

  return (
    <div className={cn('sticky top-0 z-20 -mx-4 px-4 py-3 bg-white/95 dark:bg-[#090d16]/95 backdrop-blur border-b border-gray-100 dark:border-slate-800 transition-colors', className)}>
      <div className="flex flex-col gap-1.5">
        {/* V096.1 — la fila exterior es flex SIN overflow para no clippear
            el popover. El overflow-x-auto (que necesita el mobile para
            scrollear los pills) vive solo en el div interno con los presets;
            el boton "Personalizar" + popover van fuera de ese div. */}
        <div
          ref={groupRef}
          role="radiogroup"
          aria-label="Rango temporal del dashboard"
          className="flex items-center gap-1"
        >
          <div className="flex items-center gap-1 overflow-x-auto snap-x min-w-0 [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden">
            {PRESETS.map((p, idx) => {
              const active = preset === p.key
              return (
                <button
                  key={p.key}
                  type="button"
                  role="radio"
                  aria-checked={active}
                  tabIndex={active ? 0 : -1}
                  onClick={() => setPreset(p.key)}
                  onKeyDown={(e) => onKeyDown(e, idx)}
                  className={cn(
                    'shrink-0 snap-start px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors cursor-pointer',
                    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-1',
                    active
                      ? 'bg-indigo-600 text-white shadow-sm'
                      : 'text-gray-600 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-800',
                  )}
                >
                  {p.label}
                </button>
              )
            })}
          </div>

          {/* Boton "Personalizado" + popover — FUERA del overflow para que
              el popover no sea clippeado por overflow-x (que vuelve overflow-y
              implicitamente clipped en la mayoria de browsers). */}
          <div className="relative shrink-0">
            <button
              ref={customBtnRef}
              type="button"
              role="radio"
              aria-checked={preset === 'custom'}
              aria-expanded={customOpen}
              aria-haspopup="dialog"
              tabIndex={preset === 'custom' ? 0 : -1}
              onClick={() => setCustomOpen(o => !o)}
              onKeyDown={(e) => onKeyDown(e, PRESETS.length)}
              className={cn(
                'shrink-0 ml-1 px-3 py-1.5 rounded-lg text-xs font-semibold transition-colors flex items-center gap-1.5 cursor-pointer',
                'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-1',
                preset === 'custom'
                  ? 'bg-indigo-600 text-white shadow-sm'
                  : 'text-gray-600 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-800 border border-dashed border-gray-300 dark:border-slate-700',
              )}
            >
              <Calendar size={12} />
              {preset === 'custom' ? 'Personalizado' : 'Personalizar'}
            </button>

            {customOpen && (
              <div
                ref={popoverRef}
                role="dialog"
                aria-label="Seleccionar rango personalizado"
                className="absolute z-50 mt-2 right-0 bg-white dark:bg-[#121a29] border border-gray-200 dark:border-slate-700 rounded-xl shadow-xl p-4 w-72"
              >
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-semibold text-gray-800 dark:text-slate-100">Rango personalizado</h3>
                  <button
                    onClick={() => setCustomOpen(false)}
                    className="text-gray-400 hover:text-gray-600 dark:hover:text-slate-200 p-0.5 rounded cursor-pointer"
                    aria-label="Cerrar"
                  >
                    <X size={14} />
                  </button>
                </div>
                <div className="space-y-2.5">
                  <label className="block text-xs font-medium text-gray-600 dark:text-slate-300">
                    Desde
                    <input
                      type="date"
                      value={draftStart}
                      max={draftEnd}
                      onChange={(e) => setDraftStart(e.target.value)}
                      className="mt-1 w-full px-3 py-1.5 border border-gray-200 dark:border-slate-700 dark:bg-[#0f1624] rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </label>
                  <label className="block text-xs font-medium text-gray-600 dark:text-slate-300">
                    Hasta
                    <input
                      type="date"
                      value={draftEnd}
                      min={draftStart}
                      onChange={(e) => setDraftEnd(e.target.value)}
                      className="mt-1 w-full px-3 py-1.5 border border-gray-200 dark:border-slate-700 dark:bg-[#0f1624] rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    />
                  </label>
                </div>
                <div className="flex items-center justify-end gap-2 mt-4">
                  <button
                    onClick={() => setCustomOpen(false)}
                    className="px-3 py-1.5 text-xs font-semibold text-gray-600 dark:text-slate-400 hover:bg-gray-100 dark:hover:bg-slate-800 rounded-lg cursor-pointer"
                  >
                    Cancelar
                  </button>
                  <button
                    onClick={applyCustom}
                    disabled={!draftStart || !draftEnd || draftStart > draftEnd}
                    className="px-3 py-1.5 text-xs font-semibold bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
                  >
                    Aplicar
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

        {/* Sub-label dinamico — anti "trampa de filtro" */}
        <p
          role="status"
          aria-live="polite"
          className="text-[11px] text-gray-500 dark:text-slate-400 pl-1"
        >
          Mostrando datos del <span className="font-medium text-gray-700 dark:text-slate-200">{rangeLabel}</span>
        </p>
      </div>
    </div>
  )
}
