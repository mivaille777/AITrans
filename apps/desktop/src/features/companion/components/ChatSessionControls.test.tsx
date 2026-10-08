// @vitest-environment jsdom
import { act, cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import CompanionWorkspaceV2 from "../CompanionWorkspaceV2"
import {
  streamAgentRun,
  type AgentStreamHandlers,
} from "../../../api/agent-stream"
import type { ChatSessionConfiguration } from "../../../api/chat-sessions"

vi.mock("../ConversationHistoryPanel", () => ({ default: () => null }))
vi.mock("./KnowledgeRetrievalControl", () => ({
  KnowledgeRetrievalControl: () => null,
}))
vi.mock("../../../api/agent-stream", () => ({ streamAgentRun: vi.fn() }))
vi.mock("../../../desktop", () => ({
  desktop: {
    runtime: "browser",
    files: {
      pickKnowledgeDocument: vi.fn(async () => "C:/papers/paper.md"),
      pickAgentWorkspace: vi.fn(async () => "C:/papers"),
    },
    overlay: {
      notifyCompanionConversationChanged: vi.fn(async () => {}),
      onCompanionConversationChanged: vi.fn(async () => () => {}),
    },
  },
}))

let config: ChatSessionConfiguration
let handlers: AgentStreamHandlers
const requests: {
  url: string
  method: string
  body: Record<string, unknown>
}[] = []
const clients: QueryClient[] = []
const json = (value: unknown) =>
  new Response(JSON.stringify(value), {
    headers: { "Content-Type": "application/json" },
  })
beforeEach(() => {
  config = {
    session_id: "",
    filesystem_workspace_id: "",
    execution_mode: "react",
    attachments: [],
    pending_run_id: "",
  }
  vi.mocked(streamAgentRun).mockImplementation((payload, callbacks) => {
    handlers = callbacks
    return {
      requestId: payload.request_id || 0,
      cancel: vi.fn(),
      close: vi.fn(),
    }
  })
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input, init) => {
      const url = String(input),
        method = init?.method || "GET",
        body = init?.body ? JSON.parse(String(init.body)) : {}
      requests.push({ url, method, body })
      if (url.endsWith("/chat/status"))
        return json({
          available: true,
          provider: "deepseek",
          model: "model-a",
        })
      if (url.endsWith("/handoff")) return json({ handoff: null })
      if (url.endsWith("/filesystem-workspaces"))
        return json([
          {
            workspace_id: "workspace-1",
            display_name: "Papers",
            status: "active",
          },
        ])
      if (url.includes("/companion/sessions/")) {
        if (url.includes("/workspace/changes")) return json([])
        if (url.includes("/workspace?")) return json({display_path: "D:/Papers", directory: "", entries: [], total: 0, next_offset: 0, has_more: false, filesystem_access: "read_write"})
        config.session_id = decodeURIComponent(
          url.split("/sessions/")[1].split("/")[0],
        )
        if (method === "PATCH") config = { ...config, ...body }
        if (method === "POST")
          config = {
            ...config,
            attachments: [
              {
                attachment_id: "file-1",
                name: "paper.md",
                relative_path: "AITrans Chat Imports/paper.md",
                text_chars: 42,
                size_bytes: 42,
              },
            ],
          }
        return json(config)
      }
      if (url.endsWith("/settings/llm/models"))
        return json({
          available: true,
          provider: "deepseek",
          models: [{ id: "model-a" }, { id: "model-b" }],
        })
      if (url.endsWith("/settings/llm"))
        return json({
          provider: "deepseek",
          model: body.model || "model-a",
          base_url: "",
          providers: [],
        })
      if (url.endsWith("/tools")) return json({ tools: [] })
      if (url.includes("/snapshot"))
        return json({
          run_id: "run-1",
          trace_id: "trace-1",
          events: [],
          artifacts: [],
          results: [],
          plan: {},
          scope: {},
          status: "completed",
          resumable: false,
          retryable_task_ids: [],
        })
      throw new Error(`Unexpected ${method} ${url}`)
    }),
  )
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  clients.push(client)
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <CompanionWorkspaceV2 />
      </MemoryRouter>
    </QueryClientProvider>,
  )
})
afterEach(() => {
  cleanup()
  clients.splice(0).forEach((client) => client.clear())
  requests.length = 0
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

describe("Chat session controls", () => {
  it("persists workspace, imports only to this session, and changes the configured model", async () => {
    await userEvent.click(screen.getByRole("button", { name: "工作区" }))
    await userEvent.click(
      await screen.findByRole("menuitem", { name: /Papers/ }),
    )
    await waitFor(() =>
      expect(config.filesystem_workspace_id).toBe("workspace-1"),
    )
    await userEvent.click(screen.getByRole("button", { name: "导入文件" }))
    await userEvent.click(
      await screen.findByRole("menuitem", { name: /从电脑导入/ }),
    )
    await screen.findByText("paper.md")
    expect(
      requests.find(
        (request) =>
          request.method === "POST" && request.url.includes("/files"),
      )?.body,
    ).toEqual({ path: "C:/papers/paper.md" })
    expect(
      requests.some((request) => request.url.includes("/knowledge/import")),
    ).toBe(false)
    await userEvent.click(screen.getByRole("button", { name: /model-a/ }))
    await userEvent.click(
      await screen.findByRole("option", { name: "model-b" }),
    )
    await waitFor(() =>
      expect(
        requests.some(
          (request) =>
            request.method === "PUT" && request.body.model === "model-b",
        ),
      ).toBe(true),
    )
    await screen.findByRole("button", { name: /model-b/ })
  })

  it("sends ReAct through Agent and confirms the server-issued plan with its hash", async () => {
    await userEvent.click(screen.getByRole("button", { name: "执行模式" }))
    await userEvent.click(
      await screen.findByRole("menuitemradio", { name: /Plan–Execute/ }),
    )
    await waitFor(() => expect(config.execution_mode).toBe("plan_execute"))
    await userEvent.type(
      screen.getByRole("textbox", { name: "Message" }),
      "总结导入资料",
    )
    await userEvent.click(screen.getByRole("button", { name: "Send" }))
    await waitFor(() => expect(streamAgentRun).toHaveBeenCalledTimes(1))
    const request = vi.mocked(streamAgentRun).mock.calls[0][0]
    expect(request.chat_configuration).toBe(true)
    const run = {
      run_id: "run-1",
      trace_id: "trace-1",
      conversation_id: "",
      status: "confirmation_required" as const,
      confirmation_kind: "plan" as const,
      plan_hash: "approved-hash",
      multi_step_plan: {
        goal: "总结资料",
        mode: "multi_step" as const,
        steps: [],
        current_step_id: "",
      },
      plan: {
        action: "answer" as const,
        tool_name: "",
        user_visible_reason: "总结资料",
        arguments: {},
      },
      output_text: "计划目标：总结资料",
      provider: "stub",
      model: "model-a",
      request_id: request.request_id || 0,
      tool_result: null,
      evidence: [],
      citations: [],
    }
    act(() =>
      handlers.onEvent({
        type: "done",
        request_id: request.request_id || 0,
        session_id: request.session_id,
        run_id: "run-1",
        trace_id: "trace-1",
        trace: {
          run_id: "run-1",
          trace_id: "trace-1",
          session_id: request.session_id,
          ui_mode: "assistant",
          total_duration_ms: 0,
          events: [],
          run,
        },
      }),
    )
    await userEvent.click(
      await screen.findByRole("button", { name: "确认执行" }),
    )
    const resume = vi.mocked(streamAgentRun).mock.calls[1][0]
    expect(resume.resume_run_id).toBe("run-1")
    expect(resume.plan_confirmation).toBe("approve")
    expect(resume.plan_hash).toBe("approved-hash")
    expect(resume.session_id).toBe(request.session_id)
  })
})
