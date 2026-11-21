import { describe, it, expect, beforeEach, vi } from 'vitest'
import useAuthStore from '@/store/authStore'
import api from '@/lib/api'

vi.mock('@/lib/api', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}))


describe('authStore', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    useAuthStore.setState({ token: null, user: null, error: null, isLoading: false })
    vi.clearAllMocks()
  })

  it('inicia sin autenticacion', () => {
    const state = useAuthStore.getState()
    expect(state.token).toBeNull()
    expect(state.user).toBeNull()
  })

  it('logout limpia el estado', () => {
    useAuthStore.setState({
      token: 'test-token',
      user: { email: 'test@test.com', role: 'admin' },
    })
    useAuthStore.getState().logout()
    const state = useAuthStore.getState()
    expect(state.token).toBeNull()
    expect(state.user).toBeNull()
  })

  it('clearError limpia el error', () => {
    useAuthStore.setState({ error: 'Credenciales invalidas' })
    useAuthStore.getState().clearError()
    expect(useAuthStore.getState().error).toBeNull()
  })

  it('isAdmin retorna true para admin', () => {
    useAuthStore.setState({ user: { role: 'admin' } })
    expect(useAuthStore.getState().isAdmin()).toBe(true)
  })

  it('isAdmin retorna false para asesor', () => {
    useAuthStore.setState({ user: { role: 'asesor' } })
    expect(useAuthStore.getState().isAdmin()).toBe(false)
  })

  it('canManageTeam retorna true para admin y supervisor', () => {
    useAuthStore.setState({ user: { role: 'admin' } })
    expect(useAuthStore.getState().canManageTeam()).toBe(true)

    useAuthStore.setState({ user: { role: 'supervisor' } })
    expect(useAuthStore.getState().canManageTeam()).toBe(true)
  })

  it('canManageTeam retorna false para asesor', () => {
    useAuthStore.setState({ user: { role: 'asesor' } })
    expect(useAuthStore.getState().canManageTeam()).toBe(false)
  })

  // Live Permission Refresh (ADR-0011)
  describe('refreshPermissions', () => {
    const baseUser = {
      email: 'test@test.com',
      role: 'asesor',
      user_id: 'u1',
      nombre_completo: 'Test User',
      permissions: { 'leads.view': true },
      role_id: null,
      role_is_external: false,
      api_client_id: null,
    }

    it('devuelve "session_invalid" si no hay token', async () => {
      useAuthStore.setState({ token: null, user: null })
      const result = await useAuthStore.getState().refreshPermissions()
      expect(result).toBe('session_invalid')
    })

    it('actualiza el snapshot del user con la respuesta del backend', async () => {
      useAuthStore.setState({ token: 'tok', user: { ...baseUser } })
      localStorage.setItem('user', JSON.stringify(baseUser))
      api.get.mockResolvedValueOnce({
        data: {
          access_token: 'NEW_FRESH_TOKEN',
          permissions: { 'leads.view': true, 'usuarios.manage': true },
          role: 'asesor',
          role_id: 5,
          role_is_external: false,
          api_client_id: null,
        },
      })

      const result = await useAuthStore.getState().refreshPermissions()

      expect(result).toBe('ok')
      const state = useAuthStore.getState()
      expect(state.user.permissions).toEqual({ 'leads.view': true, 'usuarios.manage': true })
      expect(state.user.role_id).toBe(5)
      // El email/nombre_completo preexistente se preserva (no viene en el response)
      expect(state.user.email).toBe('test@test.com')
      expect(state.user.nombre_completo).toBe('Test User')
      // CRITICO: el token tambien se reemplaza, asi las proximas requests
      // pegan al backend con los permisos frescos en el JWT.
      expect(state.token).toBe('NEW_FRESH_TOKEN')
      expect(localStorage.getItem('access_token')).toBe('NEW_FRESH_TOKEN')
    })

    it('si el backend no devuelve access_token, conserva el token actual', async () => {
      useAuthStore.setState({ token: 'OLD_TOKEN', user: { ...baseUser } })
      localStorage.setItem('access_token', 'OLD_TOKEN')
      localStorage.setItem('user', JSON.stringify(baseUser))
      api.get.mockResolvedValueOnce({
        data: {
          permissions: { 'leads.view': true },
          role: 'asesor',
          // sin access_token
        },
      })

      await useAuthStore.getState().refreshPermissions()

      expect(useAuthStore.getState().token).toBe('OLD_TOKEN')
    })

    it('persiste el snapshot nuevo en localStorage si la sesion era "remember"', async () => {
      useAuthStore.setState({ token: 'tok', user: { ...baseUser } })
      localStorage.setItem('user', JSON.stringify(baseUser))
      api.get.mockResolvedValueOnce({
        data: {
          permissions: { 'leads.view': true, 'asignacion.manage': true },
          role: 'asesor',
        },
      })

      await useAuthStore.getState().refreshPermissions()

      const persisted = JSON.parse(localStorage.getItem('user'))
      expect(persisted.permissions['asignacion.manage']).toBe(true)
      // No debe contaminar sessionStorage
      expect(sessionStorage.getItem('user')).toBeNull()
    })

    it('persiste en sessionStorage si la sesion era "no remember"', async () => {
      useAuthStore.setState({ token: 'tok', user: { ...baseUser } })
      sessionStorage.setItem('user', JSON.stringify(baseUser))
      api.get.mockResolvedValueOnce({
        data: { permissions: { 'leads.view': true }, role: 'asesor' },
      })

      await useAuthStore.getState().refreshPermissions()

      expect(sessionStorage.getItem('user')).not.toBeNull()
      const persisted = JSON.parse(sessionStorage.getItem('user'))
      expect(persisted.permissions['leads.view']).toBe(true)
    })

    it('devuelve "session_invalid" en 401 del backend', async () => {
      useAuthStore.setState({ token: 'tok', user: { ...baseUser } })
      api.get.mockRejectedValueOnce({ response: { status: 401 } })
      const result = await useAuthStore.getState().refreshPermissions()
      expect(result).toBe('session_invalid')
    })

    it('devuelve "transient_error" en 5xx — NO debe disparar logout', async () => {
      useAuthStore.setState({ token: 'tok', user: { ...baseUser } })
      api.get.mockRejectedValueOnce({ response: { status: 503 } })
      const result = await useAuthStore.getState().refreshPermissions()
      expect(result).toBe('transient_error')
      // El user del store no se debe haber tocado
      expect(useAuthStore.getState().user.email).toBe('test@test.com')
    })

    it('devuelve "transient_error" en error de red sin response', async () => {
      useAuthStore.setState({ token: 'tok', user: { ...baseUser } })
      api.get.mockRejectedValueOnce(new Error('Network Error'))
      const result = await useAuthStore.getState().refreshPermissions()
      expect(result).toBe('transient_error')
    })

    it('reflejar permission revocada: si el rol perdió usuarios.manage, el snapshot lo refleja', async () => {
      const userConPermiso = {
        ...baseUser,
        permissions: { 'leads.view': true, 'usuarios.manage': true },
      }
      useAuthStore.setState({ token: 'tok', user: userConPermiso })
      api.get.mockResolvedValueOnce({
        data: {
          permissions: { 'leads.view': true },  // usuarios.manage removido
          role: 'asesor',
        },
      })

      await useAuthStore.getState().refreshPermissions()

      const u = useAuthStore.getState().user
      expect(u.permissions['usuarios.manage']).toBeUndefined()
      expect(u.permissions['leads.view']).toBe(true)
    })
  })
})
