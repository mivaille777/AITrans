import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

function read(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), "utf8")
}

describe("Electron desktop window contract", () => {
  it("marks only the titlebar as draggable and keeps controls interactive", () => {
    const css = read("../../components/WindowFrame.css")

    expect(css).toContain(".window-titlebar {\n  -webkit-app-region: drag;")
    expect(css).toContain(".window-controls {\n  -webkit-app-region: no-drag;")
    expect(css).toContain(".window-controls button {\n  -webkit-app-region: no-drag;")
  })

  it("keeps the Tauri drag-region attributes during the dual-runtime phase", () => {
    const source = read("../../components/WindowFrame.tsx")

    expect(source).toContain("data-tauri-drag-region")
  })
})
