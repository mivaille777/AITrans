import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { streamAgentRun } from "./agent-stream"
import { streamCompanionChat } from "./companion-stream"
import type { CompanionChatRequest } from "./types"

class TestSocket extends EventTarget {
  static CONNECTING = 0
  static OPEN = 1
  static CLOSED = 3
  static latest: TestSocket
  readyState = TestSocket.CONNECTING
  send = vi.fn()
  close = vi.fn(() => { this.readyState = TestSocket.CLOSED })
  constructor(_url: string) { super(); TestSocket.latest = this }
  open() { this.readyState = TestSocket.OPEN; this.dispatchEvent(new Event("open")) }
  disconnect() { this.readyState = TestSocket.CLOSED; this.dispatchEvent(Object.assign(new Event("close"), { code: 1006 })) }
}

const payload: CompanionChatRequest = {
  session_id: "session-1", request_id: 1, user_message: "Hello", source_text: "", translated_text: "",
  source_language: "auto", target_language: "zh-CN", context_mode: "general", history: [],
  knowledge_access_policy: "auto", knowledge_document_ids: [],
  resource_url: "", resource_title: "", section_heading: "", context_before: "", context_after: "", source_kind: "",
}

beforeEach(() => vi.stubGlobal("WebSocket", TestSocket))
afterEach(() => vi.unstubAllGlobals())

describe.each([
  ["Companion", streamCompanionChat],
  ["Agent", streamAgentRun],
] as const)("%s cancellation", (_name, start) => {
  it("terminates cancellation before connection instead of leaving Stop active", () => {
    const onEvent = vi.fn()
    const handle = start(payload, { onEvent, onTransportError: vi.fn() })
    const socket = TestSocket.latest
    handle.cancel()
    expect(onEvent).toHaveBeenCalledTimes(1)
    expect(onEvent).toHaveBeenCalledWith(expect.objectContaining({ type: "cancelled", request_id: 1 }))
    expect(socket.close).toHaveBeenCalledTimes(1)
    expect(socket.send).not.toHaveBeenCalled()
    socket.dispatchEvent(new Event("open"))
    expect(socket.send).not.toHaveBeenCalled()
    expect(onEvent).toHaveBeenCalledTimes(1)
  })

  it("reports disconnects after requesting cancellation so the runtime can clear Stop", () => {
    const onTransportError = vi.fn()
    const handle = start(payload, { onEvent: vi.fn(), onTransportError })
    const socket = TestSocket.latest
    socket.open()
    handle.cancel()
    expect(socket.send).toHaveBeenLastCalledWith(JSON.stringify({ type: "cancel", request_id: 1 }))
    socket.disconnect()
    expect(onTransportError).toHaveBeenCalledTimes(1)
    socket.dispatchEvent(new Event("error"))
    expect(onTransportError).toHaveBeenCalledTimes(1)
  })

  it("ignores intentional surface closure without starting recovery", () => {
    const onTransportError = vi.fn()
    const handle = start(payload, { onEvent: vi.fn(), onTransportError })
    const socket = TestSocket.latest
    socket.open()
    handle.close()
    socket.disconnect()
    expect(onTransportError).not.toHaveBeenCalled()
  })
})
