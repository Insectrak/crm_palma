/**
 * Metas.jsx — Sistema de Metas Mensuales (Sprint 3)
 *
 * Patron patrón estándar Quotas / patrón estándar Goals: el admin / supervisor define
 * meta numerica de ventas / citas / llamadas por (asesor, mes) y el
 * sistema mide cumplimiento real-time contra los datos.
 *
 * Vista premium tipo patrón estándar Goals dashboard:
 *   - KPI cards arriba (totales del mes)
 *   - Selector de mes
 *   - Tabla con barra de progreso por meta
 *   - Modal para crear/editar meta
 *   - Color codigo: verde >= esperado, amber 70-100% esperado, rojo <70%
 */
import React, { useEffect, useState, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Target, ChevronLeft, ChevronRight, Plus, Edit2, Trash2,
  TrendingUp, Calendar, Phone, AlertCircle, Check, X as XIcon,
  Users, User, ChevronDown, Crown, Trophy,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Card, CardContent } from '@/components/ui/card'
import LoadingSpinner from '@/components/shared/LoadingSpinner'
import ConfirmDialog from '@/components/shared/ConfirmDialog'
import useAuthStore from '@/store/authStore'
import { hasPermission } from '@/lib/permissions'
import api from '@/lib/api'

const MESES = ['Enero','Febrero','Marzo','Abril','Mayo','Junio','Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']

function formatMes(iso) {
  if (!iso) return ''
  const d = new Date(iso + 'T00:00:00')
  return `${MESES[d.getMonth()]} ${d.getFullYear()}`
}

function thisMonthIso() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function shiftMonth(iso, delta) {
  const [y, m] = iso.split('-').map(Number)
  const d = new Date(y, m - 1 + delta, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function ProgressBar({ pct, expected = 100, big = false }) {
  // Color logic: si llegas o superas lo esperado-segun-dia, verde.
  // Si estas a >70% de lo esperado, amber. Sino rojo.
  const ratio = expected > 0 ? (pct || 0) / expected : 0
  const color = pct == null ? '#D1D5DB'
    : ratio >= 1   ? '#10B981'
    : ratio >= 0.7 ? '#F59E0B'
    :                '#EF4444'
  const width = Math.min(Math.max(pct || 0, 0), 100)
  return (
    <div className={`relative w-full ${big ? 'h-3' : 'h-2'} bg-gray-100 rounded-full overflow-hidden`}>
      <div
        className="absolute left-0 top-0 bottom-0 transition-all duration-500"
        style={{ width: `${width}%`, backgroundColor: color }}
      />
      {/* Marker de "esperado segun dia del mes" */}
      {expected < 100 && expected > 0 && (
        <div
          className="absolute top-0 bottom-0 w-px bg-gray-400"
          style={{ left: `${expected}%` }}
          title={`Esperado al día de hoy: ${expected}%`}
        />
      )}
    </div>
  )
}

function KpiCard({ icon: Icon, label, actual, meta, pct, esperado, color = 'indigo' }) {
  const colors = {
    indigo:  { bg: 'bg-indigo-50',  text: 'text-indigo-600',  ring: 'ring-indigo-100' },
    emerald: { bg: 'bg-emerald-50', text: 'text-emerald-600', ring: 'ring-emerald-100' },
    amber:   { bg: 'bg-amber-50',   text: 'text-amber-600',   ring: 'ring-amber-100' },
  }[color]
  return (
    <Card className={`ring-1 ${colors.ring}`}>
      <CardContent className="p-4 space-y-3">
        <div className="flex items-center gap-2">
          <div className={`w-8 h-8 rounded-lg ${colors.bg} flex items-center justify-center`}>
            <Icon size={16} className={colors.text} />
          </div>
          <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">{label}</span>
        </div>
        <div className="flex items-baseline gap-2">
          <span className="text-3xl font-bold text-gray-900">{actual}</span>
          <span className="text-sm text-gray-400">/ {meta}</span>
        </div>
        <div className="space-y-1">
          <ProgressBar pct={pct} expected={esperado} big />
          <div className="flex justify-between text-[11px]">
            <span className={`font-semibold ${pct == null ? 'text-gray-400' : pct >= esperado ? 'text-emerald-600' : pct >= esperado * 0.7 ? 'text-amber-600' : 'text-red-600'}`}>
              {pct != null ? `${pct}%` : 'Sin meta'}
            </span>
            <span className="text-gray-400">esperado: {esperado}%</span>
          </div>
        </div>
      </CardContent>
    </Card>
  )
}

export default function Metas() {
  const navigate = useNavigate()
  const { user } = useAuthStore()
  const role = user?.role || 'asesor'
  // metas.view es la unica permission key de metas (no hay metas.edit todavia).
  // Si en el futuro queremos permitir solo lectura, agregar metas.edit y separar.
  const canEdit = hasPermission(user, 'metas.view') || role === 'admin' || role === 'supervisor'

  const [mes, setMes] = useState(thisMonthIso())
  const [data, setData] = useState(null)
  const [asesores, setAsesores] = useState([])
  const [loading, setLoading] = useState(true)
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState(null)
  const [confirmDelete, setConfirmDelete] = useState(null)
  const [form, setForm] = useState({
    asesor_id: '', mes, tipo: 'asesor',
    meta_ventas: 0, meta_citas: 0, meta_llamadas: 0, notas: '',
  })
  const [equipoHint, setEquipoHint] = useState(null)  // suma indiv del equipo seleccionado en el modal

  // Fetch hint con la suma de metas individuales del equipo seleccionado
  // (solo cuando estamos creando una meta de equipo y hay supervisor elegido).
  useEffect(() => {
    setEquipoHint(null)
    if (!showForm || form.tipo !== 'equipo' || !form.asesor_id || editing) return
    let cancel = false
    api.get(`/api/metas/equipo/${form.asesor_id}/detalle?mes=${mes}`)
      .then(r => {
        if (cancel) return
        const ms = r.data?.miembros || []
        setEquipoHint({
          ventas:   ms.reduce((s, m) => s + (m.meta_ventas   || 0), 0),
          citas:    ms.reduce((s, m) => s + (m.meta_citas    || 0), 0),
          llamadas: ms.reduce((s, m) => s + (m.meta_llamadas || 0), 0),
          n:        ms.length,
        })
      })
      .catch(() => {})
    return () => { cancel = true }
  }, [showForm, form.tipo, form.asesor_id, mes, editing])

  useEffect(() => {
    if (!canEdit) {
      navigate('/dashboard')
      return
    }
    api.get('/auth/users').then(r => {
      setAsesores((r.data || []).filter(u => ['asesor', 'supervisor'].includes(u.role) && u.is_active))
    }).catch(() => {})
  }, [canEdit, navigate])

  const load = async () => {
    setLoading(true)
    try {
      const r = await api.get(`/api/metas/cumplimiento?mes=${mes}`)
      setData(r.data)
    } catch (err) {
      // Si la migracion V043 todavia no se aplico, tirara error
      setData({ metas: [], totales: {}, pct_esperado: 0, error: err.response?.data?.detail })
    } finally {
      setLoading(false)
    }
  }
  useEffect(() => { load() }, [mes])

  const openNew = (tipo = 'asesor') => {
    setEditing(null)
    setForm({
      asesor_id: '', mes, tipo,
      meta_ventas: 0, meta_citas: 0, meta_llamadas: 0, notas: '',
    })
    setShowForm(true)
  }

  const openEdit = (meta) => {
    setEditing(meta)
    setForm({
      asesor_id: meta.asesor_id,
      mes,
      tipo: meta.tipo || 'asesor',
      meta_ventas: meta.meta_ventas,
      meta_citas: meta.meta_citas,
      meta_llamadas: meta.meta_llamadas,
      notas: meta.notas || '',
    })
    setShowForm(true)
  }

  const handleSave = async () => {
    if (!form.asesor_id) return
    try {
      await api.post('/api/metas', {
        asesor_id: form.asesor_id,
        mes: form.mes,
        tipo: form.tipo || 'asesor',
        meta_ventas: parseInt(form.meta_ventas) || 0,
        meta_citas:  parseInt(form.meta_citas)  || 0,
        meta_llamadas: parseInt(form.meta_llamadas) || 0,
        notas: form.notas || null,
      })
      setShowForm(false)
      load()
    } catch (err) {
      alert(err.response?.data?.detail || 'Error al guardar.')
    }
  }

  const handleDelete = async () => {
    if (!confirmDelete) return
    try {
      await api.delete(`/api/metas/${confirmDelete.id}`)
      setConfirmDelete(null)
      load()
    } catch (err) {
      alert(err.response?.data?.detail || 'Error al eliminar.')
    }
  }

  const pctEsperado = data?.pct_esperado || 0
  const totales = data?.totales || {}
  const metas   = data?.metas   || []
  const metasAsesor   = useMemo(() => metas.filter(m => (m.tipo || 'asesor') === 'asesor'), [metas])
  const metasEquipo   = useMemo(() => metas.filter(m => m.tipo === 'equipo'), [metas])
  // V088 — excluye supervisores deshabilitados del listado de metas.
  const supervisores  = useMemo(() => asesores.filter(a => a.role === 'supervisor' && a.is_active !== false), [asesores])

  const asesoresSinMeta = useMemo(() => {
    const ids = new Set(metasAsesor.map(m => m.asesor_id))
    return asesores.filter(a => !ids.has(a.id))
  }, [metasAsesor, asesores])

  const equiposSinMeta = useMemo(() => {
    const ids = new Set(metasEquipo.map(m => m.asesor_id))
    return supervisores.filter(s => !ids.has(s.id))
  }, [metasEquipo, supervisores])

  return (
    <div className="space-y-5 max-w-6xl">
      {/* Header */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-2">
            <Target size={22} className="text-indigo-500" /> Metas mensuales
          </h1>
          <p className="text-sm text-gray-400 mt-0.5">
            Define metas de ventas / citas / llamadas y mide el cumplimiento real-time por asesor y por equipo.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => setMes(shiftMonth(mes, -1))} className="px-2">
            <ChevronLeft size={14} />
          </Button>
          <span className="font-semibold text-gray-700 min-w-[140px] text-center capitalize">
            {formatMes(mes + '-01')}
          </span>
          <Button variant="outline" size="sm" onClick={() => setMes(shiftMonth(mes, 1))} className="px-2">
            <ChevronRight size={14} />
          </Button>
          {canEdit && (
            <div className="flex items-center gap-1.5 ml-2">
              <Button size="sm" variant="outline" onClick={() => openNew('asesor')} className="gap-1.5">
                <User size={13} /> Por asesor
              </Button>
              <Button size="sm" onClick={() => openNew('equipo')} className="gap-1.5">
                <Users size={13} /> Por equipo
              </Button>
            </div>
          )}
        </div>
      </div>

      {loading ? <LoadingSpinner /> : (
        <>
          {/* KPIs totales del mes */}
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <KpiCard
              icon={TrendingUp} label="Ventas (ganados)"
              actual={totales.ventas_actuales || 0} meta={totales.meta_ventas || 0}
              pct={totales.pct_ventas} esperado={pctEsperado}
              color="emerald"
            />
            <KpiCard
              icon={Calendar} label="Citas agendadas"
              actual={totales.citas_actuales || 0} meta={totales.meta_citas || 0}
              pct={totales.pct_citas} esperado={pctEsperado}
              color="indigo"
            />
            <KpiCard
              icon={Phone} label="Llamadas"
              actual={totales.llamadas_actuales || 0} meta={totales.meta_llamadas || 0}
              pct={totales.pct_llamadas} esperado={pctEsperado}
              color="amber"
            />
          </div>

          {data?.error && (
            <div className="bg-amber-50 border border-amber-200 text-amber-800 text-sm rounded-lg p-3 flex items-start gap-2">
              <AlertCircle size={16} className="shrink-0 mt-0.5" />
              <div>
                <strong>Atención:</strong> {data.error}. Asegúrate de que la migración V043 se haya aplicado.
              </div>
            </div>
          )}

          {/* Metas por equipo (supervisor → su equipo entero) */}
          {metasEquipo.length > 0 && (
            <div className="space-y-2">
              <div className="flex items-center gap-2">
                <Users size={15} className="text-purple-500" />
                <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Por equipo</h2>
                <span className="text-[10px] bg-purple-50 text-purple-600 border border-purple-200 px-1.5 rounded">
                  Suma de supervisor + sus asesores
                </span>
                <span className="text-[10px] text-gray-400 ml-1">click en una fila para ver el detalle</span>
              </div>
              <Card>
                <CardContent className="p-0">
                  <EquiposTable
                    metas={metasEquipo}
                    pctEsperado={pctEsperado}
                    canEdit={canEdit}
                    onEdit={openEdit}
                    onDelete={setConfirmDelete}
                    mes={mes}
                  />
                </CardContent>
              </Card>
            </div>
          )}

          {/* Metas por asesor */}
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <User size={15} className="text-indigo-500" />
              <h2 className="text-sm font-semibold text-gray-700 uppercase tracking-wide">Por asesor</h2>
            </div>
            <Card>
              <CardContent className="p-0">
                {metasAsesor.length === 0 ? (
                  <div className="p-10 text-center">
                    <Target size={32} className="mx-auto text-gray-300 mb-2" />
                    <p className="text-sm text-gray-500 mb-3">Sin metas individuales este mes.</p>
                    {canEdit && (
                      <Button size="sm" onClick={() => openNew('asesor')} className="gap-1.5">
                        <Plus size={14} /> Crear primera meta
                      </Button>
                    )}
                  </div>
                ) : (
                  <MetasTable
                    metas={metasAsesor}
                    pctEsperado={pctEsperado}
                    canEdit={canEdit}
                    onEdit={openEdit}
                    onDelete={setConfirmDelete}
                    leadColor="indigo"
                    leadLabel="Asesor"
                  />
                )}
              </CardContent>
            </Card>
          </div>

          {/* Equipos sin meta (sugerencia) */}
          {canEdit && equiposSinMeta.length > 0 && (
            <Card className="bg-purple-50/30 border-purple-200">
              <CardContent className="p-4">
                <p className="text-xs font-semibold text-purple-700 uppercase tracking-wide mb-2 flex items-center gap-1.5">
                  <Users size={12} /> Equipos sin meta este mes ({equiposSinMeta.length})
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {equiposSinMeta.map(s => (
                    <button
                      key={s.id}
                      onClick={() => {
                        setForm(p => ({ ...p, asesor_id: s.id, tipo: 'equipo' }))
                        setEditing(null)
                        setShowForm(true)
                      }}
                      className="text-xs px-2.5 py-1 bg-white border border-purple-300 text-purple-700 rounded-full hover:bg-purple-50"
                    >
                      + Equipo de {[s.first_name, s.last_name].filter(Boolean).join(' ') || s.email}
                    </button>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Asesores sin meta (sugerencia) */}
          {canEdit && asesoresSinMeta.length > 0 && (
            <Card className="bg-amber-50/30 border-amber-200">
              <CardContent className="p-4">
                <p className="text-xs font-semibold text-amber-700 uppercase tracking-wide mb-2">
                  Asesores sin meta este mes ({asesoresSinMeta.length})
                </p>
                <div className="flex flex-wrap gap-1.5">
                  {asesoresSinMeta.map(a => (
                    <button
                      key={a.id}
                      onClick={() => {
                        setForm(p => ({ ...p, asesor_id: a.id, tipo: 'asesor' }))
                        setEditing(null)
                        setShowForm(true)
                      }}
                      className="text-xs px-2.5 py-1 bg-white border border-amber-300 text-amber-700 rounded-full hover:bg-amber-50"
                    >
                      + {[a.first_name, a.last_name].filter(Boolean).join(' ') || a.email}
                    </button>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </>
      )}

      {/* Modal crear/editar */}
      {showForm && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
          <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md p-6 space-y-4">
            <div className="flex items-center justify-between">
              <h3 className="text-base font-semibold text-gray-900 flex items-center gap-2">
                {form.tipo === 'equipo' ? <Users size={16} className="text-purple-500" /> : <User size={16} className="text-indigo-500" />}
                {editing
                  ? `Editar meta ${form.tipo === 'equipo' ? 'de equipo' : 'individual'}`
                  : `Nueva meta ${form.tipo === 'equipo' ? 'de equipo' : 'individual'}`}
              </h3>
              <button onClick={() => setShowForm(false)} className="text-gray-400 hover:text-gray-600">
                <XIcon size={16} />
              </button>
            </div>
            {/* Toggle tipo (solo en creacion) */}
            {!editing && (
              <div className="flex gap-1 bg-gray-100 rounded-lg p-1">
                <button
                  onClick={() => setForm(p => ({ ...p, tipo: 'asesor', asesor_id: '' }))}
                  className={`flex-1 text-xs font-semibold py-1.5 rounded-md transition-colors flex items-center justify-center gap-1.5 ${
                    form.tipo === 'asesor' ? 'bg-white text-indigo-700 shadow-sm' : 'text-gray-500'
                  }`}
                >
                  <User size={12} /> Por asesor
                </button>
                <button
                  onClick={() => setForm(p => ({ ...p, tipo: 'equipo', asesor_id: '' }))}
                  className={`flex-1 text-xs font-semibold py-1.5 rounded-md transition-colors flex items-center justify-center gap-1.5 ${
                    form.tipo === 'equipo' ? 'bg-white text-purple-700 shadow-sm' : 'text-gray-500'
                  }`}
                >
                  <Users size={12} /> Por equipo
                </button>
              </div>
            )}
            {!editing && (
              <div>
                <Label className="text-xs">{form.tipo === 'equipo' ? 'Equipo (supervisor)' : 'Asesor'}</Label>
                <select
                  value={form.asesor_id}
                  onChange={e => setForm(p => ({ ...p, asesor_id: e.target.value }))}
                  className="w-full mt-1 text-sm border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                >
                  <option value="">
                    {form.tipo === 'equipo' ? 'Seleccionar equipo…' : 'Seleccionar asesor…'}
                  </option>
                  {(form.tipo === 'equipo' ? supervisores : asesores).map(a => (
                    <option key={a.id} value={a.id}>
                      {form.tipo === 'equipo' ? 'Equipo de ' : ''}
                      {[a.first_name, a.last_name].filter(Boolean).join(' ') || a.email}
                      {form.tipo !== 'equipo' && ` (${a.role})`}
                    </option>
                  ))}
                </select>
                {form.tipo === 'equipo' && (
                  <p className="text-[10px] text-gray-400 mt-1">
                    El cumplimiento sumará ventas/citas/llamadas del supervisor + todos sus asesores activos.
                  </p>
                )}
                {/* Hint: suma de metas individuales del equipo seleccionado */}
                {form.tipo === 'equipo' && form.asesor_id && equipoHint && (
                  <div className="mt-2 bg-purple-50 border border-purple-100 rounded-lg px-2.5 py-2 text-[11px]">
                    <p className="text-purple-700 font-semibold mb-1 flex items-center gap-1">
                      <Users size={11} />
                      Metas individuales actuales del equipo ({equipoHint.n} miembros)
                    </p>
                    <div className="grid grid-cols-3 gap-2">
                      <div>
                        <span className="text-emerald-600 font-semibold">Ventas:</span>{' '}
                        <span className="font-bold text-gray-800">{equipoHint.ventas}</span>
                      </div>
                      <div>
                        <span className="text-indigo-600 font-semibold">Citas:</span>{' '}
                        <span className="font-bold text-gray-800">{equipoHint.citas}</span>
                      </div>
                      <div>
                        <span className="text-amber-600 font-semibold">Llamadas:</span>{' '}
                        <span className="font-bold text-gray-800">{equipoHint.llamadas}</span>
                      </div>
                    </div>
                    <button
                      onClick={() => setForm(p => ({
                        ...p,
                        meta_ventas:   equipoHint.ventas,
                        meta_citas:    equipoHint.citas,
                        meta_llamadas: equipoHint.llamadas,
                      }))}
                      className="mt-1.5 text-[10px] text-purple-600 hover:text-purple-800 font-medium underline-offset-2 hover:underline"
                    >
                      Usar estos números como meta de equipo
                    </button>
                  </div>
                )}
              </div>
            )}
            {editing && (
              <div className={`border rounded-lg p-2.5 text-sm ${form.tipo === 'equipo' ? 'bg-purple-50 border-purple-100' : 'bg-indigo-50 border-indigo-100'}`}>
                <strong className={form.tipo === 'equipo' ? 'text-purple-700' : 'text-indigo-700'}>
                  {form.tipo === 'equipo' ? `Equipo de ${editing.asesor_nombre}` : editing.asesor_nombre}
                </strong> · {formatMes(mes + '-01')}
              </div>
            )}
            <div className="grid grid-cols-3 gap-3">
              <div>
                <Label className="text-xs text-emerald-700">Ventas</Label>
                <Input type="number" min="0" value={form.meta_ventas} onChange={e => setForm(p => ({ ...p, meta_ventas: e.target.value }))} className="mt-1" />
              </div>
              <div>
                <Label className="text-xs text-indigo-700">Citas</Label>
                <Input type="number" min="0" value={form.meta_citas} onChange={e => setForm(p => ({ ...p, meta_citas: e.target.value }))} className="mt-1" />
              </div>
              <div>
                <Label className="text-xs text-amber-700">Llamadas</Label>
                <Input type="number" min="0" value={form.meta_llamadas} onChange={e => setForm(p => ({ ...p, meta_llamadas: e.target.value }))} className="mt-1" />
              </div>
            </div>
            <div>
              <Label className="text-xs">Notas (opcional)</Label>
              <textarea
                value={form.notas}
                onChange={e => setForm(p => ({ ...p, notas: e.target.value }))}
                rows={2}
                className="w-full mt-1 text-sm border border-gray-200 rounded-md px-3 py-2 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500 resize-none"
                placeholder="Ej: Foco en proyecto Palmeras"
              />
            </div>
            <div className="flex gap-2 justify-end pt-1">
              <Button variant="outline" onClick={() => setShowForm(false)}>Cancelar</Button>
              <Button onClick={handleSave} disabled={!form.asesor_id} className="gap-1.5">
                <Check size={14} /> Guardar
              </Button>
            </div>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={!!confirmDelete}
        title={confirmDelete?.tipo === 'equipo' ? 'Eliminar meta de equipo' : 'Eliminar meta'}
        message={confirmDelete
          ? `¿Eliminar la meta ${confirmDelete.tipo === 'equipo' ? 'del equipo de' : 'de'} ${confirmDelete.asesor_nombre} para ${formatMes(mes + '-01')}?`
          : ''}
        onConfirm={handleDelete}
        onCancel={() => setConfirmDelete(null)}
      />
    </div>
  )
}

function MetasTable({ metas, pctEsperado, canEdit, onEdit, onDelete, leadColor, leadLabel, isEquipo }) {
  const accentBg = isEquipo ? 'bg-purple-100 text-purple-600' : 'bg-indigo-100 text-indigo-600'
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-gray-50 border-b border-gray-100">
            <th className={`text-left px-4 py-3 text-xs font-semibold text-${leadColor}-600 uppercase tracking-wide`}>{leadLabel}</th>
            <th className="text-left px-4 py-3 text-xs font-semibold text-emerald-600 uppercase tracking-wide min-w-[200px]">Ventas</th>
            <th className="text-left px-4 py-3 text-xs font-semibold text-indigo-600 uppercase tracking-wide min-w-[200px]">Citas</th>
            <th className="text-left px-4 py-3 text-xs font-semibold text-amber-600 uppercase tracking-wide min-w-[200px]">Llamadas</th>
            {canEdit && <th className="px-3 py-3"></th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {metas.map((m) => (
            <tr key={m.id} className="hover:bg-gray-50/50">
              <td className="px-4 py-3">
                <div className="flex items-center gap-2.5">
                  <div className={`w-9 h-9 rounded-full ${accentBg} flex items-center justify-center text-sm font-semibold shrink-0`}>
                    {isEquipo ? <Users size={15} /> : (m.asesor_nombre || '?')[0].toUpperCase()}
                  </div>
                  <div className="min-w-0">
                    <p className="font-medium text-gray-800 truncate">
                      {isEquipo ? `Equipo de ${m.asesor_nombre || '—'}` : (m.asesor_nombre || '—')}
                    </p>
                    {!isEquipo && m.asesor_role === 'supervisor' && (
                      <span className="text-[10px] bg-purple-50 text-purple-600 border border-purple-200 px-1.5 rounded">Supervisor</span>
                    )}
                    {isEquipo && (
                      <span className="text-[10px] text-gray-400">Suma de su equipo</span>
                    )}
                  </div>
                </div>
              </td>
              <MetaCell actual={m.ventas_actuales}    meta={m.meta_ventas}    pct={m.pct_ventas}    esperado={pctEsperado} />
              <MetaCell actual={m.citas_actuales}     meta={m.meta_citas}     pct={m.pct_citas}     esperado={pctEsperado} />
              <MetaCell actual={m.llamadas_actuales}  meta={m.meta_llamadas}  pct={m.pct_llamadas}  esperado={pctEsperado} />
              {canEdit && (
                <td className="px-3 py-3 text-right whitespace-nowrap">
                  <button onClick={() => onEdit(m)} className="p-1.5 rounded hover:bg-indigo-50 text-gray-400 hover:text-indigo-500" title="Editar">
                    <Edit2 size={13} />
                  </button>
                  <button onClick={() => onDelete(m)} className="p-1.5 rounded hover:bg-red-50 text-gray-400 hover:text-red-500" title="Eliminar">
                    <Trash2 size={13} />
                  </button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function MetaCell({ actual, meta, pct, esperado }) {
  return (
    <td className="px-4 py-3">
      <div className="space-y-1">
        <div className="flex items-baseline gap-1.5">
          <span className="text-base font-bold text-gray-800">{actual || 0}</span>
          <span className="text-xs text-gray-400">/ {meta || 0}</span>
          {pct != null && (
            <span className={`ml-auto text-xs font-semibold ${pct >= esperado ? 'text-emerald-600' : pct >= esperado * 0.7 ? 'text-amber-600' : 'text-red-600'}`}>
              {pct}%
            </span>
          )}
        </div>
        <ProgressBar pct={pct} expected={esperado} />
      </div>
    </td>
  )
}

// ─── EquiposTable: tabla expandible con drill-down de miembros ──────────────
function hasIncoherencia(m) {
  // Si el backend ya proveyo suma_indiv_*, comparamos contra meta_*
  if (m.suma_indiv_ventas == null && m.suma_indiv_citas == null && m.suma_indiv_llamadas == null) return false
  return (
    (m.suma_indiv_ventas   ?? 0) !== (m.meta_ventas   || 0) ||
    (m.suma_indiv_citas    ?? 0) !== (m.meta_citas    || 0) ||
    (m.suma_indiv_llamadas ?? 0) !== (m.meta_llamadas || 0)
  )
}

function EquiposTable({ metas, pctEsperado, canEdit, onEdit, onDelete, mes }) {
  const [expanded, setExpanded] = useState(() => new Set())
  const [details, setDetails] = useState({})       // {supervisor_id: data}
  const [loadingId, setLoadingId] = useState(null)

  const toggle = async (m) => {
    const next = new Set(expanded)
    if (next.has(m.id)) {
      next.delete(m.id)
      setExpanded(next)
      return
    }
    next.add(m.id)
    setExpanded(next)
    if (!details[m.asesor_id]) {
      setLoadingId(m.id)
      try {
        const r = await api.get(`/api/metas/equipo/${m.asesor_id}/detalle?mes=${mes}`)
        setDetails(d => ({ ...d, [m.asesor_id]: r.data }))
      } catch (err) {
        setDetails(d => ({ ...d, [m.asesor_id]: { error: err.response?.data?.detail || 'Error al cargar detalle' } }))
      } finally {
        setLoadingId(null)
      }
    }
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="bg-gray-50 border-b border-gray-100">
            <th className="w-8 px-2 py-3"></th>
            <th className="text-left px-3 py-3 text-xs font-semibold text-purple-600 uppercase tracking-wide">Equipo</th>
            <th className="text-left px-4 py-3 text-xs font-semibold text-emerald-600 uppercase tracking-wide min-w-[200px]">Ventas</th>
            <th className="text-left px-4 py-3 text-xs font-semibold text-indigo-600 uppercase tracking-wide min-w-[200px]">Citas</th>
            <th className="text-left px-4 py-3 text-xs font-semibold text-amber-600 uppercase tracking-wide min-w-[200px]">Llamadas</th>
            {canEdit && <th className="px-3 py-3"></th>}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-50">
          {metas.map((m) => {
            const isOpen = expanded.has(m.id)
            const detalle = details[m.asesor_id]
            return (
              <React.Fragment key={m.id}>
                <tr
                  className={`cursor-pointer hover:bg-purple-50/40 transition-colors ${isOpen ? 'bg-purple-50/30' : ''}`}
                  onClick={() => toggle(m)}
                >
                  <td className="px-2 py-3 align-middle">
                    <ChevronDown
                      size={16}
                      className={`text-gray-400 transition-transform duration-200 ${isOpen ? 'rotate-0' : '-rotate-90'}`}
                    />
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex items-center gap-2.5">
                      <div className="w-9 h-9 rounded-full bg-purple-100 text-purple-600 flex items-center justify-center shrink-0 relative">
                        <Users size={15} />
                        {hasIncoherencia(m) && (
                          <span
                            className="absolute -top-0.5 -right-0.5 w-2.5 h-2.5 rounded-full bg-amber-400 ring-2 ring-white"
                            title="Las metas individuales del equipo no coinciden con la del equipo. Click para ver detalle."
                          />
                        )}
                      </div>
                      <div className="min-w-0">
                        <p className="font-medium text-gray-800 truncate">Equipo de {m.asesor_nombre || '—'}</p>
                        <span className="text-[10px] text-gray-400">
                          {hasIncoherencia(m) ? 'Σ metas individuales ≠ meta equipo' : 'Suma de su equipo'}
                        </span>
                      </div>
                    </div>
                  </td>
                  <MetaCell actual={m.ventas_actuales}    meta={m.meta_ventas}    pct={m.pct_ventas}    esperado={pctEsperado} />
                  <MetaCell actual={m.citas_actuales}     meta={m.meta_citas}     pct={m.pct_citas}     esperado={pctEsperado} />
                  <MetaCell actual={m.llamadas_actuales}  meta={m.meta_llamadas}  pct={m.pct_llamadas}  esperado={pctEsperado} />
                  {canEdit && (
                    <td className="px-3 py-3 text-right whitespace-nowrap" onClick={e => e.stopPropagation()}>
                      <button onClick={() => onEdit(m)} className="p-1.5 rounded hover:bg-indigo-50 text-gray-400 hover:text-indigo-500" title="Editar">
                        <Edit2 size={13} />
                      </button>
                      <button onClick={() => onDelete(m)} className="p-1.5 rounded hover:bg-red-50 text-gray-400 hover:text-red-500" title="Eliminar">
                        <Trash2 size={13} />
                      </button>
                    </td>
                  )}
                </tr>
                {isOpen && (
                  <tr className="bg-gradient-to-b from-purple-50/40 to-transparent">
                    <td colSpan={canEdit ? 6 : 5} className="px-0 py-0">
                      <MiembrosPanel data={detalle} loading={loadingId === m.id} metaEquipo={m} />
                    </td>
                  </tr>
                )}
              </React.Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ─── MiembrosPanel: drill-down con tarjetas por miembro ─────────────────────
function MiembrosPanel({ data, loading, metaEquipo }) {
  if (loading) {
    return (
      <div className="px-12 py-6 text-center text-xs text-gray-400">
        <div className="inline-flex items-center gap-2">
          <span className="w-3 h-3 rounded-full bg-purple-400 animate-pulse" />
          Cargando detalle del equipo…
        </div>
      </div>
    )
  }
  if (!data) return null
  if (data.error) {
    return (
      <div className="px-12 py-4 text-center text-xs text-red-500">
        <AlertCircle size={14} className="inline mr-1" />
        {data.error}
      </div>
    )
  }
  const miembros = data.miembros || []
  const totales = data.totales || {}

  // Identificar top performer en cada metrica (mayor contribucion)
  const topVentas    = miembros.reduce((max, m) => m.ventas_actuales   > (max?.ventas_actuales   || 0) ? m : max, null)
  const topCitas     = miembros.reduce((max, m) => m.citas_actuales    > (max?.citas_actuales    || 0) ? m : max, null)
  const topLlamadas  = miembros.reduce((max, m) => m.llamadas_actuales > (max?.llamadas_actuales || 0) ? m : max, null)

  // Coherencia: meta del equipo vs suma de metas individuales de los miembros
  const sumaIndivVentas   = metaEquipo?.suma_indiv_ventas   ?? miembros.reduce((s, m) => s + (m.meta_ventas || 0), 0)
  const sumaIndivCitas    = metaEquipo?.suma_indiv_citas    ?? miembros.reduce((s, m) => s + (m.meta_citas || 0), 0)
  const sumaIndivLlamadas = metaEquipo?.suma_indiv_llamadas ?? miembros.reduce((s, m) => s + (m.meta_llamadas || 0), 0)

  return (
    <div className="px-6 pt-3 pb-5 space-y-3">
      {/* Banner de coherencia (patrón estándar Goals) — meta equipo vs suma individuales */}
      {metaEquipo && (
        <CoherenceBanner
          metaEquipo={metaEquipo}
          sumaIndiv={{ ventas: sumaIndivVentas, citas: sumaIndivCitas, llamadas: sumaIndivLlamadas }}
        />
      )}

      {/* Resumen totales del equipo (ACTUALES, no metas) */}
      <div>
        <p className="text-[10px] uppercase tracking-wide text-gray-400 font-semibold mb-1.5">
          Avance real del equipo este mes
        </p>
        <div className="grid grid-cols-3 gap-2 text-xs">
          <div className="bg-emerald-50 border border-emerald-100 rounded-lg px-3 py-2">
            <p className="text-[10px] uppercase tracking-wide text-emerald-700 font-semibold">Ventas</p>
            <p className="text-lg font-bold text-emerald-900">{totales.ventas_actuales || 0}</p>
          </div>
          <div className="bg-indigo-50 border border-indigo-100 rounded-lg px-3 py-2">
            <p className="text-[10px] uppercase tracking-wide text-indigo-700 font-semibold">Citas</p>
            <p className="text-lg font-bold text-indigo-900">{totales.citas_actuales || 0}</p>
          </div>
          <div className="bg-amber-50 border border-amber-100 rounded-lg px-3 py-2">
            <p className="text-[10px] uppercase tracking-wide text-amber-700 font-semibold">Llamadas</p>
            <p className="text-lg font-bold text-amber-900">{totales.llamadas_actuales || 0}</p>
          </div>
        </div>
      </div>

      {/* Tabla de miembros con contribucion individual */}
      <div className="bg-white rounded-lg border border-purple-100 overflow-hidden shadow-sm">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-purple-50/50 border-b border-purple-100">
              <th className="text-left px-3 py-2 text-[10px] font-semibold text-purple-700 uppercase tracking-wide">Miembro</th>
              <th className="text-left px-3 py-2 text-[10px] font-semibold text-emerald-600 uppercase tracking-wide">Ventas</th>
              <th className="text-left px-3 py-2 text-[10px] font-semibold text-indigo-600 uppercase tracking-wide">Citas</th>
              <th className="text-left px-3 py-2 text-[10px] font-semibold text-amber-600 uppercase tracking-wide">Llamadas</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-purple-50">
            {miembros.map(m => {
              const isTopV = topVentas?.id === m.id && m.ventas_actuales > 0
              const isTopC = topCitas?.id === m.id && m.citas_actuales > 0
              const isTopL = topLlamadas?.id === m.id && m.llamadas_actuales > 0
              return (
                <tr key={m.id} className="hover:bg-purple-50/20">
                  <td className="px-3 py-2">
                    <div className="flex items-center gap-2">
                      <div className={`w-7 h-7 rounded-full ${m.es_supervisor ? 'bg-purple-100 text-purple-600' : 'bg-gray-100 text-gray-600'} flex items-center justify-center text-[11px] font-semibold shrink-0`}>
                        {m.es_supervisor ? <Crown size={12} /> : (m.nombre || '?')[0].toUpperCase()}
                      </div>
                      <div className="min-w-0">
                        <p className="font-medium text-gray-800 truncate">{m.nombre || '—'}</p>
                        <span className={`text-[9px] px-1 rounded ${m.es_supervisor ? 'bg-purple-50 text-purple-600 border border-purple-200' : 'bg-gray-50 text-gray-500'}`}>
                          {m.es_supervisor ? 'Supervisor' : 'Asesor'}
                        </span>
                      </div>
                    </div>
                  </td>
                  <ContribCell actual={m.ventas_actuales}   meta={m.meta_ventas}   pct={m.pct_ventas_total}   color="emerald" isTop={isTopV} />
                  <ContribCell actual={m.citas_actuales}    meta={m.meta_citas}    pct={m.pct_citas_total}    color="indigo"  isTop={isTopC} />
                  <ContribCell actual={m.llamadas_actuales} meta={m.meta_llamadas} pct={m.pct_llamadas_total} color="amber"   isTop={isTopL} />
                </tr>
              )
            })}
          </tbody>
        </table>
        {miembros.length === 0 && (
          <p className="px-4 py-6 text-center text-xs text-gray-400">No hay miembros activos en este equipo.</p>
        )}
      </div>
    </div>
  )
}

// ─── CoherenceBanner: muestra meta_equipo vs suma_individuales (patrón estándar)
function CoherenceBanner({ metaEquipo, sumaIndiv }) {
  const rows = [
    { label: 'Ventas',    color: 'emerald', meta: metaEquipo.meta_ventas   || 0, suma: sumaIndiv.ventas   || 0 },
    { label: 'Citas',     color: 'indigo',  meta: metaEquipo.meta_citas    || 0, suma: sumaIndiv.citas    || 0 },
    { label: 'Llamadas',  color: 'amber',   meta: metaEquipo.meta_llamadas || 0, suma: sumaIndiv.llamadas || 0 },
  ]
  // Hay incoherencia si alguna metrica difiere significativamente
  const hayIncoherencia = rows.some(r => r.meta !== r.suma && (r.meta > 0 || r.suma > 0))
  if (!hayIncoherencia) {
    return (
      <div className="bg-emerald-50/60 border border-emerald-100 rounded-lg px-3 py-2 text-xs flex items-start gap-2">
        <Check size={13} className="text-emerald-600 shrink-0 mt-0.5" />
        <div>
          <span className="font-semibold text-emerald-800">Metas coherentes.</span>
          <span className="text-emerald-700 ml-1">La meta del equipo coincide con la suma de las metas individuales.</span>
        </div>
      </div>
    )
  }
  return (
    <div className="bg-amber-50 border border-amber-200 rounded-lg px-3 py-2 text-xs">
      <div className="flex items-start gap-2 mb-2">
        <AlertCircle size={13} className="text-amber-600 shrink-0 mt-0.5" />
        <div>
          <span className="font-semibold text-amber-800">Las metas no coinciden.</span>
          <span className="text-amber-700 ml-1">
            La meta del equipo y la suma de las metas individuales son independientes — esto es solo informativo.
          </span>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2 mt-1">
        {rows.map(r => {
          const diff = r.suma - r.meta
          const sign = diff > 0 ? '+' : ''
          const bg   = r.meta === r.suma ? 'bg-white' : 'bg-white border-l-2 border-l-amber-300'
          return (
            <div key={r.label} className={`${bg} rounded px-2 py-1.5 border border-amber-100`}>
              <p className={`text-[9px] uppercase tracking-wide font-semibold text-${r.color}-600 mb-0.5`}>{r.label}</p>
              <div className="flex items-baseline gap-2 text-[11px]">
                <span className="text-gray-500">Equipo:</span>
                <span className="font-bold text-gray-800">{r.meta}</span>
              </div>
              <div className="flex items-baseline gap-2 text-[11px]">
                <span className="text-gray-500">Σ indiv:</span>
                <span className="font-bold text-gray-800">{r.suma}</span>
                {r.meta !== r.suma && (
                  <span className={`ml-auto text-[10px] font-semibold ${diff > 0 ? 'text-amber-700' : 'text-purple-700'}`}>
                    {sign}{diff}
                  </span>
                )}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function ContribCell({ actual, meta, pct, color, isTop }) {
  const colorMap = {
    emerald: 'bg-emerald-500',
    indigo:  'bg-indigo-500',
    amber:   'bg-amber-500',
  }
  const barColor = colorMap[color] || 'bg-gray-400'
  const width = Math.min(pct || 0, 100)
  return (
    <td className="px-3 py-2">
      <div className="flex items-center gap-2">
        <div className="flex items-baseline gap-1 min-w-[70px]">
          <span className="text-sm font-bold text-gray-800">{actual || 0}</span>
          {meta > 0 && <span className="text-[10px] text-gray-400">/ {meta}</span>}
          {isTop && <Trophy size={11} className="text-amber-500 ml-0.5" />}
        </div>
        {pct != null && (
          <div className="flex-1 flex items-center gap-1.5 min-w-[60px]">
            <div className="flex-1 h-1.5 bg-gray-100 rounded-full overflow-hidden">
              <div className={`h-full ${barColor} transition-all duration-500`} style={{ width: `${width}%` }} />
            </div>
            <span className="text-[10px] text-gray-500 font-medium w-8 text-right">{pct}%</span>
          </div>
        )}
      </div>
    </td>
  )
}
