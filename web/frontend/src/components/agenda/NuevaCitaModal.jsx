/**
 * NuevaCitaModal — modal para crear una cita desde el header de la Agenda.
 *
 * V096.2.1 — Paridad con mobile NuevaCitaScreen. En mobile el asesor abre
 * la agenda y aprieta "+" para crear una cita sin tener que entrar a un
 * lead primero. En web ese flujo no existia: habia que ir a Leads, abrir
 * el detalle, click "Agendar cita". 3 pasos vs 1.
 *
 * Flujo:
 *   1. Typeahead de lead (debounce 300ms, busca por nombre o telefono)
 *   2. Fecha + hora del compromiso
 *   3. Tipo de contacto (catalogo)
 *   4. Notas opcionales
 *   5. POST /api/leads/{leadId}/contactos con resultado='cita_agendada'
 *
 * Defaults inteligentes (igual que mobile NuevaCitaScreen):
 *   - Fecha = hoy
 *   - Hora = proxima hora completa (currentHour + 1, mediodia minimo)
 *   - Tipo = primer tipo del catalogo
 */
import { useState, useEffect, useRef } from 'react'
import { X, Search, Calendar, Loader2, Check, Video } from 'lucide-react'
import api from '@/lib/api'

function nextRoundHour() {
  const now = new Date()
  const h = Math.min(20, Math.max(now.getHours() + 1, 9))
  return `${String(h).padStart(2, '0')}:00`
}

function todayIso() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/Lima',
    year: 'numeric', month: '2-digit', day: '2-digit',
  }).formatToParts(new Date())
  const map = Object.fromEntries(parts.filter(p => p.type !== 'literal').map(p => [p.type, p.value]))
  return `${map.year}-${map.month}-${map.day}`
}

// La prop `resultadosContacto` la pasa Agenda.jsx por simetria con
// LeadDetalle, pero la creacion de cita no necesita el resultado (la cita
// aun no ocurrio). Alias a `_resultadosContacto` para signalar intencion
// (eslint no-unused-vars permite prefijo `_`).
export default function NuevaCitaModal({
  tiposCita: tiposCitaProp = [],
  tiposContacto = [],
  resultadosContacto: _resultadosContacto = [],
  onClose,
  onCreated,
}) {
  // Acepta tiposCita con fallback a tiposContacto para retrocompatibilidad
  const tiposCita = tiposCitaProp.length > 0 ? tiposCitaProp : tiposContacto
  const [query, setQuery] = useState('')
  const [results, setResults] = useState([])
  const [searching, setSearching] = useState(false)
  const [lead, setLead] = useState(null)
  const [tipo, setTipo] = useState((tiposCita[0]?.nombre) || 'Cita oficina Bustamante')
  const [date, setDate] = useState(todayIso())
  const [time, setTime] = useState(nextRoundHour())
  const [urlReunion, setUrlReunion] = useState('')
  const [notas, setNotas] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [error, setError] = useState(null)
  const debounceRef = useRef(null)

  const isVirtual = (tipo || '').toLowerCase().includes('virtual') || (tipo || '').toLowerCase().includes('video') || (tipo || '').toLowerCase().includes('meet') || (tipo || '').toLowerCase().includes('zoom')

  // ESC cierra.
  useEffect(() => {
    const onKey = (e) => { if (e.key === 'Escape') onClose?.() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  // Typeahead con debounce.
  useEffect(() => {
    if (lead) return                 // ya hay lead seleccionado, no buscar
    if (!query || query.length < 2) { setResults([]); return }
    clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(async () => {
      setSearching(true)
      try {
        const res = await api.get('/api/leads', {
          params: { search: query, limit: 8 },
        })
        setResults(res.data?.items || res.data?.data || [])
      } catch {
        setResults([])
      } finally {
        setSearching(false)
      }
    }, 300)
    return () => clearTimeout(debounceRef.current)
  }, [query, lead])

  // Default tipo cuando llega el catalogo.
  useEffect(() => {
    if (tiposCita.length > 0 && !tiposCita.some(t => t.nombre === tipo)) {
      setTipo(tiposCita[0].nombre)
    }
  }, [tiposCita, tipo])

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError(null)
    if (!lead) { setError('Selecciona un lead antes de agendar.'); return }
    if (!date || !time) { setError('Indica fecha y hora.'); return }
    if (isVirtual && (!urlReunion || !urlReunion.trim())) {
      setError('La URL de la reunión (Meet, Zoom, etc.) es obligatoria para citas virtuales.')
      return
    }
    const fechaCita = `${date}T${time}:00`
    // Validacion: no agendar en el pasado (tolerancia 5 min).
    if (new Date(fechaCita).getTime() < Date.now() - 5 * 60 * 1000) {
      setError('No puedes agendar en una fecha pasada.')
      return
    }
    setSubmitting(true)
    try {
      // V096.2.2 — Bug fix de la hora "3:59 p.m." en agenda:
      // El backend reconoce que es una cita via `tipo_contacto = 'cita'`
      // (literal) O `resultado = 'cita_agendada'` (literal snake_case).
      // Si no reconoce ninguno, NO valida fecha_cita y la agenda fallback
      // a `created_at` (la hora exacta de creacion = "3:59 p.m.").
      //
      // Asi que enviamos los DOS marcadores literales + el tipo de
      // comunicacion (llamada/presencial/etc) va en tipo_cita.
      await api.post(`/api/leads/${lead.id}/contactos`, {
        tipo_contacto: 'cita',          // marcador para el backend
        tipo_cita:     tipo,            // modalidad: llamada / presencial / video / etc
        resultado:     'cita_agendada', // marcador para el backend
        fecha_cita:    fechaCita,
        url_reunion:   isVirtual && urlReunion.trim() ? urlReunion.trim() : null,
        notas:         notas || null,
      })
      onCreated?.()
      onClose?.()
    } catch (err) {
      setError(err.response?.data?.detail || err.message || 'No se pudo crear la cita.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <>
      <div
        className="fixed inset-0 bg-black/40 z-40 transition-opacity"
        onClick={onClose}
        aria-hidden="true"
      />
      <div
        className="fixed top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-lg bg-white dark:bg-[#121a29] border border-gray-100 dark:border-slate-800 rounded-2xl shadow-2xl z-50 flex flex-col overflow-hidden max-h-[90vh]"
        role="dialog"
        aria-modal="true"
        aria-label="Nueva cita"
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-100 dark:border-slate-800">
          <h2 className="text-base font-bold text-gray-900 dark:text-slate-100 flex items-center gap-2">
            <Calendar size={18} className="text-emerald-600 dark:text-emerald-400" />
            Nueva cita
          </h2>
          <button
            onClick={onClose}
            className="p-1 rounded hover:bg-gray-100 dark:hover:bg-slate-800 text-gray-400 hover:text-gray-600 dark:hover:text-slate-200 cursor-pointer"
            aria-label="Cerrar"
          >
            <X size={20} />
          </button>
        </div>

        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-5 space-y-4">
          {/* Lead typeahead */}
          <div>
            <label className="text-xs font-semibold text-gray-700 dark:text-slate-300 mb-1 block">Lead</label>
            {lead ? (
              <div className="flex items-center justify-between p-2.5 rounded-lg border border-emerald-200 dark:border-emerald-900/60 bg-emerald-50 dark:bg-emerald-950/30">
                <div className="flex items-center gap-2 min-w-0">
                  <Check size={16} className="text-emerald-600 dark:text-emerald-400 shrink-0" />
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-gray-900 dark:text-slate-100 truncate">
                      {lead.nombres ? `${lead.nombres} ${lead.apellidos || ''}`.trim() : 'Sin nombre'}
                    </p>
                    <p className="text-xs text-gray-500 dark:text-slate-400 font-mono">{lead.telefono}</p>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => { setLead(null); setQuery(''); setResults([]) }}
                  className="text-xs text-gray-500 dark:text-slate-400 hover:text-gray-700 dark:hover:text-slate-200 px-2 py-1 rounded hover:bg-white dark:hover:bg-slate-800 cursor-pointer"
                >
                  Cambiar
                </button>
              </div>
            ) : (
              <div className="relative">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 dark:text-slate-500" />
                <input
                  type="text"
                  value={query}
                  onChange={e => setQuery(e.target.value)}
                  placeholder="Buscar por nombre o teléfono…"
                  autoFocus
                  className="w-full pl-9 pr-3 py-2 text-sm border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-gray-900 dark:text-slate-100 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
                {(searching || results.length > 0) && query.length >= 2 && (
                  <div className="absolute z-10 top-full left-0 right-0 mt-1 bg-white dark:bg-[#121a29] border border-gray-200 dark:border-slate-800 rounded-md shadow-lg max-h-60 overflow-y-auto">
                    {searching && (
                      <div className="px-3 py-2 text-xs text-gray-500 dark:text-slate-400 flex items-center gap-2">
                        <Loader2 size={12} className="animate-spin" /> Buscando…
                      </div>
                    )}
                    {!searching && results.length === 0 && (
                      <div className="px-3 py-2 text-xs text-gray-500 dark:text-slate-400">Sin resultados</div>
                    )}
                    {!searching && results.map(l => (
                      <button
                        key={l.id}
                        type="button"
                        onClick={() => { setLead(l); setQuery(''); setResults([]) }}
                        className="w-full text-left px-3 py-2 hover:bg-indigo-50 dark:hover:bg-indigo-950/50 text-sm border-b border-gray-50 dark:border-slate-800 last:border-b-0 cursor-pointer"
                      >
                        <p className="font-medium text-gray-900 dark:text-slate-100 truncate">
                          {l.nombres ? `${l.nombres} ${l.apellidos || ''}`.trim() : 'Sin nombre'}
                        </p>
                        <p className="text-xs text-gray-500 dark:text-slate-400 font-mono">{l.telefono}</p>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Fecha + Hora */}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-semibold text-gray-700 dark:text-slate-300 mb-1 block">Fecha</label>
              <input
                type="date"
                value={date}
                onChange={e => setDate(e.target.value)}
                min={todayIso()}
                className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-gray-900 dark:text-slate-100 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
            <div>
              <label className="text-xs font-semibold text-gray-700 dark:text-slate-300 mb-1 block">Hora</label>
              <input
                type="time"
                value={time}
                onChange={e => setTime(e.target.value)}
                className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-gray-900 dark:text-slate-100 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500"
              />
            </div>
          </div>

          {/* Tipo de Cita */}
          <div>
            <label className="text-xs font-semibold text-gray-700 dark:text-slate-300 mb-1 block">Tipo de Cita</label>
            <select
              value={tipo}
              onChange={e => setTipo(e.target.value)}
              className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-slate-700 rounded-md bg-white dark:bg-slate-900 text-gray-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              {tiposCita.length === 0 ? (
                <>
                  <option value="Cita oficina Bustamante">Cita oficina Bustamante</option>
                  <option value="Cita oficina Umacollo">Cita oficina Umacollo</option>
                  <option value="Cita Exteriores">Cita Exteriores</option>
                  <option value="Cita Virtual">Cita Virtual</option>
                </>
              ) : (
                tiposCita.map(t => (
                  <option key={t.id || t.codigo || t.nombre} value={t.nombre}>{t.nombre}</option>
                ))
              )}
            </select>
          </div>

          {/* URL de reunión virtual */}
          {isVirtual && (
            <div className="bg-indigo-50/60 dark:bg-indigo-950/30 border border-indigo-200 dark:border-indigo-900/60 rounded-lg p-3 space-y-1.5 animate-in fade-in duration-150">
              <label className="text-xs font-semibold text-indigo-900 dark:text-indigo-300 flex items-center gap-1.5">
                <Video size={14} className="text-indigo-600 dark:text-indigo-400" />
                URL de la reunión (Meet / Zoom / Teams) <span className="text-red-500">*</span>
              </label>
              <input
                type="url"
                value={urlReunion}
                onChange={e => setUrlReunion(e.target.value)}
                placeholder="https://meet.google.com/... o https://zoom.us/j/..."
                required={isVirtual}
                className="w-full px-3 py-2 text-sm border border-indigo-300 dark:border-indigo-800 rounded-md bg-white dark:bg-slate-900 text-gray-900 dark:text-slate-100 focus:outline-none focus:ring-2 focus:ring-indigo-500 font-mono text-xs"
              />
              <p className="text-[11px] text-indigo-700/80 dark:text-indigo-400">
                Ingresa el enlace donde se llevará a cabo la videollamada.
              </p>
            </div>
          )}

          {/* Notas */}
          <div>
            <label className="text-xs font-semibold text-gray-700 dark:text-slate-300 mb-1 block">Notas (opcional)</label>
            <textarea
              value={notas}
              onChange={e => setNotas(e.target.value)}
              rows={3}
              placeholder="Ej: Visita al proyecto Yllary, lleva planos."
              className="w-full px-3 py-2 text-sm border border-gray-200 dark:border-slate-700 bg-white dark:bg-slate-900 text-gray-900 dark:text-slate-100 rounded-md focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
            />
          </div>

          {error && (
            <div className="bg-rose-50 dark:bg-rose-950/40 border border-rose-200 dark:border-rose-900/60 text-rose-700 dark:text-rose-300 text-xs rounded-md px-3 py-2">
              {error}
            </div>
          )}

          <div className="flex gap-2 justify-end pt-2 border-t border-gray-100 dark:border-slate-800">
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="px-4 py-2 text-sm font-medium border border-gray-200 dark:border-slate-700 rounded-md hover:bg-gray-50 dark:hover:bg-slate-800 text-gray-700 dark:text-slate-300 disabled:opacity-50 cursor-pointer"
            >
              Cancelar
            </button>
            <button
              type="submit"
              disabled={submitting || !lead}
              className="px-4 py-2 text-sm font-bold rounded-md bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-2 cursor-pointer"
            >
              {submitting ? <Loader2 size={14} className="animate-spin" /> : <Calendar size={14} />}
              {submitting ? 'Agendando…' : 'Agendar cita'}
            </button>
          </div>
        </form>
      </div>
    </>
  )
}
