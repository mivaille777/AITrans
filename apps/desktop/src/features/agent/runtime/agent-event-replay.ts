import type { AgentTraceEvent } from "../../../api/agent"

const terminalTaskEvents = new Set([
  "task_completed",
  "task_partial",
  "task_failed",
  "task_blocked",
  "task_cancelled",
  "task_skipped",
])

export function mergeAgentEvents(
  current: AgentTraceEvent[],
  incoming: AgentTraceEvent[],
  runId = "",
): AgentTraceEvent[] {
  const selectedRun = runId || incoming.find((event) => event.run_id)?.run_id || current.find((event) => event.run_id)?.run_id || ""
  const merged = new Map<number, AgentTraceEvent>()
  for (const event of [...current, ...incoming]) {
    if (selectedRun && event.run_id && event.run_id !== selectedRun) continue
    merged.set(event.sequence, event)
  }
  return [...merged.values()].sort((left, right) => left.sequence - right.sequence)
}

export function latestTaskEvent(events: AgentTraceEvent[], taskId: string): AgentTraceEvent | undefined {
  const taskEvents = events.filter((event) => String(event.payload.task_id ?? "") === taskId)
  const terminal = taskEvents.filter((event) => terminalTaskEvents.has(event.event_type))
  return (terminal.length > 0 ? terminal : taskEvents).at(-1)
}
