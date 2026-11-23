import { useState, useEffect } from 'react'
import { Dialog, DialogHeader, DialogContent } from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Input } from '@/components/ui/input'
import { Calendar, AlertCircle, Lock, UserCheck, CheckCircle2, Clock, Sparkles } from 'lucide-react'
import useAuthStore from '@/store/authStore'

export const MOTIVOS_PERDIDA_OPCIONES = [
  'No interesado',
  'Precio / falta de capacidad económica',
  'No califica para financiamiento / crédito',
  'Ubicación / proyecto no se ajusta',
  'Horarios / no se ajusta a sus tiempos',
  'Prefiere a la competencia',
  'No contactar más',
  'Otro',
]

export const ACCIONES_OPORTUNIDAD_FUTURA_OPCIONES = [
  'Llamar para coordinar visita / cierre',
  'Contactar por WhatsApp con promoción / bono',
  'Volver a contactar en nueva etapa / lanzamiento',
  'Reevaluar interés y capacidad de financiamiento',
  'Enviar información actualizada / catálogo',
  'Otro',
]

/**
 * Normaliza texto para comparaciones de estado agnósticas a tildes/mayúsculas.
 */
export function normalizeEstadoNombre(str) {
  if (!str) return ''
  return str
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .trim()
}

export function isEstadoSeguimiento(estadoNombre) {
  const norm = normalizeEstadoNombre(estadoNombre)
  return norm.includes('seguimiento') || norm.includes('negociacion') || norm.includes('visita')
}

export function isEstadoPerdido(estadoNombre) {
  const norm = normalizeEstadoNombre(estadoNombre)
  return norm.includes('perdid') || norm.includes('no interesado') || norm.includes('desist') || norm.includes('descart')
}

export function isEstadoMatricula(estadoNombre) {
  const norm = normalizeEstadoNombre(estadoNombre)
  return norm.includes('matricula') || norm.includes('ganad') || norm.includes('cierr') || norm.includes('venta concretad')
}

export function isEstadoOportunidadFutura(estadoNombre) {
  const norm = normalizeEstadoNombre(estadoNombre)
  return norm.includes('oportunidad') || (norm.includes('futur') && !norm.includes('pasad'))
}

/**
 * Obtiene la lista de subestados disponibles según el nombre del estado principal.
 * Si el estado no cuenta con subestados, devuelve un arreglo vacío.
 */
export function getSubestadosForEstado(estadoNombre) {
  if (!estadoNombre) return []
  const norm = normalizeEstadoNombre(estadoNombre)

  if (norm.includes('perdid') || norm.includes('no interesado') || norm.includes('desist') || norm.includes('descart')) {
    return MOTIVOS_PERDIDA_OPCIONES
  }
  if (norm.includes('matr') || norm.includes('ganad') || norm.includes('cierr') || norm.includes('venta concretad')) {
    return ['Cierre autónomo', 'Con segunda voz']
  }
  if (norm.includes('oportunidad') || (norm.includes('futur') && !norm.includes('pasad'))) {
    return ACCIONES_OPORTUNIDAD_FUTURA_OPCIONES
  }
  return []
}

/**
 * Determina si un estado requiere modal con formulario específico.
 */
export function requiresFormularioEspecifico(estadoNombre) {
  return (
    isEstadoSeguimiento(estadoNombre) ||
    isEstadoPerdido(estadoNombre) ||
    isEstadoMatricula(estadoNombre) ||
    isEstadoOportunidadFutura(estadoNombre)
  )
}

export default function CambioEstadoModal({
  open,
  onClose,
  lead,
  targetEstado,
  onConfirm,
  users = [],
}) {
  const { user } = useAuthStore()

  const estadoNombre = targetEstado?.nombre || ''
  const isSeguimiento = isEstadoSeguimiento(estadoNombre)
  const isPerdido = isEstadoPerdido(estadoNombre)
  const isMatricula = isEstadoMatricula(estadoNombre)
  const isOportunidadFutura = isEstadoOportunidadFutura(estadoNombre)

  // Form states
  const [fechaProximaGestion, setFechaProximaGestion] = useState('')
  const [accionOportunidad, setAccionOportunidad] = useState('')
  const [accionOportunidadOtro, setAccionOportunidadOtro] = useState('')
  const [motivoPerdida, setMotivoPerdida] = useState('')
  const [motivoPerdidaOtro, setMotivoPerdidaOtro] = useState('')
  const [tipoCierre, setTipoCierre] = useState('Cierre autónomo')
  const [segundaVoz, setSegundaVoz] = useState('')
  const [segundaVozOtro, setSegundaVozOtro] = useState('')

  const [error, setError] = useState(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  // Inicializar campos con los datos previos del lead cuando abre el modal
  useEffect(() => {
    if (!open) return
    setError(null)
    setIsSubmitting(false)

    // Formatear fecha próxima gestión si existe en lead (ISO -> YYYY-MM-DDTHH:mm)
    if (lead?.fecha_proxima_gestion) {
      try {
        const d = new Date(lead.fecha_proxima_gestion)
        if (!isNaN(d.getTime())) {
          const tzOffset = d.getTimezoneOffset() * 60000
          const localIso = new Date(d.getTime() - tzOffset).toISOString().slice(0, 16)
          setFechaProximaGestion(localIso)
        } else {
          setFechaProximaGestion('')
        }
      } catch {
        setFechaProximaGestion('')
      }
    } else {
      // Default: sugerir mañana a las 10:00 AM
      const d = new Date()
      d.setDate(d.getDate() + 1)
      d.setHours(10, 0, 0, 0)
      const tzOffset = d.getTimezoneOffset() * 60000
      const localIso = new Date(d.getTime() - tzOffset).toISOString().slice(0, 16)
      setFechaProximaGestion(localIso)
    }

    if (lead?.accion_proxima_gestion) {
      if (ACCIONES_OPORTUNIDAD_FUTURA_OPCIONES.includes(lead.accion_proxima_gestion)) {
        setAccionOportunidad(lead.accion_proxima_gestion)
        setAccionOportunidadOtro('')
      } else {
        setAccionOportunidad('Otro')
        setAccionOportunidadOtro(lead.accion_proxima_gestion)
      }
    } else {
      setAccionOportunidad('')
      setAccionOportunidadOtro('')
    }

    setMotivoPerdida(lead?.motivo_perdida || '')
    setMotivoPerdidaOtro(lead?.motivo_perdida_otro || '')
    setTipoCierre(lead?.tipo_cierre || 'Cierre autónomo')

    if (lead?.segunda_voz) {
      const matched = users.some(u => {
        const n = u.nombre_completo || `${u.first_name || ''} ${u.last_name || ''}`.trim() || u.username
        return n === lead.segunda_voz
      })
      if (matched || users.length === 0) {
        setSegundaVoz(lead.segunda_voz)
        setSegundaVozOtro('')
      } else {
        setSegundaVoz('__otro__')
        setSegundaVozOtro(lead.segunda_voz)
      }
    } else {
      setSegundaVoz('')
      setSegundaVozOtro('')
    }
  }, [open, lead, targetEstado, users])

  const handleSubmit = async (e) => {
    if (e) e.preventDefault()
    setError(null)

    const payload = {
      estado_id: targetEstado.id,
    }

    // 1. Validaciones En seguimiento
    if (isSeguimiento) {
      if (!fechaProximaGestion || !fechaProximaGestion.trim()) {
        setError('La fecha y hora de próxima gestión es obligatoria para el estado En seguimiento.')
        return
      }
      payload.fecha_proxima_gestion = new Date(fechaProximaGestion).toISOString()
    }

    // 2. Validaciones Oportunidad Futura
    if (isOportunidadFutura) {
      if (!fechaProximaGestion || !fechaProximaGestion.trim()) {
        setError('La fecha y hora programada es obligatoria para el estado Oportunidad futura.')
        return
      }
      payload.fecha_proxima_gestion = new Date(fechaProximaGestion).toISOString()

      if (!accionOportunidad) {
        setError('Debe seleccionar la acción a realizar en esa fecha.')
        return
      }
      if (accionOportunidad === 'Otro') {
        if (!accionOportunidadOtro || !accionOportunidadOtro.trim()) {
          setError('Debe especificar la acción a realizar en el campo de texto.')
          return
        }
        payload.accion_proxima_gestion = accionOportunidadOtro.trim()
      } else {
        payload.accion_proxima_gestion = accionOportunidad
      }
    }

    // 2. Validaciones Perdido
    if (isPerdido) {
      if (!motivoPerdida) {
        setError('Debe seleccionar un motivo de pérdida.')
        return
      }
      payload.motivo_perdida = motivoPerdida
      if (motivoPerdida === 'Otro') {
        if (!motivoPerdidaOtro || !motivoPerdidaOtro.trim()) {
          setError('Debe digitar el motivo específico en el campo de texto libre.')
          return
        }
        payload.motivo_perdida_otro = motivoPerdidaOtro.trim()
      } else {
        payload.motivo_perdida_otro = null
      }
    }

    // 3. Validaciones Matrícula
    if (isMatricula) {
      if (!tipoCierre) {
        setError('Debe seleccionar el tipo de cierre de forma obligatoria.')
        return
      }
      payload.tipo_cierre = tipoCierre
      if (tipoCierre === 'Con segunda voz') {
        const finalSegundaVoz = (segundaVoz === '__otro__' ? segundaVozOtro : segundaVoz)?.trim()
        if (!finalSegundaVoz) {
          setError('Debe indicar la persona que realizó la segunda voz.')
          return
        }
        payload.segunda_voz = finalSegundaVoz
      } else {
        payload.segunda_voz = null
      }
    }

    setIsSubmitting(true)
    try {
      await onConfirm(payload)
      onClose()
    } catch (err) {
      setError(err?.response?.data?.detail || err?.message || 'Error al actualizar el estado.')
    } finally {
      setIsSubmitting(false)
    }
  }

  if (!open || !targetEstado) return null

  return (
    <Dialog open={open} onClose={onClose} size="md">
      <DialogHeader onClose={onClose}>
        <div className="flex items-center gap-2">
          <span
            className="w-3 h-3 rounded-full shrink-0"
            style={{ backgroundColor: targetEstado.color_hex || '#6366f1' }}
          />
          <span>Cambiar estado a <strong className="text-gray-900">{estadoNombre}</strong></span>
        </div>
      </DialogHeader>

      <DialogContent>
        <form onSubmit={handleSubmit} className="space-y-4 pt-2">
          {lead && (
            <div className="p-3 bg-gray-50 border border-gray-100 rounded-xl flex items-center justify-between text-xs text-gray-600">
              <div>
                <span className="text-gray-400 block text-[11px]">Lead seleccionado:</span>
                <span className="font-semibold text-gray-800 text-sm">
                  {lead.nombre_completo || lead.nombres || `Lead #${lead.id}`}
                </span>
              </div>
              {lead.telefono && (
                <span className="font-mono text-gray-500 bg-white px-2 py-1 rounded border border-gray-200">
                  {lead.telefono}
                </span>
              )}
            </div>
          )}

          {/* ═════════════════ FORMULARIO: EN SEGUIMIENTO ═════════════════ */}
          {isSeguimiento && (
            <div className="space-y-3 bg-blue-50/50 border border-blue-100 rounded-xl p-4">
              <div className="flex items-center gap-2 text-blue-900 font-medium text-sm">
                <Calendar size={16} className="text-blue-600" />
                <span>Programación de Próxima Acción</span>
              </div>
              <p className="text-xs text-blue-700">
                Es obligatorio registrar la fecha y hora exacta en la que se realizará el próximo contacto. El sistema enviará una alerta 1 hora antes.
              </p>
              <div>
                <Label className="text-xs font-semibold text-gray-700">
                  Fecha y hora de próxima acción <span className="text-red-500">*</span>
                </Label>
                <Input
                  type="datetime-local"
                  value={fechaProximaGestion}
                  onChange={(e) => setFechaProximaGestion(e.target.value)}
                  required
                  className="mt-1 bg-white"
                />
              </div>
            </div>
          )}

          {/* ═════════════════ FORMULARIO: OPORTUNIDAD FUTURA ═════════════════ */}
          {isOportunidadFutura && (
            <div className="space-y-3 bg-purple-50/50 border border-purple-100 rounded-xl p-4">
              <div className="flex items-center gap-2 text-purple-900 font-medium text-sm">
                <Calendar size={16} className="text-purple-600" />
                <span>Programación de Oportunidad Futura</span>
              </div>
              <p className="text-xs text-purple-700">
                Indique la fecha/hora en la que se debe retomar el contacto y la acción específica a realizar en esa fecha.
              </p>

              <div>
                <Label className="text-xs font-semibold text-gray-700">
                  Fecha y hora de próxima acción <span className="text-red-500">*</span>
                </Label>
                <Input
                  type="datetime-local"
                  value={fechaProximaGestion}
                  onChange={(e) => setFechaProximaGestion(e.target.value)}
                  required
                  className="mt-1 bg-white"
                />
              </div>

              <div>
                <Label className="text-xs font-semibold text-gray-700">
                  Acción a realizar en esa fecha <span className="text-red-500">*</span>
                </Label>
                <select
                  value={accionOportunidad}
                  onChange={(e) => {
                    setAccionOportunidad(e.target.value)
                    if (e.target.value !== 'Otro') setAccionOportunidadOtro('')
                  }}
                  required
                  className="w-full mt-1 text-sm border border-gray-300 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-purple-500"
                >
                  <option value="">— Seleccionar acción a realizar —</option>
                  {ACCIONES_OPORTUNIDAD_FUTURA_OPCIONES.map((opt) => (
                    <option key={opt} value={opt}>
                      {opt}
                    </option>
                  ))}
                </select>
              </div>

              {accionOportunidad === 'Otro' && (
                <div className="pt-1 animate-in fade-in">
                  <Label className="text-xs font-semibold text-gray-700">
                    Especifique la acción <span className="text-red-500">*</span>
                  </Label>
                  <textarea
                    value={accionOportunidadOtro}
                    onChange={(e) => setAccionOportunidadOtro(e.target.value)}
                    rows={2}
                    placeholder="Describa brevemente la acción a realizar…"
                    required
                    className="w-full mt-1 text-sm border border-gray-300 rounded-lg p-2.5 bg-white focus:outline-none focus:ring-2 focus:ring-purple-500 resize-none"
                  />
                </div>
              )}
            </div>
          )}

          {/* ═════════════════ FORMULARIO: PERDIDO ═════════════════ */}
          {isPerdido && (
            <div className="space-y-3 bg-rose-50/50 border border-rose-100 rounded-xl p-4">
              <div className="flex items-center gap-2 text-rose-900 font-medium text-sm">
                <AlertCircle size={16} className="text-rose-600" />
                <span>Motivo de Pérdida</span>
              </div>
              <p className="text-xs text-rose-700">
                Seleccione el motivo principal por el cual se descarta o pierde la oportunidad.
              </p>
              <div>
                <Label className="text-xs font-semibold text-gray-700">
                  Motivo de pérdida <span className="text-red-500">*</span>
                </Label>
                <select
                  value={motivoPerdida}
                  onChange={(e) => setMotivoPerdida(e.target.value)}
                  required
                  className="w-full mt-1 text-sm border border-gray-300 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-rose-500"
                >
                  <option value="">— Seleccionar motivo —</option>
                  {MOTIVOS_PERDIDA_OPCIONES.map((m) => (
                    <option key={m} value={m}>
                      {m}
                    </option>
                  ))}
                  {motivoPerdida && !MOTIVOS_PERDIDA_OPCIONES.includes(motivoPerdida) && (
                    <option key={motivoPerdida} value={motivoPerdida}>
                      {motivoPerdida} (actual)
                    </option>
                  )}
                </select>
              </div>

              {motivoPerdida === 'Otro' && (
                <div className="pt-2 animate-in fade-in">
                  <Label className="text-xs font-semibold text-gray-700">
                    Especifique el motivo <span className="text-red-500">*</span>
                  </Label>
                  <textarea
                    value={motivoPerdidaOtro}
                    onChange={(e) => setMotivoPerdidaOtro(e.target.value)}
                    rows={2}
                    placeholder="Describa brevemente la razón de pérdida…"
                    required
                    className="w-full mt-1 text-sm border border-gray-300 rounded-lg p-2.5 bg-white focus:outline-none focus:ring-2 focus:ring-rose-500 resize-none"
                  />
                </div>
              )}
            </div>
          )}

          {/* ═════════════════ FORMULARIO: MATRÍCULA ═════════════════ */}
          {isMatricula && (
            <div className="space-y-3 bg-emerald-50/50 border border-emerald-100 rounded-xl p-4">
              <div className="flex items-center gap-2 text-emerald-900 font-medium text-sm">
                <UserCheck size={16} className="text-emerald-600" />
                <span>Datos de Venta y Cierre</span>
              </div>

              <div>
                <Label className="text-xs font-semibold text-gray-700">
                  Tipo de cierre <span className="text-red-500">*</span>
                </Label>
                <div className="grid grid-cols-2 gap-2 mt-1.5">
                      <label
                        className={`flex items-center gap-2 p-2.5 rounded-lg border text-xs cursor-pointer transition-all ${
                          tipoCierre === 'Cierre autónomo'
                            ? 'bg-emerald-50 border-emerald-400 font-medium text-emerald-900 shadow-sm'
                            : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                        }`}
                      >
                        <input
                          type="radio"
                          name="tipo_cierre"
                          value="Cierre autónomo"
                          checked={tipoCierre === 'Cierre autónomo'}
                          onChange={() => setTipoCierre('Cierre autónomo')}
                          className="text-emerald-600 focus:ring-emerald-500"
                        />
                        <span>Cierre autónomo</span>
                      </label>

                      <label
                        className={`flex items-center gap-2 p-2.5 rounded-lg border text-xs cursor-pointer transition-all ${
                          tipoCierre === 'Con segunda voz'
                            ? 'bg-emerald-50 border-emerald-400 font-medium text-emerald-900 shadow-sm'
                            : 'bg-white border-gray-200 text-gray-700 hover:bg-gray-50'
                        }`}
                      >
                        <input
                          type="radio"
                          name="tipo_cierre"
                          value="Con segunda voz"
                          checked={tipoCierre === 'Con segunda voz'}
                          onChange={() => setTipoCierre('Con segunda voz')}
                          className="text-emerald-600 focus:ring-emerald-500"
                        />
                        <span>Con segunda voz</span>
                      </label>
                    </div>
                  </div>

                  {tipoCierre === 'Con segunda voz' && (
                    <div className="pt-2 animate-in fade-in">
                      <Label className="text-xs font-semibold text-gray-700">
                        Persona que realizó la segunda voz <span className="text-red-500">*</span>
                      </Label>
                      {users.length > 0 ? (
                        <div className="space-y-1.5 mt-1">
                          <select
                            value={segundaVoz}
                            onChange={(e) => {
                              setSegundaVoz(e.target.value)
                              if (e.target.value !== '__otro__') setSegundaVozOtro('')
                            }}
                            required
                            className="w-full text-sm border border-gray-300 rounded-lg px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-emerald-500"
                          >
                            <option value="">— Seleccionar usuario / asesor —</option>
                            {users.map((u) => {
                              const nombre = u.nombre_completo || `${u.first_name || ''} ${u.last_name || ''}`.trim() || u.username
                              return (
                                <option key={u.id || nombre} value={nombre}>
                                  {nombre} {u.role ? `(${u.role})` : ''}
                                </option>
                              )
                            })}
                            <option value="__otro__">Otro (escribir nombre)…</option>
                          </select>
                          {segundaVoz === '__otro__' && (
                            <Input
                              placeholder="Nombre de la persona que realizó la segunda voz"
                              value={segundaVozOtro}
                              onChange={(e) => setSegundaVozOtro(e.target.value)}
                              className="mt-1 bg-white"
                              autoFocus
                            />
                          )}
                        </div>
                      ) : (
                        <Input
                          placeholder="Nombre de la persona que realizó la segunda voz"
                          value={segundaVoz}
                          onChange={(e) => setSegundaVoz(e.target.value)}
                          required
                          className="mt-1 bg-white"
                        />
                      )}
                    </div>
                  )}
            </div>
          )}

          {error && (
            <div className="p-3 bg-red-50 border border-red-200 text-red-700 text-xs rounded-xl flex items-start gap-2 animate-in fade-in">
              <AlertCircle size={14} className="shrink-0 mt-0.5" />
              <span>{error}</span>
            </div>
          )}

          <div className="flex items-center justify-end gap-2.5 pt-2 border-t border-gray-100">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={onClose}
              disabled={isSubmitting}
            >
              Cancelar
            </Button>
            <Button
              type="submit"
              size="sm"
              disabled={isSubmitting}
              className="gap-1.5"
              style={{
                backgroundColor: targetEstado.color_hex || '#4f46e5',
                borderColor: targetEstado.color_hex || '#4f46e5',
              }}
            >
              {isSubmitting ? (
                'Guardando…'
              ) : (
                <>
                  <CheckCircle2 size={14} />
                  Confirmar estado
                </>
              )}
            </Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  )
}
