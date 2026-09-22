import { apiGet, apiPost, apiWebSocketUrl } from "./client"
import type { AgentRunRequest, AgentRunResponse, AgentTraceEvent } from "./agent"

export type DurableAgentRunStatus =
  | "queued"
  | "running"
  | "waiting"
  | "pause_requested"
  | "paused"
  | "recovering"
  | "completed"
  | "failed"
  | "cancelled"

export type AgentRuntimeProfile = "interactive" | "long_task"

export interface DurableAgentRunRecord {
  task_id: string
  run_id: string
  trace_id: string
  runtime_profile: AgentRuntimeProfile
  status: DurableAgentRunStatus
  created_at: string
  updated_at: string
  started_at: string | null
  finished_at: string | null
  graph_version: string
  state_schema_version: number
  checkpoint_id: string
  budget_used_ms: number
}

export interface DurableAgentRunResult {
  status: DurableAgentRunStatus
  result: AgentRunResponse | Record<string, unknown> | null
}

export type DurableAgentRuntimeStreamEvent =
  | { type: "run"; run: DurableAgentRunRecord }
  | { type: "event"; event: AgentTraceEvent }
  | { type: "terminal"; run: DurableAgentRunRecord; last_sequence: number }
  | { type: "error"; code: string; message: string }

export interface DurableAgentRuntimeStreamHandlers {
  onEvent: (event: DurableAgentRuntimeStreamEvent) => void
  onTransportError: (error: Error) => void
}

export interface DurableAgentRuntimeStreamHandle {
  close: () => void
}

export function createAgentRuntimeRun(
  request: AgentRunRequest,
  runtimeProfile: AgentRuntimeProfile = "long_task",
): Promise<DurableAgentRunRecord> {
  return apiPost<DurableAgentRunRecord, {
    request: AgentRunRequest
    runtime_profile: AgentRuntimeProfile
  }>("/api/agent/runs", {
    request,
    runtime_profile: runtimeProfile,
  })
}

export function getAgentRuntimeRun(runId: string): Promise<DurableAgentRunRecord> {
  return apiGet<DurableAgentRunRecord>(`/api/agent/runs/${encodeURIComponent(runId)}`)
}

export function getAgentRuntimeEvents(runId: string): Promise<AgentTraceEvent[]> {
  return apiGet<AgentTraceEvent[]>(`/api/agent/runs/${encodeURIComponent(runId)}/events`)
}

export function getAgentRuntimeResult(runId: string): Promise<DurableAgentRunResult> {
  return apiGet<DurableAgentRunResult>(`/api/agent/runs/${encodeURIComponent(runId)}/result`)
}

export function pauseAgentRuntimeRun(runId: string): Promise<DurableAgentRunRecord> {
  return apiPost<DurableAgentRunRecord, Record<string, never>>(
    `/api/agent/runs/${encodeURIComponent(runId)}/pause`,
    {},
  )
}

export function resumeAgentRuntimeRun(runId: string): Promise<DurableAgentRunRecord> {
  return apiPost<DurableAgentRunRecord, Record<string, never>>(
    `/api/agent/runs/${encodeURIComponent(runId)}/resume`,
    {},
  )
}

export function cancelAgentRuntimeRun(runId: string): Promise<DurableAgentRunRecord> {
  return apiPost<DurableAgentRunRecord, Record<string, never>>(
    `/api/agent/runs/${encodeURIComponent(runId)}/cancel`,
    {},
  )
}

export function retryAgentRuntimeRun(runId: string): Promise<DurableAgentRunRecord> {
  return apiPost<DurableAgentRunRecord, Record<string, never>>(
    `/api/agent/runs/${encodeURIComponent(runId)}/retry`,
    {},
  )
}

function parseRuntimeStreamEvent(raw: string): DurableAgentRuntimeStreamEvent {
  const parsed = JSON.parse(raw) as Partial<DurableAgentRuntimeStreamEvent>
  if (!parsed || typeof parsed !== "object" || typeof parsed.type !== "string") {
    throw new Error("Invalid durable Agent runtime event.")
  }
  return parsed as DurableAgentRuntimeStreamEvent
}

export function streamAgentRuntimeRun(
  runId: string,
  handlers: DurableAgentRuntimeStreamHandlers,
  afterSequence = -1,
): DurableAgentRuntimeStreamHandle {
  const path = `/api/agent/runs/${encodeURIComponent(runId)}/stream?after_sequence=${afterSequence}`
  const socket = new WebSocket(apiWebSocketUrl(path))
  let closed = false

  socket.addEventListener("message", (message) => {
    if (closed) return
    try {
      const event = parseRuntimeStreamEvent(String(message.data))
      handlers.onEvent(event)
      if (event.type === "terminal" || event.type === "error") {
        closed = true
        socket.close(1000, event.type)
      }
    } catch (error) {
      closed = true
      handlers.onTransportError(
        error instanceof Error ? error : new Error("Invalid durable Agent runtime event."),
      )
      socket.close(1002, "invalid-runtime-event")
    }
  })

  socket.addEventListener("error", () => {
    if (closed) return
    closed = true
    handlers.onTransportError(new Error("Unable to connect to the durable Agent runtime stream."))
  })

  socket.addEventListener("close", (event) => {
    if (closed || event.code === 1000) return
    closed = true
    handlers.onTransportError(
      new Error(`Durable Agent runtime stream closed unexpectedly (${event.code}).`),
    )
  })

  return {
    close() {
      if (closed) return
      closed = true
      if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
        socket.close(1000, "client-close")
      }
    },
  }
}
