import { useEffect, useState } from 'react'
import { StatusPill } from './Common.jsx'
import { getTask, money } from '../api.js'

// Fields worth showing individually; everything else is in the raw JSON block.
const DETAIL_FIELDS = [
  ['model', 'Model'], ['resolution', 'Resolution'], ['ratio', 'Ratio'],
  ['duration', 'Duration (s)'], ['framespersecond', 'FPS'], ['frames', 'Frames'],
  ['seed', 'Seed'], ['generate_audio', 'Audio'], ['service_tier', 'Tier'],
  ['fileformat', 'File format'], ['total_tokens', 'Tokens'],
  ['unit_price_per_million_usd', 'Unit price / 1M tokens'],
  ['cost_basis', 'Cost basis'], ['pricing_version', 'Pricing version'],
  ['poll_count', 'Polls'], ['local_path', 'Local file'],
]

// raw_response is whatever the API stored; never let a bad parse break the view.
function prettyJson(text) {
  try {
    return JSON.stringify(JSON.parse(text || '{}'), null, 2)
  } catch {
    return text || '(empty)'
  }
}

export default function TaskDetail({ taskId, onClose }) {
  const [task, setTask] = useState(null)
  const [error, setError] = useState(null)
  const [showRaw, setShowRaw] = useState(false)

  useEffect(() => {
    getTask(taskId).then(setTask).catch((e) => setError(e.message))
  }, [taskId])

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center
                    overflow-y-auto bg-black/70 p-6"
         onClick={onClose}>
      <div className="card w-full max-w-3xl p-6 space-y-5"
           onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between">
          <div>
            <h2 className="font-mono text-sm text-slate-300">{taskId}</h2>
            {task && <div className="mt-2"><StatusPill status={task.status} /></div>}
          </div>
          <button onClick={onClose}
                  className="rounded-lg px-3 py-1 text-slate-400 hover:bg-ink-800">
            ✕
          </button>
        </div>

        {error && <p className="text-sm text-rose-400">{error}</p>}
        {!task && !error && <p className="text-sm text-slate-500">Loading…</p>}

        {task && (
          <>
            {task.video_url && (
              <video src={task.video_url} controls
                     className="w-full rounded-lg border border-ink-700 bg-black" />
            )}

            {task.prompt && (
              <div>
                <div className="label">Prompt</div>
                <p className="rounded-lg bg-ink-850 p-3 text-sm text-slate-300">
                  {task.prompt}
                </p>
              </div>
            )}

            <div className="grid grid-cols-2 gap-x-6 sm:grid-cols-3">
              <div className="col-span-2 mb-1 sm:col-span-3">
                <div className="flex justify-between border-b border-ink-700 pb-2">
                  <span className="text-sm text-slate-400">
                    {task.cost_is_estimate ? 'Estimated price (USD)' : 'Price (USD)'}
                  </span>
                  <span className="text-lg font-semibold text-indigo-400">
                    {task.cost_is_estimate ? '~' : ''}
                    {money(task.estimated_cost_usd)}
                  </span>
                </div>
              </div>
              {DETAIL_FIELDS.map(([key, label]) =>
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
              <p className="rounded-md bg-amber-500/10 px-3 py-2 text-xs
                            text-amber-300/90">
                {task.cost_note}
              </p>
            )}

            {task.error_message && (
              <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3">
                <p className="text-sm text-rose-300">{task.error_code}</p>
                <p className="mt-1 text-xs text-rose-400/80">{task.error_message}</p>
              </div>
            )}

            {task.references?.length > 0 && (
              <div>
                <div className="label">Reference media ({task.references.length})</div>
                <div className="space-y-1">
                  {task.references.map((r) => (
                    <div key={r.position}
                         className="flex items-center gap-2 rounded-md bg-ink-850
                                    px-3 py-1.5 text-xs">
                      <span className="rounded bg-ink-700 px-1.5 py-0.5 text-slate-300">
                        {r.ref_type.replace('_url', '')}
                      </span>
                      <span className="text-slate-500">{r.role}</span>
                      <a href={r.url} target="_blank" rel="noreferrer"
                         className="truncate text-indigo-400 hover:underline">
                        {r.url}
                      </a>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {task.events?.length > 0 && (
              <div>
                <div className="label">Timeline</div>
                <div className="space-y-1">
                  {task.events.map((e, i) => (
                    <div key={i} className="flex gap-3 text-xs text-slate-500">
                      <span className="tabular-nums">{e.observed_at}</span>
                      <span className="text-slate-300">{e.status}</span>
                      {e.detail && <span className="truncate">{e.detail}</span>}
                    </div>
                  ))}
                </div>
              </div>
            )}

            <div>
              <button onClick={() => setShowRaw((v) => !v)}
                      className="text-xs text-slate-500 hover:text-slate-300">
                {showRaw ? '▾' : '▸'} Raw response
              </button>
              {showRaw && (
                <pre className="mt-2 max-h-64 overflow-auto rounded-lg bg-ink-950
                                p-3 text-xs text-slate-400">
                  {prettyJson(task.raw_response)}
                </pre>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}
