import { useEffect, useState } from 'react'
import { StatusPill, Stat, Empty, ErrorNote } from './Common.jsx'
import { listImages, money, formatWhen } from '../api.js'
import KindTabs from './KindTabs.jsx'
import ImageDetail from './ImageDetail.jsx'

const EMPTY_FILTERS = { status: '', model: '', size: '', search: '' }

export default function ImageTable({ onKindChange }) {
  const [filters, setFilters] = useState(EMPTY_FILTERS)
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  const [selected, setSelected] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    const load = () =>
      listImages(filters)
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
  const options = data?.filter_options || { statuses: [], models: [], sizes: [] }

  return (
    <div className="space-y-5">
      <KindTabs kind="image" onChange={onKindChange} />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label={active ? 'Total price (filtered)' : 'Total price (USD)'}
              value={money(totals?.cost_usd)} accent
              sub="priced per image" />
        <Stat label="Requests" value={totals?.tasks ?? '—'}
              sub={totals ? `${totals.succeeded} succeeded · ${totals.failed} failed` : null} />
        <Stat label="Images" value={totals?.images ?? '—'} />
        <Stat label="Average price"
              value={totals?.images ? money(totals.cost_usd / totals.images) : '—'}
              sub="per image" />
      </div>

      <div className="card p-4">
        <div className="flex flex-wrap items-end gap-3">
          <div className="min-w-56 flex-1">
            <label className="label">Search</label>
            <input className="field" placeholder="prompt or id…"
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
            <select className="field w-64" value={filters.model}
                    onChange={(e) => set({ model: e.target.value })}>
              <option value="">All</option>
              {options.models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <div>
            <label className="label">Size</label>
            <select className="field w-28" value={filters.size}
                    onChange={(e) => set({ size: e.target.value })}>
              <option value="">All</option>
              {options.sizes.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>
          {active && (
            <button onClick={() => setFilters(EMPTY_FILTERS)}
                    className="btn-ghost h-10">Clear</button>
          )}
        </div>
      </div>

      <ErrorNote>{error}</ErrorNote>

      <div className="card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-ink-700 text-left text-xs uppercase
                             tracking-wider text-slate-400">
                <th className="px-4 py-3 font-medium">Preview</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Prompt</th>
                <th className="px-4 py-3 font-medium">Model</th>
                <th className="px-4 py-3 font-medium">Size</th>
                <th className="px-4 py-3 text-right font-medium">Images</th>
                <th className="px-4 py-3 text-right font-medium">Rate</th>
                <th className="px-4 py-3 text-right font-medium">Price (USD)</th>
                <th className="px-4 py-3 font-medium">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-ink-800">
              {(data?.tasks || []).map((t) => (
                <tr key={t.id} onClick={() => setSelected(t.id)}
                    className="cursor-pointer transition hover:bg-ink-850">
                  <td className="px-4 py-2">
                    {t.outputs?.[0]?.url ? (
                      <img src={t.outputs[0].url} alt=""
                           className="h-10 w-10 rounded object-cover"
                           onError={(e) => { e.currentTarget.style.visibility = 'hidden' }} />
                    ) : <span className="text-slate-600">—</span>}
                  </td>
                  <td className="px-4 py-3"><StatusPill status={t.status} /></td>
                  <td className="max-w-xs truncate px-4 py-3 text-slate-300">
                    {t.prompt || '—'}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-400">{t.model || '—'}</td>
                  <td className="px-4 py-3 text-xs text-slate-400">
                    {t.size || '—'}
                    {t.outputs?.[0]?.size && (
                      <span className="block text-slate-600">{t.outputs[0].size}</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-slate-400">
                    {t.generated_images ?? '—'}
                    {t.input_images ? (
                      <span className="block text-xs text-slate-600">
                        +{t.input_images} in
                      </span>
                    ) : null}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-slate-500">
                    {t.output_rate_usd != null
                      ? `$${t.output_rate_usd.toFixed(3)}` : '—'}
                  </td>
                  <td className="px-4 py-3 text-right tabular-nums text-indigo-400">
                    {t.cost_is_estimate ? '~' : ''}{money(t.estimated_cost_usd)}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {formatWhen(t.created || t.created_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {!loading && data?.tasks?.length === 0 && (
          <Empty>
            {active ? 'No images match these filters.'
                    : 'No images yet. Switch to Generate to create one.'}
          </Empty>
        )}
        {loading && <Empty>Loading…</Empty>}
      </div>

      {selected && (
        <ImageDetail taskId={selected} onClose={() => setSelected(null)} />
      )}
    </div>
  )
}
