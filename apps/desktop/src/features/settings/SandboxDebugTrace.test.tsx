import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

const closeStream = vi.fn()
let streamHandlers: {
  onEvent: (event: any) => void
  onTransportError: (error: Error) => void
} | null = null

vi.mock("../../api/sandbox-debug", () => ({
  startSandboxDebugRun: vi.fn(),
  getSandboxDebugRun: vi.fn(),
  cancelSandboxDebugRun: vi.fn(),
  streamSandboxDebugRun: vi.fn((_sandboxId: string, handlers: any) => {
    streamHandlers = handlers
    return { close: closeStream }
  }),
}))

import {
  cancelSandboxDebugRun,
  getSandboxDebugRun,
  startSandboxDebugRun,
} from "../../api/sandbox-debug"
import SandboxDebugTrace from "./SandboxDebugTrace"

const health = {
  available: true,
  runtime: "docker" as const,
  image: "aitrans-sandbox:latest",
  daemon_ready: true,
  os_type: "linux",
  detail: "",
}

function makeTrace(overrides: Record<string, unknown> = {}) {
  return {
    run: {
      sandbox_id: "sb-1",
      run_id: "run-1",
      tool_call_id: "tool-1",
      source: "manual" as const,
      workspace_id: "",
      workspace_name: "",
      runtime: "docker",
      image: "aitrans-sandbox:latest",
      status: "completed" as const,
      started_at: "2026-09-26T12:00:00Z",
      finished_at: "2026-09-26T12:00:01Z",
      duration_ms: 842,
      exit_code: 0,
      ...(overrides.run as object | undefined),
    },
    stages: [
      { key: "request" as const, label: "Request", status: "complete" as const, elapsed_ms: 2, note: "" },
      { key: "execute" as const, label: "Execute", status: "complete" as const, elapsed_ms: 800, note: "" },
      { key: "cleanup" as const, label: "Cleanup", status: "complete" as const, elapsed_ms: 20, note: "" },
    ],
    stdout: "285",
    stderr: "",
    activities: [],
    resources: [],
    policy: {
      network: "none",
      root_filesystem_read_only: true,
      user: "10001:10001",
      cap_drop: ["ALL"],
      no_new_privileges: true,
      seccomp: "default",
      cpu_limit: 1,
      memory_limit_bytes: 536870912,
      pids_limit: 64,
      timeout_seconds: 30,
      stdout_limit_bytes: 1048576,
      stderr_limit_bytes: 1048576,
      docker_socket_mounted: false,
    },
    input_files: [],
    output_files: [],
    error: "",
    ...overrides,
  }
}

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
  closeStream.mockClear()
  streamHandlers = null
})

describe("SandboxDebugTrace", () => {
  it("runs Python and renders a completed trace", async () => {
    vi.mocked(startSandboxDebugRun).mockResolvedValue({
      sandbox_id: "sb-1",
      run_id: "run-1",
      status: "pending",
    })
    vi.mocked(getSandboxDebugRun).mockResolvedValue(makeTrace())

    render(<SandboxDebugTrace health={health} />)
    fireEvent.change(screen.getByLabelText("Python Code"), { target: { value: "print(285)" } })
    fireEvent.click(screen.getByRole("button", { name: "Run" }))

    await waitFor(() => expect(startSandboxDebugRun).toHaveBeenCalledWith({ code: "print(285)" }))
    await waitFor(() => expect(screen.getByText("285")).toBeTruthy())
    expect(screen.getByText("842 ms")).toBeTruthy()
    expect(screen.getByText("0")).toBeTruthy()
  })

  it("renders runtime errors from a terminal trace", async () => {
    vi.mocked(startSandboxDebugRun).mockResolvedValue({
      sandbox_id: "sb-1",
      run_id: "run-1",
      status: "pending",
    })
    vi.mocked(getSandboxDebugRun).mockResolvedValue(makeTrace({
      run: { status: "failed", exit_code: 1 },
      stdout: "",
      stderr: "Traceback: boom",
    }))

    render(<SandboxDebugTrace health={health} />)
    fireEvent.click(screen.getByRole("button", { name: "Run" }))

    await waitFor(() => expect(screen.getByText("Traceback: boom")).toBeTruthy())
    expect(screen.getByText("failed")).toBeTruthy()
  })

  it("renders timeout lifecycle from a streamed terminal trace", async () => {
    vi.mocked(startSandboxDebugRun).mockResolvedValue({
      sandbox_id: "sb-1",
      run_id: "run-1",
      status: "pending",
    })
    vi.mocked(getSandboxDebugRun).mockRejectedValue(new Error("not ready"))

    render(<SandboxDebugTrace health={health} />)
    fireEvent.click(screen.getByRole("button", { name: "Run" }))

    await waitFor(() => expect(screen.getByRole("button", { name: "Stop" })).toBeTruthy())
    streamHandlers?.onEvent({
      type: "terminal",
      trace: makeTrace({
        run: { status: "timed_out", duration_ms: 30000, exit_code: null },
        stages: [
          { key: "execute", label: "Execute", status: "failed", elapsed_ms: 30000, note: "Timed out" },
          { key: "cleanup", label: "Cleanup", status: "complete", elapsed_ms: 20, note: "" },
        ],
      }),
    })

    await waitFor(() => expect(screen.getByText("timed_out")).toBeTruthy())
    expect(screen.getByText(/failed · 30000 ms/)).toBeTruthy()
    expect(screen.getByText(/complete · 20 ms/)).toBeTruthy()
  })

  it("disables Run when Docker is unavailable", () => {
    render(<SandboxDebugTrace health={{ ...health, available: false, daemon_ready: false }} />)

    expect(screen.getByText("Runtime unavailable")).toBeTruthy()
    expect((screen.getByRole("button", { name: "Run" }) as HTMLButtonElement).disabled).toBe(true)
  })

  it("cancels an active run", async () => {
    vi.mocked(startSandboxDebugRun).mockResolvedValue({
      sandbox_id: "sb-1",
      run_id: "run-1",
      status: "pending",
    })
    vi.mocked(getSandboxDebugRun)
      .mockRejectedValueOnce(new Error("not ready"))
      .mockResolvedValueOnce(makeTrace({ run: { status: "cancelled", exit_code: null } }))
    vi.mocked(cancelSandboxDebugRun).mockResolvedValue({
      ...makeTrace().run,
      status: "cancelled",
      exit_code: null,
    })

    render(<SandboxDebugTrace health={health} />)
    fireEvent.click(screen.getByRole("button", { name: "Run" }))
    await waitFor(() => expect(screen.getByRole("button", { name: "Stop" })).toBeTruthy())

    fireEvent.click(screen.getByRole("button", { name: "Stop" }))

    await waitFor(() => expect(cancelSandboxDebugRun).toHaveBeenCalledWith("sb-1"))
    await waitFor(() => expect(screen.getByText("cancelled")).toBeTruthy())
    expect(closeStream).toHaveBeenCalled()
  })
})
