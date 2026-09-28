import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

function read(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), "utf8")
}

describe("overlay clear material contract", () => {
  it("keeps the runtime-agnostic overlay theme bridge on DesktopAdapter", () => {
    const source = read("./overlay-native-theme.ts")

    expect(source).toContain("desktop.overlay.setVisualTheme(theme)")
    expect(source).not.toContain("ipcRenderer")
    expect(source).not.toContain("BrowserWindow")
  })

  it("keeps the Electron overlay transparent without an opaque native backdrop", () => {
    const source = read("../../electron/main/overlay-manager.cts")

    expect(source).toContain("transparent: true")
    expect(source).toContain('backgroundColor: "#00000000"')
    expect(source).toContain("hasShadow: false")
    expect(source).toContain("frame: false")
  })

  it("supports click-through through the bounded Electron overlay manager API", () => {
    const source = read("../../electron/main/overlay-manager.cts")

    expect(source).toContain("setIgnoreMouseEvents(true, { forward: true })")
    expect(source).toContain("setIgnoreMouseEvents(false)")
  })
})
