import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

function read(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), "utf8")
}

describe("Electron desktop window contract", () => {
  it("marks only the titlebar as draggable and keeps controls interactive", () => {
    const css = read("../../components/WindowFrame.css")

    expect(css).toMatch(/\.window-titlebar\s*\{\s*-webkit-app-region:\s*drag;/)
    expect(css).toMatch(/\.window-controls\s*\{\s*-webkit-app-region:\s*no-drag;/)
    expect(css).toMatch(/\.window-controls button\s*\{\s*-webkit-app-region:\s*no-drag;/)
  })

  it("keeps the Tauri drag-region attributes during the dual-runtime phase", () => {
    const source = read("../../components/WindowFrame.tsx")

    expect(source).toContain("data-tauri-drag-region")
  })
})
