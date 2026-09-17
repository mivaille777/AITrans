import type { AgentRunRequest } from "../../../api/agent"
import type { AgentStreamAcceptedEvent } from "../../../api/agent-stream"

export const AGENT_PENDING_RUN_STORAGE_KEY = "aitrans.agent.pending-run.v1"
export const AGENT_PENDING_RUN_MAX_AGE_MS = 24 * 60 * 60 * 1000

export interface PendingAgentRun {
  runId: string
  traceId: string
  sessionId: string
  requestId: number
  acceptedAt: number
}

function normalizedPendingRun(value: unknown): PendingAgentRun | null {
  if (!value || typeof value !== "object") return null
  const candidate = value as Partial<PendingAgentRun>
  const runId = String(candidate.runId ?? "").trim()
  const traceId = String(candidate.traceId ?? "").trim()
  const sessionId = String(candidate.sessionId ?? "").trim()
  const requestId = Number(candidate.requestId)
  const acceptedAt = Number(candidate.acceptedAt)
  if (
    !runId
    || !traceId
    || !sessionId
    || !Number.isSafeInteger(requestId)
    || requestId < 0
    || !Number.isFinite(acceptedAt)
    || acceptedAt <= 0
  ) {
    return null
  }
  return { runId, traceId, sessionId, requestId, acceptedAt }
}

export function rememberPendingAgentRun(
  event: AgentStreamAcceptedEvent,
  acceptedAt = Date.now(),
  temporary = false,
): PendingAgentRun | null {
  if (temporary || typeof window === "undefined") return null
  const pending = normalizedPendingRun({
    runId: event.run_id,
    traceId: event.trace_id,
    sessionId: event.session_id,
    requestId: event.request_id,
    acceptedAt,
  })
  if (!pending) return null
  try {
    window.localStorage.setItem(AGENT_PENDING_RUN_STORAGE_KEY, JSON.stringify(pending))
    return pending
  } catch {
    return null
  }
}

export function readPendingAgentRun(now = Date.now()): PendingAgentRun | null {
  if (typeof window === "undefined") return null
  try {
    const raw = window.localStorage.getItem(AGENT_PENDING_RUN_STORAGE_KEY)
    const pending = normalizedPendingRun(raw ? JSON.parse(raw) : null)
    if (
      !pending
      || pending.acceptedAt > now
      || now - pending.acceptedAt > AGENT_PENDING_RUN_MAX_AGE_MS
    ) {
      window.localStorage.removeItem(AGENT_PENDING_RUN_STORAGE_KEY)
      return null
    }
    return pending
  } catch {
    window.localStorage.removeItem(AGENT_PENDING_RUN_STORAGE_KEY)
    return null
  }
}

export function clearPendingAgentRun(runId = ""): void {
  if (typeof window === "undefined") return
  if (runId) {
    const current = readPendingAgentRun()
    if (current && current.runId !== runId) return
  }
  window.localStorage.removeItem(AGENT_PENDING_RUN_STORAGE_KEY)
}

export function buildAgentResumeRequest(
  pending: PendingAgentRun,
  targetLanguage: string,
): AgentRunRequest {
  return {
    session_id: pending.sessionId,
    trace_id: pending.traceId,
    resume_run_id: pending.runId,
    request_id: pending.requestId,
    user_message: "Resume interrupted Agent run.",
    source_text: "",
    translated_text: "",
    source_language: "auto",
    target_language: targetLanguage || "zh-CN",
    resource_url: "",
    resource_title: "",
    section_heading: "",
    context_before: "",
    context_after: "",
    source_kind: "checkpoint_resume",
  }
}
