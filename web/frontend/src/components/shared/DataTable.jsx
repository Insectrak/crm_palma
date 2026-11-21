import { useEffect, useMemo, useState } from 'react'
import { ChevronLeft, ChevronRight, Table, GripVertical } from 'lucide-react'
import {
  DndContext,
  PointerSensor,
  KeyboardSensor,
  useSensor,
  useSensors,
  closestCenter,
} from '@dnd-kit/core'
import {
  SortableContext,
  horizontalListSortingStrategy,
  sortableKeyboardCoordinates,
  arrayMove,
  useSortable,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import LoadingSpinner from './LoadingSpinner'
import EmptyState from './EmptyState'

/**
 * Tabla reutilizable con estados de carga, vacío y paginación integrada.
 *
 * headers: array de { key, label, className?, tdClassName? }
 *   - Las keys `_select` y `_acciones` se tratan como "fijas":
 *     `_select` queda anclada a la izquierda, `_acciones` a la derecha
 *     (con sticky right + sombra). Solo las columnas intermedias son
 *     arrastrables.
 *
 * rows: array de objetos con los datos.
 * renderCell: función (row, key) => ReactNode.
 *
 * maxHeight (opcional): cuando viene seteado, la tabla scrollea
 *   verticalmente dentro del contenedor (en vez de hacerlo el body).
 *   Esto deja el scrollbar horizontal SIEMPRE accesible al fondo del
 *   viewport. Combina con thead sticky top-0. Patrón tablas profesionales.
 *
 * columnOrderKey (opcional): cuando viene seteado, el orden de las
 *   columnas arrastrables se persiste en localStorage[columnOrderKey].
 *   Si no viene, el orden es solo en memoria mientras dure la sesión.
 *   Patrón hojas de cálculo: cada usuario arregla la tabla a su gusto.
 */

// Keys que no se pueden reordenar — son "anclas" visuales.
const FIXED_LEFT_KEYS  = new Set(['_select'])
const FIXED_RIGHT_KEYS = new Set(['_acciones'])

function isDraggable(key) {
  return !FIXED_LEFT_KEYS.has(key) && !FIXED_RIGHT_KEYS.has(key)
}

/** Reconciliacion entre el orden persistido y el catalogo actual de
 *  columnas. Asegura: (a) solo keys que existen, (b) nuevas columnas se
 *  agregan al final, (c) el orden persistido se respeta para las que
 *  siguen existiendo. */
function reconcileOrder(persistedKeys, currentKeys) {
  if (!persistedKeys || !persistedKeys.length) return currentKeys
  const currentSet = new Set(currentKeys)
  let result = persistedKeys.filter(k => currentSet.has(k))
  const keptSet = new Set(result)
  const newOnes = currentKeys.filter(k => !keptSet.has(k))

  for (const newKey of newOnes) {
    const targetIndexInCurrent = currentKeys.indexOf(newKey)
    const nextKey = currentKeys.slice(targetIndexInCurrent + 1).find(k => result.includes(k))
    if (nextKey) {
      const idx = result.indexOf(nextKey)
      result.splice(idx, 0, newKey)
    } else {
      result.push(newKey)
    }
  }

  // Garantizar que supervisor_nombre quede a la izquierda de asesor_nombre
  const supIdx = result.findIndex(k => k === 'supervisor_nombre' || k === 'supervisor_jefe_nombre')
  const asIdx = result.indexOf('asesor_nombre')
  if (supIdx !== -1 && asIdx !== -1 && supIdx > asIdx) {
    const [supKey] = result.splice(supIdx, 1)
    const newAsIdx = result.indexOf('asesor_nombre')
    result.splice(newAsIdx, 0, supKey)
  }

  // Garantizar que origen quede a la izquierda de fuente_nombre / campana
  const origIdx = result.indexOf('origen')
  const fnIdx = result.indexOf('fuente_nombre')
  if (origIdx !== -1 && fnIdx !== -1 && origIdx > fnIdx) {
    result.splice(origIdx, 1)
    const newFnIdx = result.indexOf('fuente_nombre')
    result.splice(newFnIdx, 0, 'origen')
  }

  return result
}

export default function DataTable({
  headers,
  rows,
  renderCell,
  isLoading,
  error,
  emptyTitle = 'No hay datos',
  emptyDescription = '',
  emptyIcon = Table,
  emptyAction = null,
  pagination,
  onPageChange,
  onRowClick,
  rowClassName,
  maxHeight = null,
  columnOrderKey = null,
  // V063: orden controlado externamente (vistas guardadas). Cuando viene
  // seteado, gana sobre el persistido en localStorage. Si tambien hay
  // onColumnOrderChange, cada drag emite el nuevo orden hacia el caller
  // (que decide si guarda/marca dirty/etc).
  controlledOrder = null,
  onColumnOrderChange = null,
}) {
  const hasRows = rows && rows.length > 0
  const showSpinner = isLoading && !hasRows && !error
  const showRefreshOverlay = isLoading && hasRows

  // Separamos columnas fijas vs draggables manteniendo el orden original
  // del caller para el primer mount / cuando no hay persistencia previa.
  const fixedLeft  = useMemo(() => headers.filter(h => FIXED_LEFT_KEYS.has(h.key)),  [headers])
  const fixedRight = useMemo(() => headers.filter(h => FIXED_RIGHT_KEYS.has(h.key)), [headers])
  const draggableHeaders = useMemo(() => headers.filter(h => isDraggable(h.key)), [headers])
  const draggableKeys    = useMemo(() => draggableHeaders.map(h => h.key), [draggableHeaders])

  // Preferencia del usuario: el orden manual que arrastró. Es el ÚNICO
  // estado. El orden efectivo se deriva en cada render reconciliando
  // contra `draggableKeys` (que puede cambiar al toggle de columnas).
  // Asi evitamos el anti-patron de setState-en-useEffect.
  const [userOrder, setUserOrder] = useState(() => {
    if (!columnOrderKey) return null
    try {
      const raw = localStorage.getItem(columnOrderKey)
      if (raw) return JSON.parse(raw)
    } catch { /* ignore */ }
    return null
  })

  // Orden efectivo = controlledOrder (si viene) > preferencia local > catálogo.
  // En los tres casos se reconcilia contra el catalogo actual.
  const orderedKeys = useMemo(
    () => reconcileOrder(controlledOrder ?? userOrder, draggableKeys),
    [controlledOrder, userOrder, draggableKeys],
  )

  // Persistencia local. Si el orden viene controlado, NO lo escribimos —
  // delegamos la persistencia al caller (que probablemente lo manda al
  // backend como parte de una vista).
  useEffect(() => {
    if (!columnOrderKey || controlledOrder) return
    try {
      localStorage.setItem(columnOrderKey, JSON.stringify(orderedKeys))
    } catch { /* ignore quota errors */ }
  }, [columnOrderKey, controlledOrder, orderedKeys])

  // Orden final que se renderiza
  const orderedDraggable = useMemo(
    () => orderedKeys.map(k => draggableHeaders.find(h => h.key === k)).filter(Boolean),
    [orderedKeys, draggableHeaders],
  )
  const finalHeaders = useMemo(
    () => [...fixedLeft, ...orderedDraggable, ...fixedRight],
    [fixedLeft, orderedDraggable, fixedRight],
  )

  // Sensores dnd-kit. Distance 6 evita que un click normal en el header
  // (orden, abrir menu) dispare un drag accidental.
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 6 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  )

  const handleDragEnd = (event) => {
    const { active, over } = event
    if (!over || active.id === over.id) return
    const oldIdx = orderedKeys.indexOf(active.id)
    const newIdx = orderedKeys.indexOf(over.id)
    if (oldIdx === -1 || newIdx === -1) return
    const next = arrayMove(orderedKeys, oldIdx, newIdx)
    setUserOrder(next)
    // V063: notificar al caller — el padre puede marcar la vista activa
    // como modificada y ofrecer "Guardar cambios".
    if (onColumnOrderChange) onColumnOrderChange(next)
  }

  return (
    <div className="relative">
      {showSpinner && <LoadingSpinner />}

      {!isLoading && error && (
        <div className="p-6">
          <div className="bg-red-50 border border-red-200 text-red-700 rounded-md p-4 text-sm">
            <strong>Error:</strong> {error}
          </div>
        </div>
      )}

      {showRefreshOverlay && (
        <div className="absolute top-0 left-0 right-0 h-0.5 overflow-hidden z-10">
          <div className="h-full bg-indigo-500" style={{
            width: '40%',
            animation: 'refreshSlide 1.2s ease-in-out infinite',
          }} />
          <style>{`
            @keyframes refreshSlide {
              0%   { transform: translateX(-100%); }
              100% { transform: translateX(350%); }
            }
          `}</style>
        </div>
      )}

      {!error && hasRows && (
        <div
          className={`${maxHeight ? 'overflow-auto wa-scrollbar' : 'overflow-x-auto'} transition-opacity ${showRefreshOverlay ? 'opacity-70 pointer-events-none' : ''}`}
          style={maxHeight ? { maxHeight } : undefined}
        >
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
            <table className="w-full min-w-[900px] text-sm">
              <thead>
                <tr className="border-b border-gray-100 dark:border-slate-800">
                  <SortableContext items={orderedKeys} strategy={horizontalListSortingStrategy}>
                    {finalHeaders.map((h) => {
                      const isLast = FIXED_RIGHT_KEYS.has(h.key)
                      const cornerSticky = isLast && maxHeight
                      const stickyParts = []
                      if (maxHeight) stickyParts.push('sticky top-0')
                      if (isLast)    stickyParts.push('sticky right-0 border-l border-gray-200 dark:border-slate-800 shadow-[-6px_0_10px_-4px_rgba(0,0,0,0.08)]')
                      const zCls = cornerSticky ? 'z-30' : (isLast || maxHeight ? 'z-20' : '')
                      const stickyCls = `${stickyParts.join(' ')} ${zCls}`

                      if (isDraggable(h.key)) {
                        return (
                          <SortableHeaderCell
                            key={h.key}
                            header={h}
                            stickyCls={stickyCls}
                          />
                        )
                      }
                      return (
                        <th
                          key={h.key}
                          className={`text-left px-2 py-2.5 font-semibold text-gray-600 dark:text-slate-300 whitespace-nowrap bg-gray-50 dark:bg-[#121927] ${stickyCls} ${h.className || ''}`}
                        >
                          {h.label}
                        </th>
                      )
                    })}
                  </SortableContext>
                </tr>
              </thead>
              <tbody>
                {rows.map((row, index) => {
                  const isOdd = index % 2 !== 0
                  const rowBg = isOdd ? 'bg-gray-50/50 dark:bg-[#131b2c]' : 'bg-white dark:bg-[#0c121e]'
                  const stickyBg = isOdd ? 'bg-[#f7f7f8] dark:bg-[#131b2c]' : 'bg-white dark:bg-[#0c121e]'
                  return (
                    <tr
                      key={row.id || index}
                      onClick={() => onRowClick && onRowClick(row)}
                      className={`group border-b border-gray-50 dark:border-slate-800/60 transition-colors
                        ${onRowClick ? 'cursor-pointer hover:bg-indigo-50/60 dark:hover:bg-slate-800/80' : 'hover:bg-gray-50 dark:hover:bg-slate-800/50'}
                        ${rowBg}
                        ${rowClassName ? rowClassName(row) : ''}`}
                    >
                      {finalHeaders.map((h) => {
                        const isLast = FIXED_RIGHT_KEYS.has(h.key)
                        const stickyCls = isLast
                          ? `sticky right-0 z-10 ${stickyBg} group-hover:bg-indigo-50 dark:group-hover:bg-slate-800 border-l border-gray-200 dark:border-slate-800 shadow-[-6px_0_10px_-4px_rgba(0,0,0,0.08)]`
                          : ''
                        return (
                          <td key={h.key} className={`px-2 py-2.5 ${stickyCls} ${h.tdClassName || ''}`}>
                            {renderCell ? renderCell(row, h.key) : (row[h.key] ?? '—')}
                          </td>
                        )
                      })}
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </DndContext>
        </div>
      )}

      {!isLoading && !error && !hasRows && (
        <EmptyState
          icon={emptyIcon}
          title={emptyTitle}
          description={emptyDescription}
        >
          {emptyAction}
        </EmptyState>
      )}

      {/* V067: paginacion estilo correo profesional SIEMPRE visible cuando hay rows.
          Flechas se deshabilitan via has_prev/has_next del backend. */}
      {!error && hasRows && pagination && pagination.total > 0 && (
        <div className="inline-flex items-center justify-end gap-3 px-4 py-2.5 border-t border-gray-100 dark:border-slate-800 w-full whitespace-nowrap">
          <span className="text-sm text-gray-500 dark:text-slate-400 select-none leading-none">
            {((pagination.page - 1) * pagination.page_size + 1).toLocaleString()}–{Math.min(pagination.page * pagination.page_size, pagination.total).toLocaleString()} de {pagination.total.toLocaleString()}
          </span>
          <div className="inline-flex items-center gap-1 shrink-0">
            <button
              onClick={() => onPageChange(pagination.page - 1)}
              disabled={!pagination.has_prev}
              className="w-8 h-8 inline-flex items-center justify-center rounded-full border border-gray-200 dark:border-slate-700 text-gray-500 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors cursor-pointer"
            >
              <ChevronLeft size={16} />
            </button>
            <button
              onClick={() => onPageChange(pagination.page + 1)}
              disabled={!pagination.has_next}
              className="w-8 h-8 inline-flex items-center justify-center rounded-full border border-gray-200 dark:border-slate-700 text-gray-500 dark:text-slate-300 hover:bg-gray-100 dark:hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors cursor-pointer"
            >
              <ChevronRight size={16} />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}


/** Header arrastrable. dnd-kit aplica transform al estilo durante el
 *  drag para producir el efecto hojas de cálculo: el header "se levanta" y
 *  los demás headers se desplazan para hacerle espacio. Las celdas
 *  debajo no se animan (solo se reordenan al hacer drop).
 *
 *  El handle de drag es un icono pequeño que aparece en hover — no
 *  todo el <th> es draggable porque eso choca con los selects/menus
 *  que algunas columnas tienen como contenido del label. */
function SortableHeaderCell({ header, stickyCls }) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: header.key })

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.4 : 1,
    cursor: isDragging ? 'grabbing' : 'default',
  }

  return (
    <th
      ref={setNodeRef}
      style={style}
      className={`group/th relative text-left px-2 py-2.5 font-semibold text-gray-600 dark:text-slate-300 whitespace-nowrap bg-gray-50 dark:bg-[#121927] ${stickyCls} ${header.className || ''}`}
    >
      <div className="flex items-center gap-1">
        {/* Handle: solo visible al hover de la celda. Cursor grab.
            Patron patrón premium: el handle es discreto pero presente. */}
        <button
          type="button"
          {...attributes}
          {...listeners}
          aria-label={`Reordenar columna ${typeof header.label === 'string' ? header.label : header.key}`}
          className="opacity-0 group-hover/th:opacity-100 text-gray-300 hover:text-gray-600 dark:text-slate-600 dark:hover:text-slate-300 cursor-grab active:cursor-grabbing -ml-1 transition-opacity"
        >
          <GripVertical size={12} />
        </button>
        <span className="select-none">{header.label}</span>
      </div>
    </th>
  )
}
