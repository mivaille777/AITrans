import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

function read(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), "utf8")
}

describe("Electron Stage 10 packaging contract", () => {
  it("defines package and Windows installer commands", () => {
    const packageJson = JSON.parse(read("../../../package.json"))
    expect(packageJson.productName).toBe("AITrans")
    expect(packageJson.version).toBe("0.1.0")
    expect(packageJson.scripts["backend:package"]).toContain("build-backend-sidecar.mjs")
    expect(packageJson.scripts["electron:package"]).toContain("electron-forge package")
    expect(packageJson.scripts["electron:make"]).toContain("electron-forge make")
    expect(packageJson.devDependencies["@electron-forge/maker-squirrel"]).toBe("7.11.2")
    expect(packageJson.devDependencies["electron-winstaller"]).toBe("5.4.4")
  })

  it("keeps the renderer unpacked and the Python sidecar outside ASAR", () => {
    const forge = read("../../../forge.config.cjs")
    const backend = read("../../../electron/main/services/backend-process-manager.cts")
    expect(forge).toContain('unpackDir: "dist"')
    expect(forge).toContain('"electron-resources", "backend"')
    expect(forge).toContain('"@electron-forge/maker-squirrel"')
    expect(backend).toContain('"AITransBackend.exe"')
  })

  it("builds and smoke-tests a frozen sidecar without model weights", () => {
    const builder = read("../../../scripts/build-backend-sidecar.mjs")
    const verifier = read("../../../scripts/verify-electron-package.mjs")
    expect(builder).toContain("aitrans_backend.spec")
    expect(builder).toContain("--runtime-smoke-test")
    expect(builder).toContain("model.safetensors")
    expect(builder).toContain(".gguf")
    expect(verifier).toContain('"app.asar.unpacked", "dist", "index.html"')
    expect(verifier).toContain("Squirrel.Windows")
  })
})
