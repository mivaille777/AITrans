import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

function read(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), "utf8")
}

describe("Electron Stage 15 release readiness contract", () => {
  it("uses VERSION as the release version authority", () => {
    const version = read("../../../../../VERSION").trim()
    const packageJson = JSON.parse(read("../../../package.json"))
    const pyproject = read("../../../../../pyproject.toml")
    const backend = read("../../../../../backend/main.py")

    expect(version).toMatch(/^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/)
    expect(packageJson.version).toBe(version)
    expect(pyproject).toContain(`version = "${version}"`)
    expect(backend).toContain("version=get_app_version()")

    const forge = read("../../../forge.config.cjs")
    expect(forge).toContain('path.join(repoRoot, "VERSION")')
    expect(forge).toContain("appVersion: releaseVersion")
    expect(forge).toContain("buildVersion: releaseVersion")
  })

  it("bundles VERSION into the frozen backend and sidecar manifest", () => {
    const spec = read("../../../../../aitrans_backend.spec")
    const builder = read("../../../scripts/build-backend-sidecar.mjs")
    const sidecar = read("../../../../../backend/sidecar.py")

    expect(spec).toContain('project_root / "VERSION"')
    expect(builder).toContain("version: appVersion")
    expect(sidecar).toContain('"version": get_app_version()')
  })

  it("defines a release gate before packaging", () => {
    const packageJson = JSON.parse(read("../../../package.json"))

    expect(packageJson.scripts["security:audit:runtime"]).toBe("npm audit --omit=dev --audit-level=high")
    expect(packageJson.scripts["security:audit:all"]).toBe("npm audit")
    expect(packageJson.scripts["deps:repair"]).toContain("npm cache verify")
    expect(packageJson.scripts["deps:repair"]).toContain("npm ci --prefer-online")
    expect(packageJson.scripts["release:static"]).toBe("node scripts/release-readiness.mjs")
    expect(packageJson.scripts["desktop:release-check"]).toContain("security:audit:runtime")
    expect(packageJson.scripts["desktop:release-check"]).toContain("release:static")
    expect(packageJson.scripts["desktop:release-check"]).toContain("desktop:regression")
    expect(packageJson.scripts["desktop:release-check"]).toContain("desktop:build")
    expect(packageJson.scripts["desktop:release-package"]).toContain("desktop:release-check")
    expect(packageJson.scripts["desktop:release-package"]).toContain("desktop:package")
    expect(packageJson.scripts["release:manifest"]).toBe("node scripts/create-release-manifest.mjs")
    expect(packageJson.scripts["desktop:release-candidate"]).toContain("desktop:make")
    expect(packageJson.scripts["desktop:release-candidate"]).toContain("release:manifest")
  })

  it("creates an integrity manifest for Windows release artifacts", () => {
    const manifestScript = read("../../../scripts/create-release-manifest.mjs")
    expect(manifestScript).toContain("sha256")
    expect(manifestScript).toContain("Setup.exe")
    expect(manifestScript).toContain("full\\.nupkg")
    expect(manifestScript).toContain("release-manifest.json")
  })

  it("keeps release readiness explicit and non-publishing", () => {
    const workflow = read("../../../../../.github/workflows/electron-release-readiness.yml")
    expect(workflow).toContain("name: Electron Release Readiness")
    expect(workflow).toContain("tags:")
    expect(workflow).toContain('"v*"')
    expect(workflow).toContain("Verify tag matches VERSION")
    expect(workflow).toContain("npm run desktop:release-candidate")
    expect(workflow).toContain("release-manifest.json")
    expect(workflow).not.toContain("gh release create")
    expect(workflow).not.toContain("softprops/action-gh-release")
  })

  it("prevents active legacy runtime references from returning", () => {
    const releaseScript = read("../../../scripts/release-readiness.mjs")
    expect(releaseScript).toContain("legacy runtime references remain in active files")
    expect(releaseScript).toContain("activeRoots")
    expect(releaseScript).toContain("isContractOrTest")
  })
})
