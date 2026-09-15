import { describe, expect, it } from "vitest"

import { companionLayoutClassNames } from "./companion-layout"

describe("AI Chat nested scroll layout", () => {
  it("keeps the workspace bounded to the available route height", () => {
    expect(companionLayoutClassNames.shell).toContain("h-full")
    expect(companionLayoutClassNames.shell).toContain("min-h-0")
    expect(companionLayoutClassNames.shell).toContain("xl:overflow-hidden")
  })

  it("uses a two-column intermediate desktop layout before the full inspector layout", () => {
    expect(companionLayoutClassNames.shell).toContain("min-[960px]:grid-cols-[200px_minmax(0,1fr)]")
    expect(companionLayoutClassNames.shell).toContain("xl:grid-cols-[220px_minmax(0,1fr)_280px]")
    expect(companionLayoutClassNames.contextPanel).toContain("min-[960px]:col-span-2")
  })

  it("gives history, context, and messages their own scroll ownership", () => {
    expect(companionLayoutClassNames.historyPanel).toContain("min-h-0")
    expect(companionLayoutClassNames.historyScroller).toContain("flex-1")
    expect(companionLayoutClassNames.historyScroller).toContain("overflow-y-auto")
    expect(companionLayoutClassNames.contextPanel).toContain("overflow-y-auto")
    expect(companionLayoutClassNames.messageScroller).toContain("overflow-y-scroll")
    expect(companionLayoutClassNames.messageScroller).toContain("overscroll-contain")
  })

  it("keeps the composer in a dedicated chat grid row", () => {
    expect(companionLayoutClassNames.chatColumn).toContain("grid-rows-[minmax(0,1fr)_auto]")
    expect(companionLayoutClassNames.composer).toContain("shrink-0")
    expect(companionLayoutClassNames.composer).toContain("sticky")
    expect(companionLayoutClassNames.composer).toContain("xl:static")
  })
})
