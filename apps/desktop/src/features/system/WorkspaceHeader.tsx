import { Activity } from "lucide-react"

import type { LlmRuntimeStatus, LlmRuntimeState } from "../../api/llm-settings"

const stateLabel: Record<LlmRuntimeState, string> = {
  available: "LLM available",
  calling: "LLM calling…",
  unavailable: "LLM unavailable",
}

const stateDot: Record<LlmRuntimeState, string> = {
  available: "bg-emerald-500",
  calling: "animate-pulse bg-amber-400",
  unavailable: "bg-red-500",
}

export default function WorkspaceHeader({
  title,
  description,
  llmStatus,
}: {
  title: string
  description: string
  llmStatus: LlmRuntimeStatus
}) {
  const label = stateLabel[llmStatus.state]

  return (
    <header className="workspace-header">
      <div className="workspace-header-inner">
        <div className="min-w-0">
          <h1 className="workspace-title">{title}</h1>
          <p className="workspace-description">{description}</p>
        </div>

        <details className="group relative shrink-0">
          <summary
            className="workspace-status"
            aria-label={`LLM status: ${label}`}
            title={label}
            data-llm-state={llmStatus.state}
          >
            <span
              className={`h-2 w-2 rounded-full ${stateDot[llmStatus.state]}`}
              data-testid="llm-status-dot"
            />
            <Activity size={14} strokeWidth={1.8} />
          </summary>

          <div className="ait-system-popover absolute right-0 top-full z-50 mt-2 w-[300px] overflow-hidden rounded-[16px] border border-slate-200/80 bg-white/98 p-2.5 shadow-[0_20px_60px_rgba(15,23,42,0.16)] backdrop-blur-xl">
            <p className="px-2 pb-2 pt-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-slate-400">
              LLM status
            </p>
            <StatusRow label="State" value={label} />
            <StatusRow label="Provider" value={llmStatus.provider || "Not configured"} />
            <StatusRow label="Model" value={llmStatus.model || "Not loaded"} />
            {llmStatus.detail && <StatusRow label="Detail" value={llmStatus.detail} />}
          </div>
        </details>
      </div>
    </header>
  )
}

function StatusRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-4 rounded-[10px] px-2 py-2 hover:bg-slate-50">
      <div className="flex items-center gap-2 text-xs text-slate-500">
        <span>{label}</span>
      </div>
      <span className="max-w-[170px] break-all text-right text-xs font-medium text-slate-700">{value}</span>
    </div>
  )
}
