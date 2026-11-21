/**
 * Agenda — Calendario mensual de citas agendadas.
 * Admin: todas las citas | Supervisor: equipo | Asesor: propias
 *
 * V096 — Paridad con la app movil: click en una cita abre CitaActionSheet
 * con acciones rapidas (Completada / Reprogramar / No asistio / Cancelar /
 * cambio de estado del lead inline). Antes navegaba directo al lead,
 * forzando 4 pasos para cambiar el estado de la cita.
 */
import { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import { ChevronLeft, ChevronRight, Calendar, Clock, Phone, User, X, Filter, Plus, Video, ExternalLink, Sparkles } from 'lucide-react'
import { cn } from '@/lib/utils'
import api from '@/lib/api'
import useAuthStore from '@/store/authStore'
import { hasPermission } from '@/lib/permissions'
import CitaActionSheet from '@/components/agenda/CitaActionSheet'
import NuevaCitaModal from '@/components/agenda/NuevaCitaModal'

const DIAS = ['Lun', 'Mar', 'Mié', 'Jue', 'Vie', 'Sáb', 'Dom']
const MESES = [
    'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre',
]

// Color por tipo de contacto / tipo de cita
const TIPO_COLOR_MAP = {
    'cita oficina bustamante': { bg: 'bg-indigo-500', text: 'text-white', light: 'bg-indigo-50 text-indigo-700 border-indigo-200' },
    'cita oficina umacollo': { bg: 'bg-purple-500', text: 'text-white', light: 'bg-purple-50 text-purple-700 border-purple-200' },
    'cita exteriores': { bg: 'bg-emerald-500', text: 'text-white', light: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
    'cita virtual': { bg: 'bg-sky-500', text: 'text-white', light: 'bg-sky-50 text-sky-700 border-sky-200' },
    // Fallbacks para tipos clasicos
    'llamada': { bg: 'bg-indigo-500', text: 'text-white', light: 'bg-indigo-50 text-indigo-700 border-indigo-200' },
    'video llamada': { bg: 'bg-sky-500', text: 'text-white', light: 'bg-sky-50 text-sky-700 border-sky-200' },
    'presencial': { bg: 'bg-emerald-500', text: 'text-white', light: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
    'whatsapp': { bg: 'bg-emerald-600', text: 'text-white', light: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
    'email': { bg: 'bg-amber-500', text: 'text-white', light: 'bg-amber-50 text-amber-700 border-amber-200' },
}

const PALETTE = [
    { bg: 'bg-indigo-500', text: 'text-white', light: 'bg-indigo-50 text-indigo-700 border-indigo-200' },
    { bg: 'bg-purple-500', text: 'text-white', light: 'bg-purple-50 text-purple-700 border-purple-200' },
    { bg: 'bg-emerald-500', text: 'text-white', light: 'bg-emerald-50 text-emerald-700 border-emerald-200' },
    { bg: 'bg-sky-500', text: 'text-white', light: 'bg-sky-50 text-sky-700 border-sky-200' },
    { bg: 'bg-amber-500', text: 'text-white', light: 'bg-amber-50 text-amber-700 border-amber-200' },
    { bg: 'bg-pink-500', text: 'text-white', light: 'bg-pink-50 text-pink-700 border-pink-200' },
]

function getColor(tipo) {
    const norm = (tipo || '').toLowerCase().trim()
    if (TIPO_COLOR_MAP[norm]) return TIPO_COLOR_MAP[norm]
    if (norm.includes('bustamante')) return TIPO_COLOR_MAP['cita oficina bustamante']
    if (norm.includes('umacollo')) return TIPO_COLOR_MAP['cita oficina umacollo']
    if (norm.includes('exterior')) return TIPO_COLOR_MAP['cita exteriores']
    if (norm.includes('virtual')) return TIPO_COLOR_MAP['cita virtual']
    let hash = 0
    for (let i = 0; i < norm.length; i++) hash += norm.charCodeAt(i)
    return PALETTE[hash % PALETTE.length]
}

/** Formatea "2026-04-06T12:23:00" a "12:23" (24h, sin am/pm). */
function formatHora(iso) {
    if (!iso) return null
    try {
        const m = String(iso).match(/\d{4}-\d{2}-\d{2}[ T](\d{2}):(\d{2})/)
        if (m) return `${m[1]}:${m[2]}`
        return new Date(iso).toLocaleTimeString('es-PE', {
            timeZone: 'America/Lima',
            hour: '2-digit', minute: '2-digit', hour12: false,
        })
    } catch { return null }
}

/** Devuelve la fecha actual en zona horaria Lima como { year, month, day, iso } */
function getLimaToday() {
    const parts = new Intl.DateTimeFormat('en-CA', {
        timeZone: 'America/Lima',
        year: 'numeric', month: '2-digit', day: '2-digit',
    }).formatToParts(new Date())
    const map = Object.fromEntries(
        parts.filter(p => p.type !== 'literal').map(p => [p.type, p.value])
    )
    return {
        year: Number(map.year),
        month: Number(map.month),
        day: Number(map.day),
        iso: `${map.year}-${map.month}-${map.day}`,
    }
}

/** Genera array de celdas del calendario para el mes (con padding de días previos/posteriores) */
function buildCalendarDays(year, month) {
    const firstDay = new Date(year, month - 1, 1)
    // Lunes=0 … Domingo=6
    let startDow = firstDay.getDay() - 1  // getDay: 0=domingo
    if (startDow < 0) startDow = 6

    const daysInMonth = new Date(year, month, 0).getDate()
    const prevDays = new Date(year, month - 1, 0).getDate()

    const cells = []
    // Días del mes anterior (padding)
    for (let i = startDow - 1; i >= 0; i--) {
        cells.push({ day: prevDays - i, current: false, key: `prev-${i}` })
    }
    // Días del mes actual
    for (let d = 1; d <= daysInMonth; d++) {
        const iso = `${year}-${String(month).padStart(2, '0')}-${String(d).padStart(2, '0')}`
        cells.push({ day: d, current: true, key: iso, iso })
    }
    // Días del mes siguiente (padding hasta completar última fila)
    let next = 1
    while (cells.length % 7 !== 0) {
        cells.push({ day: next++, current: false, key: `next-${next}` })
    }
    return cells
}

// V096.2.3 — Helper para identificar citas canceladas. Se usa para
// aplicar opacity reducida y strikethrough (las canceladas siguen
// visibles para audit pero no compiten visualmente con las activas).
function isCanceladaCita(cita) {
    return String(cita?.cita_estado_codigo || '').toLowerCase() === 'cancelada'
}

function getAgendaItemKind(item) {
    if (item?.item_kind === 'seguimiento' || item?.item_kind === 'oportunidad_futura') {
        return item.item_kind
    }
    const tc = String(item?.tipo_contacto || '').toLowerCase()
    if (tc === 'seguimiento') return 'seguimiento'
    if (tc === 'oportunidad_futura') return 'oportunidad_futura'
    return 'cita'
}

/** Pill compacto de cita/seguimiento/oportunidad en el calendario. */
function CitaPill({ cita, onOpen }) {
    const kind = getAgendaItemKind(cita)
    const isSeg = kind === 'seguimiento'
    const isOpor = kind === 'oportunidad_futura'
    const isLeadItem = isSeg || isOpor
    const hora = formatHora(cita.fecha_evento)
    const estadoColor = isSeg
        ? '#2563EB'
        : isOpor
            ? '#7C3AED'
            : (cita.cita_estado_color || '#3B82F6')
    const estadoNombre = isSeg
        ? 'Seguimiento'
        : isOpor
            ? 'Oport. futura'
            : (cita.cita_estado_nombre || 'Pendiente')
    const shortTag = isSeg ? 'Seg' : isOpor ? 'Opor' : estadoNombre.slice(0, 4)
    const cancelada = !isLeadItem && isCanceladaCita(cita)
    const isHighPotential = !isLeadItem && /potencial|cierre|interes/i.test(cita.notas || '')

    return (
        <button
            type="button"
            onClick={(e) => { e.stopPropagation(); onOpen?.(cita) }}
            className={cn(
                'group block w-full text-left rounded-md px-1.5 py-1 text-[10px] font-medium transition-all shadow-2xs border-l-[3px]',
                'cursor-pointer hover:brightness-95 hover:shadow-xs focus-visible:outline-none focus-visible:ring-1',
                cancelada
                    ? 'opacity-60 line-through bg-gray-100 dark:bg-gray-800/60 border-gray-400 text-gray-500'
                    : isSeg
                        ? 'bg-blue-50/70 dark:bg-blue-950/30 text-gray-800 dark:text-slate-100 hover:bg-blue-50'
                        : isOpor
                            ? 'bg-purple-50/70 dark:bg-purple-950/30 text-gray-800 dark:text-slate-100 hover:bg-purple-50'
                            : 'bg-white dark:bg-slate-800/90 text-gray-800 dark:text-slate-100 hover:bg-gray-50 dark:hover:bg-slate-800'
            )}
            style={{
                borderLeftColor: estadoColor,
                borderTop: '1px solid rgba(0,0,0,0.06)',
                borderRight: '1px solid rgba(0,0,0,0.06)',
                borderBottom: '1px solid rgba(0,0,0,0.06)',
            }}
            title={`${estadoNombre} · ${hora || ''} · ${cita.lead_nombre || cita.lead_telefono || ''}${cita.notas ? ' · ' + cita.notas : ''}`}
        >
            <div className="flex items-center justify-between gap-1">
                <div className="flex items-center gap-1 min-w-0">
                    <span
                        className="inline-block w-1.5 h-1.5 rounded-full shrink-0"
                        style={{ backgroundColor: estadoColor }}
                    />
                    {hora && <span className="font-semibold tabular-nums shrink-0 text-gray-700 dark:text-gray-300">{hora}</span>}
                    {isHighPotential && <span className="text-[10px] shrink-0" title="Alto potencial de cierre">⭐</span>}
                    <span className="truncate font-medium">{cita.lead_nombre || cita.lead_telefono || '—'}</span>
                </div>
                <span
                    className="text-[8px] font-bold px-1 py-0.2 rounded shrink-0 uppercase tracking-tight"
                    style={{
                        backgroundColor: estadoColor + '20',
                        color: estadoColor,
                    }}
                >
                    {shortTag}
                </span>
            </div>
            {cita.asesor_nombre?.trim() && (
                <div className="text-[9px] text-gray-400 dark:text-gray-500 truncate mt-0.5">
                    {cita.asesor_nombre}
                </div>
            )}
        </button>
    )
}

/** Panel lateral de detalle del día seleccionado */
function DayPanel({ date, citas, onClose, onOpenCita }) {
    if (!date) return null
    const [y, m, d] = date.split('-').map(Number)
    const label = `${d} de ${MESES[m - 1]} ${y}`

    return (
        <div className="w-80 shrink-0 bg-white border border-gray-200 rounded-2xl shadow-sm flex flex-col overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-gray-100">
                <div className="flex items-center gap-2">
                    <Calendar size={15} className="text-indigo-500" />
                    <span className="text-sm font-semibold text-gray-800">{label}</span>
                </div>
                <button onClick={onClose} className="p-1 rounded hover:bg-gray-100 text-gray-400 hover:text-gray-600">
                    <X size={14} />
                </button>
            </div>

            {/* Lista de citas. Si la cita tiene lead_id, la card es un Link al
          detalle del lead — Ctrl+Click / right-click "Abrir en nueva
          pestaña" funcionan nativos. Sin lead_id se renderiza como div
          estatico. */}
            <div className="flex-1 overflow-y-auto p-3 space-y-2">
                {citas.length === 0 ? (
                    <p className="text-sm text-gray-400 text-center py-6">Sin citas este día</p>
                ) : (
                    citas.map(c => {
                        const kind = getAgendaItemKind(c)
                        const isSeg = kind === 'seguimiento'
                        const isOpor = kind === 'oportunidad_futura'
                        const tipo = c.tipo_cita || c.tipo_contacto
                        const light = isSeg
                            ? 'bg-blue-50 text-blue-800 border-blue-200'
                            : isOpor
                                ? 'bg-purple-50 text-purple-800 border-purple-200'
                                : getColor(tipo).light
                        const hora = formatHora(c.fecha_evento)

                        const cardBody = (
                            <>
                                {/* Tipo + hora */}
                                <div className="flex items-center justify-between gap-2 pr-5">
                                    <span className="inline-flex items-center gap-1 text-xs font-semibold capitalize">
                                        {isSeg && <Clock size={11} className="text-blue-600" />}
                                        {isOpor && <Sparkles size={11} className="text-purple-600" />}
                                        {isSeg ? 'Seguimiento' : isOpor ? 'Oportunidad futura' : tipo}
                                    </span>
                                    {hora && (
                                        <span className="flex items-center gap-1 text-xs font-mono opacity-70">
                                            <Clock size={10} />{hora}
                                        </span>
                                    )}
                                </div>

                                {/* V070.65 — Estado de la cita (Pendiente/Completada/etc).
                    Paridad con mobile AgendaScreen.js. */}
                                {c.cita_estado_nombre && (
                                    <span
                                        className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded-full text-[10px] font-semibold border"
                                        style={{
                                            backgroundColor: (c.cita_estado_color || '#3B82F6') + '20',
                                            borderColor: (c.cita_estado_color || '#3B82F6') + '60',
                                            color: c.cita_estado_color || '#3B82F6',
                                        }}
                                    >
                                        <span
                                            className="inline-block w-1.5 h-1.5 rounded-full"
                                            style={{ backgroundColor: c.cita_estado_color || '#3B82F6' }}
                                        />
                                        {c.cita_estado_nombre}
                                    </span>
                                )}

                                {/* Lead */}
                                <div className="flex items-center gap-1.5">
                                    <User size={11} className="shrink-0 opacity-60" />
                                    <span className="text-xs font-medium truncate">
                                        {c.lead_nombre?.trim() || '—'}
                                    </span>
                                </div>

                                {/* Teléfono */}
                                {c.lead_telefono && (
                                    <div className="flex items-center gap-1.5">
                                        <Phone size={11} className="shrink-0 opacity-60" />
                                        <span className="text-xs font-mono opacity-80">{c.lead_telefono}</span>
                                    </div>
                                )}

                                {/* Asesor */}
                                {c.asesor_nombre?.trim() && (
                                    <p className="text-xs opacity-60">Asesor: {c.asesor_nombre}</p>
                                )}

                                {/* URL de reunión virtual */}
                                {c.url_reunion && (
                                    <div className="pt-1">
                                        <a
                                            href={c.url_reunion.startsWith('http://') || c.url_reunion.startsWith('https://') ? c.url_reunion : `https://${c.url_reunion}`}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            onClick={(e) => e.stopPropagation()}
                                            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-white/90 hover:bg-white dark:bg-slate-800/90 dark:hover:bg-slate-700 border border-current/20 text-xs font-semibold shadow-2xs hover:shadow-xs transition-all"
                                            title="Unirse a la reunión virtual"
                                        >
                                            <Video size={12} className="text-sky-600 dark:text-sky-400 shrink-0" />
                                            <span className="truncate max-w-[170px]">Unirse a reunión</span>
                                            <ExternalLink size={10} className="opacity-60 shrink-0" />
                                        </a>
                                    </div>
                                )}

                                {/* Observaciones / Notas */}
                                {c.notas && (
                                    <div className={cn(
                                        "text-xs rounded-lg p-2.5 mt-1.5 border leading-relaxed",
                                        /potencial|cierre|interes/i.test(c.notas)
                                            ? "bg-amber-50 text-amber-950 border-amber-200 dark:bg-amber-950/40 dark:text-amber-200 dark:border-amber-800/60 font-medium"
                                            : "bg-white/80 dark:bg-slate-800/60 text-gray-700 dark:text-slate-300 border-gray-200 dark:border-slate-700"
                                    )}>
                                        <div className="flex items-center gap-1 text-[11px] font-bold text-gray-500 dark:text-gray-400 mb-0.5">
                                            {/potencial|cierre/i.test(c.notas) && <span>⭐</span>}
                                            <span>Observación:</span>
                                        </div>
                                        <div>{c.notas}</div>
                                    </div>
                                )}

                                {/* Próxima acción */}
                                {c.proxima_accion && (
                                    <p className="text-xs opacity-70 line-clamp-2 border-t border-current/20 pt-1.5 mt-1">
                                        Próxima acción: {c.proxima_accion}
                                    </p>
                                )}
                            </>
                        )

                        // V096 — Card clickable abre the ActionSheet (no link directo)
                        // V096.2.3 — Canceladas con opacity 60% para no competir
                        // visualmente con las activas.
                        const cancelada = isCanceladaCita(c)
                        return (
                            <button
                                key={c.id}
                                type="button"
                                onClick={() => onOpenCita?.(c)}
                                className={cn(
                                    'group relative w-full text-left border rounded-xl p-3 space-y-1.5 transition-all duration-150',
                                    'cursor-pointer hover:shadow-md hover:-translate-y-0.5',
                                    'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-indigo-500 focus-visible:ring-offset-1',
                                    light,
                                    cancelada && 'opacity-60',
                                )}
                                title={`Abrir acciones rápidas: ${c.lead_nombre || c.lead_telefono || ''}`}
                            >
                                {cardBody}
                                <ChevronRight
                                    size={16}
                                    className="absolute right-2 top-1/2 -translate-y-1/2 opacity-0 group-hover:opacity-60 transition-opacity duration-150"
                                />
                            </button>
                        )
                    })
                )}
            </div>
        </div>
    )
}

export default function Agenda() {
    const { user } = useAuthStore()
    const today = getLimaToday()
    const [year, setYear] = useState(today.year)
    const [month, setMonth] = useState(today.month)
    const [citas, setCitas] = useState([])
    const [isLoading, setIsLoading] = useState(false)
    const [apiError, setApiError] = useState(null)
    const [selectedDay, setSelectedDay] = useState(null)
    const [filterSupervisor, setFilterSupervisor] = useState('')
    const [filterAsesor, setFilterAsesor] = useState('')
    const [filterEstado, setFilterEstado] = useState('')
    const [filterTipoAgenda, setFilterTipoAgenda] = useState('todos')
    const [supervisoresList, setSupervisoresList] = useState([])
    // V096 — ActionSheet state. Cita actualmente abierta + catalogos para
    // los pickers de estado de cita y estado del lead.
    const [activeCita, setActiveCita] = useState(null)
    const [citaEstados, setCitaEstados] = useState([])
    const [leadEstados, setLeadEstados] = useState([])
    // V096.2.1 — Modal "Nueva cita" desde el header de Agenda (paridad mobile).
    const [showNuevaCita, setShowNuevaCita] = useState(false)
    const [tiposCita, setTiposCita] = useState([])
    const [tiposContacto, setTiposContacto] = useState([])
    const [resultadosContacto, setResultadosContacto] = useState([])

    const mes = `${year}-${String(month).padStart(2, '0')}`

    // V096 — cargar catalogos una vez. citaEstados/leadEstados/tipos son
    // invariantes, no recargar en cada cambio de mes.
    useEffect(() => {
        api.get('/api/cita-estados').then(res => setCitaEstados(res.data || [])).catch(() => { })
        api.get('/api/estados').then(res => setLeadEstados(res.data || [])).catch(() => { })
        // V099 — tipos de cita independientes de tipos de contacto.
        api.get('/api/tipos-cita').then(res => setTiposCita(res.data || [])).catch(() => { })
        api.get('/api/tipos-contacto').then(res => setTiposContacto(res.data || [])).catch(() => { })
        api.get('/api/resultados-contacto').then(res => setResultadosContacto(res.data || [])).catch(() => { })
        // Cargar supervisores para el filtro
        api.get('/auth/users')
            .then(res => {
                const users = res.data || []
                const sups = users.filter(u => (u.role === 'supervisor' || u.role === 'admin') && u.is_active !== false)
                setSupervisoresList(sups)
            })
            .catch(() => { })
    }, [])

    // Refresh silencioso (sin spinner — para polling y eventos sin parpadeo).
    // El primer fetch del mes si usa spinner.
    const fetchedRef = useRef(false)
    const fetchCitas = useCallback((silent = false) => {
        if (!silent) setIsLoading(true)
        setApiError(null)
        const supParam = filterSupervisor ? `&supervisor_id=${encodeURIComponent(filterSupervisor)}` : ''
        api.get(`/api/agenda/citas?mes=${mes}${supParam}`)
            .then(res => {
                setCitas(res.data?.citas || [])
            })
            .catch(err => {
                const msg = err.response?.data?.detail || err.message || 'Error desconocido'
                if (!silent) setApiError(`Error cargando citas: ${msg} (status ${err.response?.status || '?'})`)
                if (!silent) setCitas([])
            })
            .finally(() => {
                if (!silent) setIsLoading(false)
                fetchedRef.current = true
            })
    }, [mes, filterSupervisor])

    useEffect(() => { fetchCitas() }, [fetchCitas])

    // V096.6 — Polling 20s + refresh al volver la pestana a primer plano.
    // Patron mobile AgendaScreen: la agenda siempre debe estar fresca cuando
    // el asesor la mira (otro miembro del equipo pudo haber agendado).
    useEffect(() => {
        if (!fetchedRef.current) return undefined
        const id = setInterval(() => fetchCitas(true), 20_000)
        const onVisible = () => {
            if (document.visibilityState === 'visible') fetchCitas(true)
        }
        document.addEventListener('visibilitychange', onVisible)
        return () => {
            clearInterval(id)
            document.removeEventListener('visibilitychange', onVisible)
        }
    }, [fetchCitas])

    // Al cambiar de mes, limpiar selección si el día no existe en el nuevo mes
    useEffect(() => { setSelectedDay(null) }, [mes])

    const prevMonth = () => {
        if (month === 1) { setYear(y => y - 1); setMonth(12) }
        else setMonth(m => m - 1)
    }
    const nextMonth = () => {
        if (month === 12) { setYear(y => y + 1); setMonth(1) }
        else setMonth(m => m + 1)
    }

    // Lista consolidada de supervisores (de /auth/users + citas)
    const allSupervisores = useMemo(() => {
        const map = new Map()
        supervisoresList.forEach(s => {
            const nombre = [s.first_name, s.last_name].filter(Boolean).join(' ') || s.email
            map.set(s.id, nombre)
        })
        citas.forEach(c => {
            if (c.supervisor_id && c.supervisor_nombre?.trim()) {
                if (!map.has(c.supervisor_id)) {
                    map.set(c.supervisor_id, c.supervisor_nombre.trim())
                }
            }
        })
        return [...map.entries()].sort((a, b) => a[1].localeCompare(b[1]))
    }, [supervisoresList, citas])

    // Lista de asesores filtrada según el supervisor seleccionado
    const asesores = useMemo(() => {
        const list = citas.filter(c => {
            if (!c.asesor_id || !c.asesor_nombre?.trim()) return false
            if (filterSupervisor && c.supervisor_id && c.supervisor_id !== filterSupervisor) return false
            return true
        })
        return [...new Map(list.map(c => [c.asesor_id, c.asesor_nombre.trim()])).entries()]
            .sort((a, b) => a[1].localeCompare(b[1]))
    }, [citas, filterSupervisor])

    // Filtrar eventos por tipo (citas/seguimientos/oportunidad), supervisor, asesor y estado
    const filteredCitas = useMemo(() => {
        return citas.filter(c => {
            const kind = getAgendaItemKind(c)
            if (filterTipoAgenda !== 'todos' && kind !== filterTipoAgenda) return false
            if (filterSupervisor && c.supervisor_id && c.supervisor_id !== filterSupervisor) return false
            if (filterAsesor && c.asesor_id !== filterAsesor) return false
            if (filterEstado) {
                if (kind !== 'cita') return false
                const cod = String(c.cita_estado_codigo || '').toLowerCase()
                if (cod !== filterEstado.toLowerCase()) return false
            }
            return true
        })
    }, [citas, filterTipoAgenda, filterSupervisor, filterAsesor, filterEstado])

    // Agrupar citas por fecha_dia
    const citasByDay = {}
    filteredCitas.forEach(c => {
        if (!c.fecha_dia) return
        if (!citasByDay[c.fecha_dia]) citasByDay[c.fecha_dia] = []
        citasByDay[c.fecha_dia].push(c)
    })

    const cells = buildCalendarDays(year, month)
    const todayIso = today.iso
    const selectedCitas = selectedDay ? (citasByDay[selectedDay] || []) : []

    return (
        <div className="space-y-4">
            {/* Encabezado */}
            <div className="flex items-center justify-between flex-wrap gap-3">
                <div>
                    <h1 className="text-2xl font-bold text-gray-900">Agenda</h1>
                    {/* V096.2.3 — Conteo separa activas vs canceladas para que el
              numero no enganhe (5 citas no es lo mismo si 3 estan canceladas). */}
                    {(() => {
                        const citasOnly = filteredCitas.filter(c => getAgendaItemKind(c) === 'cita')
                        const segCount = filteredCitas.filter(c => getAgendaItemKind(c) === 'seguimiento').length
                        const oporCount = filteredCitas.filter(c => getAgendaItemKind(c) === 'oportunidad_futura').length
                        const canceladas = citasOnly.filter(isCanceladaCita).length
                        const activas = citasOnly.length - canceladas
                        return (
                            <p className="text-sm text-gray-500 mt-0.5">
                                {isLoading
                                    ? 'Cargando…'
                                    : (
                                        <>
                                            {`${activas} cita${activas !== 1 ? 's' : ''}`}
                                            {segCount > 0 && ` · ${segCount} seguimiento${segCount !== 1 ? 's' : ''}`}
                                            {oporCount > 0 && ` · ${oporCount} oport. futura${oporCount !== 1 ? 's' : ''}`}
                                            {` en ${MESES[month - 1]} ${year}`}
                                            {canceladas > 0 && (
                                                <span className="text-gray-400 ml-1">
                                                    ({canceladas} cancelada{canceladas !== 1 ? 's' : ''})
                                                </span>
                                            )}
                                        </>
                                    )}
                            </p>
                        )
                    })()}
                </div>
                {/* Filtros + Navegación de mes + Nueva cita */}
                <div className="flex items-center gap-2 flex-wrap">
                    {/* V096.2.1 — Paridad mobile: boton "+ Nueva cita" en el header. */}
                    {hasPermission(user, 'agenda.edit') && (
                        <button
                            onClick={() => setShowNuevaCita(true)}
                            className="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg bg-emerald-600 text-white hover:bg-emerald-700 transition-colors mr-1"
                            title="Crear una nueva cita"
                        >
                            <Plus size={14} />
                            Nueva cita
                        </button>
                    )}

                    {/* Filtro por tipo de evento (Todos / Citas / Seguimientos / Oport. futura) */}
                    <div className="inline-flex rounded-lg border border-gray-200 bg-gray-50 p-0.5 text-xs">
                        {[
                            { id: 'todos', label: 'Todos' },
                            { id: 'cita', label: 'Citas' },
                            { id: 'seguimiento', label: 'Seguimientos' },
                            { id: 'oportunidad_futura', label: 'Oport. futura' },
                        ].map(tab => (
                            <button
                                key={tab.id}
                                type="button"
                                onClick={() => setFilterTipoAgenda(tab.id)}
                                className={cn(
                                    'px-2.5 py-1 rounded-md font-medium transition-colors cursor-pointer',
                                    filterTipoAgenda === tab.id
                                        ? 'bg-white text-indigo-600 shadow-2xs font-semibold'
                                        : 'text-gray-600 hover:text-gray-900'
                                )}
                            >
                                {tab.label}
                            </button>
                        ))}
                    </div>

                    {/* Filtro por Supervisor */}
                    {allSupervisores.length > 0 && (
                        <div className="flex items-center gap-1">
                            <Filter size={13} className="text-gray-400 shrink-0" />
                            <select
                                value={filterSupervisor}
                                onChange={(e) => {
                                    setFilterSupervisor(e.target.value)
                                    setFilterAsesor('')
                                }}
                                className="h-8 rounded-lg border border-gray-200 bg-white px-2 pr-6 text-xs text-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 font-medium"
                                title="Filtrar citas por Supervisor"
                            >
                                <option value="">Todos los supervisores</option>
                                {allSupervisores.map(([id, nombre]) => (
                                    <option key={id} value={id}>{nombre}</option>
                                ))}
                            </select>
                        </div>
                    )}

                    {/* Filtro por Asesor */}
                    {asesores.length > 0 && (
                        <div className="flex items-center gap-1">
                            <select
                                value={filterAsesor}
                                onChange={(e) => setFilterAsesor(e.target.value)}
                                className="h-8 rounded-lg border border-gray-200 bg-white px-2 pr-6 text-xs text-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                                title="Filtrar por asesor"
                            >
                                <option value="">Todos los asesores</option>
                                {asesores.map(([id, nombre]) => (
                                    <option key={id} value={id}>{nombre}</option>
                                ))}
                            </select>
                        </div>
                    )}

                    {/* Filtro por Estado de Cita */}
                    <div className="flex items-center gap-1">
                        <select
                            value={filterEstado}
                            onChange={(e) => setFilterEstado(e.target.value)}
                            className="h-8 rounded-lg border border-gray-200 bg-white px-2 pr-6 text-xs text-gray-700 focus:outline-none focus:ring-2 focus:ring-indigo-500 font-medium"
                            title="Filtrar por estado de cita"
                        >
                            <option value="">Todos los estados</option>
                            {(citaEstados.length > 0
                                ? citaEstados
                                : [
                                    { codigo: 'pendiente', nombre: 'Pendiente' },
                                    { codigo: 'completada', nombre: 'Completada' },
                                    { codigo: 'reprogramada', nombre: 'Reprogramada' },
                                    { codigo: 'no_asistio', nombre: 'No asistió' },
                                    { codigo: 'cancelada', nombre: 'Cancelada' },
                                ]
                            ).map(est => (
                                <option key={est.codigo || est.id} value={est.codigo}>
                                    {est.nombre}
                                </option>
                            ))}
                        </select>
                    </div>

                    <div className="flex items-center gap-1 ml-1">
                        <button
                            onClick={prevMonth}
                            className="w-8 h-8 flex items-center justify-center rounded-full border border-gray-200 hover:bg-gray-100 text-gray-500 transition-colors"
                        >
                            <ChevronLeft size={16} />
                        </button>
                        <span className="text-sm font-semibold text-gray-800 min-w-[130px] text-center">
                            {MESES[month - 1]} {year}
                        </span>
                        <button
                            onClick={nextMonth}
                            className="w-8 h-8 flex items-center justify-center rounded-full border border-gray-200 hover:bg-gray-100 text-gray-500 transition-colors"
                        >
                            <ChevronRight size={16} />
                        </button>
                        <button
                            onClick={() => { const t = getLimaToday(); setYear(t.year); setMonth(t.month) }}
                            className="ml-1 text-xs font-medium px-2.5 py-1.5 border border-gray-200 rounded-lg hover:bg-gray-50 text-gray-600 transition-colors"
                        >
                            Hoy
                        </button>
                    </div>
                </div>
            </div>

            {/* Error de API */}
            {apiError && (
                <div className="bg-red-50 border border-red-200 text-red-700 text-sm rounded-xl px-4 py-3 font-mono">
                    {apiError}
                </div>
            )}

            {/* Cuerpo: calendario + panel */}
            <div className="flex gap-4 items-start">
                {/* Calendario */}
                <div className="flex-1 bg-white border border-gray-200 rounded-2xl shadow-sm overflow-hidden">
                    {/* Cabecera días */}
                    <div className="grid grid-cols-7 border-b border-gray-100">
                        {DIAS.map(d => (
                            <div key={d} className="py-2.5 text-center text-xs font-semibold text-gray-400 uppercase tracking-wide">
                                {d}
                            </div>
                        ))}
                    </div>

                    {/* Grid de días */}
                    {isLoading ? (
                        <div className="py-20 text-center text-sm text-gray-400">Cargando citas…</div>
                    ) : (
                        <div className="grid grid-cols-7 divide-x divide-gray-100">
                            {cells.map((cell, idx) => {
                                const isToday = cell.current && cell.iso === todayIso
                                const isSelected = cell.current && cell.iso === selectedDay
                                const dayCitas = cell.iso ? (citasByDay[cell.iso] || []) : []
                                const extras = dayCitas.length > 2 ? dayCitas.length - 2 : 0

                                return (
                                    <div
                                        key={cell.key}
                                        onClick={() => cell.current && setSelectedDay(isSelected ? null : cell.iso)}
                                        className={cn(
                                            'min-h-[90px] p-1.5 flex flex-col gap-1 border-b border-gray-100',
                                            idx % 7 !== 0 && 'border-l-0',
                                            cell.current ? 'cursor-pointer hover:bg-gray-50' : 'bg-gray-50/50 cursor-default',
                                            isSelected && 'bg-indigo-50 hover:bg-indigo-50',
                                        )}
                                    >
                                        {/* Número del día */}
                                        <div className="flex items-center justify-between">
                                            <span
                                                className={cn(
                                                    'w-6 h-6 flex items-center justify-center rounded-full text-xs font-semibold',
                                                    isToday ? 'bg-[var(--brand-primary)] text-white' : '',
                                                    !isToday && cell.current ? 'text-gray-700' : 'text-gray-300',
                                                    isSelected && !isToday ? 'text-indigo-700' : '',
                                                )}
                                            >
                                                {cell.day}
                                            </span>
                                            {dayCitas.length > 0 && (
                                                <span className="text-[9px] font-bold text-indigo-500 bg-indigo-50 px-1 rounded-full">
                                                    {dayCitas.length}
                                                </span>
                                            )}
                                        </div>

                                        {/* Pills de citas */}
                                        <div className="space-y-0.5 flex-1">
                                            {dayCitas.slice(0, 2).map(c => (
                                                <CitaPill key={c.id} cita={c} onOpen={setActiveCita} />
                                            ))}
                                            {extras > 0 && (
                                                // Texto plano sin handler propio — el click sube al
                                                // div padre y abre el side panel del dia (ahi se ven
                                                // todas las citas y se puede navegar a cada lead).
                                                <div className="text-[10px] text-gray-400 font-medium pl-1 hover:text-indigo-600 hover:underline transition-colors">
                                                    +{extras} más
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                )
                            })}
                        </div>
                    )}
                </div>

                {/* Panel lateral */}
                {selectedDay && (
                    <DayPanel
                        date={selectedDay}
                        citas={selectedCitas}
                        onClose={() => setSelectedDay(null)}
                        onOpenCita={setActiveCita}
                    />
                )}
            </div>

            {/* V096 — ActionSheet de la cita activa. Cierre via onClose + refresh
          silencioso tras cualquier update para refrescar pills + DayPanel. */}
            {activeCita && (
                <CitaActionSheet
                    cita={activeCita}
                    citaEstados={citaEstados}
                    leadEstados={leadEstados}
                    onClose={() => setActiveCita(null)}
                    onUpdated={(citaActualizada) => {
                        // Optimistic update local + refresh silent en background.
                        setCitas(prev => prev.map(c => c.id === citaActualizada.id ? { ...c, ...citaActualizada } : c))
                        fetchCitas(true)
                    }}
                    onLeadEstadoChanged={() => fetchCitas(true)}
                />
            )}

            {/* V096.2.1 — Modal Nueva cita (paridad mobile NuevaCitaScreen).
          Tras crear, refresh silent del mes actual para ver la cita nueva. */}
            {showNuevaCita && (
                <NuevaCitaModal
                    tiposCita={tiposCita}
                    tiposContacto={tiposContacto}
                    resultadosContacto={resultadosContacto}
                    onClose={() => setShowNuevaCita(false)}
                    onCreated={() => fetchCitas(true)}
                />
            )}

            {/* Leyenda */}
            <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 pt-3 border-t border-gray-100 flex-wrap">
                {/* Estados con colores */}
                <div className="flex items-center gap-3 flex-wrap">
                    <span className="text-xs text-gray-500 font-semibold">Estados:</span>
                    {(citaEstados.length > 0
                        ? citaEstados
                        : [
                            { nombre: 'Pendiente', color_hex: '#3B82F6' },
                            { nombre: 'Completada', color_hex: '#10B981' },
                            { nombre: 'Reprogramada', color_hex: '#F59E0B' },
                            { nombre: 'No asistió', color_hex: '#EF4444' },
                            { nombre: 'Cancelada', color_hex: '#6B7280' },
                        ]
                    ).map(e => (
                        <div key={e.id || e.nombre} className="flex items-center gap-1.5">
                            <span
                                className="w-2.5 h-2.5 rounded-full shrink-0 shadow-2xs"
                                style={{ backgroundColor: e.color_hex }}
                            />
                            <span className="text-xs text-gray-600 font-medium">{e.nombre}</span>
                        </div>
                    ))}
                    <div className="flex items-center gap-1 text-xs text-amber-700 bg-amber-50 px-2 py-0.5 rounded border border-amber-200 ml-1">
                        <span>⭐</span>
                        <span className="font-medium">Alto potencial</span>
                    </div>
                </div>

                {/* Tipos */}
                <div className="flex items-center gap-3 flex-wrap">
                    <span className="text-xs text-gray-500 font-semibold">Tipos:</span>
                    {(tiposCita.length > 0
                        ? tiposCita
                        : [
                            { nombre: 'Cita oficina Bustamante' },
                            { nombre: 'Cita oficina Umacollo' },
                            { nombre: 'Cita Exteriores' },
                            { nombre: 'Cita Virtual' },
                        ]
                    ).map(t => {
                        const color = getColor(t.nombre)
                        return (
                            <div key={t.id || t.nombre} className="flex items-center gap-1.5">
                                <div className={cn('w-2.5 h-2.5 rounded-full shrink-0', color.bg)} />
                                <span className="text-xs text-gray-600 font-medium">{t.nombre}</span>
                            </div>
                        )
                    })}
                </div>
            </div>
        </div>
    )
}
