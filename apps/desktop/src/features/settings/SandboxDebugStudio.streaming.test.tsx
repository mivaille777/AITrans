// @vitest-environment jsdom
import { Profiler } from "react"
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"
import type { SandboxDebugStreamHandlers, SandboxDebugTrace } from "../../api/sandbox-debug"

const api = vi.hoisted(() => ({
  start: vi.fn(), get: vi.fn(), stream: vi.fn(), close: vi.fn(),
}))
vi.mock("../../api/sandbox-debug", () => ({
  getSandboxRuntimeHealth: vi.fn().mockResolvedValue({ available: true, daemon_ready: true, runtime: "docker", image: "sandbox:v1" }),
  startSandboxDebugRun: api.start,
  getSandboxDebugRun: api.get,
  streamSandboxDebugRun: api.stream,
  cancelSandboxDebugRun: vi.fn(),
}))
vi.mock("../../api/filesystem-workspaces", () => ({ listFilesystemWorkspaces: vi.fn().mockResolvedValue([]) }))
vi.mock("./SandboxDebugFilesystem", () => ({ default: ({ trace }: { trace: SandboxDebugTrace | null }) => <div>Files for {trace?.run.sandbox_id}</div> }))
vi.mock("./SandboxDebugResources", () => ({ default: () => null }))
vi.mock("./SandboxDebugPolicy", () => ({ default: () => null }))
vi.mock("./SandboxDebugRuns", () => ({ default: () => null }))
import SandboxDebugStudio from "./SandboxDebugStudio"

function trace(id: string, status: "preparing" | "completed", stdout = ""): SandboxDebugTrace {
  return {
    run: { sandbox_id: id, run_id: `run-${id}`, tool_call_id: "", source: "manual", workspace_id: "", workspace_name: "", runtime: "docker", image: "sandbox:v1", status, started_at: "", finished_at: "", duration_ms: status === "completed" ? 900 : 0, exit_code: status === "completed" ? 0 : null },
    stages: [{ key: "collect", label: "Collect", status: status === "completed" ? "complete" : "running", elapsed_ms: 0, note: "" }],
    stdout, stderr: "", activities: [], resources: [],
    policy: { network: "none", root_filesystem_read_only: true, user: "10001:10001", cap_drop: ["ALL"], no_new_privileges: true, seccomp: "default", cpu_limit: 1, memory_limit_bytes: 536870912, pids_limit: 64, timeout_seconds: 30, stdout_limit_bytes: 1048576, stderr_limit_bytes: 1048576, docker_socket_mounted: false },
    input_files: [], output_files: [], workspace_changes: [], error: "",
  }
}

afterEach(() => { cleanup(); vi.clearAllMocks() })

describe("SandboxDebugStudio streaming integration", () => {
  it("starts a new run after navigation to an older trace without restoring the selection", async () => {
    let handlers!: SandboxDebugStreamHandlers
    api.stream.mockImplementation((_id: string, next: SandboxDebugStreamHandlers) => { handlers = next; return { close: api.close } })
    api.get.mockResolvedValueOnce(trace("history", "completed", "old output"))
      .mockResolvedValueOnce(trace("new", "preparing"))
    api.start.mockResolvedValue({ sandbox_id: "new", run_id: "run-new", status: "pending" })
    let renders = 0
    render(<Profiler id="navigation" onRender={() => {
      renders += 1
      if (renders > 80) throw new Error("History selection feedback loop")
    }}><SandboxDebugStudio initialSandboxId="history" /></Profiler>)
    await waitFor(() => expect(screen.getByText("old output")).toBeTruthy())
    await waitFor(() => expect(screen.getByText("Docker · Ready")).toBeTruthy())
    fireEvent.click(screen.getByRole("button", { name: "Run" }))
    await waitFor(() => expect(api.stream).toHaveBeenCalledWith("new", expect.any(Object)))
    expect(screen.getByRole("button", { name: "Stop" })).toBeTruthy()
    expect(screen.queryByText("old output")).toBeNull()
    act(() => handlers.onEvent({ type: "terminal", trace: trace("new", "completed", "new output") }))
    expect(screen.getByText("new output")).toBeTruthy()
    expect(screen.queryByText("old output")).toBeNull()
    expect(renders).toBeLessThan(35)
  })

  it("keeps consecutive runs stable and publishes final output to other tabs", async () => {
    const handlers: SandboxDebugStreamHandlers[] = []
    api.stream.mockImplementation((_id: string, next: SandboxDebugStreamHandlers) => { handlers.push(next); return { close: api.close } })
    api.start.mockResolvedValueOnce({ sandbox_id: "first", run_id: "run-first", status: "pending" })
      .mockResolvedValueOnce({ sandbox_id: "second", run_id: "run-second", status: "pending" })
    api.get.mockResolvedValueOnce(trace("first", "preparing"))
      .mockResolvedValueOnce(trace("second", "preparing"))
    let renders = 0
    render(<Profiler id="studio" onRender={() => {
      renders += 1
      if (renders > 80) throw new Error("Trace selection feedback loop")
    }}><SandboxDebugStudio /></Profiler>)
    await waitFor(() => expect(screen.getByText("Docker · Ready")).toBeTruthy())
    fireEvent.change(screen.getByLabelText("Python Code"), { target: { value: 'print("Hello from AITran Sandbox")' } })
    fireEvent.click(screen.getByRole("button", { name: "Run" }))
    await waitFor(() => expect(handlers).toHaveLength(1))
    act(() => handlers[0].onEvent({ type: "terminal", trace: trace("first", "completed", "Hello from AITran Sandbox\n") }))
    await waitFor(() => expect(screen.getByText("Hello from AITran Sandbox")).toBeTruthy())

    fireEvent.click(screen.getByRole("button", { name: "Run" }))
    await waitFor(() => expect(handlers).toHaveLength(2))
    expect(screen.getByRole("button", { name: "Stop" })).toBeTruthy()
    expect(screen.queryByText("Hello from AITran Sandbox")).toBeNull()
    act(() => handlers[0].onEvent({ type: "terminal", trace: trace("first", "completed", "stale output") }))
    act(() => handlers[1].onEvent({ type: "terminal", trace: trace("second", "completed", "Hello from AITran Sandbox\n") }))
    expect(screen.getByText("second")).toBeTruthy()
    expect(screen.getByText("Hello from AITran Sandbox")).toBeTruthy()
    expect(screen.queryByText("stale output")).toBeNull()
    expect(api.start).toHaveBeenCalledTimes(2)
    expect(api.start).toHaveBeenLastCalledWith({ code: 'print("Hello from AITran Sandbox")' })
    fireEvent.click(screen.getByRole("tab", { name: "Filesystem" }))
    expect(screen.getByText("Files for second")).toBeTruthy()
    fireEvent.click(screen.getByRole("tab", { name: "Trace" }))
    expect(screen.getByText("Hello from AITran Sandbox")).toBeTruthy()
    expect(renders).toBeLessThan(35)
  })
})
