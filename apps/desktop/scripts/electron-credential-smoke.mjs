import assert from "node:assert/strict"
import path from "node:path"
import { pathToFileURL } from "node:url"

if (process.platform !== "win32") {
  console.log("Credential smoke test is Windows-only; skipping.")
  process.exit(0)
}

const modulePath = path.join(
  process.cwd(),
  "dist-electron",
  "main",
  "services",
  "credential-service.cjs",
)
const credentials = await import(pathToFileURL(modulePath).href)

const provider = "openai_compatible"
const secret = "aitrans-electron-ci-credential"

try {
  await credentials.deleteCredential(provider)
  await credentials.saveCredential(provider, secret)

  const status = await credentials.getCredentialStatus(provider)
  assert.equal(status.configured, true)

  const preview = await credentials.getCredentialPreview(provider)
  assert.equal(preview.configured, true)
  assert.equal(preview.masked.endsWith(` · ${secret.length} chars`), true)

  await credentials.deleteCredential(provider)
  const removed = await credentials.getCredentialStatus(provider)
  assert.equal(removed.configured, false)

  console.log("Electron credential vault smoke test passed.")
} finally {
  await credentials.deleteCredential(provider).catch(() => undefined)
}
