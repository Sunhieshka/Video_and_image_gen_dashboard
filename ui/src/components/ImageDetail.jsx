import { useEffect, useState } from 'react'
import { StatusPill } from './Common.jsx'
import { getImage, money } from '../api.js'

const FIELDS = [
  ['model', 'Model'], ['size', 'Requested size'], ['output_format', 'Format'],
  ['seed', 'Seed'], ['watermark', 'Watermark'],
  ['generated_images', 'Images out'], ['input_images', 'Images in'],
  ['output_tokens', 'Output tokens'], ['total_tokens', 'Total tokens'],
  ['output_rate_usd', 'Rate per image'], ['output_cost_usd', 'Output cost'],
  ['input_cost_usd', 'Input cost'], ['cost_basis', 'Cost basis'],
  ['latency_ms', 'Latency (ms)'], ['pricing_version', 'Pricing version'],
]

export default function ImageDetail({ taskId, onClose }) {
  const [task, setTask] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    getImage(taskId).then(setTask).catch((e) => setError(e.message))
  }, [taskId])

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center
                    overflow-y-auto bg-black/70 p-6" onClick={onClose}>
      <div className="card w-full max-w-3xl p-6 space-y-5"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between">
          <div>
            <h2 className="font-mono text-sm text-slate-300">{taskId}</h2>
            {task && <div className="mt-2"><StatusPill status={task.status} /></div>}
          </div>
          <button onClick={onClose}
                  className="rounded-lg px-3 py-1 text-slate-400 hover:bg-ink-800">✕</button>
        </div>

        {error && <p className="text-sm text-rose-400">{error}</p>}
        {!task && !error && <p className="text-sm text-slate-500">Loading…</p>}

        {task && (
          <>
            {task.outputs?.length > 0 && (
              <div className="grid grid-cols-2 gap-3">
                {task.outputs.map((o) => (
                  <a key={o.position} href={o.url} target="_blank" rel="noreferrer"
                     className="group block">
                    <img src={o.url} alt=""
                         className="w-full rounded-lg border border-ink-700 bg-black" />
                    <div className="mt-1 flex justify-between text-xs text-slate-500">
                      <span>{o.size}</span>
                      <span>{o.rate_usd != null ? `$${o.rate_usd.toFixed(3)}` : ''}</span>
                    </div>
                  </a>
                ))}
              </div>
            )}

            {task.prompt && (
              <div>
                <div className="label">Prompt</div>
                <p className="rounded-lg bg-ink-850 p-3 text-sm text-slate-300">
                  {task.prompt}
                </p>
              </div>
            )}

            <div className="flex justify-between border-b border-ink-700 pb-2">
              <span className="text-sm text-slate-400">Price (USD)</span>
              <span className="text-lg font-semibold text-indigo-400">
                {task.cost_is_estimate ? '~' : ''}{money(task.estimated_cost_usd)}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-x-6 sm:grid-cols-3">
              {FIELDS.map(([key, label]) =>
                task[key] === null || task[key] === undefined ? null : (
                  <div key={key} className="py-1.5">
                    <div className="text-xs text-slate-500">{label}</div>
                    <div className="truncate text-sm text-slate-200">
                      {String(task[key])}
                    </div>
                  </div>
                ),
              )}
            </div>

            {task.cost_note && (
              <p className="rounded-md bg-ink-850 px-3 py-2 text-xs text-slate-500">
                {task.cost_note}
              </p>
            )}

            {task.error_message && (
              <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3">
                <p className="text-sm text-rose-300">{task.error_code}</p>
                <p className="mt-1 text-xs text-rose-400/80">{task.error_message}</p>
              </div>
            )}

            {task.inputs?.length > 0 && (
              <div>
                <div className="label">Input images ({task.inputs.length})</div>
                <div className="space-y-1">
                  {task.inputs.map((r) => (
                    <div key={r.position}
                         className="flex items-center gap-2 rounded-md bg-ink-850
                                    px-3 py-1.5 text-xs">
                      <span className={`rounded px-1.5 py-0.5 ${r.billable
                        ? 'bg-ink-700 text-slate-300' : 'bg-emerald-500/15 text-emerald-400'}`}>
                        {r.billable ? 'billed' : 'free'}
                      </span>
                      <a href={r.url} target="_blank" rel="noreferrer"
                         className="truncate text-indigo-400 hover:underline">{r.url}</a>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
