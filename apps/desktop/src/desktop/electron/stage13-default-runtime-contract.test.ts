import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

function read(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), "utf8")
}

describe("Electron Stage 13 default runtime contract", () => {
  it("routes canonical desktop scripts to Electron", () => {
    const packageJson = JSON.parse(read("../../../package.json"))
    const scripts = packageJson.scripts

    expect(scripts["desktop:dev"]).toBe("npm run electron:dev")
    expect(scripts["desktop:check"]).toBe("npm run electron:check")
    expect(scripts["desktop:verify"]).toBe("npm run electron:verify")
    expect(scripts["desktop:regression"]).toBe("npm run electron:regression")
    expect(scripts["desktop:build"]).toBe("npm run electron:build")
    expect(scripts["desktop:package"]).toBe("npm run electron:package")
    expect(scripts["desktop:make"]).toBe("npm run electron:make")
  })

  it("keeps explicit Tauri legacy aliases during fallback period", () => {
    const packageJson = JSON.parse(read("../../../package.json"))
    expect(packageJson.scripts["legacy:tauri:dev"]).toBe("npm run tauri:dev")
    expect(packageJson.scripts["legacy:tauri:build"]).toBe("npm run tauri:build")
  })

  it("provides a branch-neutral canonical Electron launcher while preserving legacy start.ps1", () => {
    const launcher = read("../../../../../start-electron.ps1")
    const legacy = read("../../../../../start.ps1")

    expect(launcher).toContain("AITrans Electron development launcher")
    expect(launcher).not.toContain('$ExpectedBranch = "electronrebuild"')
    expect(launcher).toContain("npm run desktop:dev")
    expect(legacy).toContain('$ExpectedBranch = "WebReBuild"')
    expect(legacy).toContain("npm run tauri:dev")
  })

  it("makes Tauri CI non-blocking while Electron remains a required quality gate", () => {
    const workflow = read("../../../../../.github/workflows/ci.yml")

    expect(workflow).toContain("Tauri shell build (legacy fallback)")
    expect(workflow).toMatch(/tauri_shell:[\s\S]*continue-on-error: true/)
    expect(workflow).toContain("- electron_shell")

    const qualityGate = workflow.slice(workflow.indexOf("  quality_gate:"))
    expect(qualityGate).not.toContain("- tauri_shell")
    expect(qualityGate).not.toContain("needs.tauri_shell.result")
  })

  it("records active Electron cutover without falsifying pending manual parity", () => {
    const parity = JSON.parse(read("../../../../../docs/electron-migration/stage12-parity.json"))

    expect(parity.stage13.status).toBe("cutover_active")
    expect(parity.stage13.default_runtime).toBe("electron")
    expect(parity.stage13.tauri_fallback).toBe("legacy_non_blocking")
    expect(parity.stage13.manual_parity_complete).toBe(false)
    expect(parity.stage13_ready).toBe(false)
  })
})
