import { StatusPill, Empty } from './Common.jsx'
import { money, isTerminal } from '../api.js'

function Row({ label, children }) {
  return (
    <div className="flex justify-between gap-4 py-1.5 text-sm">
      <span className="text-slate-500">{label}</span>
      <span className="text-right text-slate-200 tabular-nums">{children}</span>
    </div>
  )
}

export default function OutputPanel({ task, elapsed }) {
  if (!task) {
    return (
      <div className="card p-5">
        <h2 className="mb-1 text-sm font-semibold text-slate-200">Output</h2>
        <Empty>Your generated video will appear here.</Empty>
      </div>
    )
  }

  const status = (task.status || '').toLowerCase()
  const done = isTerminal(status)

  return (
    <div className="card p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-200">Output</h2>
        <StatusPill status={task.status} />
      </div>

      {!done && (
        <div className="flex flex-col items-center gap-3 py-10">
          <div className="h-8 w-8 animate-spin rounded-full border-2
                          border-ink-600 border-t-indigo-500" />
          <p className="text-sm text-slate-400">
            Generating… {elapsed != null && `${elapsed}s elapsed`}
          </p>
          <p className="text-xs text-slate-600">
            This can take several minutes. The dashboard updates on its own.
          </p>
        </div>
      )}

      {status === 'failed' && (
        <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 p-3">
          <p className="text-sm font-medium text-rose-300">
            {task.error_code || 'Generation failed'}
          </p>
          {task.error_message && (
            <p className="mt-1 text-xs text-rose-400/80">{task.error_message}</p>
          )}
        </div>
      )}

      {status === 'succeeded' && task.video_url && (
        <video
          key={task.video_url}
          src={task.video_url}
          controls
          className="w-full rounded-lg border border-ink-700 bg-black"
        />
      )}

      {done && (
        <div className="divide-y divide-ink-800">
          <Row label="Task">
            <span className="font-mono text-xs">{task.id}</span>
          </Row>
          <Row label="Model">{task.model || '—'}</Row>
          <Row label="Resolution">
            {[task.resolution, task.ratio, task.duration && `${task.duration}s`]
              .filter(Boolean).join(' · ') || '—'}
          </Row>
          <Row label="Frames">
            {task.framespersecond ? `${task.framespersecond} fps` : '—'}
          </Row>
          <Row label="Tokens">
            {task.total_tokens ? task.total_tokens.toLocaleString() : '—'}
          </Row>
          <Row label="Unit price">
            {task.unit_price_per_million_usd != null
              ? `$${task.unit_price_per_million_usd.toFixed(2)} / 1M tokens`
              : '—'}
          </Row>
          <Row label={task.cost_is_estimate ? 'Estimated price' : 'Price (USD)'}>
            <span className="text-indigo-400">
              {task.cost_is_estimate ? '~' : ''}{money(task.estimated_cost_usd)}
            </span>
          </Row>
          {task.video_url && (
            <Row label="Video">
              <a href={task.video_url} target="_blank" rel="noreferrer"
                 className="text-indigo-400 hover:underline">Open ↗</a>
            </Row>
          )}
        </div>
      )}

      {task.cost_note && (
        <p className="rounded-md bg-ink-850 px-3 py-2 text-xs text-slate-500">
          {task.cost_note}
        </p>
      )}
    </div>
  )
}
