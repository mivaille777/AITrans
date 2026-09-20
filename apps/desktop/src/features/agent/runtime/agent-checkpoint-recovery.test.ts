// @vitest-environment jsdom

import { beforeEach, describe, expect, it } from "vitest"

import type { AgentStreamAcceptedEvent } from "../../../api/agent-stream"
import {
  AGENT_PENDING_RUN_MAX_AGE_MS,
  AGENT_PENDING_RUN_STORAGE_KEY,
  buildAgentResumeRequest,
  clearPendingAgentRun,
  readPendingAgentRun,
  rememberPendingAgentRun,
} from "./agent-checkpoint-recovery"

const accepted: AgentStreamAcceptedEvent = {
  type: "accepted",
  request_id: 17,
  session_id: "session-checkpoint",
  run_id: "run-checkpoint",
  trace_id: "trace-checkpoint",
}

describe("agent checkpoint recovery", () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it("stores only the accepted run identity", () => {
    rememberPendingAgentRun(accepted, 1_000)

    expect(readPendingAgentRun(1_001)).toEqual({
      runId: "run-checkpoint",
      traceId: "trace-checkpoint",
      sessionId: "session-checkpoint",
      requestId: 17,
      acceptedAt: 1_000,
    })
    expect(window.localStorage.getItem(AGENT_PENDING_RUN_STORAGE_KEY)).not.toContain(
      "source_text",
    )
  })

  it("does not persist a temporary run recovery record", () => {
    expect(rememberPendingAgentRun(accepted, 1_000, true)).toBeNull()
    expect(window.localStorage.getItem(AGENT_PENDING_RUN_STORAGE_KEY)).toBeNull()
  })

  it("builds a minimal explicit resume request without user content", () => {
    const pending = rememberPendingAgentRun(accepted, 1_000)

    expect(pending).not.toBeNull()
    expect(buildAgentResumeRequest(pending!, "en")).toMatchObject({
      session_id: "session-checkpoint",
      trace_id: "trace-checkpoint",
      resume_run_id: "run-checkpoint",
      request_id: 17,
      user_message: "Resume interrupted Agent run.",
      source_text: "",
      target_language: "en",
    })
  })

  it("uses the same resume contract for a task retry without carrying approval", () => {
    const pending = rememberPendingAgentRun(accepted, 1_000)
    const request = buildAgentResumeRequest(pending!, "zh-CN", "research-1")
    expect(request.resume_run_id).toBe("run-checkpoint")
    expect(request.retry_task_id).toBe("research-1")
    expect(request.confirmed_write_tools).toBeUndefined()
  })

  it("expires stale or future-dated recovery records", () => {
    rememberPendingAgentRun(accepted, 1_000)
    expect(readPendingAgentRun(1_000 + AGENT_PENDING_RUN_MAX_AGE_MS + 1)).toBeNull()

    rememberPendingAgentRun(accepted, 2_000)
    expect(readPendingAgentRun(1_999)).toBeNull()
  })

  it("does not let an older terminal event clear a newer run", () => {
    rememberPendingAgentRun(
      { ...accepted, run_id: "run-newer" },
      Date.now(),
    )

    clearPendingAgentRun("run-older")
    expect(readPendingAgentRun()?.runId).toBe("run-newer")

    clearPendingAgentRun("run-newer")
    expect(readPendingAgentRun()).toBeNull()
  })
})
