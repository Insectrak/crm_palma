/**
 * SafeTextInput — input de texto blindado contra reescritura de placeholder.
 *
 * Bug que motivó la versión actual:
 * - Usuarios reportan que en Chrome normal (con extensiones activas) los
 *   placeholders se reescriben como la string literal "null".
 *   En incógnito y otros browsers funciona OK.
 * - Causa: alguna extensión del browser está reescribiendo el atributo
 *   `placeholder` del DOM. Ningún `autoComplete=off` ni `data-*-ignore` lo
 *   detiene porque la extensión opera DIRECTO sobre el atributo placeholder.
 *
 * Solución: **no usamos el atributo `placeholder` en absoluto.**
 * En su lugar, renderizamos un <span> absoluto posicionado sobre el input
 * que se ve igual que un placeholder cuando el input está vacío.
 * - El span NO es un atributo placeholder → ninguna extensión lo toca.
 * - pointer-events: none → el click pasa al input debajo.
 * - aria-hidden + role para mantener accesibilidad correcta
 *   (aria-label en el input cubre la semántica para lectores de pantalla).
 *
 * Otras defensas mantenidas del commit anterior:
 *  - value defensivo (sanitiza string "null" → "")
 *  - onChange defensivo
 *  - onKeyDownCapture preventDefault Escape (bloquea listeners globales)
 *  - useEffect ref → si DOM value queda con "null", lo restaura
 *  - autoComplete=off + name único + data-*-ignore
 */
import { useEffect, useRef } from 'react'

export default function SafeTextInput({
  value,
  onChange,
  type = 'text',
  name,
  className,
  placeholder,
  autoFocus,
  disabled,
  // Permite cambiar el color del placeholder simulado.
  placeholderClassName = 'text-gray-400',
  // Offset del placeholder simulado (en px). Por default 12px = px-3 de Tailwind.
  // Cuando el input tiene un ícono al frente (pl-9), pasar '36px'.
  placeholderPaddingLeft = '12px',
  ...rest
}) {
  const inputRef = useRef(null)
  const safeValue = (value && value !== 'null') ? value : ''
  const showPlaceholder = !safeValue && placeholder

  useEffect(() => {
    const el = inputRef.current
    if (!el) return
    if (el.value === 'null' && safeValue === '') {
      el.value = ''
    }
  })

  return (
    <span style={{ position: 'relative', display: 'inline-block', width: '100%' }}>
      <input
        ref={inputRef}
        type={type}
        name={name}
        // NO usamos el atributo placeholder — usamos el span simulado
        // para evitar extensiones que reescriban el atributo a "null".
        value={safeValue}
        aria-label={typeof placeholder === 'string' ? placeholder : undefined}
        onChange={(e) => {
          const v = e.target.value
          const sanitized = (v == null || v === 'null') ? '' : v
          onChange(sanitized)
        }}
        onKeyDownCapture={(e) => {
          if (e.key === 'Escape') {
            e.preventDefault()
            e.stopPropagation()
            if (inputRef.current && inputRef.current.value === 'null') {
              inputRef.current.value = safeValue
            }
          }
        }}
        autoComplete="off"
        autoCorrect="off"
        autoCapitalize="off"
        spellCheck={false}
        data-1p-ignore="true"
        data-lpignore="true"
        data-bwignore="true"
        data-form-type="other"
        autoFocus={autoFocus}
        disabled={disabled}
        className={className}
        {...rest}
      />
      {showPlaceholder && (
        <span
          aria-hidden="true"
          style={{
            position: 'absolute',
            // El padding del input es px-3 py-2 (~12px x 8px). El input
            // también puede tener pl-9 cuando hay un ícono al frente. El
            // posicionamiento que usamos respeta el padding-left real del
            // input mediante un offset del span — pero como cada input
            // tiene padding distinto, dependemos del consumer.
            left: 0,
            top: 0,
            right: 0,
            bottom: 0,
            // Mismas alineaciones que un placeholder nativo en flexbox.
            display: 'flex',
            alignItems: 'center',
            // Pegado a las paddings del input — pl=12px por default, sobre
            // escribible con `placeholderPaddingLeft` prop si hace falta.
            paddingLeft: placeholderPaddingLeft,
            paddingRight: '12px',
            pointerEvents: 'none',
            // Truncar si es muy largo.
            overflow: 'hidden',
            whiteSpace: 'nowrap',
            textOverflow: 'ellipsis',
          }}
          className={`text-sm ${placeholderClassName}`}
        >
          {placeholder}
        </span>
      )}
    </span>
  )
}
