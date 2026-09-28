import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

function read(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), "utf8")
}

describe("Electron desktop window contract", () => {
  it("keeps the titlebar interactive and limits drag regions to non-control areas", () => {
    const css = read("../../components/WindowFrame.css")

    expect(css).toMatch(/\.window-titlebar\s*\{\s*-webkit-app-region:\s*no-drag;/)
    expect(css).toMatch(/\.window-brand\s*\{\s*-webkit-app-region:\s*drag;/)
    expect(css).toMatch(/\.window-drag-space\s*\{\s*-webkit-app-region:\s*drag;/)
    expect(css).toMatch(/\.window-controls\s*\{\s*-webkit-app-region:\s*no-drag;/)
    expect(css).toMatch(/\.window-controls button\s*\{\s*-webkit-app-region:\s*no-drag;/)
    expect(css).toContain("pointer-events:auto")
  })

  it("keeps Electron drag behavior in CSS without legacy runtime attributes", () => {
    const source = read("../../components/WindowFrame.tsx")

    expect(source).toContain('<header className="window-titlebar">')
    expect(source).toContain('<div className="window-brand">')
    expect(source).toContain('<div className="window-drag-space" />')
    expect(source).not.toContain("data-tauri")
  })

  it("keeps the main BrowserWindow on the native Windows window-state path", () => {
    const source = read("../../../electron/main/window-manager.cts")

    expect(source).toContain("frame: false")
    expect(source).toContain("transparent: false")
    expect(source).toContain("minimizable: true")
    expect(source).toContain("maximizable: true")
    expect(source).toContain("closable: true")
    expect(source).toContain("thickFrame: true")
  })

  it("routes all three caption controls through the desktop adapter", () => {
    const source = read("../../components/WindowFrame.tsx")

    expect(source).toContain("desktop.window.minimize()")
    expect(source).toContain("desktop.window.toggleMaximize()")
    expect(source).toContain("desktop.window.close()")
  })
})
