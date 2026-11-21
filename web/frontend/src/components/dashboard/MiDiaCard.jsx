/**
 * MiDiaCard — "Tu día al X%" (efecto Zeigarnik).
 *
 * Patron LinkedIn "perfil 80%" / Duolingo daily goals: barra de progreso
 * prominente que mantiene activos los loops abiertos del dia hasta que
 * el user los cierra. El cerebro humano libera tension cognitiva solo
 * cuando una tarea se completa (Bluma Zeigarnik, 1927).
 *
 * Filosofia anti-ansiedad:
 *   - Reset diario: solo cuenta contactos+pendientes del DIA.
 *   - Mensaje motivacional positivo en TODOS los rangos.
 *   - Celebracion visual al 100% (verde + emoji).
 *   - Acciones claras debajo (no es solo info — es accionable).
 */
import { useEffect, useState } from 'react'
import { Flame, Clock, CalendarCheck, ChevronRight, Loader2 } from 'lucide-react'
import api from '@/lib/api'

export default function MiDiaCard({ onClickPendientes, onClickNextLead }) {
  const [data, setData]     = useState(null)
  const [loading, setLoading] = useState(true)
  // Animacion del numero: tween de 0 → progress_pct cuando carga.
  const [animPct, setAnimPct] = useState(0)

  useEffect(() => {
    let cancelled = false
    api.get('/api/dashboard/mi-dia')
      .then(res => { if (!cancelled) setData(res.data) })
      .catch(() => { if (!cancelled) setData(null) })
      .finally(() => { if (!cancelled) setLoading(false) })
    return () => { cancelled = true }
  }, [])

  // Tween del % cuando llega data nueva — efecto "subiendo" suave.
  useEffect(() => {
    if (!data) return
    const target = data.progress_pct || 0
    let raf
    const start = performance.now()
    const duration = 900
    const from = animPct
    const tick = (now) => {
      const t = Math.min(1, (now - start) / duration)
      // Ease out cubic
      const eased = 1 - Math.pow(1 - t, 3)
      const v = Math.round(from + (target - from) * eased)
      setAnimPct(v)
      if (t < 1) raf = requestAnimationFrame(tick)
    }
    popAnimation:
    raf = requestAnimationFrame(tick)
    return () => raf && cancelAnimationFrame(raf)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.progress_pct])

  if (loading) {
    return (
      <div className="rounded-2xl border border-gray-100 dark:border-slate-800 bg-gradient-to-br from-indigo-50/40 to-white dark:from-indigo-950/20 dark:to-[#121a29] p-5 flex items-center gap-3 min-h-[120px]">
        <Loader2 size={18} className="animate-spin text-gray-300 dark:text-slate-600" />
        <span className="text-sm text-gray-400 dark:text-slate-500">Cargando tu día…</span>
      </div>
    )
  }
  if (!data) return null

  const done   = data.progress_pct >= 100
  const pct    = animPct

  // Gradiente segun rango — verde al 100%, indigo principal,
  // ambar/amber cuando hay pocos contactos hechos.
  const tone = done
    ? { from: 'from-emerald-50 dark:from-emerald-950/40',  to: 'to-emerald-50/30 dark:to-[#121a29]',  ring: 'border-emerald-200 dark:border-emerald-900/40', bar: 'bg-emerald-500',  text: 'text-emerald-700 dark:text-emerald-400' }
    : pct >= 50
      ? { from: 'from-indigo-50 dark:from-indigo-950/40',  to: 'to-indigo-50/30 dark:to-[#121a29]',  ring: 'border-indigo-100 dark:border-indigo-900/40', bar: 'bg-indigo-500',  text: 'text-indigo-700 dark:text-indigo-400' }
      : { from: 'from-amber-50 dark:from-amber-950/40',   to: 'to-amber-50/30 dark:to-[#121a29]',   ring: 'border-amber-100 dark:border-amber-900/40',  bar: 'bg-amber-500',   text: 'text-amber-700 dark:text-amber-400' }

  return (
    <div className={`rounded-2xl border ${tone.ring} bg-gradient-to-br ${tone.from} ${tone.to} p-5`}>
      {/* Fila superior: titulo + emoji */}
      <div className="flex items-start justify-between gap-3 mb-3">
        <div className="min-w-0 flex-1">
          <p className="text-[11px] uppercase tracking-wider font-semibold text-gray-500 dark:text-slate-400 mb-1">
            Tu día
          </p>
          <p className={`text-3xl font-bold ${tone.text} leading-tight`}>
            {pct}<span className="text-2xl">%</span>
            <span className="text-sm font-medium text-gray-500 dark:text-slate-400 ml-2">
              {done ? 'completo' : 'avanzado'}
            </span>
          </p>
          <p className="text-sm text-gray-600 dark:text-slate-300 mt-1.5 flex items-center gap-1.5">
            <span className="text-base">{data.emoji}</span>
            {data.motivational}
          </p>
        </div>
      </div>

      {/* Barra de progreso */}
      <div className="h-2 bg-white/60 dark:bg-slate-800 rounded-full overflow-hidden mb-4">
        <div
          className={`h-full ${tone.bar} rounded-full transition-all duration-700 ease-out`}
          style={{ width: `${pct}%` }}
        />
      </div>

      {/* Breakdown — 3 chips compactos */}
      <div className="grid grid-cols-3 gap-2">
        <Stat
          icon={<Flame size={13} />}
          label="Contactos hoy"
          value={data.contactos_hoy}
          tone="indigo"
        />
        <Stat
          icon={<Clock size={13} />}
          label="Pendientes"
          value={data.pendientes_hoy}
          tone={data.pendientes_hoy > 0 ? 'amber' : 'emerald'}
          onClick={data.pendientes_hoy > 0 ? onClickPendientes : null}
        />
        <Stat
          icon={<CalendarCheck size={13} />}
          label="Citas hoy"
          value={`${data.citas_confirmadas}/${data.citas_hoy}`}
          tone="sky"
          hideIfZero={data.citas_hoy === 0}
        />
      </div>

      {/* CTA principal: próximo lead recomendado (Netflix-style autoplay) */}
      {data.next_recommended_lead && !done && (
        <button
          onClick={() => onClickNextLead && onClickNextLead(data.next_recommended_lead)}
          className="mt-4 w-full flex items-center gap-3 px-3 py-2.5 rounded-lg bg-white dark:bg-[#0f1624] border border-gray-200 dark:border-slate-700/80 hover:border-indigo-300 dark:hover:border-indigo-500 hover:bg-indigo-50/40 dark:hover:bg-indigo-950/30 transition-colors text-left group cursor-pointer"
          type="button"
        >
          <div className="w-8 h-8 rounded-full bg-indigo-100 dark:bg-indigo-950 text-indigo-600 dark:text-indigo-400 flex items-center justify-center text-xs font-bold shrink-0">
            {(data.next_recommended_lead.nombres || '?')[0]?.toUpperCase()}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-[10px] uppercase tracking-wider text-gray-400 dark:text-slate-400 font-semibold mb-0.5">
              Próximo lead recomendado
            </p>
            <p className="text-sm font-semibold text-gray-900 dark:text-slate-100 truncate">
              {[data.next_recommended_lead.nombres, data.next_recommended_lead.apellidos]
                .filter(Boolean).join(' ') || 'Sin nombre'}
            </p>
            <p className="text-[11px] text-gray-500 dark:text-slate-400 mt-0.5">
              {data.next_recommended_lead.calidad_codigo && (
                <span className="inline-block px-1.5 py-0.5 mr-1 rounded text-[10px] font-semibold bg-red-50 dark:bg-red-950/50 text-red-600 dark:text-red-400 border border-red-100 dark:border-red-900/40">
                  {data.next_recommended_lead.calidad_codigo}
                </span>
              )}
              {Math.round(data.next_recommended_lead.horas_sin_contacto)}h sin contacto · {data.next_recommended_lead.estado_nombre}
            </p>
          </div>
          <ChevronRight size={16} className="text-gray-300 dark:text-slate-600 group-hover:text-indigo-500 transition-colors shrink-0" />
        </button>
      )}
    </div>
  )
}


function Stat({ icon, label, value, tone, onClick, hideIfZero }) {
  if (hideIfZero) return <div className="opacity-0 pointer-events-none" />

  const tones = {
    indigo:  'bg-white/80 dark:bg-[#0f1624]/80 text-indigo-700 dark:text-indigo-300 border-indigo-100 dark:border-indigo-900/40',
    amber:   'bg-white/80 dark:bg-[#0f1624]/80 text-amber-700 dark:text-amber-300 border-amber-200 dark:border-amber-900/40',
    emerald: 'bg-white/80 dark:bg-[#0f1624]/80 text-emerald-700 dark:text-emerald-300 border-emerald-200 dark:border-emerald-900/40',
    sky:     'bg-white/80 dark:bg-[#0f1624]/80 text-sky-700 dark:text-sky-300 border-sky-100 dark:border-sky-900/40',
  }
  const cls = `flex items-center gap-1.5 px-2.5 py-2 rounded-lg border ${tones[tone] || tones.indigo} ${onClick ? 'cursor-pointer hover:shadow-sm transition-shadow' : ''}`
  const inner = (
    <>
      <span className="opacity-70 shrink-0">{icon}</span>
      <div className="min-w-0">
        <p className="text-[10px] uppercase tracking-wide opacity-70 font-semibold leading-none">{label}</p>
        <p className="text-base font-bold leading-tight mt-0.5 truncate">{value}</p>
      </div>
    </>
  )
  if (onClick) {
    return <button type="button" onClick={onClick} className={cls}>{inner}</button>
  }
  return <div className={cls}>{inner}</div>
}
