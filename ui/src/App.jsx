import { useEffect, useRef, useState } from 'react'
import GenerateForm from './components/GenerateForm.jsx'
import ImageForm from './components/ImageForm.jsx'
import ImageOutput from './components/ImageOutput.jsx'
import OutputPanel from './components/OutputPanel.jsx'
import Dashboard from './components/Dashboard.jsx'
import { ErrorNote } from './components/Common.jsx'
import ErrorBoundary from './components/ErrorBoundary.jsx'
import {
  getModels, getConfig, generate, getTask, isTerminal,
  getImageModels, generateImage,
} from './api.js'

let nextKey = 1
const newJob = (kind = 'video') => ({
  key: nextKey++, kind, task: null, busy: false, error: null,
  startedAt: null, elapsed: null,
})

const DOT = {
  succeeded: 'bg-emerald-400',
  failed: 'bg-rose-400',
  cancelled: 'bg-slate-500',
}

function TabDot({ job }) {
  const status = (job.task?.status || '').toLowerCase()
  if (!job.task) return <span className="h-1.5 w-1.5 rounded-full bg-ink-600" />
  const color = DOT[status] || 'bg-amber-400'
  return (
    <span className={`h-1.5 w-1.5 rounded-full ${color}
                      ${isTerminal(status) ? '' : 'animate-pulse'}`} />
  )
}

export default function App() {
  const [view, setView] = useState('generate')
  const [models, setModels] = useState([])
  const [imageModels, setImageModels] = useState([])
  const [config, setConfig] = useState(null)
  const [dashboardKind, setDashboardKind] = useState('video')
  const [bootError, setBootError] = useState(null)

  // Each tab is an independent generation. They run in parallel: the backend
  // submits and returns immediately, so several can be in flight at once.
  const [jobs, setJobs] = useState([newJob()])
  const [activeKey, setActiveKey] = useState(1)
  const jobsRef = useRef(jobs)
  jobsRef.current = jobs

  useEffect(() => {
    getModels().then((d) => setModels(d.models))
      .catch((e) => setBootError(`Could not reach the API: ${e.message}`))
    getImageModels().then((d) => setImageModels(d.models)).catch(() => {})
    getConfig().then(setConfig).catch(() => {})
  }, [])

  const patchJob = (key, patch) =>
    setJobs((js) => js.map((j) => (j.key === key
      ? { ...j, ...(typeof patch === 'function' ? patch(j) : patch) }
      : j)))

  // One timer polls every in-flight job, so a background tab still updates.
  useEffect(() => {
    const id = setInterval(() => {
      const pending = jobsRef.current.filter(
        (j) => j.kind === 'video' && j.task && !isTerminal(j.task.status))
      if (!pending.length) return
      pending.forEach((job) => {
        getTask(job.task.id)
          .then((task) => patchJob(job.key, {
            task,
            busy: !isTerminal(task.status),
            elapsed: job.startedAt
              ? Math.round((Date.now() - job.startedAt) / 1000) : null,
          }))
          .catch(() => {})
      })
    }, 3000)
    return () => clearInterval(id)
  }, [])

  // Separate 1s ticker so the elapsed counter moves smoothly.
  useEffect(() => {
    const id = setInterval(() => {
      setJobs((js) => js.map((j) =>
        j.busy && j.startedAt
          ? { ...j, elapsed: Math.round((Date.now() - j.startedAt) / 1000) }
          : j))
    }, 1000)
    return () => clearInterval(id)
  }, [])

  const addJob = (kind = 'video') => {
    const job = newJob(kind)
    setJobs((js) => [...js, job])
    setActiveKey(job.key)
    setView('generate')
  }

  const setJobKind = (key, kind) =>
    patchJob(key, { kind, task: null, error: null, busy: false, elapsed: null })

  const closeJob = (key, event) => {
    event.stopPropagation()
    // Compute the next state outside the updater: calling setActiveKey from
    // inside one is a state update during the render phase, which React 18
    // rejects (and StrictMode runs updaters twice).
    const remaining = jobs.filter((j) => j.key !== key)
    const next = remaining.length ? remaining : [newJob()]
    setJobs(next)
    if (key === activeKey) setActiveKey(next[next.length - 1].key)
  }

  const onSubmit = (key) => async (body) => {
    patchJob(key, { busy: true, error: null, task: null,
                    startedAt: Date.now(), elapsed: 0 })
    try {
      const { task_id } = await generate(body)
      const task = await getTask(task_id)
      patchJob(key, { task, busy: !isTerminal(task.status) })
    } catch (e) {
      patchJob(key, { error: e.message, busy: false })
    }
  }

  // Image generation is synchronous: one call returns the finished row.
  const onSubmitImage = (key) => async (body) => {
    patchJob(key, { busy: true, error: null, task: null,
                    startedAt: Date.now(), elapsed: 0 })
    try {
      patchJob(key, { task: await generateImage(body), busy: false })
    } catch (e) {
      patchJob(key, { error: e.message, busy: false })
    }
  }

  const running = jobs.filter((j) => j.busy).length

  return (
    <div className="min-h-full text-slate-100">
      <header className="sticky top-0 z-40 border-b border-ink-800
                         bg-ink-950/85 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center justify-between
                        px-6 py-3.5">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg
                            bg-indigo-600 text-sm font-bold">V</div>
            <div>
              <h1 className="text-sm font-semibold leading-tight">
                Video Generation
              </h1>
              <p className="text-xs text-slate-500">BytePlus Ark · Seedance</p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            {running > 0 && (
              <span className="mr-1 flex items-center gap-1.5 rounded-full
                               bg-amber-500/10 px-2.5 py-1 text-xs
                               text-amber-400 ring-1 ring-inset ring-amber-500/20">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-current" />
                {running} running
              </span>
            )}
            <button onClick={() => setView('generate')}
                    className={view === 'generate' ? 'btn-primary' : 'btn-ghost'}>
              Generate
            </button>
            <button onClick={() => setView('dashboard')}
                    className={view === 'dashboard' ? 'btn-primary' : 'btn-ghost'}>
              Dashboard
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-6">
        {bootError && <div className="mb-5"><ErrorNote>{bootError}</ErrorNote></div>}

        {view === 'generate' && (
          <div className="mb-5 flex items-center gap-2 border-b border-ink-800 pb-2">
            <div className="flex flex-1 flex-wrap items-center gap-1.5">
              {jobs.map((job, i) => (
                <button
                  key={job.key}
                  onClick={() => setActiveKey(job.key)}
                  className={`group flex items-center gap-2 rounded-lg px-3 py-1.5
                              text-sm transition
                              ${job.key === activeKey
                                ? 'bg-ink-800 text-slate-100'
                                : 'text-slate-400 hover:bg-ink-850'}`}
                >
                  <TabDot job={job} />
                  {job.kind === 'image' ? 'Image' : 'Video'} {i + 1}
                  {job.busy && job.elapsed != null && (
                    <span className="text-xs tabular-nums text-amber-400/80">
                      {job.elapsed}s
                    </span>
                  )}
                  {jobs.length > 1 && (
                    <span onClick={(e) => closeJob(job.key, e)}
                          className="ml-0.5 rounded px-1 text-slate-600
                                     hover:bg-ink-700 hover:text-rose-400">✕</span>
                  )}
                </button>
              ))}
            </div>

            <button
              onClick={addJob}
              title="New generation task"
              className="flex h-8 w-8 shrink-0 items-center justify-center
                         rounded-lg border border-ink-700 text-lg leading-none
                         text-slate-400 transition hover:border-indigo-500
                         hover:bg-indigo-500/10 hover:text-indigo-400"
            >
              +
            </button>
          </div>
        )}

        {view === 'generate' ? (
          // Every tab stays mounted so its form state and polling survive a
          // switch; only the active one is visible.
          jobs.map((job) => (
            <div key={job.key}
                 className={job.key === activeKey ? 'space-y-4' : 'hidden'}>
              <div className="inline-flex rounded-lg border border-ink-700 p-0.5">
                {[['video', 'Video'], ['image', 'Image']].map(([value, label]) => (
                  <button key={value}
                          onClick={() => setJobKind(job.key, value)}
                          disabled={job.busy}
                          className={`rounded-md px-4 py-1.5 text-sm font-medium
                                      transition disabled:opacity-40
                                      ${job.kind === value
                                        ? 'bg-indigo-600 text-white'
                                        : 'text-slate-400 hover:text-slate-200'}`}>
                    {label}
                  </button>
                ))}
              </div>

              <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_420px]">
                <ErrorBoundary label="the generation form">
                  {job.kind === 'image' ? (
                    <ImageForm models={imageModels}
                               onSubmit={onSubmitImage(job.key)}
                               busy={job.busy} error={job.error} />
                  ) : (
                    <GenerateForm models={models} config={config}
                                  onSubmit={onSubmit(job.key)}
                                  busy={job.busy} error={job.error} />
                  )}
                </ErrorBoundary>
                <ErrorBoundary label="the output panel">
                  {job.kind === 'image'
                    ? <ImageOutput task={job.task} busy={job.busy} />
                    : <OutputPanel task={job.task} elapsed={job.elapsed} />}
                </ErrorBoundary>
              </div>
            </div>
          ))
        ) : (
          <ErrorBoundary label="the dashboard">
            <Dashboard kind={dashboardKind} onKindChange={setDashboardKind} />
          </ErrorBoundary>
        )}
      </main>
    </div>
  )
}
