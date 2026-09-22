// Thin wrapper around the FastAPI backend. Relative paths work in dev (Vite
// proxies /api) and in the built bundle (FastAPI serves both).

async function request(path, options = {}) {
  const res = await fetch(`/api${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body.detail) detail = body.detail
    } catch {
      /* non-JSON error body; keep the status line */
    }
    throw new Error(detail)
  }
  return res.json()
}

export const getModels = () => request('/models')
export const getStats = () => request('/stats')
export const getTask = (id) => request(`/tasks/${id}`)

export const quotePrice = (body) =>
  request('/price', { method: 'POST', body: JSON.stringify(body) })

export const generate = (body) =>
  request('/generate', { method: 'POST', body: JSON.stringify(body) })

export const listTasks = (filters = {}) => {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== '' && v !== null && v !== undefined && v !== false) params.set(k, v)
  })
  const qs = params.toString()
  return request(`/tasks${qs ? `?${qs}` : ''}`)
}

export const TERMINAL = ['succeeded', 'failed', 'cancelled']
export const isTerminal = (status) => TERMINAL.includes((status || '').toLowerCase())

export const money = (n) =>
  n === null || n === undefined ? '—' : `$${Number(n).toFixed(4)}`

export const formatWhen = (unix) => {
  if (!unix) return '—'
  return new Date(unix * 1000).toLocaleString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  })
}

export const getConfig = () => request('/config')

export async function uploadFiles(fileList) {
  const form = new FormData()
  for (const file of fileList) form.append('files', file)
  const res = await fetch('/api/upload', { method: 'POST', body: form })
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = await res.json()
      if (body.detail) detail = body.detail
    } catch { /* keep the status line */ }
    throw new Error(detail)
  }
  return res.json()
}

export const humanSize = (bytes) => {
  if (!bytes) return ''
  const units = ['B', 'KB', 'MB', 'GB']
  let n = bytes
  let i = 0
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++ }
  return `${n.toFixed(n < 10 && i > 0 ? 1 : 0)} ${units[i]}`
}

// ---- image generation ----------------------------------------------------

export const getImageModels = () => request('/image-models')

export const quoteImagePrice = (body) =>
  request('/images/price', { method: 'POST', body: JSON.stringify(body) })

export const generateImage = (body) =>
  request('/images/generate', { method: 'POST', body: JSON.stringify(body) })

export const getImage = (id) => request(`/images/${id}`)

export const listImages = (filters = {}) => {
  const params = new URLSearchParams()
  Object.entries(filters).forEach(([k, v]) => {
    if (v !== '' && v !== null && v !== undefined && v !== false) params.set(k, v)
  })
  const qs = params.toString()
  return request(`/images${qs ? `?${qs}` : ''}`)
}
