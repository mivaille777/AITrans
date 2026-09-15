import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

function read(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), "utf8")
}

describe("overlay clear material contract", () => {
  it("does not mutate the WebView2 background at runtime", () => {
    const source = read("./overlay-native-theme.ts")

    expect(source).not.toContain("@tauri-apps/api/webview")
    expect(source).not.toContain(".setBackgroundColor(")
  })

  it("keeps the light DOM theme while disabling the opaque system backdrop", () => {
    const source = read("./overlay-native-theme.ts")

    expect(source).toContain('const nativeTheme = "dark"')
    expect(source).toContain('{ theme: nativeTheme }')
    expect(source).toContain('{ theme }')
  })

  it("grants only the native window permissions required to reassert borderless chrome", () => {
    const capability = read("../../src-tauri/capabilities/default.json")

    expect(capability).toContain('"core:window:allow-set-decorations"')
    expect(capability).toContain('"core:window:allow-set-resizable"')
  })
})
