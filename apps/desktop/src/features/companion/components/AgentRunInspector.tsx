import { useMemo } from "react"
import {
  ArrowLeft,
  Check,
  CheckCircle2,
  CircleAlert,
  CircleDot,
  FileText,
  LoaderCircle,
  Package,
  Wrench,
} from "lucide-react"

import type { AgentRunSnapshot, AgentTraceEvent } from "../../../api/agent"
import type { AgentCitationRef, AgentEvidenceItem } from "../../evidence/evidence-types"
import type {
  CompanionAgentPhase,
  CompanionContextSnapshot,
} from "../companion-runtime"

type ProgressStatus = "pending" | "active" | "complete" | "warning" | "failed"

interface ProgressItem {
  id: string
  sequence: number
  label: string
  detail: string
  status: ProgressStatus
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : ""
}

function count(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0
}

function titleCase(value: string): string {
  return value
    .split("_")
    .filter(Boolean)
    .map((part) => `${part.charAt(0).toUpperCase()}${part.slice(1)}`)
    .join(" ")
}

function eventKey(event: AgentTraceEvent): string {
  const payload = event.payload
  const taskId = text(payload.task_id)
  const toolName = text(payload.tool_name) || text(payload.name)
  if (taskId) return `task:${taskId}`
  if (toolName) return `tool:${toolName}`
  if (event.event_type.startsWith("rag_")) return "rag:retrieval"
  if (event.event_type.startsWith("multi_agent_")) return "multi-agent"
  if (event.event_type === "synthesis_ready" || event.event_type === "grounding_verification_evaluated") return "synthesis"
  return event.event_type
}

function eventLabel(event: AgentTraceEvent): string {
  const payload = event.payload
  const task = text(payload.title) || text(payload.objective) || text(payload.task_name)
  const tool = text(payload.tool_name) || text(payload.name)
  if (task) return task
  if (tool) return titleCase(tool)
  switch (event.event_type) {
    case "agent_start": return "Prepare Agent run"
    case "context_ready": return "Read context"
    case "plan_ready": return text(payload.user_visible_reason) || "Plan next action"
    case "synthesis_ready": return "Synthesize response"
    case "grounding_verification_evaluated": return "Verify grounding"
    case "failure": return "Agent failure"
    case "cancelled": return "Stop Agent run"
    default: return titleCase(event.event_type)
  }
}

function eventDetail(event: AgentTraceEvent): string {
  const payload = event.payload
  const raw = text(payload.detail)
    || text(payload.message)
    || text(payload.reason)
    || text(payload.user_visible_reason)
    || text(payload.output_text)
  if (raw) return raw.length > 130 ? `${raw.slice(0, 127)}…` : raw
  const evidence = count(payload.evidence_count) || count(payload.final_count)
  return evidence > 0 ? `${evidence} evidence items reported.` : "Runtime event received."
}

function eventStatus(event: AgentTraceEvent): ProgressStatus {
  if (["task_failed", "failure", "artifact_rejected", "multi_agent_specialist_failed"].includes(event.event_type)) return "failed"
  if (["task_partial", "task_blocked", "retry", "rag_fallback", "budget_exhausted", "workflow_partial"].includes(event.event_type)) return "warning"
  if (["task_completed", "task_skipped", "tool_result", "synthesis_ready", "grounding_verification_evaluated", "agent_end", "knowledge_retrieved", "rag_evidence_selected"].includes(event.event_type)) return "complete"
  return "active"
}

export function deriveChatAgentProgress(
  events: AgentTraceEvent[],
  phase: CompanionAgentPhase,
): ProgressItem[] {
  const grouped = new Map<string, ProgressItem>()
  for (const event of [...events].sort((left, right) => left.sequence - right.sequence)) {
    const id = eventKey(event)
    const next: ProgressItem = {
      id,
      sequence: event.sequence,
      label: eventLabel(event),
      detail: eventDetail(event),
      status: eventStatus(event),
    }
    const previous = grouped.get(id)
    grouped.set(id, previous ? { ...previous, ...next } : next)
  }

  const items = [...grouped.values()].sort((left, right) => left.sequence - right.sequence)
  if (phase === "running" || phase === "cancelling") {
    const current = [...items].reverse().find((item) => item.status === "active")
    if (current) current.status = "active"
  }
  return items
}

function StatusIcon({ status }: { status: ProgressStatus }) {
  if (status === "complete") return <span className="ait-chat-run-status is-complete"><Check size={12} /></span>
  if (status === "failed") return <span className="ait-chat-run-status is-failed"><CircleAlert size={12} /></span>
  if (status === "warning") return <span className="ait-chat-run-status is-warning"><CircleAlert size={12} /></span>
  if (status === "active") return <span className="ait-chat-run-status is-active"><LoaderCircle size={12} /></span>
  return <span className="ait-chat-run-status"><CircleDot size={11} /></span>
}

function ArtifactCard({ artifact }: { artifact: AgentRunSnapshot["artifacts"][number] }) {
  const title = text(artifact.content.title) || text(artifact.content.name) || titleCase(artifact.kind) || "Verified artifact"
  const coverage = artifact.source_coverage?.complete
    ? "Source coverage complete"
    : artifact.source_coverage?.missing_refs?.length
      ? `${artifact.source_coverage.missing_refs.length} source gaps`
      : "Verification reported"
  return (
    <div className="ait-chat-run-artifact">
      <span className="ait-chat-run-artifact-icon"><Package size={16} /></span>
      <span className="ait-chat-run-artifact-copy">
        <strong>{title}</strong>
        <small>{titleCase(artifact.kind)} · v{artifact.version} · {coverage}</small>
      </span>
      <span className={`ait-chat-run-artifact-status ${artifact.verification_status === "verified" ? "is-good" : ""}`}>
        {artifact.verification_status || "pending"}
      </span>
    </div>
  )
}

export function AgentRunInspector({
  context,
  phase,
  runId,
  traceId,
  events,
  snapshot,
  selectedTools,
  confirmationTool,
  evidence,
  citations,
  knowledgeDocumentIds,
  onViewContext,
  onConfirmWrite,
}: {
  context: CompanionContextSnapshot
  phase: CompanionAgentPhase
  runId: string
  traceId: string
  events: AgentTraceEvent[]
  snapshot: AgentRunSnapshot | null
  selectedTools: string[]
  confirmationTool: string
  evidence: AgentEvidenceItem[]
  citations: AgentCitationRef[]
  knowledgeDocumentIds: string[]
  onViewContext: () => void
  onConfirmWrite: () => void
}) {
  const progress = useMemo(() => deriveChatAgentProgress(events, phase), [events, phase])
  const actualTools = useMemo(() => {
    const names = events
      .map((event) => text(event.payload.tool_name) || text(event.payload.name))
      .filter(Boolean)
    return [...new Set(names)]
  }, [events])
  const contextTitle = context.resource_title || context.section_heading || "Reading context"
  const phaseLabel = phase === "cancelling" ? "Stopping" : phase === "confirmation_required" ? "Confirmation required" : phase === "error" ? "Run failed" : phase === "completed" ? "Completed" : phase === "cancelled" ? "Cancelled" : "Working"

  return (
    <aside className="ait-chat-run-inspector ait-context-panel-enter" aria-label="Agent run inspector">
      <div className="ait-chat-run-header">
        <div>
          <p className="ait-chat-section-eyebrow">Agent run</p>
          <h2 className="ait-chat-run-title">{phaseLabel}</h2>
          <p className="ait-chat-run-meta">{runId ? `Run ${runId.slice(0, 12)}` : "Starting a bounded run"}</p>
        </div>
        <button type="button" className="ait-chat-run-context-button" onClick={onViewContext}>
          <ArrowLeft size={14} /> Context
        </button>
      </div>

      <section className="ait-chat-run-section">
        <div className="ait-chat-run-section-heading">
          <span><CircleDot size={16} /> Progress</span>
          <small>{progress.filter((item) => item.status === "complete").length}/{progress.length || 0}</small>
        </div>
        {progress.length > 0 ? (
          <div className="ait-chat-run-progress">
            {progress.map((item) => (
              <div key={item.id} className="ait-chat-run-progress-item">
                <StatusIcon status={item.status} />
                <div className="ait-chat-run-progress-copy">
                  <strong>{item.label}</strong>
                  <p>{item.detail}</p>
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="ait-chat-run-empty">Waiting for the first Agent activity event…</p>
        )}
      </section>

      <section className="ait-chat-run-section">
        <div className="ait-chat-run-section-heading">
          <span><Package size={16} /> Artifacts</span>
          <small>{snapshot?.artifacts.length ?? 0}</small>
        </div>
        {snapshot?.artifacts.length ? (
          <div className="ait-chat-run-artifacts">
            {snapshot.artifacts.map((artifact) => <ArtifactCard key={`${artifact.artifact_id}:${artifact.version}`} artifact={artifact} />)}
          </div>
        ) : (
          <p className="ait-chat-run-empty">Verified artifacts returned by this run will appear here.</p>
        )}
      </section>

      <section className="ait-chat-run-section">
        <div className="ait-chat-run-section-heading">
          <span><FileText size={16} /> Context</span>
          <small>{evidence.length + citations.length}</small>
        </div>
        {context.source_text && (
          <div className="ait-chat-run-context-card">
            <p className="ait-chat-card-eyebrow">{contextTitle}</p>
            <p>{context.source_text}</p>
          </div>
        )}
        <div className="ait-chat-run-context-list">
          <div><span>Evidence</span><strong>{evidence.length} items · {citations.length} citations</strong></div>
          <div><span>Knowledge</span><strong>{knowledgeDocumentIds.length > 0 ? `${knowledgeDocumentIds.length} selected documents` : "Automatic scope"}</strong></div>
          <div><span>Tools used</span><strong>{actualTools.length > 0 ? actualTools.join(", ") : selectedTools.length > 0 ? selectedTools.join(", ") : "None yet"}</strong></div>
        </div>
        {traceId && <p className="ait-chat-run-trace">Trace {traceId.slice(0, 18)}</p>}
      </section>

      {phase === "confirmation_required" && (
        <div className="ait-chat-run-confirmation">
          <Wrench size={15} />
          <div>
            <strong>Approval required before write action</strong>
            <p>
              {confirmationTool || "A write tool"} is waiting for your confirmation. No persistent change has been executed yet.
            </p>
            <button type="button" onClick={onConfirmWrite}>
              <CheckCircle2 size={14} /> Approve and execute
            </button>
          </div>
        </div>
      )}
    </aside>
  )
}
