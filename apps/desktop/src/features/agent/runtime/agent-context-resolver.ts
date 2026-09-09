import type { ReadingContextFields } from "../../../api/types"
import type { AgentContextMode } from "./agent-context-mode"

export interface AgentResolvedContext {
  mode: AgentContextMode
  sourceText: string
  context: ReadingContextFields
}

export interface AgentContextResolverInput {
  mode: AgentContextMode
  readingText?: string
  readingContext?: ReadingContextFields | null
  browserContext?: ReadingContextFields | null
  knowledgeText?: string
  knowledgeContext?: ReadingContextFields | null
  fallbackText?: string
}

const emptyContext: ReadingContextFields = {
  resource_url: "",
  resource_title: "",
  section_heading: "",
  context_before: "",
  context_after: "",
  source_kind: "desktop",
}

export function resolveAgentContext(input: AgentContextResolverInput): AgentResolvedContext {
  if (input.mode === "knowledge" && input.knowledgeText) {
    return {
      mode: input.mode,
      sourceText: input.knowledgeText.trim(),
      context: input.knowledgeContext ?? emptyContext,
    }
  }

  if (input.mode === "reading" && input.readingText) {
    return {
      mode: input.mode,
      sourceText: input.readingText.trim(),
      context: input.readingContext ?? emptyContext,
    }
  }

  if (input.mode === "research" && input.knowledgeText) {
    return {
      mode: input.mode,
      sourceText: input.knowledgeText.trim(),
      context: input.knowledgeContext ?? emptyContext,
    }
  }

  if (input.browserContext && input.fallbackText) {
    return {
      mode: input.mode,
      sourceText: input.fallbackText.trim(),
      context: input.browserContext,
    }
  }

  return {
    mode: input.mode,
    sourceText: input.fallbackText?.trim() ?? "",
    context: input.readingContext ?? input.browserContext ?? emptyContext,
  }
}
