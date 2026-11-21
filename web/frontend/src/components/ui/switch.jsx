/**
 * Switch / Toggle reusable estilo SaaS pro (patrón premium / patrón estándar / patrón premium).
 *
 * Características:
 * - Track con padding interno (knob no toca los bordes).
 * - Knob con sombra elevada para que destaque sobre cualquier color.
 * - Color de marca dinámico cuando ON.
 * - Estado disabled con opacidad reducida.
 * - Focus ring accesible (keyboard navigation).
 * - Transición suave del knob (cubic-bezier).
 *
 * Uso:
 *   <Switch
 *     checked={value}
 *     onChange={() => setValue(v => !v)}
 *     disabled={saving}
 *     ariaLabel="Asesor puede editar contactos"
 *   />
 */
export default function Switch({
  checked = false,
  onChange,
  disabled = false,
  ariaLabel,
  size = 'md',
}) {
  // Tamaños: track y knob proporcionales.
  // Padding interno = (trackHeight - knobSize) / 2 para centrar verticalmente.
  const dims = {
    sm: { track: 'w-9 h-5',  knob: 'w-3.5 h-3.5', offX: 'translate-x-0.5', onX: 'translate-x-4'  },
    md: { track: 'w-11 h-6', knob: 'w-5 h-5',     offX: 'translate-x-0.5', onX: 'translate-x-5'  },
    lg: { track: 'w-14 h-7', knob: 'w-6 h-6',     offX: 'translate-x-0.5', onX: 'translate-x-7'  },
  }[size] || { track: 'w-11 h-6', knob: 'w-5 h-5', offX: 'translate-x-0.5', onX: 'translate-x-5' }

  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={ariaLabel}
      onClick={onChange}
      disabled={disabled}
      className={[
        'relative inline-flex items-center shrink-0 rounded-full',
        'transition-colors duration-200 ease-out',
        'focus:outline-none focus-visible:ring-2 focus-visible:ring-offset-2',
        'focus-visible:ring-[var(--brand-primary,#4F46E5)]',
        disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer',
        dims.track,
        checked
          ? 'bg-[var(--brand-primary,#4F46E5)] hover:bg-[var(--brand-primary-hover,#4338CA)]'
          : 'bg-gray-200 hover:bg-gray-300',
      ].join(' ')}
    >
      <span
        aria-hidden="true"
        className={[
          'pointer-events-none inline-block rounded-full bg-white',
          'shadow-[0_1px_3px_rgba(0,0,0,0.15),0_1px_2px_rgba(0,0,0,0.10)]',
          'ring-0 transition-transform duration-200 ease-out',
          dims.knob,
          checked ? dims.onX : dims.offX,
        ].join(' ')}
      />
    </button>
  )
}
