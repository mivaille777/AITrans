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
})
