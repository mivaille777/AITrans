import { useEffect, useState } from "react"

import {
  getSandboxRuntimeHealth,
  type SandboxRuntimeHealth,
} from "../../api/sandbox-debug"
import SandboxDebugTrace from "./SandboxDebugTrace"

type SandboxDebugTab = "trace" | "filesystem" | "resources" | "policy" | "runs"

const TABS: Array<{ id: SandboxDebugTab; label: string }> = [
  { id: "trace", label: "Trace" },
  { id: "filesystem", label: "Filesystem" },
  { id: "resources", label: "Resources" },
  { id: "policy", label: "Policy" },
  { id: "runs", label: "Runs" },
]

const EMPTY_STATES: Record<Exclude<SandboxDebugTab, "trace">, { title: string; description: string }> = {
  filesystem: {
    title: "No filesystem activity recorded",
    description: "Run a Sandbox trace with workspace input to inspect staged files and file access.",
  },
  resources: {
    title: "No resource samples recorded",
    description: "CPU, memory, PID and output usage will appear here for the selected Sandbox run.",
  },
  policy: {
    title: "No effective policy recorded",
    description: "The security policy enforced for a Sandbox run will appear here once runtime data is available.",
  },
  runs: {
    title: "No sandbox runs recorded",
    description: "Sandbox execution history will appear here after the runtime API is connected.",
  },
}

export default function SandboxDebugStudio() {
  const [activeTab, setActiveTab] = useState<SandboxDebugTab>("trace")
  const [visitedTabs, setVisitedTabs] = useState<Set<SandboxDebugTab>>(() => new Set(["trace"]))
  const [runtimeHealth, setRuntimeHealth] = useState<SandboxRuntimeHealth | null>(null)
  const [runtimeHealthPending, setRuntimeHealthPending] = useState(true)

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

  const runtimeReady = Boolean(runtimeHealth?.available && runtimeHealth.daemon_ready)

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
            {runtimeHealthPending
              ? "Checking runtime"
              : runtimeReady
                ? "Docker · Ready"
                : "Runtime status unavailable"}
          </span>
        </div>

        <nav className="mt-5 flex gap-8" aria-label="Sandbox Debug Studio tabs" role="tablist">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.id}
              aria-controls={`sandbox-debug-panel-${tab.id}`}
              id={`sandbox-debug-tab-${tab.id}`}
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
              {id === "trace"
                ? <SandboxDebugTrace health={runtimeHealth} />
                : <SandboxEmptyState tab={id} />}
            </div>
          )
        })}
      </div>
    </section>
  )
}

function SandboxEmptyState({ tab }: { tab: Exclude<SandboxDebugTab, "trace"> }) {
  const emptyState = EMPTY_STATES[tab]
  return (
    <div className="flex h-full items-center justify-center overflow-auto px-8 py-10">
      <div className="w-full max-w-3xl rounded-[10px] border border-slate-200 bg-white px-8 py-10 text-center shadow-[0_1px_2px_rgba(15,23,42,0.03)]">
        <p className="text-[11px] font-semibold uppercase tracking-[0.12em] text-slate-400">
          Sandbox / {TABS.find((item) => item.id === tab)?.label}
        </p>
        <h2 className="mt-3 text-[16px] font-semibold text-slate-900">{emptyState.title}</h2>
        <p className="mx-auto mt-2 max-w-xl text-[12px] leading-5 text-slate-500">{emptyState.description}</p>
      </div>
    </div>
  )
}
