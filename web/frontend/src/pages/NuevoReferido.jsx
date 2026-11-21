/**
 * NuevoReferido — Formulario simplificado para que el asesor registre un lead referido.
 * Solo muestra los campos esenciales. La fuente se setea automáticamente como "referido".
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, UserPlus, Check } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import useCrmStore from '@/store/crmStore'
import api from '@/lib/api'
import { normalizePhonePE } from '@/lib/phone'

function Field({ label, required, error, children }) {
  return (
    <div>
      <Label className="text-sm font-medium text-gray-700">
        {label}
        {required && <span className="text-red-400 ml-0.5">*</span>}
      </Label>
      <div className="mt-1.5">{children}</div>
      {error && <p className="text-xs text-red-500 mt-1">{error}</p>}
    </div>
  )
}

export default function NuevoReferido() {
  const navigate = useNavigate()
  const { fuentes, loadCatalogs } = useCrmStore()

  const [form, setForm] = useState({
    nombres: '', apellidos: '', telefono: '', email: '', referido_por: '', observaciones: '',
  })
  const [errors, setErrors]         = useState({})
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitError, setSubmitError]   = useState(null)
  const [success, setSuccess]           = useState(false)

  useEffect(() => { loadCatalogs() }, [])

  const f = (key) => ({
    value: form[key],
    onChange: e => { setForm(p => ({ ...p, [key]: e.target.value })); setErrors(p => ({ ...p, [key]: '' })) },
  })

  const validate = () => {
    const e = {}
    if (!form.nombres.trim() && !form.apellidos.trim()) e.nombres = 'Ingresa al menos el nombre o apellido.'
    if (!form.telefono.trim()) {
      e.telefono = 'El teléfono es obligatorio.'
    } else {
      // V070.96 — anti-junk + formato PE. Bug en prod: referido con
      // +51999999999 pasaba validacion. Ahora se rechaza.
      const r = normalizePhonePE(form.telefono)
      if (!r.valid) e.telefono = r.error || 'Número de teléfono inválido.'
    }
    if (!form.referido_por.trim()) e.referido_por = '¿Quién te refirió este contacto?'
    return e
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    const errs = validate()
    if (Object.keys(errs).length > 0) { setErrors(errs); return }

    setIsSubmitting(true)
    setSubmitError(null)

    // Buscar id de la fuente "referido"
    const fuenteReferido = fuentes.find(f => f.nombre === 'referido')

    // V070.96 — siempre mandar telefono normalizado E.164 al backend.
    const phoneE164 = normalizePhonePE(form.telefono).normalized || form.telefono.trim()

    try {
      await api.post('/api/leads', {
        nombres:      form.nombres.trim() || null,
        apellidos:    form.apellidos.trim() || null,
        telefono:     phoneE164,
        email:        form.email.trim() || null,
        referido_por: form.referido_por.trim(),
        observaciones: form.observaciones.trim() || null,
        fuente_id:    fuenteReferido?.id || null,
      })
      setSuccess(true)
    } catch (err) {
      if (err.response?.status === 409) {
        setSubmitError('Ya existe un lead con este teléfono (posible duplicado).')
      } else {
        setSubmitError(err.response?.data?.detail || 'Error al guardar. Intenta nuevamente.')
      }
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleNuevo = () => {
    setForm({ nombres: '', apellidos: '', telefono: '', email: '', referido_por: '', observaciones: '' })
    setErrors({})
    setSubmitError(null)
    setSuccess(false)
  }

  // ── Pantalla de éxito ────────────────────────────────────────────────────
  if (success) return (
    <div className="max-w-md mx-auto mt-12">
      <div className="bg-white border border-gray-100 rounded-2xl p-8 text-center shadow-sm space-y-4">
        <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto">
          <Check size={32} className="text-green-600" />
        </div>
        <div>
          <h2 className="text-xl font-bold text-gray-900">¡Referido registrado!</h2>
          <p className="text-sm text-gray-500 mt-1">
            <span className="font-medium text-gray-800">
              {[form.nombres, form.apellidos].filter(Boolean).join(' ')}
            </span>{' '}
            fue referido por <span className="font-medium text-gray-800">{form.referido_por}</span>.
          </p>
        </div>
        <div className="flex gap-3 justify-center pt-2">
          {/* Despues de crear el referido: "Ver Leads" SI quiere ir a /leads
              explicitamente (es una accion, no un back). Mantenemos. */}
          <Button variant="outline" onClick={() => navigate('/leads')}>
            Ver Leads
          </Button>
          <Button onClick={handleNuevo} className="gap-2">
            <UserPlus size={15} /> Registrar otro
          </Button>
        </div>
      </div>
    </div>
  )

  // ── Formulario ───────────────────────────────────────────────────────────
  return (
    <div className="max-w-lg space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3">
        <button
          onClick={() => (window.history.length > 1 ? navigate(-1) : navigate('/leads'))}
          className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500"
          title="Volver"
        >
          <ArrowLeft size={18} />
        </button>
        <div>
          <h1 className="text-xl font-bold text-gray-900">Registrar Referido</h1>
          <p className="text-sm text-gray-400">Ingresa los datos del contacto que te recomendaron</p>
        </div>
      </div>

      <form onSubmit={handleSubmit} className="bg-white border border-gray-100 rounded-2xl p-6 shadow-sm space-y-5">

        {/* Quién refirió — campo destacado al inicio */}
        <div className="bg-indigo-50 border border-indigo-100 rounded-xl p-4">
          <Field label="¿Quién te recomendó este contacto?" required error={errors.referido_por}>
            <Input
              {...f('referido_por')}
              placeholder="Nombre del cliente o persona que refirió"
              className={`bg-white ${errors.referido_por ? 'border-red-400' : ''}`}
              autoFocus
            />
          </Field>
        </div>

        {/* Datos del contacto referido */}
        <div className="space-y-4">
          <p className="text-xs font-semibold text-gray-500 uppercase tracking-wide">Datos del contacto referido</p>

          <div className="grid grid-cols-2 gap-3">
            <Field label="Nombres" error={errors.nombres}>
              <Input {...f('nombres')} placeholder="Ej: María" className={errors.nombres ? 'border-red-400' : ''} />
            </Field>
            <Field label="Apellidos">
              <Input {...f('apellidos')} placeholder="Ej: García" />
            </Field>
          </div>

          <Field label="Teléfono" required error={errors.telefono}>
            <div className="flex">
              <span className="inline-flex items-center px-3 text-sm rounded-l-md border border-r-0 border-gray-200 bg-gray-50 text-gray-500 font-mono select-none">
                +51
              </span>
              <input
                type="tel"
                value={form.telefono.replace(/^\+?51/, '')}
                onChange={e => {
                  const digits = e.target.value.replace(/\D/g, '').slice(0, 9)
                  setForm(p => ({ ...p, telefono: digits ? '+51' + digits : '' }))
                }}
                placeholder="987 654 321"
                maxLength={9}
                className={`flex-1 min-w-0 border border-gray-200 rounded-r-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 ${errors.telefono ? 'border-red-400' : ''}`}
              />
            </div>
          </Field>

          <Field label="Email (opcional)">
            <Input {...f('email')} type="email" placeholder="correo@ejemplo.com" />
          </Field>

          <Field label="Notas adicionales (opcional)">
            <textarea
              {...f('observaciones')}
              rows={2}
              placeholder="Ej: Interesado en cotización para esta semana…"
              className="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
            />
          </Field>
        </div>

        {submitError && (
          <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-lg px-4 py-2.5">
            {submitError}
          </div>
        )}

        <div className="flex gap-3 justify-end pt-1">
          <Button
            type="button"
            variant="outline"
            onClick={() => (window.history.length > 1 ? navigate(-1) : navigate('/leads'))}
          >
            Cancelar
          </Button>
          <Button type="submit" disabled={isSubmitting} className="gap-2 min-w-[140px]">
            <UserPlus size={15} />
            {isSubmitting ? 'Guardando…' : 'Guardar referido'}
          </Button>
        </div>
      </form>
    </div>
  )
}
