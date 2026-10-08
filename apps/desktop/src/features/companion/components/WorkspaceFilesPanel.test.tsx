// @vitest-environment jsdom
import { cleanup, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { WorkspaceFilesPanel } from "./WorkspaceFilesPanel"

vi.mock("../../../desktop", () => ({desktop: {runtime: "browser", files: {}}}))
const clients: QueryClient[] = []
let applied = false
let calls: string[] = []
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), {status, headers: {"Content-Type": "application/json"}})
beforeEach(() => {
  applied = false; calls = []
  vi.stubGlobal("fetch", vi.fn(async (input: unknown, init?: RequestInit) => {
    const url = String(input)
    calls.push(url)
    if (url.endsWith("/undo/preview")) return json({relative_path: "a.md", diff: "-abcd", size_before: 4, size_after: 0, approval_token: "approval"})
    if (url.endsWith("/undo/apply")) {expect(JSON.parse(String(init?.body)).approval_token).toBe("approval"); applied = true; return json({})}
    if (url.includes("/workspace/text")) return json({relative_path: "a.md", text: "abcd", size_bytes: 4, encoding: "utf-8", next_line: 2, has_more: false})
    if (url.endsWith("/workspace/changes")) return json(applied ? [] : [{change_id: "change", relative_path: "a.md", kind: "file", size_bytes: 4, exists: true, operation: "create"}])
    if (url.includes("/workspace?")) return json({display_path: "D:\\Work", directory: "", entries: applied ? [] : [{relative_path: "a.md", name: "a.md", kind: "file", size_bytes: 4}], total: applied ? 0 : 1, next_offset: 1, has_more: false})
    throw new Error(`Unexpected ${url}`)
  }))
})
afterEach(() => {cleanup(); clients.splice(0).forEach(client => client.clear()); vi.unstubAllGlobals()})
function mount(readOnly = false) {
  const client = new QueryClient({defaultOptions: {queries: {retry: false}, mutations: {retry: false}}})
  clients.push(client)
  return render(<QueryClientProvider client={client}><WorkspaceFilesPanel sessionId="session" workspaceId="workspace" readOnly={readOnly} busy={false} refreshKey="idle"/></QueryClientProvider>)
}
describe("workspace file results", () => {
  it("previews exact text and requires a separate confirmation to undo", async () => {
    mount()
    await userEvent.click(await screen.findByRole("button", {name: "查看内容"}))
    expect((await screen.findByText("abcd")).textContent).toBe("abcd")
    await userEvent.click(screen.getByRole("button", {name: "查看撤销差异"}))
    expect(await screen.findByText("-abcd")).toBeDefined()
    expect(applied).toBe(false)
    await userEvent.click(screen.getByRole("button", {name: "确认撤销"}))
    await waitFor(() => expect(applied).toBe(true))
    await waitFor(() => expect(screen.queryByRole("button", {name: "确认撤销"})).toBeNull())
  })
  it("cancels undo without changing the file", async () => {
    mount()
    await userEvent.click(await screen.findByRole("button", {name: "查看撤销差异"}))
    await userEvent.click(await screen.findByRole("button", {name: "取消"}))
    expect(applied).toBe(false)
    expect(calls.some(url => url.endsWith("/undo/apply"))).toBe(false)
  })
  it("allows browsing but disables undo in read-only mode", async () => {
    mount(true)
    const undo = await screen.findByRole("button", {name: "查看撤销差异"}) as HTMLButtonElement
    expect(undo.disabled).toBe(true)
    await userEvent.click(screen.getByRole("button", {name: "查看内容"}))
    expect(await screen.findByText("abcd")).toBeDefined()
  })
})
