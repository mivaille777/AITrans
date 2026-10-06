import { apiWebSocketUrl } from "./client"
import type {
  AgentRunRequest,
  AgentRunTraceResponse,
  AgentTraceEvent,
} from "./agent"

interface AgentStreamIdentity {
  request_id: number
  session_id: string
  run_id: string
  trace_id: string
}

export interface AgentStreamAcceptedEvent extends AgentStreamIdentity {
  type: "accepted"
}

export interface AgentStreamActivityEvent extends AgentStreamIdentity {
  type: "activity"
  event: AgentTraceEvent
}

export interface AgentStreamCancelRequestedEvent extends AgentStreamIdentity {
  type: "cancel_requested"
}

export interface AgentStreamCancelledEvent extends AgentStreamIdentity {
  type: "cancelled"
  message: string
}

export interface AgentStreamDoneEvent extends AgentStreamIdentity {
  type: "done"
  trace: AgentRunTraceResponse
}

export interface AgentStreamErrorEvent extends AgentStreamIdentity {
  type: "error"
  code: string
  fallback_reason?: string
  message: string
}

export type AgentStreamEvent =
  | AgentStreamAcceptedEvent
  | AgentStreamActivityEvent
  | AgentStreamCancelRequestedEvent
  | AgentStreamCancelledEvent
  | AgentStreamDoneEvent
  | AgentStreamErrorEvent

export interface AgentStreamHandlers {
  onEvent: (event: AgentStreamEvent) => void
  onTransportError: (error: Error) => void
}

export interface AgentStreamHandle {
  requestId: number
  cancel: () => void
  close: () => void
}

const terminalTypes = new Set<AgentStreamEvent["type"]>(["done", "error", "cancelled"])

function parseEvent(raw: string): AgentStreamEvent {
  const parsed = JSON.parse(raw) as Partial<AgentStreamEvent>
  if (!parsed || typeof parsed !== "object" || typeof parsed.type !== "string") {
    throw new Error("Invalid Agent stream event.")
  }
  return parsed as AgentStreamEvent
}

export function streamAgentRun(
  payload: AgentRunRequest,
  handlers: AgentStreamHandlers,
): AgentStreamHandle {
  const requestId = payload.request_id ?? 0
  const socket = new WebSocket(apiWebSocketUrl("/api/agent/stream"))
  let terminal = false
  let cancelRequested = false

  function emitCancelledBeforeStart() {
    if (terminal) return
    terminal = true
    handlers.onEvent({
      type: "cancelled",
      request_id: requestId,
      session_id: payload.session_id,
      run_id: "",
      trace_id: payload.trace_id ?? "",
      message: "Agent run cancelled before start.",
    })
  }

  socket.addEventListener("open", () => {
    if (terminal) return
    if (cancelRequested) {
      emitCancelledBeforeStart()
      socket.close(1000, "cancelled-before-start")
      return
    }
    socket.send(JSON.stringify({ type: "start", request: payload }))
  })

  socket.addEventListener("message", (message) => {
    if (terminal) return
    try {
      const event = parseEvent(String(message.data))
      if (event.request_id !== requestId) return
      handlers.onEvent(event)
      if (terminalTypes.has(event.type)) {
        terminal = true
        socket.close(1000, event.type)
      }
    } catch (error) {
      terminal = true
      handlers.onTransportError(
        error instanceof Error ? error : new Error("Invalid Agent stream event."),
      )
      socket.close(1002, "invalid-agent-stream-event")
    }
  })

  socket.addEventListener("error", () => {
    if (terminal) return
    terminal = true
    handlers.onTransportError(new Error("Unable to connect to the Agent stream."))
  })

  socket.addEventListener("close", (event) => {
    if (terminal) return
    terminal = true
    handlers.onTransportError(
      new Error(`Agent stream closed unexpectedly (${event.code}).`),
    )
  })

  return {
    requestId,
    cancel() {
      if (terminal || cancelRequested) return
      cancelRequested = true
      if (socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "cancel", request_id: requestId }))
      } else if (socket.readyState === WebSocket.CONNECTING) {
        emitCancelledBeforeStart()
        socket.close(1000, "cancelled-before-start")
      }
    },
    close() {
      terminal = true
      if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
        socket.close(1000, "client-close")
      }
    },
  }
}
