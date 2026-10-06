import { apiWebSocketUrl } from "./client"
import type {
  CompanionChatRequest,
  CompanionChatStreamEvent,
} from "./types"

export interface CompanionChatStreamHandlers {
  onEvent: (event: CompanionChatStreamEvent) => void
  onTransportError: (error: Error) => void
}

export interface CompanionChatStreamHandle {
  requestId: number
  cancel: () => void
  close: () => void
}

const terminalTypes = new Set<CompanionChatStreamEvent["type"]>([
  "done",
  "error",
  "cancelled",
])

function parseEvent(raw: string): CompanionChatStreamEvent {
  const parsed = JSON.parse(raw) as Partial<CompanionChatStreamEvent>
  if (!parsed || typeof parsed !== "object" || typeof parsed.type !== "string") {
    throw new Error("Invalid AI Chat stream event.")
  }
  return parsed as CompanionChatStreamEvent
}

export function streamCompanionChat(
  payload: CompanionChatRequest,
  handlers: CompanionChatStreamHandlers,
): CompanionChatStreamHandle {
  const requestId = payload.request_id ?? 0
  const socket = new WebSocket(apiWebSocketUrl("/ws/companion/chat"))
  let terminal = false
  let cancelRequested = false

  socket.addEventListener("open", () => {
    if (terminal) return
    if (cancelRequested) {
      terminal = true
      handlers.onEvent({
        type: "cancelled",
        request_id: requestId,
        conversation_id: payload.session_id,
        message_id: "",
      })
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
        error instanceof Error ? error : new Error("Invalid AI Chat stream event."),
      )
      socket.close(1002, "invalid-stream-event")
    }
  })

  socket.addEventListener("error", () => {
    if (terminal) return
    terminal = true
    handlers.onTransportError(new Error("Unable to connect to the AI Chat stream."))
  })

  socket.addEventListener("close", (event) => {
    if (terminal) return
    terminal = true
    handlers.onTransportError(
      new Error(`AI Chat stream closed unexpectedly (${event.code}).`),
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
        terminal = true
        handlers.onEvent({
          type: "cancelled",
          request_id: requestId,
          conversation_id: payload.conversation_id ?? "",
          message_id: "",
        })
        socket.close(1000, "cancelled-before-start")
      }
    },
    close() {
      if (terminal) return

      // Closing a live surface (for example because a new external selection
      // remounts the overlay conversation) is a cancellation boundary, not a
      // silent disconnect. Ask the backend to stop before closing the socket so
      // stale work cannot continue and later race the new reading context.
      if (!cancelRequested && socket.readyState === WebSocket.OPEN) {
        cancelRequested = true
        socket.send(JSON.stringify({ type: "cancel", request_id: requestId }))
      } else if (!cancelRequested && socket.readyState === WebSocket.CONNECTING) {
        cancelRequested = true
      }

      terminal = true
      if (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING) {
        socket.close(1000, "client-close")
      }
    },
  }
}
