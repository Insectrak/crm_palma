/**
 * Paleta compartida para vistas guardadas.
 *
 * Una sola fuente de verdad para los colores que el user elige en
 * SaveViewModal y los que muestra ViewsBar en cada tab. Si la vista
 * trae un color desconocido (legado o roto), cae al neutro `slate`.
 */
export const VIEW_COLORS = [
  // Cálidos
  { value: 'red',     hex: '#ef4444', label: 'Rojo' },
  { value: 'orange',  hex: '#f97316', label: 'Naranja' },
  { value: 'amber',   hex: '#f59e0b', label: 'Ámbar' },
  { value: 'yellow',  hex: '#eab308', label: 'Amarillo' },
  { value: 'lime',    hex: '#84cc16', label: 'Lima' },
  { value: 'emerald', hex: '#10b981', label: 'Esmeralda' },
  { value: 'teal',    hex: '#14b8a6', label: 'Turquesa' },
  // Fríos + violetas
  { value: 'cyan',    hex: '#06b6d4', label: 'Cian' },
  { value: 'sky',     hex: '#0ea5e9', label: 'Cielo' },
  { value: 'blue',    hex: '#3b82f6', label: 'Azul' },
  { value: 'indigo',  hex: '#6366f1', label: 'Índigo' },
  { value: 'violet',  hex: '#8b5cf6', label: 'Violeta' },
  { value: 'fuchsia', hex: '#d946ef', label: 'Fucsia' },
  { value: 'pink',    hex: '#ec4899', label: 'Rosa' },
  { value: 'rose',    hex: '#f43f5e', label: 'Coral' },
  // Neutro
  { value: 'slate',   hex: '#64748b', label: 'Gris' },
]

const COLOR_BY_NAME = Object.fromEntries(VIEW_COLORS.map(c => [c.value, c]))

/** Devuelve el hex de un color por nombre, con fallback al neutro. */
export function viewColorHex(name) {
  return (COLOR_BY_NAME[name] || COLOR_BY_NAME.slate).hex
}

/** Devuelve el color completo (hex + label) por nombre. */
export function viewColorDef(name) {
  return COLOR_BY_NAME[name] || COLOR_BY_NAME.slate
}
