import { useEffect, useMemo, useState } from 'react'
import { Field, ErrorNote } from './Common.jsx'
import ReferenceInput from './ReferenceInput.jsx'
import { quoteImagePrice, money } from '../api.js'

const FORMATS = ['png', 'jpeg']

export default function ImageForm({ models, onSubmit, busy, error }) {
  const [prompt, setPrompt] = useState('')
  const [family, setFamily] = useState('')
  const [size, setSize] = useState('2K')
  const [outputFormat, setOutputFormat] = useState('png')
  const [watermark, setWatermark] = useState(false)
  const [seed, setSeed] = useState('')
  const [references, setReferences] = useState([])
  const [quote, setQuote] = useState(null)

  const selected = useMemo(
    () => models.find((m) => m.family === family) || models[0],
    [models, family],
  )

  useEffect(() => {
    if (!family && models.length) setFamily(models[0].family)
  }, [models, family])

  // Each model takes a different size set -- pro is 1K/1.5K/2K, 5.0 and 4.5 are
  // 2K/4K -- so follow the selection rather than offering an invalid pairing.
  const sizes = selected?.sizes?.length ? selected.sizes : ['1K', '2K', '4K']

  useEffect(() => {
    if (!sizes.includes(size)) setSize(sizes.includes('2K') ? '2K' : sizes[0])
  }, [sizes, size])

  // Only images are valid input here; the API takes no video or audio.
  const inputImages = references.filter((r) => r.type === 'image_url')

  useEffect(() => {
    if (!selected) return
    const id = setTimeout(() => {
      quoteImagePrice({
        model: selected.model_id || selected.family,
        size,
        generated_images: 1,
        input_images: inputImages.length,
      }).then(setQuote).catch(() => setQuote(null))
    }, 250)
    return () => clearTimeout(id)
  }, [selected, size, inputImages.length])

  const submit = (e) => {
    e.preventDefault()
    onSubmit({
      prompt,
      model: selected?.model_id || selected?.family,
      size,
      output_format: outputFormat,
      response_format: 'url',
      watermark,
      seed: seed === '' ? null : Number(seed),
      image: inputImages.map((r) => r.url),
    })
  }

  return (
    <form onSubmit={submit} className="card p-5 space-y-5">
      <Field label="Prompt">
        <textarea className="field min-h-32 resize-y"
                  placeholder="Describe the image you want to generate…"
                  value={prompt} onChange={(e) => setPrompt(e.target.value)}
                  required />
      </Field>

      <div className="grid grid-cols-2 gap-4">
        <Field label="Model">
          <select className="field" value={family}
                  onChange={(e) => setFamily(e.target.value)}>
            {models.map((m) => (
              <option key={m.family} value={m.family}>{m.family}</option>
            ))}
          </select>
        </Field>
        <Field label="Size">
          <select className="field" value={size}
                  onChange={(e) => setSize(e.target.value)}>
            {sizes.map((s) => <option key={s} value={s}>{s}</option>)}
          </select>
        </Field>
        <Field label="Output format">
          <select className="field" value={outputFormat}
                  onChange={(e) => setOutputFormat(e.target.value)}>
            {FORMATS.map((f) => <option key={f} value={f}>{f}</option>)}
          </select>
        </Field>
        <Field label="Seed" hint="blank for random">
          <input className="field" type="number" placeholder="random"
                 value={seed} onChange={(e) => setSeed(e.target.value)} />
        </Field>
      </div>

      <label className="flex cursor-pointer items-center gap-2 text-sm text-slate-300">
        <input type="checkbox" checked={watermark}
               onChange={(e) => setWatermark(e.target.checked)}
               className="h-4 w-4 rounded border-ink-600 bg-ink-850
                          accent-indigo-500" />
        Watermark
      </label>

      {/* Image-to-image: reference images only. */}
      <ReferenceInput references={references} onChange={setReferences}
                      kinds={['image_url']} label="Input images"
                      hint="Optional. Adding one or more switches to image-to-image." />

      <ErrorNote>{error}</ErrorNote>

      <div className="flex items-center justify-between border-t border-ink-700 pt-4">
        <div>
          <div className="text-xs uppercase tracking-wider text-slate-400">
            Estimated price (USD)
          </div>
          <div className="text-xl font-semibold tabular-nums text-indigo-400">
            {quote?.amount != null ? money(quote.amount) : '—'}
          </div>
          {quote?.output_rate != null && (
            <div className="mt-0.5 text-xs text-slate-500">
              ${quote.output_rate.toFixed(3)} per image
              {quote.input_cost > 0 && ` + ${money(quote.input_cost)} input`}
              {selected?.tiered && ` at ${size}`}
            </div>
          )}
          {quote?.note && (
            <div className="mt-0.5 max-w-md text-xs text-slate-500">{quote.note}</div>
          )}
        </div>
        <button type="submit" className="btn-primary px-6 py-2.5"
                disabled={busy || !prompt.trim()}>
          {busy ? 'Generating…' : 'Generate image'}
        </button>
      </div>
    </form>
  )
}
