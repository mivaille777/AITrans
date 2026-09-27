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
    expect(source).toContain('APP_ORIGIN + "/index.html"')
    expect(source).toContain("setWindowOpenHandler(() => ({ action: \"deny\" }))")
    expect(source).toContain('webContents.on("will-navigate"')
  })

  it("keeps the overlay renderer sandboxed and isolated from Node", () => {
    const source = read("../../../electron/main/overlay-manager.cts")

    expect(source).toContain("nodeIntegration: false")
    expect(source).toContain("contextIsolation: true")
    expect(source).toContain("sandbox: true")
    expect(source).toContain("webSecurity: true")
    expect(source).toContain('APP_ORIGIN + "/overlay.html"')
    expect(source).toContain("setWindowOpenHandler(() => ({ action: \"deny\" }))")
    expect(source).toContain('webContents.on("will-navigate"')
  })

  it("exposes a named preload API instead of raw ipcRenderer", () => {
    const source = read("../../../electron/preload/index.cts")

    expect(source).toContain('exposeInMainWorld("aiTransDesktop", api)')
    expect(source).not.toContain("send: ipcRenderer.send")
    expect(source).not.toContain("invoke: ipcRenderer.invoke")
    expect(source).not.toContain("ipcRenderer,")
    expect(source).not.toContain("child_process")
    expect(source).not.toContain("node:fs")
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

  it("authorizes privileged IPC senders against known desktop windows", () => {
    const auth = read("../../../electron/main/ipc/ipc-auth.cts")
    const files = read("../../../electron/main/ipc/file-ipc.cts")
    const credentials = read("../../../electron/main/ipc/credential-ipc.cts")
    const overlay = read("../../../electron/main/ipc/overlay-ipc.cts")
    const window = read("../../../electron/main/ipc/window-ipc.cts")

    expect(auth).toContain("event.sender !== mainWindow.webContents")
    expect(auth).toContain("Unauthorized desktop IPC sender.")
    expect(files).toContain("authorizedMainWindow(event, resolveMainWindow)")
    expect(credentials).toContain("authorizedMainWindow(event, resolveMainWindow)")
    expect(overlay).toContain("authorizedDesktopWindow(event, resolveMainWindow, resolveOverlayWindow)")
    expect(window).toContain("authorizedMainWindow(event, resolveMainWindow)")
  })
})
