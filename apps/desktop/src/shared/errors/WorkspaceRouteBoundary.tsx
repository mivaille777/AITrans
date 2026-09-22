import { Component, type ErrorInfo, type ReactNode } from "react"
import { Link } from "react-router-dom"

import { buttonClassName } from "../ui/button-styles"

interface RouteBoundaryState {
  error: Error | null
}

class RouteBoundary extends Component<{ children: ReactNode }, RouteBoundaryState> {
  state: RouteBoundaryState = { error: null }

  static getDerivedStateFromError(error: Error): RouteBoundaryState {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("Workspace route crashed", error, info)
  }

  render() {
    if (!this.state.error) return this.props.children

    return (
      <section className="rounded-2xl border border-rose-200 bg-white p-6 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.16em] text-rose-500">
          Workspace route error
        </p>
        <h2 className="mt-2 text-lg font-semibold text-slate-900">
          This page failed without taking down the desktop shell.
        </h2>
        <p className="mt-2 text-sm leading-6 text-slate-500">
          Try the route again, or reload the WebView if the same page keeps failing.
        </p>
        <pre className="mt-4 max-h-32 overflow-auto rounded-xl bg-slate-950 p-3 text-xs leading-5 text-slate-300">
          {this.state.error.message}
        </pre>
        <div className="mt-4 flex gap-2">
          <button
            type="button"
            className={buttonClassName()}
            onClick={() => this.setState({ error: null })}
          >
            Try again
          </button>
          <Link to="/translation" className={buttonClassName({ variant: "primary" })}>
            Translation workspace
          </Link>
          <button
            type="button"
            className={buttonClassName()}
            onClick={() => window.location.reload()}
          >
            Reload
          </button>
        </div>
      </section>
    )
  }
}

export default function WorkspaceRouteBoundary({ children }: { children: ReactNode }) {
  return <RouteBoundary>{children}</RouteBoundary>
}
