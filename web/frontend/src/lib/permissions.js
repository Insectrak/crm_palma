/**
 * Catálogo de permisos del CRM (ADR-0011).
 *
 * Inspirado en el patrón del producto hermano DoctorMuelita:
 * permission keys flat con formato `resource.action`. El catálogo vive
 * en frontend porque cada permiso va atado a código (un permiso sin
 * endpoint que lo chequee es inútil).
 *
 * Para agregar un permiso nuevo:
 *   1. Agregar la key aquí + label legible.
 *   2. Usar `check_permission("key")` en el endpoint backend que lo necesita.
 *   3. Actualizar el seed de roles built-in en la migración SQL si aplica.
 *
 * No hardcodear estas keys en otros componentes — importar siempre desde
 * este archivo.
 */

export const PERMISSION_GROUPS = [
  {
    group: 'Leads',
    perms: [
      { key: 'leads.view',      label: 'Ver leads' },
      { key: 'leads.create',    label: 'Crear leads' },
      { key: 'leads.edit',      label: 'Editar leads' },
      { key: 'leads.delete',    label: 'Eliminar leads' },
      // V094 — el boton Excel vive en la pantalla de Leads (no en Reportes).
      // La key historica es `reportes.export` por compatibilidad con la
      // migracion V078 y el seed V079; el label y la ubicacion en la UI
      // reflejan donde el admin realmente VE el efecto.
      { key: 'reportes.export', label: 'Exportar leads (Excel)' },
    ],
  },
  {
    group: 'Agenda y contactos',
    perms: [
      { key: 'agenda.view',    label: 'Ver agenda' },
      { key: 'agenda.edit',    label: 'Crear/editar citas' },
      { key: 'chat.view',      label: 'Ver chat' },
      { key: 'llamadas.view',  label: 'Ver llamadas' },
    ],
  },
  {
    group: 'Reportes y análisis',
    perms: [
      { key: 'reportes.view',   label: 'Ver reportes' },
      { key: 'dashboards.view', label: 'Ver dashboards' },
      { key: 'metas.view',      label: 'Ver metas' },
      { key: 'historicos.view', label: 'Ver históricos' },
    ],
  },
  {
    group: 'Gestión',
    perms: [
      { key: 'asignacion.manage',   label: 'Asignar leads' },
      { key: 'formularios.manage',  label: 'Gestionar formularios públicos' },
      { key: 'rotacion.manage',     label: 'Configurar reparto de leads' },
      { key: 'carga_masiva.use',    label: 'Carga masiva de leads' },
    ],
  },
  {
    group: 'Visibilidad y alcance de datos',
    perms: [
      { key: 'data.view_all',       label: 'Ver todos los datos globales (Maestro: Leads, Dashboard, Reportes, Agenda, Chat)' },
      { key: 'leads.view_all',      label: 'Ver todos los leads (global / todos los asesores)' },
      { key: 'dashboards.view_all', label: 'Ver métricas globales de toda la empresa en Dashboard' },
      { key: 'reportes.view_all',   label: 'Ver datos y métricas globales en Reportes' },
      { key: 'agenda.view_all',     label: 'Ver todas las citas y llamadas en Agenda' },
      { key: 'chat.view_all',       label: 'Ver todas las conversaciones de WhatsApp' },
    ],
  },
  {
    group: 'Configuración',
    perms: [
      { key: 'integraciones.manage', label: 'Gestionar integraciones' },
      { key: 'usuarios.manage',      label: 'Gestionar usuarios' },
      { key: 'roles.manage',         label: 'Gestionar roles' },
      { key: 'config.manage',        label: 'Configuración general' },
      // V089 — controla acceso a "Mi cuenta → Mis notificaciones".
      // Si OFF: el usuario no puede apagar su kill switch ni cambiar el
      // horario silencioso. Útil para asegurar que los asesores siempre
      // reciban push de leads.
      { key: 'notificaciones.manage_own', label: 'Gestionar mis notificaciones' },
    ],
  },
]

/** Helper para chequeos inline en componentes React.
 *
 * Misma lógica que `has_permission` del backend:
 *   admin legacy → siempre permite
 *   _all flag    → siempre permite
 *   key match    → permite si TRUE
 */
export function hasPermission(user, permissionKey) {
  if (!user) return false
  if (user.role === 'admin') return true
  const perms = user.permissions || {}
  if (perms._all === true) return true
  return perms[permissionKey] === true
}

/**
 * Helper para obtener el alcance de asignación de leads de un usuario.
 * Retorna: { canAssign: boolean, scope: 'global' | 'equipo' | 'personalizado' | 'none', allowedUsers: string[] }
 */
export function getAssignmentConfig(user) {
  if (!user) return { canAssign: false, scope: 'none', allowedUsers: [] }
  if (user.role === 'admin' || user.permissions?._all === true) {
    return { canAssign: true, scope: 'global', allowedUsers: [] }
  }
  const hasManage = hasPermission(user, 'asignacion.manage')
  const isSupervisor = user.role === 'supervisor'
  if (!hasManage && !isSupervisor) {
    return { canAssign: false, scope: 'none', allowedUsers: [] }
  }
  const scope = user.permissions?.['asignacion.scope'] || 'equipo'
  const allowedUsers = Array.isArray(user.permissions?.['asignacion.allowed_users'])
    ? user.permissions['asignacion.allowed_users']
    : []
  return { canAssign: true, scope, allowedUsers }
}

/**
 * Helper para verificar si un usuario tiene visibilidad de datos global (todos los registros)
 * o si solo debe ver sus registros propios.
 */
export function canViewAllData(user, scope = 'leads') {
  if (!user) return false
  if (user.role === 'admin') return true
  const perms = user.permissions || {}
  if (perms._all === true) return true
  if (perms['data.view_all'] === true) return true
  if (perms[`${scope}.view_all`] === true) return true
  return false
}

/** Field-Level Security (ADR-0011 Sprint 5).
 *
 * Devuelve true si el usuario puede LEER el field del objeto.
 * Default true: si la key no está en permissions, se asume acceso libre
 * (backward compat — roles existentes no se rompen).
 *
 * Admin legacy y _all bypasean siempre.
 */
export function canReadField(user, obj, field) {
  if (!user) return false
  if (user.role === 'admin') return true
  const perms = user.permissions || {}
  if (perms._all === true) return true
  return perms[`field.${obj}.${field}.read`] !== false
}

/** Field-Level Security: devuelve true si el usuario puede EDITAR el field.
 * Implica canReadField — si no podés leer, no podés editar.
 */
export function canEditField(user, obj, field) {
  if (!user) return false
  if (user.role === 'admin') return true
  const perms = user.permissions || {}
  if (perms._all === true) return true
  if (!canReadField(user, obj, field)) return false
  return perms[`field.${obj}.${field}.edit`] !== false
}
