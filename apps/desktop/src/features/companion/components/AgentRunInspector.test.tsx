import { describe, expect, it } from "vitest"
import type { AgentTraceEvent } from "../../../api/agent"
import { deriveChatAgentProgress, deriveChatTaskAcceptance } from "./AgentRunInspector"

function event(sequence: number, event_type: AgentTraceEvent["event_type"], payload: Record<string, unknown> = {}, extra: Partial<AgentTraceEvent> = {}): AgentTraceEvent {
  return { sequence, event_type, payload, timestamp: "", run_id: "run", trace_id: "trace", elapsed_ms: 0, ...extra }
}

it("replaces pre-confirmation acceptance with the resumed final receipt", () => {
  const events = [event(1, "task_verification", {status: "pending"}), event(2, "task_verification", {status: "completed"})]
  const progress = deriveChatAgentProgress(events, "completed")
  expect(progress).toHaveLength(1)
  expect(progress[0].status).toBe("complete")
  expect(deriveChatTaskAcceptance(events)?.status).toBe("completed")
})

describe("Agent progress", () => {
  it("preserves failed verification after a physical result and run end", () => {
    const events = [event(0, "tool_call", { name: "python_execute" }, { tool_call_id: "a" }),
      event(1, "tool_result", { status: "failed" }, { tool_call_id: "a" }),
      event(2, "tool_verification", { status: "failed" }, { tool_call_id: "a" }),
      event(3, "task_verification", { status: "partial", passed: 1, total: 2 }), event(4, "agent_end")]
    expect(deriveChatAgentProgress(events, "completed").filter(item => item.status === "failed")).toHaveLength(2)
    expect(deriveChatTaskAcceptance(events)?.status).toBe("partial")
  })

  it("does not infer acceptance for historical runs", () => {
    expect(deriveChatTaskAcceptance([event(0, "agent_end")])).toBeNull()
  })
  it("completes the checkpoints in the reported 2/9 regression", () => {
    const types: AgentTraceEvent["event_type"][] = ["agent_start", "context_ready", "knowledge_decision", "knowledge_scope_resolved", "plan_ready", "react_started", "decision_ready", "synthesis_ready", "agent_end"]
    const progress = deriveChatAgentProgress(types.map((type, i) => event(i, type)), "completed")
    expect(progress).toHaveLength(9)
    expect(progress.every(item => item.status === "complete")).toBe(true)
    expect(progress.every(item => !item.detail.includes("Runtime event received"))).toBe(true)
  })

  it("tracks repeated tool calls by invocation and preserves start order", () => {
    const progress = deriveChatAgentProgress([
      event(0, "tool_call", {name: "read_workspace_file"}, {tool_call_id: "a"}),
      event(1, "tool_call", {name: "read_workspace_file"}, {tool_call_id: "b"}),
      event(2, "tool_result", {tool_name: "read_workspace_file"}, {tool_call_id: "b"}),
      event(3, "tool_result", {tool_name: "read_workspace_file"}, {tool_call_id: "a"}),
    ], "completed")
    expect(progress.map(item => item.id)).toEqual(["call:a", "call:b"])
    expect(progress.map(item => item.status)).toEqual(["complete", "complete"])
  })

  it("keeps legacy serial invocations separate", () => {
    const progress = deriveChatAgentProgress([
      event(0, "tool_call", {name: "read_workspace_file"}),
      event(1, "tool_result", {tool_name: "read_workspace_file"}),
      event(2, "tool_call", {name: "read_workspace_file"}),
      event(3, "tool_result", {tool_name: "read_workspace_file"}),
    ], "completed")
    expect(progress).toHaveLength(2)
    expect(progress.every(item => item.status === "complete")).toBe(true)
  })

  it("shows unresolved work as incomplete on terminal runs and keeps failures", () => {
    const events = [event(0, "task_started", {}, {task_id: "failed"}), event(1, "task_failed", {reason: "failed"}, {task_id: "failed"}), event(2, "tool_call", {name: "tool"}, {tool_call_id: "unfinished"})]
    expect(deriveChatAgentProgress(events, "completed").map(item => item.status)).toEqual(["failed", "warning"])
    expect(deriveChatAgentProgress(events, "cancelled").every(item => item.status !== "active")).toBe(true)
    expect(deriveChatAgentProgress(events, "running")[1].status).toBe("active")
  })
})
