// Switch the dashboard between the video and image tables.
export default function KindTabs({ kind, onChange }) {
  return (
    <div className="inline-flex rounded-lg border border-ink-700 p-0.5">
      {[['video', 'Videos'], ['image', 'Images']].map(([value, label]) => (
        <button key={value} onClick={() => onChange(value)}
                className={`rounded-md px-4 py-1.5 text-sm font-medium transition
                            ${kind === value
                              ? 'bg-indigo-600 text-white'
                              : 'text-slate-400 hover:text-slate-200'}`}>
          {label}
        </button>
      ))}
    </div>
  )
}
