import type { KnowledgeAccessPolicy, KnowledgeScopeStrategy } from "../../../api/agent"

export type { KnowledgeAccessPolicy, KnowledgeScopeStrategy } from "../../../api/agent"

export interface KnowledgeAccessDecision {
  mode: KnowledgeAccessPolicy
  should_retrieve: boolean
  reason_code: string
  scope_strategy: KnowledgeScopeStrategy
  confidence: number | null
  query: string
}

export const defaultKnowledgeAccessPolicy: KnowledgeAccessPolicy = "auto"

export function normalizeKnowledgeAccessPolicy(value: unknown): KnowledgeAccessPolicy {
  if (value === "always" || value === "never" || value === "auto") return value
  return defaultKnowledgeAccessPolicy
}

export function serializeKnowledgeAccessPolicy(value: unknown): KnowledgeAccessPolicy {
  return normalizeKnowledgeAccessPolicy(value)
}
