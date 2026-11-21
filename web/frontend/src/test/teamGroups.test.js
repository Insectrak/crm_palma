import { describe, it, expect } from 'vitest'
import { buildTeamGroups, flattenGroups } from '@/lib/teamGroups'

describe('buildTeamGroups', () => {
  const users = [
    { id: 'sup-1', first_name: 'Diego', last_name: 'Moreno', email: 'diego@crm.com', role: 'supervisor', is_active: true },
    { id: 'sup-2', first_name: 'Darwin', last_name: 'Gomez', email: 'darwin@crm.com', role: 'supervisor', is_active: true },
    { id: 'ase-1', first_name: 'Carlos', last_name: 'Perez', email: 'carlos@crm.com', role: 'asesor', is_active: true },
  ]

  const equipos = [
    { supervisor_id: 'sup-1', supervisor_nombre: 'Diego Moreno', asesor_id: 'ase-1' }
  ]

  it('permite a un supervisor incluirse a sí mismo en los supervisores para filtros y asignaciones', () => {
    const { groups } = buildTeamGroups({
      users,
      equipos,
      role: 'supervisor',
      currentUserId: 'sup-1',
    })

    const flattened = flattenGroups(groups)
    const selfUser = flattened.find(u => u.id === 'sup-1')

    expect(selfUser).toBeDefined()
    expect(selfUser.nombre_completo).toContain('Diego Moreno')
    expect(selfUser.nombre_completo).toContain('(Tú - Supervisor)')
  })

  it('incluye también a otros supervisores para cross-derivación', () => {
    const { groups } = buildTeamGroups({
      users,
      equipos,
      role: 'supervisor',
      currentUserId: 'sup-1',
    })

    const flattened = flattenGroups(groups)
    const otherSup = flattened.find(u => u.id === 'sup-2')

    expect(otherSup).toBeDefined()
    expect(otherSup.nombre_completo).toContain('Darwin Gomez')
    expect(otherSup.nombre_completo).toContain('(Supervisor)')
  })
})
