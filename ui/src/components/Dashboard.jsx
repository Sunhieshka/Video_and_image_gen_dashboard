import { useEffect, useState } from 'react'
import { StatusPill, Stat, Empty, ErrorNote } from './Common.jsx'
import { listTasks, money, formatWhen } from '../api.js'
import ImageTable from './ImageTable.jsx'
import KindTabs from './KindTabs.jsx'
import TaskDetail from './TaskDetail.jsx'

const EMPTY_FILTERS = {
  status: '', model: '', resolution: '', search: '',
}

export default function Dashboard({ kind, onKindChange }) {
  if (kind === 'image') return <ImageTable onKindChange={onKindChange} />
  return <VideoTable onKindChange={onKindChange} />
}

function VideoTable({ onKindChange }) {
  const [filters, setFilters] = useState(EMPTY_FILTERS)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(true)

  // Refetch on filter change, and poll so in-flight generations update here.
  useEffect(() => {
    let cancelled = false
    const load = () =>
      listTasks(filters)
        .then((d) => { if (!cancelled) { setData(d); setError(null) } })
        .catch((e) => { if (!cancelled) setError(e.message) })
        .finally(() => { if (!cancelled) setLoading(false) })

    load()
    const id = setInterval(load, 5000)
    return () => { cancelled = true; clearInterval(id) }
  }, [filters])

  const set = (patch) => setFilters((f) => ({ ...f, ...patch }))
  const active = JSON.stringify(filters) !== JSON.stringify(EMPTY_FILTERS)
  const totals = data?.totals
  const options = data?.filter_options || { statuses: [], models: [], resolutions: [] }

  return (
    <div className="space-y-5">
      <KindTabs kind="video" onChange={onKindChange} />

      {/* Totals -- these reflect the current filter, not the whole table. */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat
          label={active ? 'Total price (filtered)' : 'Total price (USD)'}
          value={money(totals?.cost_usd)}
          accent
          sub={totals?.estimated_rows
            ? `${totals.estimated_rows} still projected`
            : 'billed on token usage'}
        />
        <Stat label="Generations" value={totals?.tasks ?? '—'}
              sub={totals ? `${totals.succeeded} succeeded · ${totals.failed} failed` : null} />
        <Stat label="Tokens" value={totals?.tokens?.toLocaleString() ?? '—'} />
        <Stat
          label="Average price"
          value={totals?.tasks ? money(totals.cost_usd / totals.tasks) : '—'}
          sub="per generation"
        />
      </div>

      {/* Filters --------------------------------------------------------- */}
      <div className="card p-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-56 flex-1">
            <label className="label">Search</label>
            <input className="field" placeholder="prompt or task id…"
                   value={filters.search}
                   onChange={(e) => set({ search: e.target.value })} />
          </div>
          <div>
            <label className="label">Status</label>
            <select className="field w-36" value={filters.status}
                    onChange={(e) => set({ status: e.target.value })}>
              <option value="">All</option>
              {options.statuses.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Model</label>
            <select className="field w-60" value={filters.model}
                    onChange={(e) => set({ model: e.target.value })}>
              <option value="">All</option>
              {options.models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Resolution</label>
            <select className="field w-32" value={filters.resolution}
                    onChange={(e) => set({ resolution: e.target.value })}>
              <option value="">All</option>
              {options.resolutions.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </div>
          {active && (
            <button onClick={() => setFilters(EMPTY_FILTERS)}
                    className="btn-ghost h-10">Clear</button>
          )}
        </div>
      </div>

      <ErrorNote>{error}</ErrorNote>

      {/* Table ----------------------------------------------------------- */}
      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-ink-700 text-left text-xs uppercase
                             tracking-wider text-slate-400">
                <th className="px-4 py-3 font-medium">Task</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Prompt</th>
                <th className="px-4 py-3 font-medium">Model</th>
                <th className="px-4 py-3 font-medium">Config</th>
                <th className="px-4 py-3 text-right font-medium">Tokens</th>
                <th className="px-4 py-3 text-right font-medium">Price (USD)</th>
                <th className="px-4 py-3 font-medium">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-800">
              {(data?.tasks || []).map((t) => (
                <tr key={t.id} onClick={() => setSelected(t.id)}
                    className="cursor-pointer transition hover:bg-ink-850">
                  <td className="px-4 py-3 font-mono text-xs text-slate-400">
                    {t.id}
                  </td>
                  <td className="px-4 py-3"><StatusPill status={t.status} /></td>
                  <td className="max-w-xs truncate px-4 py-3 text-slate-300">
                    {t.prompt || '—'}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-400">{t.model || '—'}</td>
                  <td className="px-4 py-3 text-xs text-slate-400">
                    {[t.resolution, t.ratio, t.duration && `${t.duration}s`]
                      .filter(Boolean).join(' · ') || '—'}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-slate-400">
                    {t.total_tokens ? t.total_tokens.toLocaleString() : '—'}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-indigo-400">
                    {t.cost_is_estimate ? '~' : ''}{money(t.estimated_cost_usd)}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {formatWhen(t.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {!loading && data?.tasks?.length === 0 && (
          <Empty>
            {active
              ? 'No generations match these filters.'
              : 'No generations yet. Switch to Generate to create one.'}
          </Empty>
        )}
        {loading && <Empty>Loading…</Empty>}
      </div>

      {selected && (
        <TaskDetail taskId={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  )
}
