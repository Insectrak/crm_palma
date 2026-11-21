/** Pills de estado con conteo para filtro rápido.
 *
 * V094 — soporta una pill extra opcional (`extraPill`) renderizada al
 * final de la fila. Caso de uso: "Recontactos sin atender" en amber,
 * orthogonal al pipeline de estados. Mantener en la misma fila evita
 * agregar otra fila vertical y conserva la jerarquia visual.
 */
export default function EstadoPills({ estados, selected, onSelect, counts, total, extraPill }) {
  return (
    <div className="flex gap-1.5 overflow-x-auto pb-1 flex-wrap items-center">
      <button
        onClick={() => onSelect('')}
        className={`shrink-0 flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium transition-all border ${
          !selected
            ? 'bg-slate-800 text-white border-slate-800'
            : 'bg-white text-gray-500 border-gray-200 hover:border-gray-400 hover:text-gray-700'
        }`}
      >
        Todos
        {total > 0 && (
          <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${
            !selected ? 'bg-white/20 text-white' : 'bg-gray-100 text-gray-500'
          }`}>
            {total.toLocaleString()}
          </span>
        )}
      </button>
      {estados.map(e => {
        const isActive = selected === String(e.id)
        const count = counts[e.id] || 0
        return (
          <button
            key={e.id}
            onClick={() => onSelect(isActive ? '' : String(e.id))}
            className={`shrink-0 flex items-center gap-1.5 px-3 py-1 rounded-full text-xs font-medium transition-all border ${
              isActive ? 'text-white border-transparent' : 'bg-white text-gray-500 border-gray-200 hover:border-gray-400'
            }`}
            style={isActive ? { backgroundColor: e.color_hex, borderColor: e.color_hex } : {}}
          >
            {e.nombre}
            {count > 0 && (
              <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${
                isActive ? 'bg-white/25 text-white' : 'text-white'
              }`}
              style={!isActive ? { backgroundColor: e.color_hex + 'cc' } : {}}
              >
                {count.toLocaleString()}
              </span>
            )}
          </button>
        )
      })}
      {extraPill && (
        <>
          <span className="shrink-0 h-4 w-px bg-gray-200 mx-1" aria-hidden="true" />
          {extraPill}
        </>
      )}
    </div>
  )
}
