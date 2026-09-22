import { Empty, StatusPill } from './Common.jsx'
import { money } from '../api.js'

function Row({ label, children }) {
  return (
    <div className="flex justify-between gap-4 py-1.5 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className="text-right text-slate-200 tabular-nums">{children}</span>
    </div>
  )
}

export default function ImageOutput({ task, busy }) {
  if (busy) {
    return (
      <div className="card p-5">
        <h2 className="mb-1 text-sm font-semibold text-slate-200">Output</h2>
        <div className="flex flex-col items-center gap-3 py-12">
          <div className="h-8 w-8 animate-spin rounded-full border-2
                          border-ink-600 border-t-indigo-500" />
          <p className="text-sm text-slate-400">Generating…</p>
        </div>
      </div>
    )
  }

  if (!task) {
    return (
      <div className="card p-5">
        <h2 className="mb-1 text-sm font-semibold text-slate-200">Output</h2>
        <Empty>Your generated image will appear here.</Empty>
      </div>
    )
  }

  return (
    <div className="card p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-200">Output</h2>
        <StatusPill status={task.status} />
      </div>

      {task.error_message && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3">
          <p className="text-sm font-medium text-rose-300">
            {task.error_code || 'Generation failed'}
          </p>
          <p className="mt-1 text-xs text-rose-400/80">{task.error_message}</p>
        </div>
      )}

      {(task.outputs || []).map((o) => (
        <a key={o.position} href={o.url} target="_blank" rel="noreferrer">
          <img src={o.url} alt=""
               className="w-full rounded-lg border border-ink-700 bg-black" />
        </a>
      ))}

      <div className="divide-y divide-ink-800">
        <Row label="Task"><span className="font-mono text-xs">{task.id}</span></Row>
        <Row label="Model">{task.model || '—'}</Row>
        <Row label="Size">
          {task.outputs?.[0]?.size || task.size || '—'}
        </Row>
        <Row label="Images">
          {task.generated_images ?? '—'}
          {task.input_images ? ` (+${task.input_images} in)` : ''}
        </Row>
        <Row label="Rate per image">
          {task.output_rate_usd != null
            ? `$${task.output_rate_usd.toFixed(3)}` : '—'}
        </Row>
        <Row label="Tokens">
          {task.total_tokens ? task.total_tokens.toLocaleString() : '—'}
        </Row>
        <Row label="Price (USD)">
          <span className="text-indigo-400">
            {task.cost_is_estimate ? '~' : ''}{money(task.estimated_cost_usd)}
          </span>
        </Row>
      </div>

      {task.cost_note && (
        <p className="rounded-md bg-ink-850 px-3 py-2 text-xs text-slate-500">
          {task.cost_note}
        </p>
      )}
    </div>
  )
}
