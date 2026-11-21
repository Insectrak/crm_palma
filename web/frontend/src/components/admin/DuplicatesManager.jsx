/**
 * DuplicatesManager — V067 Fase 3: panel admin para fusionar leads duplicados.
 *
 * Patron patrón estándar "Duplicate Management" / patrón estándar "Merge contacts":
 *   1. Lista clusters de leads con el mismo telefono.
 *   2. Admin elige uno como MASTER (el que conserva el id) y otro como
 *      SECONDARY (se absorbe).
 *   3. Preview con diff campo por campo — admin marca por campo "master"
 *      o "secondary".
 *   4. Confirmar → backend hace UPDATE atomico, audita en lead_merges,
 *      marca secondary como activo=FALSE + merged_into=master_id.
 *
 * Solo admin (require_admin a nivel backend; UI filtra por rol).
 */
import { Fragment, useEffect, useMemo, useState } from 'react'
import {
  GitMerge, AlertCircle, ChevronRight, Loader,
  CheckCircle, X as XIcon, Eye, Users,
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import api from '@/lib/api'

// Campos del lead que el admin puede "tomar" del secondary durante merge.
// Espejo de MERGEABLE_FIELDS en backend/services/lead_merge_service.py.
const FIELD_LABELS = {
  nombres:        'Nombres',
  apellidos:      'Apellidos',
  telefono:       'Teléfono',
  email:          'Email',
  dni:            'Documento',
  tipo_documento: 'Tipo doc.',
  ciudad:         'Ciudad',
  trabajo:        'Trabajo',
  campana:        'Campaña',
  observaciones:  'Observaciones',
  asesor_id:      'Asesor',
  supervisor_id:  'Supervisor',
  sede_id:        'Sede',
  fuente_id:      'Fuente',
}

// V067.2 — Agrupamiento semantico de campos para el merge (patron
// CRMs profesionales Contact Merge): "quien es" → "como contactarlo" →
// "perfil" → "quien lo maneja" → "de donde vino" → "notas". El orden
// alfabetico previo era confuso (Asesor antes que Nombres no tiene
// sentido en un flujo de fusion de contactos).
const FIELD_GROUPS = [
  { label: 'Identidad',  fields: ['nombres', 'apellidos', 'tipo_documento', 'dni'] },
  { label: 'Contacto',   fields: ['telefono', 'email'] },
  { label: 'Perfil',     fields: ['ciudad', 'trabajo'] },
  { label: 'Asignación', fields: ['asesor_id', 'supervisor_id', 'sede_id'] },
  { label: 'Atribución', fields: ['fuente_id', 'campana'] },
  { label: 'Notas',      fields: ['observaciones'] },
]

// Campos cuyos valores se muestran con su "nombre resuelto" (no el UUID).
const RESOLVED_FIELD = {
  asesor_id:     'asesor_nombre',
  supervisor_id: 'supervisor_nombre',
  fuente_id:     'fuente_nombre',
  estado_id:     'estado_nombre',
}


export default function DuplicatesManager() {
  const [clusters, setClusters]    = useState([])
  const [meta, setMeta]            = useState({ total: 0, totalGlobal: 0, capped: false })
  const [loading, setLoading]      = useState(true)
  const [error, setError]          = useState(null)
  const [mergeUI, setMergeUI]      = useState(null) // { masterId, secondaryId, preview, decisions, notes }
  const [merging, setMerging]      = useState(false)
  const [msg, setMsg]              = useState(null)
  const [limit, setLimit]          = useState(500)  // ampliable si total_capped

  const loadClusters = (lim = limit) => {
    setLoading(true); setError(null)
    api.get(`/api/admin/leads/duplicates?limit=${lim}`)
      .then(res => {
        setClusters(res.data?.clusters || [])
        setMeta({
          total:       res.data?.total_clusters || 0,
          totalGlobal: res.data?.total_clusters_global || 0,
          capped:      !!res.data?.total_capped,
        })
      })
      .catch(err => setError(err.response?.data?.detail || 'No se pudieron cargar los duplicados.'))
      .finally(() => setLoading(false))
  }

  useEffect(() => { loadClusters() }, [])

  const openMerge = (masterId, secondaryId) => {
    setMergeUI({ loading: true, masterId, secondaryId })
    api.get(`/api/admin/leads/merge/preview?master_id=${masterId}&secondary_id=${secondaryId}`)
      .then(res => {
        setMergeUI({
          masterId, secondaryId,
          preview:   res.data,
          decisions: {},   // default: todos los campos se conservan del master
          notes:     '',
        })
      })
      .catch(err => {
        setMergeUI(null)
        setMsg({ ok: false, text: err.response?.data?.detail || 'No se pudo abrir el preview.' })
        setTimeout(() => setMsg(null), 4000)
      })
  }

  const closeMerge = () => setMergeUI(null)

  const setDecision = (field, choice) => {
    setMergeUI(p => ({ ...p, decisions: { ...p.decisions, [field]: choice } }))
  }

  const confirmMerge = () => {
    if (!mergeUI?.preview) return
    setMerging(true)
    api.post(`/api/admin/leads/${mergeUI.masterId}/merge`, {
      secondary_id:    mergeUI.secondaryId,
      field_decisions: mergeUI.decisions,
      notes:           mergeUI.notes?.trim() || null,
    })
      .then(res => {
        const c = res.data?.counts || {}
        const moved = (c.contactos_migrated || 0) + (c.llamadas_migrated || 0)
                    + (c.tags_migrated || 0) + (c.recontactos_migrated || 0)
                    + (c.submissions_migrated || 0)
        setMsg({
          ok: true,
          text: `Leads fusionados. Master #${res.data.master_id} absorbió ${moved} registro(s) del lead #${res.data.secondary_id}.`,
        })
        setMergeUI(null)
        loadClusters()
        setTimeout(() => setMsg(null), 5000)
      })
      .catch(err => {
        setMsg({ ok: false, text: err.response?.data?.detail || 'Error al fusionar leads.' })
        setTimeout(() => setMsg(null), 5000)
      })
      .finally(() => setMerging(false))
  }

  return (
    <div className="space-y-6 max-w-6xl">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-gray-900 flex items-center gap-2">
            <GitMerge size={18} className="text-indigo-600" />
            Leads duplicados
          </h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Clusters de leads activos con el mismo teléfono. Fusiona el duplicado al lead
            original para preservar el historial — el lead absorbido queda archivado para
            auditoría.
          </p>
        </div>
        {!loading && !error && meta.totalGlobal > 0 && (
          <div className="text-xs text-gray-500 shrink-0 text-right">
            <div>
              Mostrando <span className="font-semibold text-gray-700">{meta.total}</span>
              {' '}de <span className="font-semibold text-gray-700">{meta.totalGlobal}</span> clusters
            </div>
            {meta.capped && (
              <button
                type="button"
                onClick={() => { setLimit(meta.totalGlobal); loadClusters(meta.totalGlobal) }}
                className="text-indigo-600 hover:text-indigo-800 underline underline-offset-2"
              >
                Cargar todos
              </button>
            )}
          </div>
        )}
      </div>

      {msg && (
        <div className={`rounded-lg p-3 text-sm flex items-center gap-2 ${
          msg.ok ? 'bg-green-50 border border-green-200 text-green-800'
                 : 'bg-red-50 border border-red-200 text-red-700'
        }`}>
          {msg.ok ? <CheckCircle size={15} /> : <AlertCircle size={15} />}
          {msg.text}
        </div>
      )}

      {loading && (
        <div className="flex items-center gap-2 text-sm text-gray-500">
          <Loader size={16} className="animate-spin" /> Cargando clusters…
        </div>
      )}

      {!loading && error && (
        <div className="rounded-lg p-3 bg-red-50 border border-red-200 text-red-700 text-sm flex items-center gap-2">
          <AlertCircle size={15} />
          {error}
        </div>
      )}

      {!loading && !error && clusters.length === 0 && (
        <div className="rounded-xl border border-gray-200 bg-gray-50/60 p-8 text-center">
          <CheckCircle size={28} className="text-green-500 mx-auto mb-2" />
          <p className="text-sm font-semibold text-gray-700">No hay duplicados pendientes</p>
          <p className="text-xs text-gray-500 mt-1">
            No se encontraron leads activos con teléfonos repetidos. Todo limpio.
          </p>
        </div>
      )}

      {!loading && !error && clusters.length > 0 && (
        <div className="space-y-3">
          {clusters.map(cluster => (
            <ClusterCard key={cluster.telefono} cluster={cluster} onMerge={openMerge} />
          ))}
        </div>
      )}

      {mergeUI && <MergeDialog ui={mergeUI} onClose={closeMerge} onConfirm={confirmMerge}
                               merging={merging} setDecision={setDecision}
                               setNotes={(n) => setMergeUI(p => ({ ...p, notes: n }))} />}
    </div>
  )
}


function ClusterCard({ cluster, onMerge }) {
  // Por default, el "master sugerido" es el LEAD MAS ANTIGUO del cluster
  // (suele tener mas historial). El admin puede cambiarlo en el modal.
  const sorted = useMemo(
    () => [...cluster.leads].sort((a, b) => new Date(a.created_at) - new Date(b.created_at)),
    [cluster.leads],
  )
  const master = sorted[0]
  const secondaries = sorted.slice(1)

  return (
    <div className="rounded-xl border border-gray-200 bg-white p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Users size={14} className="text-gray-400" />
          <span className="font-mono text-xs text-gray-600">{cluster.telefono}</span>
          <span className="text-xs bg-amber-100 text-amber-800 px-2 py-0.5 rounded-full font-medium">
            {cluster.total} leads
          </span>
        </div>
      </div>

      <div className="space-y-2">
        <LeadRow lead={master} role="master" />
        {secondaries.map(lead => (
          <LeadRow
            key={lead.id}
            lead={lead}
            role="secondary"
            onMerge={() => onMerge(master.id, lead.id)}
          />
        ))}
      </div>
    </div>
  )
}


function LeadRow({ lead, role, onMerge }) {
  const fullName = [lead.nombres, lead.apellidos].filter(Boolean).join(' ') || 'Sin nombre'
  const isMaster = role === 'master'
  return (
    <div className={`flex items-center gap-3 px-3 py-2 rounded-lg ${
      isMaster ? 'bg-emerald-50 border border-emerald-200'
               : 'bg-gray-50 border border-gray-200'
    }`}>
      <div className={`text-xs font-semibold px-1.5 py-0.5 rounded ${
        isMaster ? 'bg-emerald-600 text-white' : 'bg-gray-500 text-white'
      }`}>
        {isMaster ? 'PRINCIPAL' : 'DUPLICADO'}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <a href={`/leads/${lead.id}`} target="_blank" rel="noreferrer"
             className="text-sm font-medium text-gray-900 hover:underline truncate">
            #{lead.id} · {fullName}
          </a>
          {lead.estado_nombre && (
            <span className="text-[11px] text-gray-500">{lead.estado_nombre}</span>
          )}
        </div>
        <div className="text-[11px] text-gray-500 truncate">
          {lead.fuente_nombre ? `${lead.fuente_nombre} · ` : ''}
          {lead.asesor_nombre || 'sin asesor'}
          {lead.email ? ` · ${lead.email}` : ''}
        </div>
      </div>
      {!isMaster && onMerge && (
        <Button size="sm" variant="outline" onClick={onMerge} className="gap-1.5 shrink-0">
          <GitMerge size={13} /> Fusionar
        </Button>
      )}
      {isMaster && (
        <span className="text-[11px] text-emerald-700 shrink-0 flex items-center gap-1">
          <ChevronRight size={12} /> conservar
        </span>
      )}
    </div>
  )
}


function MergeDialog({ ui, onClose, onConfirm, merging, setDecision, setNotes }) {
  // Toggle "solo diferencias" — default true cuando hay campos distintos
  // (patrón estándar pattern: focus on what NEEDS a decision, hide the obvious).
  const [showOnlyDiffs, setShowOnlyDiffs] = useState(true)

  if (ui.loading) {
    return (
      <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
        <div className="bg-white rounded-xl p-6 flex items-center gap-3">
          <Loader size={18} className="animate-spin text-indigo-600" />
          <span className="text-sm text-gray-700">Cargando comparación…</span>
        </div>
      </div>
    )
  }
  const { preview, decisions, masterId, secondaryId, notes } = ui
  const { master, secondary, secondary_counts: counts, mergeable_fields } = preview

  // Set para lookups rapidos (los campos que el backend permite mergear).
  const allowedSet = new Set(mergeable_fields)

  // Computa por campo si difieren — usado para el toggle y el contador.
  const diffMap = {}
  let diffCount = 0
  for (const f of mergeable_fields) {
    const same = formatValue(master, f) === formatValue(secondary, f)
    diffMap[f] = !same
    if (!same) diffCount++
  }

  // Construye los grupos a renderizar respetando FIELD_GROUPS + filtrando
  // por whitelist del backend + (opcional) solo diferencias.
  const groupsToRender = FIELD_GROUPS
    .map(g => ({
      label:  g.label,
      fields: g.fields.filter(f =>
        allowedSet.has(f) && (!showOnlyDiffs || diffMap[f]),
      ),
    }))
    .filter(g => g.fields.length > 0)

  return (
    <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-xl max-w-4xl w-full max-h-[90vh] overflow-hidden flex flex-col">
        <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200">
          <div className="flex items-center gap-2">
            <GitMerge size={16} className="text-indigo-600" />
            <h3 className="text-sm font-semibold text-gray-900">
              Fusionar lead #{secondaryId} → #{masterId}
            </h3>
          </div>
          <button onClick={onClose} className="p-1 hover:bg-gray-100 rounded">
            <XIcon size={16} className="text-gray-500" />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-4">
          <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-800">
            <p className="font-semibold mb-1">Lo que va a pasar</p>
            <ul className="space-y-0.5 list-disc list-inside">
              <li>El lead <strong>#{masterId}</strong> conservará su id y todo su historial.</li>
              <li>El lead <strong>#{secondaryId}</strong> quedará archivado (activo=FALSE) y apuntará al principal.</li>
              <li>Se migrarán al principal: {counts.contactos_migrated} contactos · {counts.llamadas_migrated} llamadas · {counts.recontactos_migrated} recontactos · {counts.submissions_migrated} envíos · {counts.tags_migrated} tags.</li>
              <li>Para cada campo, marca si conservar el valor del principal o tomar el del duplicado.</li>
            </ul>
          </div>

          {/* Toggle "solo diferencias" — patron estandar.
              V067.3: barra propia con separador inferior. Antes `-mb-1`
              causaba que el checkbox se montara visualmente encima del
              header "DUPLICADO #xxx" del grid de abajo. */}
          <div className="flex items-center justify-between gap-3 pb-2 border-b border-gray-100">
            <div className="text-[11px] text-gray-500">
              {diffCount === 0
                ? 'Los dos leads son idénticos en todos los campos editables.'
                : `${diffCount} campo${diffCount !== 1 ? 's' : ''} difiere${diffCount !== 1 ? 'n' : ''} entre principal y duplicado.`}
            </div>
            {diffCount > 0 && (
              <label className="flex items-center gap-1.5 text-xs text-gray-700 cursor-pointer select-none whitespace-nowrap shrink-0">
                <input
                  type="checkbox"
                  checked={showOnlyDiffs}
                  onChange={e => setShowOnlyDiffs(e.target.checked)}
                  className="w-3.5 h-3.5 accent-indigo-600"
                />
                Solo diferencias
              </label>
            )}
          </div>

          {/* Tabla 3 columnas: label / principal / duplicado */}
          <div className="grid grid-cols-[140px_1fr_1fr] gap-x-2 text-xs">
            <div></div>
            <div className="font-semibold text-emerald-700 bg-emerald-50 px-2 py-1 rounded">
              PRINCIPAL #{master.id}
            </div>
            <div className="font-semibold text-gray-700 bg-gray-100 px-2 py-1 rounded">
              DUPLICADO #{secondary.id}
            </div>

            {groupsToRender.length === 0 && (
              <div className="col-span-3 text-center text-xs text-gray-400 py-6">
                No hay diferencias que decidir. Confirmá para archivar el duplicado.
              </div>
            )}

            {groupsToRender.map((group, gi) => (
              <Fragment key={group.label}>
                <div className={`col-span-3 ${gi > 0 ? 'mt-3' : 'mt-1'} mb-0.5
                                 text-[10px] font-semibold uppercase tracking-wider text-gray-400`}>
                  {group.label}
                </div>
                {group.fields.map(field => {
                  const mVal = formatValue(master, field)
                  const sVal = formatValue(secondary, field)
                  const same = !diffMap[field]
                  const choice = decisions[field] || 'master'
                  return (
                    <FieldRow key={field} field={field} mVal={mVal} sVal={sVal}
                              same={same} choice={choice} onChoose={setDecision} />
                  )
                })}
              </Fragment>
            ))}
          </div>

          <div>
            <label className="text-xs font-semibold text-gray-700">Nota (opcional)</label>
            <textarea
              // V067.4: defensa total contra el bug del "null" visible:
              // 1) `?? ''` cubre los valores reales null/undefined.
              // 2) Filtro contra el string literal "null"/"undefined" — algunos
              //    browsers/extensions hacen autofill con valores antiguos
              //    o stringifican null en restore-form, dejando esos literales
              //    en el textarea.
              // 3) autoComplete=off + name unico desactiva la sugerencia
              //    automatica del browser para este campo.
              value={(() => {
                const v = notes ?? ''
                return (v === 'null' || v === 'undefined') ? '' : v
              })()}
              onChange={e => setNotes(e.target.value)}
              maxLength={2000}
              rows={2}
              name="merge-notes"
              autoComplete="off"
              placeholder="Por qué hiciste este merge (queda en el audit log)…"
              className="mt-1 w-full text-sm border border-gray-200 rounded-md px-3 py-2 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
          </div>
        </div>

        <div className="px-5 py-3 border-t border-gray-200 flex justify-end gap-2">
          <Button variant="outline" onClick={onClose} disabled={merging}>Cancelar</Button>
          <Button onClick={onConfirm} disabled={merging} className="gap-1.5">
            {merging ? <Loader size={14} className="animate-spin" /> : <GitMerge size={14} />}
            {merging ? 'Fusionando…' : 'Confirmar fusión'}
          </Button>
        </div>
      </div>
    </div>
  )
}


function FieldRow({ field, mVal, sVal, same, choice, onChoose }) {
  const label = FIELD_LABELS[field] || field
  return (
    <>
      <div className="text-gray-600 font-medium pt-1.5">{label}</div>
      <button
        type="button"
        onClick={() => onChoose(field, 'master')}
        className={`text-left px-2 py-1.5 rounded border ${
          choice === 'master'
            ? 'bg-emerald-50 border-emerald-300 ring-1 ring-emerald-300'
            : 'bg-white border-gray-200 hover:bg-gray-50'
        } ${same ? 'opacity-60' : ''}`}
      >
        <span className="truncate block text-gray-800">{mVal || <em className="text-gray-300">vacío</em>}</span>
      </button>
      <button
        type="button"
        onClick={() => onChoose(field, 'secondary')}
        disabled={same}
        className={`text-left px-2 py-1.5 rounded border ${
          choice === 'secondary'
            ? 'bg-blue-50 border-blue-300 ring-1 ring-blue-300'
            : 'bg-white border-gray-200 hover:bg-gray-50'
        } ${same ? 'opacity-60 cursor-not-allowed' : ''}`}
      >
        <span className="truncate block text-gray-800">{sVal || <em className="text-gray-300">vacío</em>}</span>
      </button>
    </>
  )
}


function formatValue(lead, field) {
  // Para campos FK mostramos el nombre resuelto si esta disponible
  const resolvedKey = RESOLVED_FIELD[field]
  if (resolvedKey && lead[resolvedKey] != null) return String(lead[resolvedKey])
  const v = lead[field]
  if (v == null || v === '') return ''
  if (typeof v === 'object') return JSON.stringify(v)
  return String(v)
}
