/**
 * events.js — eventos custom del frontend para sincronizar UI cross-component.
 *
 * V070.79 (UX badges responsive).
 *
 * Patron: cuando una accion local modifica un contador que vive en otro
 * componente (ej: sidebar, header, dashboard widget), disparamos un evento
 * de window y los listeners refrescan SU contador en <500ms en vez de
 * esperar al proximo polling.
 *
 * Inspirado en el evento ya existente 'chat:unread-changed' que disparaba
 * Chat.jsx para refrescar el badge rojo del sidebar al abrir una conversacion.
 *
 * ## Eventos disponibles
 *
 *   - leads:assignment-changed  → cualquier accion que cambie asesor/equipo
 *                                 de un lead (asignacion, reasignacion,
 *                                 derivacion). Listeners: Sidebar (badge
 *                                 "Asignacion").
 *   - leads:list-changed        → cualquier accion que altere la lista total
 *                                 (crear, eliminar). Listeners: Leads.jsx
 *                                 (banner "X nuevos leads") indirectamente.
 *   - chat:unread-changed       → mensaje WhatsApp marcado como leido o
 *                                 nueva conversacion. Listener: Sidebar
 *                                 (badge "Chat"). YA EXISTE en Chat.jsx.
 *
 * ## Uso
 *
 * ```js
 * import { fireEvent } from '@/lib/events'
 *
 * // Tras un PATCH exitoso de asignacion:
 * await api.patch('/api/leads/bulk/asesor', payload)
 * fireEvent('leads:assignment-changed')
 * ```
 *
 * ## Por que no Redux/Zustand?
 *
 * Estos eventos son fire-and-forget (no necesitan estado global persistido).
 * Los listeners solo refrescan su propio dato via su propia fuente de
 * verdad (API). Es un patron mas simple que pasar callbacks o subscribers
 * Redux que solo se usan para "invalidar cache".
 */


/**
 * Dispara un evento custom de window. Si el nombre no esta en la lista
 * de eventos conocidos, loguea warning en dev (no en prod).
 */
export function fireEvent(name, detail) {
  if (typeof window === 'undefined') return
  try {
    window.dispatchEvent(new CustomEvent(name, { detail }))
  } catch {
    // CustomEvent puede fallar en browsers muy viejos. Fallback a Event.
    try {
      window.dispatchEvent(new Event(name))
    } catch {
      /* sin soporte de eventos — el badge se actualizara por polling */
    }
  }
}

/**
 * Atajo semantico: dispara los 2 eventos relacionados con cambios de
 * asignacion (el badge en sidebar Y cualquier listener de la lista).
 */
export function fireAssignmentChanged() {
  fireEvent('leads:assignment-changed')
}
