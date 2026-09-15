import { Bot } from "lucide-react"

import { AITPanel } from "@/shared/components/AITPanel"
import type { AgentWorkspacePhase } from "../../agent/state/agent-workspace-state"
import { CitedAnswer } from "../../evidence/CitedAnswer"
import type { AgentCitationRef, AgentEvidenceItem } from "../../evidence/evidence-types"

export function AgentMessage({
  content,
  phase,
  provider,
  model,
  evidence,
  citations,
}: {
  content: string
  phase: AgentWorkspacePhase
  provider: string
  model: string
  evidence: AgentEvidenceItem[]
  citations: AgentCitationRef[]
}) {
  return (
    <AITPanel className="p-5">
      <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
        <Bot size={16} />
        Agent response
      </div>

      {phase === "idle" ? (
        <p className="mt-4 text-sm leading-6 text-slate-500">
          The Agent response will appear here after a traced run.
        </p>
      ) : null}

      {phase === "running" && !content ? (
        <p className="mt-4 text-sm leading-6 text-slate-500">Planning and executing the bounded workflow…</p>
      ) : null}

      {phase === "cancelling" && !content ? (
        <p className="mt-4 text-sm leading-6 text-slate-500">The current response will stop when cancellation reaches a safe checkpoint.</p>
      ) : null}

      {phase === "confirmation_required" && !content ? (
        <p className="mt-4 text-sm leading-6 text-slate-500">
          The Agent is waiting for a decision before it can continue this task.
        </p>
      ) : null}

      {(phase === "error" || phase === "cancelled") && !content ? (
        <p className="mt-4 text-sm leading-6 text-slate-500">
          No final response was produced for this run. See the Agent decision above for details.
        </p>
      ) : null}

      {content ? (
        <CitedAnswer content={content} evidence={evidence} citations={citations} />
      ) : null}

      {provider || model ? (
        <p className="mt-4 text-[11px] text-slate-400">
          {[provider, model].filter(Boolean).join(" · ")}
        </p>
      ) : null}
    </AITPanel>
  )
}
