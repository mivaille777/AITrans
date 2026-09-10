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
  fallbackText?: string
}

export interface AgentContextModeInput {
  userMessage: string
  hasReadingContext?: boolean
  hasKnowledgeScope?: boolean
  hasResearchWorkspace?: boolean
}

const emptyContext: ReadingContextFields = {
  resource_url: "",
  resource_title: "",
  section_heading: "",
  context_before: "",
  context_after: "",
  source_kind: "desktop",
}

const KNOWLEDGE_PATTERNS = [
  /知识库/u,
  /知识文档/u,
  /knowledge\s*(base|library)/i,
  /indexed\s+documents?/i,
]

const RESEARCH_PATTERNS = [
  /研究项目/u,
  /研究笔记/u,
  /证据账本/u,
  /research\s+projects?/i,
  /research\s+notes?/i,
  /evidence\s+ledger/i,
]

const READING_PATTERNS = [
  /当前(?:选中|选区|段落|章节|文章|论文|文档)/u,
  /选中(?:内容|文本|段落|章节)/u,
  /这(?:一?段|一?节|一?章|篇论文|篇文章|个文档)/u,
  /\bcurrent\s+(?:selection|passage|section|paper|document)\b/i,
  /\bselected\s+(?:text|passage|section)\b/i,
  /\bthis\s+(?:passage|section|paper|document)\b/i,
]

const TRANSLATION_PATTERNS = [
  /翻译/u,
  /译成/u,
  /译为/u,
  /\btranslat(?:e|ion|ing)\b/i,
]

function matchesAny(text: string, patterns: RegExp[]): boolean {
  return patterns.some((pattern) => pattern.test(text))
}

export function inferAgentContextMode({
  userMessage,
  hasReadingContext = false,
  hasKnowledgeScope = false,
  hasResearchWorkspace = false,
}: AgentContextModeInput): AgentContextMode {
  const message = userMessage.trim()
  if (!message) return "general"

  // Explicit corpus/project references outrank embedded operations such as
  // "translate the abstract" so a compound knowledge task cannot inherit an
  // unrelated reading selection merely because translation is one subtask.
  if (matchesAny(message, KNOWLEDGE_PATTERNS)) return "knowledge"
  if (matchesAny(message, RESEARCH_PATTERNS)) return "research"

  if (matchesAny(message, READING_PATTERNS) && hasReadingContext) {
    return matchesAny(message, TRANSLATION_PATTERNS) ? "translation" : "reading"
  }

  if (matchesAny(message, TRANSLATION_PATTERNS) && hasReadingContext) {
    return "translation"
  }

  if (hasResearchWorkspace && /(?:项目|project|evidence|证据|笔记|notes?)/iu.test(message)) {
    return "research"
  }

  if (hasKnowledgeScope && /(?:论文|文献|documents?|papers?|corpus|资料)/iu.test(message)) {
    return "knowledge"
  }

  return "general"
}

export function resolveAgentContext(input: AgentContextResolverInput): AgentResolvedContext {
  // General, Knowledge and Research requests are intentionally detached from
  // the ambient Reading selection. Their evidence arrives through conversation
  // history, trusted research scope and retrieval tools instead.
  if (input.mode === "general" || input.mode === "knowledge" || input.mode === "research") {
    return {
      mode: input.mode,
      sourceText: "",
      context: emptyContext,
    }
  }

  const sourceText = (input.readingText || input.fallbackText || "").trim()
  const context = input.readingContext ?? input.browserContext ?? emptyContext

  return {
    mode: input.mode,
    sourceText,
    context,
  }
}
