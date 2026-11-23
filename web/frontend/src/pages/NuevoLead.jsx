import { useEffect, useState, useMemo, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowLeft, Save, Calendar, AlertCircle, UserCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import useAuthStore from '@/store/authStore'
import useCrmStore from '@/store/crmStore'
import api from '@/lib/api'
import { normalizePhonePE } from '@/lib/phone'
import DuplicateBanner from '@/components/leads/DuplicateBanner'
import { isEstadoMatricula, isEstadoSeguimiento, isEstadoPerdido, isEstadoOportunidadFutura, MOTIVOS_PERDIDA_OPCIONES, ACCIONES_OPORTUNIDAD_FUTURA_OPCIONES } from '@/components/leads/CambioEstadoModal'

export default function NuevoLead() {
  const navigate = useNavigate()
  const { user } = useAuthStore()
  const { estados, fuentes, loadCatalogs } = useCrmStore()
  const role = user?.role || 'asesor'
  const canAssign = role === 'admin' || role === 'supervisor'

  const [form, setForm] = useState({
    nombres: '', apellidos: '', telefono: '', email: '',
    // tipo_documento: DNI (8 dig) | CE (Carnet Extranjeria, 9 dig) |
    // Pasaporte (6-12 alfanumerico). El campo `dni` guarda solo el
    // numero/codigo; el tipo viaja aparte para que el backend valide
    // contra el patron correcto y se preserve para futura UI.
    tipo_documento: 'DNI',
    dni: '', campana: '', observaciones: '',
    // V070.10 — paridad con LeadDetalle edit + mobile LeadFormScreen.
    // El backend ya persiste ambos campos en crm.leads desde V020.
    ciudad: '', trabajo: '',
    fuente_id: '', estado_id: '', asesor_id: '', referido_por: '',
    codigo_convenio: '',
    fecha_proxima_gestion: '',
    accion_proxima_gestion: '',
    motivo_perdida: '',
    motivo_perdida_otro: '',
    tipo_cierre: 'Cierre autónomo',
    segunda_voz: '',
  })
  const [segundaVozSelect, setSegundaVozSelect] = useState('')
  const [segundaVozOtro, setSegundaVozOtro] = useState('')
  const [phonePrefix, setPhonePrefix] = useState('+51')
  const [phoneLocal,  setPhoneLocal]  = useState('')
  const [asesores, setAsesores]     = useState([])
  const [campanas, setCampanas]     = useState([])
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError]           = useState(null)
  const [fieldErrors, setFieldErrors] = useState({})

  // V067 — dedupe: state del banner de duplicado detectado.
  // duplicateMatch = null | { id, nombres, apellidos, telefono, email, asesor_nombre, estado_nombre }
  // duplicateField = 'telefono' | 'email' | 'dni' | null
  // overrideActive = true cuando el user hace click "Crear de todos modos"
  const [duplicateMatch,    setDuplicateMatch]    = useState(null)
  const [duplicateField,    setDuplicateField]    = useState(null)
  const [overrideActive,    setOverrideActive]    = useState(false)
  const [overrideReason,    setOverrideReason]    = useState('')
  const dupeCheckTimer = useRef(null)

  // Debounce check-duplicate cuando cambia telefono/email/dni
  const checkDuplicate = (field, value) => {
    if (dupeCheckTimer.current) clearTimeout(dupeCheckTimer.current)
    const v = (value || '').trim()
    if (!v) {
      // Si el campo se vacia, limpiamos cualquier match previo de ese campo
      if (duplicateField === field) {
        setDuplicateMatch(null); setDuplicateField(null); setOverrideActive(false)
      }
      return
    }
    dupeCheckTimer.current = setTimeout(() => {
      const params = new URLSearchParams()
      params.set(field, v)
      api.get(`/api/leads/check-duplicate?${params.toString()}`)
        .then(res => {
          if (res.data?.match) {
            setDuplicateMatch(res.data.match)
            setDuplicateField(res.data.match_field)
            setOverrideActive(false)
          } else if (duplicateField === field) {
            // Si era un match previo del MISMO campo, limpiarlo
            setDuplicateMatch(null); setDuplicateField(null); setOverrideActive(false)
          }
        })
        .catch(() => {})
    }, 500)
  }

  useEffect(() => { loadCatalogs() }, [])

  // Cargar catalogo de campañas para el dropdown. Antes el campo era texto
  // libre, lo que ensuciaba el catalogo (ej. "fb-mayo", "FB Mayo 2026",
  // "FB_mayo26" entrando como tres campañas distintas). Ahora es select
  // del catalogo gestionado en Configuracion → Campañas.
  useEffect(() => {
    api.get('/api/campanas?activos=true')
      .then(res => setCampanas(res.data || []))
      .catch(() => { /* silencioso: el dropdown queda vacio */ })
  }, [])

  useEffect(() => {
    api.get('/auth/users')
      .then(res => {
        // V070.11 — paridad con CRMs profesionales: incluir supervisores
        // ademas de asesores. El backend _resolve_lead_owner ya modela el
        // caso supervisor=owner como "queda en cola del supervisor"
        // (asesor_id=NULL, supervisor_id=ese sup, fecha_entrada_cola=NOW).
        // Admin se excluye intencionalmente — no es semantica limpia.
        // Solo users activos (is_active) para no listar deshabilitados.
        const list = (res.data || [])
          .filter(u =>
            u.is_active !== false &&
            (u.role === 'asesor' || u.role === 'supervisor')
          )
          .map(u => ({
            ...u,
            nombre_completo:
              [u.first_name, u.last_name].filter(Boolean).join(' ') || u.email,
          }))
        setAsesores(list)
      })
      .catch(() => {})
  }, [])

  useEffect(() => {
    if (estados.length > 0 && !form.estado_id) {
      setForm(p => ({ ...p, estado_id: String(estados[0].id) }))
    }
  }, [estados])

  const isReferido = useMemo(() => {
    if (!form.fuente_id) return false
    const fuente = fuentes.find(x => String(x.id) === String(form.fuente_id))
    return fuente?.nombre?.toLowerCase().includes('referid') || false
  }, [form.fuente_id, fuentes])

  const isConvenio = useMemo(() => {
    if (!form.fuente_id) return false
    const fuente = fuentes.find(x => String(x.id) === String(form.fuente_id))
    return fuente?.nombre?.toLowerCase().includes('convenio') || false
  }, [form.fuente_id, fuentes])

  const validate = () => {
    const errors = {}
    if (!form.nombres.trim() && !form.apellidos.trim()) {
      errors.nombres = 'Se requiere al menos nombre o apellido.'
    }
    if (!form.telefono.trim()) {
      errors.telefono = 'El teléfono es requerido.'
    } else {
      const result = normalizePhonePE(form.telefono)
      if (!result.valid) errors.telefono = result.error || 'Número inválido.'
    }
    if (form.email.trim() && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(form.email.trim())) {
      errors.email = 'Formato de email inválido.'
    }
    if (form.dni.trim()) {
      const value = form.dni.trim().toUpperCase()
      if (form.tipo_documento === 'DNI' && !/^\d{8}$/.test(value)) errors.dni = 'DNI debe tener 8 dígitos.'
      else if (form.tipo_documento === 'CE' && !/^\d{9}$/.test(value)) errors.dni = 'CE debe tener 9 dígitos.'
      else if (form.tipo_documento === 'Pasaporte' && !/^[A-Z0-9]{6,12}$/.test(value)) errors.dni = 'Pasaporte inválido.'
    }
    if (!form.fuente_id) errors.fuente_id = 'La fuente es obligatoria.'
    if (isReferido && !form.referido_por.trim()) errors.referido_por = 'Campo obligatorio.'
    if (isConvenio && !form.codigo_convenio.trim()) errors.codigo_convenio = 'Campo obligatorio.'

    const selectedEstadoObj = estados.find(e => String(e.id) === String(form.estado_id))
    const isSeg = isEstadoSeguimiento(selectedEstadoObj?.nombre)
    const isOpor = isEstadoOportunidadFutura(selectedEstadoObj?.nombre)
    const isPerd = isEstadoPerdido(selectedEstadoObj?.nombre)
    const isMatr = isEstadoMatricula(selectedEstadoObj?.nombre)

    if (isSeg && (!form.fecha_proxima_gestion || !form.fecha_proxima_gestion.trim())) {
      errors.fecha_proxima_gestion = 'La fecha y hora de próxima acción es obligatoria.'
    }
    if (isOpor) {
      if (!form.fecha_proxima_gestion || !form.fecha_proxima_gestion.trim()) {
        errors.fecha_proxima_gestion = 'La fecha y hora programada es obligatoria para Oportunidad futura.'
      }
      if (!form.accion_proxima_gestion || !form.accion_proxima_gestion.trim()) {
        errors.accion_proxima_gestion = 'Debe indicar la acción a realizar en esa fecha.'
      }
    }
    if (isPerd) {
      if (!form.motivo_perdida) {
        errors.motivo_perdida = 'Debe seleccionar un motivo de pérdida.'
      } else if (form.motivo_perdida === 'Otro' && (!form.motivo_perdida_otro || !form.motivo_perdida_otro.trim())) {
        errors.motivo_perdida_otro = 'Debe especificar el motivo de pérdida.'
      }
    }
    if (isMatr) {
      const effectiveTipoCierre = form.tipo_cierre || 'Cierre autónomo'
      if (!effectiveTipoCierre) {
        errors.tipo_cierre = 'Debe seleccionar el tipo de cierre.'
      } else if (effectiveTipoCierre === 'Con segunda voz') {
        const finalSegundaVoz = (segundaVozSelect === '__otro__' ? segundaVozOtro : (segundaVozSelect || form.segunda_voz))?.trim()
        if (!finalSegundaVoz) {
          errors.segunda_voz = 'Debe indicar la persona que realizó la segunda voz.'
        }
      }
    }

    return errors
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    const errors = validate()
    if (Object.keys(errors).length > 0) { setFieldErrors(errors); return }
    setFieldErrors({})
    setIsSubmitting(true)
    setError(null)
    try {
      const selectedEstadoObj = estados.find(e => String(e.id) === String(form.estado_id))
      const isSeg = isEstadoSeguimiento(selectedEstadoObj?.nombre)
      const isOpor = isEstadoOportunidadFutura(selectedEstadoObj?.nombre)
      const isPerd = isEstadoPerdido(selectedEstadoObj?.nombre)
      const isMatr = isEstadoMatricula(selectedEstadoObj?.nombre)

      const qs = overrideActive ? `?allow_duplicate=true&duplicate_reason=${encodeURIComponent(overrideReason || '')}` : ''
      const res = await api.post(`/api/leads${qs}`, {
        ...form,
        fuente_id:    form.fuente_id ? parseInt(form.fuente_id) : null,
        estado_id:    form.estado_id ? parseInt(form.estado_id) : undefined,
        asesor_id:    form.asesor_id || null,
        referido_por: form.referido_por || null,
        codigo_convenio: form.codigo_convenio || null,
        fecha_proxima_gestion: (isSeg || isOpor) && form.fecha_proxima_gestion ? new Date(form.fecha_proxima_gestion).toISOString() : null,
        accion_proxima_gestion: isOpor && form.accion_proxima_gestion ? form.accion_proxima_gestion.trim() : null,
        motivo_perdida: isPerd ? (form.motivo_perdida || null) : null,
        motivo_perdida_otro: isPerd && form.motivo_perdida === 'Otro' ? (form.motivo_perdida_otro?.trim() || null) : null,
        tipo_cierre: isMatr ? (form.tipo_cierre || 'Cierre autónomo') : null,
        segunda_voz: isMatr && (form.tipo_cierre === 'Con segunda voz')
          ? ((segundaVozSelect === '__otro__' ? segundaVozOtro : (segundaVozSelect || form.segunda_voz))?.trim() || null)
          : null,
      })
      navigate(`/leads/${res.data.id}`)
    } catch (err) {
      if (err.response?.status === 409) {
        const detail = err.response.data?.detail
        if (detail?.existing_lead) { setDuplicateMatch(detail.existing_lead); setDuplicateField('telefono'); setOverrideActive(false) }
        else setError('Ya existe un lead con estos datos.')
      } else {
        setError(err?.response?.data?.detail || 'Error al crear el lead.')
      }
    } finally { setIsSubmitting(false) }
  }

  const f = (key) => ({ value: form[key], onChange: e => setForm(p => ({ ...p, [key]: e.target.value })) })

  return (
    <div className="max-w-2xl space-y-5">
      <div className="flex items-center gap-3">
        <button
          onClick={() => (window.history.length > 1 ? navigate(-1) : navigate('/leads'))}
          className="p-1.5 rounded-lg hover:bg-gray-100 text-gray-500"
          title="Volver"
        >
          <ArrowLeft size={18} />
        </button>
        <h1 className="text-xl font-bold text-gray-900">Nuevo Lead</h1>
      </div>

      {/* V067: banner de duplicado detectado (patrón estándar style) */}
      {duplicateMatch && (
        <DuplicateBanner
          match={duplicateMatch}
          matchField={duplicateField}
          overrideActive={overrideActive}
          onOverride={(reason) => { setOverrideActive(true); setOverrideReason(reason || '') }}
          onCancelOverride={() => { setOverrideActive(false); setOverrideReason('') }}
          onDismiss={() => { setDuplicateMatch(null); setDuplicateField(null); setOverrideActive(false) }}
        />
      )}

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold text-gray-700">Datos de contacto</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-xs">Nombres</Label>
                <Input {...f('nombres')} className={`mt-1 ${fieldErrors.nombres ? 'border-red-400' : ''}`} />
                {fieldErrors.nombres && <p className="text-xs text-red-500 mt-0.5">{fieldErrors.nombres}</p>}
              </div>
              <div>
                <Label className="text-xs">Apellidos</Label>
                <Input {...f('apellidos')} className="mt-1" />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-xs">Teléfono <span className="text-red-400">*</span></Label>
                <div className="flex mt-1">
                  <input
                    type="text"
                    value={phonePrefix}
                    onChange={e => {
                      // Permite editar el prefijo: solo + y dígitos, máx 4
                      let v = e.target.value.replace(/[^\d+]/g, '').slice(0, 4)
                      if (v && !v.startsWith('+')) v = '+' + v.replace(/\+/g, '')
                      setPhonePrefix(v)
                      setForm(p => ({ ...p, telefono: phoneLocal ? v + phoneLocal : '' }))
                    }}
                    className="w-16 text-center text-sm rounded-l-md border border-r-0 border-gray-200 bg-gray-50 text-gray-700 font-mono focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    title="Código de país (editable)"
                  />
                  <input
                    type="tel"
                    value={phoneLocal}
                    onChange={e => {
                      // Limite duro segun prefijo: PE=9 (caso default).
                      // Para otros países dejamos hasta 11 (Mexico, US).
                      // Antes era 15 y aceptaba 13 dígitos sin error claro.
                      const maxDigits = phonePrefix === '+51' ? 9 : 11
                      const digits = e.target.value.replace(/\D/g, '').slice(0, maxDigits)
                      setPhoneLocal(digits)
                      const fullPhone = digits ? phonePrefix + digits : ''
                      setForm(p => ({ ...p, telefono: fullPhone }))
                      // V067: dispara check-duplicate debounced mientras tipea
                      checkDuplicate('telefono', fullPhone)
                    }}
                    onBlur={() => checkDuplicate('telefono', form.telefono)}
                    placeholder={phonePrefix === '+51' ? '987 654 321' : 'Solo dígitos'}
                    maxLength={phonePrefix === '+51' ? 9 : 11}
                    className={`flex-1 min-w-0 border border-gray-200 rounded-r-md px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 ${fieldErrors.telefono ? 'border-red-400' : ''}`}
                  />
                </div>
                {fieldErrors.telefono && <p className="text-xs text-red-500 mt-0.5">{fieldErrors.telefono}</p>}
              </div>
              <div>
                <Label className="text-xs">Email</Label>
                <Input
                  type="email"
                  value={form.email}
                  onChange={e => setForm(p => ({ ...p, email: e.target.value }))}
                  onBlur={() => checkDuplicate('email', form.email)}
                  placeholder="nombre@dominio.com"
                  className={`mt-1 ${fieldErrors.email ? 'border-red-400' : ''}`}
                />
                {fieldErrors.email && <p className="text-xs text-red-500 mt-0.5">{fieldErrors.email}</p>}
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-xs">Documento</Label>
                {/* Selector de tipo + input. Al cambiar de tipo se limpia
                    el valor para evitar mezclar formatos (digitos de DNI
                    en un campo de Pasaporte, etc). El input se adapta:
                    DNI/CE solo digitos, Pasaporte alfanumerico mayusculas. */}
                <div className="flex mt-1">
                  <select
                    value={form.tipo_documento}
                    onChange={e => setForm(p => ({ ...p, tipo_documento: e.target.value, dni: '' }))}
                    className="text-sm rounded-l-md border border-r-0 border-gray-200 bg-gray-50 text-gray-700 px-2 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                    title="Tipo de documento"
                  >
                    <option value="DNI">DNI</option>
                    <option value="CE">CE</option>
                    <option value="Pasaporte">Pasaporte</option>
                  </select>
                  <Input
                    value={form.dni}
                    inputMode={form.tipo_documento === 'Pasaporte' ? 'text' : 'numeric'}
                    maxLength={
                      form.tipo_documento === 'DNI'
                        ? 8
                        : form.tipo_documento === 'CE'
                          ? 9
                          : 12
                    }
                    placeholder={
                      form.tipo_documento === 'DNI'
                        ? '12345678'
                        : form.tipo_documento === 'CE'
                          ? '001234567'
                          : 'AB123456'
                    }
                    onChange={e => {
                      const raw = e.target.value
                      let cleaned
                      if (form.tipo_documento === 'Pasaporte') {
                        cleaned = raw.toUpperCase().replace(/[^A-Z0-9]/g, '').slice(0, 12)
                      } else if (form.tipo_documento === 'CE') {
                        cleaned = raw.replace(/\D/g, '').slice(0, 9)
                      } else {
                        cleaned = raw.replace(/\D/g, '').slice(0, 8)
                      }
                      setForm(p => ({ ...p, dni: cleaned }))
                    }}
                    onBlur={() => checkDuplicate('dni', form.dni)}
                    className={`flex-1 min-w-0 rounded-l-none rounded-r-md ${fieldErrors.dni ? 'border-red-400' : ''}`}
                  />
                </div>
                {fieldErrors.dni && <p className="text-xs text-red-500 mt-0.5">{fieldErrors.dni}</p>}
              </div>
              <div>
                <Label className="text-xs">Campaña publicitaria</Label>
                {campanas.length > 0 ? (
                  <select
                    value={form.campana}
                    onChange={e => setForm(p => ({ ...p, campana: e.target.value }))}
                    className="w-full mt-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  >
                    <option value="">— Sin campaña —</option>
                    {campanas.map(c => (
                      <option key={c.id} value={c.nombre}>{c.nombre}</option>
                    ))}
                  </select>
                ) : (
                  <Input
                    {...f('campana')}
                    placeholder="Carga campañas en Configuración → Campañas"
                    className="mt-1"
                    disabled
                  />
                )}
                <p className="text-[10px] text-gray-400 mt-0.5">
                  Las campañas se gestionan en Configuración → Pipeline → Campañas.
                </p>
              </div>
            </div>

            {/* V070.10 — Ciudad y Trabajo: campos demograficos opcionales.
                Paridad con LeadDetalle (edit) y mobile LeadFormScreen.
                Ambos campos viajan con el ...form en el POST asi que no
                requieren cambio en el handler de submit. */}
            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-xs">
                  Ciudad <span className="text-gray-400 font-normal">(opcional)</span>
                </Label>
                <Input
                  {...f('ciudad')}
                  placeholder="Ej: Arequipa"
                  className="mt-1"
                />
              </div>
              <div>
                <Label className="text-xs">
                  Trabajo <span className="text-gray-400 font-normal">(opcional)</span>
                </Label>
                <Input
                  {...f('trabajo')}
                  placeholder="Ej: Ingeniero civil"
                  className="mt-1"
                />
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <Label className="text-xs">
                  Fuente <span className="text-red-400">*</span>
                </Label>
                <select
                  {...f('fuente_id')}
                  className={`w-full mt-1 text-sm border rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500 ${
                    fieldErrors.fuente_id ? 'border-red-400' : 'border-gray-200'
                  }`}
                >
                  <option value="">Seleccionar…</option>
                  {fuentes.map(f => (
                    <option key={f.id} value={f.id} className="capitalize">{f.nombre}</option>
                  ))}
                </select>
                {fieldErrors.fuente_id && (
                  <p className="text-xs text-red-500 mt-0.5">{fieldErrors.fuente_id}</p>
                )}
              </div>
              <div>
                <Label className="text-xs">Estado inicial</Label>
                <select
                  value={form.estado_id}
                  onChange={e => {
                    const newEstadoId = e.target.value
                    const targetEst = estados.find(st => String(st.id) === String(newEstadoId))
                    setForm(p => {
                      const next = { ...p, estado_id: newEstadoId }
                      if (isEstadoMatricula(targetEst?.nombre) && !p.tipo_cierre) {
                        next.tipo_cierre = 'Cierre autónomo'
                      }
                      return next
                    })
                    if (fieldErrors.estado_id) setFieldErrors(p => ({ ...p, estado_id: undefined }))
                  }}
                  className="w-full mt-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  {estados.map(e => <option key={e.id} value={e.id}>{e.nombre}</option>)}
                </select>
              </div>
            </div>

            {/* Formulario condicional para En seguimiento */}
            {(() => {
              const selectedEstadoObj = estados.find(e => String(e.id) === String(form.estado_id))
              if (!isEstadoSeguimiento(selectedEstadoObj?.nombre)) return null
              return (
                <div className="p-3.5 bg-blue-50/70 border border-blue-200 rounded-lg space-y-2 animate-in fade-in">
                  <Label className="text-xs font-semibold text-blue-950 flex items-center gap-1.5">
                    <Calendar size={13} className="text-blue-600" />
                    Fecha y hora de próxima acción <span className="text-red-500">*</span>
                  </Label>
                  <Input
                    type="datetime-local"
                    value={form.fecha_proxima_gestion}
                    onChange={e => setForm(p => ({ ...p, fecha_proxima_gestion: e.target.value }))}
                    required
                    className={`bg-white ${fieldErrors.fecha_proxima_gestion ? 'border-red-400' : ''}`}
                  />
                  {fieldErrors.fecha_proxima_gestion && (
                    <p className="text-xs text-red-500">{fieldErrors.fecha_proxima_gestion}</p>
                  )}
                  <p className="text-[10px] text-blue-700">
                    Obligatorio para programar la próxima acción. El sistema emitirá una alerta 1 hora antes al asesor y supervisor.
                  </p>
                </div>
              )
            })()}

            {/* Formulario condicional para Oportunidad Futura */}
            {(() => {
              const selectedEstadoObj = estados.find(e => String(e.id) === String(form.estado_id))
              if (!isEstadoOportunidadFutura(selectedEstadoObj?.nombre)) return null
              return (
                <div className="p-3.5 bg-purple-50/70 border border-purple-200 rounded-lg space-y-2.5 animate-in fade-in">
                  <Label className="text-xs font-semibold text-purple-950 flex items-center gap-1.5">
                    <Calendar size={13} className="text-purple-600" />
                    Fecha y hora de próxima acción <span className="text-red-500">*</span>
                  </Label>
                  <Input
                    type="datetime-local"
                    value={form.fecha_proxima_gestion}
                    onChange={e => setForm(p => ({ ...p, fecha_proxima_gestion: e.target.value }))}
                    required
                    className={`bg-white ${fieldErrors.fecha_proxima_gestion ? 'border-red-400' : ''}`}
                  />
                  {fieldErrors.fecha_proxima_gestion && (
                    <p className="text-xs text-red-500">{fieldErrors.fecha_proxima_gestion}</p>
                  )}

                  <Label className="text-xs font-semibold text-purple-950 flex items-center gap-1.5 pt-1">
                    Acción a realizar <span className="text-red-500">*</span>
                  </Label>
                  <Input
                    type="text"
                    list="acciones-oportunidad-options-nuevo"
                    placeholder="Ej: Llamar para coordinar inicio, enviar oferta por WhatsApp..."
                    value={form.accion_proxima_gestion}
                    onChange={e => setForm(p => ({ ...p, accion_proxima_gestion: e.target.value }))}
                    required
                    className={`bg-white text-xs ${fieldErrors.accion_proxima_gestion ? 'border-red-400' : ''}`}
                  />
                  <datalist id="acciones-oportunidad-options-nuevo">
                    {ACCIONES_OPORTUNIDAD_FUTURA_OPCIONES.filter(opt => opt !== 'Otro').map(opt => (
                      <option key={opt} value={opt} />
                    ))}
                  </datalist>
                  {fieldErrors.accion_proxima_gestion && (
                    <p className="text-xs text-red-500">{fieldErrors.accion_proxima_gestion}</p>
                  )}
                </div>
              )
            })()}

            {/* Formulario condicional para Perdido */}
            {(() => {
              const selectedEstadoObj = estados.find(e => String(e.id) === String(form.estado_id))
              if (!isEstadoPerdido(selectedEstadoObj?.nombre)) return null
              return (
                <div className="p-3.5 bg-rose-50/70 border border-rose-200 rounded-lg space-y-2.5 animate-in fade-in">
                  <Label className="text-xs font-semibold text-rose-950 flex items-center gap-1.5">
                    <AlertCircle size={13} className="text-rose-600" />
                    Motivo de pérdida <span className="text-red-500">*</span>
                  </Label>
                  <select
                    value={form.motivo_perdida}
                    onChange={e => setForm(p => ({ ...p, motivo_perdida: e.target.value }))}
                    className={`w-full text-sm border rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-rose-500 ${
                      fieldErrors.motivo_perdida ? 'border-red-400' : 'border-gray-200'
                    }`}
                  >
                    <option value="">— Seleccionar motivo de pérdida —</option>
                    {MOTIVOS_PERDIDA_OPCIONES.map(m => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                  {fieldErrors.motivo_perdida && (
                    <p className="text-xs text-red-500">{fieldErrors.motivo_perdida}</p>
                  )}

                  {form.motivo_perdida === 'Otro' && (
                    <div className="pt-1">
                      <Label className="text-xs font-semibold text-rose-950">
                        Especifique el motivo <span className="text-red-500">*</span>
                      </Label>
                      <textarea
                        value={form.motivo_perdida_otro}
                        onChange={e => setForm(p => ({ ...p, motivo_perdida_otro: e.target.value }))}
                        rows={2}
                        placeholder="Detalle el motivo específico…"
                        className={`w-full mt-1 text-sm border rounded-md p-2 bg-white focus:outline-none focus:ring-2 focus:ring-rose-500 resize-none ${
                          fieldErrors.motivo_perdida_otro ? 'border-red-400' : 'border-gray-200'
                        }`}
                      />
                      {fieldErrors.motivo_perdida_otro && (
                        <p className="text-xs text-red-500">{fieldErrors.motivo_perdida_otro}</p>
                      )}
                    </div>
                  )}
                </div>
              )
            })()}

            {/* Formulario condicional para Matrícula / Cierre */}
            {(() => {
              const selectedEstadoObj = estados.find(e => String(e.id) === String(form.estado_id))
              if (!isEstadoMatricula(selectedEstadoObj?.nombre)) return null
              const currentTipoCierre = form.tipo_cierre || 'Cierre autónomo'
              return (
                <div className="p-3.5 bg-emerald-50/70 border border-emerald-200 rounded-lg space-y-3 animate-in fade-in">
                  <div className="flex items-center gap-2 text-emerald-950 font-semibold text-xs">
                    <UserCheck size={14} className="text-emerald-600 shrink-0" />
                    <span>Datos de Venta y Cierre</span>
                  </div>

                  <div>
                    <Label className="text-xs font-semibold text-gray-700">
                      Tipo de cierre <span className="text-red-500">*</span>
                    </Label>
                    <div className="grid grid-cols-2 gap-2 mt-1.5">
                      <label
                        className={`flex items-center gap-2 p-2.5 rounded-lg border text-xs cursor-pointer transition-all ${
                          currentTipoCierre === 'Cierre autónomo'
                            ? 'bg-emerald-50 border-emerald-400 font-medium text-emerald-900 shadow-2xs'
                            : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                        }`}
                      >
                        <input
                          type="radio"
                          name="nuevo_lead_tipo_cierre"
                          value="Cierre autónomo"
                          checked={currentTipoCierre === 'Cierre autónomo'}
                          onChange={() => {
                            setForm(p => ({ ...p, tipo_cierre: 'Cierre autónomo' }))
                            if (fieldErrors.tipo_cierre) setFieldErrors(p => ({ ...p, tipo_cierre: undefined }))
                          }}
                          className="text-emerald-600 focus:ring-emerald-500"
                        />
                        <span>Cierre autónomo</span>
                      </label>

                      <label
                        className={`flex items-center gap-2 p-2.5 rounded-lg border text-xs cursor-pointer transition-all ${
                          currentTipoCierre === 'Con segunda voz'
                            ? 'bg-emerald-50 border-emerald-400 font-medium text-emerald-900 shadow-2xs'
                            : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                        }`}
                      >
                        <input
                          type="radio"
                          name="nuevo_lead_tipo_cierre"
                          value="Con segunda voz"
                          checked={currentTipoCierre === 'Con segunda voz'}
                          onChange={() => {
                            setForm(p => ({ ...p, tipo_cierre: 'Con segunda voz' }))
                            if (fieldErrors.tipo_cierre) setFieldErrors(p => ({ ...p, tipo_cierre: undefined }))
                          }}
                          className="text-emerald-600 focus:ring-emerald-500"
                        />
                        <span>Con segunda voz</span>
                      </label>
                    </div>
                    {fieldErrors.tipo_cierre && (
                      <p className="text-xs text-red-500 mt-1">{fieldErrors.tipo_cierre}</p>
                    )}
                  </div>

                  {currentTipoCierre === 'Con segunda voz' && (
                    <div className="pt-1 animate-in fade-in space-y-1.5">
                      <Label className="text-xs font-semibold text-gray-700">
                        Persona que realizó la segunda voz <span className="text-red-500">*</span>
                      </Label>
                      {asesores && asesores.length > 0 ? (
                        <div className="space-y-1.5">
                          <select
                            value={segundaVozSelect}
                            onChange={(e) => {
                              const val = e.target.value
                              setSegundaVozSelect(val)
                              if (val !== '__otro__') {
                                setForm(p => ({ ...p, segunda_voz: val }))
                                setSegundaVozOtro('')
                              } else {
                                setForm(p => ({ ...p, segunda_voz: segundaVozOtro }))
                              }
                              if (fieldErrors.segunda_voz) setFieldErrors(p => ({ ...p, segunda_voz: undefined }))
                            }}
                            className={`w-full text-sm border rounded-md px-2.5 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-emerald-500 ${
                              fieldErrors.segunda_voz ? 'border-red-400' : 'border-gray-200'
                            }`}
                          >
                            <option value="">— Seleccionar usuario / asesor —</option>
                            {asesores.map((u) => {
                              const nombre = u.nombre_completo || `${u.first_name || ''} ${u.last_name || ''}`.trim() || u.username
                              return (
                                <option key={u.id || nombre} value={nombre}>
                                  {nombre} {u.role ? `(${u.role})` : ''}
                                </option>
                              )
                            })}
                            <option value="__otro__">Otro (escribir nombre)…</option>
                          </select>
                          {segundaVozSelect === '__otro__' && (
                            <Input
                              placeholder="Nombre de la persona que realizó la segunda voz"
                              value={segundaVozOtro}
                              onChange={(e) => {
                                const val = e.target.value
                                setSegundaVozOtro(val)
                                setForm(p => ({ ...p, segunda_voz: val }))
                                if (fieldErrors.segunda_voz) setFieldErrors(p => ({ ...p, segunda_voz: undefined }))
                              }}
                              className={`mt-1 bg-white ${fieldErrors.segunda_voz ? 'border-red-400' : ''}`}
                              autoFocus
                            />
                          )}
                        </div>
                      ) : (
                        <Input
                          placeholder="Nombre de la persona que realizó la segunda voz"
                          value={form.segunda_voz}
                          onChange={(e) => {
                            setForm(p => ({ ...p, segunda_voz: e.target.value }))
                            if (fieldErrors.segunda_voz) setFieldErrors(p => ({ ...p, segunda_voz: undefined }))
                          }}
                          className={`mt-1 bg-white ${fieldErrors.segunda_voz ? 'border-red-400' : ''}`}
                        />
                      )}
                      {fieldErrors.segunda_voz && (
                        <p className="text-xs text-red-500 mt-0.5">{fieldErrors.segunda_voz}</p>
                      )}
                    </div>
                  )}
                </div>
              )
            })()}

            {/* Campo condicional para código de convenio cuando la fuente seleccionada es de tipo convenio */}
            {isConvenio && (
              <div>
                <Label className="text-xs">
                  Código de convenio <span className="text-red-400">*</span>
                </Label>
                <Input
                  {...f('codigo_convenio')}
                  placeholder="Ej: CONV-2026 / PNP / MINEDU"
                  className={`mt-1 ${fieldErrors.codigo_convenio ? 'border-red-400' : ''}`}
                />
                {fieldErrors.codigo_convenio && (
                  <p className="text-xs text-red-500 mt-0.5">{fieldErrors.codigo_convenio}</p>
                )}
              </div>
            )}

            <div>
              <Label className="text-xs">
                Referido por{' '}
                {isReferido
                  ? <span className="text-red-400">*</span>
                  : <span className="text-gray-400 font-normal">(opcional)</span>}
              </Label>
              <Input
                {...f('referido_por')}
                placeholder="Nombre de quien refirió al lead"
                className={`mt-1 ${fieldErrors.referido_por ? 'border-red-400' : ''}`}
              />
              {fieldErrors.referido_por && <p className="text-xs text-red-500 mt-0.5">{fieldErrors.referido_por}</p>}
            </div>

            {canAssign && (
              <div>
                <Label className="text-xs">Asignar a</Label>
                {/* V070.11 — optgroup separa asesores (owner directo) de
                    supervisores (queda en su cola). La distincion es
                    importante porque el comportamiento del backend es
                    distinto: a un asesor lo asigna directo; a un
                    supervisor lo mete en cola con fecha_entrada_cola. */}
                <select
                  value={form.asesor_id}
                  onChange={e => setForm(p => ({ ...p, asesor_id: e.target.value }))}
                  className="w-full mt-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  <option value="">Sin asignar</option>
                  {asesores.some(a => a.role === 'asesor') && (
                    <optgroup label="Asesores">
                      {asesores
                        .filter(a => a.role === 'asesor')
                        .map(a => (
                          <option key={a.id} value={a.id}>
                            {a.nombre_completo || a.username}
                          </option>
                        ))}
                    </optgroup>
                  )}
                  {asesores.some(a => a.role === 'supervisor') && (
                    <optgroup label="Supervisores (queda en su cola)">
                      {asesores
                        .filter(a => a.role === 'supervisor')
                        .map(a => (
                          <option key={a.id} value={a.id}>
                            {a.nombre_completo || a.username}
                          </option>
                        ))}
                    </optgroup>
                  )}
                </select>
                <p className="text-[10px] text-gray-400 mt-0.5">
                  Si seleccionas un supervisor el lead queda en su cola para
                  reasignar a un asesor del equipo.
                </p>
              </div>
            )}

            <div>
              <Label className="text-xs">Observaciones</Label>
              <textarea
                {...f('observaciones')}
                rows={3}
                className="w-full mt-1 text-sm border border-gray-200 rounded-md px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
              />
            </div>

            {error && (
              <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded px-3 py-2">
                {error}
              </div>
            )}

            <div className="flex gap-2 justify-end pt-1">
              <Button
                type="button"
                variant="outline"
                onClick={() => (window.history.length > 1 ? navigate(-1) : navigate('/leads'))}
              >
                Cancelar
              </Button>
              <Button type="submit" disabled={isSubmitting} className="gap-1.5">
                <Save size={14} />
                {isSubmitting ? 'Creando…' : 'Crear Lead'}
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  )
}
