import { describe, expect, it } from "vitest"

import {
  buildKnowledgeViewParams,
  buildOpenGraphParams,
  buildOpenLibraryItemParams,
  resolveKnowledgeView,
  resolveLegacyKnowledgeReaderPaperId,
} from "./knowledge-workspace-navigation"

describe("knowledge workspace navigation", () => {
  it("keeps Knowledge limited to canvas, graph, and library views", () => {
    expect(resolveKnowledgeView(new URLSearchParams())).toBe("canvas")
    expect(resolveKnowledgeView(new URLSearchParams("view=graph"))).toBe("graph")
    expect(resolveKnowledgeView(new URLSearchParams("document=doc-1"))).toBe("library")
    expect(resolveKnowledgeView(new URLSearchParams("item=item-1"))).toBe("library")
    expect(resolveKnowledgeView(new URLSearchParams("view=reader&paper=paper-1"))).toBe("library")
  })

  it("recognizes legacy Knowledge reader links for compatibility redirect", () => {
    expect(resolveLegacyKnowledgeReaderPaperId(new URLSearchParams("view=reader&paper=paper-1"))).toBe("paper-1")
    expect(resolveLegacyKnowledgeReaderPaperId(new URLSearchParams("view=reader"))).toBe("")
    expect(resolveLegacyKnowledgeReaderPaperId(new URLSearchParams("view=library&paper=paper-1"))).toBe("")
  })

  it("switches primary views without carrying reader or selection state", () => {
    const current = new URLSearchParams("view=reader&paper=paper-1&document=doc-1&item=item-1&focus=focus-1")

    expect(buildKnowledgeViewParams(current, "canvas").toString()).toBe("")
    expect(buildKnowledgeViewParams(current, "library").toString()).toBe("view=library")
    expect(buildKnowledgeViewParams(current, "graph").toString()).toBe("view=graph&focus=focus-1")
  })

  it("builds stable graph and library-item deep links", () => {
    const current = new URLSearchParams("view=library&document=doc-1&item=item-1&focus=old&paper=legacy")

    expect(buildOpenGraphParams(current, "item-2").toString()).toBe("view=graph&focus=item-2")
    expect(buildOpenLibraryItemParams(current, "item-3").toString()).toBe("view=library&item=item-3")
  })
})
