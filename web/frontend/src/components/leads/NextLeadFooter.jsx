/**
 * NextLeadFooter — "Próximo lead recomendado" tipo Netflix autoplay.
 *
 * Footer sticky en LeadDetalle que muestra siempre el siguiente lead
 * prioritario para contactar. Patron Netflix "Siguiente episodio":
 * elimina la friccion de decidir cual lead atacar despues. El asesor
 * cierra el lead actual y queda en automatico empujado al siguiente.
 *
 * Anti-ansiedad:
 *   - Si no hay siguiente lead pendiente, se oculta (no muestra "vacio").
 *   - Dismissable (X) — el user puede ocultarlo si quiere terminar el dia.
 *   - Solo aparece tras 1.5s para no abrumar al cargar la pagina.
 */
import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ChevronRight, X, Sparkles } from 'lucide-react'
import api from '@/lib/api'

export default function NextLeadFooter({ currentLeadId }) {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [visible, setVisible] = useState(false)
  const [dismissed, setDismissed] = useState(false)

  // Refrescar cuando cambia el lead actual (navegacion intra-app).
  useEffect(() => {
    if (!currentLeadId) return
    setDismissed(false)
    setVisible(false)
    let cancelled = false
    api.get(`/api/dashboard/mi-dia?exclude_lead_id=${currentLeadId}`)
      .then(res => {
        if (cancelled) return
        const next = res.data?.next_recommended_lead
        if (next && next.id !== currentLeadId) {
          setData(next)
          // Delay 1.5s para que no salte de golpe — sensacion de discovery
          setTimeout(() => { if (!cancelled) setVisible(true) }, 1500)
        }
      })
      .catch(() => { })
    return () => { cancelled = true }
  }, [currentLeadId])

  if (!data || !visible || dismissed) return null

  const fullName = [data.nombres, data.apellidos].filter(Boolean).join(' ') || 'Sin nombre'
  const initial = (data.nombres || '?')[0]?.toUpperCase()
  const hours = Math.round(data.horas_sin_contacto || 0)
  const isCaliente = (data.calidad_codigo || '').toUpperCase() === 'CALIENTE'

  return (
    <div className="fixed bottom-4 right-4 z-40 max-w-sm animate-slide-up">
      <style>{`
        @keyframes nlf-slide-up {
          from { opacity: 0; transform: translateY(12px); }
          to   { opacity: 1; transform: translateY(0); }
        }
        .animate-slide-up { animation: nlf-slide-up 0.35s ease-out both; }
      `}</style>
      <div className="bg-white border border-gray-200 rounded-2xl shadow-[0_12px_40px_rgba(0,0,0,0.15)] p-3.5 flex items-center gap-3">
        <button
          onClick={() => navigate(`/leads/${data.id}`)}
          className="flex items-center gap-3 flex-1 min-w-0 text-left group"
          type="button"
        >
          {/* Avatar inicial con sparkle */}
          <div className="relative shrink-0">
            <div className={`w-10 h-10 rounded-full flex items-center justify-center text-sm font-bold ${isCaliente
                ? 'bg-red-100 text-red-600 ring-2 ring-red-200'
                : 'bg-indigo-100 text-indigo-600 ring-2 ring-indigo-200'
              }`}>
              {initial}
            </div>
            <Sparkles size={11} className="absolute -top-1 -right-1 text-amber-400 fill-amber-300" />
          </div>

          {/* Contenido */}
          <div className="flex-1 min-w-0">
            <p className="text-[10px] uppercase tracking-wider font-bold text-indigo-500 mb-0.5">
              Siguiente lead recomendado
            </p>
            <p className="text-sm font-semibold text-gray-900 truncate group-hover:text-indigo-600 transition-colors">
              {fullName}
            </p>
            <p className="text-[11px] text-gray-500 mt-0.5 flex items-center gap-1 flex-wrap">
              {isCaliente && (
                <span className="inline-flex items-center px-1.5 py-0.5 rounded text-[10px] font-bold bg-red-50 text-red-600 border border-red-100">
                  CALIENTE
                </span>
              )}
              <span>{hours}h sin contacto</span>
              <span className="text-gray-300">·</span>
              <span>{data.estado_nombre}</span>
            </p>
          </div>

          <ChevronRight size={18} className="text-gray-300 group-hover:text-indigo-500 transition-colors shrink-0" />
        </button>

        {/* Dismiss */}
        <button
          onClick={() => setDismissed(true)}
          className="text-gray-300 hover:text-gray-600 p-1 rounded transition-colors shrink-0"
          title="Ocultar sugerencia"
          aria-label="Cerrar sugerencia"
          type="button"
        >
          <X size={14} />
        </button>
      </div>
    </div>
  )
}
