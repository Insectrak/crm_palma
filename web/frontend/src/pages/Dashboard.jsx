import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Users, UserCheck, Phone, TrendingUp, TrendingDown, Minus,
  AlertCircle, RefreshCw, Zap, CalendarCheck, UserPlus, X, Target,
} from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import useAuthStore from '@/store/authStore'
import useCrmStore from '@/store/crmStore'
import api from '@/lib/api'
import MiDiaCard from '@/components/dashboard/MiDiaCard'
import DateRangeSelector from '@/components/dashboard/DateRangeSelector'
import Sparkline from '@/components/dashboard/Sparkline'
import TeamBlockedBanner from '@/components/equipos/TeamBlockedBanner'
import useDateRange from '@/hooks/useDateRange'

/* ─── Comparison arrow + % vs periodo anterior ────────────────────────────
 * V096 — calcula la variacion porcentual entre current y previous.
 * Null si no hay previo o el previo es 0 (no se puede dividir).
 * Verde si sube, rojo si baja, gris si igual. */
function PeriodDelta({ current, previous }) {
  if (current == null || previous == null) return null
  if (previous === 0 && current === 0) return null
  if (previous === 0) {
    // De 0 a algo: muestra "nuevo" sin %
    return (
      <span className="inline-flex items-center gap-0.5 text-[11px] font-medium text-emerald-600">
        <TrendingUp size={11} />nuevo
      </span>
    )
  }
  const pct = ((current - previous) / previous) * 100
  const rounded = Math.round(pct)
  if (rounded === 0) {
    return (
      <span className="inline-flex items-center gap-0.5 text-[11px] font-medium text-gray-400">
        <Minus size={11} />sin cambio
      </span>
    )
  }
  const up = rounded > 0
  const Icon = up ? TrendingUp : TrendingDown
  return (
    <span
      className={`inline-flex items-center gap-0.5 text-[11px] font-medium ${
        up ? 'text-emerald-600' : 'text-rose-600'
      }`}
      title={`${current} vs ${previous} periodo anterior`}
    >
      <Icon size={11} />{up ? '+' : ''}{rounded}%
    </span>
  )
}

/* ─── KPI Card principal ──────────────────────────────────────────────────
 * V096 — soporte nuevo de:
 *   - badge:      "HISTÓRICO" (snapshot) | "· últimos 7 días" (filtrado)
 *   - delta:      sub-texto adicional (compat con uso anterior)
 *   - comparison: { current, previous }  -> arrow + % vs periodo anterior
 *   - sparkline:  [{date, count}, ...]   -> mini chart en el footer del card
 *   - sparklineColor */
function KpiCard({
  icon: Icon, label, value, delta, color = 'blue',
  isLoading, onClick, badge, comparison, sparkline, sparklineColor,
}) {
  const styles = {
    blue:   { wrap: 'from-indigo-50 to-white dark:from-indigo-950/40 dark:to-[#121a29] border-indigo-100 dark:border-indigo-900/40', icon: 'bg-indigo-100 dark:bg-indigo-950/80 text-indigo-600 dark:text-indigo-400',   spark: '#6366f1' },
    green:  { wrap: 'from-emerald-50 to-white dark:from-emerald-950/40 dark:to-[#121a29] border-emerald-100 dark:border-emerald-900/40', icon: 'bg-emerald-100 dark:bg-emerald-950/80 text-emerald-600 dark:text-emerald-400', spark: '#10b981' },
    amber:  { wrap: 'from-amber-50 to-white dark:from-amber-950/40 dark:to-[#121a29] border-amber-100 dark:border-amber-900/40', icon: 'bg-amber-100 dark:bg-amber-950/80 text-amber-600 dark:text-amber-400',     spark: '#f59e0b' },
    purple: { wrap: 'from-purple-50 to-white dark:from-purple-950/40 dark:to-[#121a29] border-purple-100 dark:border-purple-900/40', icon: 'bg-purple-100 dark:bg-purple-950/80 text-purple-600 dark:text-purple-400', spark: '#a855f7' },
    pink:   { wrap: 'from-pink-50 to-white dark:from-pink-950/40 dark:to-[#121a29] border-pink-100 dark:border-pink-900/40', icon: 'bg-pink-100 dark:bg-pink-950/80 text-pink-600 dark:text-pink-400',         spark: '#ec4899' },
  }
  const s = styles[color] || styles.blue

  return (
    <Card
      className={`bg-gradient-to-br ${s.wrap} border transition-all duration-150 ${onClick ? 'cursor-pointer hover:shadow-md hover:-translate-y-0.5' : ''}`}
      onClick={onClick}
    >
      <CardContent className="p-5">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between gap-2 mb-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-gray-500 dark:text-slate-400">{label}</p>
              {badge && (
                <span className="text-[9px] font-bold uppercase tracking-wider text-gray-400 dark:text-slate-500 shrink-0">
                  {badge}
                </span>
              )}
            </div>
            {isLoading
              ? <div className="h-9 w-20 bg-gray-200 dark:bg-slate-800 rounded-lg animate-pulse" />
              : <p className="text-3xl font-bold text-gray-900 dark:text-slate-100 leading-none">{value ?? '—'}</p>}
            {!isLoading && (delta !== undefined || comparison) && (
              <div className="flex items-center gap-2 mt-2 leading-tight flex-wrap">
                {comparison && <PeriodDelta current={comparison.current} previous={comparison.previous} />}
                {delta !== undefined && (
                  <p className="text-xs text-gray-400 dark:text-slate-400">{delta}</p>
                )}
              </div>
            )}
          </div>
          <div className={`w-11 h-11 ${s.icon} rounded-xl flex items-center justify-center shrink-0`}>
            <Icon size={20} />
          </div>
        </div>
        {sparkline && !isLoading && sparkline.length >= 2 && (
          <div className="mt-3 -mx-1">
            <Sparkline data={sparkline} color={sparklineColor || s.spark} height={28} />
          </div>
        )}
      </CardContent>
    </Card>
  )
}

/* ─── Mini stat (fila de estados) ──────────────────────────────────────── */
function MiniStat({ label, value, color, isLoading, onClick, comparison }) {
  const colors = {
    sky:    'bg-sky-50 dark:bg-sky-950/30 text-sky-700 dark:text-sky-300 border-sky-100 dark:border-sky-900/50',
    amber:  'bg-amber-50 dark:bg-amber-950/30 text-amber-700 dark:text-amber-300 border-amber-100 dark:border-amber-900/50',
    orange: 'bg-orange-50 dark:bg-orange-950/30 text-orange-700 dark:text-orange-300 border-orange-100 dark:border-orange-900/50',
    green:  'bg-green-50 dark:bg-green-950/30 text-green-700 dark:text-green-300 border-green-100 dark:border-green-900/50',
    red:    'bg-red-50 dark:bg-red-950/30 text-red-700 dark:text-red-300 border-red-100 dark:border-red-900/50',
    rose:   'bg-rose-50 dark:bg-rose-950/30 text-rose-700 dark:text-rose-300 border-rose-100 dark:border-rose-900/50',
    purple: 'bg-purple-50 dark:bg-purple-950/30 text-purple-700 dark:text-purple-300 border-purple-100 dark:border-purple-900/50',
    indigo: 'bg-indigo-50 dark:bg-indigo-950/30 text-indigo-700 dark:text-indigo-300 border-indigo-100 dark:border-indigo-900/50',
    emerald:'bg-emerald-50 dark:bg-emerald-950/30 text-emerald-700 dark:text-emerald-300 border-emerald-100 dark:border-emerald-900/50',
  }
  return (
    <div
      onClick={onClick}
      className={`rounded-xl border px-4 py-3 flex items-center justify-between gap-2 ${colors[color] || colors.sky} ${onClick ? 'cursor-pointer hover:shadow-sm transition-all hover:scale-[1.01]' : ''}`}
    >
      <span className="text-xs font-semibold uppercase tracking-wide opacity-80 truncate">{label}</span>
      {isLoading ? (
        <div className="h-5 w-10 bg-current opacity-20 rounded animate-pulse" />
      ) : (
        <div className="flex items-baseline gap-1.5 shrink-0">
          <span className="text-xl font-bold">{value ?? 0}</span>
          {comparison && <PeriodDelta current={comparison.current} previous={comparison.previous} />}
        </div>
      )}
    </div>
  )
}

/* ─── Banner de alerta — leads urgentes sin contactar ───────────────────── */
function AlertaBanner({ urgentes, isLoading, onNavigate }) {
  if (isLoading || !urgentes || urgentes.total === 0) return null
  const hot = urgentes.total > 15
  return (
    <div className={`rounded-xl border px-4 py-3 flex items-center gap-3 ${
      hot
        ? 'bg-red-50 dark:bg-red-950/40 border-red-200 dark:border-red-900/50'
        : 'bg-amber-50 dark:bg-amber-950/40 border-amber-200 dark:border-amber-900/50'
    }`}>
      <AlertCircle size={18} className={`shrink-0 ${hot ? 'text-red-500 dark:text-red-400' : 'text-amber-500 dark:text-amber-400'}`} />
      <div className="flex-1 min-w-0">
        <span className={`font-semibold text-sm ${hot ? 'text-red-800 dark:text-red-300' : 'text-amber-800 dark:text-amber-300'}`}>
          {urgentes.total} leads sin contactar
        </span>
        <span className="text-xs text-gray-500 dark:text-slate-400 ml-2">más de 48 horas sin ningún intento de contacto</span>
      </div>
      {/* Preview de los más antiguos — solo desktop */}
      {urgentes.leads?.length > 0 && (
        <div className="hidden lg:flex items-center gap-1.5 shrink-0">
          {urgentes.leads.slice(0, 3).map(l => (
            <span key={l.id} className={`text-xs px-2 py-0.5 rounded-full font-medium ${
              hot
                ? 'bg-red-100 dark:bg-red-900/60 text-red-700 dark:text-red-200'
                : 'bg-amber-100 dark:bg-amber-900/60 text-amber-700 dark:text-amber-200'
            }`}>
              {l.nombre_completo?.split(' ')[0]} · {l.dias_sin_contacto}d
            </span>
          ))}
        </div>
      )}
      <button
        onClick={onNavigate}
        className={`text-xs font-semibold px-3 py-1.5 rounded-lg transition-colors shrink-0 cursor-pointer ${
          hot
            ? 'bg-red-100 dark:bg-red-900/50 hover:bg-red-200 dark:hover:bg-red-900/80 text-red-700 dark:text-red-200'
            : 'bg-amber-100 dark:bg-amber-900/50 hover:bg-amber-200 dark:hover:bg-amber-900/80 text-amber-700 dark:text-amber-200'
        }`}
      >
        Ver todos →
      </button>
    </div>
  )
}

/* ─── Actividad del equipo (admin/supervisor) ─────────────────────────────
 * V096.2 — clase mundial: TODOS los cards de esta fila responden al
 * selector temporal global. Consistencia > excepciones. Si el manager
 * quiere ver "citas hoy", elige "Hoy" en el filtro global.
 * Patron patrón de analytics / patrón de analytics / patrón premium: pure analytics, sin mezclar
 * widgets operacionales en la misma fila. */
function ActividadEquipo({ data, isLoading, periodLabel, onNavigateToAgenda }) {
  const contactos     = data?.contactos_periodo
  const contactosPrev = data?.contactos_periodo_anterior
  const citas         = data?.citas_periodo ?? data?.citas_mes
  const citasPrev     = data?.citas_periodo_anterior ?? data?.citas_mes_anterior
  const citasHoy      = data?.citas_hoy || 0

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
      <div className="rounded-xl border px-4 py-3 text-indigo-600 dark:text-indigo-300 bg-indigo-50 dark:bg-indigo-950/30 border-indigo-100 dark:border-indigo-900/40">
        <div className="flex items-center justify-between mb-1">
          <p className="text-xs font-semibold uppercase tracking-wide opacity-70">
            Contactos del Equipo · {periodLabel || 'periodo'}
          </p>
          <Zap size={13} className="opacity-60" />
        </div>
        {isLoading ? (
          <div className="h-7 w-16 bg-current opacity-10 rounded animate-pulse" />
        ) : (
          <div className="flex items-baseline gap-2">
            <p className="text-2xl font-bold text-indigo-950 dark:text-indigo-100">{contactos ?? '—'}</p>
            <PeriodDelta current={contactos} previous={contactosPrev} />
          </div>
        )}
      </div>

      <div
        onClick={onNavigateToAgenda}
        className="rounded-xl border px-4 py-3 text-amber-700 dark:text-amber-300 bg-amber-50 dark:bg-amber-950/30 border-amber-200 dark:border-amber-900/40 cursor-pointer hover:bg-amber-100/70 dark:hover:bg-amber-950/50 hover:shadow-sm transition-all group relative"
      >
        <div className="flex items-center justify-between mb-1">
          <div className="flex items-center gap-1.5">
            <CalendarCheck size={14} className="text-amber-600 dark:text-amber-400" />
            <p className="text-xs font-bold uppercase tracking-wide text-amber-900 dark:text-amber-200">
              Citas del Equipo · {periodLabel || 'periodo'}
            </p>
          </div>
          <span className="text-[11px] font-medium text-amber-700 dark:text-amber-400 group-hover:translate-x-0.5 transition-transform flex items-center gap-0.5">
            Ver agenda →
          </span>
        </div>
        {isLoading ? (
          <div className="h-7 w-12 bg-current opacity-10 rounded animate-pulse" />
        ) : (
          <div className="flex items-baseline justify-between">
            <div className="flex items-baseline gap-2">
              <p className="text-2xl font-bold text-amber-950 dark:text-amber-100">{citas ?? '—'}</p>
              <PeriodDelta current={citas} previous={citasPrev} />
            </div>
            {citasHoy > 0 && (
              <span className="text-[11px] font-semibold bg-amber-200/80 dark:bg-amber-900/60 text-amber-900 dark:text-amber-200 px-2 py-0.5 rounded-full">
                {citasHoy} hoy
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

/* ─── Funnel de conversión SVG ──────────────────────────────────────────── */
function FunnelChart({ data, isLoading }) {
  if (isLoading) return <div className="h-20 bg-gray-100 dark:bg-slate-800/60 rounded-xl animate-pulse" />
  if (!data || data.length === 0)
    return <p className="text-sm text-gray-400 dark:text-slate-500 py-6 text-center">Sin datos disponibles</p>

  const boxW = 92
  const boxH = 52
  const gap  = 34
  const H    = 80
  const topY = (H - boxH) / 2
  const n    = data.length
  const pad  = 8
  const totalW = pad * 2 + n * boxW + (n - 1) * gap

  return (
    <div className="overflow-x-auto -mx-1 px-1">
      <svg viewBox={`0 0 ${totalW} ${H}`} className="w-full min-w-[480px] h-20" preserveAspectRatio="xMidYMid meet">
        {data.map((etapa, i) => {
          const boxX  = pad + i * (boxW + gap)
          const midY  = H / 2
          const color = etapa.color_hex || '#6366f1'
          const arrowX = boxX + boxW

          return (
            <g key={etapa.estado}>
              {/* Caja del estado */}
              <rect x={boxX} y={topY} width={boxW} height={boxH} rx="7"
                fill={color} fillOpacity="0.12" />
              <rect x={boxX} y={topY} width={boxW} height={boxH} rx="7"
                fill="none" stroke={color} strokeWidth="1.5" />

              {/* Nombre del estado */}
              <text x={boxX + boxW / 2} y={topY + 17} textAnchor="middle"
                fontSize="8.5" fontWeight="600" fill="currentColor" className="fill-gray-600 dark:fill-slate-300">
                {etapa.estado}
              </text>

              {/* Cantidad */}
              <text x={boxX + boxW / 2} y={topY + 37} textAnchor="middle"
                fontSize="15" fontWeight="800" fill={color}>
                {etapa.total.toLocaleString()}
              </text>

              {/* Flecha + tasa de conversión */}
              {i < data.length - 1 && (
                <g>
                  <line x1={arrowX + 4} y1={midY} x2={arrowX + gap - 10} y2={midY}
                    className="stroke-gray-300 dark:stroke-slate-600" strokeWidth="1.5" />
                  <path
                    d={`M ${arrowX + gap - 12} ${midY - 4} L ${arrowX + gap - 6} ${midY} L ${arrowX + gap - 12} ${midY + 4}`}
                    fill="none" className="stroke-gray-300 dark:stroke-slate-600" strokeWidth="1.5" strokeLinejoin="round"
                  />
                  {data[i + 1]?.tasa_desde_anterior != null && (
                    <text x={arrowX + gap / 2} y={midY - 7} textAnchor="middle"
                      fontSize="8" fontWeight="700"
                      fill={data[i + 1].tasa_desde_anterior > 30 ? '#10b981' : data[i + 1].tasa_desde_anterior > 10 ? '#f59e0b' : '#ef4444'}>
                      {data[i + 1].tasa_desde_anterior}%
                    </text>
                  )}
                </g>
              )}
            </g>
          )
        })}
      </svg>
    </div>
  )
}

/* ─── Barras horizontales por estado ────────────────────────────────────── */
function BarChart({ data, isLoading }) {
  if (isLoading) return (
    <div className="space-y-3 py-1">
      {[...Array(5)].map((_, i) => (
        <div key={i} className="flex items-center gap-3">
          <div className="h-3 rounded w-20 bg-gray-100 dark:bg-slate-800 animate-pulse" />
          <div className="flex-1 h-3 rounded bg-gray-100 dark:bg-slate-800 animate-pulse" />
          <div className="h-3 w-8 rounded bg-gray-100 dark:bg-slate-800 animate-pulse" />
        </div>
      ))}
    </div>
  )
  if (!data || data.length === 0)
    return <p className="text-sm text-gray-400 dark:text-slate-500 py-6 text-center">Sin datos disponibles</p>

  const maxVal = Math.max(...data.map(d => d.count), 1)
  return (
    <div className="space-y-2.5">
      {data.map((item) => (
        <div key={item.estado} className="flex items-center gap-3">
          <span className="text-xs text-gray-500 dark:text-slate-400 w-28 truncate shrink-0 font-medium">{item.estado}</span>
          <div className="flex-1 h-2.5 bg-gray-100 dark:bg-slate-800 rounded-full overflow-hidden">
            <div
              className="h-full rounded-full transition-all duration-700 ease-out"
              style={{
                width: `${Math.max((item.count / maxVal) * 100, item.count > 0 ? 2 : 0)}%`,
                backgroundColor: item.color_hex || '#6366f1',
              }}
            />
          </div>
          <span className="text-xs font-bold text-gray-700 dark:text-slate-200 w-10 text-right tabular-nums">
            {item.count.toLocaleString()}
          </span>
        </div>
      ))}
    </div>
  )
}

/* ─── Gráfico de línea SVG — tendencia ──────────────────────────────────── */
function LineChart({ data, isLoading }) {
  if (isLoading) return <div className="h-56 bg-gray-100 dark:bg-slate-800/60 rounded-xl animate-pulse" />
  if (!data || data.length === 0)
    return <p className="text-sm text-gray-400 dark:text-slate-500 py-10 text-center">Sin datos disponibles</p>

  const W = 900, H = 280, padX = 24, padTop = 32, padBot = 40
  const counts = data.map(d => d.count)
  const maxVal = Math.max(...counts, 1)
  const total = counts.reduce((s, n) => s + n, 0)
  const avg = total / counts.length
  const maxIdx = counts.indexOf(Math.max(...counts))

  const plotH = H - padTop - padBot
  const pts = data.map((d, i) => ({
    x: padX + (i / Math.max(data.length - 1, 1)) * (W - padX * 2),
    y: padTop + plotH - (d.count / maxVal) * plotH,
    ...d,
  }))
  const polyline = pts.map(p => `${p.x},${p.y}`).join(' ')
  const area = `${pts[0].x},${H - padBot} ${polyline} ${pts[pts.length - 1].x},${H - padBot}`
  const labelEvery = Math.ceil(data.length / 10)
  const avgY = padTop + plotH - (avg / maxVal) * plotH

  return (
    <div className="space-y-2">
      {/* Resumen analítico arriba del gráfico */}
      <div className="flex items-center gap-5 text-xs">
        <div>
          <span className="text-gray-400 dark:text-slate-400">Total: </span>
          <span className="font-bold text-gray-800 dark:text-slate-100 tabular-nums">{total.toLocaleString()}</span>
        </div>
        <div>
          <span className="text-gray-400 dark:text-slate-400">Promedio/día: </span>
          <span className="font-bold text-gray-800 dark:text-slate-100 tabular-nums">{avg.toFixed(1)}</span>
        </div>
        <div>
          <span className="text-gray-400 dark:text-slate-400">Pico: </span>
          <span className="font-bold text-indigo-600 dark:text-indigo-400 tabular-nums">{maxVal}</span>
          <span className="text-gray-400 dark:text-slate-400 ml-1">({data[maxIdx]?.fecha?.slice(5) || '—'})</span>
        </div>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-72">
        <defs>
          <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#6366f1" stopOpacity="0.25" />
            <stop offset="100%" stopColor="#6366f1" stopOpacity="0.01" />
          </linearGradient>
        </defs>

        {/* Línea de promedio (referencia) */}
        <line x1={padX} y1={avgY} x2={W - padX} y2={avgY}
          className="stroke-slate-300 dark:stroke-slate-700" strokeWidth="1" strokeDasharray="3,3" />
        <text x={W - padX} y={avgY - 4} fontSize="11" className="fill-slate-400 dark:fill-slate-500" textAnchor="end">
          prom. {avg.toFixed(1)}
        </text>

        <polygon points={area} fill="url(#areaGrad)" />
        <polyline points={polyline} fill="none" stroke="#6366f1" strokeWidth="3"
          strokeLinejoin="round" strokeLinecap="round" />

        {/* Puntos: pico destacado */}
        {pts.map((p, i) => {
          const isMax = i === maxIdx
          return (
            <circle key={i} cx={p.x} cy={p.y}
              r={isMax ? 6 : 4.5}
              fill={isMax ? '#4f46e5' : '#6366f1'}
              stroke="white" strokeWidth={isMax ? 2.5 : 2} />
          )
        })}

        {/* Cantidad sobre cada punto — siempre visible, sin hover */}
        {pts.map((p, i) => {
          const isMax = i === maxIdx
          return (
            <text key={`n-${i}`} x={p.x} y={p.y - 10}
              fontSize={isMax ? 14 : 12}
              fontWeight={isMax ? 700 : 600}
              fill={isMax ? '#4f46e5' : '#818cf8'}
              textAnchor="middle">
              {p.count}
            </text>
          )
        })}

        {/* Etiquetas de fechas */}
        {pts.map((p, i) =>
          (i % labelEvery === 0 || i === pts.length - 1) ? (
            <text key={`d-${i}`} x={p.x} y={H - 6} fontSize="12" className="fill-gray-500 dark:fill-slate-400" textAnchor="middle" fontWeight="500">
              {p.fecha?.slice(5) || ''}
            </text>
          ) : null
        )}
      </svg>
    </div>
  )
}

/* ─── Donut chart de fuentes ─────────────────────────────────────────────── */
const PIE_COLORS = ['#6366f1','#10b981','#f59e0b','#ef4444','#8b5cf6','#ec4899','#0ea5e9','#6b7280']

function DonutChart({ data, isLoading }) {
  if (isLoading) return <div className="h-44 bg-gray-100 dark:bg-slate-800/60 rounded-xl animate-pulse" />
  if (!data || data.length === 0)
    return <p className="text-sm text-gray-400 dark:text-slate-500 py-10 text-center">Sin datos disponibles</p>

  const total = data.reduce((s, d) => s + d.count, 0) || 1
  const R = 52, r = 32, cx = 68, cy = 68
  const items = data.slice(0, 7)
  // Calculamos ángulos acumulados de forma inmutable (n ≤ 7, O(n²) despreciable)
  const slices = items.map((d, i) => {
    const startAngle = items.slice(0, i).reduce(
      (acc, p) => acc + (p.count / total) * 2 * Math.PI,
      -Math.PI / 2,
    )
    const sweep    = (d.count / total) * 2 * Math.PI
    const endAngle = startAngle + sweep
    const x1o = cx + R * Math.cos(startAngle), y1o = cy + R * Math.sin(startAngle)
    const x1i = cx + r * Math.cos(startAngle), y1i = cy + r * Math.sin(startAngle)
    const x2o = cx + R * Math.cos(endAngle),   y2o = cy + R * Math.sin(endAngle)
    const x2i = cx + r * Math.cos(endAngle),   y2i = cy + r * Math.sin(endAngle)
    const large = sweep > Math.PI ? 1 : 0
    const path = [`M ${x1i} ${y1i}`,`L ${x1o} ${y1o}`,`A ${R} ${R} 0 ${large} 1 ${x2o} ${y2o}`,
      `L ${x2i} ${y2i}`,`A ${r} ${r} 0 ${large} 0 ${x1i} ${y1i}`,'Z'].join(' ')
    return { path, color: PIE_COLORS[i % PIE_COLORS.length], label: d.fuente, count: d.count,
      pct: Math.round((d.count / total) * 100) }
  })

  return (
    <div className="flex items-center gap-5">
      <svg viewBox="0 0 136 136" className="w-36 h-36 shrink-0">
        {slices.map((s, i) => (
          <path key={i} d={s.path} fill={s.color} className="stroke-white dark:stroke-[#121a29]" strokeWidth="2" />
        ))}
        <text x={cx} y={cy - 6} textAnchor="middle" fontSize="16" fontWeight="700" className="fill-gray-900 dark:fill-slate-100">
          {total.toLocaleString()}
        </text>
        <text x={cx} y={cy + 10} textAnchor="middle" fontSize="8" className="fill-gray-400 dark:fill-slate-400">leads</text>
      </svg>
      <div className="space-y-2 min-w-0 flex-1">
        {slices.map((s, i) => (
          <div key={i} className="flex items-center gap-2">
            <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ backgroundColor: s.color }} />
            <span className="text-xs text-gray-600 dark:text-slate-300 capitalize truncate flex-1">{s.label}</span>
            <span className="text-xs font-bold text-gray-800 dark:text-slate-100 tabular-nums ml-auto">{s.pct}%</span>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ─── Top asesores con barra de progreso ────────────────────────────────── */
function TopAsesores({ data, isLoading }) {
  const [expanded, setExpanded] = useState(false)
  const INITIAL_COUNT = 5

  if (isLoading) return (
    <div className="space-y-2">
      {[...Array(5)].map((_, i) => (
        <div key={i} className="flex items-center gap-2.5 px-2 py-2">
          <div className="w-5 h-5 rounded bg-gray-200 dark:bg-slate-800 animate-pulse shrink-0" />
          <div className="w-7 h-7 rounded-full bg-gray-200 dark:bg-slate-800 animate-pulse shrink-0" />
          <div className="flex-1 space-y-1.5">
            <div className="h-3 bg-gray-200 dark:bg-slate-800 rounded animate-pulse w-3/4" />
            <div className="h-1.5 bg-gray-100 dark:bg-slate-800 rounded-full animate-pulse" />
          </div>
          <div className="h-4 w-14 bg-gray-200 dark:bg-slate-800 rounded animate-pulse" />
        </div>
      ))}
    </div>
  )
  if (!data || data.length === 0)
    return <p className="text-sm text-gray-400 dark:text-slate-500 py-4 text-center">Sin datos</p>

  const maxMatriculas = Math.max(...data.map(a => a.matriculas || 0), 1)
  const maxLeads = Math.max(...data.map(a => a.total_leads || 0), 1)
  const visible = expanded ? data : data.slice(0, INITIAL_COUNT)
  const hasMore = data.length > INITIAL_COUNT

  // Color del badge de ranking: oro, plata, bronce, luego gris
  const rankStyle = (i) => {
    if (i === 0) return 'bg-amber-400 text-white'
    if (i === 1) return 'bg-gray-300 dark:bg-slate-600 text-white'
    if (i === 2) return 'bg-amber-600 text-white'
    return 'bg-gray-100 dark:bg-slate-800 text-gray-400 dark:text-slate-400'
  }

  // Color del avatar según posición
  const avatarStyle = (i) => {
    const palette = [
      'bg-indigo-100 dark:bg-indigo-950 text-indigo-700 dark:text-indigo-300 ring-indigo-200 dark:ring-indigo-800',
      'bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-300 ring-emerald-200 dark:ring-emerald-800',
      'bg-amber-100 dark:bg-amber-950 text-amber-700 dark:text-amber-300 ring-amber-200 dark:ring-amber-800',
      'bg-purple-100 dark:bg-purple-950 text-purple-700 dark:text-purple-300 ring-purple-200 dark:ring-purple-800',
      'bg-sky-100 dark:bg-sky-950 text-sky-700 dark:text-sky-300 ring-sky-200 dark:ring-sky-800',
      'bg-pink-100 dark:bg-pink-950 text-pink-700 dark:text-pink-300 ring-pink-200 dark:ring-pink-800',
      'bg-rose-100 dark:bg-rose-950 text-rose-700 dark:text-rose-300 ring-rose-200 dark:ring-rose-800',
      'bg-teal-100 dark:bg-teal-950 text-teal-700 dark:text-teal-300 ring-teal-200 dark:ring-teal-800',
    ]
    return palette[i % palette.length]
  }

  // Color semántico para tasa de conversión
  const conversionColor = (rate) => {
    if (rate >= 20) return 'text-emerald-600 dark:text-emerald-400 bg-emerald-50 dark:bg-emerald-950/40'
    if (rate >= 10) return 'text-amber-600 dark:text-amber-400 bg-amber-50 dark:bg-amber-950/40'
    return 'text-red-500 dark:text-red-400 bg-red-50 dark:bg-red-950/40'
  }

  // Color de barra de progreso según volumen relativo
  const barColor = (ratio) => {
    if (ratio >= 0.7) return 'bg-indigo-500'
    if (ratio >= 0.4) return 'bg-indigo-400'
    return 'bg-indigo-300 dark:bg-indigo-600'
  }

  const hasAnyMatriculas = data.some(a => (a.matriculas || 0) > 0)

  return (
    <div>
      <div className="space-y-0.5">
        {visible.map((asesor, i) => {
          const initials = (asesor.nombre_completo || 'A')
            .split(' ').slice(0, 2).map(w => w[0]).join('').toUpperCase()
          const ratio = hasAnyMatriculas
            ? ((asesor.matriculas || 0) / maxMatriculas)
            : ((asesor.total_leads || 0) / maxLeads)
          const rate = asesor.tasa_conversion ?? 0
          const matriculas = asesor.matriculas ?? 0

          return (
            <div
              key={asesor.asesor_id}
              className="flex items-center gap-2.5 px-2 py-1.5 -mx-2 rounded-lg hover:bg-gray-50 dark:hover:bg-slate-800/60 transition-colors group"
            >
              {/* Rank badge */}
              <span className={`w-5 h-5 rounded text-[10px] font-bold flex items-center justify-center shrink-0 ${rankStyle(i)}`}>
                {i + 1}
              </span>

              {/* Avatar */}
              <div className={`w-7 h-7 rounded-full flex items-center justify-center text-[10px] font-bold shrink-0 ring-1 ${avatarStyle(i)} ${i < 3 ? 'ring-2' : ''}`}>
                {initials}
              </div>

              {/* Name + progress bar */}
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-sm font-medium text-gray-800 dark:text-slate-200 truncate leading-tight">
                    {(asesor.nombre_completo || asesor.username || '').split(' ').slice(0, 2).join(' ')}
                  </p>
                  <div className="flex items-center gap-2 shrink-0">
                    {/* Conversion rate pill */}
                    <span
                      className={`text-[10px] font-bold px-1.5 py-0.5 rounded ${conversionColor(rate)}`}
                      title={`${rate}% de conversión (${matriculas} matrículas de ${asesor.total_leads} leads)`}
                    >
                      {rate}%
                    </span>
                    {/* Lead & Matriculas count */}
                    <span
                      className="text-xs font-semibold text-gray-700 dark:text-slate-300 tabular-nums min-w-[3.5rem] text-right"
                      title={`${matriculas} matrículas de ${asesor.total_leads} leads`}
                    >
                      <span className={matriculas > 0 ? "text-emerald-600 dark:text-emerald-400 font-bold" : "text-gray-500 dark:text-slate-400"}>
                        {matriculas}
                      </span>
                      <span className="text-gray-400 dark:text-slate-500 font-normal text-[10px]">
                        /{asesor.total_leads}
                      </span>
                    </span>
                  </div>
                </div>
                <div className="w-full h-1.5 bg-gray-100 dark:bg-slate-800 rounded-full overflow-hidden mt-1">
                  <div
                    className={`h-full rounded-full transition-all duration-700 ease-out ${barColor(ratio)}`}
                    style={{ width: `${Math.max(ratio * 100, 2)}%` }}
                  />
                </div>
              </div>
            </div>
          )
        })}
      </div>

      {hasMore && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="w-full text-center text-xs font-medium text-indigo-600 dark:text-indigo-400 hover:text-indigo-800 dark:hover:text-indigo-300 mt-2 py-1.5 rounded-lg hover:bg-indigo-50 dark:hover:bg-indigo-950/40 transition-colors border border-transparent hover:border-indigo-100 dark:hover:border-indigo-900/40 cursor-pointer"
        >
          {expanded ? '▲ Ver menos' : `▼ Ver ${data.length - INITIAL_COUNT} más`}
        </button>
      )}
    </div>
  )
}

/* ─── Widget Metas Cumplimiento (Sprint 3) ──────────────────────────────── */
function MetaBar({ label, actual, meta, pct, color, esperado }) {
  const ratio = esperado > 0 ? (pct || 0) / esperado : 0
  const colorBg = pct == null ? '#D1D5DB'
    : ratio >= 1   ? '#10B981'
    : ratio >= 0.7 ? '#F59E0B'
    :                '#EF4444'
  const width = Math.min(Math.max(pct || 0, 0), 100)
  return (
    <div className="space-y-1.5">
      <div className="flex items-baseline justify-between">
        <span className={`text-xs font-semibold uppercase tracking-wide text-${color}-600 dark:text-${color}-400`}>{label}</span>
        <span className="text-xs text-gray-500 dark:text-slate-400">
          <span className="text-gray-900 dark:text-slate-100 font-bold text-sm">{actual || 0}</span>
          <span className="mx-1">/</span>
          {meta || 0}
          {pct != null && <span className="ml-2 text-[10px] font-semibold" style={{ color: colorBg }}>{pct}%</span>}
        </span>
      </div>
      <div className="relative w-full h-2 bg-gray-100 dark:bg-slate-800 rounded-full overflow-hidden">
        <div className="absolute left-0 top-0 bottom-0 transition-all duration-500" style={{ width: `${width}%`, backgroundColor: colorBg }} />
        {esperado < 100 && esperado > 0 && (
          <div className="absolute top-0 bottom-0 w-px bg-gray-400 dark:bg-slate-600" style={{ left: `${esperado}%` }} title={`Esperado al día de hoy: ${esperado}%`} />
        )}
      </div>
    </div>
  )
}

const MESES_METAS = ['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']

function MetasWidget({ navigate }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  useEffect(() => {
    api.get('/api/metas/cumplimiento')
      .then(r => setData(r.data))
      .catch(() => setData({ totales: {}, pct_esperado: 0, metas: [] }))
      .finally(() => setLoading(false))
  }, [])

  const t = data?.totales || {}
  const esperado = data?.pct_esperado || 0
  const sinMetas = !loading && (!data?.metas || data.metas.length === 0)
  const mesLabel = data?.mes
    ? `${MESES_METAS[parseInt(data.mes.slice(5, 7), 10) - 1]} ${data.mes.slice(0, 4)}`
    : ''

  return (
    <Card>
      <CardHeader className="pb-2 flex flex-row items-center justify-between">
        <div className="flex items-center gap-2">
          <Target size={15} className="text-indigo-500 dark:text-indigo-400" />
          <CardTitle className="text-sm font-semibold text-gray-700 dark:text-slate-200">
            Cumplimiento de metas — <span className="capitalize">{mesLabel}</span>
          </CardTitle>
        </div>
        <button
          onClick={() => navigate('/metas')}
          className="text-[11px] text-indigo-500 dark:text-indigo-400 hover:text-indigo-700 dark:hover:text-indigo-300 font-medium cursor-pointer"
        >
          Ver detalle →
        </button>
      </CardHeader>
      <CardContent className="pt-0 space-y-3">
        {loading ? (
          <div className="space-y-3">
            {[1, 2, 3].map(i => <div key={i} className="h-8 bg-gray-100 dark:bg-slate-800 rounded animate-pulse" />)}
          </div>
        ) : sinMetas ? (
          <div className="text-center py-6">
            <Target size={28} className="mx-auto text-gray-300 dark:text-slate-600 mb-1.5" />
            <p className="text-sm text-gray-500 dark:text-slate-400 mb-2">No hay metas definidas para este mes.</p>
            <button onClick={() => navigate('/metas')} className="text-xs text-indigo-600 dark:text-indigo-400 hover:underline font-medium cursor-pointer">
              Crear primera meta
            </button>
          </div>
        ) : (
          <>
            <MetaBar label="Ventas (ganados)" actual={t.ventas_actuales}    meta={t.meta_ventas}    pct={t.pct_ventas}    color="emerald" esperado={esperado} />
            <MetaBar label="Citas agendadas"  actual={t.citas_actuales}     meta={t.meta_citas}     pct={t.pct_citas}     color="indigo"  esperado={esperado} />
            <MetaBar label="Llamadas"         actual={t.llamadas_actuales}  meta={t.meta_llamadas}  pct={t.pct_llamadas}  color="amber"   esperado={esperado} />
            <p className="text-[10px] text-gray-400 dark:text-slate-500 pt-1">
              Línea gris = progreso esperado al día de hoy ({esperado}%)
            </p>
          </>
        )}
      </CardContent>
    </Card>
  )
}

/* ─── Helpers ────────────────────────────────────────────────────────────── */
function getGreeting() {
  const h = new Date().getHours()
  if (h < 12) return 'Buenos días'
  if (h < 19) return 'Buenas tardes'
  return 'Buenas noches'
}

function todayLabel() {
  return new Date().toLocaleDateString('es-PE', { weekday: 'long', day: 'numeric', month: 'long' })
}

/* ─── Dashboard principal ────────────────────────────────────────────────── */
export default function Dashboard() {
  const navigate         = useNavigate()
  const { user }         = useAuthStore()
  const { loadCatalogs } = useCrmStore()
  const role             = user?.role || 'asesor'
  const canSeeTeam       = role === 'admin' || role === 'supervisor' || user?.role_id != null

  // V096 — selector temporal global del dashboard. Persiste por usuario
  // en localStorage. Default = ultimos 7 dias.
  const dateRange = useDateRange(user?.id || user?.user_id || 'anon')

  const [resumen,    setResumen]    = useState(null)
  const [porEstado,  setPorEstado]  = useState([])
  const [tendencia,  setTendencia]  = useState([])
  const [porFuente,  setPorFuente]  = useState([])
  const [urgentes,   setUrgentes]   = useState({ total: 0, leads: [] })
  const [funnel,     setFunnel]     = useState([])
  const [asesores,   setAsesores]   = useState([])
  const [actividad,  setActividad]  = useState(null)
  const [referidos,  setReferidos]  = useState(null)
  const [sparklines, setSparklines] = useState({ leads_creados: [], contactos_realizados: [] })
  // V095.1 — tendencia semanal 12 semanas (leads_nuevos vs leads_contactados).
  const [tendenciaSemanal, setTendenciaSemanal] = useState({ semanas: [] })
  // V094 — re-engagement workflow summary para card "Recontactos".
  const [recontactos, setRecontactos] = useState(null)
  const [isLoading,  setIsLoading]  = useState(true)
  const [error,      setError]      = useState(null)
  const [aiGreeting, setAiGreeting] = useState('')
  // Visibilidad del greeting — auto-dismiss para que no quede como ruido
  // permanente. Se persiste por dia para no re-mostrarlo en cada tab change.
  const [greetingVisible, setGreetingVisible] = useState(false)
  const [greetingFading, setGreetingFading]   = useState(false)

  const loadDashboard = async () => {
    setIsLoading(true)
    setError(null)
    try {
      loadCatalogs()

      // V096 — pasamos el rango temporal a todos los endpoints time-aware.
      // Los snapshot (leads-por-estado, leads-urgentes, leads-por-asesor)
      // ignoran params de fecha, no afecta nada agregarlos.
      const params = dateRange.apiParams

      // Requests base — todos los roles
      const requests = [
        api.get('/api/dashboard/resumen',           { params }), // 0 — period_metrics + previous_period
        api.get('/api/dashboard/leads-por-estado'),              // 1 — snapshot
        api.get('/api/dashboard/tendencia?dias=30'),             // 2 — snapshot
        api.get('/api/dashboard/leads-por-fuente',  { params }), // 3 — cohorte
        api.get('/api/dashboard/leads-urgentes'),                // 4 — snapshot operacional
        api.get('/api/dashboard/funnel-conversion', { params }), // 5 — cohorte
        api.get('/api/dashboard/referidos',         { params }), // 6 — totals + en_periodo
        api.get('/api/dashboard/sparklines',        { params }), // 7 — series diarias para mini-charts
        api.get('/api/dashboard/recontactos-summary', { params }), // 8 — V094: re-engagement KPI
        api.get('/api/dashboard/tendencia-semanal?semanas=12'),    // 9 — V095.1: 12 semanas dos series
      ]
      const teamOffset = requests.length
      if (canSeeTeam) {
        requests.push(api.get('/api/dashboard/leads-por-asesor', { params }))        // 10
        requests.push(api.get('/api/dashboard/actividad-equipo', { params }))        // 11
      }

      const results = await Promise.all(requests)
      setResumen(results[0].data)
      setPorEstado(results[1].data)
      setTendencia(results[2].data)
      setPorFuente(results[3].data)
      setUrgentes(results[4].data)
      setFunnel(results[5].data)
      setReferidos(results[6].data)
      setSparklines(results[7].data || { leads_creados: [], contactos_realizados: [] })
      setRecontactos(results[8].data)
      setTendenciaSemanal(results[9].data || { semanas: [] })
      if (canSeeTeam) {
        setAsesores(results[teamOffset].data)
        setActividad(results[teamOffset + 1].data)
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Error al cargar el dashboard.')
    } finally {
      setIsLoading(false)
    }
  }

  // V096 — recarga el dashboard cada vez que cambie el rango temporal
  useEffect(() => {
    loadDashboard()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dateRange.startDate, dateRange.endDate])

  useEffect(() => {
    // Greeting: one per day per user (cached en sessionStorage). Solo se
    // muestra brevemente — si el usuario ya lo vio en esta sesion (tab
    // change, refresh) no aparece de nuevo. Auto-dismiss a los 5s con
    // fade suave (300ms). El usuario tambien puede cerrarlo con X.
    const today = new Date().toISOString().slice(0, 10)
    const uid = user?.id || user?.user_id || 'anon'
    const cacheKey = `greeting_${uid}`
    const seenKey  = `greeting_seen_${uid}`
    const cached = (() => { try { return JSON.parse(sessionStorage.getItem(cacheKey)) } catch { return null } })()
    const alreadySeen = sessionStorage.getItem(seenKey) === today

    const showGreeting = (msg) => {
      if (!msg) return
      setAiGreeting(msg)
      if (alreadySeen) return  // Ya lo vio en esta sesion — no re-mostrar
      setGreetingVisible(true)
      sessionStorage.setItem(seenKey, today)
    }

    if (cached?.date === today) {
      showGreeting(cached.msg)
    } else {
      api.get('/api/greeting')
        .then(res => {
          const msg = res.data?.message || ''
          if (msg) {
            sessionStorage.setItem(cacheKey, JSON.stringify({ date: today, msg }))
          }
          showGreeting(msg)
        })
        .catch(() => {})
    }
  }, [user?.id, user?.user_id])

  // Auto-dismiss del greeting a los 5s (visible 5s + fade 300ms = 5.3s total).
  // 5s es el minimo recomendado WCAG para texto auto-dismiss (lectura
  // suficiente). Mantenemos animado para no ser brusco.
  useEffect(() => {
    if (!greetingVisible) return
    const fadeAt = setTimeout(() => setGreetingFading(true), 5000)
    const hideAt = setTimeout(() => {
      setGreetingVisible(false)
      setGreetingFading(false)
    }, 5300)
    return () => {
      clearTimeout(fadeAt)
      clearTimeout(hideAt)
    }
  }, [greetingVisible])

  const dismissGreeting = () => {
    setGreetingFading(true)
    setTimeout(() => {
      setGreetingVisible(false)
      setGreetingFading(false)
    }, 250)
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-4">
        <AlertCircle size={40} className="text-red-400" />
        <p className="text-gray-600 text-sm">{error}</p>
        <button onClick={loadDashboard} className="flex items-center gap-2 text-sm text-indigo-600 hover:underline">
          <RefreshCw size={14} /> Reintentar
        </button>
      </div>
    )
  }

  // V096 — datos period-aware
  const period   = resumen?.period_metrics          || {}
  const prevPeriod = resumen?.previous_period_metrics || {}
  const periodLabel = dateRange.activePresetLabel
  const sparkLeads     = sparklines?.leads_creados        || []
  const sparkContactos = sparklines?.contactos_realizados || []

  // Delta del card snapshot Total Leads — mantiene la nota "ultimos 7 dias"
  const delta7dias = resumen?.leads_7dias !== undefined ? `+${resumen.leads_7dias} últimos 7 días` : undefined

  return (
    <div className="space-y-5">

      {/* ── Encabezado ── */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">
            {getGreeting()}, {(user?.nombre_completo || user?.username || '').split(' ')[0]}
          </h1>
          <p className="text-sm text-gray-400 mt-0.5 capitalize">{todayLabel()}</p>
        </div>
        <button
          onClick={loadDashboard}
          disabled={isLoading}
          className="flex items-center gap-2 text-sm text-gray-500 hover:text-gray-700 px-3 py-1.5 rounded-lg hover:bg-gray-100 transition-colors disabled:opacity-40"
        >
          <RefreshCw size={14} className={isLoading ? 'animate-spin' : ''} />
          Actualizar
        </button>
      </div>

      {/* V096 — Selector temporal sticky. Default = ultimos 7 dias, persistido por usuario. */}
      <DateRangeSelector
        preset={dateRange.preset}
        startDate={dateRange.startDate}
        endDate={dateRange.endDate}
        rangeLabel={dateRange.rangeLabel}
        setPreset={dateRange.setPreset}
        setCustomRange={dateRange.setCustomRange}
      />

      {/* ── Saludo IA — auto-dismiss + fade + boton cerrar ── */}
      {greetingVisible && aiGreeting && (
        <div
          role="status"
          aria-live="polite"
          className={`flex items-center gap-2.5 px-4 py-2.5 rounded-xl bg-indigo-50 dark:bg-indigo-950/40 border border-indigo-100 dark:border-indigo-900/40 transition-all duration-300 ease-out ${
            greetingFading ? 'opacity-0 -translate-y-1' : 'opacity-100 translate-y-0'
          }`}
        >
          <Zap size={14} className="text-indigo-500 dark:text-indigo-400 shrink-0" />
          <p className="text-sm text-gray-700 dark:text-slate-200 flex-1">{aiGreeting}</p>
          <button
            onClick={dismissGreeting}
            className="text-indigo-400 hover:text-indigo-600 dark:hover:text-indigo-300 transition-colors p-0.5 rounded cursor-pointer"
            aria-label="Cerrar saludo"
            title="Cerrar"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* V070.78 (ADR-0010) — Team circuit breaker: banner solo para supervisores
          si su equipo entero esta bloqueado. Auto-refresca cada 30s. */}
      {user?.role === 'supervisor' && <TeamBlockedBanner />}

      {/* ── V064: Card "Tu día" (efecto Zeigarnik) ──
          V070.96 — Role-aware: solo asesor ve "Tu día" + "Próximo lead
          recomendado". Admin y supervisor NO tienen leads personales
          asignados; mostrarles "0% avanzado" + "Arrancá el día contactando"
          era confuso porque no es su rol operacional. El admin ve el
          resumen ejecutivo del CRM (KPIs + actividad equipo). El supervisor
          ve estado del equipo (ActividadEquipo abajo).
          Patron CRMs profesionales: dashboards distintos por rol. */}
      {user?.role === 'asesor' && !user?.role_id && (
        <MiDiaCard
          onClickPendientes={() => navigate('/leads?alerta=pendientes')}
          onClickNextLead={(lead) => navigate(`/leads/${lead.id}`)}
        />
      )}

      {/* ── Alerta: leads urgentes sin contactar ── */}
      <AlertaBanner
        urgentes={urgentes}
        isLoading={isLoading}
        onNavigate={() => navigate('/leads?alerta=urgentes')}
      />

      {/* ── KPIs principales ──
          V096 — combinacion snapshot + filtrado:
            - Total Leads, Referidos  → snapshot, badge HISTORICO
            - Leads/Contactados/Tasa  → filtrados al periodo, comparacion + sparkline
          V094 — agregada card "Recontactos" al final (6ta col en lg) con
          comparativa + sparkline. Patron re-engagement workflow. */}
      <div className="grid grid-cols-2 lg:grid-cols-6 gap-4">
        <KpiCard
          icon={Users}
          label="Total Leads"
          badge="HISTÓRICO"
          value={resumen?.total_leads?.toLocaleString()}
          delta={delta7dias}
          color="blue"
          isLoading={isLoading}
          onClick={() => navigate('/leads')}
        />
        <KpiCard
          icon={UserCheck}
          label={`Nuevos · ${periodLabel}`}
          value={period.leads_creados?.toLocaleString()}
          comparison={{ current: period.leads_creados, previous: prevPeriod.leads_creados }}
          sparkline={sparkLeads}
          color="green"
          isLoading={isLoading}
          onClick={() => navigate('/leads')}
        />
        <KpiCard
          icon={Phone}
          label={`Contactados · ${periodLabel}`}
          value={period.leads_contactados?.toLocaleString()}
          comparison={{ current: period.leads_contactados, previous: prevPeriod.leads_contactados }}
          sparkline={sparkContactos}
          color="amber"
          isLoading={isLoading}
          onClick={() => navigate('/leads')}
        />
        <KpiCard
          icon={TrendingUp}
          label={`Tasa Conversión · ${periodLabel}`}
          value={period.tasa_conversion_pct != null ? `${period.tasa_conversion_pct}%` : undefined}
          comparison={{ current: period.tasa_conversion_pct, previous: prevPeriod.tasa_conversion_pct }}
          color="purple"
          isLoading={isLoading}
        />
        <KpiCard
          icon={UserPlus}
          label="Referidos"
          badge="HISTÓRICO"
          value={referidos?.total?.toLocaleString()}
          comparison={referidos ? { current: referidos.en_periodo, previous: referidos.en_periodo_anterior } : undefined}
          delta={
            referidos
              ? `${referidos.en_periodo ?? 0} en período · ${referidos.ganados ?? 0} ganados${referidos.tasa_conversion_pct != null ? ` (${referidos.tasa_conversion_pct}%)` : ''}`
              : undefined
          }
          color="pink"
          isLoading={isLoading}
          onClick={() => navigate('/leads')}
        />
        <KpiCard
          icon={Zap}
          label={`Recontactos · ${periodLabel}`}
          value={recontactos?.en_periodo?.toLocaleString()}
          comparison={recontactos ? { current: recontactos.en_periodo, previous: recontactos.en_periodo_anterior } : undefined}
          sparkline={recontactos?.daily || []}
          sparklineColor="#f59e0b"
          delta={(() => {
            // V094.1 — escalacion: rojo predomina si hay >=48h sin atender.
            if (!recontactos) return undefined
            const red    = recontactos.sin_atender_red    || 0
            const amber  = recontactos.sin_atender_amber  || 0
            const dias   = recontactos.mas_viejo_dias
            if (red > 0) {
              const d = dias && dias >= 1 ? `${dias}d` : '+48h'
              return `🚨 ${red} URGENTE${red !== 1 ? 'S' : ''} (${d})${amber > 0 ? ` · ${amber} reciente${amber !== 1 ? 's' : ''}` : ''}`
            }
            if (amber > 0) return `${amber} sin atender (<48h)`
            return undefined
          })()}
          color="amber"
          isLoading={isLoading}
          onClick={() => navigate('/leads')}
        />
      </div>

      {/* ── Actividad del equipo (admin/supervisor) ──
          V096 — 2 cards en vez de 4: contactos en periodo (responde al filtro)
          + citas hoy (snapshot, siempre operacional). */}
      {canSeeTeam && (
        <ActividadEquipo
          data={actividad}
          isLoading={isLoading}
          periodLabel={periodLabel}
          onNavigateToAgenda={() => navigate('/agenda')}
        />
      )}

      {/* ── Estados del funnel / métricas clave (admin/supervisor) ── */}
      {canSeeTeam && (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
          <MiniStat
            label="Tibios"
            value={period.tibios}
            comparison={{ current: period.tibios, previous: prevPeriod.tibios }}
            color="amber"
            isLoading={isLoading}
            onClick={() => navigate('/leads')}
          />
          <MiniStat
            label="Calientes"
            value={period.calientes}
            comparison={{ current: period.calientes, previous: prevPeriod.calientes }}
            color="rose"
            isLoading={isLoading}
            onClick={() => navigate('/leads')}
          />
          <MiniStat
            label="En seguimiento"
            value={period.en_seguimiento}
            comparison={{ current: period.en_seguimiento, previous: prevPeriod.en_seguimiento }}
            color="sky"
            isLoading={isLoading}
            onClick={() => navigate('/leads')}
          />
          <MiniStat
            label="Matrículas"
            value={period.matriculas}
            comparison={{ current: period.matriculas, previous: prevPeriod.matriculas }}
            color="green"
            isLoading={isLoading}
            onClick={() => navigate('/leads')}
          />
          <MiniStat
            label="Perdidos"
            value={period.perdidos}
            comparison={{ current: period.perdidos, previous: prevPeriod.perdidos }}
            color="red"
            isLoading={isLoading}
            onClick={() => navigate('/leads')}
          />
          <MiniStat
            label="COD"
            value={period.cod}
            comparison={{ current: period.cod, previous: prevPeriod.cod }}
            color="purple"
            isLoading={isLoading}
            onClick={() => navigate('/leads')}
          />
        </div>
      )}

      {/* ── Funnel de conversión + Cumplimiento de metas ── */}
      <div className={`grid gap-4 ${canSeeTeam ? 'grid-cols-1 lg:grid-cols-3' : 'grid-cols-1'}`}>
        <Card className={canSeeTeam ? 'lg:col-span-2' : ''}>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold text-gray-700 dark:text-slate-200">
              Funnel de Conversión
            </CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <FunnelChart data={funnel} isLoading={isLoading} />
          </CardContent>
        </Card>
        {canSeeTeam && <MetasWidget navigate={navigate} />}
      </div>

      {/* ── Gráficos: estado | fuente | top asesores ── */}
      <div className={`grid gap-4 ${canSeeTeam ? 'grid-cols-1 lg:grid-cols-3' : 'grid-cols-1 lg:grid-cols-2'}`}>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold text-gray-700 dark:text-slate-200">Leads por Estado</CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <BarChart data={porEstado} isLoading={isLoading} />
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold text-gray-700 dark:text-slate-200">Leads por Fuente</CardTitle>
          </CardHeader>
          <CardContent className="pt-0">
            <DonutChart data={porFuente} isLoading={isLoading} />
          </CardContent>
        </Card>

        {canSeeTeam && (
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-semibold text-gray-700 dark:text-slate-200">Top Asesores</CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <TopAsesores data={asesores} isLoading={isLoading} />
            </CardContent>
          </Card>
        )}
      </div>

      {/* ── Tendencia — últimos 30 días ── */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-semibold text-gray-700 dark:text-slate-200">
            Ingreso de Leads — Últimos 30 días
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          <LineChart data={tendencia} isLoading={isLoading} />
        </CardContent>
      </Card>

      {/* V095.1 — Tendencia semanal 12 semanas: dos series (ingresados vs
          contactados). Patron CRMs profesionales — el primer widget que
          transmite "el negocio se mueve" en lugar de fotos estaticas. */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-semibold text-gray-700 dark:text-slate-200 flex items-center justify-between">
            <span>Tendencia semanal — Últimas 12 semanas</span>
            <span className="flex items-center gap-3 text-xs font-normal">
              <span className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded-full bg-indigo-500" />
                <span className="text-gray-500 dark:text-slate-400">Ingresados</span>
              </span>
              <span className="flex items-center gap-1">
                <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" />
                <span className="text-gray-500 dark:text-slate-400">Contactados</span>
              </span>
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="pt-0">
          <WeeklyTrendChart data={tendenciaSemanal.semanas} isLoading={isLoading} />
        </CardContent>
      </Card>

    </div>
  )
}

/* ─── V095.1 — Tendencia semanal (dual line + tasa de contacto) ─────────── */
function WeeklyTrendChart({ data, isLoading }) {
  if (isLoading) return <div className="h-56 bg-gray-100 dark:bg-slate-800/60 rounded-xl animate-pulse" />
  if (!data || data.length === 0)
    return <p className="text-sm text-gray-400 dark:text-slate-500 py-10 text-center">Sin datos disponibles</p>

  const W = 900, H = 280, padX = 32, padTop = 32, padBot = 40
  const maxIngresados = Math.max(...data.map(d => d.leads_nuevos || 0), 1)
  const plotH = H - padTop - padBot

  const ptsIng = data.map((d, i) => ({
    x: padX + (i / Math.max(data.length - 1, 1)) * (W - padX * 2),
    y: padTop + plotH - ((d.leads_nuevos || 0) / maxIngresados) * plotH,
    label: d.leads_nuevos || 0,
    semana: d.semana,
  }))
  const ptsCont = data.map((d, i) => ({
    x: padX + (i / Math.max(data.length - 1, 1)) * (W - padX * 2),
    y: padTop + plotH - ((d.leads_contactados || 0) / maxIngresados) * plotH,
    label: d.leads_contactados || 0,
  }))

  const polyIng = ptsIng.map(p => `${p.x},${p.y}`).join(' ')
  const polyCont = ptsCont.map(p => `${p.x},${p.y}`).join(' ')
  const areaIng = `${ptsIng[0].x},${H - padBot} ${polyIng} ${ptsIng[ptsIng.length - 1].x},${H - padBot}`

  const totalIng = data.reduce((s, d) => s + (d.leads_nuevos || 0), 0)
  const totalCont = data.reduce((s, d) => s + (d.leads_contactados || 0), 0)
  const tasaContacto = totalIng > 0 ? (100 * totalCont / totalIng).toFixed(1) : '0.0'

  // Etiqueta corta de la semana — "DD/MM" del lunes que ancla la serie.
  const fmtSemana = (iso) => {
    if (!iso) return ''
    const [, m, d] = iso.split('-')
    return `${d}/${m}`
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-5 text-xs">
        <div>
          <span className="text-gray-400 dark:text-slate-400">Total ingresados: </span>
          <span className="font-bold text-indigo-600 dark:text-indigo-400 tabular-nums">{totalIng.toLocaleString()}</span>
        </div>
        <div>
          <span className="text-gray-400 dark:text-slate-400">Total contactados: </span>
          <span className="font-bold text-emerald-600 dark:text-emerald-400 tabular-nums">{totalCont.toLocaleString()}</span>
        </div>
        <div>
          <span className="text-gray-400 dark:text-slate-400">Tasa de contacto: </span>
          <span className="font-bold text-gray-800 dark:text-slate-100 tabular-nums">{tasaContacto}%</span>
        </div>
      </div>

      <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-72">
        <defs>
          <linearGradient id="areaGradWeekly" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#6366f1" stopOpacity="0.25" />
            <stop offset="100%" stopColor="#6366f1" stopOpacity="0.01" />
          </linearGradient>
        </defs>

        <polygon points={areaIng} fill="url(#areaGradWeekly)" />

        {/* Linea ingresados (indigo) */}
        <polyline points={polyIng} fill="none" stroke="#6366f1" strokeWidth="3"
          strokeLinejoin="round" strokeLinecap="round" />

        {/* Linea contactados (emerald) */}
        <polyline points={polyCont} fill="none" stroke="#10b981" strokeWidth="3"
          strokeLinejoin="round" strokeLinecap="round" strokeDasharray="0" />

        {/* Puntos ambas series */}
        {ptsIng.map((p, i) => (
          <circle key={`i-${i}`} cx={p.x} cy={p.y} r="4" fill="#6366f1"
            stroke="white" strokeWidth="2" />
        ))}
        {ptsCont.map((p, i) => (
          <circle key={`c-${i}`} cx={p.x} cy={p.y} r="3.5" fill="#10b981"
            stroke="white" strokeWidth="2" />
        ))}

        {/* Etiquetas valores ingresados (arriba) */}
        {ptsIng.map((p, i) => (
          <text key={`ni-${i}`} x={p.x} y={p.y - 10} fontSize="11" fontWeight="600"
            fill="#818cf8" textAnchor="middle">
            {p.label}
          </text>
        ))}

        {/* Etiquetas semana en eje X */}
        {ptsIng.map((p, i) => (
          <text key={`sem-${i}`} x={p.x} y={H - 8} fontSize="11" className="fill-gray-500 dark:fill-slate-400"
            textAnchor="middle" fontWeight="500">
            {fmtSemana(p.semana)}
          </text>
        ))}
      </svg>
    </div>
  )
}
