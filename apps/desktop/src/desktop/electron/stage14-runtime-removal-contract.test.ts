import { existsSync, readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

function pathOf(relativePath: string): string {
  return fileURLToPath(new URL(relativePath, import.meta.url))
}

function read(relativePath: string): string {
  return readFileSync(pathOf(relativePath), "utf8")
}

describe("Electron Stage 14 legacy runtime removal", () => {
  it("removes legacy runtime directories and npm dependencies", () => {
    expect(existsSync(pathOf("../../../src-tauri"))).toBe(false)
    expect(existsSync(pathOf("../tauri"))).toBe(false)
    const packageJson = JSON.parse(read("../../../package.json"))
    const lock = read("../../../package-lock.json").toLowerCase()
    expect(JSON.stringify(packageJson).toLowerCase()).not.toContain("tauri")
    expect(lock).not.toContain("@tauri-apps")
  })

  it("keeps runtime selection Electron-or-browser only", () => {
    const adapter = read("../adapter.ts")
    const index = read("../index.ts")
    const frame = read("../../components/WindowFrame.tsx")
    expect(adapter).toContain('DesktopRuntime = "browser" | "electron"')
    expect(index).not.toContain("TAURI")
    expect(index).not.toContain("./tauri/")
    expect(frame).not.toContain("data-tauri")
  })

  it("removes legacy backend and CI hooks", () => {
    const backend = read("../../../../../backend/main.py").toLowerCase()
    const ci = read("../../../../../.github/workflows/ci.yml").toLowerCase()
    expect(backend).not.toContain("tauri://")
    expect(backend).not.toContain("tauri.localhost")
    expect(ci).not.toContain("tauri_shell")
    expect(ci).not.toContain("src-tauri")
  })

  it("keeps all active launcher and verification paths Electron-only", () => {
    for (const file of [
      "../../../../../start.ps1",
      "../../../../../start-electron.ps1",
      "../../../../../start-electronrebuild.ps1",
      "../../../../../scripts/start.ps1",
      "../../../../../scripts/verify.ps1",
      "../../../../../scripts/verify_and_start.ps1",
      "../../../../../scripts/build_windows.ps1",
      "../../../README.md",
    ]) {
      expect(read(file).toLowerCase()).not.toContain("tauri")
    }
    expect(existsSync(pathOf("../../../../../docs/archive/legacy/start-tauri.ps1"))).toBe(true)
  })

  it("records owner-authorized removal without falsifying manual parity", () => {
    const parity = JSON.parse(read("../../../../../docs/electron-migration/stage12-parity.json"))
    expect(parity.stage14.status).toBe("runtime_removed")
    expect(parity.stage14.electron_only).toBe(true)
    expect(parity.stage14.removal_authorized_by_owner).toBe(true)
    expect(parity.stage14.manual_parity_complete).toBe(false)
  })
})
