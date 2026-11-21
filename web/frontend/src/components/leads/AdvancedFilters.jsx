/**
 * AdvancedFilters — builder dinámico estilo patrón premium / patrón premium.
 *
 * Cada filtro es una fila independiente con:
 *   [📍 Campo ▾]  [Operador ▾]  [Valor]   🗑️
 *
 * Permite agregar/eliminar filtros dinámicamente. El estado interno es
 * una lista de objetos { id, field, operator, value }. Al cambiar,
 * llama onChange con un dict plano que el caller traduce a query params.
 *
 * Operadores soportados según tipo de campo:
 *   select  → 'eq' (es)
 *   text    → 'contains' (contiene)
 *   date    → 'gte' (desde), 'lte' (hasta)
 *   bool    → 'true' (sí)
 *
 * NO soporta grupos AND/OR — para CRMs medianos como Palma del Río
 * la composición es siempre AND y agregar OR confunde más que ayuda.
 */
import { useState, useRef, useEffect, useMemo } from 'react'
import FieldPicker from '@/components/ui/FieldPicker'
// V067.10 — createPortal removed: solo se usaba en el FieldPicker local
// duplicado, ahora extraido a components/ui/FieldPicker.jsx
import {
  Filter, Plus, Trash2, X, Tag, Globe, User, UserCheck, Megaphone,
  Sparkles, Calendar, Archive, ChevronDown, Search, Plug, MapPin, History, Clock, ClipboardList, CheckCircle2,
} from 'lucide-react'
import PortalSelect from '@/components/ui/PortalSelect'
import { getSubestadosForEstado } from '@/components/leads/CambioEstadoModal'

const FIELD_ICONS = {
  estado: Tag,
  subestado: Tag,
  origen: Globe,
  fuente_id: Globe,
  supervisor_id: UserCheck,
  asesor_id: User,
  asesor_historico_id: History,
  campana: Megaphone,
  calidad: Sparkles,
  fecha_desde: Calendar,
  fecha_hasta: Calendar,
  fecha_asig_desde: Calendar,
  fecha_asig_hasta: Calendar,
  fecha_actividad_desde: Calendar,
  fecha_actividad_hasta: Calendar,
  con_antecedentes: Archive,
  search: Search,
  api_client_id: Plug,
  api_client_legacy_slug: Archive,
  estado_cola: Clock,
  ficha_tecnica_estado: ClipboardList,
  filtro_fecha_gestion: Clock,
  filtro_fecha_cita: Calendar,
  filtro_cita_atendida: CheckCircle2,
}

// Operadores por tipo de campo. Las fechas tienen un operador FIJO segun
// el campo (fecha_desde → 'desde', fecha_hasta → 'hasta'), no intercambiable.
const OPERATORS_BY_TYPE = {
  select: [{ v: 'eq', label: 'es' }],
  text: [{ v: 'contains', label: 'contiene' }],
  date_from: [{ v: 'gte', label: 'desde' }],
  date_to: [{ v: 'lte', label: 'hasta' }],
  bool: [{ v: 'true', label: 'sí' }],
}

export default function AdvancedFilters({
  // catálogos
  estados = [],
  fuentes = [],
  asesores = [],
  supervisores = [],
  campanas = [],
  calidades = [],
  apiClients = [],          // V062: proveedores activos del catalogo
  apiClientsLegacy = [],    // V062: slugs legacy realmente en uso (post-unlink)
  sedes = [],               // V065: sedes activas
  canFilterByAsesor = true,
  canFilterBySupervisor = true,
  // estado actual (dict plano: { fuente_id: 5, calidad: 'FRIO', ... })
  values = {},
  estadoFilter = '',
  onChange,
  onChangeEstado,
}) {
  const activeEstadoObj = estados.find(e => String(e.id) === String(estadoFilter || values.estado_id || values.estado))
  const subestadosDisponibles = getSubestadosForEstado(activeEstadoObj?.nombre)

  // Convierte el dict de valores externos en una lista de filtros para
  // inicializacion y sincronizacion con vistas guardadas.
  const buildFromValues = (vals = {}, estado = '') => {
    const list = []
    if (estado != null && estado !== '') list.push({ id: 'estado', field: 'estado', operator: 'eq', value: String(estado) })
    if (vals.subestado) list.push({ id: 'subestado', field: 'subestado', operator: 'eq', value: String(vals.subestado) })
    if (vals.estado_cola) list.push({ id: 'estado_cola', field: 'estado_cola', operator: 'eq', value: String(vals.estado_cola) })
    if (vals.origen) list.push({ id: 'origen', field: 'origen', operator: 'eq', value: String(vals.origen) })
    if (vals.fuente_id) list.push({ id: 'fuente_id', field: 'fuente_id', operator: 'eq', value: String(vals.fuente_id) })
    if (vals.supervisor_id) list.push({ id: 'supervisor_id', field: 'supervisor_id', operator: 'eq', value: String(vals.supervisor_id) })
    if (vals.asesor_id) list.push({ id: 'asesor_id', field: 'asesor_id', operator: 'eq', value: String(vals.asesor_id) })
    if (vals.asesor_historico_id) list.push({ id: 'asesor_historico_id', field: 'asesor_historico_id', operator: 'eq', value: String(vals.asesor_historico_id) })
    if (vals.campana) list.push({ id: 'campana', field: 'campana', operator: 'contains', value: String(vals.campana) })
    if (vals.calidad) list.push({ id: 'calidad', field: 'calidad', operator: 'eq', value: String(vals.calidad) })
    if (vals.fecha_desde) list.push({ id: 'fecha_desde', field: 'fecha_desde', operator: 'gte', value: String(vals.fecha_desde) })
    if (vals.fecha_hasta) list.push({ id: 'fecha_hasta', field: 'fecha_hasta', operator: 'lte', value: String(vals.fecha_hasta) })
    if (vals.fecha_asig_desde) list.push({ id: 'fecha_asig_desde', field: 'fecha_asig_desde', operator: 'gte', value: String(vals.fecha_asig_desde) })
    if (vals.fecha_asig_hasta) list.push({ id: 'fecha_asig_hasta', field: 'fecha_asig_hasta', operator: 'lte', value: String(vals.fecha_asig_hasta) })
    if (vals.fecha_actividad_desde) list.push({ id: 'fecha_actividad_desde', field: 'fecha_actividad_desde', operator: 'gte', value: String(vals.fecha_actividad_desde) })
    if (vals.fecha_actividad_hasta) list.push({ id: 'fecha_actividad_hasta', field: 'fecha_actividad_hasta', operator: 'lte', value: String(vals.fecha_actividad_hasta) })
    if (vals.con_antecedentes) list.push({ id: 'con_antecedentes', field: 'con_antecedentes', operator: 'true', value: true })
    if (vals.api_client_id) list.push({ id: 'api_client_id', field: 'api_client_id', operator: 'eq', value: String(vals.api_client_id) })
    if (vals.api_client_legacy_slug) list.push({ id: 'api_client_legacy_slug', field: 'api_client_legacy_slug', operator: 'eq', value: String(vals.api_client_legacy_slug) })
    if (vals.sede_id) list.push({ id: 'sede_id', field: 'sede_id', operator: 'eq', value: String(vals.sede_id) })
    // V084: filtros por atribución del recontacto
    if (vals.recontacto_campana) list.push({ id: 'recontacto_campana', field: 'recontacto_campana', operator: 'contains', value: String(vals.recontacto_campana) })
    if (vals.recontacto_anuncio) list.push({ id: 'recontacto_anuncio', field: 'recontacto_anuncio', operator: 'contains', value: String(vals.recontacto_anuncio) })
    if (vals.recontacto_conjunto) list.push({ id: 'recontacto_conjunto', field: 'recontacto_conjunto', operator: 'contains', value: String(vals.recontacto_conjunto) })
    if (vals.recontacto_fuente_id) list.push({ id: 'recontacto_fuente_id', field: 'recontacto_fuente_id', operator: 'eq', value: String(vals.recontacto_fuente_id) })
    if (vals.recontacto_desde) list.push({ id: 'recontacto_desde', field: 'recontacto_desde', operator: 'gte', value: String(vals.recontacto_desde) })
    if (vals.recontacto_hasta) list.push({ id: 'recontacto_hasta', field: 'recontacto_hasta', operator: 'lte', value: String(vals.recontacto_hasta) })
    if (vals.recontacto_api_client_id) list.push({ id: 'recontacto_api_client_id', field: 'recontacto_api_client_id', operator: 'eq', value: String(vals.recontacto_api_client_id) })
    // V086: tocado por proveedor (origen O recontacto)
    if (vals.tocado_por_api_client_id) list.push({ id: 'tocado_por_api_client_id', field: 'tocado_por_api_client_id', operator: 'eq', value: String(vals.tocado_por_api_client_id) })
    // V124: Ficha técnica
    if (vals.ficha_tecnica_estado) list.push({ id: 'ficha_tecnica_estado', field: 'ficha_tecnica_estado', operator: 'eq', value: String(vals.ficha_tecnica_estado) })
    if (vals.filtro_fecha_gestion) list.push({ id: 'filtro_fecha_gestion', field: 'filtro_fecha_gestion', operator: 'eq', value: String(vals.filtro_fecha_gestion) })
    if (vals.filtro_fecha_cita) list.push({ id: 'filtro_fecha_cita', field: 'filtro_fecha_cita', operator: 'eq', value: String(vals.filtro_fecha_cita) })
    if (vals.filtro_cita_atendida) list.push({ id: 'filtro_cita_atendida', field: 'filtro_cita_atendida', operator: 'eq', value: String(vals.filtro_cita_atendida) })
    return list
  }

  // Definición de campos disponibles.
  const FIELDS = useMemo(() => {
    const base = [
      // ── Datos del lead ──────────────────────────────────────────────
      {
        v: 'estado', label: 'Estado', group: 'Datos del lead',
        type: 'select', icon: Tag,
        description: 'Etapa del pipeline donde está el lead.'
      },
      {
        v: 'estado_cola', label: 'Estado en cola / Asignación', group: 'Datos del lead',
        type: 'select', icon: Clock,
        description: 'Filtrar por estancados (>24h sin asesor), pendientes o asignados.'
      },
      ...(subestadosDisponibles.length > 0 ? [{
        v: 'subestado',
        label: `Subestado (${activeEstadoObj?.nombre})`,
        group: 'Datos del lead',
        type: 'select',
        icon: Tag,
        description: `Subestados específicos para el estado ${activeEstadoObj?.nombre}.`,
      }] : []),
      ...(canFilterBySupervisor ? [{
        v: 'supervisor_id', label: 'Supervisor', group: 'Datos del lead',
        type: 'select', icon: UserCheck,
        description: 'Supervisor directo del equipo.'
      }] : []),
      ...(canFilterByAsesor ? [{
        v: 'asesor_id', label: 'Asesor', group: 'Datos del lead',
        type: 'select', icon: User,
        description: 'Asesor actualmente asignado.'
      }] : []),
      ...(canFilterByAsesor ? [{
        v: 'asesor_historico_id', label: 'Asesor histórico (en historial)', group: 'Datos del lead',
        type: 'select', icon: History,
        description: 'Leads que pertenecieron a este asesor en el historial pero hoy están a cargo de otra persona.'
      }] : []),
      ...(calidades.length > 0 ? [{
        v: 'calidad', label: 'Calidad', group: 'Datos del lead',
        type: 'select', icon: Sparkles,
        description: 'Frío / Tibio / Caliente según el catálogo.'
      }] : []),
      {
        v: 'ficha_tecnica_estado', label: 'Ficha técnica', group: 'Datos del lead',
        type: 'select', icon: ClipboardList,
        description: 'Pendiente / Incompleta / Completa.'
      },
      {
        v: 'filtro_fecha_gestion', label: 'Próxima gestión (Fecha / Estado)', group: 'Datos del lead',
        type: 'select', icon: Clock,
        description: 'Filtrar por vencidas, sin fecha asignada, hoy o al día.'
      },
      {
        v: 'filtro_fecha_cita', label: 'Citas (Fecha)', group: 'Datos del lead',
        type: 'select', icon: Calendar,
        description: 'Filtrar citas por vencidas, sin fecha, hoy o al día.'
      },
      {
        v: 'filtro_cita_atendida', label: 'Citas (Atención)', group: 'Datos del lead',
        type: 'select', icon: CheckCircle2,
        description: 'Filtrar por citas no atendidas, atendidas o no asistió.'
      },
      {
        v: 'fecha_desde', label: 'Creado desde', group: 'Datos del lead',
        type: 'date_from', icon: Calendar,
        description: 'Fecha de creación del lead, límite inferior.'
      },
      {
        v: 'fecha_hasta', label: 'Creado hasta', group: 'Datos del lead',
        type: 'date_to', icon: Calendar,
        description: 'Fecha de creación del lead, límite superior.'
      },
      {
        v: 'fecha_asig_desde', label: 'Asignado desde', group: 'Datos del lead',
        type: 'date_from', icon: Calendar,
        description: 'Fecha en que pasó a un asesor, límite inferior.'
      },
      {
        v: 'fecha_asig_hasta', label: 'Asignado hasta', group: 'Datos del lead',
        type: 'date_to', icon: Calendar,
        description: 'Fecha en que pasó a un asesor, límite superior.'
      },
      {
        v: 'fecha_actividad_desde', label: 'Última actividad desde', group: 'Datos del lead',
        type: 'date_from', icon: Calendar,
        description: 'Fecha y hora del último registro o actividad del lead, límite inferior.'
      },
      {
        v: 'fecha_actividad_hasta', label: 'Última actividad hasta', group: 'Datos del lead',
        type: 'date_to', icon: Calendar,
        description: 'Fecha y hora del último registro o actividad del lead, límite superior.'
      },
      ...(sedes.length > 0
        ? [{
          v: 'sede_id', label: 'Sede', group: 'Datos del lead',
          type: 'select', icon: MapPin,
          description: 'Sede física a la que va destinado el lead.'
        }]
        : []),

      // ── Origen y atribución ─────────────────────────────────────────
      {
        v: 'origen', label: 'Origen', group: 'Origen y atribución',
        type: 'select', icon: Globe,
        description: 'Plataforma o canal de origen: TikTok, Facebook, Instagram, WhatsApp, etc.'
      },
      {
        v: 'fuente_id', label: 'Fuente', group: 'Origen y atribución',
        type: 'select', icon: Globe,
        description: 'Canal por donde entró: Facebook, Instagram, TikTok, etc.'
      },
      {
        v: 'campana', label: 'Campaña', group: 'Origen y atribución',
        type: 'text', icon: Megaphone,
        description: 'Campaña original del lead (texto libre).'
      },
      ...(apiClients.length > 0
        ? [{
          v: 'api_client_id', label: 'Proveedor (origen del lead)',
          group: 'Origen y atribución', type: 'select', icon: Plug,
          description: 'Proveedor activo que creó el lead originalmente.'
        }]
        : []),
      ...(apiClientsLegacy.length > 0
        ? [{
          v: 'api_client_legacy_slug', label: 'Proveedor archivado (origen)',
          group: 'Origen y atribución', type: 'select', icon: Archive,
          description: 'Proveedor original que ya está desvinculado del CRM.'
        }]
        : []),

      // ── Re-engagement (recontactos) ─────────────────────────────────
      {
        v: 'con_antecedentes', label: 'Sólo con recontactos',
        group: 'Re-engagement (recontactos)', type: 'bool', icon: Archive,
        description: 'Leads que tienen al menos un recontacto registrado.'
      },
      {
        v: 'recontacto_campana', label: 'Campaña del recontacto',
        group: 'Re-engagement (recontactos)', type: 'text', icon: Sparkles,
        description: 'Campaña con la que el cliente volvió a interactuar.'
      },
      {
        v: 'recontacto_anuncio', label: 'Anuncio del recontacto',
        group: 'Re-engagement (recontactos)', type: 'text', icon: Sparkles,
        description: 'Nivel Ad de la nueva interacción (Meta Ads y similares).'
      },
      {
        v: 'recontacto_conjunto', label: 'Conjunto del recontacto',
        group: 'Re-engagement (recontactos)', type: 'text', icon: Sparkles,
        description: 'Nivel Ad Set / Ad Group de la nueva interacción.'
      },
      {
        v: 'recontacto_fuente_id', label: 'Fuente del recontacto',
        group: 'Re-engagement (recontactos)', type: 'select', icon: Sparkles,
        description: 'Canal por donde el cliente volvió (puede diferir del origen).'
      },
      {
        v: 'recontacto_desde', label: 'Recontacto desde',
        group: 'Re-engagement (recontactos)', type: 'date_from', icon: Sparkles,
        description: 'Fecha del recontacto, límite inferior.'
      },
      {
        v: 'recontacto_hasta', label: 'Recontacto hasta',
        group: 'Re-engagement (recontactos)', type: 'date_to', icon: Sparkles,
        description: 'Fecha del recontacto, límite superior.'
      },
      ...(apiClients.length > 0
        ? [{
          v: 'recontacto_api_client_id', label: 'Proveedor del recontacto',
          group: 'Re-engagement (recontactos)', type: 'select', icon: Sparkles,
          description: 'Proveedor que envió al menos un recontacto del lead.'
        }]
        : []),

      // ── Búsqueda combinada ──────────────────────────────────────────
      ...(apiClients.length > 0
        ? [{
          v: 'tocado_por_api_client_id', label: 'Proveedor (origen o recontacto)',
          group: 'Búsqueda combinada', type: 'select', icon: Plug,
          description: 'Leads tocados por el proveedor: como origen O como recontacto.'
        }]
        : []),
    ]
    return base
  }, [canFilterBySupervisor, canFilterByAsesor, calidades.length, apiClients.length, apiClientsLegacy.length, sedes.length])

  const computeSnapshot = (vals = {}, estado = '') => {
    const clean = {}
    if (estado != null && estado !== '') clean._estado = String(estado)
    for (const [k, v] of Object.entries(vals || {})) {
      if (v === null || v === undefined || v === '' || v === false) continue
      clean[k] = typeof v === 'boolean' ? v : String(v).trim()
    }
    const keys = Object.keys(clean).sort()
    return '{' + keys.map(k => JSON.stringify(k) + ':' + JSON.stringify(clean[k])).join(',') + '}'
  }

  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(() => buildFromValues(values, estadoFilter))
  const lastPropagatedSnapshotRef = useRef(computeSnapshot(values, estadoFilter))
  const ref = useRef(null)

  // Sincronizacion bidireccional: cuando los valores externos cambian
  // (por aplicar una vista guardada, cambiar estado en tabs o limpiar filtros),
  // se reconstruye el draft para reflejar la configuracion en el builder.
  useEffect(() => {
    const incoming = computeSnapshot(values, estadoFilter)
    if (incoming !== lastPropagatedSnapshotRef.current) {
      lastPropagatedSnapshotRef.current = incoming
      setDraft(buildFromValues(values, estadoFilter))
    }
  }, [values, estadoFilter])

  // Cantidad de filtros aplicados (con valor real) — para el badge del boton.
  const appliedCount = useMemo(() =>
    draft.filter(f => f.field && (f.value === true || (f.value !== '' && f.value != null))).length,
    [draft]
  )

  // Cerrar al click afuera. Excluye los popups portalizados (FieldPicker
  // se renderiza con createPortal a document.body — está marcado con
  // data-filter-popup para que un click dentro no cierre el panel).
  useEffect(() => {
    if (!open) return
    const handler = (e) => {
      if (!ref.current) return
      if (ref.current.contains(e.target)) return
      if (e.target.closest && e.target.closest('[data-filter-popup]')) return
      setOpen(false)
    }
    document.addEventListener('mousedown', handler)
    return () => document.removeEventListener('mousedown', handler)
  }, [open])


  const propagate = (newDraft) => {
    setDraft(newDraft)
    // Convertir lista a dict plano y notificar
    const dict = {
      estado_cola: '',
      origen: '',
      fuente_id: '',
      supervisor_id: '',
      asesor_id: '',
      asesor_historico_id: '',
      campana: '',
      calidad: '',
      fecha_desde: '',
      fecha_hasta: '',
      fecha_asig_desde: '',
      fecha_asig_hasta: '',
      fecha_actividad_desde: '',
      fecha_actividad_hasta: '',
      con_antecedentes: false,
      api_client_id: '',
      api_client_legacy_slug: '',
      sede_id: '',
      recontacto_campana: '',
      recontacto_anuncio: '',
      recontacto_conjunto: '',
      recontacto_fuente_id: '',
      recontacto_desde: '',
      recontacto_hasta: '',
      recontacto_api_client_id: '',
      tocado_por_api_client_id: '',
      ficha_tecnica_estado: '',
      filtro_fecha_gestion: '',
      filtro_fecha_cita: '',
      filtro_cita_atendida: '',
    }
    let estadoNew = ''
    newDraft.forEach(f => {
      if (!f.field || f.value === '' || f.value == null) return
      if (f.field === 'estado') estadoNew = String(f.value)
      else if (f.field === 'con_antecedentes') dict[f.field] = !!f.value
      else dict[f.field] = f.value
    })
    lastPropagatedSnapshotRef.current = computeSnapshot(dict, estadoNew)
    onChange && onChange(dict)
    if (onChangeEstado) onChangeEstado(estadoNew)
  }

  const addFilter = () => {
    // Encontrar primer campo disponible (no usado todavía)
    const used = new Set(draft.map(f => f.field))
    const next = FIELDS.find(f => !used.has(f.v))
    if (!next) return  // todos los campos ya están usados
    const op = OPERATORS_BY_TYPE[next.type][0].v
    const newRow = {
      id: `f-${Date.now()}-${Math.random()}`,
      field: next.v,
      operator: op,
      value: next.type === 'bool' ? true : '',
    }
    const newDraft = [...draft, newRow]
    // Si el value default es valido (bool=true), propagamos para que aplique
    // de inmediato. Si es vacio (select/text/date), solo actualizamos el draft
    // local — el parent se entera cuando el user llene el value.
    if (newRow.value === true || (newRow.value !== '' && newRow.value != null)) {
      propagate(newDraft)
    } else {
      setDraft(newDraft)
    }
  }

  const removeFilter = (id) => {
    propagate(draft.filter(f => f.id !== id))
  }

  const hasMeaningfulValue = (row) =>
    row && (row.value === true || (row.value !== '' && row.value != null))

  const updateFilter = (id, patch) => {
    const oldRow = draft.find(f => f.id === id)
    const oldActive = hasMeaningfulValue(oldRow)

    const newDraft = draft.map(f => f.id === id ? { ...f, ...patch } : f)
    // Si cambió el campo, resetear valor y operador segun el nuevo tipo
    if ('field' in patch) {
      const newField = FIELDS.find(x => x.v === patch.field)
      if (newField) {
        const idx = newDraft.findIndex(f => f.id === id)
        newDraft[idx] = {
          ...newDraft[idx],
          operator: OPERATORS_BY_TYPE[newField.type][0].v,
          value: newField.type === 'bool' ? true : '',
        }
      }
    }
    const newActive = hasMeaningfulValue(newDraft.find(f => f.id === id))

    // Solo propagar (= disparar fetch en parent) si el cambio afecta a un
    // filtro activo. Cambiar el campo de un filtro vacio a otro vacio no
    // debe refrescar la tabla (evita parpadeo de "Cargando...").
    if (oldActive || newActive) {
      propagate(newDraft)
    } else {
      setDraft(newDraft)
    }
  }

  const clearAll = () => propagate([])

  return (
    <div ref={ref} className="relative">
      <button
        onClick={() => setOpen(!open)}
        className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-lg border text-sm font-medium transition-colors
          ${appliedCount > 0
            ? 'border-indigo-300 bg-indigo-50 text-indigo-700 hover:bg-indigo-100'
            : 'border-gray-200 bg-white text-gray-700 hover:bg-gray-50'}`}
      >
        <Filter size={14} />
        Filtros
        {appliedCount > 0 && (
          <span className="bg-indigo-600 text-white text-[10px] font-bold px-1.5 py-0.5 rounded-full min-w-[18px] text-center leading-tight">
            {appliedCount}
          </span>
        )}
      </button>

      {open && (
        <div
          className={`absolute top-full left-0 mt-2 z-40 bg-white border border-gray-200 rounded-xl shadow-[0_12px_40px_rgba(0,0,0,0.12)] max-w-[calc(100vw-2rem)] ${draft.length === 0 ? 'w-[320px]' : 'w-[680px]'
            }`}
        >
          {draft.length === 0 ? (
            // Empty state compacto estilo patrón premium
            <>
              <button
                onClick={addFilter}
                className="w-full inline-flex items-center gap-2 px-4 py-2.5 text-sm text-indigo-600 hover:bg-indigo-50 font-medium transition-colors rounded-t-xl"
              >
                <Plus size={14} /> Añadir filtro
              </button>
              <p className="px-4 py-2.5 text-xs text-gray-400 border-t border-gray-100 text-center rounded-b-xl bg-gray-50/40">
                No hay filtros añadidos
              </p>
            </>
          ) : (
            <>
              {/* Body */}
              <div className="wa-scrollbar p-4 max-h-[60vh] overflow-y-auto overflow-x-hidden">
                <div className="space-y-2.5">
                  {draft.map((f, idx) => (
                    <FilterRow
                      key={f.id}
                      filter={f}
                      isFirst={idx === 0}
                      fields={FIELDS}
                      estados={estados}
                      subestadosDisponibles={subestadosDisponibles}
                      fuentes={fuentes}
                      asesores={asesores}
                      supervisores={supervisores}
                      campanas={campanas}
                      calidades={calidades}
                      apiClients={apiClients}
                      apiClientsLegacy={apiClientsLegacy}
                      sedes={sedes}
                      onChange={(patch) => updateFilter(f.id, patch)}
                      onRemove={() => removeFilter(f.id)}
                      usedFields={new Set(draft.filter(x => x.id !== f.id).map(x => x.field))}
                    />
                  ))}
                </div>
              </div>
              {/* Footer */}
              <div className="flex items-center gap-2 px-4 py-2.5 border-t border-gray-100 bg-gray-50/40 rounded-b-xl">
                <button
                  onClick={addFilter}
                  disabled={draft.length >= FIELDS.length}
                  className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md text-xs text-indigo-600 hover:bg-indigo-50 font-medium disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                >
                  <Plus size={13} /> Añadir filtro
                </button>
                <button
                  onClick={clearAll}
                  className="ml-auto inline-flex items-center gap-1 px-2 py-1 rounded-md text-xs text-gray-500 hover:text-gray-700 hover:bg-gray-100"
                >
                  <X size={11} /> Limpiar todo
                </button>
              </div>
            </>
          )}
        </div>
      )}
    </div>
  )
}

function FilterRow({
  filter, isFirst, fields, estados, subestadosDisponibles = [], fuentes, asesores, supervisores, campanas, calidades,
  apiClients = [], apiClientsLegacy = [], sedes = [],
  onChange, onRemove, usedFields,
}) {
  const fieldDef = fields.find(f => f.v === filter.field) || fields[0]
  const operators = OPERATORS_BY_TYPE[fieldDef.type] || OPERATORS_BY_TYPE.text

  return (
    <div className="flex items-center gap-2 group">
      <span className="text-[11px] font-medium uppercase tracking-wide text-gray-400 w-10 shrink-0 text-right">
        {isFirst ? 'Donde' : 'Y'}
      </span>
      {/* Campo */}
      <FieldPicker
        fields={fields}
        value={filter.field}
        onChange={(v) => onChange({ field: v })}
        usedFields={usedFields}
      />
      {/* Operador — chip plano (la mayoría son fijos por tipo) */}
      {operators.length > 1 ? (
        <select
          value={filter.operator}
          onChange={e => onChange({ operator: e.target.value })}
          className="text-xs border border-gray-200 rounded-md px-2 py-1.5 bg-white hover:bg-gray-50 focus:outline-none focus:ring-2 focus:ring-indigo-500 min-w-[90px] cursor-pointer transition-colors"
        >
          {operators.map(o => <option key={o.v} value={o.v}>{o.label}</option>)}
        </select>
      ) : (
        <span className="text-[11px] font-medium text-gray-500 bg-gray-100 px-2 py-1 rounded select-none whitespace-nowrap">
          {operators[0].label}
        </span>
      )}
      {/* Valor — render según tipo */}
      <div className="flex-1 min-w-0">
        <ValueInput
          field={filter.field}
          value={filter.value}
          onChange={(v) => onChange({ value: v })}
          estados={estados}
          subestadosDisponibles={subestadosDisponibles}
          fuentes={fuentes}
          asesores={asesores}
          supervisores={supervisores}
          campanas={campanas}
          calidades={calidades}
          apiClients={apiClients}
          apiClientsLegacy={apiClientsLegacy}
          sedes={sedes}
        />
      </div>
      <button
        onClick={onRemove}
        className="text-gray-300 hover:text-red-500 p-1.5 rounded-md hover:bg-red-50 transition-colors opacity-60 group-hover:opacity-100"
        title="Eliminar filtro"
      >
        <Trash2 size={13} />
      </button>
    </div>
  )
}

// V067.10 — FieldPicker movido a components/ui/FieldPicker.jsx
// para deduplicacion (antes existia copia identica aqui y en FilterBuilder).
// El import se hace al tope del archivo.

function ValueInput({
  field, value, onChange, estados, subestadosDisponibles = [], fuentes, asesores, supervisores = [], campanas, calidades,
  apiClients = [], apiClientsLegacy = [], sedes = [],
}) {
  const cls = "w-full text-xs border border-gray-200 rounded-md px-2.5 py-1.5 bg-white hover:border-gray-300 focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-indigo-400 transition-colors"

  if (field === 'estado') {
    return <PortalSelect value={value} onChange={onChange}
      options={estados.map(e => ({ value: String(e.id), label: e.nombre }))} />
  }
  if (field === 'estado_cola') {
    return (
      <PortalSelect
        value={value}
        onChange={onChange}
        options={[
          { value: 'estancados', label: '⚠️ Estancados (>24h sin asignar)' },
          { value: 'pendientes', label: '⏳ Pendientes (<24h en cola)' },
          { value: 'en_cola',    label: '📥 Todos en cola' },
          { value: 'asignados',  label: '👤 Asignados a asesor' },
        ]}
      />
    )
  }
  if (field === 'subestado') {
    return <PortalSelect value={value} onChange={onChange}
      options={subestadosDisponibles.map(s => ({ value: s, label: s }))} />
  }
  if (field === 'origen') {
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
    return <PortalSelect value={value} onChange={onChange} options={list} searchable />
  }
  if (field === 'fuente_id') {
    return <PortalSelect value={value} onChange={onChange}
      options={fuentes.map(f => ({ value: String(f.id), label: f.nombre }))} />
  }
  if (field === 'supervisor_id') {
    return (
      <PortalSelect
        value={value}
        onChange={onChange}
        options={supervisores.map(s => ({
          value: String(s.id),
          label: s.nombre_completo || s.email,
        }))}
        searchable
      />
    )
  }
  if (field === 'asesor_id' || field === 'asesor_historico_id') {
    const asesoresList = asesores.filter(a => a.role !== 'supervisor')
    const supervisoresList = asesores.filter(a => a.role === 'supervisor')
    const groups = []
    if (asesoresList.length > 0)
      groups.push({ label: 'Asesores', options: asesoresList.map(a => ({ value: String(a.id), label: a.nombre_completo || a.email })) })
    if (supervisoresList.length > 0)
      groups.push({ label: 'Supervisores', options: supervisoresList.map(a => ({ value: String(a.id), label: a.nombre_completo || a.email })) })
    return <PortalSelect value={value} onChange={onChange} groups={groups} searchable />
  }
  if (field === 'calidad') {
    return <PortalSelect value={value} onChange={onChange}
      options={calidades.map(c => ({ value: c.codigo, label: c.nombre }))} />
  }
  if (field === 'ficha_tecnica_estado') {
    return <PortalSelect value={value} onChange={onChange}
      options={[
        { value: 'pendiente', label: 'Pendiente / Incompleta' },
        { value: 'completa', label: 'Completa (6/6)' },
      ]} />
  }
  if (field === 'filtro_fecha_gestion') {
    return <PortalSelect value={value} onChange={onChange}
      options={[
        { value: 'vencidas', label: '⚠️ Vencidas (< ahora/hoy)' },
        { value: 'sin_fecha', label: '❓ Sin fecha asignada' },
        { value: 'hoy', label: '📅 Para hoy' },
        { value: 'al_dia', label: '✅ Al día / Futuras' },
      ]} />
  }
  if (field === 'filtro_fecha_cita') {
    return <PortalSelect value={value} onChange={onChange}
      options={[
        { value: 'vencidas', label: '⚠️ Vencidas (< ahora/hoy)' },
        { value: 'sin_fecha', label: '❓ Sin fecha asignada' },
        { value: 'hoy', label: '📅 Para hoy' },
        { value: 'al_dia', label: '✅ Al día / Futuras' },
      ]} />
  }
  if (field === 'filtro_cita_atendida') {
    return <PortalSelect value={value} onChange={onChange}
      options={[
        { value: 'no_atendidas', label: '⏳ No atendidas / Pendientes' },
        { value: 'atendidas', label: '✅ Atendidas' },
        { value: 'no_asistio', label: '❌ No asistió' },
      ]} />
  }
  if (field === 'api_client_id') {
    // V062: solo proveedores activos. Inactivos pueden buscarse via legacy.
    return <PortalSelect value={value} onChange={onChange}
      options={apiClients
        .filter(c => c.activo)
        .map(c => ({ value: String(c.id), label: c.nombre }))}
      searchable />
  }
  if (field === 'api_client_legacy_slug') {
    // V062: lista de slugs legacy realmente en uso (ya desvinculados).
    // El value es el slug textual, no el id (porque el client puede no
    // existir mas).
    return <PortalSelect value={value} onChange={onChange}
      options={apiClientsLegacy.map(l => ({
        value: l.slug,
        label: `${l.nombre || l.slug} (${l.leads_count})`,
      }))}
      searchable />
  }
  if (field === 'sede_id') {
    // V065: sede de destino del lead. Solo sedes activas.
    return <PortalSelect value={value} onChange={onChange}
      options={sedes.map(s => ({
        value: String(s.id),
        label: s.ciudad ? `${s.nombre} · ${s.ciudad}` : s.nombre,
      }))}
      searchable />
  }
  if (field === 'campana') {
    if (campanas.length > 0) {
      return <PortalSelect value={value} onChange={onChange}
        options={campanas.map(c => ({ value: c, label: c }))}
        searchable />
    }
    return (
      <input type="text" value={value || ''} onChange={e => onChange(e.target.value)}
        placeholder="Texto de campaña…" className={cls} />
    )
  }
  if (field === 'fecha_desde' || field === 'fecha_hasta' ||
    field === 'fecha_asig_desde' || field === 'fecha_asig_hasta' ||
    field === 'fecha_actividad_desde' || field === 'fecha_actividad_hasta' ||
    field === 'recontacto_desde' || field === 'recontacto_hasta') {
    return (
      <input type="date" value={value || ''} onChange={e => onChange(e.target.value)} className={cls} />
    )
  }
  if (field === 'con_antecedentes') {
    return (
      <label className="flex items-center gap-1.5 text-xs text-gray-700 px-2">
        <input type="checkbox" checked={!!value} onChange={e => onChange(e.target.checked)} className="rounded" />
        Sí, con antecedentes
      </label>
    )
  }
  // V084: atribución del recontacto
  if (field === 'recontacto_campana' || field === 'recontacto_anuncio' || field === 'recontacto_conjunto') {
    const placeholder =
      field === 'recontacto_campana' ? 'Nombre de la campaña…' :
        field === 'recontacto_anuncio' ? 'Nombre del anuncio…' :
          'Nombre del ad set…'
    return (
      <input type="text" value={value || ''} onChange={e => onChange(e.target.value)}
        placeholder={placeholder} className={cls} />
    )
  }
  if (field === 'recontacto_fuente_id') {
    return <PortalSelect value={value} onChange={onChange}
      options={fuentes.map(f => ({ value: String(f.id), label: f.nombre }))} />
  }
  if (field === 'recontacto_api_client_id') {
    return <PortalSelect value={value} onChange={onChange}
      options={apiClients
        .filter(c => c.activo)
        .map(c => ({ value: String(c.id), label: c.nombre }))}
      searchable />
  }
  // V086: tocado por proveedor (union origen + recontacto)
  if (field === 'tocado_por_api_client_id') {
    return <PortalSelect value={value} onChange={onChange}
      options={apiClients
        .filter(c => c.activo)
        .map(c => ({ value: String(c.id), label: c.nombre }))}
      searchable />
  }
  return (
    <input type="text" value={value || ''} onChange={e => onChange(e.target.value)} className={cls} />
  )
}

// PortalSelect movido a @/components/ui/PortalSelect (reusable en
// otras secciones: Asignacion, Historicos, etc.)
