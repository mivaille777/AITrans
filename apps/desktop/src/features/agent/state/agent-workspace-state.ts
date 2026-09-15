import type { AgentRunTraceResponse, AgentTraceEvent, AgentTraceEventType } from "../../../api/agent"
import type { AgentCitationRef, AgentEvidenceItem } from "../../evidence/evidence-types"

export type AgentWorkspacePhase =
  | "idle"
  | "running"
  | "cancelling"
  | "cancelled"
  | "completed"
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
        label: "Knowledge retrieval started",
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
        label: "Evidence selected",
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
}: {
  trace: AgentRunTraceResponse | null
  liveEvents?: AgentTraceEvent[]
  pending?: boolean
  cancelRequested?: boolean
  cancelledMessage?: string
  errorMessage?: string
}): AgentWorkspaceViewState {
  const activities = activitySource(trace, liveEvents).map((event) => ({
    ...eventToActivity(event),
    payload: event.payload,
  }))
  const shared = {
    uiMode: trace?.ui_mode ?? "assistant",
    outputText: trace?.run.output_text ?? "",
    provider: trace?.run.provider ?? "",
    model: trace?.run.model ?? "",
    runId: trace?.run_id ?? liveEvents.at(-1)?.run_id ?? "",
    traceId: trace?.trace_id ?? liveEvents.at(-1)?.trace_id ?? "",
    totalDurationMs: trace?.total_duration_ms ?? liveEvents.at(-1)?.elapsed_ms ?? 0,
    activities,
    evidence: trace?.run.evidence ?? [],
    citations: trace?.run.citations ?? [],
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
