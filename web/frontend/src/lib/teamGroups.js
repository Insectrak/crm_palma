/**
 * Agrupa usuarios para los selectores de Reasignar / Asignar.
 *
 * Salida unificada: lista ordenada de "equipos" tal como los renderiza
 * la barra bulk de Asignación y la barra bulk de Leads. Mantener una sola
 * forma evita inconsistencias entre páginas (ver bug de "Asesores vs
 * Equipo: Diego" reportado por el supervisor).
 *
 * Esquema:
 *   [
 *     { supervisor_id, supervisor_nombre, asesores: [user, ...] },
 *     ...,
 *     { supervisor_id: '__supers__', supervisor_nombre: 'Otros supervisores',
 *       asesores: [supervisor, ...] }    // solo cuando aplica
 *   ]
 *
 * Reglas por rol del usuario que mira:
 *   - admin:      ve todos los equipos. No agrega "Otros supervisores"
 *                 porque cada supervisor ya tiene su propia sección.
 *   - supervisor: solo ve su equipo + sección "Otros supervisores" con
 *                 los demás supervisores activos (cross-derivación).
 *   - asesor:     no debería llamar a esta función (no puede reasignar).
 */
export function buildTeamGroups({
  users = [],
  equipos = [],
  role,
  currentUserId,
  asignacionScope = 'equipo',
  allowedUserIds = [],
}) {
  const asesorSupMap = {}
  for (const e of equipos) {
    if (e.asesor_id) asesorSupMap[e.asesor_id] = e
  }

  const decorate = u => ({
    ...u,
    nombre_completo:
      [u.first_name, u.last_name].filter(Boolean).join(' ') || u.email,
    supervisor_id:     asesorSupMap[u.id]?.supervisor_id || null,
    supervisor_nombre: asesorSupMap[u.id]?.supervisor_nombre || null,
  })

  const isGlobal = role === 'admin' || asignacionScope === 'global'
  const isPersonalizado = asignacionScope === 'personalizado'
  const allowedSet = new Set((allowedUserIds || []).map(String))

  // Si es personalizado, filtramos los usuarios a los autorizados explícitamente (+ sí mismo)
  const targetUsers = isPersonalizado
    ? users.filter(u => allowedSet.has(String(u.id)) || String(u.id) === String(currentUserId))
    : users

  const asesoresActivos = targetUsers
    .filter(u => u.role === 'asesor' && u.is_active !== false)
    .map(decorate)

  const groupsById = {}
  const sinEquipo  = []
  for (const a of asesoresActivos) {
    if (a.supervisor_id) {
      if (!groupsById[a.supervisor_id]) {
        groupsById[a.supervisor_id] = {
          supervisor_id:     a.supervisor_id,
          supervisor_nombre: a.supervisor_nombre || 'Equipo',
          asesores:          [],
        }
      }
      groupsById[a.supervisor_id].asesores.push(a)
    } else {
      sinEquipo.push(a)
    }
  }

  // Orden alfabético por nombre de supervisor; asesores ordenados dentro
  let finalGroups = Object.values(groupsById)
    .map(g => ({
      ...g,
      asesores: [...g.asesores].sort((a, b) =>
        (a.nombre_completo || '').localeCompare(b.nombre_completo || '')
      ),
    }))
    .sort((a, b) => (a.supervisor_nombre || '').localeCompare(b.supervisor_nombre || ''))

  // 1. MODO PERSONALIZADO
  if (isPersonalizado) {
    // Si hay supervisores en allowedUserIds, los agregamos en su equipo o en grupo de Supervisores
    const supersAutorizados = targetUsers
      .filter(u => u.role === 'supervisor' && u.is_active !== false && allowedSet.has(String(u.id)))
      .map(u => ({
        ...u,
        nombre_completo:
          ([u.first_name, u.last_name].filter(Boolean).join(' ') || u.email) + ' (Supervisor)',
      }))
      .sort((a, b) => (a.nombre_completo || '').localeCompare(b.nombre_completo || ''))

    if (supersAutorizados.length > 0) {
      finalGroups.push({
        supervisor_id:     '__supers__',
        supervisor_nombre: 'Supervisores autorizados',
        asesores:          supersAutorizados,
      })
    }

    if (sinEquipo.length > 0) {
      finalGroups.push({
        supervisor_id:     '__sin_equipo__',
        supervisor_nombre: 'Otros usuarios autorizados',
        asesores:          sinEquipo,
      })
    }

    return { groups: finalGroups, sinEquipo: [] }
  }

  // 2. MODO EQUIPO PARA ASESOR (o rol no supervisor)
  // "puede asignar leads a cualquiera que este en su equipo sea supervisor o no"
  if (!isGlobal && role !== 'supervisor') {
    const myEquipo = equipos.find(e => String(e.asesor_id) === String(currentUserId))
    const mySupId = myEquipo?.supervisor_id
    const mySupName = myEquipo?.supervisor_nombre

    if (mySupId) {
      // Filtrar finalGroups solo al equipo del usuario
      let myGroup = finalGroups.find(g => String(g.supervisor_id) === String(mySupId))
      if (!myGroup) {
        myGroup = {
          supervisor_id: mySupId,
          supervisor_nombre: mySupName || 'Mi Equipo',
          asesores: [],
        }
      }

      // Buscar al supervisor en `users` e incluirlo como opción asignable ("sea supervisor o no")
      const supUser = users.find(u => String(u.id) === String(mySupId))
      const supDecorated = supUser ? {
        ...supUser,
        nombre_completo: ([supUser.first_name, supUser.last_name].filter(Boolean).join(' ') || supUser.email) + ' (Supervisor)',
      } : {
        id: mySupId,
        nombre_completo: (mySupName || 'Supervisor') + ' (Supervisor)',
        role: 'supervisor',
      }

      // El supervisor va primero en la lista de asesores de su equipo
      const teamAsesores = myGroup.asesores.filter(a => String(a.id) !== String(mySupId))
      return {
        groups: [{
          ...myGroup,
          supervisor_nombre: mySupName || 'Mi Equipo',
          asesores: [supDecorated, ...teamAsesores],
        }],
        sinEquipo: [],
      }
    }
  }

  // 3. MODO EQUIPO PARA SUPERVISOR: su propio equipo + subordinados
  if (role === 'supervisor' && !isGlobal) {
    const subordinateSupIds = new Set(
      users
        .filter(u => u.role === 'supervisor' && u.supervisor_jefe_id === currentUserId)
        .map(u => u.id)
    )
    finalGroups = finalGroups.filter(
      g => g.supervisor_id === currentUserId || subordinateSupIds.has(g.supervisor_id)
    )

    // Sección "Supervisores" (otros supervisores activos para cross-derivación)
    const otros = users
      .filter(u => u.role === 'supervisor' && u.is_active !== false)
      .map(u => ({
        ...u,
        nombre_completo:
          ([u.first_name, u.last_name].filter(Boolean).join(' ') || u.email)
          + (u.id === currentUserId ? ' (Tú - Supervisor)' : ' (Supervisor)'),
      }))
      .sort((a, b) => (a.nombre_completo || '').localeCompare(b.nombre_completo || ''))

    if (otros.length > 0) {
      finalGroups = [
        ...finalGroups,
        {
          supervisor_id:     '__supers__',
          supervisor_nombre: 'Supervisores',
          asesores:          otros,
        },
      ]
    }
  }

  // 4. MODO GLOBAL / ADMIN: agregar sección "Delegar a supervisor"
  if (isGlobal) {
    const supervisores = users
      .filter(u => u.role === 'supervisor' && u.is_active !== false)
      .map(u => ({
        ...u,
        nombre_completo:
          ([u.first_name, u.last_name].filter(Boolean).join(' ') || u.email)
          + ' (cola del supervisor)',
      }))
      .sort((a, b) => (a.nombre_completo || '').localeCompare(b.nombre_completo || ''))

    if (supervisores.length > 0) {
      finalGroups = [
        ...finalGroups,
        {
          supervisor_id:     '__delegar_sup__',
          supervisor_nombre: 'Delegar a supervisor',
          asesores:          supervisores,
        },
      ]
    }
  }

  return { groups: finalGroups, sinEquipo: role === 'supervisor' ? [] : sinEquipo }
}

/**
 * Aplana un array de groups en una lista de usuarios (útil para lookups
 * por id, p.ej. obtener nombre del asesor seleccionado para un confirm).
 */
export function flattenGroups(groups) {
  const out = []
  for (const g of groups || []) {
    for (const a of g.asesores || []) out.push(a)
  }
  return out
}
