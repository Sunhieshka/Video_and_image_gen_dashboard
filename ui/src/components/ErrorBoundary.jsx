import { Component } from 'react'

/**
 * Without this, any render error unmounts the whole tree and leaves a blank
 * white page with the reason only in the console. Showing the error on screen
 * means a crash is diagnosable instead of silent.
 */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props)
    this.state = { error: null, info: null }
  }

  static getDerivedStateFromError(error) {
    return { error }
  }

  componentDidCatch(error, info) {
    this.setState({ info })
    console.error('UI crashed:', error, info)
  }

  render() {
    const { error, info } = this.state
    if (!error) return this.props.children

    return (
      <div className="m-6 rounded-xl border border-rose-500/30 bg-rose-500/5 p-6">
        <h2 className="text-base font-semibold text-rose-300">
          Something broke while rendering {this.props.label || 'this view'}
        </h2>
        <p className="mt-1 text-sm text-slate-400">
          Your generation is unaffected — tasks are stored in the database and
          the dashboard will still show them.
        </p>

        <pre className="mt-4 max-h-48 overflow-auto rounded-lg bg-ink-950 p-3
                        text-xs text-rose-300">
          {String(error?.stack || error)}
        </pre>
        {info?.componentStack && (
          <pre className="mt-2 max-h-40 overflow-auto rounded-lg bg-ink-950 p-3
                          text-xs text-slate-500">
            {info.componentStack}
          </pre>
        )}

        <div className="mt-4 flex gap-2">
          <button onClick={() => this.setState({ error: null, info: null })}
                  className="btn-primary">Try again</button>
          <button onClick={() => window.location.reload()}
                  className="btn-ghost">Reload</button>
        </div>
      </div>
    )
  }
}
