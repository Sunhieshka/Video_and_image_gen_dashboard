import { useRef, useState } from 'react'
import { uploadFiles, humanSize } from '../api.js'

// One box per kind. `accept` filters the OS file picker to matching files.
const KINDS = [
  { type: 'image_url', label: 'Images', icon: '🖼', accept: 'image/*',
    hint: 'png, jpg, webp' },
  { type: 'video_url', label: 'Videos', icon: '🎬', accept: 'video/*',
    hint: 'mp4, mov, webm' },
  { type: 'audio_url', label: 'Audio', icon: '🎵', accept: 'audio/*',
    hint: 'mp3, wav, m4a' },
]

const EXT_TYPE = {
  mp4: 'video_url', mov: 'video_url', webm: 'video_url', mkv: 'video_url',
  avi: 'video_url',
  mp3: 'audio_url', wav: 'audio_url', aac: 'audio_url', m4a: 'audio_url',
  flac: 'audio_url', ogg: 'audio_url',
}

/**
 * Reference media picker with a separate box per kind. Files can be chosen
 * from disk or dragged in; URLs can be pasted. Uploads are stored by the
 * backend and referenced by URL, which is what the Ark API expects.
 */
export default function ReferenceInput({
  references, onChange, kinds = null, label = 'Reference media', hint = null,
}) {
  // `kinds` restricts which boxes are shown (image generation takes images only).
  const shown = kinds ? KINDS.filter((k) => kinds.includes(k.type)) : KINDS
  const [dragKind, setDragKind] = useState(null)
  const [uploading, setUploading] = useState(null)
  const [error, setError] = useState(null)
  const [urlDraft, setUrlDraft] = useState('')
  const inputs = useRef({})

  const handleFiles = async (fileList, kind) => {
    const files = Array.from(fileList || [])
    if (!files.length) return
    setUploading(kind)
    setError(null)
    try {
      const { files: uploaded } = await uploadFiles(files)
      // The backend reports the real type, so a video dropped on the image
      // box still lands in the video group rather than being mislabelled.
      onChange([...references, ...uploaded.map((f) => ({
        type: f.type,
        url: f.url,
        role: '',
        filename: f.filename,
        size: f.size,
        duration_seconds: f.duration_seconds,
        uploaded: true,
      }))])
    } catch (e) {
      setError(e.message)
    } finally {
      setUploading(null)
      if (inputs.current[kind]) inputs.current[kind].value = ''
    }
  }

  const addUrl = () => {
    const url = urlDraft.trim()
    if (!url) return
    const ext = url.split('?')[0].split('.').pop().toLowerCase()
    let type = EXT_TYPE[ext] || 'image_url'
    if (kinds && !kinds.includes(type)) type = kinds[0]
    onChange([...references, { type, url, role: '', uploaded: false }])
    setUrlDraft('')
  }

  const update = (ref, patch) =>
    onChange(references.map((r) => (r === ref ? { ...r, ...patch } : r)))

  const remove = (ref) => onChange(references.filter((r) => r !== ref))

  return (
    <div className="space-y-3">
      <div className="flex items-baseline justify-between">
        <span className="label mb-0">{label}</span>
        <span className="text-xs text-slate-600">optional</span>
      </div>
      {hint && <p className="-mt-1 text-xs text-slate-500">{hint}</p>}

      <div className={`grid gap-3 ${shown.length > 1 ? 'sm:grid-cols-3' : ''}`}>
        {shown.map((kind) => {
          const mine = references.filter((r) => r.type === kind.type)
          const active = dragKind === kind.type
          return (
            <div key={kind.type} className="space-y-2">
              <div
                onClick={() => inputs.current[kind.type]?.click()}
                onDragOver={(e) => { e.preventDefault(); setDragKind(kind.type) }}
                onDragLeave={() => setDragKind(null)}
                onDrop={(e) => {
                  e.preventDefault()
                  setDragKind(null)
                  handleFiles(e.dataTransfer.files, kind.type)
                }}
                className={`flex cursor-pointer flex-col items-center justify-center
                            gap-1 rounded-lg border-2 border-dashed px-3 py-4
                            text-center transition
                            ${active
                              ? 'border-indigo-500 bg-indigo-500/10'
                              : 'border-ink-700 hover:border-ink-600 hover:bg-ink-850'}`}
              >
                <input
                  ref={(el) => { inputs.current[kind.type] = el }}
                  type="file" multiple accept={kind.accept} className="hidden"
                  onChange={(e) => handleFiles(e.target.files, kind.type)}
                />
                {uploading === kind.type ? (
                  <span className="h-5 w-5 animate-spin rounded-full border-2
                                   border-ink-600 border-t-indigo-500" />
                ) : (
                  <span className="text-xl leading-none">{kind.icon}</span>
                )}
                <span className="text-sm font-medium text-slate-200">
                  {kind.label}
                  {mine.length > 0 && (
                    <span className="ml-1.5 rounded-full bg-indigo-500/20 px-1.5
                                     text-xs text-indigo-300">{mine.length}</span>
                  )}
                </span>
                <span className="text-[11px] leading-tight text-slate-500">
                  Click or drag<br />{kind.hint}
                </span>
              </div>

              {mine.map((ref, i) => (
                <div key={i}
                     className="rounded-lg border border-ink-700 bg-ink-850 p-1.5">
                  <div className="flex items-center gap-1.5">
                    {ref.type === 'image_url' ? (
                      <img src={ref.url} alt=""
                           className="h-7 w-7 shrink-0 rounded object-cover"
                           onError={(e) => { e.currentTarget.style.display = 'none' }} />
                    ) : (
                      <span className="flex h-7 w-7 shrink-0 items-center
                                       justify-center rounded bg-ink-800 text-sm">
                        {kind.icon}
                      </span>
                    )}
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-xs text-slate-200"
                           title={ref.filename || ref.url}>
                        {ref.filename || ref.url}
                      </div>
                      <div className="truncate text-[11px] text-slate-500">
                        {ref.size ? humanSize(ref.size) : 'external URL'}
                        {ref.duration_seconds ? ` · ${ref.duration_seconds}s` : ''}
                      </div>
                    </div>
                    <button type="button" onClick={() => remove(ref)}
                            title="Remove"
                            className="shrink-0 rounded px-1 text-slate-600
                                       hover:bg-ink-800 hover:text-rose-400">✕</button>
                  </div>
                  <input
                    className="mt-1 w-full rounded border border-ink-700 bg-ink-900
                               px-1.5 py-0.5 text-[11px] text-slate-300
                               placeholder-slate-600 outline-none
                               focus:border-indigo-500"
                    placeholder="role (optional)"
                    value={ref.role}
                    onChange={(e) => update(ref, { role: e.target.value })}
                  />
                </div>
              ))}
            </div>
          )
        })}
      </div>

      <div className="flex gap-2">
        <input
          className="field flex-1"
          placeholder="…or paste a URL"
          value={urlDraft}
          onChange={(e) => setUrlDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') { e.preventDefault(); addUrl() }
          }}
        />
        <button type="button" onClick={addUrl} disabled={!urlDraft.trim()}
                className="btn-ghost shrink-0">Add URL</button>
      </div>

      {error && (
        <p className="rounded-lg border border-rose-500/30 bg-rose-500/10 px-3
                      py-2 text-xs text-rose-300">{error}</p>
      )}
    </div>
  )
}
