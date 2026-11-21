import { useEffect, useRef } from 'react'
import { logCopyAttempt } from '@/lib/api'

/**
 * Hook de protección contra copia en páginas con información sensible (PII).
 *
 * Instala listeners a nivel `document` mientras el componente está montado:
 *   - `copy`        → bloqueado (Ctrl+C / menú derecho → Copiar)
 *   - `cut`         → bloqueado (Ctrl+X)
 *   - `contextmenu` → bloqueado (click derecho)
 *
 * Excepciones:
 *   - Se permite la acción si el target es un `<input>`, `<textarea>` o
 *     elemento `contentEditable`. De lo contrario los formularios de edición
 *     de leads (teléfono, email, observaciones) quedan inservibles.
 *
 * Feedback al usuario:
 *   - La **primera** vez en la sesión que intenta copiar, muestra un alert
 *     explicando por qué está bloqueado. Las siguientes son silenciosas
 *     (no queremos spam de alerts pero sí que el usuario sepa la razón).
 *
 * Auditoría:
 *   - Cada intento dispara `logCopyAttempt()` → POST al backend (best-effort,
 *     si falla no molesta al usuario). El backend lo guarda en
 *     `crm.audit_lead_access` con action='copy_attempt'.
 *
 * Limitaciones conocidas (la manager debe entender esto):
 *   - No bloquea screenshots del OS (PrtScn, Win+Shift+S, móviles).
 *   - No bloquea fotos de la pantalla con celular.
 *   - No bloquea DevTools → inspeccionar elemento o ver la respuesta JSON.
 *   - Un usuario técnico con el token JWT puede llamar al API con curl.
 *   El watermark + audit log son la defensa real contra esos casos.
 *
 * @param {boolean} enabled — si `false`, el hook no hace nada (útil para
 *   deshabilitar dinámicamente por rol, toggle, etc.)
 * @param {string}  page    — identificador de la página ('leads' | 'asignacion')
 *   que se envía al audit log para saber dónde se intentó copiar.
 */
export default function useCopyProtection(enabled = true, page = 'unknown') {
  // Evita spam de alerts: solo el primer intento en la sesión avisa.
  const alertShownRef = useRef(false)

  useEffect(() => {
    if (!enabled) return

    const isEditableTarget = (target) => {
      if (!target) return false
      const tag = target.tagName
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true
      if (target.isContentEditable) return true
      return false
    }

    const block = (type) => (e) => {
      if (isEditableTarget(e.target)) return
      e.preventDefault()
      e.stopPropagation()

      // Log best-effort al backend
      logCopyAttempt({ page, action: type }).catch(() => { /* silencioso */ })

      // Aviso solo la primera vez
      if (!alertShownRef.current) {
        alertShownRef.current = true
        // setTimeout para no bloquear el event handler
        setTimeout(() => {
          alert(
            'Por política de seguridad, no está permitido copiar información ' +
            'desde esta sección. La acción ha sido registrada.'
          )
        }, 0)
      }
    }

    const onCopy = block('copy')
    const onCut = block('cut')
    const onContextMenu = block('contextmenu')

    document.addEventListener('copy', onCopy, true)
    document.addEventListener('cut', onCut, true)
    document.addEventListener('contextmenu', onContextMenu, true)

    return () => {
      document.removeEventListener('copy', onCopy, true)
      document.removeEventListener('cut', onCut, true)
      document.removeEventListener('contextmenu', onContextMenu, true)
    }
  }, [enabled, page])
}
