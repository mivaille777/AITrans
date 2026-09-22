import type {
  AgentActivityItem,
  AgentWorkspacePhase,
} from "../state/agent-workspace-state"

export type AgentDecisionKind =
  | "confirmation"
  | "retry"
  | "fallback"
  | "cancelling"
  | "cancelled"
  | "failure"

export type AgentDecisionTone = "info" | "warning" | "danger"

export interface AgentDecisionNotice {
  kind: AgentDecisionKind
  tone: AgentDecisionTone
  title: string
  detail: string
  toolName: string
  requiresConfirmation: boolean
}

export function deriveAgentDecision({
  phase,
  confirmationTool,
  errorMessage,
  fallbackReason,
  activities,
}: {
  phase: AgentWorkspacePhase
  confirmationTool: string
  errorMessage: string
  fallbackReason: string
  activities: AgentActivityItem[]
}): AgentDecisionNotice | null {
  if (phase === "confirmation_required" && confirmationTool) {
    return {
      kind: "confirmation",
      tone: "warning",
      title: "Approval required before write action",
      detail: `The Agent requested ${confirmationTool}. No persistent change has been executed yet.`,
      toolName: confirmationTool,
      requiresConfirmation: true,
    }
  }

  if (fallbackReason) {
    const failureDetail = errorMessage.trim()
    return {
      kind: "fallback",
      tone: "warning",
      title: "Fallback activated",
      detail: failureDetail
        ? `${failureDetail} Runtime fallback: ${fallbackReason}.`
        : `The primary execution path could not continue. Runtime fallback: ${fallbackReason}.`,
      toolName: "",
      requiresConfirmation: false,
    }
  }

  if (phase === "error" || phase === "failed") {
    return {
      kind: "failure",
      tone: "danger",
      title: "Agent task could not complete",
      detail: errorMessage || "The Agent run ended before producing a valid result.",
      toolName: "",
      requiresConfirmation: false,
    }
  }

  if (phase === "cancelling") {
    return {
      kind: "cancelling",
      tone: "info",
      title: "Cancellation requested",
      detail: "The Agent will stop at the next safe runtime checkpoint. In-flight write actions are not force-executed.",
      toolName: "",
      requiresConfirmation: false,
    }
  }

  if (phase === "cancelled") {
    return {
      kind: "cancelled",
      tone: "warning",
      title: "Agent task cancelled",
      detail: errorMessage || "The run stopped at a safe checkpoint.",
      toolName: "",
      requiresConfirmation: false,
    }
  }

  if (phase === "running") {
    const latest = activities.at(-1)
    if (latest?.eventType === "retry") {
      return {
        kind: "retry",
        tone: "warning",
        title: "Retrying bounded tool call",
        detail: latest.detail || "A transient tool failure triggered the registered retry policy.",
        toolName: "",
        requiresConfirmation: false,
      }
    }
  }

  return null
}
