/**
 * ViewsBar — tab bar de vistas guardadas patrón premium/patrón premium.
 *
 * El usuario ve sus vistas como pestañas horizontales arriba de la
 * tabla y cambia entre ellas con un click. Cada vista guarda una
 * combinación de filtros + sort + columnas visibles + orden.
 *
 * Tres niveles de visibilidad:
 *   - 👤 personal: solo el owner ve la vista
 *   - 👥 team:     supervisor + sus asesores
 *   - 🌐 public:   todos (solo admin crea)
 *
 * Save manual: cuando hay cambios respecto a la vista guardada, aparece
 * un indicador ámbar "● modificada" + botones [Guardar] [Descartar].
 * Patrón patrón estándar/patrón premium, no auto-save (patrón premium) — evita sobreescribir
 * vistas guardadas sin querer.
 */
import { useState, useRef, useEffect } from 'react'
import {
  Plus, Check, RotateCcw, MoreVertical, Pencil, Star, Trash2,
  Bookmark,
} from 'lucide-react'
import { viewColorHex } from '@/lib/viewColors'

export default function ViewsBar({
  views = [],
  activeViewId = null,
  isDirty = false,
  isMutating = false,
  onSelect,
  onCreate,
  onSaveChanges,
  onDiscardChanges,
  onRename,
  onDuplicate,
  onSetDefault,
  onDelete,
}) {
  return (
    <div className="flex items-center gap-1.5 flex-wrap min-h-[34px]">
      {/* Pseudo-vista "Todos" — sin filtros aplicados. No editable, siempre
          al inicio. Cuando ninguna vista guardada está activa, esta queda
          seleccionada visualmente. */}
      <ViewTab
        label="Todos"
        icon={<Bookmark size={11} />}
        active={!activeViewId}
        onClick={() => onSelect && onSelect(null)}
      />

      {views.map(v => (
        <ViewTab
          key={v.id}
          label={v.name}
          // V063: el color elegido al guardar la vista colorea el icono
          // SIEMPRE (activa o inactiva) — asi cada vista tiene identidad
          // visual y se distinguen de un golpe de vista.
          icon={<Bookmark size={11} fill="currentColor" />}
          color={v.color}
          isDefault={v.is_default}
          active={v.id === activeViewId}
          isDirty={v.id === activeViewId && isDirty}
          onClick={() => onSelect && onSelect(v.id)}
          menu={
            <ViewMenu
              view={v}
              onRename={() => onRename && onRename(v)}
              onDuplicate={() => onDuplicate && onDuplicate(v)}
              onSetDefault={() => onSetDefault && onSetDefault(v)}
              onDelete={() => onDelete && onDelete(v)}
            />
          }
        />
      ))}

      {/* Botón crear nueva vista — siempre disponible para cualquier rol */}
      <button
        onClick={onCreate}
        title="Guardar la configuración actual como una vista nueva"
        className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium text-gray-500 hover:text-indigo-600 hover:bg-indigo-50 transition-colors"
        type="button"
      >
        <Plus size={13} /> Vista
      </button>

      {/* Indicador "modificada" + acciones cuando hay diff con la vista
          guardada. Solo aparece cuando hay una vista activa Y el estado
          actual difiere de ella. */}
      {activeViewId && isDirty && (
        <div className="ml-auto flex items-center gap-1.5 pl-3 border-l border-gray-200">
          <span className="text-[11px] text-amber-700 flex items-center gap-1">
            <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
            modificada
          </span>
          <button
            onClick={onSaveChanges}
            disabled={isMutating}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors"
            type="button"
          >
            <Check size={12} /> Guardar
          </button>
          <button
            onClick={onDiscardChanges}
            disabled={isMutating}
            className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs font-medium text-gray-500 hover:text-gray-700 hover:bg-gray-100 disabled:opacity-50 transition-colors"
            type="button"
            title="Descartar cambios y volver a la vista guardada"
          >
            <RotateCcw size={12} /> Descartar
          </button>
        </div>
      )}
    </div>
  )
}


function ViewTab({ label, icon, color, active, isDefault, isDirty, onClick, menu }) {
  // El icono SIEMPRE muestra el color elegido (con leve transparencia
  // cuando la tab no esta activa para no competir con la tab activa).
  // Cuando active, el tab tiene un tinte del color de la vista.
  const hex = color ? viewColorHex(color) : null

  const activeStyle = hex
    ? {
        backgroundColor: `${hex}1f`,   // ~12% alpha → tinte sutil
        color:           hex,
        boxShadow:       `inset 0 0 0 1px ${hex}55`,  // ring del mismo color
      }
    : undefined

  const iconStyle = hex
    ? { color: hex, opacity: active ? 1 : 0.8 }
    : undefined

  return (
    <div className="relative inline-flex items-center group">
      <button
        onClick={onClick}
        style={active ? activeStyle : undefined}
        className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs font-medium transition-colors max-w-[200px] ${
          active
            ? (hex ? '' : 'bg-indigo-100 text-indigo-700 ring-1 ring-indigo-200')
            : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
        }`}
        type="button"
      >
        {isDefault && <Star size={10} className="text-amber-500 fill-amber-400 shrink-0" />}
        <span
          style={iconStyle}
          className={hex ? '' : (active ? 'text-indigo-600' : 'text-gray-400')}
        >
          {icon}
        </span>
        <span className="truncate">{label}</span>
        {isDirty && <span className="w-1.5 h-1.5 rounded-full bg-amber-500 shrink-0" />}
      </button>
      {menu && active && (
        <span className="ml-0.5">{menu}</span>
      )}
    </div>
  )
}


function ViewMenu({ view, onRename, onDuplicate, onSetDefault, onDelete }) {
  const [open, setOpen] = useState(false)
  const ref = useRef(null)

  useEffect(() => {
    if (!open) return
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false) }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(v => !v)}
        className="p-1 rounded text-gray-400 hover:text-gray-700 hover:bg-gray-100"
        type="button"
        title="Acciones de la vista"
      >
        <MoreVertical size={12} />
      </button>
      {open && (
        <div className="absolute right-0 top-full mt-1 z-50 bg-white border border-gray-200 rounded-lg shadow-lg py-1 w-44">
          <MenuItem icon={<Pencil size={12} />} onClick={() => { setOpen(false); onRename() }}>
            Renombrar
          </MenuItem>
          <MenuItem icon={<Plus size={12} />} onClick={() => { setOpen(false); onDuplicate() }}>
            Duplicar
          </MenuItem>
          <MenuItem
            icon={<Star size={12} className={view.is_default ? 'text-amber-500 fill-amber-400' : ''} />}
            onClick={() => { setOpen(false); onSetDefault() }}
          >
            {view.is_default ? 'Quitar default' : 'Marcar como default'}
          </MenuItem>
          <div className="my-1 border-t border-gray-100" />
          <MenuItem icon={<Trash2 size={12} />} onClick={() => { setOpen(false); onDelete() }} danger>
            Eliminar
          </MenuItem>
        </div>
      )}
    </div>
  )
}


function MenuItem({ icon, children, onClick, danger }) {
  return (
    <button
      onClick={onClick}
      className={`w-full text-left px-3 py-1.5 text-xs flex items-center gap-2 transition-colors ${
        danger ? 'text-red-600 hover:bg-red-50' : 'text-gray-700 hover:bg-gray-50'
      }`}
      type="button"
    >
      {icon}
      <span>{children}</span>
    </button>
  )
}
