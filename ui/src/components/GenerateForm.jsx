import { useEffect, useMemo, useState } from 'react'
import { Field, ErrorNote } from './Common.jsx'
import ReferenceInput from './ReferenceInput.jsx'
import { quotePrice, money } from '../api.js'

const RATIOS = ['16:9', '9:16', '1:1', '4:3', '3:4', '21:9']
const DURATIONS = [5, 10, 15, 20, 30]
export default function GenerateForm({ models, onSubmit, busy, error, config }) {
  const [prompt, setPrompt] = useState('')
  const [family, setFamily] = useState('')
  const [resolution, setResolution] = useState('')
  const [ratio, setRatio] = useState('16:9')
  const [duration, setDuration] = useState(5)
  const [generateAudio, setGenerateAudio] = useState(true)
  const [outputFormat, setOutputFormat] = useState('')
  const [references, setReferences] = useState([])
  const [inputVideoSeconds, setInputVideoSeconds] = useState('')
  const [quote, setQuote] = useState(null)

  const selected = useMemo(
    () => models.find((m) => m.family === family) || models[0],
    [models, family],
  )

  // Default to the first model, and keep resolution valid for it: Fast and Mini
  // top out at 720p, only 2.0 does 4K.
  useEffect(() => {
    if (!family && models.length) setFamily(models[0].family)
  }, [models, family])

  useEffect(() => {
    if (!selected) return
    if (!selected.resolutions.includes(resolution)) {
      setResolution(selected.resolutions.includes('720p')
        ? '720p' : selected.resolutions[0])
    }
  }, [selected, resolution])

  const hasVideoRef = references.some((r) => r.type === 'video_url')

  // ffprobe gives us the length of uploaded videos, so prefill the surcharge
  // input rather than making the user measure it. A manual edit wins.
  const [durationTouched, setDurationTouched] = useState(false)
  const probedSeconds = references
    .filter((r) => r.type === 'video_url' && r.duration_seconds)
    .reduce((sum, r) => sum + r.duration_seconds, 0)

  useEffect(() => {
    if (!durationTouched && probedSeconds > 0) {
      setInputVideoSeconds(String(Math.round(probedSeconds * 10) / 10))
    }
  }, [probedSeconds, durationTouched])

  // Live cost quote, debounced so typing a duration does not spam the backend.
  useEffect(() => {
    if (!selected || !resolution) return
    const id = setTimeout(() => {
      quotePrice({
        model: selected.model_id || selected.family,
        resolution,
        duration: Number(duration),
        has_video_input: hasVideoRef,
        input_video_seconds: hasVideoRef && inputVideoSeconds
          ? Number(inputVideoSeconds) : null,
      }).then(setQuote).catch(() => setQuote(null))
    }, 250)
    return () => clearTimeout(id)
  }, [selected, resolution, duration, inputVideoSeconds, hasVideoRef])

  const submit = (e) => {
    e.preventDefault()
    onSubmit({
      prompt,
      model: selected?.model_id || selected?.family,
      resolution,
      ratio,
      duration: Number(duration),
      generate_audio: generateAudio,
      output_format: outputFormat || null,
      references: references
        .filter((r) => r.url.trim())
        .map((r) => ({ type: r.type, url: r.url.trim(), role: r.role || null })),
      input_video_seconds: hasVideoRef && inputVideoSeconds
        ? Number(inputVideoSeconds) : null,
    })
  }

  const unavailable = selected && !selected.model_id

  return (
    <form onSubmit={submit} className="card p-5 space-y-5">
      <Field label="Prompt">
        <textarea
          className="field min-h-32 resize-y"
          placeholder="Describe the video you want to generate…"
          value={prompt}
          onChange={(e) => setPrompt(e.target.value)}
          required
        />
      </Field>

      <div className="grid grid-cols-2 gap-4">
        <Field label="Model">
          <select className="field" value={family}
                  onChange={(e) => setFamily(e.target.value)}>
            {models.map((m) => (
              <option key={m.family} value={m.family}>
                {m.family}{m.model_id ? '' : ' (model id not set)'}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Resolution">
          <select className="field" value={resolution}
                  onChange={(e) => setResolution(e.target.value)}>
            {(selected?.resolutions || []).map((r) => (
              <option key={r} value={r}>{r}</option>
            ))}
          </select>
        </Field>
        <Field label="Aspect ratio">
          <select className="field" value={ratio}
                  onChange={(e) => setRatio(e.target.value)}>
            {RATIOS.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
        </Field>
        <Field label="Duration">
          <select className="field" value={duration}
                  onChange={(e) => setDuration(e.target.value)}>
            {DURATIONS.map((d) => <option key={d} value={d}>{d} seconds</option>)}
          </select>
        </Field>
      </div>

      <div className="grid grid-cols-2 gap-4">
        <Field label="Output format">
          <select className="field" value={outputFormat}
                  onChange={(e) => setOutputFormat(e.target.value)}>
            <option value="">default</option>
            <option value="mp4">mp4</option>
            <option value="mov">mov</option>
          </select>
        </Field>
        <div className="flex items-end pb-1">
          <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-300">
            <input type="checkbox" checked={generateAudio}
                   onChange={(e) => setGenerateAudio(e.target.checked)}
                   className="h-4 w-4 rounded border-ink-600 bg-ink-850
                              accent-indigo-500" />
            Generate audio
          </label>
        </div>
      </div>

      <ReferenceInput references={references} onChange={setReferences} />

      {hasVideoRef && (
        <Field
          label="Total reference video length (seconds)"
          hint={probedSeconds > 0
            ? 'Measured from the uploaded files. Drives the video-input surcharge.'
            : 'Drives the video-input surcharge. Without it the cost shown is understated.'}
        >
          <input type="number" min="0" step="0.1" className="field w-48"
                 placeholder="e.g. 24"
                 value={inputVideoSeconds}
                 onChange={(e) => {
                   setDurationTouched(true)
                   setInputVideoSeconds(e.target.value)
                 }} />
        </Field>
      )}

      <ErrorNote>{error}</ErrorNote>

      {unavailable && (
        <ErrorNote>
          No model id configured for {selected.family}. Set its
          ARK_MODEL_… environment variable before generating.
        </ErrorNote>
      )}

      {/* Cost + submit --------------------------------------------------- */}
      <div className="flex items-center justify-between border-t border-ink-700 pt-4">
        <div>
          <div className="text-xs uppercase tracking-wider text-slate-400">
            Estimated price (USD)
          </div>
          <div className="text-xl font-semibold tabular-nums text-indigo-400">
            {quote?.amount != null ? `~${money(quote.amount)}` : '—'}
          </div>
          {quote?.unit_price_per_million != null && (
            <div className="mt-0.5 text-xs text-slate-500">
              ${quote.unit_price_per_million.toFixed(2)} per million tokens
              {hasVideoRef ? ' (with video input)' : ''} · billed on actual usage
            </div>
          )}
          {quote?.note && !quote.note.startsWith('projected;') && (
            <div className="mt-0.5 max-w-md text-xs text-slate-500">{quote.note}</div>
          )}
        </div>
        <button type="submit" className="btn-primary px-6 py-2.5"
                disabled={busy || !prompt.trim() || unavailable}>
          {busy ? 'Generating…' : 'Generate video'}
        </button>
      </div>
    </form>
  )
}
