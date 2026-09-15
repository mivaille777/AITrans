import { describe, expect, it } from "vitest"

import { clampPdfPage } from "./PdfReaderSurface"

describe("PdfReaderSurface", () => {
  it("clamps requested pages to the available PDF range", () => {
    expect(clampPdfPage(0, 12)).toBe(1)
    expect(clampPdfPage(4.6, 12)).toBe(5)
    expect(clampPdfPage(99, 12)).toBe(12)
  })

  it("falls back to page one for invalid page counts or requests", () => {
    expect(clampPdfPage(Number.NaN, 12)).toBe(1)
    expect(clampPdfPage(4, 0)).toBe(1)
  })
})
