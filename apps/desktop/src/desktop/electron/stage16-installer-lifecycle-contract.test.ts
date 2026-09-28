import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

function read(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), "utf8")
}

describe("Electron Stage 16 installer lifecycle contract", () => {
  it("handles Squirrel install/update/uninstall events before normal startup", () => {
    const source = read("../../../electron/main/index.cts")

    expect(source).toContain("--squirrel-install")
    expect(source).toContain("--squirrel-updated")
    expect(source).toContain("--squirrel-uninstall")
    expect(source).toContain("--squirrel-obsolete")
    expect(source).toContain('runSquirrelShortcutCommand("--createShortcut")')
    expect(source).toContain('runSquirrelShortcutCommand("--removeShortcut")')
    expect(source).toContain('"Update.exe"')
    expect(source).toContain("spawnSync")
  })

  it("keeps the installer lifecycle test explicit because it mutates the Windows user install", () => {
    const packageJson = JSON.parse(read("../../../package.json"))
    const lifecycle = read("../../../../../scripts/electron-installer-lifecycle.ps1")

    expect(packageJson.scripts["desktop:lifecycle-test"]).toContain("-AcknowledgeInstallMutation")
    expect(lifecycle).toContain("[switch]$AcknowledgeInstallMutation")
    expect(lifecycle).toContain("existing AITrans installation")
    expect(lifecycle).toContain("electron-installer-lifecycle.json")
  })

  it("keeps destructive installer acceptance in an explicit manual workflow", () => {
    const workflow = read("../../../../../.github/workflows/electron-installer-lifecycle.yml")

    expect(workflow).toContain("name: Electron Installer Lifecycle")
    expect(workflow).toContain("workflow_dispatch:")
    expect(workflow).toContain("previous_setup_url:")
    expect(workflow).toContain("desktop:release-candidate")
    expect(workflow).toContain("electron-installer-lifecycle.ps1")
    expect(workflow).toContain("AcknowledgeInstallMutation")
    expect(workflow).toContain("electron-installer-lifecycle.json")
  })

  it("requires user-data retention and backend process cleanup after uninstall", () => {
    const lifecycle = read("../../../../../scripts/electron-installer-lifecycle.ps1")

    expect(lifecycle).toContain("retention-marker")
    expect(lifecycle).toContain("User data marker was removed by uninstall")
    expect(lifecycle).toContain("AITransBackend")
    expect(lifecycle).toContain("Get-InstalledBackendVersion")
    expect(lifecycle).toContain("does not match VERSION")
    expect(lifecycle).toContain("a true upgrade test requires an older installer")
    expect(lifecycle).toContain("--uninstall")
    expect(lifecycle).toContain("--silent")
  })
})
