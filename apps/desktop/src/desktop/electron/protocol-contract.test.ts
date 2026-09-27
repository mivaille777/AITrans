import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

function read(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), "utf8")
}

describe("Electron production protocol contract", () => {
  it("registers a standard secure renderer scheme without bypassing CSP", () => {
    const source = read("../../../electron/main/app-protocol.cts")

    expect(source).toContain('APP_SCHEME = "aitrans"')
    expect(source).toContain('APP_HOST = "app"')
    expect(source).toContain("standard: true")
    expect(source).toContain("secure: true")
    expect(source).toContain("corsEnabled: true")
    expect(source).not.toContain("bypassCSP: true")
  })

  it("guards renderer assets against path traversal", () => {
    const source = read("../../../electron/main/app-protocol.cts")

    expect(source).toContain('relative.startsWith("..")')
    expect(source).toContain("path.isAbsolute(relative)")
  })

  it("keeps the Electron origin explicitly allowed by FastAPI", () => {
    const source = read("../../../../../backend/main.py")

    expect(source).toContain('"aitrans://app"')
  })
})
