import { useMemo, useState } from 'react'
import { ArrowRightLeft, UserPlus, UserX, Trash2, X, AlertTriangle, Tags, RotateCcw, Globe, Archive } from 'lucide-react'

/**
 * Barra flotante de acciones masivas sobre leads seleccionados.
 *
 * Acciones disponibles:
 *   1. Cambiar estado (nuevo) — dropdown de estados del pipeline
 *   2. Asignar / reasignar — dropdown de asesores (y supervisores para admin)
 *   3. Revertir TMK — devuelve leads reciclados a su estado/asesor original
 *   4. Devolver a Históricos — quita asesor y supervisor y retira de lista activa
 *   5. Eliminar — soft delete masivo
 */
export default function BulkReassignBar({
  selectedRows,
  asesores,
  groups,
  estados = [],
  fuentes = [],
  canChangeFuente = false,
  onAssign,
  onChangeEstado,
  onChangeFuente,
  onRevertTmk,
  onDevolverHistoricos,
  onDelete,
  onClear,
  isAssigning,
  isChangingEstado,
  isChangingFuente,
  isRevertingTmk,
  isDevolviendoHistoricos,
  isDeleting,
  confirmThreshold = 10,
}) {
  const [toAsesorId, setToAsesorId] = useState('')
  const [toEstadoId, setToEstadoId] = useState('')
  const [toFuenteId, setToFuenteId] = useState('')

  const recycledCount = useMemo(() => {
    return selectedRows.filter(r =>
      r.es_reciclado ||
      r.lote_reciclaje_id ||
      (r.origen_reciclaje && String(r.origen_reciclaje).toLowerCase().includes('tmk')) ||
      (r.fuente_nombre && String(r.fuente_nombre).toLowerCase().includes('bolsa tmk'))
    ).length
  }, [selectedRows])

  const historicosCount = useMemo(() => {
    return selectedRows.filter(r =>
      r.es_historico ||
      (r.fuente_nombre && String(r.fuente_nombre).toLowerCase().includes('hist')) ||
      (r.origen && String(r.origen).toLowerCase().includes('hist'))
    ).length
  }, [selectedRows])

  const breakdown = useMemo(() => {
    const yaAsignados = selectedRows.filter(r => r.asesor_id).length
    const sinAsignar = selectedRows.length - yaAsignados
    const supervisores = new Set(
      selectedRows.map(r => r.supervisor_id).filter(Boolean)
    )
    return {
      yaAsignados,
      sinAsignar,
      crossSupervisor: supervisores.size > 1,
    }
  }, [selectedRows])

  const count = selectedRows.length
  if (count === 0) return null

  const actionLabel =
    breakdown.yaAsignados === 0
      ? 'Asignar'
      : breakdown.sinAsignar === 0
        ? 'Reasignar'
        : 'Asignar / reasignar'

  const needsConfirm =
    count >= confirmThreshold ||
    breakdown.crossSupervisor ||
    breakdown.yaAsignados > 0

  const isUnassignSelected = toAsesorId === '__unassigned__'

  const handleAssignClick = () => {
    if (!toAsesorId) return
    const isUnassign = toAsesorId === '__unassigned__'
    const targetId = isUnassign ? null : toAsesorId
    onAssign(targetId, {
      breakdown,
      needsConfirm: isUnassign ? true : needsConfirm,
      isUnassign,
    })
    setToAsesorId('')
  }

  const handleEstadoClick = () => {
    if (!toEstadoId) return
    const estado = estados.find(e => String(e.id) === toEstadoId)
    onChangeEstado(Number(toEstadoId), {
      estadoNombre: estado?.nombre || '',
      count,
      needsConfirm: count >= confirmThreshold,
    })
    setToEstadoId('')
  }

  const handleFuenteClick = () => {
    if (!toFuenteId) return
    const fuente = fuentes.find(f => String(f.id) === toFuenteId)
    onChangeFuente && onChangeFuente(Number(toFuenteId), {
      fuenteNombre: fuente?.nombre || '',
      count,
      needsConfirm: count >= confirmThreshold,
    })
    setToFuenteId('')
  }

  return (
    // V040.1 — barra de acciones masivas en variante OSCURA (slate-900).
    // El usuario prefiere el contraste oscuro del original; ademas todo
    // tiene que ir en UNA sola fila (antes flex-wrap dejaba "Eliminar"
    // saltando al renglon de abajo cuando el ancho era justo). Ahora:
    // - flex-nowrap + overflow-x-auto: nunca se rompe a 2 filas; si el
    //   ancho de pantalla es muy chico, scroll horizontal interno.
    // - max-w-5xl + selects mas compactos para que en desktops modernos
    //   todo entre comodo en una linea.
    // V040.3 — barra mas compacta (max-w-3xl, menos padding) para que
    // se vea como un floating toolbar premium tipo patrón premium, no
    // como un mega-banner que ocupa la mitad de la pantalla.
    // V052.1 — Rediseno alineado con la BulkBar de Asignacion.
    // Antes la barra de Leads se sentia 'cargada' (3 separadores
    // verticales, padding chico, controles aprietados). Ahora:
    //   - rounded-2xl + px-5 py-3 (mismo padding generoso que Asignacion)
    //   - Contador 7x7 (mas presente)
    //   - Sin separadores verticales: ArrowRightLeft como pivot visual
    //   - "lead seleccionado" textual completo
    <div className="sticky bottom-4 z-40 mx-auto max-w-5xl px-4">
      <div className="bg-slate-900 text-white rounded-2xl shadow-2xl px-5 py-3 flex flex-col gap-1.5">
        <div className="flex items-center gap-3 flex-wrap">
          {/* Contador */}
          <div className="flex items-center gap-2 shrink-0">
            <span className="bg-[var(--brand-primary)] text-white text-sm font-bold w-7 h-7 rounded-full flex items-center justify-center shadow-sm">
              {count}
            </span>
            <span className="text-sm font-medium whitespace-nowrap">
              lead{count !== 1 ? 's' : ''} seleccionado{count !== 1 ? 's' : ''}
            </span>
          </div>

          <ArrowRightLeft size={14} className="text-slate-500 shrink-0" />

          {/* Accion: Cambiar estado */}
          <div className="flex items-center gap-1.5 shrink-0">
            <select
              value={toEstadoId}
              onChange={e => setToEstadoId(e.target.value)}
              className="text-sm bg-slate-800 border border-slate-700 text-white rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-500 min-w-[130px]"
            >
              <option value="">Estado…</option>
              {estados.map(e => (
                <option key={e.id} value={e.id}>{e.nombre}</option>
              ))}
            </select>
            <button
              disabled={!toEstadoId || isChangingEstado}
              onClick={handleEstadoClick}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-violet-600 hover:bg-violet-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors shrink-0 whitespace-nowrap"
            >
              <Tags size={13} />
              {isChangingEstado ? 'Cambiando…' : 'Cambiar'}
            </button>
          </div>

          {/* Accion: Cambiar fuente (solo admin) */}
          {canChangeFuente && (
            <div className="flex items-center gap-1.5 shrink-0">
              <select
                value={toFuenteId}
                onChange={e => setToFuenteId(e.target.value)}
                className="text-sm bg-slate-800 border border-slate-700 text-white rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-500 min-w-[130px]"
              >
                <option value="">Fuente…</option>
                {fuentes.filter(f => f.activo !== false).map(f => (
                  <option key={f.id} value={f.id}>{f.nombre}</option>
                ))}
              </select>
              <button
                disabled={!toFuenteId || isChangingFuente}
                onClick={handleFuenteClick}
                className="flex items-center gap-1.5 px-3 py-1.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors shrink-0 whitespace-nowrap shadow-sm"
              >
                <Globe size={13} />
                {isChangingFuente ? 'Cambiando…' : 'Cambiar'}
              </button>
            </div>
          )}

          {/* Accion: Asignar/Reasignar */}
          <div className="flex items-center gap-1.5 shrink-0 flex-1 min-w-[260px]">
            <select
              value={toAsesorId}
              onChange={e => setToAsesorId(e.target.value)}
              className="flex-1 min-w-[160px] text-sm bg-slate-800 border border-slate-700 text-white rounded-lg px-3 py-1.5 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            >
              <option value="">→ {actionLabel} a…</option>
              <option value="__unassigned__" className="text-amber-400 font-semibold bg-slate-900">
                ⚪ Sin asignar
              </option>
              {Array.isArray(groups) && groups.length > 0 ? (
                groups.map(g => (
                  <optgroup
                    key={g.supervisor_id}
                    label={
                      g.supervisor_id === '__supers__'
                        ? (g.supervisor_nombre || 'Supervisores')
                        : `Equipo: ${g.supervisor_nombre || ''}`
                    }
                  >
                    {(g.asesores || []).map(a => (
                      <option key={a.id} value={a.id}>
                        {a.nombre_completo || a.email}
                      </option>
                    ))}
                  </optgroup>
                ))
              ) : (
                (() => {
                  const asesoresList     = (asesores || []).filter(a => a.role !== 'supervisor')
                  const supervisoresList = (asesores || []).filter(a => a.role === 'supervisor')
                  return (
                    <>
                      {asesoresList.length > 0 && (
                        <optgroup label="Asesores">
                          {asesoresList.map(a => (
                            <option key={a.id} value={a.id}>
                              {a.nombre_completo || a.email}
                            </option>
                          ))}
                        </optgroup>
                      )}
                      {supervisoresList.length > 0 && (
                        <optgroup label="Supervisores">
                          {supervisoresList.map(a => (
                            <option key={a.id} value={a.id}>
                              {a.nombre_completo || a.email}
                            </option>
                          ))}
                        </optgroup>
                      )}
                    </>
                  )
                })()
              )}
            </select>
            <button
              disabled={!toAsesorId || isAssigning}
              onClick={handleAssignClick}
              className={`flex items-center gap-1.5 px-3 py-1.5 ${
                isUnassignSelected
                  ? 'bg-amber-600 hover:bg-amber-500'
                  : 'bg-[var(--brand-primary)] hover:bg-[var(--brand-primary-hover)]'
              } disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors shrink-0 whitespace-nowrap shadow-sm`}
            >
              {isUnassignSelected ? <UserX size={13} /> : <UserPlus size={13} />}
              {isAssigning
                ? (isUnassignSelected ? 'Desasignando…' : 'Procesando…')
                : (isUnassignSelected ? 'Desasignar' : actionLabel)}
            </button>
          </div>

          {/* Accion: Revertir Bolsa TMK */}
          {recycledCount > 0 && onRevertTmk && (
            <button
              type="button"
              disabled={isRevertingTmk}
              onClick={onRevertTmk}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-rose-600 hover:bg-rose-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors shrink-0 whitespace-nowrap shadow-sm"
              title="Devolver leads a su estado y asesor anterior a la Bolsa TMK"
            >
              <RotateCcw size={13} className={isRevertingTmk ? 'animate-spin' : ''} />
              {isRevertingTmk ? 'Revirtiendo…' : `Revertir TMK (${recycledCount})`}
            </button>
          )}

          {/* Accion: Devolver a Históricos */}
          {historicosCount > 0 && onDevolverHistoricos && (
            <button
              type="button"
              disabled={isDevolviendoHistoricos}
              onClick={onDevolverHistoricos}
              className="flex items-center gap-1.5 px-3 py-1.5 bg-amber-600 hover:bg-amber-500 disabled:opacity-40 disabled:cursor-not-allowed text-white text-sm font-medium rounded-lg transition-colors shrink-0 whitespace-nowrap shadow-sm"
              title="Devolver leads a Históricos (quita asesor y supervisor y los retira de la lista activa)"
            >
              <Archive size={13} className={isDevolviendoHistoricos ? 'animate-spin' : ''} />
              {isDevolviendoHistoricos ? 'Devolviendo…' : `Devolver a Históricos (${historicosCount})`}
            </button>
          )}

          {/* Accion: Eliminar — solo icono con acento rojo permanente */}
          <button
            disabled={isDeleting}
            onClick={onDelete}
            className="w-9 h-9 flex items-center justify-center rounded-lg bg-red-500/10 text-red-400 border border-red-500/20 hover:bg-red-500/20 hover:text-red-300 hover:border-red-500/40 disabled:opacity-40 disabled:cursor-not-allowed transition-colors shrink-0"
            title={isDeleting ? 'Eliminando…' : `Eliminar ${count} lead${count !== 1 ? 's' : ''}`}
            aria-label="Eliminar leads seleccionados"
          >
            <Trash2 size={15} />
          </button>

          {/* Cerrar */}
          <button
            onClick={onClear}
            className="w-8 h-8 flex items-center justify-center rounded-lg text-slate-400 hover:bg-slate-700 hover:text-white transition-colors shrink-0"
            title="Limpiar selección"
            aria-label="Limpiar selección"
          >
            <X size={16} />
          </button>
        </div>

        {/* Linea secundaria — desglose con dots de color */}
        {(breakdown.yaAsignados > 0 || breakdown.crossSupervisor || historicosCount > 0) && (
          <div className="flex items-center gap-4 text-xs text-slate-300 flex-wrap pl-9">
            {breakdown.sinAsignar > 0 && (
              <span className="inline-flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400" aria-hidden="true" />
                <span className="font-semibold text-emerald-400">{breakdown.sinAsignar}</span>
                <span>sin asignar</span>
              </span>
            )}
            {breakdown.yaAsignados > 0 && (
              <span className="inline-flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400" aria-hidden="true" />
                <span className="font-semibold text-amber-400">{breakdown.yaAsignados}</span>
                <span>ya con asesor</span>
              </span>
            )}
            {historicosCount > 0 && (
              <span className="inline-flex items-center gap-1.5 text-amber-300">
                <Archive size={11} />
                <span className="font-semibold text-amber-300">{historicosCount}</span>
                <span>de origen histórico</span>
              </span>
            )}
            {breakdown.crossSupervisor && (
              <span className="inline-flex items-center gap-1 text-amber-400">
                <AlertTriangle size={11} />
                cruza varios equipos
              </span>
            )}
          </div>
        )}
      </div>
    </div>
  )
}
