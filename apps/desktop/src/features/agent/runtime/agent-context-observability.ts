import type { AgentKnowledgeContext, AgentTraceEvent } from "../../../api/agent"

export interface KnowledgeContextStageDiagnostics {
  maxChars: number
  usedChars: number
  cardsIncluded: number
  relationsIncluded: number
  cardSummariesCompacted: number
  cardsDropped: number
  relationsDropped: number
  truncated: boolean
}

export interface KnowledgeContextObservability {
  status: "attached" | "runtime_confirmed"
  binding: string
  canvasName: string
  cards: number
  relations: number
  documents: number
  visibility: {
    planner: boolean
    react: boolean
    synthesis: boolean
  }
  synthesis: KnowledgeContextStageDiagnostics | null
  relationTrust: string
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : ""
}

function numeric(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) ? value : 0
}

function boolean(value: unknown): boolean {
  return value === true
}

function stage(value: unknown): KnowledgeContextStageDiagnostics | null {
  const payload = record(value)
  if (Object.keys(payload).length === 0) return null
  return {
    maxChars: numeric(payload.max_chars),
    usedChars: numeric(payload.used_chars),
    cardsIncluded: numeric(payload.cards_included),
    relationsIncluded: numeric(payload.relations_included),
    cardSummariesCompacted: numeric(payload.card_summaries_compacted),
    cardsDropped: numeric(payload.cards_dropped),
    relationsDropped: numeric(payload.relations_dropped),
    truncated: boolean(payload.truncated),
  }
}

export function previewKnowledgeContextObservability(
  context: AgentKnowledgeContext | null,
): KnowledgeContextObservability | null {
  if (!context) return null
  const documents = new Set(
    context.cards.map((card) => card.document_id.trim()).filter(Boolean),
  )
  return {
    status: "attached",
    binding: context.canvas ? "knowledge_canvas" : "knowledge_selection",
    canvasName: context.canvas?.board_name?.trim() || context.canvas?.scope_label?.trim() || "Knowledge selection",
    cards: context.cards.length,
    relations: context.relations.length,
    documents: documents.size,
    visibility: {
      planner: false,
      react: false,
      synthesis: false,
    },
    synthesis: null,
    relationTrust: "organizational_context_not_factual_evidence",
  }
}

export function runtimeKnowledgeContextObservability(
  events: AgentTraceEvent[],
): KnowledgeContextObservability | null {
  const event = [...events].reverse().find((item) => item.event_type === "knowledge_context_ready")
  if (!event) return null

  const payload = record(event.payload)
  const canvas = record(payload.canvas)
  const attached = record(payload.attached)
  const visibility = record(payload.visibility)
  const stages = record(payload.stages)

  return {
    status: "runtime_confirmed",
    binding: text(payload.binding) || "knowledge_context",
    canvasName: text(canvas.board_name) || text(canvas.scope_label) || "Knowledge selection",
    cards: numeric(attached.cards),
    relations: numeric(attached.relations),
    documents: numeric(attached.documents),
    visibility: {
      planner: boolean(visibility.planner),
      react: boolean(visibility.react),
      synthesis: boolean(visibility.synthesis),
    },
    synthesis: stage(stages.synthesis),
    relationTrust: text(payload.relation_trust),
  }
}

export function resolveKnowledgeContextObservability({
  context,
  events,
}: {
  context: AgentKnowledgeContext | null
  events: AgentTraceEvent[]
}): KnowledgeContextObservability | null {
  return runtimeKnowledgeContextObservability(events)
    ?? previewKnowledgeContextObservability(context)
}
