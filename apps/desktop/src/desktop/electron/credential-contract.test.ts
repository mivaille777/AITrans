import { readFileSync } from "node:fs"
import { fileURLToPath } from "node:url"
import { describe, expect, it } from "vitest"

function read(relativePath: string): string {
  return readFileSync(fileURLToPath(new URL(relativePath, import.meta.url)), "utf8")
}

describe("Electron credential vault contract", () => {
  it("preserves the credential target namespace used by the Python backend", () => {
    const source = read("../../../electron/main/services/credential-service.cts")

    expect(source).toContain('CREDENTIAL_TARGET_PREFIX = "AITranslator/ai"')
    expect(source).toContain('"openai_compatible"')
  })

  it("keeps secrets out of process arguments", () => {
    const source = read("../../../electron/main/services/credential-service.cts")

    expect(source).toContain('child.stdin.end(JSON.stringify(request))')
    expect(source).not.toContain("cmdkey")
    expect(source).not.toContain("/pass:")
  })

  it("does not expose a generic credential or process primitive to the renderer", () => {
    const preload = read("../../../electron/preload/index.cts")

    expect(preload).toContain("IPC_CHANNELS.credentialsSave")
    expect(preload).toContain("IPC_CHANNELS.credentialsDelete")
    expect(preload).not.toContain("child_process")
    expect(preload).not.toContain("powershell.exe")
  })
})
