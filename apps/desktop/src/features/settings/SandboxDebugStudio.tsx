import { AlertCircle, LoaderCircle } from "lucide-react"
import { useEffect, useRef, useState, type KeyboardEvent } from "react"

import {
  getSandboxDebugRun,
  getSandboxRuntimeHealth,
  type SandboxDebugTrace as SandboxDebugTraceData,
  type SandboxRuntimeHealth,
} from "../../api/sandbox-debug"
import SandboxDebugFilesystem from "./SandboxDebugFilesystem"
import SandboxDebugPolicy from "./SandboxDebugPolicy"
import SandboxDebugResources from "./SandboxDebugResources"
import SandboxDebugRuns from "./SandboxDebugRuns"
import SandboxDebugTrace from "./SandboxDebugTrace"
import { sandboxDebugErrorFromCode } from "./sandbox-debug-errors"

type SandboxDebugTab = "trace" | "filesystem" | "resources" | "policy" | "runs"

const TABS: Array<{ id: SandboxDebugTab; label: string }> = [
  { id: "trace", label: "Trace" },
  { id: "filesystem", label: "Filesystem" },
  { id: "resources", label: "Resources" },
  { id: "policy", label: "Policy" },
  { id: "runs", label: "Runs" },
]

export default function SandboxDebugStudio({ initialSandboxId = "" }: { initialSandboxId?: string }) {
  const [activeTab, setActiveTab] = useState<SandboxDebugTab>("trace")
  const [visitedTabs, setVisitedTabs] = useState<Set<SandboxDebugTab>>(() => new Set(["trace"]))
  const [runtimeHealth, setRuntimeHealth] = useState<SandboxRuntimeHealth | null>(null)
  const [runtimeHealthPending, setRuntimeHealthPending] = useState(true)
  const [latestTrace, setLatestTrace] = useState<SandboxDebugTraceData | null>(null)
  const [traceIntentPending, setTraceIntentPending] = useState(false)
  const [traceIntentError, setTraceIntentError] = useState("")
  const inspectedIntentRef = useRef("")

  /* oxlint-disable react/set-state-in-effect -- retain tab-local state after the user visits a tab */
  useEffect(() => {
    setVisitedTabs((current) => {
      if (current.has(activeTab)) return current
      return new Set(current).add(activeTab)
    })
  }, [activeTab])
  /* oxlint-enable react/set-state-in-effect */

  useEffect(() => {
    let disposed = false
    void getSandboxRuntimeHealth()
      .then((health) => {
        if (!disposed) setRuntimeHealth(health)
      })
      .catch(() => {
        if (!disposed) setRuntimeHealth(null)
      })
      .finally(() => {
        if (!disposed) setRuntimeHealthPending(false)
      })
    return () => {
      disposed = true
    }
  }, [])

  /* oxlint-disable react-hooks/set-state-in-effect -- navigation intent selects the requested Sandbox trace */
  useEffect(() => {
    const sandboxId = initialSandboxId.trim()
    if (!sandboxId || inspectedIntentRef.current === sandboxId) return
    inspectedIntentRef.current = sandboxId
    setActiveTab("trace")
    setTraceIntentPending(true)
    setTraceIntentError("")
    void getSandboxDebugRun(sandboxId)
      .then(setLatestTrace)
      .catch(() => setTraceIntentError("Sandbox trace is unavailable."))
      .finally(() => setTraceIntentPending(false))
  }, [initialSandboxId])
  /* oxlint-enable react-hooks/set-state-in-effect */

  function focusTab(index: number) {
    const normalizedIndex = (index + TABS.length) % TABS.length
    const nextTab = TABS[normalizedIndex]
    setActiveTab(nextTab.id)
    window.requestAnimationFrame(() => {
      document.getElementById(`sandbox-debug-tab-${nextTab.id}`)?.focus()
    })
  }

  function handleTabKeyDown(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (event.key === "ArrowRight") {
      event.preventDefault()
      focusTab(index + 1)
    } else if (event.key === "ArrowLeft") {
      event.preventDefault()
      focusTab(index - 1)
    } else if (event.key === "Home") {
      event.preventDefault()
      focusTab(0)
    } else if (event.key === "End") {
      event.preventDefault()
      focusTab(TABS.length - 1)
    }
  }

  const runtimeReady = Boolean(runtimeHealth?.available && runtimeHealth.daemon_ready)
  const runtimeStatusLabel = runtimeHealthPending
    ? "Checking runtime"
    : runtimeReady
      ? "Docker · Ready"
      : runtimeHealth?.error_code
        ? sandboxDebugErrorFromCode(runtimeHealth.error_code, "Runtime status unavailable")
        : "Runtime status unavailable"

  return (
    <section className="flex h-full min-h-0 flex-col overflow-hidden bg-white">
      <header className="shrink-0 border-b border-slate-200 px-8 pt-7">
        <div className="flex items-start justify-between gap-6">
          <div>
            <h1 className="text-[27px] font-semibold tracking-[-0.035em] text-slate-950">Sandbox Debug Studio</h1>
            <p className="mt-1 text-[13px] text-slate-500">
              Inspect isolated execution, filesystem activity, resource limits and effective sandbox policy.
            </p>
          </div>
          <span
            className={`mt-1 inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-medium ${
              runtimeReady
                ? "border-emerald-200 bg-emerald-50 text-emerald-700"
                : "border-slate-200 bg-slate-50 text-slate-600"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${runtimeReady ? "bg-emerald-500" : "bg-slate-400"}`}
              aria-hidden="true"
            />
            {runtimeStatusLabel}
          </span>
        </div>

        <nav className="mt-5 flex gap-8" aria-label="Sandbox Debug Studio tabs" role="tablist">
          {TABS.map((tab, index) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.id}
              aria-controls={`sandbox-debug-panel-${tab.id}`}
              id={`sandbox-debug-tab-${tab.id}`}
              tabIndex={activeTab === tab.id ? 0 : -1}
              onKeyDown={(event) => handleTabKeyDown(event, index)}
              onClick={() => setActiveTab(tab.id)}
              className={`relative px-1 pb-4 text-[13px] font-medium transition-colors duration-150 ${activeTab === tab.id ? "text-slate-950" : "text-slate-500 hover:text-slate-800"}`}
            >
              {tab.label}
              <span
                className={`absolute inset-x-0 bottom-0 h-[2px] origin-center bg-slate-950 transition-transform duration-200 ${activeTab === tab.id ? "scale-x-100" : "scale-x-0"}`}
                aria-hidden="true"
              />
            </button>
          ))}
        </nav>
      </header>

      <div className="min-h-0 flex-1">
        {TABS.map(({ id }) => {
          const visible = activeTab === id
          if (!visible && !visitedTabs.has(id)) return null

          return (
            <div
              key={id}
              id={`sandbox-debug-panel-${id}`}
              role="tabpanel"
              aria-labelledby={`sandbox-debug-tab-${id}`}
              aria-hidden={!visible}
              className={visible ? "h-full min-h-0 animate-[ragFadeIn_.18s_ease-out]" : "hidden"}
            >
              {id === "trace" && (
                <div className="relative h-full min-h-0">
                  {traceIntentPending ? (
                    <div className="absolute right-5 top-4 z-20 inline-flex items-center gap-2 rounded-[8px] border border-slate-200 bg-white px-3 py-2 text-[10px] text-slate-600 shadow-sm">
                      <LoaderCircle size={12} className="animate-spin" />
                      Loading Sandbox trace…
                    </div>
                  ) : null}
                  {traceIntentError ? (
                    <div className="absolute right-5 top-4 z-20 inline-flex items-center gap-2 rounded-[8px] border border-rose-200 bg-rose-50 px-3 py-2 text-[10px] text-rose-700 shadow-sm" role="alert">
                      <AlertCircle size={12} />
                      {traceIntentError}
                    </div>
                  ) : null}
                  <SandboxDebugTrace health={runtimeHealth} selectedTrace={latestTrace} onTraceChange={setLatestTrace} />
                </div>
              )}
              {id === "filesystem" && <SandboxDebugFilesystem trace={latestTrace} />}
              {id === "resources" && <SandboxDebugResources trace={latestTrace} />}
              {id === "policy" && <SandboxDebugPolicy trace={latestTrace} />}
              {id === "runs" && (
                <SandboxDebugRuns
                  onSelectTrace={(nextTrace) => {
                    setLatestTrace(nextTrace)
                    setActiveTab("trace")
                  }}
                />
              )}
            </div>
          )
        })}
      </div>
    </section>
  )
}
