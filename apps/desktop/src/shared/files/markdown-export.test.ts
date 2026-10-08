// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest"
import { downloadMarkdown } from "./markdown-export"

afterEach(() => {
  vi.useRealTimers()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe("Markdown download", () => {
  it("downloads a UTF-8 document using its filename and releases the object URL", () => {
    vi.useFakeTimers()
    const createObjectURL = vi.fn((_blob: Blob) => "blob:markdown-test")
    const revokeObjectURL = vi.fn()
    vi.stubGlobal("URL", {createObjectURL, revokeObjectURL})
    let filename = ""
    const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (this: HTMLAnchorElement) {
      filename = this.download
      expect(this.href).toBe("blob:markdown-test")
      expect(document.body.contains(this)).toBe(true)
    })
    downloadMarkdown({filename:"周报.md", markdown:"# 周报\n\n完成测试。\n", mime_type:"text/markdown;charset=utf-8"})
    expect(click).toHaveBeenCalledOnce()
    expect(filename).toBe("周报.md")
    const blob = createObjectURL.mock.calls[0][0] as unknown as Blob
    expect(blob.size).toBeGreaterThan(20)
    expect(blob.type).toBe("text/markdown;charset=utf-8")
    expect(document.querySelector('a[download="周报.md"]')).toBeNull()
    expect(revokeObjectURL).not.toHaveBeenCalled()
    vi.advanceTimersByTime(1000)
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:markdown-test")
  })
})
