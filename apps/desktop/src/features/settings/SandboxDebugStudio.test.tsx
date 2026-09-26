// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

vi.mock("../../api/sandbox-debug", () => ({
  getSandboxRuntimeHealth: vi.fn().mockResolvedValue({
    available: true,
    runtime: "docker",
    image: "aitrans-sandbox:latest",
    daemon_ready: true,
    os_type: "linux",
    detail: "",
  }),
  getSandboxDebugRun: vi.fn(),
}))

vi.mock("./SandboxDebugTrace", () => ({
  default: ({ selectedTrace }: { selectedTrace?: { run?: { sandbox_id?: string } } | null }) => (
    <div>Sandbox trace content{selectedTrace?.run?.sandbox_id ? ` · ${selectedTrace.run.sandbox_id}` : ""}</div>
  ),
}))
vi.mock("./SandboxDebugFilesystem", () => ({ default: () => <div>No filesystem activity recorded</div> }))
vi.mock("./SandboxDebugResources", () => ({ default: () => <div>No resource samples recorded</div> }))
vi.mock("./SandboxDebugPolicy", () => ({ default: () => <div>No effective policy recorded</div> }))
vi.mock("./SandboxDebugRuns", () => ({ default: () => <div>No sandbox runs recorded</div> }))

import { getSandboxDebugRun, getSandboxRuntimeHealth } from "../../api/sandbox-debug"
import SandboxDebugStudio from "./SandboxDebugStudio"

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe("SandboxDebugStudio", () => {
  it("renders the studio shell and all five tabs", async () => {
    render(<SandboxDebugStudio />)

    expect(screen.getByText("Sandbox Debug Studio")).toBeTruthy()
    await waitFor(() => expect(screen.getByText("Docker · Ready")).toBeTruthy())

    for (const label of ["Trace", "Filesystem", "Resources", "Policy", "Runs"]) {
      const tab = screen.getByRole("tab", { name: label })
      expect((tab as HTMLButtonElement).disabled).toBe(false)
    }
  })

  it("shows a safe backend-specific runtime reason", async () => {
    vi.mocked(getSandboxRuntimeHealth).mockResolvedValueOnce({
      available: false,
      runtime: "docker",
      image: "aitrans-sandbox:latest",
      daemon_ready: false,
      os_type: "windows",
      detail: "",
      error_code: "docker_not_linux",
    })

    render(<SandboxDebugStudio />)

    await waitFor(() => expect(screen.getByText("Sandbox requires a Linux Docker runtime.")).toBeTruthy())
  })

  it("starts on Trace and switches between tab panels", () => {
    render(<SandboxDebugStudio />)

    expect(screen.getByRole("tab", { name: "Trace" }).getAttribute("aria-selected")).toBe("true")
    expect(screen.getByText("Sandbox trace content")).toBeTruthy()

    fireEvent.click(screen.getByRole("tab", { name: "Filesystem" }))
    expect(screen.getByRole("tab", { name: "Filesystem" }).getAttribute("aria-selected")).toBe("true")
    expect(screen.getByText("No filesystem activity recorded")).toBeTruthy()

    fireEvent.click(screen.getByRole("tab", { name: "Resources" }))
    expect(screen.getByText("No resource samples recorded")).toBeTruthy()

    fireEvent.click(screen.getByRole("tab", { name: "Policy" }))
    expect(screen.getByText("No effective policy recorded")).toBeTruthy()

    fireEvent.click(screen.getByRole("tab", { name: "Runs" }))
    expect(screen.getByText("No sandbox runs recorded")).toBeTruthy()
  })

  it("supports arrow, Home and End keyboard navigation between tabs", async () => {
    render(<SandboxDebugStudio />)

    const traceTab = screen.getByRole("tab", { name: "Trace" })
    const filesystemTab = screen.getByRole("tab", { name: "Filesystem" })
    const runsTab = screen.getByRole("tab", { name: "Runs" })

    traceTab.focus()
    fireEvent.keyDown(traceTab, { key: "ArrowRight" })
    expect(filesystemTab.getAttribute("aria-selected")).toBe("true")
    await waitFor(() => expect(document.activeElement).toBe(filesystemTab))

    fireEvent.keyDown(filesystemTab, { key: "End" })
    expect(runsTab.getAttribute("aria-selected")).toBe("true")
    await waitFor(() => expect(document.activeElement).toBe(runsTab))

    fireEvent.keyDown(runsTab, { key: "Home" })
    expect(traceTab.getAttribute("aria-selected")).toBe("true")
    await waitFor(() => expect(document.activeElement).toBe(traceTab))
  })

  it("moves the active underline with the selected tab", () => {
    render(<SandboxDebugStudio />)

    const traceTab = screen.getByRole("tab", { name: "Trace" })
    const policyTab = screen.getByRole("tab", { name: "Policy" })

    expect(traceTab.querySelector("span")?.className).toContain("scale-x-100")
    expect(policyTab.querySelector("span")?.className).toContain("scale-x-0")

    fireEvent.click(policyTab)

    expect(traceTab.querySelector("span")?.className).toContain("scale-x-0")
    expect(policyTab.querySelector("span")?.className).toContain("scale-x-100")
  })

  it("shows an unavailable state when the requested trace cannot be loaded", async () => {
    vi.mocked(getSandboxDebugRun).mockRejectedValue(new Error("raw daemon path C:\\Users\\secret"))

    render(<SandboxDebugStudio initialSandboxId="sb-missing" />)

    await waitFor(() => expect(screen.getByRole("alert").textContent).toContain("Sandbox trace is unavailable."))
    expect(screen.queryByText(/C:\\Users\\secret/)).toBeNull()
  })

  it("loads the requested trace when navigation provides a sandbox id", async () => {
    vi.mocked(getSandboxDebugRun).mockResolvedValue({
      run: {
        sandbox_id: "sb-123",
        run_id: "run-123",
        tool_call_id: "tool-123",
        source: "agent",
        workspace_id: "fsw-123",
        workspace_name: "AITrans",
        runtime: "docker",
        image: "aitrans-sandbox:latest",
        status: "completed",
        started_at: "",
        finished_at: "",
        duration_ms: 842,
        exit_code: 0,
      },
      stages: [],
      stdout: "",
      stderr: "",
      activities: [],
      workspace_changes: [],
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
    })

    render(<SandboxDebugStudio initialSandboxId="sb-123" />)

    await waitFor(() => expect(getSandboxDebugRun).toHaveBeenCalledWith("sb-123"))
    await waitFor(() => expect(screen.getByText("Sandbox trace content · sb-123")).toBeTruthy())
    expect(screen.getByRole("tab", { name: "Trace" }).getAttribute("aria-selected")).toBe("true")
  })
})
