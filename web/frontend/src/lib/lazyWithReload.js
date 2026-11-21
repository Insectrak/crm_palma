import { lazy } from 'react'

/**
 * lazyWithReload — wrapper alrededor de React.lazy() que auto-recupera
 * de "Failed to fetch dynamically imported module".
 *
 * Por qué existe:
 * --------------
 * Vite hace code splitting y le pone un hash al nombre de cada chunk
 * (ej. `Agenda-Bm-zDSex.js`). Cuando hacemos un deploy nuevo, los
 * chunks viejos dejan de existir en el servidor.
 *
 * Si un usuario tiene la SPA cargada en una pestaña DESDE ANTES del
 * deploy, su index.html en memoria sigue refiriendo a los hashes
 * viejos. Cuando navega lazily a una página (ej. /agenda), el
 * import() dispara un fetch a `Agenda-Bm-zDSex.js` → 404 → React
 * crashea con "Failed to fetch dynamically imported module".
 *
 * El fix estándar (usado por patrón premium, patrón premium, servicio externo, etc.):
 * detectar este error específico y recargar la página una sola vez.
 * Tras el reload, el browser baja el index.html nuevo con los
 * hashes correctos y la navegación funciona.
 *
 * Protección contra loop:
 * -----------------------
 * Si tras el reload el error se repite (ej. server caído sirviendo
 * 404 en /assets/), NO recargamos en bucle. Marcamos en sessionStorage
 * que ya intentamos. Si vuelve a fallar → dejamos que el error suba
 * al ErrorBoundary y el usuario ve el mensaje real, con botón
 * "Recargar página" manual.
 *
 * sessionStorage (no localStorage) → la marca se borra al cerrar la
 * pestaña, así el siguiente boot empieza limpio.
 */

const RELOAD_KEY = 'crm-chunk-reload-attempted'

// Regex defensiva: matchea las variantes que escupen distintos navegadores
// y bundlers cuando un chunk no se puede cargar.
const CHUNK_ERROR_RE = /Failed to fetch dynamically imported module|Loading chunk \d+ failed|ChunkLoadError|Importing a module script failed/i

export function isChunkLoadError(err) {
  if (!err) return false
  const msg = String(err.message || err)
  if (CHUNK_ERROR_RE.test(msg)) return true
  // En Safari el error puede venir como TypeError con un message diferente.
  const name = String(err.name || '')
  if (name === 'ChunkLoadError') return true
  return false
}

/**
 * Wrappea un importer dinámico para que, ante un error de chunk, recargue
 * la página una sola vez por sesión. Si ya recargó antes y vuelve a fallar,
 * propaga el error al ErrorBoundary.
 *
 * Uso:
 *   const Agenda = lazyWithReload(() => import('@/pages/Agenda'))
 */
export function lazyWithReload(importer) {
  return lazy(() =>
    importer().catch((err) => {
      if (!isChunkLoadError(err)) throw err
      try {
        if (sessionStorage.getItem(RELOAD_KEY) === '1') {
          // Ya intentamos recargar y sigue fallando → mostramos el error.
          throw err
        }
        sessionStorage.setItem(RELOAD_KEY, '1')
        // Forzamos un reload sin caché para que el browser baje el index.html
        // nuevo con los hashes correctos.
        window.location.reload()
        // Devolvemos una promesa pendiente para que React no intente render
        // mientras se está recargando.
        return new Promise(() => {})
      } catch {
        throw err
      }
    }),
  )
}
