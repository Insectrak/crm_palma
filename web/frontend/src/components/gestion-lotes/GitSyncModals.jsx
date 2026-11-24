import React from 'react'
import {
  GitPullRequest,
  GitCommit,
  Settings,
  X,
  Check,
  ChevronDown,
  ChevronRight,
} from 'lucide-react'

export function formatDateTimeLima(iso) {
  if (!iso) return '—'
  try {
    const d = new Date(iso)
    if (Number.isNaN(d.getTime())) return '—'
    return d.toLocaleString('es-PE', {
      timeZone: 'America/Lima',
      day: '2-digit',
      month: '2-digit',
      year: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    })
  } catch {
    return '—'
  }
}

export function GitDiffModal({
  pendingRevision,
  diffFilter,
  setDiffFilter,
  diffChanges,
  selectedDiffKeys,
  setSelectedDiffKeys,
  commitMsg,
  setCommitMsg,
  approving,
  onApprove,
  onReject,
  onClose,
  renderAddedSummary,
}) {
  if (!pendingRevision) return null
  const isExcel = pendingRevision.source === 'excel_upload'
  const originLabel = isExcel ? 'Archivo Excel' : 'Google Drive'

  return (
    <div className="fixed inset-0 z-50 bg-slate-950/60 backdrop-blur-xs flex items-center justify-center p-4">
      <div className="bg-white dark:bg-[#121a29] rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl w-full max-w-4xl max-h-[90vh] flex flex-col overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between gap-3">
          <div>
            <h3 className="text-base font-bold flex items-center gap-2">
              <GitPullRequest size={18} className="text-indigo-600" />
              Comparativo Git: {originLabel} vs. Servidor CRM (Rev #{pendingRevision.revision_number})
            </h3>
            <p className="text-xs text-slate-500 mt-0.5">
              Marca o desmarca qué cambios deseas fusionar al servidor. Los registros creados manualmente en el CRM nunca se eliminan.
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 cursor-pointer"
          >
            <X size={18} />
          </button>
        </div>

        <div className="px-5 py-2.5 border-b border-slate-100 dark:border-slate-800 flex flex-wrap items-center justify-between gap-2 bg-slate-50 dark:bg-[#0e1522] text-xs">
          <div className="flex items-center gap-1.5 flex-wrap">
            {[
              { id: 'todos', label: `Todos (${(pendingRevision.diff_json || []).length})` },
              { id: 'added', label: `+ Nuevos (${pendingRevision.summary_json?.added ?? 0})` },
              { id: 'modified', label: `~ Modificados (${pendingRevision.summary_json?.modified ?? 0})` },
              { id: 'removed', label: `- Quitados (${pendingRevision.summary_json?.removed ?? 0})` },
            ].map((f) => (
              <button
                key={f.id}
                type="button"
                onClick={() => setDiffFilter(f.id)}
                className={`px-2.5 py-1 rounded-lg font-semibold cursor-pointer ${
                  diffFilter === f.id
                    ? 'bg-slate-900 text-white dark:bg-white dark:text-slate-900'
                    : 'text-slate-600 dark:text-slate-300 hover:bg-slate-200/60'
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={() => setSelectedDiffKeys(new Set((pendingRevision.diff_json || []).map((c) => c.sync_key)))}
              className="font-semibold text-indigo-600 hover:underline cursor-pointer"
            >
              Seleccionar todo
            </button>
            <button
              type="button"
              onClick={() => setSelectedDiffKeys(new Set())}
              className="font-semibold text-slate-500 hover:underline cursor-pointer"
            >
              Limpiar
            </button>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-2.5">
          {diffChanges.map((item) => {
            const checked = selectedDiffKeys.has(item.sync_key)
            const isAdd = item.change_type === 'added'
            const isMod = item.change_type === 'modified'
            return (
              <label
                key={item.sync_key}
                className={`block p-3 rounded-xl border cursor-pointer transition-all ${
                  isAdd
                    ? 'border-emerald-200 bg-emerald-50/40 dark:bg-emerald-950/20'
                    : isMod
                      ? 'border-amber-200 bg-amber-50/40 dark:bg-amber-950/20'
                      : 'border-rose-200 bg-rose-50/40 dark:bg-rose-950/20'
                }`}
              >
                <div className="flex items-start gap-3">
                  <input
                    type="checkbox"
                    checked={checked}
                    onChange={() => {
                      const next = new Set(selectedDiffKeys)
                      if (next.has(item.sync_key)) next.delete(item.sync_key)
                      else next.add(item.sync_key)
                      setSelectedDiffKeys(next)
                    }}
                    className="mt-1"
                  />
                  <div className="flex-1 text-xs space-y-1.5">
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-bold text-slate-900 dark:text-white">{item.label}</span>
                      <span
                        className={`text-[10px] font-extrabold uppercase px-2 py-0.5 rounded ${
                          isAdd
                            ? 'bg-emerald-100 text-emerald-800'
                            : isMod
                              ? 'bg-amber-200 text-amber-900'
                              : 'bg-rose-100 text-rose-800'
                        }`}
                      >
                        {isAdd ? `+ Nuevo (${originLabel})` : isMod ? '~ Modificado' : `- Quitados (${originLabel})`}
                      </span>
                    </div>

                    {isAdd && item.after && (
                      <div className="text-[11px] text-emerald-900 dark:text-emerald-200 font-mono bg-white/80 dark:bg-slate-900/60 p-2 rounded-lg border border-emerald-200/70">
                        {renderAddedSummary(item.after)}
                      </div>
                    )}

                    {isMod && (item.changed_fields || []).length > 0 && (
                      <div className="space-y-1 font-mono text-[11px]">
                        {item.changed_fields.map((cf) => (
                          <div key={cf.field} className="bg-white/90 dark:bg-slate-900/60 p-1.5 rounded border border-amber-200/60 flex flex-wrap items-center gap-2">
                            <span className="font-sans font-bold text-slate-600 dark:text-slate-300">{cf.label}:</span>
                            <span className="px-1.5 py-0.5 rounded bg-rose-100 text-rose-800 line-through">
                              - {cf.before || 'vacío'}
                            </span>
                            <span className="px-1.5 py-0.5 rounded bg-emerald-100 text-emerald-800 font-bold">
                              + {cf.after || 'vacío'}
                            </span>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              </label>
            )
          })}
        </div>

        <div className="px-5 py-4 border-t border-slate-200 dark:border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-3 bg-slate-50 dark:bg-[#0e1522]">
          <input
            type="text"
            value={commitMsg}
            onChange={(e) => setCommitMsg(e.target.value)}
            placeholder="Nota o comentario de esta versión..."
            className="flex-1 text-xs px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-white dark:bg-[#0c121d]"
          />
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onReject}
              disabled={approving}
              className="px-3.5 py-2 rounded-xl text-xs font-bold border border-rose-200 text-rose-700 hover:bg-rose-50 cursor-pointer disabled:opacity-50"
            >
              Descartar
            </button>
            <button
              type="button"
              onClick={onApprove}
              disabled={approving || selectedDiffKeys.size === 0}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-bold bg-emerald-600 hover:bg-emerald-700 text-white shadow-sm cursor-pointer disabled:opacity-50"
            >
              <Check size={14} />
              <span>{approving ? 'Guardando…' : `Aprobar (${selectedDiffKeys.size}) en Servidor`}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

export function GitRevisionsModal({
  title = 'Historial de Versiones (Commits en Servidor)',
  loadingHistory,
  revisions,
  expandedRevId,
  setExpandedRevId,
  onClose,
}) {
  return (
    <div className="fixed inset-0 z-50 bg-slate-950/60 backdrop-blur-xs flex items-center justify-center p-4">
      <div className="bg-white dark:bg-[#121a29] rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl w-full max-w-3xl max-h-[88vh] flex flex-col overflow-hidden">
        <div className="px-5 py-4 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between">
          <h3 className="text-base font-bold flex items-center gap-2">
            <GitCommit size={18} className="text-purple-600" />
            {title}
          </h3>
          <button type="button" onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 cursor-pointer">
            <X size={18} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-5 space-y-3">
          {loadingHistory ? (
            <p className="text-xs text-slate-500 text-center py-8">Cargando historial...</p>
          ) : revisions.length === 0 ? (
            <p className="text-xs text-slate-500 text-center py-8">Aún no hay versiones registradas.</p>
          ) : (
            revisions.map((rev) => {
              const isOpen = expandedRevId === rev.id
              const sm = rev.summary_json || {}
              const sourceLabel =
                rev.source === 'excel_upload'
                  ? 'Excel Upload'
                  : rev.source === 'drive_initial'
                    ? 'Importación Drive'
                    : rev.source === 'drive_sync'
                      ? 'Sync Drive'
                      : 'CRM Manual'
              return (
                <div key={rev.id} className="border border-slate-200 dark:border-slate-800 rounded-xl p-3.5 text-xs space-y-2">
                  <div className="flex items-start justify-between gap-2">
                    <button
                      type="button"
                      onClick={() => setExpandedRevId(isOpen ? null : rev.id)}
                      className="flex items-start gap-2 text-left flex-1 cursor-pointer"
                    >
                      {isOpen ? <ChevronDown size={15} className="mt-0.5 text-slate-400" /> : <ChevronRight size={15} className="mt-0.5 text-slate-400" />}
                      <div>
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-mono font-bold text-purple-700 dark:text-purple-300">
                            v{rev.revision_number}
                          </span>
                          <span className="font-bold text-slate-900 dark:text-white">{rev.message}</span>
                        </div>
                        <p className="text-[11px] text-slate-500 mt-0.5">
                          Por <strong>{rev.reviewed_by_name || rev.created_by_name || 'Sistema'}</strong> · {formatDateTimeLima(rev.reviewed_at || rev.created_at)}
                        </p>
                      </div>
                    </button>
                    <div className="flex items-center gap-1.5 shrink-0 flex-wrap justify-end">
                      <span className="px-2 py-0.5 rounded bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300 text-[10px] font-bold">
                        {sourceLabel}
                      </span>
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                          rev.status === 'pending'
                            ? 'bg-amber-100 text-amber-800'
                            : rev.status === 'rejected'
                              ? 'bg-rose-100 text-rose-800'
                              : 'bg-emerald-100 text-emerald-800'
                        }`}
                      >
                        {rev.status}
                      </span>
                      {(sm.added > 0 || sm.modified > 0 || sm.removed > 0) && (
                        <span className="text-[10px] font-mono text-slate-600 dark:text-slate-300">
                          +{sm.added || 0} / ~{sm.modified || 0} / -{sm.removed || 0}
                        </span>
                      )}
                    </div>
                  </div>

                  {isOpen && Array.isArray(rev.diff_json) && rev.diff_json.length > 0 && (
                    <div className="pl-6 pt-2 border-t border-slate-100 dark:border-slate-800 space-y-1 max-h-56 overflow-y-auto">
                      {rev.diff_json.map((d, idx) => (
                        <div key={`${d.sync_key}-${idx}`} className="text-[11px] font-mono text-slate-600 dark:text-slate-300">
                          <span className={d.change_type === 'added' ? 'text-emerald-600 font-bold' : d.change_type === 'modified' ? 'text-amber-600 font-bold' : 'text-rose-600 font-bold'}>
                            {d.change_type === 'added' ? '+' : d.change_type === 'modified' ? '~' : '-'}
                          </span>{' '}
                          {d.label}
                          {d.changed_fields?.length > 0 && (
                            <span className="text-slate-400">
                              {' '}
                              ({d.changed_fields.map((cf) => `${cf.label}: ${cf.before || '∅'} → ${cf.after || '∅'}`).join(' · ')})
                            </span>
                          )}
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })
          )}
        </div>
      </div>
    </div>
  )
}

export function DriveConfigModal({
  title = 'Configurar Google Drive de Origen',
  sheetUrl,
  setSheetUrl,
  saving,
  onSave,
  onClose,
}) {
  return (
    <div className="fixed inset-0 z-50 bg-slate-950/60 backdrop-blur-xs flex items-center justify-center p-4">
      <form
        onSubmit={onSave}
        className="bg-white dark:bg-[#121a29] rounded-2xl border border-slate-200 dark:border-slate-800 shadow-2xl w-full max-w-lg p-5 space-y-4"
      >
        <div className="flex items-center justify-between">
          <h3 className="text-base font-bold flex items-center gap-2">
            <Settings size={17} className="text-indigo-600" />
            {title}
          </h3>
          <button type="button" onClick={onClose} className="p-1.5 rounded-lg hover:bg-slate-100 cursor-pointer">
            <X size={18} />
          </button>
        </div>

        <div>
          <label className="block text-xs font-bold text-slate-600 mb-1">URL de Google Sheets</label>
          <input
            type="url"
            required
            value={sheetUrl}
            onChange={(e) => setSheetUrl(e.target.value)}
            placeholder="https://docs.google.com/spreadsheets/d/..."
            className="w-full text-xs px-3 py-2 rounded-xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-[#0c121d]"
          />
          <p className="text-[11px] text-slate-500 mt-1.5">
            El CRM detectará automáticamente diferencias cuando este Google Sheet sea accesible con lectura pública/enlace, o puedes subir cualquier archivo <code>.xlsx</code> / <code>.csv</code> descargado usando <strong>Subir Excel</strong>.
          </p>
        </div>

        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="px-4 py-2 rounded-xl text-xs font-semibold border border-slate-200 cursor-pointer">
            Cancelar
          </button>
          <button
            type="submit"
            disabled={saving}
            className="px-4 py-2 rounded-xl text-xs font-bold bg-indigo-600 hover:bg-indigo-700 text-white cursor-pointer disabled:opacity-50"
          >
            {saving ? 'Guardando…' : 'Guardar URL'}
          </button>
        </div>
      </form>
    </div>
  )
}
