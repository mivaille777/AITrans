import type { AgentRunSnapshot, AgentTraceEvent } from "../../../api/agent"
import { TaskExecutionPanel } from "./TaskExecutionPanel"

/** Compatibility export: the former fixed-role graph now follows the backend TaskPlan. */
export function MultiAgentTracePanel({
  events,
  running,
  snapshot = null,
  onRetry = () => undefined,
}: {
  events: AgentTraceEvent[]
  running: boolean
  snapshot?: AgentRunSnapshot | null
  onRetry?: (taskId: string) => void
}) {
  return <TaskExecutionPanel events={events} snapshot={snapshot} running={running} onRetry={onRetry} />
}

export default MultiAgentTracePanel
