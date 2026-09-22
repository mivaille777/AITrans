import { Bot, CircleDot, LoaderCircle } from "lucide-react"

import { AITPanel } from "@/shared/components/AITPanel"
import type { AgentWorkspacePhase } from "../agent-workspace-state"

const phaseLabel: Record<AgentWorkspacePhase, string> = {
  idle: "Ready",
  queued: "Queued",
  running: "Running",
  pausing: "Pausing",
  paused: "Paused",
  recovering: "Recovering",
  waiting: "Waiting",
  cancelling: "Cancelling",
  cancelled: "Cancelled",
  completed: "Completed",
  failed: "Failed",
  confirmation_required: "Waiting for confirmation",
  error: "Error",
}

export function AgentHeader({ phase, uiMode }: { phase: AgentWorkspacePhase; uiMode: string }) {
  const running = ["queued", "running", "pausing", "recovering", "cancelling"].includes(phase)

  return (
    <AITPanel className="p-5">
      <div className="flex items-center justify-between gap-4">
        <div className="flex items-center gap-3">
          <span className="flex h-10 w-10 items-center justify-center rounded-[14px] bg-slate-950 text-white">
            <Bot size={18} strokeWidth={1.8} />
          </span>
          <div>
            <strong className="block text-sm font-semibold text-slate-950">AI Translator Agent</strong>
            <small className="mt-1 block text-xs text-slate-500">
              Agent Core · {uiMode || "assistant"}
            </small>
          </div>
        </div>
        <div className="flex items-center gap-2 rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 text-xs font-medium text-slate-600">
          {running ? (
            <LoaderCircle size={13} className="animate-spin" />
          ) : (
            <CircleDot size={13} />
          )}
          {phaseLabel[phase]}
        </div>
      </div>
    </AITPanel>
  )
}
