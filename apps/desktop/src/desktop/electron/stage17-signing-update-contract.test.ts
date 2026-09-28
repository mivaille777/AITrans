import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

function read(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), "utf8")
}

describe("Electron Stage 17 signing and update contract", () => {
  it("keeps Windows signing optional for development and secret-driven for release builds", () => {
    const forge = read("../../../forge.config.cjs")
    const gitignore = read("../../../../../.gitignore")

    expect(forge).toContain("AITRANS_WINDOWS_CERTIFICATE_FILE")
    expect(forge).toContain("AITRANS_WINDOWS_CERTIFICATE_PASSWORD")
    expect(forge).toContain("timestampServer")
    expect(forge).toContain("windowsSign")
    expect(gitignore).toContain("*.pfx")
    expect(gitignore).toContain("*.p12")
  })

  it("builds separate stable and beta Squirrel feeds", () => {
    const feed = read("../../../scripts/create-update-feed.mjs")
    const prepare = read("../../../scripts/prepare-update-config.mjs")

    expect(feed).toContain('"stable", "beta"')
    expect(feed).toContain('"win32", "x64"')
    expect(feed).toContain("RELEASES")
    expect(feed).toContain("full\\.nupkg")
    expect(prepare).toContain("AITRANS_UPDATE_BASE_URL")
    expect(prepare).toContain("AITRANS_ENABLE_AUTO_UPDATE")
    expect(prepare).toContain("Production auto-update base URL must use HTTPS")
  })

  it("only starts autoUpdater for packaged Squirrel installs with explicit enabled configuration", () => {
    const updater = read("../../../electron/main/services/update-manager.cts")
    const main = read("../../../electron/main/index.cts")

    expect(updater).toContain("app.isPackaged")
    expect(updater).toContain('"Update.exe"')
    expect(updater).toContain("config.enabled")
    expect(updater).toContain("https:")
    expect(updater).toContain("autoUpdater.setFeedURL")
    expect(updater).toContain("autoUpdater.checkForUpdates")
    expect(main).toContain("updateManager.start()")
  })

  it("delays first-run update checks and never forces an immediate restart after download", () => {
    const updater = read("../../../electron/main/services/update-manager.cts")

    expect(updater).toContain("--squirrel-firstrun")
    expect(updater).toContain("15_000")
    expect(updater).toContain("update-downloaded")
    expect(updater).toContain("It will apply on restart.")
    expect(updater).not.toContain("quitAndInstall")
  })

  it("verifies Authenticode signatures when production signing is required", () => {
    const signing = read("../../../scripts/verify-windows-signing.mjs")
    const packageJson = JSON.parse(read("../../../package.json"))

    expect(signing).toContain("Get-AuthenticodeSignature")
    expect(signing).toContain("AITRANS_REQUIRE_WINDOWS_SIGNING")
    expect(signing).toContain('status === "Valid"')
    expect(packageJson.scripts["release:verify-signing"]).toContain("verify-windows-signing.mjs")
    expect(packageJson.scripts["desktop:release-candidate"]).toContain("release:update-feed")
  })
})
