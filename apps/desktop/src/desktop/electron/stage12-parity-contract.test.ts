import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

function read(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), "utf8")
}

describe("Electron Stage 12 parity manifest", () => {
  it("does not permit Stage 13 before manual parity acceptance", () => {
    const manifest = JSON.parse(read("../../../../../docs/electron-migration/stage12-parity.json"))
    expect(manifest.rule).toBe("Electron Regression >= Tauri Baseline")
    expect(manifest.stage13_ready).toBe(false)
    expect(manifest.gates.built_runtime_manual.status).toBe("manual_pending")
    expect(manifest.gates.packaged_runtime_manual.status).toBe("manual_pending")
    expect(manifest.gates.dpi_multi_monitor_manual.status).toBe("manual_pending")
  })

  it("tracks all migration-critical product capabilities", () => {
    const manifest = JSON.parse(read("../../../../../docs/electron-migration/stage12-parity.json"))
    const ids = new Set(manifest.capabilities.map((item: { id: string }) => item.id))
    for (const id of ["main_window", "overlay", "credentials", "files_workspace", "backend_lifecycle", "agent", "rag", "sandbox", "production_renderer"]) {
      expect(ids.has(id)).toBe(true)
    }
  })
})
