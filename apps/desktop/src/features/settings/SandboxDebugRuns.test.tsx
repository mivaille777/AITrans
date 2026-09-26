import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

vi.mock("../../api/sandbox-debug", () => ({
  listSandboxDebugRuns: vi.fn(),
  getSandboxDebugRun: vi.fn(),
}))

import { getSandboxDebugRun, listSandboxDebugRuns } from "../../api/sandbox-debug"
import SandboxDebugRuns from "./SandboxDebugRuns"

const runs = [
  { sandbox_id: "sb-1", run_id: "run-1", tool_call_id: "tool-1", source: "agent" as const, workspace_id: "fsw-1", workspace_name: "AITrans", runtime: "docker", image: "", status: "completed" as const, started_at: "2026-09-26T10:00:00Z", finished_at: "", duration_ms: 1210, exit_code: 0 },
  { sandbox_id: "sb-2", run_id: "run-2", tool_call_id: "tool-2", source: "manual" as const, workspace_id: "", workspace_name: "", runtime: "docker", image: "", status: "timed_out" as const, started_at: "2026-09-26T10:01:00Z", finished_at: "", duration_ms: 30000, exit_code: null },
]

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe("SandboxDebugRuns", () => {
  it("lists and filters runs", async () => {
    vi.mocked(listSandboxDebugRuns).mockResolvedValue(runs)
    render(<SandboxDebugRuns onSelectTrace={vi.fn()} />)

    await waitFor(() => expect(screen.getByText("sb-1")).toBeTruthy())
    expect(screen.getByText("sb-2")).toBeTruthy()

    fireEvent.change(screen.getByLabelText("Run source"), { target: { value: "agent" } })
    expect(screen.getByText("sb-1")).toBeTruthy()
    expect(screen.queryByText("sb-2")).toBeNull()
  })

  it("selects a run and returns its trace", async () => {
    vi.mocked(listSandboxDebugRuns).mockResolvedValue(runs)
    const trace = { run: runs[0], stages: [], stdout: "", stderr: "", activities: [], resources: [], policy: {}, input_files: [], output_files: [], error: "" } as any
    vi.mocked(getSandboxDebugRun).mockResolvedValue(trace)
    const onSelectTrace = vi.fn()
    render(<SandboxDebugRuns onSelectTrace={onSelectTrace} />)

    await waitFor(() => expect(screen.getByRole("button", { name: "sb-1" })).toBeTruthy())
    fireEvent.click(screen.getByRole("button", { name: "sb-1" }))

    await waitFor(() => expect(getSandboxDebugRun).toHaveBeenCalledWith("sb-1"))
    expect(onSelectTrace).toHaveBeenCalledWith(trace)
  })

  it("shows an empty state", async () => {
    vi.mocked(listSandboxDebugRuns).mockResolvedValue([])
    render(<SandboxDebugRuns onSelectTrace={vi.fn()} />)
    await waitFor(() => expect(screen.getByText("No sandbox runs recorded")).toBeTruthy())
  })

  it("shows API errors", async () => {
    vi.mocked(listSandboxDebugRuns).mockRejectedValue(new Error("backend unavailable"))
    render(<SandboxDebugRuns onSelectTrace={vi.fn()} />)
    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("backend unavailable"))
  })
})
