// Small presentational pieces shared by the generate and dashboard views.

const STATUS_STYLES = {
  succeeded: 'bg-emerald-500/10 text-emerald-400 ring-emerald-500/20',
  failed: 'bg-rose-500/10 text-rose-400 ring-rose-500/20',
  cancelled: 'bg-slate-500/10 text-slate-400 ring-slate-500/20',
  running: 'bg-amber-500/10 text-amber-400 ring-amber-500/20',
  queued: 'bg-sky-500/10 text-sky-400 ring-sky-500/20',
}

export function StatusPill({ status }) {
  const key = (status || 'unknown').toLowerCase()
  const style = STATUS_STYLES[key] || 'bg-slate-500/10 text-slate-400 ring-slate-500/20'
  const spinning = key === 'running' || key === 'queued'
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5
                      text-xs font-medium ring-1 ring-inset ${style}`}>
      {spinning && (
        <span className="h-1.5 w-1.5 rounded-full bg-current animate-pulse" />
      )}
      {status || 'unknown'}
    </span>
  )
}

export function Stat({ label, value, sub, accent }) {
  return (
    <div className="card p-4">
      <div className="text-xs uppercase tracking-wider text-slate-400">{label}</div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums
                       ${accent ? 'text-indigo-400' : 'text-slate-100'}`}>
        {value}
      </div>
      {sub && <div className="mt-0.5 text-xs text-slate-500">{sub}</div>}
    </div>
  )
}

export function Field({ label, hint, children }) {
  return (
    <div>
      <label className="label">{label}</label>
      {children}
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  )
}

export function Empty({ children }) {
  return (
    <div className="py-16 text-center text-sm text-slate-500">{children}</div>
  )
}

export function ErrorNote({ children }) {
  if (!children) return null
  return (
    <div className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3 py-2
                    text-sm text-rose-300">
      {children}
    </div>
  )
}
