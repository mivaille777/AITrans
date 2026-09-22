import type {
  AgentContextMode,
  AgentTraceEvent,
  KnowledgeAccessPolicy,
  KnowledgeScopeStrategy,
} from "../../../api/agent"
import { normalizeKnowledgeAccessPolicy } from "./knowledge-access-policy"

export type AgentKnowledgeRuntimeStatus =
  | "idle"
  | "evaluating"
  | "skipped"
  | "retrieval_required"
  | "retrieved"

export interface AgentKnowledgeState {
  policy: KnowledgeAccessPolicy
  policyLabel: string
  scopeLabel: string
  scopeDisplay: string
  scopeStrategy: KnowledgeScopeStrategy | ""
  status: AgentKnowledgeRuntimeStatus
  statusDetail: string
  reasonCode: string
  documentCount: number
  evidenceCount: number
}

interface DeriveAgentKnowledgeStateInput {
  events: AgentTraceEvent[]
  pending: boolean
  policy?: KnowledgeAccessPolicy
  contextMode?: AgentContextMode
  contextTitle?: string
  contextSection?: string
  documentCount?: number
  researchSourceCount?: number
  workspaceSelected?: boolean
}

const scopeStrategies = new Set<KnowledgeScopeStrategy>([
  "none",
  "attached_document",
  "explicit_documents",
  "research_workspace",
  "global_knowledge",
])

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : ""
}

function count(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? Math.max(0, value) : 0
}

function latestEvent(events: AgentTraceEvent[], eventType: AgentTraceEvent["event_type"]): AgentTraceEvent | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    if (events[index]?.event_type === eventType) return events[index]
  }
  return null
}

function scopeStrategy(value: unknown): KnowledgeScopeStrategy | "" {
  const candidate = text(value) as KnowledgeScopeStrategy
  return scopeStrategies.has(candidate) ? candidate : ""
}

function policyLabel(policy: KnowledgeAccessPolicy): string {
  if (policy === "always") return "Always search"
  if (policy === "never") return "Never search"
  return "Auto"
}

function scopeLabel(
  strategy: KnowledgeScopeStrategy | "",
  documentCount: number,
  researchSourceCount: number,
  workspaceSelected: boolean,
  contextMode: AgentContextMode | undefined,
): string {
  if (strategy === "research_workspace" || workspaceSelected || contextMode === "research") {
    return "Research workspace"
  }
  if (strategy === "global_knowledge") return "All knowledge"
  if (strategy === "explicit_documents" || documentCount > 1) {
    return `${documentCount || researchSourceCount || "Selected"} documents`
  }
  if (strategy === "attached_document" || documentCount === 1 || contextMode === "reading" || contextMode === "translation") {
    return "Current document"
  }
  return "Current workspace"
}

function skipDetail(reasonCode: string): string {
  if (reasonCode === "explicit_never") return "Skipped · Policy disabled"
  if (reasonCode === "current_context_sufficient" || !reasonCode) return "Skipped · Context sufficient"
  if (reasonCode === "knowledge_unavailable") return "Skipped · Knowledge unavailable"
  return `Skipped · ${reasonCode.replaceAll("_", " ")}`
}

export function deriveAgentKnowledgeState({
  events,
  pending,
  policy = "auto",
  contextMode,
  contextTitle,
  contextSection,
  documentCount: inputDocumentCount = 0,
  researchSourceCount: inputResearchSourceCount = 0,
  workspaceSelected = false,
}: DeriveAgentKnowledgeStateInput): AgentKnowledgeState {
  const decisionEvent = latestEvent(events, "knowledge_decision")
  const scopeEvent = latestEvent(events, "knowledge_scope_resolved")
  const skippedEvent = latestEvent(events, "knowledge_skipped")
  const retrievedEvent = latestEvent(events, "knowledge_retrieved")
  const decision = decisionEvent?.payload ?? {}
  const resolvedScope = scopeEvent?.payload ?? {}
  const resolvedPolicy = normalizeKnowledgeAccessPolicy(decision.mode ?? policy)
  const strategy = scopeStrategy(resolvedScope.strategy ?? decision.scope_strategy)
  const documentCount = scopeEvent
    ? count(resolvedScope.document_count)
    : Math.max(0, inputDocumentCount)
  const researchSourceCount = scopeEvent
    ? count(resolvedScope.research_source_count)
    : Math.max(0, inputResearchSourceCount)
  const selectedWorkspace = scopeEvent
    ? resolvedScope.workspace_selected === true
    : workspaceSelected
  const label = scopeLabel(
    strategy,
    documentCount,
    researchSourceCount,
    selectedWorkspace,
    contextMode,
  )
  const detail = text(contextSection) || text(contextTitle) || "Current selection"
  const reasonCode = text(skippedEvent?.payload.reason_code) || text(decision.reason_code)
  const retrieved = Boolean(retrievedEvent)
  const shouldRetrieve = decision.should_retrieve === true
  const status: AgentKnowledgeRuntimeStatus = pending
    ? "evaluating"
    : skippedEvent || decision.should_retrieve === false
      ? "skipped"
      : retrieved
        ? "retrieved"
        : shouldRetrieve
          ? "retrieval_required"
          : "idle"

  const statusDetail = status === "evaluating"
    ? "Evaluating…"
    : status === "skipped"
      ? skipDetail(reasonCode)
      : status === "retrieval_required"
        ? `${label} · Retrieval required`
        : status === "retrieved"
          ? `${label} · Retrieval complete`
          : "Awaiting run"

  return {
    policy: resolvedPolicy,
    policyLabel: policyLabel(resolvedPolicy),
    scopeLabel: label,
    scopeDisplay: `${label} · ${detail}`,
    scopeStrategy: strategy,
    status,
    statusDetail,
    reasonCode,
    documentCount,
    evidenceCount: count(
      retrievedEvent?.payload.evidence_count
      ?? retrievedEvent?.payload.citation_count,
    ),
  }
}
