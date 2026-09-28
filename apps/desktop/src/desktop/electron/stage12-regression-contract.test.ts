import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

function read(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), "utf8")
}

describe("Electron Stage 12 full regression contract", () => {
  it("provides a deterministic cross-stack regression command", () => {
    const packageJson = JSON.parse(read("../../../package.json"))
    expect(packageJson.scripts["electron:regression"]).toBe("node scripts/electron-regression.mjs")
  })

  it("covers Electron, frontend, backend, Agent, RAG, workspace and sandbox boundaries", () => {
    const source = read("../../../scripts/electron-regression.mjs")
    expect(source).toContain('"electron:check"')
    expect(source).toContain('"frontend-regression"')
    expect(source).toContain('"frontend-build"')
    expect(source).toContain("npm_execpath")
    expect(source).toContain("process.execPath")
    expect(source).toContain("tests/test_backend_health.py")
    expect(source).toContain("test_llm_settings_api.py")
    expect(source).toContain("test_workspace_apply_api.py")
    expect(source).toContain("test_sandbox_approvals_api.py")
    expect(source).toContain("test_agent_api_runtime.py")
    expect(source).toContain("test_python_execute_agent_integration.py")
    expect(source).toContain("test_offline_runtime.py")
    expect(source).toContain("test_model_manager.py")
    expect(source).toContain("test_filesystem_workspace_service.py")
    expect(source).toContain("test_sandbox_debug_service.py")
  })

  it("keeps packaged Electron-to-sidecar lifecycle verification in the package gate", () => {
    const verifier = read("../../../scripts/verify-electron-package.mjs")
    const main = read("../../../electron/main/index.cts")
    expect(verifier).toContain("--electron-runtime-smoke-test")
    expect(main).toContain("AITrans packaged Electron runtime smoke test passed.")
  })

  it("writes a machine-readable report without claiming GUI or packaged runtime acceptance", () => {
    const source = read("../../../scripts/electron-regression.mjs")
    expect(source).toContain("electron-regression.json")
    expect(source).toContain("packaged_runtime: false")
    expect(source).toContain("gui_manual_acceptance: false")
    expect(source).toContain("Failed Electron regression steps")
  })
})
