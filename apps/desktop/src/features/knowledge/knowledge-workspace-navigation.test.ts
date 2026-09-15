import { describe, expect, it } from "vitest"

import {
  buildCloseReaderParams,
  buildKnowledgeViewParams,
  buildOpenGraphParams,
  buildOpenLibraryItemParams,
  buildOpenPaperParams,
  resolveKnowledgeView,
} from "./knowledge-workspace-navigation"

describe("knowledge workspace navigation", () => {
  it("resolves the active workspace view from URL state", () => {
    expect(resolveKnowledgeView(new URLSearchParams())).toBe("canvas")
    expect(resolveKnowledgeView(new URLSearchParams("view=graph"))).toBe("graph")
    expect(resolveKnowledgeView(new URLSearchParams("document=doc-1"))).toBe("library")
    expect(resolveKnowledgeView(new URLSearchParams("item=item-1"))).toBe("library")
    expect(resolveKnowledgeView(new URLSearchParams("view=reader&paper=paper-1"))).toBe("reader")
    expect(resolveKnowledgeView(new URLSearchParams("view=reader"))).toBe("canvas")
  })

  it("switches primary views without carrying incompatible selection state", () => {
    const current = new URLSearchParams("view=reader&paper=paper-1&document=doc-1&item=item-1&focus=focus-1")

    expect(buildKnowledgeViewParams(current, "canvas").toString()).toBe("")
    expect(buildKnowledgeViewParams(current, "library").toString()).toBe("view=library")
    expect(buildKnowledgeViewParams(current, "graph").toString()).toBe("view=graph&focus=focus-1")
  })

  it("builds stable deep links for reader, graph, and library items", () => {
    const current = new URLSearchParams("view=library&document=doc-1&item=item-1&focus=old")

    expect(buildOpenPaperParams(current, "paper-2").toString()).toBe("view=reader&paper=paper-2")
    expect(buildOpenGraphParams(current, "item-2").toString()).toBe("view=graph&focus=item-2")
    expect(buildOpenLibraryItemParams(current, "item-3").toString()).toBe("view=library&item=item-3")
  })

  it("returns from reader to the library while preserving unrelated query state", () => {
    const current = new URLSearchParams("view=reader&paper=paper-1&source=agent")
    expect(buildCloseReaderParams(current).toString()).toBe("view=library&source=agent")
  })
})
