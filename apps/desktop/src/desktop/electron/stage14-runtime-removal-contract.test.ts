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
    // Local ignored build leftovers (for example src-tauri/target) may survive
    // a branch migration. Guard the actual legacy runtime entrypoints instead
    // of treating any leftover directory as active product code.
    expect(existsSync(pathOf("../../../src-tauri/tauri.conf.json"))).toBe(false)
    expect(existsSync(pathOf("../../../src-tauri/src/main.rs"))).toBe(false)
    expect(existsSync(pathOf("../tauri/tauri-adapter.ts"))).toBe(false)
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
      "../../../../../scripts/verify.ps1",
      "../../../README.md",
    ]) {
      expect(read(file).toLowerCase()).not.toContain("tauri")
    }
    for (const obsolete of [
      "../../../../../start-electron.ps1",
      "../../../../../start-electronrebuild.ps1",
      "../../../../../scripts/start.ps1",
      "../../../../../docs/archive/legacy/start-tauri.ps1",
      "../../../../../docs/archive/legacy/scripts-start-tauri.ps1",
      "../../../../../docs/archive/legacy/verify-and-start-tauri.ps1",
      "../../../../../docs/archive/legacy/webrebuild-dev.ps1",
    ]) {
      expect(existsSync(pathOf(obsolete))).toBe(false)
    }
  })

  it("records owner-authorized removal without falsifying manual parity", () => {
    const parity = JSON.parse(read("../../../../../docs/electron-migration/stage12-parity.json"))
    expect(parity.stage14.status).toBe("runtime_removed")
    expect(parity.stage14.electron_only).toBe(true)
    expect(parity.stage14.removal_authorized_by_owner).toBe(true)
    expect(parity.stage14.manual_parity_complete).toBe(false)
  })
})
