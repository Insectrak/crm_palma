/**
 * fieldCatalog.js — fields enmascarables por Field-Level Security
 * (ADR-0011 Sprint 5).
 *
 * Sincronizado con backend (app/auth/field_catalog.py). Para agregar un
 * field nuevo: registrarlo aqui Y en el backend. Si solo se agrega en un
 * lado, el otro asume default true (acceso libre).
 *
 * Cada entrada tiene `key` (matchea la columna DB / atributo JSON) y
 * `label` (lo que muestra la UI del editor de roles).
 */

export const FIELD_CATALOG = {
  leads: [
    { key: 'telefono',              label: 'Teléfono' },
    { key: 'email',                 label: 'Email' },
    { key: 'observaciones',         label: 'Observaciones' },
    { key: 'presupuesto',           label: 'Presupuesto' },
    { key: 'tipo_cierre',           label: 'Tipo de cierre' },
    { key: 'segunda_voz',           label: 'Segunda voz' },
    { key: 'motivo_perdida',        label: 'Motivo de pérdida' },
    { key: 'motivo_perdida_otro',   label: 'Motivo de pérdida (otro)' },
    { key: 'fecha_proxima_gestion', label: 'Fecha de próxima gestión' },
  ],
  // Futuras extensiones:
  // contactos: [{ key: 'contenido', label: 'Contenido del contacto' }],
  // eventos_calendario: [{ key: 'notas', label: 'Notas de la cita' }],
}

/** Devuelve true si el field es enmascarable. False = libre acceso. */
export function isFieldInCatalog(obj, field) {
  const list = FIELD_CATALOG[obj] || []
  return list.some((f) => f.key === field)
}
