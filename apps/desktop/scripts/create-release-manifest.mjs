import { createHash } from "node:crypto"
import { readFile, readdir, stat, writeFile } from "node:fs/promises"
import path from "node:path"
import process from "node:process"
import { fileURLToPath } from "node:url"

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(scriptDir, "..")
const repoRoot = path.resolve(desktopRoot, "../..")
const makerRoot = path.join(desktopRoot, "out", "make", "squirrel.windows", "x64")
const output = path.join(desktopRoot, "out", "release-manifest.json")

async function sha256(file) {
  const data = await readFile(file)
  return createHash("sha256").update(data).digest("hex")
}

const version = (await readFile(path.join(repoRoot, "VERSION"), "utf8")).trim()
const entries = await readdir(makerRoot)
const names = entries.filter((name) => /Setup\.exe$/i.test(name) || /-full\.nupkg$/i.test(name) || name === "RELEASES")
if (!names.some((name) => /Setup\.exe$/i.test(name))) throw new Error("Release manifest requires Setup.exe")
if (!names.some((name) => /-full\.nupkg$/i.test(name))) throw new Error("Release manifest requires full nupkg")
if (!names.includes("RELEASES")) throw new Error("Release manifest requires RELEASES")

const artifacts = []
for (const name of names.sort()) {
  const file = path.join(makerRoot, name)
  const info = await stat(file)
  artifacts.push({ name, bytes: info.size, sha256: await sha256(file) })
}

const manifest = {
  schema_version: 1,
  product: "AITrans",
  version,
  commit: process.env.GITHUB_SHA || process.env.AITRANS_GIT_SHA || "local",
  platform: "win32-x64",
  generated_at: new Date().toISOString(),
  artifacts,
}
await writeFile(output, JSON.stringify(manifest, null, 2) + "\n", "utf8")
console.log("Release manifest: " + output)
