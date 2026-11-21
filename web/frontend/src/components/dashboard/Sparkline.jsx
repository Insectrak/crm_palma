/**
 * Sparkline — mini line chart inline para KPI cards (V096).
 *
 * Uso:
 *   <Sparkline data={[{date:'2026-06-13', count:5}, ...]} color="#6366f1" />
 *
 * - Sin ejes, sin grid, sin tooltip — solo la linea.
 * - Si data es vacio o tiene <2 puntos, no renderiza nada.
 * - Width 100% del padre, height fijo (configurable).
 * - Usa recharts (ya en deps).
 */
import { Area, AreaChart, ResponsiveContainer } from 'recharts'

export default function Sparkline({ data, color = '#6366f1', height = 28 }) {
  if (!Array.isArray(data) || data.length < 2) return null

  // Normaliza al schema {x, y} que recharts entiende sin custom data keys
  const normalized = data.map((d, i) => ({
    x: i,
    y: typeof d === 'number' ? d : Number(d.count ?? d.value ?? 0),
  }))

  const gradientId = `spark-${color.replace('#', '')}`

  return (
    <div style={{ width: '100%', height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={normalized} margin={{ top: 2, bottom: 2, left: 0, right: 0 }}>
          <defs>
            <linearGradient id={gradientId} x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%"   stopColor={color} stopOpacity={0.35} />
              <stop offset="100%" stopColor={color} stopOpacity={0}   />
            </linearGradient>
          </defs>
          <Area
            type="monotone"
            dataKey="y"
            stroke={color}
            strokeWidth={1.5}
            fill={`url(#${gradientId})`}
            isAnimationActive={false}
            dot={false}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}
