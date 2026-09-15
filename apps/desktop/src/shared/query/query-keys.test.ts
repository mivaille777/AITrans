import { describe, expect, it } from "vitest"

import { queryKeys, queryPolling } from "./query-keys"

describe("query key registry", () => {
  it("shares the companion handoff key across observers", () => {
    expect(queryKeys.companion.handoff).toEqual(["companion", "handoff"])
  })

  it("separates conversation list/detail caches", () => {
    expect(queryKeys.conversations.list(30)).toEqual(["conversations", "list", 30])
    expect(queryKeys.conversations.detail("abc")).toEqual(["conversations", "detail", "abc"])
  })

  it("separates Research Note and Source caches", () => {
    expect(queryKeys.research.notes(5)).toEqual(["research", "notes", 5])
    expect(queryKeys.research.notes(20)).toEqual(["research", "notes", 20])
    expect(queryKeys.research.source("source-a")).toEqual(["research", "source", "source-a"])
  })

  it("keeps browser selection polling faster than page metadata polling", () => {
    expect(queryPolling.browserSelection).toBeLessThan(queryPolling.browserPage)
  })

  it("uses one shared Knowledge document list key", () => {
    expect(queryKeys.knowledge.documents).toEqual(["knowledge", "documents"])
    expect(queryPolling.knowledgeActiveDocuments).toBeLessThan(queryPolling.knowledgeDocuments)
  })
})
