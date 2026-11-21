/**
 * SedesManager — CRUD admin de crm.sedes (V065).
 *
 * Se monta como tab dentro de Configuración. Lista todas las sedes con
 * count de leads, badge de estado activo/archivado, acciones de editar
 * y eliminar (soft o hard segun haya leads).
 *
 * SRP: este componente solo gestiona la edicion de sedes. El filtro
 * de leads por sede vive en AdvancedFilters / Leads.jsx — esa
 * separacion es la que hace OCP el sistema (agregar features a sedes
 * no toca el flujo de leads).
 */
import { useEffect, useState } from 'react'
import {
  Plus, Edit2, Trash2, Power, MapPin, RefreshCw, X,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import api from '@/lib/api'
import ConfirmDialog from '@/components/shared/ConfirmDialog'
import InfoDialog from '@/components/shared/InfoDialog'
import SedeFormModal from './SedeFormModal'

export default function SedesManager() {
  const [sedes, setSedes]     = useState([])
  const [loading, setLoading] = useState(true)
  const [editing, setEditing] = useState(null)        // null | sede | 'new'
  const [confirmDelete, setConfirmDelete] = useState(null)
  const [info, setInfo]       = useState(null)

  const load = async () => {
    setLoading(true)
    try {
      const res = await api.get('/api/admin/sedes')
      setSedes(res.data || [])
    } catch (err) {
      setInfo({
        variant: 'error',
        title: 'No se pudieron cargar las sedes',
        message: err?.response?.data?.detail || 'Error de red.',
      })
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  // Re-throw los errores para que el modal los muestre inline (mantiene
  // el form abierto sin perder los datos del user). Sin try/catch porque
  // ya lo hace el modal.
  const handleSave = async (payload) => {
    if (editing && editing !== 'new' && editing.id) {
      await api.patch(`/api/admin/sedes/${editing.id}`, payload)
    } else {
      await api.post('/api/admin/sedes', payload)
    }
    setEditing(null)
    load()
  }

  const handleDelete = async () => {
    if (!confirmDelete) return
    const target = confirmDelete
    setConfirmDelete(null)
    try {
      const res = await api.delete(`/api/admin/sedes/${target.id}`)
      if (res.data?.action === 'archived') {
        setInfo({
          variant: 'info',
          title: 'Sede archivada',
          message: `"${target.nombre}" tiene ${res.data.leads_count} leads asociados. Se archivó (no es seleccionable para nuevos leads) pero queda visible en filtros históricos.`,
        })
      }
      load()
    } catch (err) {
      setInfo({
        variant: 'error',
        title: 'No se pudo eliminar la sede',
        message: err?.response?.data?.detail || 'Error inesperado.',
      })
    }
  }

  return (
    <div>
      {/* Header */}
      <div className="flex items-center justify-between mb-5">
        <div>
          <h2 className="text-lg font-semibold text-gray-900 flex items-center gap-2">
            <MapPin size={18} className="text-indigo-500" />
            Sedes
          </h2>
          <p className="text-sm text-gray-500 mt-0.5">
            Ubicaciones de servicio. Cada lead puede asignarse a una sede
            (donde el cliente quiere ser atendido).
          </p>
        </div>
        <Button onClick={() => setEditing('new')} className="gap-1.5">
          <Plus size={14} />
          Nueva sede
        </Button>
      </div>

      {/* Tabla */}
      {loading && sedes.length === 0 ? (
        <div className="flex items-center justify-center py-12 text-gray-400">
          <RefreshCw size={18} className="animate-spin mr-2" />
          <span className="text-sm">Cargando sedes…</span>
        </div>
      ) : sedes.length === 0 ? (
        <div className="border border-dashed border-gray-200 rounded-xl py-12 text-center">
          <MapPin size={32} className="text-gray-300 mx-auto mb-3" />
          <p className="text-sm text-gray-500 font-medium">Aún no creaste ninguna sede.</p>
          <p className="text-xs text-gray-400 mt-1">
            Las sedes son opcionales — solo necesarias si tu cliente tiene más de una ubicación.
          </p>
          <button
            onClick={() => setEditing('new')}
            className="mt-4 inline-flex items-center gap-1.5 text-sm text-indigo-600 hover:text-indigo-700 font-medium"
            type="button"
          >
            <Plus size={14} /> Crear la primera sede
          </button>
        </div>
      ) : (
        <div className="overflow-hidden border border-gray-100 rounded-xl">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-100">
              <tr>
                <th className="text-left px-3 py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wide">Sede</th>
                <th className="text-left px-3 py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wide">Ciudad</th>
                <th className="text-left px-3 py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wide">Teléfono</th>
                <th className="text-left px-3 py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wide">Leads</th>
                <th className="text-left px-3 py-2.5 text-xs font-semibold text-gray-500 uppercase tracking-wide">Estado</th>
                <th className="px-3 py-2.5 w-24"></th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-50">
              {sedes.map(s => (
                <tr key={s.id} className="hover:bg-gray-50/60 transition-colors">
                  <td className="px-3 py-3">
                    <div className="flex items-center gap-2">
                      <div
                        className="w-2.5 h-2.5 rounded-full shrink-0"
                        style={{ backgroundColor: s.color_hex || '#6366f1' }}
                      />
                      <div className="min-w-0">
                        <p className="text-sm font-medium text-gray-900 leading-tight truncate">
                          {s.nombre}
                        </p>
                        <p className="text-[11px] text-gray-400 font-mono leading-tight">
                          {s.codigo}
                        </p>
                      </div>
                    </div>
                  </td>
                  <td className="px-3 py-3 text-sm text-gray-600">{s.ciudad || '—'}</td>
                  <td className="px-3 py-3 text-sm text-gray-600 font-mono">{s.telefono || '—'}</td>
                  <td className="px-3 py-3">
                    <span className={`inline-flex items-center justify-center min-w-[28px] px-1.5 py-0.5 rounded-full text-xs font-semibold ${
                      s.leads_count > 0
                        ? 'bg-indigo-50 text-indigo-700 border border-indigo-100'
                        : 'bg-gray-50 text-gray-400 border border-gray-100'
                    }`}>
                      {s.leads_count}
                    </span>
                  </td>
                  <td className="px-3 py-3">
                    {s.activo ? (
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-emerald-50 text-emerald-700 border border-emerald-100">
                        Activa
                      </span>
                    ) : (
                      <span className="inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-500 border border-gray-200">
                        Archivada
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-3 text-right">
                    <div className="flex items-center justify-end gap-0.5">
                      <button
                        onClick={() => setEditing(s)}
                        className="p-1.5 rounded hover:bg-indigo-50 text-gray-400 hover:text-indigo-500"
                        title="Editar"
                      >
                        <Edit2 size={13} />
                      </button>
                      <button
                        onClick={() => setConfirmDelete(s)}
                        className="p-1.5 rounded hover:bg-red-50 text-gray-400 hover:text-red-500"
                        title={s.leads_count > 0 ? 'Archivar (tiene leads)' : 'Eliminar'}
                      >
                        {s.leads_count > 0 ? <Power size={13} /> : <Trash2 size={13} />}
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing && (
        <SedeFormModal
          initial={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
          onSave={handleSave}
        />
      )}

      <ConfirmDialog
        open={!!confirmDelete}
        variant="danger"
        title={confirmDelete?.leads_count > 0 ? 'Archivar sede' : 'Eliminar sede'}
        confirmLabel={confirmDelete?.leads_count > 0 ? 'Sí, archivar' : 'Sí, eliminar'}
        cancelLabel="Cancelar"
        message={confirmDelete
          ? (confirmDelete.leads_count > 0
              ? `La sede "${confirmDelete.nombre}" tiene ${confirmDelete.leads_count} leads asociados. NO se puede borrar — se va a archivar (no aparecerá para nuevos leads pero los existentes mantienen la referencia).`
              : `Vas a eliminar la sede "${confirmDelete.nombre}". No tiene leads asociados — el borrado es permanente.`)
          : ''}
        onConfirm={handleDelete}
        onCancel={() => setConfirmDelete(null)}
      />

      <InfoDialog
        open={!!info}
        variant={info?.variant || 'info'}
        title={info?.title || ''}
        message={info?.message || ''}
        onClose={() => setInfo(null)}
      />
    </div>
  )
}
