import type { AgentRunTraceResponse, AgentTraceEvent, AgentTraceEventType } from "../../../api/agent"
import type { DurableAgentRunRecord } from "../../../api/agent-runtime"
import type { AgentCitationRef, AgentEvidenceItem } from "../../evidence/evidence-types"

export type AgentWorkspacePhase =
  | "idle"
  | "queued"
  | "running"
  | "pausing"
  | "paused"
  | "recovering"
  | "waiting"
  | "cancelling"
  | "cancelled"
  | "completed"
  | "failed"
  | "confirmation_required"
  | "error"

export type AgentActivityTone = "neutral" | "success" | "warning"

export interface AgentActivityItem {
  sequence: number
  eventType: AgentTraceEventType
  label: string
  detail: string
  tone: AgentActivityTone
  payload?: Record<string, unknown>
  stepId?: string
  toolCallId?: string
}

export interface AgentWorkspaceViewState {
  phase: AgentWorkspacePhase
  uiMode: string
  outputText: string
  provider: string
  model: string
  runId: string
  traceId: string
  totalDurationMs: number
  confirmationTool: string
  activities: AgentActivityItem[]
  errorMessage: string
  evidence: AgentEvidenceItem[]
  citations: AgentCitationRef[]
}

function text(value: unknown): string {
  return typeof value === "string" ? value : ""
}

function numeric(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0
}

function withDuration(detail: string, payload: Record<string, unknown>): string {
  const duration = numeric(payload.duration_ms)
  return duration > 0 ? `${detail} · ${duration} ms` : detail
}

function reactIteration(payload: Record<string, unknown>): string {
  const iteration = numeric(payload.iteration)
  return iteration > 0 ? ` #${iteration}` : ""
}

function knowledgeMode(payload: Record<string, unknown>): string {
  const mode = text(payload.mode)
  if (mode === "always") return "Always"
  if (mode === "never") return "Never"
  return "Auto"
}

function knowledgeScope(payload: Record<string, unknown>): string {
  const strategy = text(payload.strategy)
  if (strategy === "attached_document") return "Current document"
  if (strategy === "explicit_documents") {
    const documents = numeric(payload.document_count)
    return `${documents || "Selected"} documents`
  }
  if (strategy === "research_workspace") return "Research workspace"
  if (strategy === "global_knowledge") return "All knowledge"
  return "No knowledge scope"
}

function scopeCounts(payload: Record<string, unknown>): string {
  const documents = numeric(payload.document_count)
  const sources = numeric(payload.research_source_count)
  const counts = [
    documents > 0 ? `${documents} document${documents === 1 ? "" : "s"}` : "",
    sources > 0 ? `${sources} source${sources === 1 ? "" : "s"}` : "",
  ].filter(Boolean)
  return counts.join(" · ")
}

function titleCaseEvent(eventType: AgentTraceEventType): string {
  return eventType
    .split("_")
    .filter(Boolean)
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ")
}

function eventToActivity(event: AgentTraceEvent): AgentActivityItem {
  const payload = event.payload
  switch (event.event_type) {
    case "agent_start":
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: "Agent started",
        detail: text(payload.run_id) || text(payload.session_id) || "Preparing this run.",
        tone: "neutral",
      }
    case "context_ready":
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: "Context ready",
        detail: text(payload.resource_title) || text(payload.section_heading) || "Reading context attached.",
        tone: "success",
      }
    case "knowledge_decision": {
      const shouldRetrieve = payload.should_retrieve === true
      const reason = text(payload.reason_code)
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: "Knowledge decision",
        detail: `${knowledgeMode(payload)} · retrieval ${shouldRetrieve ? "required" : "skipped"}${reason ? ` · ${reason}` : ""}`,
        tone: shouldRetrieve ? "neutral" : "success",
      }
    }
    case "knowledge_scope_resolved": {
      const counts = scopeCounts(payload)
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: "Knowledge scope",
        detail: `${knowledgeScope(payload)}${counts ? ` · ${counts}` : ""}`,
        tone: "success",
      }
    }
    case "knowledge_skipped":
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: "Knowledge skipped",
        detail: `Reason: ${text(payload.reason_code) || "knowledge_policy"}`,
        tone: "success",
      }
    case "knowledge_retrieval_started":
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: "Knowledge retrieval started",
        detail: "Preparing knowledge evidence for the Agent.",
        tone: "neutral",
      }
    case "knowledge_retrieved": {
      const citations = numeric(payload.citation_count)
      const contextChars = numeric(payload.context_chars)
      const facts = [
        citations > 0 ? `${citations} citations` : "",
        contextChars > 0 ? `${contextChars.toLocaleString()} context chars` : "",
      ].filter(Boolean)
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: "Knowledge retrieval complete",
        detail: facts.length > 0 ? facts.join(" · ") : "Knowledge evidence is ready.",
        tone: "success",
      }
    }
    case "plan_ready": {
      const action = text(payload.action)
      const toolName = text(payload.tool_name)
      const mode = text(payload.mode)
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: mode === "react" ? "Adaptive execution selected" : toolName ? `Plan ready: ${toolName}` : "Plan ready",
        detail: withDuration(
          mode === "react"
            ? "This complex request will choose one bounded action at a time."
            : text(payload.user_visible_reason) || (action === "answer" ? "The Agent will answer directly." : "The Agent selected its next action."),
          payload,
        ),
        tone: "neutral",
      }
    }
    case "react_started": {
      const maxIterations = numeric(payload.max_iterations)
      const maxToolCalls = numeric(payload.max_tool_calls)
      const limits = [
        maxIterations > 0 ? `${maxIterations} decisions` : "",
        maxToolCalls > 0 ? `${maxToolCalls} tool calls` : "",
      ].filter(Boolean)
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: "ReAct loop started",
        detail: limits.length > 0
          ? `Adaptive execution is bounded to ${limits.join(" · ")}.`
          : "Adaptive execution started with bounded runtime limits.",
        tone: "neutral",
      }
    }
    case "decision_ready": {
      const kind = text(payload.kind)
      const toolName = text(payload.tool_name)
      const summary = text(payload.action_summary)
      const isFinal = kind === "final"
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: isFinal
          ? `Decision${reactIteration(payload)}: finish`
          : `Decision${reactIteration(payload)}: ${toolName || "tool"}`,
        detail: summary || (isFinal
          ? "The Agent has enough information to finish."
          : "The Agent selected the next bounded tool action."),
        tone: "neutral",
      }
    }
    case "tool_call": {
      const toolName = text(payload.name) || "tool"
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: `Tool planned: ${toolName}`,
        detail: "The Agent selected a bounded tool. Execution is confirmed by a tool result.",
        tone: "neutral",
      }
    }
    case "retry": {
      const toolName = text(payload.tool_name) || "tool"
      const attempt = numeric(payload.attempt)
      const maxAttempts = numeric(payload.max_attempts)
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: `Retrying ${toolName}`,
        detail: `${attempt > 0 && maxAttempts > 0 ? `Attempt ${attempt}/${maxAttempts}. ` : ""}${text(payload.reason) || "Transient tool failure."}`,
        tone: "warning",
      }
    }
    case "tool_result": {
      const toolName = text(payload.tool_name) || "Tool"
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: `${toolName} completed`,
        detail: withDuration(text(payload.provider) || "Tool result returned to the Agent.", payload),
        tone: "success",
      }
    }
    case "observation_ready": {
      const toolName = text(payload.tool_name) || "tool"
      const evidenceCount = numeric(payload.evidence_count)
      const citationCount = numeric(payload.citation_count)
      const facts = [
        evidenceCount > 0 ? `${evidenceCount} evidence` : "",
        citationCount > 0 ? `${citationCount} citations` : "",
      ].filter(Boolean)
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: `Observation${reactIteration(payload)}: ${toolName}`,
        detail: facts.length > 0
          ? `Observation recorded · ${facts.join(" · ")}.`
          : "A compact tool observation is ready for the next decision.",
        tone: payload.success === false ? "warning" : "success",
      }
    }
    case "evidence_gate_evaluated": {
      const action = text(payload.action)
      const evidenceCount = numeric(payload.evidence_count)
      const searchCount = numeric(payload.search_count)
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: "Evidence gate",
        detail: `${action || "assessed"}${evidenceCount > 0 ? ` · ${evidenceCount} evidence` : ""}${searchCount > 0 ? ` · ${searchCount} search${searchCount === 1 ? "" : "es"}` : ""}`,
        tone: action === "stop" ? "success" : "neutral",
      }
    }
    case "evidence_sufficiency": {
      const sufficient = payload.sufficient === true
      const reason = text(payload.reason)
      const missing = Array.isArray(payload.missing_information)
        ? payload.missing_information.filter((item): item is string => typeof item === "string" && Boolean(item.trim())).join(", ")
        : ""
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: sufficient ? "Evidence ready" : "Evidence sufficiency",
        detail: `${sufficient ? "Evidence is sufficient" : "More evidence may be needed"}${reason ? ` · ${reason}` : ""}${missing ? ` · Missing: ${missing}` : ""}`,
        tone: sufficient ? "success" : "warning",
      }
    }
    case "react_limit_reached": {
      const reason = text(payload.reason)
      const toolCallCount = numeric(payload.tool_call_count)
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: "ReAct budget reached",
        detail: `${reason || "Adaptive execution reached its configured limit."}${toolCallCount > 0 ? ` · ${toolCallCount} tool calls` : ""}`,
        tone: "warning",
      }
    }
    case "rag_query_started":
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: "RAG retrieval",
        detail: text(payload.retrieval_strategy) || "Preparing local hybrid retrieval.",
        tone: "neutral",
      }
    case "rag_query_rewritten": {
      const count = numeric(payload.subquery_count)
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: "Retrieval query prepared",
        detail: `${count || 1} bounded ${count === 1 ? "query" : "queries"}${payload.rewritten === true ? " after rewrite" : ""}.`,
        tone: "success",
      }
    }
    case "rag_dense_completed":
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: "Dense retrieval complete",
        detail: withDuration(`${numeric(payload.dense_count)} candidates`, {
          duration_ms: numeric(payload.embedding_ms) + numeric(payload.dense_search_ms),
        }),
        tone: "success",
      }
    case "rag_sparse_completed":
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: "Sparse retrieval complete",
        detail: withDuration(`${numeric(payload.sparse_count)} candidates`, {
          duration_ms: payload.sparse_search_ms,
        }),
        tone: "success",
      }
    case "rag_fusion_completed":
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: "Hybrid results fused",
        detail: withDuration(`${numeric(payload.fusion_count)} fused candidates`, {
          duration_ms: payload.fusion_ms,
        }),
        tone: "success",
      }
    case "rag_rerank_completed":
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: "Evidence reranked",
        detail: withDuration(`${numeric(payload.final_count)} final candidates`, {
          duration_ms: payload.rerank_ms,
        }),
        tone: "success",
      }
    case "rag_evidence_selected":
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: "Evidence ready",
        detail: withDuration(`${numeric(payload.final_count)} verified sources`, {
          duration_ms: payload.total_rag_ms,
        }),
        tone: "success",
      }
    case "rag_fallback":
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: "Retrieval fallback",
        detail: text(payload.fallback_reason) || "No verified evidence was selected.",
        tone: "warning",
      }
    case "synthesis_ready":
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: "Response synthesized",
        detail: withDuration(text(payload.model) || text(payload.provider) || "Final response generated.", payload),
        tone: "success",
      }
    case "failure":
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: `Failed: ${text(payload.stage) || "runtime"}`,
        detail: `${text(payload.message) || "Agent execution failed."}${text(payload.fallback_reason) ? ` · ${text(payload.fallback_reason)}` : ""}`,
        tone: "warning",
      }
    case "cancelled":
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: "Agent cancelled",
        detail: text(payload.message) || "Cancellation reached a safe checkpoint.",
        tone: "warning",
      }
    case "agent_end": {
      const status = text(payload.status)
      const needsConfirmation = status === "confirmation_required"
      const failed = status === "failed"
      const cancelled = status === "cancelled"
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: needsConfirmation ? "Confirmation required" : failed ? "Agent failed" : cancelled ? "Agent cancelled" : "Agent completed",
        detail: withDuration(text(payload.intent) || text(payload.ui_mode) || "Run finished.", {
          duration_ms: payload.total_duration_ms,
        }),
        tone: needsConfirmation || failed || cancelled ? "warning" : "success",
      }
    }
    default: {
      const actor = text(payload.actor)
      const status = text(payload.status)
      const warning = status === "warning" || status === "failed" || event.event_type.endsWith("_failed")
      return {
        sequence: event.sequence,
        eventType: event.event_type,
        label: titleCaseEvent(event.event_type),
        detail: actor ? `${actor}${status ? ` · ${status}` : ""}` : status || "Runtime lifecycle event.",
        tone: warning ? "warning" : status === "complete" ? "success" : "neutral",
      }
    }
  }
}

function activitySource(
  trace: AgentRunTraceResponse | null,
  liveEvents: AgentTraceEvent[],
): AgentTraceEvent[] {
  if (liveEvents.length > 0) return liveEvents
  return trace?.events ?? []
}

export function deriveAgentWorkspaceState({
  trace,
  liveEvents = [],
  pending = false,
  cancelRequested = false,
  cancelledMessage = "",
  errorMessage = "",
  durableRun = null,
}: {
  trace: AgentRunTraceResponse | null
  liveEvents?: AgentTraceEvent[]
  pending?: boolean
  cancelRequested?: boolean
  cancelledMessage?: string
  errorMessage?: string
  durableRun?: DurableAgentRunRecord | null
}): AgentWorkspaceViewState {
  const activities = activitySource(trace, liveEvents).map((event) => ({
    ...eventToActivity(event),
    payload: event.payload,
    stepId: event.step_id ?? text(event.payload.step_id),
    toolCallId: event.tool_call_id ?? text(event.payload.tool_call_id),
  }))
  const shared = {
    uiMode: trace?.ui_mode ?? "assistant",
    outputText: trace?.run.output_text ?? "",
    provider: trace?.run.provider ?? "",
    model: trace?.run.model ?? "",
    runId: durableRun?.run_id ?? trace?.run_id ?? liveEvents.at(-1)?.run_id ?? "",
    traceId: durableRun?.trace_id ?? trace?.trace_id ?? liveEvents.at(-1)?.trace_id ?? "",
    totalDurationMs: trace?.total_duration_ms ?? liveEvents.at(-1)?.elapsed_ms ?? 0,
    activities,
    evidence: trace?.run.evidence ?? [],
    citations: trace?.run.citations ?? [],
  }

  if (durableRun) {
    const confirmationRequired = durableRun.status === "waiting"
      && trace?.run.status === "confirmation_required"
    const phaseByStatus: Record<DurableAgentRunRecord["status"], AgentWorkspacePhase> = {
      queued: "queued",
      running: cancelRequested ? "cancelling" : "running",
      waiting: confirmationRequired ? "confirmation_required" : "waiting",
      pause_requested: "pausing",
      paused: "paused",
      recovering: "recovering",
      completed: "completed",
      failed: "failed",
      cancelled: "cancelled",
    }
    const phase = phaseByStatus[durableRun.status]
    return {
      ...shared,
      phase,
      confirmationTool: confirmationRequired ? trace?.run.plan.tool_name ?? "" : "",
      errorMessage: phase === "failed" ? errorMessage || "Agent run failed." : (
        phase === "cancelled" ? cancelledMessage : ""
      ),
    }
  }

  if (errorMessage) {
    return {
      ...shared,
      phase: "error",
      confirmationTool: "",
      errorMessage,
    }
  }

  if (cancelledMessage) {
    return {
      ...shared,
      phase: "cancelled",
      confirmationTool: "",
      errorMessage: cancelledMessage,
    }
  }

  if (pending) {
    return {
      ...shared,
      phase: cancelRequested ? "cancelling" : "running",
      confirmationTool: "",
      errorMessage: "",
    }
  }

  if (!trace) {
    return {
      ...shared,
      phase: "idle",
      confirmationTool: "",
      errorMessage: "",
    }
  }

  const confirmationRequired = trace.run.status === "confirmation_required"
  return {
    ...shared,
    phase: confirmationRequired ? "confirmation_required" : "completed",
    confirmationTool: confirmationRequired ? trace.run.plan.tool_name : "",
    errorMessage: "",
  }
}
