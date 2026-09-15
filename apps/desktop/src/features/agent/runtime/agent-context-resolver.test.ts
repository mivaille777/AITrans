import { describe, expect, it } from "vitest"

import {
  inferAgentContextMode,
  resolveAgentContext,
} from "./agent-context-resolver"

const readingContext = {
  resource_url: "https://example.com/paper",
  resource_title: "Current Paper",
  section_heading: "Methods",
  context_before: "before",
  context_after: "after",
  source_kind: "browser_dom",
}

const knowledgeHandoffContext = {
  resource_url: "knowledge-item://canvas-selection-board-1",
  resource_title: "test1 · Canvas",
  section_heading: "Knowledge card · concept",
  context_before: "",
  context_after: "",
  source_kind: "knowledge_document",
}

describe("Agent context resolver", () => {
  it("keeps a general prompt general even when stale reading context exists", () => {
    expect(inferAgentContextMode({
      userMessage: "你好，请介绍一下你自己，以及你可以帮助我完成什么任务？",
      hasReadingContext: true,
      hasKnowledgeScope: true,
    })).toBe("general")
  })

  it("prioritizes an explicit knowledge task over an embedded translation operation", () => {
    expect(inferAgentContextMode({
      userMessage: "请帮我分析当前知识库中的论文，提取研究主题，并总结主要贡献，同时翻译摘要部分。",
      hasReadingContext: true,
      hasKnowledgeScope: true,
    })).toBe("knowledge")
  })

  it("recognizes an explicit current-reading request", () => {
    expect(inferAgentContextMode({
      userMessage: "请解释当前选中的这段内容",
      hasReadingContext: true,
    })).toBe("reading")
  })

  it("keeps a Paper Reader evidence question reading-grounded even when the paper is in Knowledge scope", () => {
    expect(inferAgentContextMode({
      userMessage: "Explain why this evidence is important to the paper's main argument.",
      hasReadingContext: true,
      hasKnowledgeScope: true,
      hasResearchWorkspace: true,
    })).toBe("reading")
  })

  it("detaches knowledge requests from ambient reading content", () => {
    const resolved = resolveAgentContext({
      mode: "knowledge",
      readingText: "stale selected image text",
      readingContext,
      fallbackText: "stale fallback",
    })

    expect(resolved.mode).toBe("knowledge")
    expect(resolved.sourceText).toBe("")
    expect(resolved.context.resource_title).toBe("")
    expect(resolved.context.section_heading).toBe("")
  })

  it("preserves explicit reading context for reading tasks", () => {
    const resolved = resolveAgentContext({
      mode: "reading",
      readingText: "Selected paper passage",
      readingContext,
    })

    expect(resolved.sourceText).toBe("Selected paper passage")
    expect(resolved.context).toEqual(readingContext)
  })

  it("preserves an explicit Canvas handoff even when the prompt is inferred as general", () => {
    const canvasContext = [
      "Canvas: test1",
      "Knowledge cards:",
      "[K1] Insight A",
      "Canvas relationship context:",
      "Canonical relations:",
      "[R1] Insight A --supports--> Evidence B | origin=manual; label=manual test edge",
    ].join("\n")

    const resolved = resolveAgentContext({
      mode: "general",
      readingText: canvasContext,
      readingContext: knowledgeHandoffContext,
      fallbackText: "",
    })

    expect(resolved.mode).toBe("general")
    expect(resolved.sourceText).toContain("[R1] Insight A --supports--> Evidence B")
    expect(resolved.context).toEqual(knowledgeHandoffContext)
  })

  it("preserves an explicit Canvas handoff for a knowledge-mode follow-up too", () => {
    const resolved = resolveAgentContext({
      mode: "knowledge",
      readingText: "[R1] A --related_to--> B | origin=manual",
      readingContext: knowledgeHandoffContext,
    })

    expect(resolved.sourceText).toContain("[R1]")
    expect(resolved.context.source_kind).toBe("knowledge_document")
  })
})
