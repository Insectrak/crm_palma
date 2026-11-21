import { useState, useEffect } from 'react'
import {
  GitMerge, UserCheck, Shield, AlertTriangle, ArrowRight,
  Phone, Mail, IdCard, Calendar, Tag, Megaphone, CheckCircle2,
  Loader, X, FileText, Check, AlertCircle,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import api from '@/lib/api'

function formatDate(iso) {
  if (!iso) return '—'
  try {
    return new Date(iso).toLocaleString('es-PE', {
      timeZone: 'America/Lima',
      day: '2-digit', month: 'short', year: 'numeric',
      hour: '2-digit', minute: '2-digit',
    })
  } catch {
    return String(iso)
  }
}

/**
 * FusionarLeadModal: Modal interactivo para fusionar dos leads con el mismo teléfono.
 * Permite seleccionar qué dueño va a regir y tendrá la autoridad del lead resultante.
 */
export default function FusionarLeadModal({
  currentLead,
  candidateDuplicates = [],
  isOpen,
  onClose,
  onSuccess,
}) {
  const [selectedSecondaryId, setSelectedSecondaryId] = useState(null)
  const [chosenOwnerId, setChosenOwnerId] = useState(null)
  const [notes, setNotes] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState(null)

  // Inicializar lead secundario seleccionado y dueño por defecto
  useEffect(() => {
    if (candidateDuplicates && candidateDuplicates.length > 0) {
      const firstDupe = candidateDuplicates[0]
      setSelectedSecondaryId(firstDupe.id)
      // Por defecto, pre-seleccionar el dueño del lead actual (si existe), o del secundario
      setChosenOwnerId(currentLead?.asesor_id || firstDupe.asesor_id || null)
    }
  }, [candidateDuplicates, currentLead])

  if (!isOpen || !currentLead) return null

  const selectedSecondary =
    candidateDuplicates.find((d) => d.id === selectedSecondaryId) ||
    candidateDuplicates[0] ||
    null

  const currentLeadName =
    currentLead.nombre_completo ||
    [currentLead.nombres, currentLead.apellidos].filter(Boolean).join(' ') ||
    `Lead #${currentLead.id}`

  const secondaryLeadName = selectedSecondary
    ? selectedSecondary.nombre_completo ||
      [selectedSecondary.nombres, selectedSecondary.apellidos].filter(Boolean).join(' ') ||
      `Lead #${selectedSecondary.id}`
    : '—'

  const currentAsesorName = currentLead.asesor_nombre || 'Sin asesor asignado'
  const secondaryAsesorName = selectedSecondary?.asesor_nombre || 'Sin asesor asignado'

  const handleConfirmMerge = async () => {
    if (!selectedSecondary) {
      setError('Debes seleccionar un lead duplicado para fusionar.')
      return
    }

    setIsSubmitting(true)
    setError(null)

    try {
      const res = await api.post(`/api/leads/${currentLead.id}/merge`, {
        secondary_id: selectedSecondary.id,
        chosen_owner_id: chosenOwnerId || undefined,
        notes: notes.trim() || undefined,
      })

      if (onSuccess) {
        onSuccess(res.data)
      }
      onClose()
    } catch (err) {
      setError(
        err.response?.data?.detail ||
          'No se pudo completar la fusión de leads. Intenta nuevamente.'
      )
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-xs animate-in fade-in duration-200">
      <div className="w-full max-w-3xl max-h-[92vh] overflow-y-auto bg-white dark:bg-slate-900 rounded-2xl shadow-2xl border border-gray-200 dark:border-slate-800 flex flex-col">
        {/* Header del modal */}
        <div className="flex items-start justify-between p-5 border-b border-gray-100 dark:border-slate-800 bg-gradient-to-r from-purple-50/70 to-indigo-50/50 dark:from-purple-950/40 dark:to-indigo-950/30 rounded-t-2xl">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-purple-600 text-white flex items-center justify-center shadow-md shrink-0">
              <GitMerge size={20} />
            </div>
            <div>
              <h2 className="text-base font-bold text-gray-900 dark:text-slate-100 flex items-center gap-2">
                Fusión de Leads Duplicados
              </h2>
              <p className="text-xs text-gray-600 dark:text-slate-300 mt-0.5 flex items-center gap-1.5 flex-wrap">
                Mismo número de teléfono:{' '}
                <span className="font-mono font-semibold text-purple-700 dark:text-purple-300 bg-purple-100/80 dark:bg-purple-900/60 px-2 py-0.5 rounded">
                  {currentLead.telefono || '—'}
                </span>
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            disabled={isSubmitting}
            className="text-gray-400 hover:text-gray-600 dark:hover:text-slate-200 p-1 rounded-lg"
          >
            <X size={18} />
          </button>
        </div>

        {/* Contenido */}
        <div className="p-6 space-y-6">
          {error && (
            <div className="p-3.5 rounded-xl bg-red-50 dark:bg-red-950/40 border border-red-200 dark:border-red-900/80 text-xs text-red-800 dark:text-red-300 flex items-start gap-2.5">
              <AlertCircle size={16} className="text-red-600 shrink-0 mt-0.5" />
              <div>
                <p className="font-bold">Error al procesar la fusión</p>
                <p className="mt-0.5">{error}</p>
              </div>
            </div>
          )}

          {/* Selector de duplicado si hay más de 1 */}
          {candidateDuplicates.length > 1 && (
            <div>
              <label className="block text-xs font-bold text-gray-700 dark:text-slate-300 mb-2">
                Selecciona con cuál de los leads duplicados deseas fusionar:
              </label>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {candidateDuplicates.map((cand) => {
                  const candName =
                    cand.nombre_completo ||
                    [cand.nombres, cand.apellidos].filter(Boolean).join(' ') ||
                    `Lead #${cand.id}`
                  const isSel = cand.id === selectedSecondaryId
                  return (
                    <button
                      key={cand.id}
                      type="button"
                      onClick={() => {
                        setSelectedSecondaryId(cand.id)
                        if (chosenOwnerId !== currentLead.asesor_id) {
                          setChosenOwnerId(cand.asesor_id || null)
                        }
                      }}
                      className={`text-left p-3 rounded-xl border text-xs transition-all ${
                        isSel
                          ? 'border-purple-600 bg-purple-50/60 dark:bg-purple-950/40 ring-2 ring-purple-600/20'
                          : 'border-gray-200 dark:border-slate-800 hover:bg-gray-50 dark:hover:bg-slate-800/60'
                      }`}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="font-bold text-gray-900 dark:text-slate-100">
                          ID #{cand.id} · {candName}
                        </span>
                        {isSel && (
                          <span className="text-purple-600 font-bold">✓ Seleccionado</span>
                        )}
                      </div>
                      <p className="text-[11px] text-gray-500 dark:text-slate-400">
                        Asesor: {cand.asesor_nombre || 'Sin asesor'} · Estado:{' '}
                        {cand.estado_nombre || '—'}
                      </p>
                    </button>
                  )
                })}
              </div>
            </div>
          )}

          {/* Comparativa de los dos leads */}
          {selectedSecondary && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {/* Lead Actual (Principal / Conserva ID) */}
              <div className="rounded-xl border border-purple-200 dark:border-purple-900/60 bg-purple-50/20 dark:bg-purple-950/20 p-4 space-y-3">
                <div className="flex items-center justify-between pb-2 border-b border-purple-100 dark:border-purple-900/40">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-purple-700 dark:text-purple-300">
                    Lead Actual (Principal)
                  </span>
                  <span className="text-xs font-mono font-bold text-purple-900 dark:text-purple-200 bg-purple-100 dark:bg-purple-900/60 px-2 py-0.5 rounded">
                    ID #{currentLead.id}
                  </span>
                </div>
                <div>
                  <h3 className="text-sm font-bold text-gray-900 dark:text-slate-100">
                    {currentLeadName}
                  </h3>
                  <p className="text-xs text-gray-500 dark:text-slate-400 mt-0.5">
                    Registrado: {formatDate(currentLead.fecha_ingreso || currentLead.created_at)}
                  </p>
                </div>
                <div className="space-y-1.5 text-xs text-gray-700 dark:text-slate-300">
                  <p className="flex items-center gap-2">
                    <UserCheck size={13} className="text-purple-600" />
                    <span className="text-gray-500">Asesor:</span>
                    <span className="font-semibold text-gray-900 dark:text-slate-100">
                      {currentAsesorName}
                    </span>
                  </p>
                  <p className="flex items-center gap-2">
                    <Tag size={13} className="text-amber-500" />
                    <span className="text-gray-500">Estado:</span>
                    <span className="font-medium">{currentLead.estado_nombre || '—'}</span>
                  </p>
                  <p className="flex items-center gap-2">
                    <Megaphone size={13} className="text-teal-500" />
                    <span className="text-gray-500">Fuente:</span>
                    <span>{currentLead.fuente_nombre || '—'}</span>
                  </p>
                  {currentLead.email && (
                    <p className="flex items-center gap-2">
                      <Mail size={13} className="text-sky-500" />
                      <span className="text-gray-500">Email:</span>
                      <span className="truncate">{currentLead.email}</span>
                    </p>
                  )}
                  {currentLead.dni && (
                    <p className="flex items-center gap-2">
                      <IdCard size={13} className="text-slate-500" />
                      <span className="text-gray-500">DNI/Doc:</span>
                      <span>{currentLead.dni}</span>
                    </p>
                  )}
                </div>
              </div>

              {/* Lead Duplicado (Secundario a ser absorbido) */}
              <div className="rounded-xl border border-indigo-200 dark:border-indigo-900/60 bg-indigo-50/20 dark:bg-indigo-950/20 p-4 space-y-3">
                <div className="flex items-center justify-between pb-2 border-b border-indigo-100 dark:border-indigo-900/40">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-indigo-700 dark:text-indigo-300">
                    Lead Duplicado (Absorbido)
                  </span>
                  <span className="text-xs font-mono font-bold text-indigo-900 dark:text-indigo-200 bg-indigo-100 dark:bg-indigo-900/60 px-2 py-0.5 rounded">
                    ID #{selectedSecondary.id}
                  </span>
                </div>
                <div>
                  <h3 className="text-sm font-bold text-gray-900 dark:text-slate-100">
                    {secondaryLeadName}
                  </h3>
                  <p className="text-xs text-gray-500 dark:text-slate-400 mt-0.5">
                    Registrado: {formatDate(selectedSecondary.fecha_ingreso || selectedSecondary.created_at)}
                  </p>
                </div>
                <div className="space-y-1.5 text-xs text-gray-700 dark:text-slate-300">
                  <p className="flex items-center gap-2">
                    <UserCheck size={13} className="text-indigo-600" />
                    <span className="text-gray-500">Asesor:</span>
                    <span className="font-semibold text-gray-900 dark:text-slate-100">
                      {secondaryAsesorName}
                    </span>
                  </p>
                  <p className="flex items-center gap-2">
                    <Tag size={13} className="text-amber-500" />
                    <span className="text-gray-500">Estado:</span>
                    <span className="font-medium">{selectedSecondary.estado_nombre || '—'}</span>
                  </p>
                  <p className="flex items-center gap-2">
                    <Megaphone size={13} className="text-teal-500" />
                    <span className="text-gray-500">Fuente:</span>
                    <span>{selectedSecondary.fuente_nombre || '—'}</span>
                  </p>
                  {selectedSecondary.email && (
                    <p className="flex items-center gap-2">
                      <Mail size={13} className="text-sky-500" />
                      <span className="text-gray-500">Email:</span>
                      <span className="truncate">{selectedSecondary.email}</span>
                    </p>
                  )}
                  {selectedSecondary.dni && (
                    <p className="flex items-center gap-2">
                      <IdCard size={13} className="text-slate-500" />
                      <span className="text-gray-500">DNI/Doc:</span>
                      <span>{selectedSecondary.dni}</span>
                    </p>
                  )}
                </div>
              </div>
            </div>
          )}

          {/* SELECCIÓN OBLIGATORIA DEL DUEÑO CON AUTORIDAD */}
          <div className="rounded-xl border border-amber-200 dark:border-amber-800/80 bg-amber-50/40 dark:bg-amber-950/30 p-4 space-y-3">
            <div className="flex items-center gap-2">
              <Shield size={16} className="text-amber-600 dark:text-amber-400" />
              <h4 className="text-xs font-bold uppercase tracking-wider text-amber-950 dark:text-amber-200">
                Elección de Dueño con Autoridad sobre el Lead Fusionado
              </h4>
            </div>
            <p className="text-xs text-amber-900 dark:text-amber-300">
              Debes elegir cuál de los dos asesores regirá y tendrá la autoridad y responsabilidad
              de gestión del lead resultante:
            </p>

            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 pt-1">
              {/* Opción 1: Dueño del Lead Actual */}
              <label
                className={`relative flex items-start gap-3 p-3.5 rounded-xl border cursor-pointer transition-all ${
                  chosenOwnerId === currentLead.asesor_id
                    ? 'border-amber-500 bg-white dark:bg-slate-900 shadow-xs ring-2 ring-amber-500/20'
                    : 'border-amber-200 dark:border-amber-900/60 bg-white/70 dark:bg-slate-900/60 hover:bg-white'
                }`}
              >
                <input
                  type="radio"
                  name="chosen_owner"
                  value={currentLead.asesor_id || ''}
                  checked={chosenOwnerId === currentLead.asesor_id}
                  onChange={() => setChosenOwnerId(currentLead.asesor_id || null)}
                  className="mt-0.5 text-amber-600 focus:ring-amber-500"
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 font-bold text-xs text-gray-900 dark:text-slate-100">
                    <span>Dueño Lead #{currentLead.id}</span>
                  </div>
                  <p className="text-sm font-bold text-amber-900 dark:text-amber-300 mt-0.5 truncate">
                    {currentAsesorName}
                  </p>
                  <p className="text-[11px] text-gray-500 dark:text-slate-400 mt-1">
                    Mantiene a {currentAsesorName} como el asesor asignado a cargo.
                  </p>
                </div>
              </label>

              {/* Opción 2: Dueño del Lead Duplicado */}
              <label
                className={`relative flex items-start gap-3 p-3.5 rounded-xl border cursor-pointer transition-all ${
                  selectedSecondary && chosenOwnerId === selectedSecondary.asesor_id
                    ? 'border-amber-500 bg-white dark:bg-slate-900 shadow-xs ring-2 ring-amber-500/20'
                    : 'border-amber-200 dark:border-amber-900/60 bg-white/70 dark:bg-slate-900/60 hover:bg-white'
                }`}
              >
                <input
                  type="radio"
                  name="chosen_owner"
                  value={selectedSecondary?.asesor_id || ''}
                  checked={selectedSecondary && chosenOwnerId === selectedSecondary.asesor_id}
                  onChange={() => setChosenOwnerId(selectedSecondary?.asesor_id || null)}
                  className="mt-0.5 text-amber-600 focus:ring-amber-500"
                />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5 font-bold text-xs text-gray-900 dark:text-slate-100">
                    <span>Dueño Lead #{selectedSecondary?.id}</span>
                  </div>
                  <p className="text-sm font-bold text-amber-900 dark:text-amber-300 mt-0.5 truncate">
                    {secondaryAsesorName}
                  </p>
                  <p className="text-[11px] text-gray-500 dark:text-slate-400 mt-1">
                    Otorga la autoridad a {secondaryAsesorName} para continuar el seguimiento.
                  </p>
                </div>
              </label>
            </div>
          </div>

          {/* Resumen de efectos de la fusión */}
          <div className="p-3.5 rounded-xl bg-gray-50 dark:bg-slate-800/60 border border-gray-200/80 dark:border-slate-700/60 text-xs text-gray-600 dark:text-slate-300 space-y-1.5">
            <p className="font-bold text-gray-900 dark:text-slate-100 flex items-center gap-1.5">
              <CheckCircle2 size={14} className="text-emerald-600" /> ¿Qué ocurrirá durante la fusión?
            </p>
            <ul className="list-disc pl-5 space-y-1 text-[11px] text-gray-600 dark:text-slate-400">
              <li>Los datos de contacto (email, DNI, ciudad, etc.) se completarán de forma unificada.</li>
              <li>Todas las llamadas, notas, citas e interacciones del lead #{selectedSecondary?.id} se migrarán a este lead.</li>
              <li>El lead #{selectedSecondary?.id} quedará inactivo con referencia de fusión para auditoría.</li>
              <li>Se registrará el evento en el historial de cambios y se colocará un aviso permanente en la ficha.</li>
            </ul>
          </div>

          {/* Notas opcionales */}
          <div>
            <label className="block text-xs font-semibold text-gray-700 dark:text-slate-300 mb-1">
              Notas o motivo de la fusión (opcional):
            </label>
            <input
              type="text"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Ej: Fusión por duplicado de número de WhatsApp / mismo cliente"
              maxLength={255}
              className="w-full text-xs rounded-lg border border-gray-300 dark:border-slate-700 bg-white dark:bg-slate-800 px-3 py-2 text-gray-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-purple-500"
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 p-4 border-t border-gray-100 dark:border-slate-800 bg-gray-50 dark:bg-slate-900/60 rounded-b-2xl">
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={onClose}
            disabled={isSubmitting}
            className="text-xs"
          >
            Cancelar
          </Button>
          <Button
            type="button"
            size="sm"
            onClick={handleConfirmMerge}
            disabled={isSubmitting || !selectedSecondary}
            className="gap-2 text-xs bg-purple-600 hover:bg-purple-700 text-white font-semibold"
          >
            {isSubmitting ? (
              <>
                <Loader size={14} className="animate-spin" /> Fusionando leads...
              </>
            ) : (
              <>
                <GitMerge size={14} /> Confirmar y Fusionar Leads
              </>
            )}
          </Button>
        </div>
      </div>
    </div>
  )
}

