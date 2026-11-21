/**
 * PortalSelect — dropdown custom estilo patrón premium / patrón premium.
 *
 *  - Boton con label actual + chevron
 *  - Popup portalizado a document.body con position:fixed (escapa
 *    cualquier overflow:auto / transform de un ancestor)
 *  - Scrollbar fino (clase wa-scrollbar)
 *  - Busqueda opcional para listas largas (campanas, asesores, etc)
 *  - Soporta lista plana (options) o agrupada (groups)
 *
 * Reemplazo del <select> nativo para evitar la scrollbar del SO/browser
 * (gruesa, no estilizable) y para permitir filtrado dentro del dropdown.
 *
 * Props:
 *   value         — valor actualmente seleccionado (string)
 *   onChange      — callback (nuevoValor)
 *   options       — [{ value, label }]  (lista plana)
 *   groups        — [{ label, options: [{value, label}] }]  (alternativa)
 *   placeholder   — texto para opcion vacia (default: '— Seleccionar —')
 *   searchable    — boolean: muestra input de busqueda al tope
 *   className     — clases extra para el boton (anchura, etc)
 */
import { useState, useRef, useEffect, useLayoutEffect, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { ChevronDown } from 'lucide-react'

export default function PortalSelect({
  value,
  onChange,
  options,
  groups,
  placeholder = '— Seleccionar —',
  searchable = false,
  className = '',
}) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  // V067.7 — null inicial + guard en el render para evitar flash en (0,0)
  // que aparecia como popup translucido en la esquina superior izquierda.
  const [coords, setCoords] = useState(null)
  const btnRef = useRef(null)
  const popRef = useRef(null)

  const flat = useMemo(() => {
    if (groups) return groups.flatMap(g => g.options)
    return options || []
  }, [groups, options])

  const currentLabel = useMemo(() => {
    const found = flat.find(o => String(o.value) === String(value))
    return found ? found.label : placeholder
  }, [flat, value, placeholder])

  useEffect(() => {
    if (!open) return
    const handler = (e) => {
      if (btnRef.current?.contains(e.target)) return
      if (popRef.current?.contains(e.target)) return
      setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  // V067.7 — useLayoutEffect: corre sincronicamente antes del paint, asi
  // las coords reales estan disponibles para el primer render del popup.
  useLayoutEffect(() => {
    if (!open || !btnRef.current) return
    const updatePos = () => {
      const r = btnRef.current.getBoundingClientRect()
      setCoords({ top: r.bottom + 4, left: r.left, width: r.width })
    }
    updatePos()
    window.addEventListener('scroll', updatePos, true)
    window.addEventListener('resize', updatePos)
    return () => {
      window.removeEventListener('scroll', updatePos, true)
      window.removeEventListener('resize', updatePos)
    }
  }, [open])

  // Reset busqueda + coords al cerrar (coords stale si el boton se mueve).
  useEffect(() => {
    if (!open) { setQuery(''); setCoords(null) }
  }, [open])

  const filterOpts = (opts) => {
    if (!searchable || !query.trim()) return opts
    const q = query.toLowerCase()
    return opts.filter(o => String(o.label).toLowerCase().includes(q))
  }

  // V069.2 — onMouseDown en vez de onClick para evitar event leakage al
  // unmount del portal. Mismo bug del FieldPicker: si la fila debajo del
  // popup tiene un onClick (ej. navegar al detalle del lead), al cerrarse
  // el portal sincronicamente, el browser re-targetea el click event a
  // la fila. Usar mousedown ejecuta la seleccion ANTES de que el target
  // pueda cambiar.
  const renderOption = (o) => (
    <button
      key={o.value}
      type="button"
      onMouseDown={(e) => {
        e.preventDefault()
        e.stopPropagation()
        onChange(o.value)
        setOpen(false)
      }}
      onClick={(e) => e.stopPropagation()}
      className={`w-full text-left px-3 py-1.5 text-xs transition-colors ${
        String(o.value) === String(value)
          ? 'bg-indigo-50 text-indigo-700 font-semibold'
          : 'text-gray-700 hover:bg-gray-50'
      }`}
    >
      {o.label}
    </button>
  )

  return (
    <>
      <button
        ref={btnRef}
        type="button"
        onClick={() => setOpen(!open)}
        className={`w-full inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs border rounded-md transition-colors ${
          open
            ? 'border-indigo-400 bg-indigo-50'
            : 'border-gray-200 bg-white hover:border-gray-300'
        } ${className}`}
      >
        <span className={`truncate flex-1 text-left ${value ? 'text-gray-700' : 'text-gray-400'}`}>
          {currentLabel}
        </span>
        <ChevronDown size={11} className={`shrink-0 transition-transform ${open ? 'rotate-180 text-indigo-500' : 'text-gray-400'}`} />
      </button>
      {/* V067.7 — guard `coords` no nulo evita el flash en (0,0).
          V069.2 — stopPropagation contenedor: consume cualquier click/mousedown
          dentro del portal para evitar event leakage a la fila debajo. */}
      {open && coords && createPortal(
        <div
          ref={popRef}
          data-filter-popup
          onClick={(e) => e.stopPropagation()}
          onMouseDown={(e) => e.stopPropagation()}
          style={{ position: 'fixed', top: coords.top, left: coords.left, width: Math.max(coords.width, 220) }}
          className="bg-white border border-gray-200 rounded-lg shadow-[0_8px_24px_rgba(0,0,0,0.16)] z-[9999] flex flex-col overflow-hidden"
        >
          {searchable && (
            <div className="p-1.5 border-b border-gray-100 sticky top-0 bg-white">
              <input
                type="text"
                autoFocus
                value={query}
                onChange={e => setQuery(e.target.value)}
                placeholder="Buscar…"
                className="w-full text-xs px-2 py-1.5 border border-gray-200 rounded focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
          )}
          <div className="wa-scrollbar overflow-y-auto py-1 max-h-[260px]">
            {/* Opcion vacia (placeholder) */}
            <button
              type="button"
              onClick={() => { onChange(''); setOpen(false) }}
              className={`w-full text-left px-3 py-1.5 text-xs italic transition-colors ${
                !value ? 'bg-indigo-50 text-indigo-700' : 'text-gray-400 hover:bg-gray-50'
              }`}
            >
              {placeholder}
            </button>
            {groups ? (
              groups.map(g => {
                const filtered = filterOpts(g.options)
                if (filtered.length === 0) return null
                return (
                  <div key={g.label}>
                    <div className="px-3 pt-1.5 pb-0.5 text-[10px] uppercase tracking-wide text-gray-400 font-semibold">
                      {g.label}
                    </div>
                    {filtered.map(renderOption)}
                  </div>
                )
              })
            ) : (
              filterOpts(options || []).map(renderOption)
            )}
            {searchable && filterOpts(flat).length === 0 && (
              <p className="text-center text-xs text-gray-400 py-3">Sin resultados</p>
            )}
          </div>
        </div>,
        document.body
      )}
    </>
  )
}
