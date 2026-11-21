import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import api from '@/lib/api'

/**
 * Pantalla de setup inicial — primera pantalla que ve el cliente al
 * entrar a un CRM virgen (cuando /api/setup/status devuelve
 * needs_setup: true).
 *
 * Branding default CRM:
 *   - Color indigo (#4F46E5) consistente con favicon.svg + LoginScreen
 *   - Logo "A" inline SVG (mismo del favicon)
 *   - Sin pre-relleno de credenciales (cero asumir nombres especificos)
 *   - Campo "Email" en lugar de "Usuario" (coincide con auth.users.email)
 *
 * El campo `username` del payload conserva su nombre por compat con el
 * endpoint backend, pero el LABEL al usuario dice "Email" para que sea
 * intuitivo (el sistema lo guarda en auth.users.email de todos modos).
 */
export default function Setup() {
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [nombreCompleto, setNombreCompleto] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    // Si ya hay usuarios, redirigir al login
    api.get('/api/setup/status')
      .then(res => {
        if (!res.data.needs_setup) navigate('/login', { replace: true })
        else setChecking(false)
      })
      .catch(() => { setChecking(false) })
  }, [navigate])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    if (!email.trim()) { setError('El email es obligatorio.'); return }
    if (!email.includes('@')) { setError('Ingresa un email válido.'); return }
    if (password.length < 6) { setError('La contraseña debe tener al menos 6 caracteres.'); return }
    if (password !== confirm) { setError('Las contraseñas no coinciden.'); return }

    setLoading(true)
    try {
      // El backend espera "username" en el payload pero lo guarda en
      // auth.users.email — los nombres están desfasados por compat.
      await api.post('/api/setup/create-admin', {
        username: email.trim().toLowerCase(),
        password,
        nombre_completo: nombreCompleto,
      })
      navigate('/login', { replace: true })
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al crear el usuario.')
    } finally {
      setLoading(false)
    }
  }

  if (checking) return null

  return (
    <div className="min-h-screen bg-gradient-to-br from-slate-900 to-slate-700 flex items-center justify-center p-4">
      <Card className="w-full max-w-md shadow-2xl">
        <CardHeader className="text-center pb-2">
          {/* Logo CRM */}
          <div className="mx-auto w-14 h-14 rounded-2xl flex items-center justify-center mb-4 shadow-lg bg-[#4F46E5]">
            <svg viewBox="0 0 32 32" className="w-9 h-9">
              <path
                d="M 8 25 L 16 6 L 24 25 L 20.5 25 L 18.8 20.5 L 13.2 20.5 L 11.5 25 Z M 14 17.8 L 18 17.8 L 16 12.5 Z"
                fill="white"
              />
            </svg>
          </div>
          <CardTitle className="text-2xl font-bold text-slate-900">
            Configuración Inicial
          </CardTitle>
          <CardDescription className="text-slate-500 mt-1">
            Crea el usuario administrador del sistema
          </CardDescription>
        </CardHeader>

        <CardContent className="pt-4">
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="nombre">Nombre completo</Label>
              <Input
                id="nombre"
                type="text"
                placeholder="Ej: María García"
                value={nombreCompleto}
                onChange={(e) => setNombreCompleto(e.target.value)}
                disabled={loading}
                autoFocus
                autoComplete="name"
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="admin@tuempresa.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={loading}
                autoComplete="email"
                required
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="password">Contraseña</Label>
              <Input
                id="password"
                type="password"
                placeholder="Mínimo 6 caracteres"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                disabled={loading}
                autoComplete="new-password"
                required
              />
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="confirm">Confirmar contraseña</Label>
              <Input
                id="confirm"
                type="password"
                placeholder="Repite la contraseña"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                disabled={loading}
                autoComplete="new-password"
                required
              />
            </div>

            {error && (
              <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-md px-3 py-2">
                {error}
              </div>
            )}

            <Button
              type="submit"
              className="w-full h-11 text-base font-medium bg-[#4F46E5] hover:bg-[#4338CA] text-white"
              disabled={loading}
            >
              {loading ? (
                <span className="flex items-center gap-2">
                  <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  Creando usuario...
                </span>
              ) : 'Crear usuario y continuar'}
            </Button>
          </form>

          <p className="text-center text-xs text-gray-400 mt-6">
            Plataforma CRM
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
