/**
 * Tests de canReadField / canEditField (Field-Level Security frontend).
 *
 * Cubre el mismo comportamiento que el backend (field_security_service.py)
 * para que UI y servidor compartan logica:
 * - admin bypassa
 * - _all flag bypassa
 * - default true cuando la key no esta en perms
 * - field.X.Y.read = false oculta
 * - field.X.Y.edit = false bloquea edicion (lectura sigue)
 * - read=false implica edit=false
 */
import { describe, it, expect } from 'vitest'
import { canReadField, canEditField } from '@/lib/permissions'

const user = (role = 'asesor', perms = {}) => ({
  role,
  permissions: perms,
})

describe('canReadField', () => {
  it('admin legacy bypasea cualquier restriccion', () => {
    const u = user('admin', { 'field.leads.telefono.read': false })
    expect(canReadField(u, 'leads', 'telefono')).toBe(true)
  })

  it('flag _all bypasea', () => {
    const u = user('asesor', { _all: true, 'field.leads.telefono.read': false })
    expect(canReadField(u, 'leads', 'telefono')).toBe(true)
  })

  it('default true cuando la key no esta en perms (compat)', () => {
    const u = user('asesor', {})
    expect(canReadField(u, 'leads', 'telefono')).toBe(true)
  })

  it('field.X.Y.read = false bloquea lectura', () => {
    const u = user('asesor', { 'field.leads.telefono.read': false })
    expect(canReadField(u, 'leads', 'telefono')).toBe(false)
  })

  it('field.X.Y.read = true permite explicito', () => {
    const u = user('asesor', { 'field.leads.telefono.read': true })
    expect(canReadField(u, 'leads', 'telefono')).toBe(true)
  })

  it('null user devuelve false (defensa)', () => {
    expect(canReadField(null, 'leads', 'telefono')).toBe(false)
  })
})

describe('canEditField', () => {
  it('admin legacy bypasea cualquier restriccion', () => {
    const u = user('admin', { 'field.leads.telefono.edit': false })
    expect(canEditField(u, 'leads', 'telefono')).toBe(true)
  })

  it('flag _all bypasea', () => {
    const u = user('asesor', { _all: true, 'field.leads.telefono.edit': false })
    expect(canEditField(u, 'leads', 'telefono')).toBe(true)
  })

  it('default true cuando la key no esta en perms', () => {
    const u = user('asesor', {})
    expect(canEditField(u, 'leads', 'telefono')).toBe(true)
  })

  it('field.X.Y.edit = false bloquea edicion (lectura libre)', () => {
    const u = user('asesor', { 'field.leads.telefono.edit': false })
    expect(canReadField(u, 'leads', 'telefono')).toBe(true)
    expect(canEditField(u, 'leads', 'telefono')).toBe(false)
  })

  it('read=false implica edit=false aunque edit no este explicito', () => {
    const u = user('asesor', { 'field.leads.telefono.read': false })
    expect(canEditField(u, 'leads', 'telefono')).toBe(false)
  })

  it('null user devuelve false', () => {
    expect(canEditField(null, 'leads', 'telefono')).toBe(false)
  })

  it('multiples restricciones independientes por field', () => {
    const u = user('asesor', {
      'field.leads.telefono.edit': false,
      'field.leads.email.edit': false,
      'field.leads.observaciones.read': false,
    })
    expect(canEditField(u, 'leads', 'telefono')).toBe(false)
    expect(canEditField(u, 'leads', 'email')).toBe(false)
    expect(canReadField(u, 'leads', 'observaciones')).toBe(false)
    expect(canEditField(u, 'leads', 'observaciones')).toBe(false)
    // presupuesto sigue libre
    expect(canEditField(u, 'leads', 'presupuesto')).toBe(true)
  })
})
