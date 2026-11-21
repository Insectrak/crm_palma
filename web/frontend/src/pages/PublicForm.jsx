/**
 * PublicForm.jsx — Página pública renderizada en /f/:slug.
 *
 * Renderiza un formulario configurable por el backend y envía la submission
 * al endpoint público. No requiere autenticación. Aplica la marca
 * (logo + colores) del tenant vía brandStore.
 *
 * Anti-spam integrado con el servicio:
 *  - Honeypot `website` (oculto visualmente, `autoComplete="off"`)
 *  - `_elapsed` en segundos desde el mount — rechazado si <2s
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'react-router-dom'
import api from '@/lib/api'
import useBrandStore from '@/store/brandStore'
import { normalizePhonePE } from '@/lib/phone'

// Mapa de labels por defecto para campos conocidos
const DEFAULT_LABELS = {
  nombres:       'Nombres',
  apellidos:     'Apellidos',
  telefono:      'Teléfono',
  email:         'Correo electrónico',
  dni:           'DNI',
  observaciones: 'Mensaje / Comentarios',
}

// Tipo de input HTML apropiado por campo
const INPUT_TYPES = {
  nombres:       'text',
  apellidos:     'text',
  telefono:      'tel',
  email:         'email',
  dni:           'text',
  observaciones: 'textarea',
}

/**
 * Normaliza el detail de error de FastAPI a string legible (mismo helper que
 * en CargaMasiva — lo duplicamos aquí para mantener la página pública
 * autosuficiente y sin dependencias del árbol privado).
 */
function formatApiError(err, fallback = 'No se pudo enviar el formulario.') {
  const detail = err?.response?.data?.detail
  if (detail == null) return err?.message || fallback
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map(d => {
      if (typeof d === 'string') return d
      const msg = d?.msg || d?.message || JSON.stringify(d)
      return msg
    }).join(' · ')
  }
  if (typeof detail === 'object') return detail.msg || detail.message || JSON.stringify(detail)
  return String(detail)
}

// Inicializador de Meta Pixel
function initMetaPixel(pixelId) {
  if (typeof window === 'undefined') return
  if (!window.fbq) {
    !function(f,b,e,v,n,t,s)
    {if(f.fbq)return;n=f.fbq=function(){n.callMethod?
    n.callMethod.apply(n,arguments):n.queue.push(arguments)};
    if(!f._fbq)f._fbq=n;n.push=n;n.loaded=!0;n.version='2.0';
    n.queue=[];t=b.createElement(e);t.async=!0;
    t.src=v;s=b.getElementsByTagName(e)[0];
    s.parentNode.insertBefore(t,s)}(window, document,'script',
    'https://connect.facebook.net/en_US/fbevents.js');
  }
  window.fbq('init', pixelId);
  window.fbq('track', 'PageView');
}

// Inicializador de TikTok Pixel
function initTikTokPixel(pixelId) {
  if (typeof window === 'undefined') return
  if (!window.ttq) {
    !function (w, d, t) {
      w.TiktokAnalyticsObject=t;var ttq=w[t]=w[t]||[];ttq.methods=["page","track","identify","instances","debug","on","off","once","ready","alias","group","enableCookie","disableCookie","holdConsent","revokeConsent","grantConsent"],ttq.setAndDefer=function(t,e){t[e]=function(){t.push([e].concat(Array.prototype.slice.call(arguments,0)))}};for(var e=0;e<ttq.methods.length;e++)ttq.setAndDefer(ttq,ttq.methods[e]);ttq.instance=function(t){for(var e=ttq._i[t]||[],n=0;n<ttq.methods.length;n++)ttq.setAndDefer(e,ttq.methods[n]);return e};ttq.load=function(e,n){var r="https://analytics.tiktok.com/i18n/pixel/events.js",o=n&&n.mixpool;w[t].type="use_lazy_load",w[t].mixpool=o,w[t].l=Date.now();var i=d.createElement("script");i.type="text/javascript",i.async=!0,i.src=r;var a=d.getElementsByTagName("script")[0];a.parentNode.insertBefore(i,a)};
      ttq.load(pixelId);
      ttq.page();
    }(window, document, 'ttq');
  } else {
    window.ttq.load(pixelId);
    window.ttq.page();
  }
}

export default function PublicForm() {
  const { slug } = useParams()
  const brand = useBrandStore((s) => s.brand)

  const [status, setStatus] = useState('loading') // loading | ready | success | error | notfound
  const [form, setForm] = useState(null)
  const [values, setValues] = useState({})
  // Código de país del teléfono — editable por si el lead es extranjero.
  // Se guarda como dígitos (sin el "+") para simplificar el input.
  const [phoneCC, setPhoneCC] = useState('51')
  const [honeypot, setHoneypot] = useState('')    // campo oculto
  const [submitting, setSubmitting] = useState(false)
  const [errorMsg, setErrorMsg] = useState('')
  const [successData, setSuccessData] = useState(null)

  // Tiempo de montaje para el anti-bot min-time
  const mountedAt = useRef(Date.now())

  // Cargar metadata pública del form
  useEffect(() => {
    let active = true
    api.get(`/api/f/${encodeURIComponent(slug)}`)
      .then(res => {
        if (!active) return
        setForm(res.data)
        const initial = {}
        for (const campo of res.data.config?.campos || []) {
          initial[campo.key] = ''
        }
        setValues(initial)
        setStatus('ready')
      })
      .catch(err => {
        if (!active) return
        if (err?.response?.status === 404) {
          setStatus('notfound')
        } else if (err?.response?.status === 410) {
          setErrorMsg(formatApiError(err, 'Este formulario ya no está disponible.'))
          setStatus('error')
        } else {
          setErrorMsg(formatApiError(err, 'No se pudo cargar el formulario.'))
          setStatus('error')
        }
      })
    return () => { active = false }
  }, [slug])

  // Inicializar Pixels de Seguimiento si están configurados en el Formulario
  useEffect(() => {
    if (form) {
      if (form.meta_pixel_id) {
        initMetaPixel(form.meta_pixel_id)
      }
      if (form.tiktok_pixel_id) {
        initTikTokPixel(form.tiktok_pixel_id)
      }
    }
  }, [form])

  const campos = useMemo(() => form?.config?.campos || [], [form])

  const handleChange = (key, val) => {
    setValues(v => ({ ...v, [key]: val }))
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (submitting) return
    setErrorMsg('')

    // ── Validaciones canónicas en el cliente ──────────────────────────────
    // Estas validaciones son espejo de las del backend — el objetivo es dar
    // feedback inmediato al usuario sin un round-trip, pero el backend sigue
    // siendo source of truth y las revalida.

    const clean = { ...values }

    // Trim + colapsa whitespace en todos los strings
    for (const k of Object.keys(clean)) {
      if (typeof clean[k] === 'string') {
        clean[k] = clean[k].trim().replace(/\s+/g, ' ')
      }
    }

    // nombres/apellidos: mínimo 2 caracteres
    for (const nameField of ['nombres', 'apellidos']) {
      if (clean[nameField] && clean[nameField].length < 2) {
        setErrorMsg(`El campo ${nameField} debe tener al menos 2 caracteres.`)
        return
      }
    }

    // email: formato válido + lowercase
    if (clean.email) {
      clean.email = clean.email.toLowerCase()
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(clean.email)) {
        setErrorMsg('El email no tiene un formato válido.')
        return
      }
    }

    // teléfono: V070.96 — usar normalizador centralizado para alinear
    // con backend (anti-junk, formato PE estricto, E.164 internacional).
    // El input ya viene con código de país en `phoneCC`, así que armamos
    // el string completo antes de validar.
    if (clean.telefono) {
      const localDigits = clean.telefono.replace(/\D/g, '')
      const ccDigits = (phoneCC || '').replace(/\D/g, '')
      if (!ccDigits || ccDigits.length < 1 || ccDigits.length > 4) {
        setErrorMsg('El código de país es inválido.')
        return
      }
      const fullRaw = `+${ccDigits}${localDigits}`
      const r = normalizePhonePE(fullRaw)
      if (!r.valid) {
        setErrorMsg(r.error || 'El teléfono no tiene un formato válido.')
        return
      }
      clean.telefono = r.normalized
    }

    // DNI: 8 dígitos exactos
    if (clean.dni) {
      const dniDigits = clean.dni.replace(/\D/g, '')
      if (dniDigits.length !== 8) {
        setErrorMsg('El DNI debe tener exactamente 8 dígitos.')
        return
      }
      clean.dni = dniDigits
    }

    setSubmitting(true)
    const elapsed = (Date.now() - mountedAt.current) / 1000

    try {
      const res = await api.post(`/api/f/${encodeURIComponent(slug)}/submit`, {
        data: clean,
        website: honeypot,      // honeypot
        _elapsed: elapsed,
      })
      setSuccessData(res.data)
      setStatus('success')

      // Disparar eventos de conversión si los píxeles están configurados
      if (form?.meta_pixel_id && window.fbq) {
        window.fbq('track', 'Lead')
      }
      if (form?.tiktok_pixel_id && window.ttq) {
        window.ttq.track('CompleteRegistration')
      }

      // Redirect opcional configurado por el creador del form
      if (res.data?.redirect_url) {
        setTimeout(() => {
          window.location.href = res.data.redirect_url
        }, 1500)
      }
    } catch (err) {
      setErrorMsg(formatApiError(err))
    } finally {
      setSubmitting(false)
    }
  }

  // ── Render states ────────────────────────────────────────────────────────

  if (status === 'loading') {
    return (
      <PageShell brand={brand}>
        <div className="text-center text-slate-500">Cargando formulario…</div>
      </PageShell>
    )
  }

  if (status === 'notfound') {
    return (
      <PageShell brand={brand}>
        <div className="text-center">
          <h1 className="text-xl font-semibold text-slate-800 mb-2">
            Formulario no encontrado
          </h1>
          <p className="text-sm text-slate-500">
            Verifica el enlace o contacta al organizador del evento.
          </p>
        </div>
      </PageShell>
    )
  }

  if (status === 'error' && !form) {
    return (
      <PageShell brand={brand}>
        <div className="text-center">
          <h1 className="text-xl font-semibold text-slate-800 mb-2">
            No disponible
          </h1>
          <p className="text-sm text-slate-500">{errorMsg}</p>
        </div>
      </PageShell>
    )
  }

  if (status === 'success') {
    return (
      <PageShell brand={brand} form={form}>
        <div className="text-center py-6">
          <div className="mx-auto w-14 h-14 rounded-full bg-emerald-100 flex items-center justify-center mb-4">
            <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="#059669" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round">
              <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
          </div>
          <h2 className="text-xl font-semibold text-slate-800 mb-2">¡Gracias!</h2>
          <p className="text-slate-600">
            {successData?.mensaje_exito || '¡Gracias! Pronto te contactaremos.'}
          </p>
          {successData?.redirect_url && (
            <p className="text-xs text-slate-400 mt-4">Redirigiéndote…</p>
          )}
        </div>
      </PageShell>
    )
  }

  // status === 'ready'
  return (
    <PageShell brand={brand} form={form}>
      <form onSubmit={handleSubmit} className="space-y-4" noValidate>
        {campos.map((campo) => (
          <FieldRenderer
            key={campo.key}
            campo={campo}
            value={values[campo.key] ?? ''}
            onChange={(v) => handleChange(campo.key, v)}
            phoneCC={phoneCC}
            onPhoneCCChange={setPhoneCC}
          />
        ))}

        {/* Honeypot — oculto para humanos, visible para bots */}
        <div aria-hidden="true" style={{ position: 'absolute', left: '-10000px', top: 'auto', width: 1, height: 1, overflow: 'hidden' }}>
          <label>
            No llenar este campo
            <input
              type="text"
              tabIndex={-1}
              autoComplete="off"
              value={honeypot}
              onChange={(e) => setHoneypot(e.target.value)}
            />
          </label>
        </div>

        {errorMsg && (
          <div className="rounded-md bg-rose-50 border border-rose-200 text-rose-700 text-sm p-3">
            {errorMsg}
          </div>
        )}

        <button
          type="submit"
          disabled={submitting}
          className="w-full py-3 rounded-lg font-medium text-white transition disabled:opacity-60 disabled:cursor-not-allowed"
          style={{ backgroundColor: brand?.primary_color || '#4F46E5' }}
        >
          {submitting ? 'Enviando…' : 'Enviar'}
        </button>

        <p className="text-xs text-slate-500 text-center leading-relaxed mt-3 px-1 text-balance">
          Al enviar aceptas que tus datos sean usados para contactarte sobre esta campaña.
        </p>
      </form>
    </PageShell>
  )
}


/* ── Subcomponentes ──────────────────────────────────────────────────────── */

function PageShell({ brand, form, children }) {
  const primary = brand?.primary_color || '#4F46E5'
  const companyName = brand?.company_name || 'CRM'
  return (
    <div className="min-h-screen bg-slate-50 flex flex-col">
      {/* Header con logo + colores del tenant */}
      <header
        className="w-full py-6 px-4 flex items-center justify-center"
        style={{
          background: `linear-gradient(135deg, ${primary} 0%, ${brand?.primary_hover || primary} 100%)`,
        }}
      >
        {brand?.logo_data_url ? (
          <img
            src={brand.logo_data_url}
            alt={companyName}
            className="h-12 max-w-[220px] object-contain"
          />
        ) : (
          <div className="text-white font-semibold text-lg">{companyName}</div>
        )}
      </header>

      <main className="flex-1 flex items-center justify-center p-4">
        <div className="w-full max-w-md bg-white rounded-xl shadow-sm border border-slate-200 p-6">
          {form && (
            <div className="mb-5">
              <h1 className="text-lg font-semibold text-slate-800">{form.titulo}</h1>
              {form.empresa && (
                <p className="text-xs text-slate-500 mt-0.5">{form.empresa}</p>
              )}
              {form.descripcion && (
                <p className="text-sm text-slate-600 mt-2 whitespace-pre-line">
                  {form.descripcion}
                </p>
              )}
            </div>
          )}
          {children}
        </div>
      </main>

      <footer className="text-center text-[11px] text-slate-400 py-4">
        Powered by {companyName}
      </footer>
    </div>
  )
}


function FieldRenderer({ campo, value, onChange, phoneCC, onPhoneCCChange }) {
  const label = campo.label || DEFAULT_LABELS[campo.key] || campo.key
  const type = INPUT_TYPES[campo.key] || 'text'
  const required = !!campo.required
  const id = `f-${campo.key}`

  // El teléfono tiene su propio componente con código de país editable.
  // El código y los dígitos se combinan en handleSubmit como E.164 para que
  // la BD guarde siempre el formato canónico (+<cc><digits>) y las
  // integraciones posteriores (WhatsApp) no tengan que transformar nada.
  if (campo.key === 'telefono') {
    return (
      <PhoneField
        id={id}
        label={label}
        required={required}
        value={value}
        onChange={onChange}
        countryCode={phoneCC}
        onCountryCodeChange={onPhoneCCChange}
      />
    )
  }

  if (type === 'textarea') {
    return (
      <div>
        <label htmlFor={id} className="block text-sm font-medium text-slate-700 mb-1">
          {label}{required && <span className="text-rose-500"> *</span>}
        </label>
        <textarea
          id={id}
          rows={4}
          required={required}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
        />
      </div>
    )
  }

  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-slate-700 mb-1">
        {label}{required && <span className="text-rose-500"> *</span>}
      </label>
      <input
        id={id}
        type={type}
        required={required}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        autoComplete={type === 'email' ? 'email' : type === 'tel' ? 'tel' : 'off'}
        className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
      />
    </div>
  )
}


/**
 * Input de teléfono con código de país editable + dígitos del móvil.
 *
 * - El código de país se maneja como dígitos puros (sin el "+"), el "+" se
 *   renderiza fijo como prefijo visual — así el usuario no puede romper el
 *   formato E.164.
 * - Si el usuario pega un número con código de país en el input de dígitos
 *   (ej. "51987654321" o "+51 987-654-321"), extraemos el código correcto
 *   automáticamente y lo dejamos en el input del país.
 * - Aceptamos cualquier longitud razonable (hasta 15 dígitos, límite E.164).
 */
function PhoneField({ id, label, required, value, onChange, countryCode, onCountryCodeChange }) {
  const handleCountryCodeChange = (e) => {
    // Solo dígitos, máximo 4 (el código más largo del mundo es +998)
    const raw = e.target.value.replace(/\D/g, '').slice(0, 4)
    onCountryCodeChange(raw)
  }

  const handleChange = (e) => {
    let raw = e.target.value.replace(/\D/g, '')
    // Si pegaron con código país (ej. "51987654321" o similar) y coincide con
    // el código actual, lo quitamos del número local.
    const cc = (countryCode || '').replace(/\D/g, '')
    if (cc && raw.startsWith(cc) && raw.length > cc.length) {
      raw = raw.slice(cc.length)
    }
    // Cap a 15 dígitos (límite E.164 incluyendo país)
    raw = raw.slice(0, 15)
    onChange(raw)
  }

  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-slate-700 mb-1">
        {label}{required && <span className="text-rose-500"> *</span>}
      </label>
      <div className="flex rounded-md border border-slate-300 focus-within:ring-2 focus-within:ring-indigo-500 focus-within:border-transparent overflow-hidden bg-white">
        <div className="inline-flex items-center gap-0.5 pl-3 pr-2 bg-slate-50 border-r border-slate-300 text-sm text-slate-700">
          <span className="font-semibold select-none">+</span>
          <input
            type="text"
            inputMode="numeric"
            value={countryCode}
            onChange={handleCountryCodeChange}
            maxLength={4}
            aria-label="Código de país"
            className="w-10 py-2 bg-transparent text-sm font-semibold focus:outline-none"
          />
        </div>
        <input
          id={id}
          type="tel"
          inputMode="numeric"
          required={required}
          value={value}
          onChange={handleChange}
          placeholder="987 654 321"
          maxLength={15}
          autoComplete="tel-national"
          className="flex-1 px-3 py-2 text-sm focus:outline-none bg-white min-w-0"
        />
      </div>
      <p className="text-[11px] text-slate-400 mt-1">
        Ingresa los dígitos del móvil. Puedes editar el código de país si lo necesitas.
      </p>
    </div>
  )
}
