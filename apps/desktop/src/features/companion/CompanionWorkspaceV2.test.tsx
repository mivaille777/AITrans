// @vitest-environment jsdom

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { streamCompanionChat } from "../../api/companion-stream"
import type { CompanionChatStreamHandlers } from "../../api/companion-stream"
import type { ConversationDetail } from "../../api/types"
import { EMPTY_COMPANION_CONTEXT } from "./companion-runtime"
import CompanionWorkspaceV2 from "./CompanionWorkspaceV2"

vi.mock("../../api/companion-stream", () => ({ streamCompanionChat: vi.fn() }))
vi.mock("./ConversationHistoryPanel", () => ({ default: () => null }))
vi.mock("./components/AgentToolsControl", () => ({ AgentToolsControl: () => null }))
vi.mock("./components/KnowledgeRetrievalControl", () => ({ KnowledgeRetrievalControl: () => null }))
// Keep these existing Companion transport regressions separate from the new
// Agent-mode integration tests in ChatSessionControls.test.tsx.
vi.mock("./hooks/useChatConfiguration", () => ({useChatConfiguration: () => ({
  configuration:{data:{execution_mode:"",attachments:[],pending_run_id:"",filesystem_workspace_id:""},isPending:false,isError:false},
  workspaces:{data:[]}, mutation:{isPending:false,error:null,mutate:vi.fn()},
})}))

const fetchMock = vi.fn<typeof fetch>()
const clients: QueryClient[] = []
let statusAvailable = true
let statusFails = false
let busyElsewhere = false
let handlers: CompanionChatStreamHandlers
const cancel = vi.fn()
const conversation: ConversationDetail = {
  ...EMPTY_COMPANION_CONTEXT,
  conversation_id: "conversation-1", session_id: "session-1", title: "Saved conversation",
  created_at: "", updated_at: "", provider: "deepseek", model: "test-model",
  context_mode: "general", messages: [],
}

function json(body: unknown) {
  return new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } })
}

function renderChat(path = "/chat") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  clients.push(client)
  render(<QueryClientProvider client={client}><MemoryRouter initialEntries={[path]}><CompanionWorkspaceV2 /></MemoryRouter></QueryClientProvider>)
  return client
}

function sendButton() { return screen.getByRole<HTMLButtonElement>("button", { name: "Send" }) }
function composer() { return screen.getByRole<HTMLTextAreaElement>("textbox") }

beforeEach(() => {
  statusAvailable = true
  statusFails = false
  busyElsewhere = false
  vi.mocked(streamCompanionChat).mockImplementation((payload, nextHandlers) => {
    handlers = nextHandlers
    return { requestId: payload.request_id ?? 0, cancel, close: vi.fn() }
  })
  fetchMock.mockImplementation(async (input) => {
    const url = String(input)
    if (url.endsWith("/chat/status")) {
      if (statusFails) throw new Error("Backend disconnected")
      return json({ available: statusAvailable, provider: "deepseek", model: "test-model", detail: statusAvailable ? "" : "API key missing" })
    }
    if (url.endsWith("/handoff")) return json({ handoff: null })
    if (url.includes("/chat/ownership/")) return json({ busy: busyElsewhere, owner_id: "other-window", owner_surface: "overlay" })
    if (url.includes("/conversations/")) return json(conversation)
    if (url.endsWith("/llm/settings")) return json({ provider: "deepseek", model: "test-model", base_url: "" })
    throw new Error(`Unexpected request: ${url}`)
  })
  vi.stubGlobal("fetch", fetchMock)
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => { callback(0); return 0 })
})

afterEach(() => {
  cleanup()
  clients.splice(0).forEach((client) => client.clear())
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

describe("Chat Send interaction", () => {
  it("labels a stage outline without claiming full-text reading", async () => {
    renderChat()
    await userEvent.type(composer(), "任务书有几个阶段")
    await waitFor(() => expect(sendButton().disabled).toBe(false))
    await userEvent.click(sendButton())
    const requestId = vi.mocked(streamCompanionChat).mock.calls[0][0].request_id ?? 0
    const coverage = { basis: "stage_headers", total_chunks: 11, processed_chunks: 11, total_chars: 216,
      processed_chars: 216, total_batches: 1, processed_batches: 1, complete: true }
    act(() => handlers.onEvent({
      type: "phase", phase: "reading_document", route: "document_scoped_search", request_id: requestId,
      conversation_id: "", message_id: "", knowledge_recovery: { outcome: "recovering", reading_coverage: coverage },
    }))
    expect(screen.getAllByText("正在核对阶段目录… 11/11").length).toBeGreaterThan(0)
    act(() => handlers.onEvent({
      type: "done", request_id: requestId, conversation_id: "", message_id: "outline", output_text: "共11个阶段",
      provider: "deepseek", model: "test-model", knowledge_access_policy: "auto", knowledge_enabled: true,
      knowledge_decision: null, knowledge_retrieved: true, knowledge_document_count: 1, knowledge_chunk_count: 11,
      knowledge_fallback_reason: "", evidence: [], citations: [], knowledge_recovery: { outcome: "normal", reading_coverage: coverage },
    }))
    expect(screen.getByText("阶段目录已核验")).toBeTruthy()
    expect(screen.queryByText("索引正文已完整读取")).toBeNull()
  })

  it("shows body and stage coverage separately from final citations", async () => {
    renderChat()
    await userEvent.type(composer(), "任务书讲什么")
    await waitFor(() => expect(sendButton().disabled).toBe(false))
    await userEvent.click(sendButton())
    const requestId = vi.mocked(streamCompanionChat).mock.calls[0][0].request_id ?? 0
    act(() => handlers.onEvent({
      type: "done", request_id: requestId, conversation_id: "", message_id: "rag-overview",
      output_text: "概览 [1][3]，后续阶段 [3]", provider: "deepseek", model: "test-model",
      knowledge_access_policy: "auto", knowledge_enabled: true, knowledge_decision: null,
      knowledge_retrieved: true, knowledge_document_count: 1, knowledge_chunk_count: 29,
      knowledge_fallback_reason: "", evidence: [], citations: [],
      knowledge_recovery: { outcome: "normal", full_read: { basis: "indexed_text", total_chunks: 29,
        processed_chunks: 29, total_chars: 20203, processed_chars: 20203, total_batches: 2,
        processed_batches: 2, complete: true }, rag_reading: { contract_version: "section-coverage-v1", documents: [{
        basis: "indexed_text", inventory_chunks: 29, selected_chunks: 29, read_chunks: 29,
        expected_sections: ["intro", "s1"], read_complete_sections: ["intro", "s1"],
        expected_stages: ["MA00", "MA01"], read_stages: ["MA00", "MA01"], read_complete: true, budget_truncated: false,
      }] } },
    }))
    expect(screen.getByText("正文 29/29 · 阶段 2/2 · 引用 2 个片段")).toBeTruthy()
  })

  it.each([
    ["grounding_verification_failed", "正文已读完，摘要未通过核验"],
    ["full_read_synthesis_failed", "正文已读完，摘要生成失败"],
    ["answer_incomplete", "正文已读完，回答不完整"],
  ])("distinguishes complete reading from a failed summary: %s", async (reason, label) => {
    renderChat()
    await userEvent.type(composer(), "把任务书全看完，告诉我它讲的内容是什么")
    await waitFor(() => expect(sendButton().disabled).toBe(false))
    await userEvent.click(sendButton())
    const requestId = vi.mocked(streamCompanionChat).mock.calls[0][0].request_id ?? 0
    const full = { basis: "indexed_text", total_chunks: 29, processed_chunks: 29, total_chars: 20203,
      processed_chars: 20203, total_batches: 2, processed_batches: 2, complete: true }
    act(() => handlers.onEvent({
      type: "done", request_id: requestId, conversation_id: "", message_id: "fallback",
      output_text: "正文读取已完成，但摘要未能通过核验", provider: "deepseek", model: "test-model",
      knowledge_access_policy: "auto", knowledge_enabled: true, knowledge_decision: null,
      knowledge_retrieved: true, knowledge_document_count: 1, knowledge_chunk_count: 29,
      knowledge_fallback_reason: "grounding_verification_failed", evidence: [], citations: [],
      knowledge_recovery: { outcome: "fallback", reason, full_read: full },
    }))
    expect(screen.getByText(label)).toBeTruthy()
    expect(screen.queryByText("全文读取未完成")).toBeNull()
  })

  it("shows full reading progress and distinguishes partial completion", async () => {
    renderChat()
    await userEvent.type(composer(), "读取全文")
    await waitFor(() => expect(sendButton().disabled).toBe(false))
    await userEvent.click(sendButton())
    const requestId = vi.mocked(streamCompanionChat).mock.calls[0][0].request_id ?? 0
    const full = { basis: "indexed_text", total_chunks: 10, processed_chunks: 3, total_chars: 1000,
      processed_chars: 300, total_batches: 4, processed_batches: 1, complete: false }
    act(() => handlers.onEvent({
      type: "phase", phase: "reading_document", route: "document_scoped_search",
      request_id: requestId, conversation_id: "", message_id: "",
      knowledge_recovery: { outcome: "recovering", full_read: full },
    }))
    expect(screen.getAllByText("正在阅读全文… 3/10").length).toBeGreaterThan(0)
    act(() => handlers.onEvent({
      type: "done", request_id: requestId, conversation_id: "", message_id: "partial",
      output_text: "已核验的部分内容", provider: "deepseek", model: "test-model",
      knowledge_access_policy: "auto", knowledge_enabled: true, knowledge_decision: null,
      knowledge_retrieved: true, knowledge_document_count: 1, knowledge_chunk_count: 3,
      knowledge_fallback_reason: "full_read_budget_exhausted", evidence: [], citations: [],
      knowledge_recovery: { outcome: "partial", full_read: full },
    }))
    expect(screen.getByText("全文读取未完成")).toBeTruthy()
    await userEvent.type(composer(), "下一问")
    expect(sendButton().disabled).toBe(false)
  })

  it("renders the persisted error explanation instead of an empty failed bubble", async () => {
    renderChat()
    await userEvent.type(composer(), "Hello")
    await waitFor(() => expect(sendButton().disabled).toBe(false))
    await userEvent.click(sendButton())
    const requestId = vi.mocked(streamCompanionChat).mock.calls[0][0].request_id ?? 0
    act(() => handlers.onEvent({
      type: "error", request_id: requestId, conversation_id: "", message_id: "failed",
      code: "authentication", message: "认证失败",
      output_text: "模型服务认证失败，请检查凭据后重试。",
    }))
    expect(screen.getByText("模型服务认证失败，请检查凭据后重试。")).toBeTruthy()
    expect(screen.queryByText("No response content.")).toBeNull()
    await userEvent.type(composer(), "下一问")
    expect(sendButton().disabled).toBe(false)
  })


  it("enables a non-empty draft, sends on click, and restores Send after cancellation", async () => {
    renderChat()
    expect(sendButton().disabled).toBe(true)
    await userEvent.type(composer(), "Hello")
    await waitFor(() => expect(sendButton().disabled).toBe(false))
    await userEvent.click(sendButton())
    expect(streamCompanionChat).toHaveBeenCalledTimes(1)
    const payload = vi.mocked(streamCompanionChat).mock.calls[0][0]
    expect(payload.user_message).toBe("Hello")
    await userEvent.type(composer(), "Next message")
    await userEvent.click(screen.getByRole("button", { name: "Stop" }))
    expect(cancel).toHaveBeenCalledTimes(1)
    act(() => handlers.onEvent({ type: "cancelled", request_id: payload.request_id ?? 0, conversation_id: "", message_id: "" }))
    expect(sendButton().disabled).toBe(false)
    expect(composer().value).toBe("Next message")
  })

  it("keeps Enter and form submission blocked while Chat is unavailable", async () => {
    statusAvailable = false
    renderChat()
    await screen.findByText("API key missing")
    await userEvent.type(composer(), "Hello{Enter}")
    fireEvent.submit(composer().form!)
    expect(sendButton().disabled).toBe(true)
    expect(streamCompanionChat).not.toHaveBeenCalled()
    expect(composer().value).toBe("Hello")
  })

  it("returns to Send when a reply completes and preserves the next draft", async () => {
    renderChat()
    await userEvent.type(composer(), "Hello")
    await waitFor(() => expect(sendButton().disabled).toBe(false))
    await userEvent.keyboard("{Enter}")
    const payload = vi.mocked(streamCompanionChat).mock.calls[0][0]
    await userEvent.type(composer(), "Next question")
    await userEvent.keyboard("{Enter}")
    expect(streamCompanionChat).toHaveBeenCalledTimes(1)
    act(() => handlers.onEvent({
      type: "done", request_id: payload.request_id ?? 0, conversation_id: "", message_id: "answer-1",
      output_text: "A completed reply", provider: "deepseek", model: "test-model",
      knowledge_access_policy: "auto", knowledge_enabled: false, knowledge_decision: null,
      knowledge_retrieved: false, knowledge_document_count: 0, knowledge_chunk_count: 0,
      knowledge_fallback_reason: "", evidence: [], citations: [],
    }))
    expect(sendButton().disabled).toBe(false)
    expect(composer().value).toBe("Next question")
    await userEvent.click(sendButton())
    expect(streamCompanionChat).toHaveBeenCalledTimes(2)
  })

  it("shows a failed status check and allows retry without losing the draft", async () => {
    statusFails = true
    renderChat()
    await screen.findByText(/无法连接 AI Chat/)
    await userEvent.type(composer(), "Keep this draft")
    expect(sendButton().disabled).toBe(true)
    statusFails = false
    await userEvent.click(screen.getByRole("button", { name: "重试连接" }))
    await waitFor(() => expect(sendButton().disabled).toBe(false))
    expect(composer().value).toBe("Keep this draft")
  })

  it("does not send when Enter confirms Chinese IME input, then allows normal Enter", async () => {
    renderChat()
    await userEvent.type(composer(), "中文问题")
    await waitFor(() => expect(sendButton().disabled).toBe(false))
    fireEvent.keyDown(composer(), { key: "Enter", isComposing: true })
    fireEvent.keyDown(composer(), { key: "Enter", keyCode: 229 })
    expect(streamCompanionChat).not.toHaveBeenCalled()
    await userEvent.keyboard("{Enter}")
    expect(streamCompanionChat).toHaveBeenCalledTimes(1)
  })

  it("disables Send when another window owns the reply and explains why", async () => {
    busyElsewhere = true
    const client = renderChat("/chat?conversation=conversation-1")
    await screen.findByText("此会话正在另一个窗口中生成回复，请等待完成。")
    await userEvent.type(composer(), "Hello{Enter}")
    expect(sendButton().disabled).toBe(true)
    expect(streamCompanionChat).not.toHaveBeenCalled()
    busyElsewhere = false
    await act(async () => { await client.invalidateQueries({ queryKey: ["companion", "ownership"] }) })
    await waitFor(() => expect(sendButton().disabled).toBe(false))
  })
})
