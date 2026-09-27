import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

function read(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), "utf8")
}

describe("Electron backend process contract", () => {
  it("reuses the existing FastAPI module in development", () => {
    const source = read("../../../electron/main/services/backend-process-manager.cts")

    expect(source).toContain('args: ["-m", "backend"]')
    expect(source).toContain('"http://127.0.0.1:8766/health"')
  })

  it("recognizes a healthy pre-existing backend as external", () => {
    const source = read("../../../electron/main/services/backend-process-manager.cts")

    expect(source).toContain('this.state = "external"')
    expect(source).toContain("this.owned = false")
  })

  it("reserves the packaged PyInstaller sidecar path", () => {
    const source = read("../../../electron/main/services/backend-process-manager.cts")

    expect(source).toContain('"AITransBackend.exe"')
    expect(source).toContain("process.resourcesPath")
  })

  it("owns shutdown only for backend processes it spawned", () => {
    const source = read("../../../electron/main/services/backend-process-manager.cts")

    expect(source).toContain("if (!child || !this.owned")
    expect(source).toContain('"taskkill.exe"')
  })
})
