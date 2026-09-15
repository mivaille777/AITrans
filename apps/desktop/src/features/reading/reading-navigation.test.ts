import { describe, expect, it } from "vitest"

import {
  buildCloseReadingPaperParams,
  buildOpenReadingPaperParams,
  buildReadingPaperPath,
  resolveReadingPaperId,
} from "./reading-navigation"

describe("reading navigation", () => {
  it("resolves the canonical paper id from Reading URL state", () => {
    expect(resolveReadingPaperId(new URLSearchParams())).toBe("")
    expect(resolveReadingPaperId(new URLSearchParams("paper=paper-1"))).toBe("paper-1")
  })

  it("opens and closes a paper without losing unrelated Reading state", () => {
    const current = new URLSearchParams("source=knowledge")
    expect(buildOpenReadingPaperParams(current, "paper-2").toString()).toBe("source=knowledge&paper=paper-2")
    expect(buildCloseReadingPaperParams(new URLSearchParams("paper=paper-2&source=knowledge")).toString()).toBe("source=knowledge")
  })

  it("builds the canonical cross-workspace Reading deep link", () => {
    expect(buildReadingPaperPath("paper-3")).toBe("/reading?paper=paper-3")
    expect(buildReadingPaperPath(" ")).toBe("/reading")
  })
})
