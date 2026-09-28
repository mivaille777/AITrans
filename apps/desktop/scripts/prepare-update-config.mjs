import { mkdir, readFile, writeFile } from "node:fs/promises"
import path from "node:path"
import process from "node:process"
import { fileURLToPath } from "node:url"

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(scriptDir, "..")
const repoRoot = path.resolve(desktopRoot, "../..")
const outputDir = path.join(repoRoot, "build", "electron-resources")
const output = path.join(outputDir, "update-config.json")

const version = (await readFile(path.join(repoRoot, "VERSION"), "utf8")).trim()
const requestedChannel = process.env.AITRANS_RELEASE_CHANNEL?.trim().toLowerCase()
const channel = requestedChannel || (version.includes("-") ? "beta" : "stable")
if (!["stable", "beta"].includes(channel)) {
  throw new Error("AITRANS_RELEASE_CHANNEL must be stable or beta.")
}

const baseUrl = process.env.AITRANS_UPDATE_BASE_URL?.trim().replace(/\/+$/, "") || ""
const requestedEnabled = process.env.AITRANS_ENABLE_AUTO_UPDATE?.trim() === "1"
const enabled = requestedEnabled && Boolean(baseUrl)
if (enabled && !/^https:\/\//i.test(baseUrl)) {
  throw new Error("Production auto-update base URL must use HTTPS.")
}

const payload = {
  schema_version: 1,
  enabled,
  channel,
  base_url: baseUrl,
  check_interval_minutes: 360,
}
await mkdir(outputDir, { recursive: true })
await writeFile(output, JSON.stringify(payload, null, 2) + "\n", "utf8")
console.log("Prepared Electron update config: " + output)
console.log("Auto update: " + (enabled ? "enabled" : "disabled") + ", channel=" + channel)
