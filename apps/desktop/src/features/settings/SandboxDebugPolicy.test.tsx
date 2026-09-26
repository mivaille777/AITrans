// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import type { SandboxEffectivePolicy } from "../../api/sandbox-debug"
import SandboxDebugPolicy, { policyWarnings } from "./SandboxDebugPolicy"

afterEach(() => cleanup())

const safePolicy: SandboxEffectivePolicy = {
  network: "none",
  root_filesystem_read_only: true,
  user: "10001:10001",
  cap_drop: ["ALL"],
  no_new_privileges: true,
  seccomp: "Docker default",
  cpu_limit: 1,
  memory_limit_bytes: 512 * 1024 * 1024,
  pids_limit: 64,
  timeout_seconds: 30,
  stdout_limit_bytes: 1024 * 1024,
  stderr_limit_bytes: 1024 * 1024,
  output_limit_bytes: 50 * 1024 * 1024,
  docker_socket_mounted: false,
}

function traceWith(policy: SandboxEffectivePolicy) {
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
      duration_ms: 1,
      exit_code: 0,
    },
    stages: [],
    stdout: "",
    stderr: "",
    activities: [],
    resources: [],
    policy,
    input_files: [],
    output_files: [],
    error: "",
  }
}

describe("SandboxDebugPolicy", () => {
  it("renders a safe policy as enforced", () => {
    render(<SandboxDebugPolicy trace={traceWith(safePolicy)} />)
    expect(screen.getByText("Policy enforced")).toBeTruthy()
    expect(screen.getByText("not mounted")).toBeTruthy()
  })

  it("detects unconfined seccomp", () => {
    expect(policyWarnings({ ...safePolicy, seccomp: "unconfined" })).toContain("Seccomp is unconfined.")
  })

  it("detects a mounted Docker socket", () => {
    expect(policyWarnings({ ...safePolicy, docker_socket_mounted: true })).toContain("Docker socket is mounted.")
  })

  it("marks an unreported Docker socket state as unknown instead of safe", () => {
    const policy = { ...safePolicy, docker_socket_mounted: null }
    expect(policyWarnings(policy)).toContain("Docker socket mount status is unknown.")

    render(<SandboxDebugPolicy trace={traceWith(policy)} />)
    expect(screen.getByText("unknown")).toBeTruthy()
    expect(screen.getByText("Unknown")).toBeTruthy()
  })

  it("detects network, root user and writable root filesystem", () => {
    const warnings = policyWarnings({
      ...safePolicy,
      network: "bridge",
      user: "0:0",
      root_filesystem_read_only: false,
    })
    expect(warnings).toContain("Network is not disabled.")
    expect(warnings).toContain("Sandbox is running as root.")
    expect(warnings).toContain("Root filesystem is writable.")
  })

  it("shows unsafe status visibly in the UI", () => {
    render(<SandboxDebugPolicy trace={traceWith({ ...safePolicy, docker_socket_mounted: true })} />)
    expect(screen.getByText("1 warning")).toBeTruthy()
    expect(screen.getAllByText("Unsafe").length).toBeGreaterThan(0)
  })
})
