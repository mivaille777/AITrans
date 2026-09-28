import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

function read(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), "utf8")
}

describe("Electron Stage 9 development runtime contract", () => {
  it("provides stable local Electron lifecycle scripts", () => {
    const packageJson = JSON.parse(read("../../../package.json")) as {
      scripts?: Record<string, string>
    }
    const scripts = packageJson.scripts ?? {}

    expect(scripts["electron:dev"]).toBe("node scripts/electron-dev.mjs")
    expect(scripts["electron:check"]).toContain("electron:compile")
    expect(scripts["electron:check"]).toContain("test:electron-contracts")
    expect(scripts["electron:verify"]).toContain("electron:check")
    expect(scripts["electron:preview"]).toContain("electron:build")
    expect(scripts["electron:preview"]).toContain("electron .")
    expect(scripts["electron:package"]).toBeUndefined()
    expect(scripts["electron:make"]).toBeUndefined()
  })

  it("preflights renderer/backend ports and owns child cleanup", () => {
    const source = read("../../../scripts/electron-dev.mjs")

    expect(source).toContain('rendererPort = 5173')
    expect(source).toContain('backendPort = 8766')
    expect(source).toContain("Backend port")
    expect(source).toContain("Renderer port")
    expect(source).toContain("taskkill")
    expect(source).toContain("Promise.race")
    expect(source).toContain("Vite exited while Electron was running")
  })

  it("keeps the branch-specific PowerShell launcher separate from legacy start.ps1", () => {
    const source = read("../../../../../start-electronrebuild.ps1")

    expect(source).toContain('$ExpectedBranch = "electronrebuild"')
    expect(source).toContain("[switch]$Verify")
    expect(source).toContain("[switch]$BackendOnly")
    expect(source).toContain("[switch]$BuiltRuntime")
    expect(source).toContain("npm run electron:dev")
    expect(source).toContain("npm run electron:preview")
    expect(source).toContain("python -m backend")
  })
})
