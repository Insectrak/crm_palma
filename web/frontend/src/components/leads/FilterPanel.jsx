import { X } from 'lucide-react'
import { getSubestadosForEstado } from '@/components/leads/CambioEstadoModal'

/** Panel de filtros adicionales */
export default function FilterPanel({
  filters, onChange, fuentes = [], asesores, supervisores = [], campanas = [],
  estados = [], estadoFilter = '', onChangeEstado,
  calidades = [],
  canFilterByAsesor, onClear,
}) {
  const selectedEstadoObj = estados.find(es => String(es.id) === String(estadoFilter || filters.estado_id))
  const subestadosDisponibles = getSubestadosForEstado(selectedEstadoObj?.nombre)

  const origenOptions = (() => {
    const list = [
      { value: 'tiktok', label: 'TikTok' },
      { value: 'facebook', label: 'Facebook' },
      { value: 'instagram', label: 'Instagram' },
      { value: 'whatsapp', label: 'WhatsApp' },
    ]
    const canonicalSet = new Set(['tiktok', 'facebook', 'fb', 'meta', 'instagram', 'ig', 'whatsapp', 'wa'])
    fuentes.forEach(f => {
      const key = (f.nombre || '').trim().toLowerCase()
      if (key && !canonicalSet.has(key) && !list.some(o => o.value === key)) {
        list.push({ value: key, label: f.nombre })
      }
    })
    return list
  })()

  return (
    <div className="bg-gray-50 border border-gray-200 rounded-lg p-4 grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
      <div>
        <label className="block text-xs font-medium text-gray-500 mb-1">Estado</label>
        <select
          value={estadoFilter}
          onChange={e => {
            if (onChangeEstado) onChangeEstado(e.target.value)
            if (filters.subestado) onChange('subestado', '')
          }}
          className="w-full text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
        >
          <option value="">Todos</option>
          {estados.map(es => (
            <option key={es.id} value={es.id}>{es.nombre}</option>
          ))}
        </select>
      </div>

      {subestadosDisponibles.length > 0 && (
        <div className="animate-in fade-in">
          <label className="block text-xs font-semibold text-indigo-600 mb-1 truncate" title={`Subestado de ${selectedEstadoObj?.nombre}`}>
            Subestado ({selectedEstadoObj?.nombre})
          </label>
          <select
            value={filters.subestado || ''}
            onChange={e => onChange('subestado', e.target.value)}
            className="w-full text-sm border border-indigo-200 rounded-md px-2 py-1.5 bg-indigo-50/60 text-indigo-950 focus:outline-none focus:ring-2 focus:ring-indigo-500 font-medium"
          >
            <option value="">Todos los subestados</option>
            {subestadosDisponibles.map(sub => (
              <option key={sub} value={sub}>{sub}</option>
            ))}
          </select>
        </div>
      )}

      <div>
        <label className="block text-xs font-medium text-gray-500 mb-1">Origen</label>
        <select
          value={filters.origen || ''}
          onChange={e => onChange('origen', e.target.value)}
          className="w-full text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
        >
          <option value="">Todos</option>
          {origenOptions.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-500 mb-1">Fuente</label>
        <select
          value={filters.fuente_id || ''}
          onChange={e => onChange('fuente_id', e.target.value)}
          className="w-full text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
        >
          <option value="">Todas</option>
          {fuentes.map(f => (
            <option key={f.id} value={f.id} className="capitalize">{f.nombre}</option>
          ))}
        </select>
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-500 mb-1">Estado en Cola</label>
        <select
          value={filters.estado_cola || ''}
          onChange={e => onChange('estado_cola', e.target.value)}
          className="w-full text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500 font-medium"
        >
          <option value="">Todos</option>
          <option value="estancados">⚠️ Estancados (&gt;24h)</option>
          <option value="pendientes">⏳ Pendientes (&lt;24h)</option>
          <option value="en_cola">📥 Todos en cola</option>
          <option value="asignados">👤 Asignados a asesor</option>
        </select>
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-500 mb-1">Próxima gestión</label>
        <select
          value={filters.filtro_fecha_gestion || ''}
          onChange={e => onChange('filtro_fecha_gestion', e.target.value)}
          className="w-full text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500 font-medium"
        >
          <option value="">Todas</option>
          <option value="vencidas">⚠️ Vencidas (&lt; hoy/ahora)</option>
          <option value="sin_fecha">❓ Sin fecha asignada</option>
          <option value="hoy">📅 Para hoy</option>
          <option value="al_dia">✅ Al día / Futuras</option>
        </select>
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-500 mb-1">Fecha de cita</label>
        <select
          value={filters.filtro_fecha_cita || ''}
          onChange={e => onChange('filtro_fecha_cita', e.target.value)}
          className="w-full text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500 font-medium"
        >
          <option value="">Todas</option>
          <option value="vencidas">⚠️ Vencidas (&lt; hoy/ahora)</option>
          <option value="sin_fecha">❓ Sin fecha asignada</option>
          <option value="hoy">📅 Para hoy</option>
          <option value="al_dia">✅ Al día / Futuras</option>
        </select>
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-500 mb-1">Atención de cita</label>
        <select
          value={filters.filtro_cita_atendida || ''}
          onChange={e => onChange('filtro_cita_atendida', e.target.value)}
          className="w-full text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500 font-medium"
        >
          <option value="">Todas</option>
          <option value="no_atendidas">⏳ No atendidas / Pendientes</option>
          <option value="atendidas">✅ Atendidas</option>
          <option value="no_asistio">❌ No asistió</option>
        </select>
      </div>

      {canFilterByAsesor && supervisores.length > 0 && (
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Supervisor</label>
          <select
            value={filters.supervisor_id || ''}
            onChange={e => onChange('supervisor_id', e.target.value)}
            className="w-full text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <option value="">Todos</option>
            {supervisores.map(s => (
              <option key={s.id} value={s.id}>{s.nombre_completo || s.email}</option>
            ))}
          </select>
        </div>
      )}

      {canFilterByAsesor && (
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Asesor</label>
          <select
            value={filters.asesor_id || ''}
            onChange={e => onChange('asesor_id', e.target.value)}
            className="w-full text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <option value="">Todos</option>
            {(() => {
              const asesoresList = asesores.filter(a => a.role !== 'supervisor')
              const supervisoresList = asesores.filter(a => a.role === 'supervisor')
              return (
                <>
                  {asesoresList.length > 0 && (
                    <optgroup label="Asesores">
                      {asesoresList.map(a => (
                        <option key={a.id} value={a.id}>{a.nombre_completo || a.email}</option>
                      ))}
                    </optgroup>
                  )}
                  {supervisoresList.length > 0 && (
                    <optgroup label="Supervisores">
                      {supervisoresList.map(a => (
                        <option key={a.id} value={a.id}>{a.nombre_completo || a.email}</option>
                      ))}
                    </optgroup>
                  )}
                </>
              )
            })()}
          </select>
        </div>
      )}

      {canFilterByAsesor && (
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1" title="Leads que pertenecieron a este asesor en el pasado">
            Asesor histórico
          </label>
          <select
            value={filters.asesor_historico_id || ''}
            onChange={e => onChange('asesor_historico_id', e.target.value)}
            className="w-full text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <option value="">Todos</option>
            {(() => {
              const asesoresList = asesores.filter(a => a.role !== 'supervisor')
              const supervisoresList = asesores.filter(a => a.role === 'supervisor')
              return (
                <>
                  {asesoresList.length > 0 && (
                    <optgroup label="Asesores">
                      {asesoresList.map(a => (
                        <option key={a.id} value={a.id}>{a.nombre_completo || a.email}</option>
                      ))}
                    </optgroup>
                  )}
                  {supervisoresList.length > 0 && (
                    <optgroup label="Supervisores">
                      {supervisoresList.map(a => (
                        <option key={a.id} value={a.id}>{a.nombre_completo || a.email}</option>
                      ))}
                    </optgroup>
                  )}
                </>
              )
            })()}
          </select>
        </div>
      )}

      {campanas.length > 0 && (
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Campaña</label>
          <select
            value={filters.campana || ''}
            onChange={e => onChange('campana', e.target.value)}
            className="w-full text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <option value="">Todas</option>
            {campanas.map(c => (
              <option key={c} value={c}>{c}</option>
            ))}
          </select>
        </div>
      )}

      {calidades.length > 0 && (
        <div>
          <label className="block text-xs font-medium text-gray-500 mb-1">Calidad</label>
          <select
            value={filters.calidad || ''}
            onChange={e => onChange('calidad', e.target.value)}
            className="w-full text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
          >
            <option value="">Todas</option>
            {calidades.map(c => (
              <option key={c.codigo || c.id} value={c.codigo}>{c.nombre}</option>
            ))}
          </select>
        </div>
      )}

      {/* Rango de fechas — Desde y Hasta agrupados en un solo slot col-span-2,
          inputs lado a lado con flecha entre ambos. Patron premium estilo
          CRMs profesionales 'Date Range Filter'. */}
      <div className="col-span-2">
        <label className="block text-xs font-medium text-gray-500 mb-1">Período de creación</label>
        <div className="flex items-center gap-2">
          <input
            type="date"
            value={filters.fecha_desde || ''}
            onChange={e => onChange('fecha_desde', e.target.value)}
            max={filters.fecha_hasta || undefined}
            aria-label="Desde"
            className="flex-1 min-w-0 text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
          <span className="text-gray-400 text-xs select-none shrink-0">→</span>
          <input
            type="date"
            value={filters.fecha_hasta || ''}
            onChange={e => onChange('fecha_hasta', e.target.value)}
            min={filters.fecha_desde || undefined}
            aria-label="Hasta"
            className="flex-1 min-w-0 text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
          />
        </div>
      </div>

      <div>
        <label className="block text-xs font-medium text-gray-500 mb-1">Antecedentes</label>
        <label className="flex items-center gap-2 text-sm text-gray-700 h-[34px] px-2 bg-white border border-gray-200 rounded-md cursor-pointer hover:bg-gray-50">
          <input
            type="checkbox"
            checked={!!filters.con_antecedentes}
            onChange={e => onChange('con_antecedentes', e.target.checked)}
            className="rounded border-gray-300 text-indigo-600 focus:ring-indigo-500"
          />
          <span>Solo con antecedentes</span>
        </label>
      </div>

      <div className="flex items-end">
        <button
          onClick={onClear}
          className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1"
        >
          <X size={12} /> Limpiar todo
        </button>
      </div>
    </div>
  )
}
