import { spawnSync } from "node:child_process"
import { mkdir, readdir, writeFile } from "node:fs/promises"
import path from "node:path"
import process from "node:process"
import { fileURLToPath } from "node:url"

if (process.platform !== "win32") throw new Error("Windows signing verification requires Windows.")
const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(scriptDir, "..")
const makerRoot = path.join(desktopRoot, "out", "make", "squirrel.windows", "x64")
const packageExe = path.join(desktopRoot, "out", "AITrans-win32-x64", "AITrans.exe")
const reportPath = path.join(desktopRoot, "out", "signing-report.json")
const requireSigned = process.env.AITRANS_REQUIRE_WINDOWS_SIGNING?.trim() === "1"

const makerEntries = await readdir(makerRoot)
const setupName = makerEntries.find((name) => /Setup\.exe$/i.test(name))
if (!setupName) throw new Error("Setup.exe was not found for signing verification.")
const targets = [packageExe, path.join(makerRoot, setupName)]

const results = []
for (const target of targets) {
  const command = [
    "$s = Get-AuthenticodeSignature -LiteralPath $args[0];",
    "[pscustomobject]@{ Status = [string]$s.Status; Subject = [string]$s.SignerCertificate.Subject; Thumbprint = [string]$s.SignerCertificate.Thumbprint } | ConvertTo-Json -Compress",
  ].join(" ")
  const result = spawnSync("powershell.exe", ["-NoProfile", "-Command", command, target], { encoding: "utf8", windowsHide: true })
  if (result.status !== 0) throw new Error("Get-AuthenticodeSignature failed for " + target + ": " + result.stderr)
  const parsed = JSON.parse(result.stdout.trim())
  results.push({ file: path.relative(desktopRoot, target), status: parsed.Status, subject: parsed.Subject || "", thumbprint: parsed.Thumbprint || "" })
}

const allValid = results.every((item) => item.status === "Valid")
if (requireSigned && !allValid) {
  throw new Error("Windows signing is required, but one or more release executables are not Authenticode Valid.")
}

await mkdir(path.dirname(reportPath), { recursive: true })
await writeFile(reportPath, JSON.stringify({ schema_version: 1, required: requireSigned, valid: allValid, files: results }, null, 2) + "\n", "utf8")
console.log("Windows signing verification: " + (allValid ? "VALID" : "UNSIGNED/INVALID") + (requireSigned ? " (required)" : " (optional)"))
console.log("Signing report: " + reportPath)
