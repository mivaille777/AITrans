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

      {["queued", "running", "pausing", "recovering"].includes(phase) && !content ? (
        <p className="mt-4 text-sm leading-6 text-slate-500">
          {phase === "queued"
            ? "The durable run is queued for execution."
            : phase === "pausing"
              ? "Pause requested. The Agent will stop at the next safe checkpoint."
              : phase === "recovering"
                ? "Recovering the durable run from its latest checkpoint…"
                : "Planning and executing the bounded workflow…"}
        </p>
      ) : null}

      {phase === "paused" && !content ? (
        <p className="mt-4 text-sm leading-6 text-slate-500">
          This run is paused at a safe checkpoint and can be resumed without replaying completed work.
        </p>
      ) : null}

      {phase === "waiting" && !content ? (
        <p className="mt-4 text-sm leading-6 text-slate-500">
          The durable run is waiting for a runtime condition before it can continue.
        </p>
      ) : null}

      {phase === "cancelling" && !content ? (
        <p className="mt-4 text-sm leading-6 text-slate-500">The current response will stop when cancellation reaches a safe checkpoint.</p>
      ) : null}

      {phase === "confirmation_required" && !content ? (
        <p className="mt-4 text-sm leading-6 text-slate-500">
          The Agent is waiting for a decision before it can continue this task.
        </p>
      ) : null}

      {(phase === "error" || phase === "failed" || phase === "cancelled") && !content ? (
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
