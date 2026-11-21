/**
 * FieldPicker — selector de campo con icono e indicacion de campos ya
 * usados. El dropdown usa createPortal a document.body con position:fixed
 * para escapar overflows clipping de paneles contenedores y aparecer
 * siempre por encima de cualquier UI.
 *
 * Extraido de FilterBuilder.jsx y AdvancedFilters.jsx — ambas paginas
 * tenian copias identicas (deuda tecnica). Cualquier futuro fix de UX
 * en el dropdown ahora se aplica en un solo lugar.
 *
 * Props:
 *   fields:     Array<{ v: string, label: string, icon?: Component,
 *                       group?: string, description?: string }>
 *   value:      string         — campo actualmente seleccionado
 *   onChange:   (v: string) => void
 *   usedFields: Set<string>    — campos ya en uso en otros filtros
 *                                (se renderizan con opacity-30 + "en uso")
 *
 * V086 — Patron patrón estándar de agrupacion:
 *   - Si los fields traen `group`, se renderizan con encabezado por grupo.
 *   - El orden de los grupos se preserva por su primera aparicion en
 *     `fields`. El orden interno tambien se preserva (estabilidad).
 *   - Si NO traen group, fallback al render plano clasico (backwards-compat
 *     con cualquier caller que aun no haya migrado).
 *   - `description` se muestra como tooltip al hover (HTML title attr).
 *
 * Patron de posicionamiento (clase mundial, paridad con herramientas premium):
 *   - coords inicia en null para que el portal NO renderice hasta tener
 *     las coordenadas correctas. Sin esto, el popup parpadea brevemente
 *     en (0,0) sobre el sidebar.
 *   - useLayoutEffect calcula coords sincronicamente despues de mutar
 *     el DOM pero ANTES del paint, garantizando que el primer frame del
 *     popup ya este en su posicion final.
 *   - Reset a null al cerrar — evita coords stale si el boton se movio
 *     entre apertura y cierre (sticky headers, scroll, etc).
 */
import { useState, useRef, useEffect, useLayoutEffect, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { Filter, ChevronDown } from 'lucide-react'


export default function FieldPicker({ fields, value, onChange, usedFields }) {
  const [open, setOpen] = useState(false)
  const [coords, setCoords] = useState(null)
  const btnRef = useRef(null)
  const popRef = useRef(null)

  // Click outside cierra el popup
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

  // Calculo de posicion sincronico antes del paint
  useLayoutEffect(() => {
    if (!open || !btnRef.current) return
    const updatePos = () => {
      const r = btnRef.current.getBoundingClientRect()
      setCoords({ top: r.bottom + 6, left: r.left, width: Math.max(r.width, 200) })
    }
    updatePos()
    window.addEventListener('scroll', updatePos, true)
    window.addEventListener('resize', updatePos)
    return () => {
      window.removeEventListener('scroll', updatePos, true)
      window.removeEventListener('resize', updatePos)
    }
  }, [open])

  // Reset al cerrar para no reusar coords stale
  useEffect(() => {
    if (!open) setCoords(null)
  }, [open])

  const current = fields.find(f => f.v === value) || fields[0]
  const Icon = current.icon || Filter

  // V086 — Construir lista de "items" para renderizar: cada grupo se
  // representa como un header (kind=header) seguido de sus opciones
  // (kind=option). Si NINGUN field declara `group`, todo cae al render
  // plano (sin headers) — backwards-compat.
  const items = useMemo(() => {
    const anyGrouped = fields.some(f => f.group)
    if (!anyGrouped) {
      return fields.map(f => ({ kind: 'option', field: f }))
    }
    // Preservar orden de aparicion del grupo. Mapa de group -> array de fields.
    const groupOrder = []
    const byGroup = new Map()
    for (const f of fields) {
      const g = f.group || 'Otros'
      if (!byGroup.has(g)) {
        byGroup.set(g, [])
        groupOrder.push(g)
      }
      byGroup.get(g).push(f)
    }
    const flat = []
    for (const g of groupOrder) {
      flat.push({ kind: 'header', label: g })
      for (const f of byGroup.get(g)) {
        flat.push({ kind: 'option', field: f })
      }
    }
    return flat
  }, [fields])

  return (
    <>
      <button
        ref={btnRef}
        onClick={() => setOpen(!open)}
        className={`inline-flex items-center gap-1.5 px-2.5 py-1.5 text-xs border rounded-md min-w-[148px] transition-colors ${
          open
            ? 'border-indigo-400 bg-indigo-50 text-indigo-700'
            : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50 hover:border-gray-300'
        }`}
      >
        <Icon size={13} className={`shrink-0 ${open ? 'text-indigo-600' : 'text-gray-500'}`} />
        <span className="truncate flex-1 text-left font-medium">{current.label}</span>
        <ChevronDown size={11} className={`shrink-0 transition-transform ${open ? 'rotate-180 text-indigo-500' : 'text-gray-400'}`} />
      </button>
      {/* Guard `coords` no nulo: portal solo renderiza tras calcular posicion */}
      {open && coords && createPortal(
        <div
          ref={popRef}
          data-filter-popup
          // V069.2 — Defense in depth para evitar event leakage:
          // 1) stopPropagation a nivel del contenedor: cualquier click
          //    DENTRO del popup queda consumido aca.
          // 2) onMouseDown stopPropagation: el handler de click-outside de
          //    AdvancedFilters/FilterBuilder usa mousedown — sin esto,
          //    podria cerrar el panel padre en escenarios extremos.
          onClick={(e) => e.stopPropagation()}
          onMouseDown={(e) => e.stopPropagation()}
          style={{ position: 'fixed', top: coords.top, left: coords.left, minWidth: coords.width }}
          className="wa-scrollbar bg-white border border-gray-200 rounded-lg shadow-[0_8px_24px_rgba(0,0,0,0.16)] py-1 z-[9999] max-h-[280px] overflow-y-auto"
        >
          {items.map((it, idx) => {
            // V086 — Render del header de grupo (patrón estándar).
            if (it.kind === 'header') {
              return (
                <div
                  key={`grp-${idx}`}
                  className={`px-3 pt-2.5 pb-1 text-[10px] font-semibold uppercase tracking-wider text-gray-400 select-none ${
                    idx === 0 ? '' : 'border-t border-gray-100 mt-1'
                  }`}
                >
                  {it.label}
                </div>
              )
            }
            const f = it.field
            const used = usedFields.has(f.v) && f.v !== value
            const FIcon = f.icon || Filter
            return (
              <button
                key={f.v}
                disabled={used}
                title={f.description || ''}
                // V069.2 — onMouseDown en lugar de onClick:
                // el bug reportado por el usuario era que al seleccionar
                // una opcion (ej. "Creado hasta"), el evento click "se
                // filtraba" a la fila debajo (ej. Rodolfo Ancco) y se
                // navegaba al lead. Causa raiz: cuando el portal se
                // desmonta sincrónicamente en el onClick, el browser
                // re-evalua el target del click event en el elemento de
                // abajo (la fila). patrón estándar/patrón premium evitan esto usando
                // mousedown para la seleccion (se ejecuta antes que el
                // target del click pueda cambiar).
                onMouseDown={(e) => {
                  if (used) return
                  e.preventDefault()    // evita focus shift
                  e.stopPropagation()
                  onChange(f.v)
                  setOpen(false)
                }}
                onClick={(e) => {
                  // Backup por accesibilidad (Enter/Space del teclado
                  // dispara click, no mousedown). stopPropagation defensivo.
                  e.stopPropagation()
                }}
                className={`w-full text-left px-3 py-2 text-xs flex items-start gap-2 transition-colors ${
                  f.v === value ? 'bg-indigo-50 text-indigo-700 font-semibold' :
                  used ? 'opacity-30 cursor-not-allowed' :
                  'text-gray-700 hover:bg-gray-50'
                }`}
              >
                <FIcon size={13} className="shrink-0 mt-0.5" />
                <span className="flex-1 min-w-0">
                  <span className="block truncate">{f.label}</span>
                  {f.description && (
                    <span className="block text-[10px] text-gray-400 font-normal leading-tight truncate mt-0.5">
                      {f.description}
                    </span>
                  )}
                </span>
                {used && <span className="text-[10px] text-gray-400 italic mt-0.5">en uso</span>}
              </button>
            )
          })}
        </div>,
        document.body
      )}
    </>
  )
}
