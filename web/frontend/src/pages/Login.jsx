import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '@/lib/api'
import { safeLocal } from '@/lib/safeStorage'
import { Building2, Eye, EyeOff } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from '@/components/ui/card'
import useAuthStore from '@/store/authStore'
import useBrandStore from '@/store/brandStore'

export default function Login() {
  const navigate = useNavigate()
  const { login, isLoading, error, clearError } = useAuthStore()
  const brand = useBrandStore((s) => s.brand)

  // Si la DB esta virgen (sin admin), redirigir a /setup ANTES de
  // renderizar el form de login. Sin esto, el usuario ve un parpadeo
  // "Mi CRM" -> "/setup" en el primer install que se ve poco profesional.
  // checkingSetup=true mantiene un loader hasta que el redirect ocurre.
  const [checkingSetup, setCheckingSetup] = useState(true)

  useEffect(() => {
    api.get('/api/setup/status')
      .then(res => {
        if (res.data.needs_setup) {
          navigate('/setup', { replace: true })
        } else {
          setCheckingSetup(false)
        }
      })
      .catch(() => {
        // Si /api/setup/status falla, asumimos que la DB esta OK y
        // dejamos pasar al login normal — el usuario sabra si esta
        // bootstrapped intentando loguearse.
        setCheckingSetup(false)
      })
  }, [navigate])

  const [email, setEmail] = useState(() => safeLocal.getItem('remembered_email', ''))
  const [password, setPassword] = useState('')
  const [showPassword, setShowPassword] = useState(false)
  const [validationError, setValidationError] = useState('')

  const handleSubmit = async (e) => {
    e.preventDefault()
    setValidationError('')
    clearError()

    if (!email.trim()) {
      setValidationError('El correo es requerido.')
      return
    }
    if (!password) {
      setValidationError('La contraseña es requerida.')
      return
    }

    const cleanEmail = email.trim().toLowerCase()
    const success = await login(cleanEmail, password, true)
    if (success) {
      safeLocal.setItem('remembered_email', cleanEmail)
      navigate('/dashboard')
    }
  }

  const displayError = validationError || error

  // Mientras chequea si necesita setup, no renderizar nada (evita
  // el parpadeo "Mi CRM -> redirect a /setup" en installs vírgenes).
  if (checkingSetup) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-slate-50">
        <div
          className="w-10 h-10 rounded-full border-3 border-slate-300 border-t-transparent animate-spin"
          style={{ borderTopColor: brand?.primary_color || '#4F46E5' }}
        />
      </div>
    )
  }

  return (
    <div className="min-h-screen flex items-center justify-center p-4 bg-slate-50 relative overflow-hidden">
      {/* Accentos sutiles de marca (blobs difuminados) */}
      <div
        aria-hidden
        className="absolute top-[-120px] left-[-120px] w-[360px] h-[360px] rounded-full blur-3xl opacity-[0.12] pointer-events-none"
        style={{ backgroundColor: brand.primary_color }}
      />
      <div
        aria-hidden
        className="absolute bottom-[-140px] right-[-140px] w-[420px] h-[420px] rounded-full blur-3xl opacity-[0.10] pointer-events-none"
        style={{ backgroundColor: brand.primary_color }}
      />

      <Card className="relative w-full max-w-md shadow-2xl border border-slate-200/60">
        <CardHeader className="text-center pb-2">
          {/* Logo e identidad del sistema */}
          <div
            className="mx-auto w-16 h-16 rounded-2xl flex items-center justify-center mb-4 shadow-lg overflow-hidden"
            style={{ backgroundColor: brand.logo_data_url ? 'transparent' : brand.primary_color }}
          >
            {brand.logo_data_url
              ? <img src={brand.logo_data_url} alt="logo" className="w-full h-full object-contain" />
              : <Building2 size={32} className="text-white" />}
          </div>
          <CardTitle className="text-2xl font-bold text-slate-900">
            {brand.company_name}
          </CardTitle>
          <CardDescription className="text-slate-500 mt-1">
            {brand.company_subtitle} — Acceso al Portal
          </CardDescription>
        </CardHeader>

        <CardContent className="pt-4">
          <form onSubmit={handleSubmit} className="space-y-4">
            {/* Campo de email */}
            <div className="space-y-1.5">
              <Label htmlFor="email">Correo electrónico</Label>
              <Input
                id="email"
                type="email"
                placeholder="correo@empresa.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                disabled={isLoading}
                autoComplete="email"
                autoFocus
              />
            </div>

            {/* Campo de contraseña con toggle de visibilidad */}
            <div className="space-y-1.5">
              <Label htmlFor="password">Contraseña</Label>
              <div className="relative">
                <Input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  placeholder="Ingresa tu contraseña"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  disabled={isLoading}
                  autoComplete="current-password"
                  className="pr-10"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword(!showPassword)}
                  className="absolute right-3 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600"
                  tabIndex={-1}
                >
                  {showPassword ? <EyeOff size={16} /> : <Eye size={16} />}
                </button>
              </div>
            </div>

            {/* Mensaje de error */}
            {displayError && (
              <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-md px-3 py-2">
                {displayError}
              </div>
            )}

            {/* Botón de login */}
            <Button
              type="submit"
              className="w-full h-11 text-base font-medium"
              disabled={isLoading}
            >
              {isLoading ? (
                <span className="flex items-center gap-2">
                  <span className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin" />
                  Verificando...
                </span>
              ) : (
                'Ingresar'
              )}
            </Button>
          </form>

          {/* Pie de página del formulario */}
          <p className="text-center text-xs text-gray-400 mt-6">
            Plataforma CRM
          </p>
        </CardContent>
      </Card>
    </div>
  )
}
