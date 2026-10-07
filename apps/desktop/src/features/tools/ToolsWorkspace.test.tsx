// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter } from "react-router-dom"
import { afterEach, beforeEach, expect, it, vi } from "vitest"
import * as api from "../../api/tools"
import type { ToolDetail, ToolTestRun } from "../../api/tools"
import ToolsWorkspace from "./ToolsWorkspace"

vi.mock("../../api/tools")
const record: ToolDetail = {
  tool_id: "builtin:search_knowledge_base", name: "search_knowledge_base", title: "Search knowledge",
  description: "Search indexed workspace documents.", category: "knowledge", namespace: "agent", origin: "builtin",
  effect: "read", enabled: true, available: true, effective_enabled: true, unavailable_reason: "", risk_level: "unknown",
  tool_version: "1", revision: "r1", input_schema: { type: "object", properties: { query: { type: "string" } }, required: ["query"] },
  output_schema: { type: "object" }, input_profiles: {}, context_requirements: ["knowledge_scope"],
  permissions: { requires_confirmation: false }, limits: { timeout_seconds: 20 }, examples: [],
  execution_capabilities: {}, editable_fields: [], updated_at: null,
}
const other = { ...record, tool_id: "builtin:explain_selection", name: "explain_selection", category: "reading" }

beforeEach(() => {
  vi.mocked(api.getToolTestHistory).mockResolvedValue({ items: [], next_cursor: null })
  vi.mocked(api.getToolTestEvents).mockResolvedValue({ items: [] })
  vi.mocked(api.getTools).mockImplementation(async (filters) => {
    const items = [record, other].filter((tool) => (!filters?.q || tool.name.includes(filters.q)) && (!filters?.status || filters.status !== "disabled"))
    return { items, categories: Object.fromEntries(items.map((item) => [item.category, 1])), total: 2, enabled: 2, disabled: 0, matched_total: items.length, next_cursor: null, catalog_revision: "v1" }
  })
  vi.mocked(api.getTool).mockImplementation(async (id) => id === other.tool_id ? other : record)
})
afterEach(() => { cleanup(); vi.resetAllMocks() })
function setup() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(<MemoryRouter><QueryClientProvider client={client}><ToolsWorkspace /></QueryClientProvider></MemoryRouter>)
}
it("selects real tools and filters without changing directory totals", async () => {
  setup()
  await screen.findByRole("heading", { name: /search_knowledge_base/ })
  await userEvent.click(screen.getByRole("button", { name: "explain_selection" }))
  await screen.findByRole("heading", { name: /explain_selection/ })
  await userEvent.type(screen.getByRole("textbox", { name: "Search tools" }), "missing")
  await screen.findByText("No tools match these filters.")
  expect(screen.getByRole("button", { name: "All 2" })).toBeTruthy()
})
it("shows actionable backend failures and reloads the library", async () => {
  vi.mocked(api.getTools).mockRejectedValueOnce(new Error("offline")).mockRejectedValueOnce(new Error("offline"))
  setup()
  await screen.findByRole("alert")
  await userEvent.click(screen.getByRole("button", { name: "Retry" }))
  await waitFor(() => expect(screen.getByRole("button", { name: "search_knowledge_base" })).toBeTruthy())
})

it("switches detail tabs and fills the tool-specific test draft", async () => {
  vi.mocked(api.getTool).mockResolvedValue({ ...record, examples: [{ id: "basic", title: "Basic example", description: "Search", arguments: { query: "agent" } }] })
  setup()
  await screen.findByRole("heading", { name: /search_knowledge_base/ })
  await userEvent.click(screen.getByRole("tab", { name: "Returns" }))
  expect(screen.getByRole("heading", { name: "Output schema" })).toBeTruthy()
  await userEvent.click(screen.getByRole("tab", { name: "Permissions" }))
  expect(screen.getByRole("heading", { name: "Permissions & security" })).toBeTruthy()
  await userEvent.click(screen.getByRole("tab", { name: "Examples" }))
  await userEvent.click(screen.getByRole("button", { name: "Use in test →" }))
  expect((screen.getByRole("textbox", { name: "Input parameters JSON" }) as HTMLTextAreaElement).value).toContain("agent")
})

it("reports failed policy updates while keeping the prior enabled state", async () => {
  vi.mocked(api.getTool).mockResolvedValue({ ...record, editable_fields: ["enabled"] })
  vi.mocked(api.setToolEnabled).mockRejectedValue(new Error("Configuration changed. Reload."))
  setup()
  await screen.findByRole("heading", { name: /search_knowledge_base/ })
  await userEvent.click(screen.getByRole("switch", { name: "Enable tool" }))
  await screen.findByRole("alert")
  expect(screen.getByRole("switch", { name: "Enable tool" }).getAttribute("aria-checked")).toBe("true")
})

it("blocks invalid test JSON before making an execution request", async () => {
  setup()
  await screen.findByRole("heading", { name: /search_knowledge_base/ })
  await userEvent.type(screen.getByRole("textbox", { name: "Input parameters JSON" }), "broken")
  await userEvent.click(screen.getByRole("button", { name: "Run tool" }))
  await screen.findByText("Invalid JSON. Fix the input before running.")
  expect(api.createToolTest).not.toHaveBeenCalled()
})

it("creates a disabled preset through the configuration dialog", async () => {
  vi.mocked(api.createCustomTool).mockResolvedValue({ ...record, tool_id: "custom:custom_research_search", name: "custom_research_search", origin: "custom", enabled: false })
  setup()
  await screen.findByRole("heading", { name: /search_knowledge_base/ })
  await userEvent.click(screen.getByRole("button", { name: "Add tool" }))
  await userEvent.click(screen.getByRole("button", { name: "Save tool" }))
  await waitFor(() => expect(api.createCustomTool).toHaveBeenCalled())
  expect(vi.mocked(api.createCustomTool).mock.calls[0][0].fixed_arguments).toEqual({ top_k: 5 })
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull())
})

it("requires a preview and explicit resolution before replacing imported presets", async () => {
  vi.mocked(api.previewToolImport).mockResolvedValue({ preview_token: "preview", items: [{ name: "custom_test", template_id: "builtin:search_knowledge_base", enabled: false }], conflicts: [{ name: "custom_test", archived: false }], message: "Starts disabled" })
  vi.mocked(api.applyToolImport).mockResolvedValue({ items: [] })
  setup()
  await screen.findByRole("heading", { name: /search_knowledge_base/ })
  await userEvent.click(screen.getByRole("button", { name: "Import" }))
  expect((screen.getByRole("button", { name: "Apply import" }) as HTMLButtonElement).disabled).toBe(true)
  await userEvent.click(screen.getByRole("button", { name: "Preview import" }))
  await screen.findByText("Starts disabled")
  expect((screen.getByRole("button", { name: "Apply import" }) as HTMLButtonElement).disabled).toBe(true)
  await userEvent.click(screen.getByRole("checkbox", { name: "Replace existing configurations and disable them" }))
  await userEvent.click(screen.getByRole("button", { name: "Apply import" }))
  await waitFor(() => expect(api.applyToolImport).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ preview_token: "preview" }), true))
})

it("refreshes stored logs when polling observes completion without SSE", async () => {
  const finished: ToolTestRun = {
    test_run_id: "test_complete", tool_id: record.tool_id, tool_name: record.name,
    trace_id: "trace_complete", tool_call_id: "call_complete", status: "succeeded", execution_state: "stopped",
    created_at: "2026-10-07T00:00:00Z", updated_at: "2026-10-07T00:00:01Z", finished_at: "2026-10-07T00:00:01Z",
    elapsed_ms: 1000, result: {}, result_truncated: false, error: null, approval_id: null, approval_summary: null,
  }
  vi.mocked(api.getToolTestHistory).mockResolvedValue({ items: [finished], next_cursor: null })
  vi.mocked(api.getToolTest).mockResolvedValue(finished)
  vi.mocked(api.getToolTestEvents).mockResolvedValueOnce({ items: [] }).mockResolvedValue({ items: [{ seq: 3, type: "test_succeeded", test_run_id: finished.test_run_id, status: "succeeded", execution_state: "stopped", at: finished.finished_at!, elapsed_ms: 1000, error_code: null }] })
  setup()
  await screen.findByRole("heading", { name: /search_knowledge_base/ })
  await userEvent.click(screen.getByRole("tab", { name: "Logs" }))
  await screen.findByText(/test succeeded · stopped/)
  expect(api.getToolTestEvents).toHaveBeenCalledTimes(2)
})

it("opens the test drawer with focus and returns it on Escape", async () => {
  setup()
  await screen.findByRole("heading", { name: /search_knowledge_base/ })
  const trigger = screen.getByRole("button", { name: "Test tool" })
  await userEvent.click(trigger)
  expect(document.activeElement).toBe(screen.getByRole("button", { name: "Close test panel" }))
  await userEvent.keyboard("{Escape}")
  expect(trigger.getAttribute("aria-expanded")).toBe("false")
  expect(document.activeElement).toBe(trigger)
})
