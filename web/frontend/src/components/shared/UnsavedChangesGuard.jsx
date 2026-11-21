import { useEffect } from 'react'

/**
 * UnsavedChangesGuard — Avisa cuando el usuario intenta cerrar la pestaña,
 * recargar (F5), navegar atrás del browser o salir del sitio mientras hay
 * cambios sin guardar.
 *
 * Cubre los vectores donde se pierde trabajo SIN posibilidad de recuperarlo:
 *   - Cerrar pestaña / ventana
 *   - F5 / Ctrl+R
 *   - Back del browser
 *   - Pegar otra URL en la barra de direcciones
 *
 * Mecanismo: `beforeunload`. El browser muestra su propio prompt nativo
 * ("¿Salir del sitio?"). El string custom ya no se muestra en navegadores
 * modernos (decisión de seguridad), pero el prompt sí aparece y es suficiente.
 *
 * **NO cubre** navegación interna SPA (click en el sidebar mientras hay
 * cambios sin guardar). Esto requeriría `useBlocker` de react-router 7, que a
 * su vez exige migrar de `<BrowserRouter>` a `createBrowserRouter`+`<RouterProvider>`.
 * Esa migración es grande y se deja como follow-up — el riesgo de los
 * 4 vectores de arriba ya cubiertos es mayor que el de la navegación interna
 * (que tiene siempre vuelta atrás vía back del browser).
 *
 * Uso:
 *   <UnsavedChangesGuard isDirty={hasUnsavedChanges} />
 *
 * El componente NO bloquea el botón "Guardar" — solo navegación FUERA del sitio.
 * Es responsabilidad del caller resetear `isDirty=false` tras un save OK.
 *
 * El prop `message` está aceptado por compat con callers que ya lo pasaban,
 * pero los browsers modernos lo ignoran (sólo muestran su mensaje genérico).
 */
// eslint-disable-next-line no-unused-vars
export default function UnsavedChangesGuard({ isDirty, message }) {
  useEffect(() => {
    if (!isDirty) return
    const onBeforeUnload = (e) => {
      e.preventDefault()
      e.returnValue = ''
      return ''
    }
    window.addEventListener('beforeunload', onBeforeUnload)
    return () => window.removeEventListener('beforeunload', onBeforeUnload)
  }, [isDirty])

  return null
}
