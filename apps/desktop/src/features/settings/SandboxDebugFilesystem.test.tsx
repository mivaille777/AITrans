// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import SandboxDebugFilesystem from "./SandboxDebugFilesystem"

afterEach(() => cleanup())

const trace = {
  run: {
    sandbox_id: "sb-1",
    run_id: "run-1",
    tool_call_id: "tool-1",
    source: "agent" as const,
    workspace_id: "fsw-1",
    workspace_name: "AITrans",
    runtime: "docker",
    image: "aitrans-sandbox",
    status: "completed" as const,
    started_at: "",
    finished_at: "",
    duration_ms: 100,
    exit_code: 0,
  },
  stages: [],
  stdout: "",
  stderr: "",
  activities: [
    { sequence: 1, timestamp: "2026-09-26T10:24:01Z", kind: "file" as const, action: "read", target: "/input/data.csv", decision: "allowed" as const, reason: "" },
    { sequence: 2, timestamp: "2026-09-26T10:24:02Z", kind: "network" as const, action: "connect", target: "example.com:443", decision: "denied" as const, reason: "NETWORK_DISABLED" },
    { sequence: 3, timestamp: "2026-09-26T10:24:03Z", kind: "file" as const, action: "read", target: "C:\\Users\\someone\\.ssh\\id_rsa", decision: "denied" as const, reason: "PATH_OUTSIDE_WORKSPACE" },
    { sequence: 4, timestamp: "2026-09-26T10:24:04Z", kind: "process" as const, action: "spawn", target: "python3", decision: "observed" as const, reason: "" },
    { sequence: 5, timestamp: "2026-09-26T10:24:05Z", kind: "file" as const, action: "read", target: "/Users/someone/.ssh/id_ed25519", decision: "denied" as const, reason: "PATH_OUTSIDE_WORKSPACE" },
  ],
  resources: [],
  policy: {
    network: "none",
    root_filesystem_read_only: true,
    user: "10001:10001",
    cap_drop: ["ALL"],
    no_new_privileges: true,
    seccomp: "default",
    cpu_limit: 1,
    memory_limit_bytes: 1,
    pids_limit: 64,
    timeout_seconds: 30,
    stdout_limit_bytes: 1,
    stderr_limit_bytes: 1,
    docker_socket_mounted: false,
  },
  input_files: [
    { file_id: "in-1", path: "backend/main.py", size_bytes: 12000, sha256: "abc", source: "workspace" as const },
  ],
  output_files: [
    { file_id: "out-1", path: "result.csv", size_bytes: 21000, sha256: "def", source: "generated" as const },
  ],
  workspace_changes: [
    { operation: "modify" as const, path: "src/main.py", before_sha256: "a".repeat(64), after_sha256: "b".repeat(64), size_before: 10, size_after: 15, size_delta: 5 },
    { operation: "create" as const, path: "tests/test_main.py", before_sha256: null, after_sha256: "c".repeat(64), size_before: null, size_after: 12, size_delta: 12 },
    { operation: "delete" as const, path: "src/legacy.py", before_sha256: "d".repeat(64), after_sha256: null, size_before: 3, size_after: null, size_delta: -3 },
  ],
  error: "",
}

describe("SandboxDebugFilesystem", () => {
  it("renders staged inputs, activity and collected outputs", () => {
    render(<SandboxDebugFilesystem trace={trace} />)

    expect(screen.getAllByText("AITrans")).toHaveLength(2)
    expect(screen.getByText("backend/main.py")).toBeTruthy()
    expect(screen.getByText("/input/data.csv")).toBeTruthy()
    expect(screen.getByText("example.com:443")).toBeTruthy()
    expect(screen.getByText("result.csv")).toBeTruthy()
    expect(screen.getByText("Workspace Changes")).toBeTruthy()
    expect(screen.getByText("src/main.py")).toBeTruthy()
    expect(screen.getByText("tests/test_main.py")).toBeTruthy()
    expect(screen.getByText("src/legacy.py")).toBeTruthy()
    expect(screen.getByText("+5 B")).toBeTruthy()
    expect(screen.getByText("−3 B")).toBeTruthy()
    expect(screen.getByText("a".repeat(64))).toBeTruthy()
    expect(screen.getByText("b".repeat(64))).toBeTruthy()
  })

  it("filters denied activity", () => {
    render(<SandboxDebugFilesystem trace={trace} />)
    fireEvent.click(screen.getByRole("button", { name: "Denied only" }))

    expect(screen.queryByText("/input/data.csv")).toBeNull()
    expect(screen.getByText("example.com:443")).toBeTruthy()
  })

  it("filters process activity", () => {
    render(<SandboxDebugFilesystem trace={trace} />)
    fireEvent.click(screen.getByRole("button", { name: "Process" }))

    expect(screen.getByText("python3")).toBeTruthy()
    expect(screen.queryByText("/input/data.csv")).toBeNull()
  })

  it("never displays host paths verbatim across desktop platforms", () => {
    render(<SandboxDebugFilesystem trace={trace} />)

    expect(screen.queryByText(/C:\\Users\\/)).toBeNull()
    expect(screen.queryByText(/\/Users\/someone/)).toBeNull()
    expect(screen.getByText("[host path redacted]/id_rsa")).toBeTruthy()
    expect(screen.getByText("[host path redacted]/id_ed25519")).toBeTruthy()
    expect(screen.getAllByText("PATH_OUTSIDE_WORKSPACE").length).toBeGreaterThanOrEqual(2)
  })

  it("shows an empty state before a trace exists", () => {
    render(<SandboxDebugFilesystem trace={null} />)
    expect(screen.getByText("No filesystem activity recorded")).toBeTruthy()
  })
})
