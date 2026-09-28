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

    expect(version).toBe("0.1.0")
    expect(packageJson.version).toBe(version)
    expect(pyproject).toContain(`version = "${version}"`)
    expect(backend).toContain("version=get_app_version()")
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

    expect(packageJson.scripts["release:static"]).toBe("node scripts/release-readiness.mjs")
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
    expect(manifestScript).toContain("full.nupkg")
    expect(manifestScript).toContain("release-manifest.json")
  })

  it("prevents active legacy runtime references from returning", () => {
    const releaseScript = read("../../../scripts/release-readiness.mjs")
    expect(releaseScript).toContain("legacy runtime references remain in active files")
    expect(releaseScript).toContain("activeRoots")
    expect(releaseScript).toContain("isContractOrTest")
  })
})
