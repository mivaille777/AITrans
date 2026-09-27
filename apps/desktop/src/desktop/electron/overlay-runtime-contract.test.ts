import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

function read(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), "utf8")
}

describe("Electron overlay runtime contract", () => {
  it("creates a sandboxed hidden always-on-top overlay window", () => {
    const source = read("../../../electron/main/overlay-manager.cts")

    expect(source).toContain("alwaysOnTop: true")
    expect(source).toContain("skipTaskbar: true")
    expect(source).toContain("show: false")
    expect(source).toContain("nodeIntegration: false")
    expect(source).toContain("contextIsolation: true")
    expect(source).toContain("sandbox: true")
  })

  it("reuses the renderer positioning algorithm in the Electron adapter", () => {
    const source = read("./electron-adapter.ts")

    expect(source).toContain('import { computeOverlayPosition } from "../overlay-positioning"')
    expect(source).toContain("computeOverlayPosition({")
    expect(source).toContain("getPlacementContext(reference)")
  })

  it("uses CSS app-region dragging only when overlay dragging is enabled", () => {
    const header = read("../../components/OverlayHeader.tsx")
    const styles = read("../../overlay.css")

    expect(header).toContain("ait-overlay-native-drag")
    expect(header).toContain('desktop.runtime === "electron"')
    expect(styles).toContain("-webkit-app-region: drag")
    expect(styles).toContain("-webkit-app-region: no-drag")
  })
})
