import { useState, useRef, useEffect, useCallback } from 'react'
import {
  Upload, FileSpreadsheet, AlertCircle, CheckCircle,
  X, DownloadCloud, AlertTriangle, Info, History, Trash2,
  RefreshCw, Copy, XCircle, FileDown,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import ErrorBoundary from '@/components/shared/ErrorBoundary'
import ConfirmDialog from '@/components/shared/ConfirmDialog'
import ModalDetalleCarga from '@/components/admin/ModalDetalleCarga'
import api from '@/lib/api'

/* ── constantes ─────────────────────────────────────────────────────────── */

// Columnas que puede traer un archivo de carga masiva. El orden define el
// orden visual en el mapeo. Alineado con la plantilla operativa de gerencia
// (FECHA, NOMBRE, CELULAR, CORREO, CIUDAD, PROYECTO, ESTRATEGIA, ESTADO,
// COMENTARIOS) + campos legacy (DNI, Campaña, Fuente) marcados como opcionales
// para mantener compatibilidad con plantillas antiguas.
// V060: Convencion unificada — campana (engloba proyecto) y fuente
// (engloba estrategia/canal). Las columnas viejas siguen siendo
// reconocidas por retrocompatibilidad y se mapean automaticamente:
//   - 'proyecto' (legacy) -> campana si campana viene vacia
//   - 'estrategia' (legacy) -> fuente si fuente viene vacia
const EXPECTED_COLUMNS = [
  { key: 'fecha',         label: 'Fecha',           required: false },
  { key: 'nombres',       label: 'Nombres',         required: false },
  { key: 'apellidos',     label: 'Apellidos',       required: false },
  { key: 'telefono',      label: 'Teléfono',        required: true  },
  { key: 'email',         label: 'Email',           required: false },
  { key: 'dni',           label: 'DNI',             required: false },
  { key: 'ciudad',        label: 'Ciudad',          required: false },
  { key: 'campana',       label: 'Campaña',         required: false },
  { key: 'fuente',        label: 'Fuente',          required: true  },
  { key: 'codigo_convenio', label: 'Código Convenio', required: false },
  { key: 'calidad',       label: 'Calidad',         required: false },
  { key: 'sede',          label: 'Sede',            required: false },  // V065
  { key: 'asesor',        label: 'Asesor',          required: false },
  { key: 'observaciones', label: 'Observaciones',   required: false },
  // Legacy retrocompat — se aceptan pero el backend los unifica con
  // campana/fuente. NO aparecen en la plantilla nueva.
  { key: 'proyecto',      label: 'Proyecto (legacy)',   required: false },
  { key: 'estrategia',    label: 'Estrategia (legacy)', required: false },
]

const POOL_VALUE = 'pool'   // literal que el backend acepta como "Sin asignar"

// Aliases de cabeceras comunes → key interna. Cubre la plantilla operativa
// de gerencia ("NOMBRE DEL CLIENTE", "CELULAR", "CORREO", "ESTADO",
// "COMENTARIOS") y variantes frecuentes que llegan en exports de Google
// Sheets / Excel. Normalizamos la cabecera quitando acentos, signos y
// espacios antes de buscar.
const COLUMN_ALIASES = {
  fecha:           ['fecha', 'fecharegistro', 'fechaingreso', 'fechacreacion', 'date'],
  nombres:         ['nombres', 'nombre', 'nombredelcliente', 'cliente', 'nombrecompleto'],
  apellidos:       ['apellidos', 'apellido', 'apellidodelcliente'],
  telefono:        ['telefono', 'celular', 'movil', 'numero', 'whatsapp', 'phone'],
  email:           ['email', 'correo', 'correoelectronico', 'mail'],
  ciudad:          ['ciudad', 'ubicacion', 'ubicaciongeografica', 'city'],
  // V060: campana es la columna canonica; los aliases viejos siguen mapeando
  campana:         ['campana', 'campaign', 'nombrecampana', 'inmueble', 'desarrollo'],
  // V060: fuente es la columna canonica; estrategia mapea como alias legacy
  fuente:          ['fuente', 'origen', 'source', 'medio', 'canal'],
  codigo_convenio: ['codigoconvenio', 'codigodeconvenio', 'convenio', 'codconvenio', 'codigo_convenio'],
  calidad:         ['calidad', 'estado', 'temperatura', 'clasificacion'],
  // V065: sede canonica + aliases ("sede_codigo" del back, "sucursal", "local")
  sede:            ['sede', 'sedecodigo', 'sede_codigo', 'sucursal', 'local', 'clinica', 'oficina'],
  asesor:          ['asesor', 'vendedor', 'responsable', 'advisor', 'agent'],
  observaciones:   ['observaciones', 'comentarios', 'comentario', 'notas', 'nota', 'observacion'],
  dni:             ['dni', 'documento', 'doc'],
  // Legacy retrocompat — los aliases match por nombre exacto. Si el archivo
  // dice 'proyecto', se mapea a la columna 'proyecto' (y luego el backend
  // lo unifica con campana). Si dice 'estrategia', a 'estrategia' (luego fuente).
  proyecto:      ['proyecto'],
  estrategia:    ['estrategia', 'strategy'],
}

const _normalizeHeader = (s) =>
  String(s || '')
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')  // quita acentos
    .toLowerCase()
    .replace(/[^a-z0-9]/g, '')

function autoMapColumns(fileColumns) {
  const map = {}
  const normalizedFile = fileColumns.map(fc => ({ raw: fc, norm: _normalizeHeader(fc) }))
  for (const ec of EXPECTED_COLUMNS) {
    const aliases = COLUMN_ALIASES[ec.key] || [ec.key]
    // Match exacto primero (alias == columna normalizada)
    const exact = normalizedFile.find(f => aliases.includes(f.norm))
    if (exact) { map[ec.key] = exact.raw; continue }
    // Match parcial (alias incluido en la columna o viceversa)
    const partial = normalizedFile.find(f =>
      aliases.some(a => f.norm.includes(a) || a.includes(f.norm))
    )
    if (partial) map[ec.key] = partial.raw
  }
  return map
}

/**
 * Normaliza cualquier `detail` devuelto por FastAPI a un string seguro.
 * - 422 de Pydantic: detail = [{type, loc, msg, input}, ...] → "msg (campo)"
 * - 4xx/5xx propios: detail = "texto" → passthrough
 * - Objetos sueltos: JSON.stringify como fallback
 * - undefined/null: retorna fallback
 *
 * Previene React error #31 ("Objects are not valid as a React child") cuando
 * un error 422 se pasa directo a JSX.
 */
function formatApiError(err, fallback = 'Error inesperado.') {
  const detail = err?.response?.data?.detail
  if (detail == null) {
    return err?.message || fallback
  }
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    // Pydantic validation errors: [{type, loc, msg, input}, ...]
    return detail
      .map(d => {
        if (typeof d === 'string') return d
        const msg = d?.msg || d?.message || JSON.stringify(d)
        const loc = Array.isArray(d?.loc) ? d.loc.filter(x => x !== 'body').join('.') : ''
        return loc ? `${msg} (${loc})` : msg
      })
      .join(' · ')
  }
  if (typeof detail === 'object') {
    return detail.msg || detail.message || JSON.stringify(detail)
  }
  return String(detail)
}

/* ── DropZone ────────────────────────────────────────────────────────────── */

function DropZone({ onFile, isLoading }) {
  const inputRef = useRef(null)
  const [isDragging, setIsDragging] = useState(false)

  const handleDrop = (e) => {
    e.preventDefault()
    setIsDragging(false)
    const f = e.dataTransfer.files?.[0]
    if (f) onFile(f)
  }
  const handleChange = (e) => {
    const f = e.target.files?.[0]
    if (f) onFile(f)
    e.target.value = ''
  }

  return (
    <div
      onDragOver={e => { e.preventDefault(); setIsDragging(true) }}
      onDragLeave={() => setIsDragging(false)}
      onDrop={handleDrop}
      onClick={() => !isLoading && inputRef.current?.click()}
      className={`
        border-2 border-dashed rounded-xl p-10 text-center transition-all
        ${isDragging ? 'border-indigo-400 bg-indigo-50 cursor-copy' : 'border-gray-300 bg-gray-50 hover:bg-gray-100 cursor-pointer'}
        ${isLoading ? 'opacity-50 cursor-not-allowed pointer-events-none' : ''}
      `}
    >
      <input ref={inputRef} type="file" accept=".xlsx,.xls,.csv" onChange={handleChange} className="hidden" />
      <FileSpreadsheet size={36} className="text-gray-400 mx-auto mb-3" />
      <p className="text-sm font-medium text-gray-700">Arrastra tu archivo Excel o CSV aquí</p>
      <p className="text-xs text-gray-400 mt-1">Formatos soportados: .xlsx, .xls, .csv — máx. 5 MB — máx. 1 000 filas</p>
      <Button size="sm" variant="outline" className="mt-4 pointer-events-none">
        <Upload size={13} className="mr-1.5" /> Seleccionar archivo
      </Button>
    </div>
  )
}

/* ── Reglas de validación visibles ──────────────────────────────────────── */

function ValidationRules({ calidadCatalog = [], calidadRequired = false }) {
  const codigos = calidadCatalog.length
    ? calidadCatalog.map(c => c.codigo)
    : ['FRIO', 'TIBIO', 'CALIENTE']
  return (
    <div className="bg-blue-50 border border-blue-100 rounded-xl p-4 text-xs text-blue-800 space-y-1">
      <div className="flex items-center gap-1.5 font-semibold text-blue-700 mb-2">
        <Info size={13} /> Reglas de validación
      </div>
      <ul className="space-y-1 ml-4 list-disc">
        <li><strong>Teléfono</strong> — obligatorio. Mínimo 7 dígitos. Números de 9 dígitos se normalizan a +51XXXXXXXXX.</li>
        <li><strong>Nombre o Apellido</strong> — al menos uno debe estar presente.</li>
        <li><strong>Email</strong> — opcional. Si está presente debe tener formato válido (no bloquea la fila si es inválido).</li>
        <li><strong>DNI</strong> — opcional. Solo dígitos, entre 6 y 12 caracteres.</li>
        <li><strong>Fecha</strong> — opcional. Si viene (YYYY-MM-DD o DD/MM/YYYY) sobrescribe la fecha de ingreso del lead; en blanco se usa la fecha actual.</li>
        <li><strong>Ciudad</strong> — texto libre, opcional.</li>
        <li><strong>Campaña</strong> — nombre de la campaña/promoción del lead. Engloba el proyecto/desarrollo (ej: "Test Mayo 2026 — Palma Río").</li>
        <li><strong>Fuente</strong> — <span className="text-red-700 font-semibold">obligatoria</span>. Canal de origen del lead (Convenios, Activación, Referido, Volanteo, Facebook, Instagram, etc.). Debe existir en el catálogo de Fuentes (Configuración → Fuentes).</li>
        <li><strong>Código Convenio</strong> — <span className="text-red-700 font-semibold">obligatorio</span> si la fuente es Convenios (opcional para otras fuentes). Identificador del convenio (ej: <code>CONV-2026</code>).</li>
        <li>
          <strong>Calidad</strong>
          {calidadRequired
            ? <> — <span className="text-red-700 font-semibold">obligatoria</span>. </>
            : <> — opcional. </>}
          Valores aceptados: {codigos.map((c, i) => (
            <span key={c}>{i > 0 && ', '}<code>{c}</code></span>
          ))}.
        </li>
        <li><strong>Sede</strong> — opcional. Slug o nombre exacto de una sede activa (ej: <code>lima</code>, <code>arequipa</code>). Solo aplica si tu CRM tiene sedes configuradas en Configuración → Sedes.</li>
        <li><strong>Asignación</strong> — opcional. Si se define el nombre completo o email del asesor en la columna <code>Asesor</code> de la fila, se le asignará el lead a él. Si se deja en blanco, se asignará al asesor seleccionado en la interfaz al momento de importar (fallback). Los asesores individuales siempre quedan auto-asignados a sí mismos.</li>
        <li><strong>Duplicados</strong> — teléfonos ya existentes en el CRM se omiten automáticamente.</li>
        <li><strong>Máximo</strong> — 1 000 filas por importación. Divida archivos mayores.</li>
      </ul>
    </div>
  )
}

/* ── Mapeo de columnas ──────────────────────────────────────────────────── */

function ColumnMapper({ fileColumns, columnMap, onChangeMap, expectedColumns }) {
  const requiredMapped = expectedColumns.filter(c => c.required).every(c => columnMap[c.key])
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <h3 className="text-sm font-semibold text-gray-700">Mapeo de columnas</h3>
        {!requiredMapped && (
          <span className="text-xs text-red-600 flex items-center gap-1">
            <AlertCircle size={12} /> Mapea los campos obligatorios (Teléfono y Fuente)
          </span>
        )}
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        {expectedColumns.map(ec => (
          <div key={ec.key} className="space-y-1">
            <label className="text-xs font-medium text-gray-500">
              {ec.label}
              {ec.required && <span className="text-red-500 ml-0.5">*</span>}
            </label>
            <select
              value={columnMap[ec.key] || ''}
              onChange={e => onChangeMap(ec.key, e.target.value)}
              className={`w-full text-xs border rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500
                ${ec.required && !columnMap[ec.key] ? 'border-red-300 bg-red-50' : 'border-gray-200'}`}
            >
              <option value="">— no mapear —</option>
              {fileColumns.map(col => (
                <option key={col} value={col}>{col}</option>
              ))}
            </select>
          </div>
        ))}
      </div>
    </div>
  )
}

/* ── Tarjetas de resumen del dry-run ────────────────────────────────────── */

function ValidationSummary({ summary, totalRows }) {
  if (!summary) return null
  const duplicates = (summary.duplicates_db || 0) + (summary.duplicates_file || 0)
  const cards = [
    {
      label: 'Listos para importar',
      value: summary.valid,
      className: 'bg-emerald-50 border-emerald-200 text-emerald-700',
      icon: <CheckCircle size={14} className="text-emerald-600" />,
    },
    {
      label: 'Duplicados',
      value: duplicates,
      sub: `${summary.duplicates_db || 0} en CRM · ${summary.duplicates_file || 0} en archivo`,
      className: 'bg-amber-50 border-amber-200 text-amber-700',
      icon: <Copy size={14} className="text-amber-600" />,
    },
    {
      label: 'Con error',
      value: summary.errors,
      className: summary.errors > 0
        ? 'bg-red-50 border-red-200 text-red-700'
        : 'bg-gray-50 border-gray-200 text-gray-400',
      icon: <XCircle size={14} className={summary.errors > 0 ? 'text-red-600' : 'text-gray-400'} />,
    },
    {
      label: 'Total en archivo',
      value: totalRows,
      className: 'bg-indigo-50 border-indigo-200 text-indigo-700',
      icon: <FileSpreadsheet size={14} className="text-indigo-600" />,
    },
  ]
  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      {cards.map(c => (
        <div key={c.label} className={`rounded-xl border p-4 ${c.className}`}>
          <div className="flex items-center gap-1.5 text-xs font-semibold">
            {c.icon}
            {c.label}
          </div>
          <p className="text-3xl font-bold mt-1 leading-none">{c.value}</p>
          {c.sub && <p className="text-[10px] mt-1 opacity-70">{c.sub}</p>}
        </div>
      ))}
    </div>
  )
}

/* ── Badge de estado por fila ───────────────────────────────────────────── */

const STATUS_META = {
  valid: {
    label: 'Listo',
    className: 'bg-emerald-100 text-emerald-700 border border-emerald-200',
    icon: <CheckCircle size={11} />,
  },
  duplicate_db: {
    label: 'Dup. CRM',
    className: 'bg-amber-100 text-amber-700 border border-amber-200',
    icon: <Copy size={11} />,
  },
  duplicate_file: {
    label: 'Dup. archivo',
    className: 'bg-amber-100 text-amber-700 border border-amber-200',
    icon: <Copy size={11} />,
  },
  error: {
    label: 'Error',
    className: 'bg-red-100 text-red-700 border border-red-200',
    icon: <XCircle size={11} />,
  },
}

function RowStatusBadge({ status }) {
  const meta = STATUS_META[status] || STATUS_META.error
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-semibold ${meta.className}`}>
      {meta.icon}
      {meta.label}
    </span>
  )
}

/* ── Tabla validada: una fila por registro con estado y datos normalizados ── */

function ValidatedPreviewTable({ rows, filter, onFilterChange }) {
  // Defensive: si por alguna razon rows no llega como array, no crasheamos
  // el componente — React 18 sin ErrorBoundary desmonta el arbol completo.
  const safeRows = Array.isArray(rows) ? rows : []
  const counts = {
    all:   safeRows.length,
    valid: safeRows.filter(r => r.status === 'valid').length,
    dup:   safeRows.filter(r => r.status === 'duplicate_db' || r.status === 'duplicate_file').length,
    err:   safeRows.filter(r => r.status === 'error').length,
  }
  const filtered = safeRows.filter(r => {
    if (filter === 'all')   return true
    if (filter === 'valid') return r.status === 'valid'
    if (filter === 'dup')   return r.status === 'duplicate_db' || r.status === 'duplicate_file'
    if (filter === 'err')   return r.status === 'error'
    return true
  })
  const shown = filtered.slice(0, 200)

  const tabs = [
    { key: 'all',   label: 'Todas',      count: counts.all,   active: 'bg-slate-800 text-white border-slate-800' },
    { key: 'valid', label: 'Listas',     count: counts.valid, active: 'bg-emerald-600 text-white border-emerald-600' },
    { key: 'dup',   label: 'Duplicadas', count: counts.dup,   active: 'bg-amber-500 text-white border-amber-500' },
    { key: 'err',   label: 'Errores',    count: counts.err,   active: 'bg-red-600 text-white border-red-600' },
  ]

  // Indicador legible cerca de las pestañas para que el usuario sepa que la
  // tabla muestra un subset cuando filtered > shown (200 filas visibles max).
  const showingLabel =
    filtered.length === 0
      ? 'Sin filas'
      : filtered.length <= shown.length
        ? `Mostrando ${filtered.length} ${filtered.length === 1 ? 'fila' : 'filas'}`
        : `Mostrando ${shown.length} de ${filtered.length} filas`

  return (
    <div>
      <div className="flex items-center justify-between mb-2 flex-wrap gap-2">
        <div className="flex items-baseline gap-2 flex-wrap">
          <h3 className="text-sm font-semibold text-gray-700">Vista previa de importación</h3>
          <span className="text-[11px] text-gray-500 font-medium">{showingLabel}</span>
        </div>
        <div className="flex gap-1.5 flex-wrap">
          {tabs.map(t => (
            <button
              key={t.key}
              onClick={() => onFilterChange(t.key)}
              className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border transition-colors ${
                filter === t.key ? t.active : 'bg-white text-gray-600 border-gray-200 hover:border-gray-400'
              }`}
            >
              {t.label}
              <span className={`text-[10px] font-bold px-1.5 py-0.5 rounded-full ${
                filter === t.key ? 'bg-white/20' : 'bg-gray-100 text-gray-500'
              }`}>
                {t.count}
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border border-gray-200">
        <table className="w-full text-xs">
          <thead className="bg-gray-50 border-b border-gray-200 text-gray-600">
            <tr>
              <th className="px-3 py-2 text-left font-semibold w-12">#</th>
              <th className="px-3 py-2 text-left font-semibold w-24">Estado</th>
              <th className="px-3 py-2 text-left font-semibold">Nombre</th>
              <th className="px-3 py-2 text-left font-semibold">Teléfono</th>
              <th className="px-3 py-2 text-left font-semibold hidden md:table-cell">Email</th>
              <th className="px-3 py-2 text-left font-semibold hidden md:table-cell">DNI</th>
              <th className="px-3 py-2 text-left font-semibold hidden lg:table-cell">Fuente</th>
              <th className="px-3 py-2 text-left font-semibold">Notas</th>
            </tr>
          </thead>
          <tbody>
            {shown.length === 0 && (
              <tr><td colSpan={8} className="px-3 py-6 text-center text-gray-400">
                Sin filas para este filtro.
              </td></tr>
            )}
            {shown.map(r => {
              const isError = r.status === 'error'
              const isDup   = r.status === 'duplicate_db' || r.status === 'duplicate_file'
              const rowBg   = isError ? 'bg-red-50/40' : isDup ? 'bg-amber-50/30' : 'bg-white'
              const nombre  = [r.nombres, r.apellidos].filter(Boolean).join(' ') || <span className="text-gray-400">Sin nombre</span>
              return (
                <tr key={r.row} className={`border-b border-gray-100 last:border-0 ${rowBg}`}>
                  <td className="px-3 py-2 text-gray-400 font-mono">{r.row}</td>
                  <td className="px-3 py-2"><RowStatusBadge status={r.status} /></td>
                  <td className="px-3 py-2 text-gray-700">{nombre}</td>
                  <td className="px-3 py-2 font-mono text-gray-700 whitespace-nowrap">
                    {r.telefono || <span className="text-red-500">—</span>}
                  </td>
                  <td className="px-3 py-2 text-gray-600 hidden md:table-cell max-w-[180px] truncate">
                    {r.email || <span className="text-gray-300">—</span>}
                  </td>
                  <td className="px-3 py-2 text-gray-600 hidden md:table-cell font-mono">
                    {r.dni || <span className="text-gray-300">—</span>}
                  </td>
                  <td className="px-3 py-2 text-gray-600 hidden lg:table-cell">
                    {r.fuente ? (
                      <span className={r.fuente_matched ? 'text-emerald-600' : 'text-amber-600'}>
                        {r.fuente}{!r.fuente_matched && ' ⚠'}
                      </span>
                    ) : <span className="text-gray-300">—</span>}
                    {r.codigo_convenio && (
                      <span className="block text-[10px] text-indigo-600 dark:text-indigo-400 font-mono">
                        {r.codigo_convenio}
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-gray-500 text-[11px]">
                    {Array.isArray(r.errors) && r.errors.length > 0
                      ? r.errors.map(e => (typeof e === 'string' ? e : (e?.msg || JSON.stringify(e)))).join('; ')
                      : ''}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {filtered.length > shown.length && (
          <div className="text-center text-xs text-gray-400 py-2 bg-gray-50 border-t border-gray-100">
            Mostrando {shown.length} de {filtered.length} filas filtradas.
          </div>
        )}
      </div>
    </div>
  )
}

/* ── Resultado de importación ───────────────────────────────────────────── */

function ImportResult({ result }) {
  if (!result) return null
  const hasErrors = result.errors > 0
  const hasErrorRows = result.error_rows?.length > 0

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-3 gap-3">
        <div className="bg-emerald-50 border border-emerald-200 rounded-xl p-4 text-center">
          <p className="text-3xl font-bold text-emerald-700">{result.inserted}</p>
          <p className="text-xs text-emerald-600 mt-1 font-medium">Importados</p>
        </div>
        <div className="bg-amber-50 border border-amber-200 rounded-xl p-4 text-center">
          <p className="text-3xl font-bold text-amber-700">{result.duplicates}</p>
          <p className="text-xs text-amber-600 mt-1 font-medium">Duplicados omitidos</p>
          <p className="text-xs text-amber-500 mt-0.5">Ya existían en el CRM</p>
        </div>
        <div className={`rounded-xl p-4 text-center border ${hasErrors ? 'bg-red-50 border-red-200' : 'bg-gray-50 border-gray-200'}`}>
          <p className={`text-3xl font-bold ${hasErrors ? 'text-red-700' : 'text-gray-400'}`}>{result.errors}</p>
          <p className={`text-xs mt-1 font-medium ${hasErrors ? 'text-red-600' : 'text-gray-400'}`}>Con error</p>
        </div>
      </div>

      {hasErrorRows && (
        <div>
          <h4 className="text-xs font-semibold text-gray-600 mb-2 flex items-center gap-1">
            <AlertTriangle size={12} className="text-amber-500" />
            Filas con problemas ({result.error_rows.length}):
          </h4>
          <div className="max-h-48 overflow-y-auto space-y-1 rounded-lg border border-gray-100 p-2 bg-gray-50">
            {result.error_rows.map((e, i) => (
              <div key={i} className="flex items-start gap-2 text-xs bg-white border border-red-100 rounded px-2.5 py-1.5">
                <span className="text-gray-400 flex-shrink-0 font-mono">Fila {e.row}</span>
                <span className="text-red-600">{e.error}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

/* ── Página principal ───────────────────────────────────────────────────── */

export default function CargaMasiva() {
  const [file, setFile]               = useState(null)
  const [preview, setPreview]         = useState(null)
  const [totalRows, setTotalRows]     = useState(0)
  const [columnMap, setColumnMap]     = useState({})
  const [isParsing, setIsParsing]     = useState(false)
  const [isImporting, setIsImporting] = useState(false)
  const [isDownloading, setIsDownloading] = useState(false)
  const [parseError, setParseError]   = useState(null)
  const [importResult, setImportResult] = useState(null)
  const [historial, setHistorial]       = useState([])
  const [isLoadingHistorial, setIsLoadingHistorial] = useState(false)
  // V070.48 — Estado para el modal de confirmacion al borrar historial.
  // Reemplaza window.confirm() nativo del navegador por ConfirmDialog
  // estandarizado (paridad Leads/Llamadas/Asignacion/etc).
  const [historialDelete, setHistorialDelete] = useState({ open: false, id: null, deleting: false })
  const [historialError, setHistorialError]   = useState(null)
  const [asesoresOpts, setAsesoresOpts] = useState([])
  const [userRole, setUserRole]         = useState(null)
  const [targetAsesor, setTargetAsesor] = useState('')

  // Dry-run: validación completa antes de importar.
  // null = aún no ejecutado; {summary, rows, total_rows} cuando termina.
  const [validated, setValidated]         = useState(null)
  const [isValidating, setIsValidating]   = useState(false)
  const [validationError, setValidationError] = useState(null)
  const [validatedFilter, setValidatedFilter] = useState('all')
  // Track del último column_map validado para saber si el usuario movió algo
    // y debemos ofrecer "Re-analizar".
  const [validatedMapKey, setValidatedMapKey] = useState(null)
  // Descarga del Excel de problemas (errores + duplicados)
  const [isDownloadingErrors, setIsDownloadingErrors] = useState(false)
  // V028: catálogo de calidad + flag "calidad obligatoria" (ambos configurables)
  const [modalDetalles, setModalDetalles] = useState({
    open: false,
    historialId: null,
    initialTab: 'duplicates',
    cargaPreview: null,
  })

  const handleOpenDetalles = (carga, tab) => {
    setModalDetalles({
      open: true,
      historialId: carga.id,
      initialTab: tab,
      cargaPreview: carga,
    })
  }

  const [calidadCatalog, setCalidadCatalog] = useState([])
  const [calidadRequired, setCalidadRequired] = useState(false)

  useEffect(() => {
    api.get('/api/leads/carga-masiva/asesores-disponibles')
      .then(res => {
        const { role, items } = res.data || {}
        setUserRole(role)
        setAsesoresOpts(items || [])
        if (role === 'asesor' && items?.[0]) {
          setTargetAsesor(items[0].id)
        }
      })
      .catch(() => {})
  }, [])

  // V028: catálogo de calidad y flag de obligatoriedad. Se consultan por
  // separado (endpoints distintos) y cualquier falla es silenciosa: el
  // backend valida igual, esto solo alimenta los hints de la UI.
  useEffect(() => {
    api.get('/api/calidad').then(res => {
      if (Array.isArray(res.data)) setCalidadCatalog(res.data)
    }).catch(() => {})
    api.get('/api/settings/carga-masiva').then(res => {
      setCalidadRequired(Boolean(res.data?.calidad_requerida))
    }).catch(() => {})
  }, [])

  // Columnas visibles: la obligatoriedad de `calidad` se resuelve desde el
  // setting configurable. Sin el flag: sigue siendo opcional (default).
  const expectedColumns = EXPECTED_COLUMNS.map(c =>
    c.key === 'calidad' ? { ...c, required: calidadRequired } : c
  )

  const fetchHistorial = useCallback(async () => {
    setIsLoadingHistorial(true)
    try {
      const res = await api.get('/api/leads/carga-masiva/historial')
      setHistorial(res.data?.items || [])
    } catch {
      // silencioso
    } finally {
      setIsLoadingHistorial(false)
    }
  }, [])

  useEffect(() => { fetchHistorial() }, [fetchHistorial])

  // V070.48 — Abre el modal de confirmacion. La accion real se ejecuta
  // en handleConfirmDeleteHistorial cuando el user toca "Eliminar".
  const handleDeleteHistorial = (id) => {
    setHistorialError(null)
    setHistorialDelete({ open: true, id, deleting: false })
  }

  const handleConfirmDeleteHistorial = async () => {
    const { id } = historialDelete
    if (!id) return
    setHistorialDelete(prev => ({ ...prev, deleting: true }))
    try {
      await api.delete(`/api/leads/carga-masiva/historial/${id}`)
      setHistorial(prev => prev.filter(h => h.id !== id))
      setHistorialDelete({ open: false, id: null, deleting: false })
    } catch (err) {
      setHistorialError(formatApiError(err, 'No se pudo eliminar el registro.'))
      setHistorialDelete(prev => ({ ...prev, deleting: false }))
    }
  }

  const handleCancelDeleteHistorial = () => {
    setHistorialDelete({ open: false, id: null, deleting: false })
  }

  const canDeleteHistorial = userRole === 'admin' || userRole === 'supervisor'

  // Ejecuta el dry-run en el backend: valida todas las filas y revisa
  // duplicados contra la DB. No inserta nada — es una preview confiable.
  //
  // Diseño importante:
  //  - La respuesta se VALIDA antes de setearse en el estado: si el backend
  //    devuelve algo inesperado (HTML del SPA fallback, 404 sin endpoint
  //    desplegado, datos malformados) no crasheamos los componentes hijos
  //    cuando leen rows/summary.
  //  - En caso de error NO limpiamos `validated` para no vaciar la vista:
  //    el usuario mantiene el contexto anterior y vemos el error arriba.
  const runValidation = useCallback(async (fileArg, mapArg) => {
    if (!fileArg || !mapArg?.telefono) return
    setIsValidating(true)
    setValidationError(null)
    try {
      const fd = new FormData()
      fd.append('file', fileArg)
      fd.append('column_map', JSON.stringify(mapArg))
      // NOTE: no seteamos Content-Type manualmente — axios detecta FormData
      // y agrega multipart/form-data con el boundary correcto.
      const res = await api.post('/api/leads/carga-masiva/preview-validated', fd)
      const data = res.data
      if (!data || typeof data !== 'object' || !Array.isArray(data.rows) || !data.summary) {
        throw new Error(
          'El servidor devolvió una respuesta inesperada. ' +
          'Puede ser un problema de despliegue — avisa al administrador.',
        )
      }
      setValidated(data)
      setValidatedMapKey(JSON.stringify(mapArg))
      setValidatedFilter('all')
    } catch (err) {
      // formatApiError normaliza el 422 de Pydantic (array de objetos) a
      // string seguro — previene React #31 al renderizar como child.
      setValidationError(formatApiError(err, 'Error al analizar el archivo.'))
      // NO seteamos validated=null — conservamos el resultado anterior (si
      // lo hay) para que la vista no colapse. Si era el primer análisis,
      // simplemente no hay vista que mostrar y el usuario ve el error banner.
    } finally {
      setIsValidating(false)
    }
  }, [])

  // Descarga un Excel con solo las filas problematicas (errores + duplicados)
  // para que el usuario las corrija offline y vuelva a subir.
  //
  // Usa el mismo archivo + mapeo que el dry-run, asi el backend genera el xlsx
  // con los mismos criterios exactos (idempotente).
  const handleDownloadErrors = useCallback(async () => {
    if (!file || !columnMap?.telefono) return
    setIsDownloadingErrors(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      fd.append('column_map', JSON.stringify(columnMap))
      const res = await api.post('/api/leads/carga-masiva/download-errors', fd, {
        responseType: 'blob',
      })
      // Extraer nombre del Content-Disposition si esta presente, o fallback
      const cd = res.headers?.['content-disposition'] || ''
      const match = /filename="?([^"]+)"?/i.exec(cd)
      const filename = match?.[1] || 'problemas_carga.xlsx'
      // Trigger download
      const blobUrl = window.URL.createObjectURL(new Blob([res.data], {
        type: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
      }))
      const a = document.createElement('a')
      a.href = blobUrl
      a.download = filename
      document.body.appendChild(a)
      a.click()
      a.remove()
      window.URL.revokeObjectURL(blobUrl)
    } catch (err) {
      // El endpoint devuelve blob — para leer el JSON de error hay que parsearlo
      let detail = 'No se pudo descargar el archivo de problemas.'
      if (err?.response?.data instanceof Blob) {
        try {
          const text = await err.response.data.text()
          const json = JSON.parse(text)
          detail = json?.detail || detail
        } catch { /* se queda con el fallback */ }
      } else {
        detail = formatApiError(err, detail)
      }
      alert(detail)
    } finally {
      setIsDownloadingErrors(false)
    }
  }, [file, columnMap])

  /* ── manejo de archivo ── */
  const handleFile = async (selectedFile) => {
    const validExts = /\.(xlsx|xls|csv)$/i
    if (!validExts.test(selectedFile.name)) {
      setParseError('Formato no soportado. Usa .xlsx, .xls o .csv')
      return
    }
    if (selectedFile.size > 5 * 1024 * 1024) {
      setParseError('El archivo supera el límite de 5 MB.')
      return
    }
    setFile(selectedFile)
    setParseError(null)
    setImportResult(null)
    setPreview(null)
    setColumnMap({})
    setValidated(null)
    setValidationError(null)
    setValidatedMapKey(null)
    setIsParsing(true)
    try {
      const formData = new FormData()
      formData.append('file', selectedFile)
      const res = await api.post('/api/leads/carga-masiva/preview', formData)
      const { columns, preview: rows, total_rows } = res.data
      setPreview(rows || [])
      setTotalRows(total_rows || 0)
      setColumnMap(autoMapColumns(columns))
      // NO disparamos runValidation automaticamente: la carrera entre el
      // render del preview y el fetch del dry-run causaba que la vista
      // previa pareciera "abrirse y cerrarse". El usuario activa el
      // analisis con el boton "Analizar archivo" cuando el mapeo luce bien.
    } catch (err) {
      setParseError(formatApiError(err, 'Error al procesar el archivo.'))
    } finally {
      setIsParsing(false)
    }
  }

  /* ── importar ── */
  const handleImport = async () => {
    if (!columnMap.telefono) {
      setParseError('Debes mapear la columna "Teléfono" para continuar.')
      return
    }
    if (userRole !== 'asesor' && !targetAsesor) {
      setParseError('Debes elegir un asesor destino (o "Sin asignar").')
      return
    }
    setIsImporting(true)
    setParseError(null)
    try {
      const formData = new FormData()
      formData.append('file', file)
      formData.append('column_map', JSON.stringify(columnMap))
      formData.append('target_asesor_id', targetAsesor || '')
      const res = await api.post('/api/leads/carga-masiva', formData)
      setImportResult(res.data)
      setPreview(null)
      setFile(null)
      fetchHistorial()
    } catch (err) {
      setParseError(formatApiError(err, 'Error durante la importación.'))
    } finally {
      setIsImporting(false)
    }
  }

  /* ── descargar plantilla (requiere auth) ── */
  const handleDownloadTemplate = async () => {
    setIsDownloading(true)
    try {
      const res = await api.get('/api/leads/carga-masiva/plantilla', { responseType: 'blob' })
      const url = URL.createObjectURL(res.data)
      const a = document.createElement('a')
      a.href = url
      a.download = 'plantilla_leads.xlsx'
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      // falla silenciosa
    } finally {
      setIsDownloading(false)
    }
  }

  const handleReset = () => {
    setFile(null)
    setPreview(null)
    setTotalRows(0)
    setColumnMap({})
    setParseError(null)
    setImportResult(null)
    setValidated(null)
    setValidationError(null)
    setValidatedMapKey(null)
    setValidatedFilter('all')
    if (userRole !== 'asesor') setTargetAsesor('')
  }

  const requiredMapped = Boolean(columnMap.telefono && columnMap.fuente)
  // Si el column_map cambió respecto al último validado, el dry-run esta
  // desactualizado y mostramos el boton "Re-analizar".
  const mapChangedSinceValidation = validatedMapKey && validatedMapKey !== JSON.stringify(columnMap)
  const validCount = validated?.summary?.valid || 0

  return (
    <div className="space-y-5 max-w-4xl">

      {/* ── Encabezado ── */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Carga Masiva</h1>
          <p className="text-sm text-gray-500 mt-0.5">Importa leads desde un archivo Excel o CSV.</p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={handleDownloadTemplate}
          disabled={isDownloading}
          className="gap-1.5 text-indigo-600 border-indigo-200 hover:bg-indigo-50"
        >
          <DownloadCloud size={14} />
          {isDownloading ? 'Descargando…' : 'Descargar plantilla'}
        </Button>
      </div>

      {/* ── Reglas ── */}
      {!file && !importResult && (
        <ValidationRules
          calidadCatalog={calidadCatalog}
          calidadRequired={calidadRequired}
        />
      )}

      {/* ── Card principal ── */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold text-gray-700">
            {file ? (
              <div className="flex items-center justify-between">
                <span className="flex items-center gap-2">
                  <FileSpreadsheet size={15} className="text-emerald-600" />
                  {file.name}
                  <Badge variant="secondary" className="text-xs">
                    {(file.size / 1024).toFixed(0)} KB
                  </Badge>
                </span>
                {!isImporting && !importResult && (
                  <button onClick={handleReset} className="text-gray-400 hover:text-red-500 transition-colors">
                    <X size={15} />
                  </button>
                )}
              </div>
            ) : (
              'Seleccionar archivo'
            )}
          </CardTitle>
        </CardHeader>

        <CardContent className="space-y-5">
          {/* DropZone */}
          {!file && !importResult && (
            <DropZone onFile={handleFile} isLoading={isParsing} />
          )}

          {/* Parsing spinner */}
          {isParsing && (
            <div className="flex items-center gap-2 text-sm text-gray-500 py-4 justify-center">
              <span className="w-4 h-4 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
              Analizando archivo…
            </div>
          )}

          {/* Error */}
          {parseError && (
            <div className="flex items-start gap-2 bg-red-50 border border-red-200 text-red-700 rounded-lg px-4 py-3 text-sm">
              <AlertCircle size={15} className="shrink-0 mt-0.5" />
              {parseError}
            </div>
          )}

          {/* Selector de asesor destino */}
          {preview && !importResult && (
            <div className="rounded-lg border border-indigo-100 bg-indigo-50/40 p-4">
              <h3 className="text-sm font-semibold text-gray-700 mb-2">Asignación del lote</h3>
              {userRole === 'asesor' ? (
                <p className="text-xs text-indigo-800">
                  Estos leads se asignarán automáticamente a ti:{' '}
                  <strong>{asesoresOpts[0]?.nombre || asesoresOpts[0]?.email}</strong>.
                </p>
              ) : (
                <div className="space-y-1">
                  <label className="text-xs font-medium text-gray-600">
                    Asignar leads (por defecto / fallback) a <span className="text-red-500">*</span>
                  </label>
                  <select
                    value={targetAsesor}
                    onChange={e => setTargetAsesor(e.target.value)}
                    className="w-full md:w-80 text-xs border border-gray-200 rounded-md px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                  >
                    <option value="">— elegir —</option>
                    <option value={POOL_VALUE}>Sin asignar (pool)</option>
                    {asesoresOpts.map(u => (
                      <option key={u.id} value={u.id}>
                        {u.nombre || u.email} {u.role ? `· ${u.role}` : ''}
                      </option>
                    ))}
                  </select>
                  <p className="text-xs text-gray-500 mt-1">
                    {userRole === 'supervisor'
                      ? 'Solo puedes asignar a ti mismo o a asesores de tu equipo.'
                      : 'Puedes elegir cualquier asesor/supervisor activo o dejar en pool.'}
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Mapeo de columnas + vista previa validada */}
          {preview && !importResult && (
            <>
              <ColumnMapper
                fileColumns={Object.keys(preview[0] || {})}
                columnMap={columnMap}
                onChangeMap={(key, val) => setColumnMap(p => ({ ...p, [key]: val }))}
                expectedColumns={expectedColumns}
              />

              {/* Zona del dry-run: acciones + resultado + loading.
                  min-height reserva espacio para evitar que el historial de
                  abajo "salte" cuando cambian los estados (idle → loading →
                  resultado). */}
              <div className="space-y-4" style={{ minHeight: validated ? 'auto' : '220px' }}>
                {/* Acciones de validación */}
                <div className="flex items-center justify-between gap-2 flex-wrap">
                  <div className="text-xs text-gray-500 flex-1 min-w-0">
                    {!validated && !isValidating && requiredMapped && !validationError && (
                      <span>Pulsa <strong>Analizar archivo</strong> para ver qué pasará antes de importar.</span>
                    )}
                    {!requiredMapped && (
                      <span className="text-red-600">Mapea el campo obligatorio <strong>Teléfono</strong> para poder analizar.</span>
                    )}
                    {mapChangedSinceValidation && (
                      <span className="text-amber-600 flex items-center gap-1">
                        <AlertTriangle size={12} /> Cambiaste el mapeo — vuelve a analizar para actualizar la vista previa.
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    {/* Botón de descarga: visible SOLO si hay problemas que corregir */}
                    {validated && !isValidating && (
                      (validated.summary?.errors > 0 ||
                       validated.summary?.duplicates_db > 0 ||
                       validated.summary?.duplicates_file > 0) && (
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={handleDownloadErrors}
                          disabled={isDownloadingErrors}
                          className="gap-1.5"
                          title="Descarga un Excel con solo las filas problemáticas para corregirlas offline"
                        >
                          {isDownloadingErrors ? (
                            <>
                              <span className="w-3.5 h-3.5 border-2 border-emerald-500 border-t-transparent rounded-full animate-spin" />
                              Generando…
                            </>
                          ) : (
                            <>
                              <FileDown size={13} />
                              Descargar problemas
                            </>
                          )}
                        </Button>
                      )
                    )}
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => runValidation(file, columnMap)}
                      disabled={!requiredMapped || isValidating}
                      className="gap-1.5"
                    >
                      {isValidating ? (
                        <>
                          <span className="w-3.5 h-3.5 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
                          Analizando…
                        </>
                      ) : (
                        <>
                          <RefreshCw size={13} />
                          {validated ? 'Re-analizar' : 'Analizar archivo'}
                        </>
                      )}
                    </Button>
                  </div>
                </div>

                {/* Aviso preventivo para archivos grandes — dentro del dry-run zone
                    para que el usuario lo vea ANTES de pulsar Analizar. */}
                {totalRows > 500 && !validated && !isValidating && (
                  <div className="flex items-center gap-2 bg-amber-50 border border-amber-200 text-amber-800 rounded-lg px-4 py-2.5 text-xs">
                    <AlertTriangle size={13} className="shrink-0" />
                    Archivo grande ({totalRows.toLocaleString()} filas). El análisis puede tardar 1-3 segundos.
                  </div>
                )}

                {/* Error del dry-run — prominente y persistente hasta la siguiente acción */}
                {validationError && (
                  <div className="flex items-start gap-2 bg-red-50 border border-red-300 text-red-800 rounded-lg px-4 py-3 text-sm">
                    <AlertCircle size={16} className="shrink-0 mt-0.5" />
                    <div className="flex-1">
                      <p className="font-semibold">No se pudo analizar el archivo</p>
                      <p className="text-xs mt-0.5 text-red-700">{validationError}</p>
                    </div>
                  </div>
                )}

                {/* Estado de carga: siempre se renderiza mientras isValidating,
                    esté o no ya cargado un resultado previo. Asi el usuario ve
                    feedback inmediato incluso en un re-analisis. */}
                {isValidating && (
                  <div className="rounded-xl border border-dashed border-indigo-200 bg-indigo-50/40 p-6 text-center">
                    <div className="inline-flex items-center gap-2 text-sm text-indigo-700">
                      <span className="w-4 h-4 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
                      Analizando {totalRows.toLocaleString()} fila{totalRows !== 1 ? 's' : ''}…
                    </div>
                    <p className="text-xs text-indigo-500 mt-1.5">
                      Validando formato y revisando duplicados contra el CRM.
                    </p>
                  </div>
                )}

                {/* Resumen + tabla validada (persiste incluso si hay error en un re-analisis).
                    Envolvemos en ErrorBoundary interno para que si el render de la tabla
                    falla, solo se colapse esta zona — no toda la pagina. */}
                {validated && validated.summary && !isValidating && (
                  <ErrorBoundary
                    fallback={(err, reset) => (
                      <div className="rounded-xl border border-red-200 bg-red-50 p-4 text-sm text-red-800">
                        <div className="flex items-start gap-2">
                          <AlertCircle size={16} className="shrink-0 mt-0.5" />
                          <div className="flex-1">
                            <p className="font-semibold">No se pudo mostrar la vista previa</p>
                            <p className="text-xs mt-0.5 text-red-700">
                              {err?.message || 'Error al renderizar la tabla de validación.'}
                            </p>
                            <button
                              type="button"
                              onClick={reset}
                              className="mt-2 text-xs underline hover:no-underline"
                            >
                              Reintentar
                            </button>
                          </div>
                        </div>
                      </div>
                    )}
                  >
                    <ValidationSummary summary={validated.summary} totalRows={validated.total_rows} />
                    <ValidatedPreviewTable
                      rows={validated.rows}
                      filter={validatedFilter}
                      onFilterChange={setValidatedFilter}
                    />
                  </ErrorBoundary>
                )}

                {/* Placeholder vacío cuando aún no hay validación ni error */}
                {!isValidating && !validated && !validationError && requiredMapped && (
                  <div className="rounded-xl border border-dashed border-gray-200 bg-gray-50/50 p-8 text-center text-xs text-gray-400">
                    Aún no se ha analizado el archivo.
                  </div>
                )}
              </div>

              {/* Advertencia si hay muchas filas */}
              {totalRows > 500 && (
                <div className="flex items-center gap-2 bg-amber-50 border border-amber-200 text-amber-800 rounded-lg px-4 py-2.5 text-xs">
                  <AlertTriangle size={13} className="shrink-0" />
                  Archivo grande ({totalRows} filas). La importación puede tardar unos segundos.
                </div>
              )}

              <div className="flex gap-2 justify-end pt-2 border-t border-gray-100">
                <Button variant="outline" size="sm" onClick={handleReset}>Cancelar</Button>
                <Button
                  size="sm"
                  onClick={handleImport}
                  disabled={isImporting || !requiredMapped || isValidating || (validated && validCount === 0)}
                  className="gap-1.5"
                  title={validated && validCount === 0 ? 'No hay filas listas para importar' : ''}
                >
                  {isImporting ? (
                    <>
                      <span className="w-3.5 h-3.5 border-2 border-white border-t-transparent rounded-full animate-spin" />
                      Importando…
                    </>
                  ) : (
                    <>
                      <Upload size={13} />
                      {validated
                        ? `Importar ${validCount} fila${validCount !== 1 ? 's' : ''} listas`
                        : `Importar ${totalRows} fila${totalRows !== 1 ? 's' : ''}`}
                    </>
                  )}
                </Button>
              </div>
            </>
          )}

          {/* Resultado */}
          {importResult && (
            <>
              <div className="flex items-center gap-2 text-sm font-medium text-emerald-700 bg-emerald-50 border border-emerald-200 rounded-lg px-4 py-3">
                <CheckCircle size={15} />
                Importación completada: {importResult.inserted} lead{importResult.inserted !== 1 ? 's' : ''} nuevos agregados al CRM.
              </div>
              <ImportResult result={importResult} />
              <div className="flex justify-end pt-2 border-t border-gray-100">
                <Button variant="outline" size="sm" onClick={handleReset}>
                  Importar otro archivo
                </Button>
              </div>
            </>
          )}
        </CardContent>
      </Card>

      {/* ── Historial de cargas ── */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm font-semibold text-gray-700 flex items-center gap-2">
            <History size={15} className="text-indigo-600" />
            Historial de cargas
            {historial.length > 0 && (
              <Badge variant="secondary" className="text-xs">{historial.length}</Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {isLoadingHistorial ? (
            <div className="flex items-center gap-2 text-sm text-gray-500 py-4 justify-center">
              <span className="w-4 h-4 border-2 border-indigo-500 border-t-transparent rounded-full animate-spin" />
              Cargando historial…
            </div>
          ) : historial.length === 0 ? (
            <p className="text-xs text-gray-400 text-center py-4">Aún no hay cargas registradas.</p>
          ) : (
            <div className="overflow-x-auto rounded-lg border border-gray-200">
              <table className="w-full text-xs">
                <thead>
                  <tr className="bg-gray-50 border-b border-gray-200 text-gray-600">
                    <th className="px-3 py-2 text-left font-semibold">Fecha</th>
                    <th className="px-3 py-2 text-left font-semibold">Usuario</th>
                    <th className="px-3 py-2 text-left font-semibold">Archivo</th>
                    <th className="px-3 py-2 text-right font-semibold">Filas</th>
                    <th className="px-3 py-2 text-right font-semibold text-emerald-700">Importados</th>
                    <th className="px-3 py-2 text-right font-semibold text-amber-700">Duplicados</th>
                    <th className="px-3 py-2 text-right font-semibold text-red-700">Errores</th>
                    {canDeleteHistorial && <th className="px-3 py-2 w-10"></th>}
                  </tr>
                </thead>
                <tbody>
                  {historial.map(h => (
                    <tr key={h.id} className="border-b border-gray-100 last:border-0 hover:bg-gray-50/60">
                      <td className="px-3 py-2 text-gray-600 whitespace-nowrap">
                        {h.uploaded_at ? new Date(h.uploaded_at).toLocaleString('es-PE') : '—'}
                      </td>
                      <td className="px-3 py-2 text-gray-600 whitespace-nowrap">
                        {h.uploaded_by_nombre || '—'}
                      </td>
                      <td className="px-3 py-2 text-gray-600 max-w-[220px] truncate" title={h.filename}>
                        {h.filename}
                      </td>
                      <td className="px-3 py-2 text-right text-gray-700 font-medium">{h.total_rows}</td>
                      <td className="px-3 py-2 text-right text-emerald-700 font-semibold">{h.inserted}</td>
                      <td className="px-3 py-2 text-right">
                        {h.duplicates > 0 ? (
                          <button
                            type="button"
                            onClick={() => handleOpenDetalles(h, 'duplicates')}
                            className="inline-flex items-center justify-center font-bold text-amber-700 hover:text-amber-900 bg-amber-50 hover:bg-amber-100 px-2 py-0.5 rounded-md transition-colors cursor-pointer border border-amber-200/80 shadow-2xs hover:scale-105 active:scale-95"
                            title="Haga clic para ver el detalle de los leads duplicados"
                          >
                            {h.duplicates}
                          </button>
                        ) : (
                          <span className="text-gray-400">0</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right">
                        {h.errors > 0 ? (
                          <button
                            type="button"
                            onClick={() => handleOpenDetalles(h, 'errors')}
                            className="inline-flex items-center justify-center font-bold text-red-700 hover:text-red-900 bg-red-50 hover:bg-red-100 px-2 py-0.5 rounded-md transition-colors cursor-pointer border border-red-200/80 shadow-2xs hover:scale-105 active:scale-95"
                            title="Haga clic para ver el detalle de los errores"
                          >
                            {h.errors}
                          </button>
                        ) : (
                          <span className="text-gray-400">0</span>
                        )}
                      </td>
                      {canDeleteHistorial && (
                        <td className="px-3 py-2 text-right">
                          <button
                            onClick={() => handleDeleteHistorial(h.id)}
                            className="text-gray-400 hover:text-red-600 transition-colors"
                            title="Eliminar registro del historial"
                          >
                            <Trash2 size={14} />
                          </button>
                        </td>
                      )}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Modal interactivo de detalle de duplicados y errores */}
      <ModalDetalleCarga
        open={modalDetalles.open}
        onClose={() => setModalDetalles(prev => ({ ...prev, open: false }))}
        historialId={modalDetalles.historialId}
        endpoint="/api/leads/carga-masiva/historial"
        initialTab={modalDetalles.initialTab}
        cargaPreview={modalDetalles.cargaPreview}
      />

      {/* V070.48 — Modal estandarizado (CRMs profesionales style). Reemplaza
          el window.confirm() nativo del navegador. */}
      <ConfirmDialog
        open={historialDelete.open}
        title="Eliminar registro del historial"
        message={
          historialError ||
          'Esta acción borrará el registro del historial de cargas. Los leads que ya se importaron NO se eliminan, solo desaparece esta entrada del log.'
        }
        confirmLabel={historialDelete.deleting ? 'Eliminando…' : 'Eliminar'}
        cancelLabel="Cancelar"
        variant="danger"
        onConfirm={handleConfirmDeleteHistorial}
        onCancel={handleCancelDeleteHistorial}
      />
    </div>
  )
}
