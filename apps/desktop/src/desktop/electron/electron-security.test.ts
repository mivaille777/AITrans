import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

function read(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), "utf8")
}

describe("Electron security baseline", () => {
  it("keeps the main renderer sandboxed and isolated from Node", () => {
    const source = read("../../../electron/main/window-manager.cts")

    expect(source).toContain("nodeIntegration: false")
    expect(source).toContain("contextIsolation: true")
    expect(source).toContain("sandbox: true")
    expect(source).toContain("webSecurity: true")
  })

  it("exposes a named preload API instead of raw ipcRenderer", () => {
    const source = read("../../../electron/preload/index.cts")

    expect(source).toContain('exposeInMainWorld("aiTransDesktop", api)')
    expect(source).not.toContain("send: ipcRenderer.send")
    expect(source).not.toContain("invoke: ipcRenderer.invoke")
    expect(source).not.toContain("ipcRenderer,")
  })

  it("uses a fixed IPC channel allowlist", () => {
    const source = read("../../../electron/shared/channels.cts")

    expect(source).toContain('"aitrans:window:minimize"')
    expect(source).toContain('"aitrans:window:toggle-maximize"')
    expect(source).toContain('"aitrans:files:pick-agent-workspace"')
    expect(source).toContain('"aitrans:files:open-evidence-source"')
    expect(source).toContain('"aitrans:credentials:save"')
    expect(source).toContain('"aitrans:credentials:delete"')
    expect(source).toContain('"aitrans:overlay:set-position"')
    expect(source).toContain('"aitrans:event:overlay-state-changed"')
    expect(source).not.toContain("aitrans:exec")
    expect(source).not.toContain("aitrans:fs")
    expect(source).not.toContain("aitrans:shell")
  })
})
