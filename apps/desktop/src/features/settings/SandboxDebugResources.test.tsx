// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import SandboxDebugResources from "./SandboxDebugResources"

afterEach(() => cleanup())

function makeTrace(overrides: Record<string, unknown> = {}) {
  return {
    run: {
      sandbox_id: "sb-1",
      run_id: "run-1",
      tool_call_id: "",
      source: "manual" as const,
      workspace_id: "",
      workspace_name: "",
      runtime: "docker",
      image: "",
      status: "completed" as const,
      started_at: "",
      finished_at: "",
      duration_ms: 1200,
      exit_code: 0,
      ...(overrides.run as object | undefined),
    },
    stages: [],
    stdout: "",
    stderr: "",
    activities: [],
    resources: [
      { timestamp_ms: 0, cpu_percent: 20, memory_bytes: 64 * 1024 * 1024, pids: 2, stdout_bytes: 1024, stderr_bytes: 0, output_bytes: 1024 },
      { timestamp_ms: 100, cpu_percent: 38, memory_bytes: 72 * 1024 * 1024, pids: 4, stdout_bytes: 21 * 1024, stderr_bytes: 0, output_bytes: 31 * 1024 },
    ],
    policy: {
      network: "none",
      root_filesystem_read_only: true,
      user: "10001:10001",
      cap_drop: ["ALL"],
      no_new_privileges: true,
      seccomp: "default",
      cpu_limit: 1,
      memory_limit_bytes: 512 * 1024 * 1024,
      pids_limit: 64,
      timeout_seconds: 30,
      stdout_limit_bytes: 1024 * 1024,
      stderr_limit_bytes: 1024 * 1024,
      output_limit_bytes: 50 * 1024 * 1024,
      docker_socket_mounted: false,
    },
    input_files: [],
    output_files: [],
    error: "",
    ...overrides,
  }
}

describe("SandboxDebugResources", () => {
  it("renders peak values and limits", () => {
    render(<SandboxDebugResources trace={makeTrace()} />)

    expect(screen.getByText("38 %")).toBeTruthy()
    expect(screen.getByText("72.0 MB / 512.0 MB")).toBeTruthy()
    expect(screen.getByText("4 / 64")).toBeTruthy()
    expect(screen.getByText("1.2 s / 30.0 s")).toBeTruthy()
    expect(screen.getByText("31.0 KB / 50.0 MB")).toBeTruthy()
  })

  it("shows an amber warning near a resource limit", () => {
    render(<SandboxDebugResources trace={makeTrace({
      resources: [{ timestamp_ms: 0, cpu_percent: 85, memory_bytes: 480 * 1024 * 1024, pids: 60, stdout_bytes: 0, stderr_bytes: 0, output_bytes: 0 }],
    })} />)

    expect(screen.getByText("480.0 MB / 512.0 MB").parentElement?.className).toContain("border-amber-200")
  })

  it("warns when stdout approaches its limit", () => {
    render(<SandboxDebugResources trace={makeTrace({
      resources: [{ timestamp_ms: 0, cpu_percent: 10, memory_bytes: 32 * 1024 * 1024, pids: 2, stdout_bytes: 900 * 1024, stderr_bytes: 0, output_bytes: 900 * 1024 }],
    })} />)

    expect(screen.getByText("900.0 KB / 1.0 MB").parentElement?.className).toContain("border-amber-200")
  })

  it("warns when collected outputs approach the real sandbox limit", () => {
    render(<SandboxDebugResources trace={makeTrace({
      resources: [{
        timestamp_ms: 0,
        cpu_percent: 10,
        memory_bytes: 32 * 1024 * 1024,
        pids: 2,
        stdout_bytes: 0,
        stderr_bytes: 0,
        output_bytes: 45 * 1024 * 1024,
      }],
    })} />)

    expect(screen.getByText("45.0 MB / 50.0 MB").parentElement?.className).toContain("border-amber-200")
  })

  it("shows OOM termination explicitly", () => {
    render(<SandboxDebugResources trace={makeTrace({ run: { status: "oom_killed" } })} />)
    expect(screen.getByText("Sandbox was terminated for memory use.")).toBeTruthy()
  })

  it("handles an empty sample series", () => {
    render(<SandboxDebugResources trace={makeTrace({ resources: [] })} />)
    expect(screen.getByText("No resource samples recorded")).toBeTruthy()
  })
})
