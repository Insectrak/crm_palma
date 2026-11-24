import { useState } from 'react'
import { ClipboardList, Edit2, CheckCircle2, AlertCircle, Save, X } from 'lucide-react'
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card'
import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import api from '@/lib/api'
import { FICHA_TECNICA_FIELDS, getFichaTecnicaStats } from '@/lib/fichaTecnica'

export default function FichaTecnicaCard({
  lead,
  canEdit = true,
  isParentEditing = false,
  onSaveSuccess,
}) {
  const currentFicha = lead?.ficha_tecnica || {}
  const [draftFicha, setDraftFicha] = useState(currentFicha)
  const [prevLeadFicha, setPrevLeadFicha] = useState(lead?.ficha_tecnica)
  const [isSelfEditing, setIsSelfEditing] = useState(false)
  const [isSaving, setIsSaving] = useState(false)
  const [error, setError] = useState(null)
  const [successMessage, setSuccessMessage] = useState(null)

  // Sincronizar draft si el lead cambia externamente sin trigger de efecto
  if (lead?.ficha_tecnica !== prevLeadFicha) {
    setPrevLeadFicha(lead?.ficha_tecnica)
    setDraftFicha(lead?.ficha_tecnica || {})
  }

  // Si el componente padre activa el modo de edición global
  const isEditing = isParentEditing || isSelfEditing

  const fichaData = isEditing ? draftFicha : currentFicha
  const stats = getFichaTecnicaStats(fichaData)

  const handleStartEdit = () => {
    setDraftFicha(lead?.ficha_tecnica || {})
    setIsSelfEditing(true)
    setError(null)
  }

  const handleFieldChange = (key, value) => {
    setDraftFicha(prev => ({
      ...prev,
      [key]: value,
    }))
    if (successMessage) setSuccessMessage(null)
  }

  const handleCancel = () => {
    setDraftFicha(lead?.ficha_tecnica || {})
    setIsSelfEditing(false)
    setError(null)
  }

  const handleSave = async (e) => {
    if (e) e.preventDefault()
    setIsSaving(true)
    setError(null)
    setSuccessMessage(null)

    try {
      const payload = {
        ficha_tecnica: fichaData,
      }
      await api.patch(`/api/leads/${lead.id}`, payload)
      setDraftFicha(fichaData)
      setPrevLeadFicha(fichaData)
      setIsSelfEditing(false)
      setSuccessMessage('Ficha técnica guardada correctamente.')
      setTimeout(() => setSuccessMessage(null), 3000)
      if (onSaveSuccess) {
        await onSaveSuccess()
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al guardar la ficha técnica.')
    } finally {
      setIsSaving(false)
    }
  }

  return (
    <Card id="card-ficha-tecnica" className={`transition-all duration-200 ${
      !stats.isComplete
        ? 'border-amber-200 dark:border-amber-800/60 shadow-xs'
        : 'border-emerald-100 dark:border-emerald-900/40'
    }`}>
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between gap-2 flex-wrap">
          <CardTitle className="text-sm font-semibold text-gray-700 dark:text-slate-200 flex items-center gap-2">
            <ClipboardList size={15} className={stats.isComplete ? 'text-emerald-600' : 'text-amber-600'} />
            <span>Ficha técnica</span>
          </CardTitle>

          <div className="flex items-center gap-2">
            {/* Badge de estado de completitud */}
            {stats.isComplete ? (
              <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold bg-emerald-50 text-emerald-700 border border-emerald-200">
                <CheckCircle2 size={12} className="text-emerald-600" />
                Completa ({stats.total}/{stats.total})
              </span>
            ) : stats.completedCount > 0 ? (
              <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold bg-amber-50 text-amber-700 border border-amber-200">
                <AlertCircle size={12} className="text-amber-600" />
                Incompleta ({stats.completedCount}/{stats.total})
              </span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold bg-amber-100 text-amber-800 border border-amber-300">
                <AlertCircle size={12} className="text-amber-700" />
                Pendiente (0/{stats.total})
              </span>
            )}

            {/* Botón de editar rápido en vista de detalle */}
            {canEdit && !isEditing && (
              <Button
                variant="outline"
                size="sm"
                onClick={handleStartEdit}
                className="h-7 text-xs gap-1 text-gray-700 hover:text-indigo-600 border-gray-200"
              >
                <Edit2 size={11} /> Editar ficha
              </Button>
            )}
          </div>
        </div>

        {/* Barra de progreso de llenado */}
        <div className="mt-2.5 space-y-1">
          <div className="flex justify-between items-center text-[11px] text-gray-500">
            <span>Progreso del cuestionario</span>
            <span className="font-medium text-gray-700 dark:text-slate-300">
              {stats.completedCount} de {stats.total} preguntas ({stats.percentage}%)
            </span>
          </div>
          <div className="w-full bg-gray-100 dark:bg-slate-800 rounded-full h-1.5 overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-300 ${
                stats.isComplete
                  ? 'bg-emerald-500'
                  : stats.completedCount > 0
                    ? 'bg-amber-500'
                    : 'bg-gray-300'
              }`}
              style={{ width: `${Math.max(stats.percentage, 5)}%` }}
            />
          </div>
        </div>
      </CardHeader>

      <CardContent className="pt-0 space-y-4">
        {/* Recalco / Alerta cuando la ficha está incompleta */}
        {!stats.isComplete && (
          <div className="p-3 bg-amber-50/80 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800/60 rounded-lg text-xs text-amber-900 dark:text-amber-200 flex items-start gap-2.5">
            <AlertCircle size={16} className="text-amber-600 shrink-0 mt-0.5" />
            <div className="space-y-0.5">
              <p className="font-semibold text-amber-900 dark:text-amber-100">
                Falta información comercial por incluir en la ficha
              </p>
              <p className="text-[11px] text-amber-800 dark:text-amber-300 leading-relaxed">
                Este cuestionario de perfilamiento inmobiliario es fundamental para entender qué lote busca el cliente y concretar la visita o cierre.
                {stats.completedCount === 0
                  ? ' El asesor encargado debe rellenarlo durante la gestión del lead.'
                  : ` Faltan ${stats.total - stats.completedCount} preguntas por responder.`}
              </p>
            </div>
          </div>
        )}

        {/* Mensajes de error / éxito */}
        {error && (
          <div className="p-2.5 bg-red-50 border border-red-200 rounded-md text-xs text-red-700 flex items-center gap-2">
            <AlertCircle size={14} className="shrink-0" />
            <span>{error}</span>
          </div>
        )}
        {successMessage && (
          <div className="p-2.5 bg-emerald-50 border border-emerald-200 rounded-md text-xs text-emerald-700 flex items-center gap-2">
            <CheckCircle2 size={14} className="shrink-0" />
            <span>{successMessage}</span>
          </div>
        )}

        {/* Formulario / Lista de preguntas */}
        {isEditing ? (
          <form onSubmit={handleSave} className="space-y-4">
            <div className="space-y-3.5">
              {FICHA_TECNICA_FIELDS.map((field, idx) => {
                const value = fichaData[field.key] || ''
                const hasValue = Boolean(value.trim())

                return (
                  <div
                    key={field.key}
                    className={`p-3 rounded-lg border transition-colors ${
                      hasValue
                        ? 'border-gray-200 bg-gray-50/40 dark:bg-slate-900/30'
                        : 'border-amber-200/90 bg-amber-50/30 dark:bg-amber-950/20'
                    }`}
                  >
                    <div className="flex items-center justify-between gap-2 mb-1.5">
                      <Label className="text-xs font-bold text-gray-800 dark:text-slate-200 flex items-center gap-1.5">
                        <span className="w-4 h-4 rounded-full bg-indigo-100 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300 text-[10px] flex items-center justify-center font-bold">
                          {idx + 1}
                        </span>
                        {field.label}
                      </Label>
                      {hasValue ? (
                        <span className="text-[10px] text-emerald-600 font-medium flex items-center gap-1">
                          <CheckCircle2 size={11} /> Respondido
                        </span>
                      ) : (
                        <span className="text-[10px] text-amber-700 font-medium bg-amber-100/80 px-1.5 py-0.2 rounded border border-amber-200">
                          Pendiente
                        </span>
                      )}
                    </div>

                    <p className="text-[11px] text-gray-600 dark:text-slate-400 mb-2 italic leading-snug">
                      {field.pregunta}
                    </p>

                    <textarea
                      rows={field.rows || 2}
                      value={value}
                      onChange={e => handleFieldChange(field.key, e.target.value)}
                      placeholder={field.placeholder}
                      className={`w-full rounded-md border p-2 text-xs resize-y bg-white dark:bg-slate-950 text-gray-900 dark:text-slate-100 placeholder:text-gray-400 focus:outline-none focus:ring-1 focus:ring-indigo-500 ${
                        !hasValue ? 'border-amber-300 focus:border-amber-400' : 'border-gray-200 dark:border-slate-800'
                      }`}
                    />
                  </div>
                )
              })}
            </div>

            {/* Botones de acción al editar */}
            <div className="flex items-center justify-end gap-2 pt-2 border-t border-gray-100 dark:border-slate-800">
              {isSelfEditing && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={handleCancel}
                  disabled={isSaving}
                  className="gap-1 text-xs"
                >
                  <X size={12} /> Cancelar
                </Button>
              )}
              <Button
                type="submit"
                size="sm"
                disabled={isSaving}
                className="gap-1.5 text-xs bg-indigo-600 hover:bg-indigo-700 text-white"
              >
                <Save size={12} />
                {isSaving ? 'Guardando...' : 'Guardar Ficha Técnica'}
              </Button>
            </div>
          </form>
        ) : (
          /* Modo de visualización */
          <div className="space-y-3">
            {FICHA_TECNICA_FIELDS.map((field, idx) => {
              const value = (fichaData[field.key] || '').trim()
              const hasValue = Boolean(value)

              return (
                <div
                  key={field.key}
                  className={`p-3 rounded-lg border text-xs ${
                    hasValue
                      ? 'border-gray-100 bg-gray-50/50 dark:bg-slate-900/40'
                      : 'border-dashed border-amber-200 bg-amber-50/20'
                  }`}
                >
                  <div className="flex items-center justify-between gap-2 mb-1">
                    <span className="font-bold text-gray-800 dark:text-slate-200 flex items-center gap-1.5">
                      <span className="w-4 h-4 rounded-full bg-gray-200 dark:bg-slate-800 text-gray-700 dark:text-slate-300 text-[10px] flex items-center justify-center font-bold">
                        {idx + 1}
                      </span>
                      {field.label}
                    </span>
                    {hasValue ? (
                      <span className="text-[10px] text-emerald-600 font-medium">✓ Registrado</span>
                    ) : (
                      <span className="text-[10px] text-amber-700 italic">Pendiente</span>
                    )}
                  </div>

                  <p className="text-[11px] text-gray-500 dark:text-slate-400 mb-1.5 italic">
                    {field.pregunta}
                  </p>

                  <div className="pl-5 pt-0.5">
                    {hasValue ? (
                      <p className="text-gray-800 dark:text-slate-200 whitespace-pre-wrap leading-relaxed font-normal">
                        {value}
                      </p>
                    ) : (
                      <p className="text-amber-800/80 dark:text-amber-400/80 italic text-[11px]">
                        Sin responder — pendiente de registro por el asesor.
                      </p>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
