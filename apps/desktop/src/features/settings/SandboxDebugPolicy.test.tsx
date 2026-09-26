// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import type {
  SandboxActivityEvent,
  SandboxDebugTrace,
  SandboxEffectivePolicy,
} from "../../api/sandbox-debug"
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

function traceWith(
  policy: SandboxEffectivePolicy,
  activities: SandboxActivityEvent[] = [],
): SandboxDebugTrace {
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
    activities,
    resources: [],
    policy,
    input_files: [],
    output_files: [],
    workspace_changes: [],
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
    expect(warnings).toContain("Network is not disabled or approval-gated.")
    expect(warnings).toContain("Sandbox is running as root.")
    expect(warnings).toContain("Root filesystem is writable.")
  })

  it("accepts the approval-gated restricted network policy", () => {
    expect(policyWarnings({ ...safePolicy, network: "restricted" })).not.toContain(
      "Network is not disabled or approval-gated.",
    )
  })

  it("shows permission decisions and the latest approval state", () => {
    const trace = traceWith(safePolicy, [
      {
        sequence: 1,
        timestamp: "",
        kind: "policy",
        action: "permission.approval_required",
        target: "src/main.py",
        decision: "approval_required",
        reason: "Host write requires explicit grant.",
        permission_action: "filesystem.apply_host",
        policy_rule: "workspace_write.host_apply",
      },
      ...(["pending", "approved", "denied", "expired", "consumed"] as const).map(
        (decision, index) => ({
          sequence: index + 2,
          timestamp: "",
          kind: "approval" as const,
          action: `approval.${decision}`,
          target: `src/file-${index}.py`,
          decision,
          reason: "Approval status changed.",
          approval_id: `apr-${index}`,
          permission_action: "filesystem.apply_host",
          policy_rule: "workspace_write.host_apply",
          grant_id: decision === "consumed" ? "grant-1" : "",
        }),
      ),
    ])

    render(<SandboxDebugPolicy trace={trace} />)

    expect(screen.getByText("filesystem.apply_host")).toBeTruthy()
    expect(screen.getByText("Approval Required")).toBeTruthy()
    expect(screen.getByText("workspace_write.host_apply")).toBeTruthy()
    expect(screen.getByText("Pending")).toBeTruthy()
    expect(screen.getByText("Approved")).toBeTruthy()
    expect(screen.getByText("Denied")).toBeTruthy()
    expect(screen.getByText("Expired")).toBeTruthy()
    expect(screen.getByText("Consumed")).toBeTruthy()
  })

  it("shows unsafe status visibly in the UI", () => {
    render(<SandboxDebugPolicy trace={traceWith({ ...safePolicy, docker_socket_mounted: true })} />)
    expect(screen.getByText("1 warning")).toBeTruthy()
    expect(screen.getAllByText("Unsafe").length).toBeGreaterThan(0)
  })
})
