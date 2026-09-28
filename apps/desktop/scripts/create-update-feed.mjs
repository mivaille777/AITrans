import { cp, mkdir, readFile, readdir, writeFile } from "node:fs/promises"
import path from "node:path"
import process from "node:process"
import { fileURLToPath } from "node:url"

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(scriptDir, "..")
const repoRoot = path.resolve(desktopRoot, "../..")
const makerRoot = path.join(desktopRoot, "out", "make", "squirrel.windows", "x64")
const version = (await readFile(path.join(repoRoot, "VERSION"), "utf8")).trim()
const requestedChannel = process.env.AITRANS_RELEASE_CHANNEL?.trim().toLowerCase()
const channel = requestedChannel || (version.includes("-") ? "beta" : "stable")
if (!["stable", "beta"].includes(channel)) throw new Error("Release channel must be stable or beta.")
const output = path.join(desktopRoot, "out", "update-feed", channel, "win32", "x64")

const entries = await readdir(makerRoot)
const artifacts = entries.filter((name) => /Setup\.exe$/i.test(name) || /-full\.nupkg$/i.test(name) || name === "RELEASES")
if (!artifacts.includes("RELEASES")) throw new Error("Squirrel RELEASES metadata is missing.")
if (!artifacts.some((name) => /-full\.nupkg$/i.test(name))) throw new Error("Squirrel full nupkg is missing.")

await mkdir(output, { recursive: true })
for (const name of artifacts) await cp(path.join(makerRoot, name), path.join(output, name), { force: true })
const manifest = { schema_version: 1, product: "AITrans", version, channel, platform: "win32", arch: "x64", path: `${channel}/win32/x64`, artifacts: artifacts.sort() }
await writeFile(path.join(output, "channel-manifest.json"), JSON.stringify(manifest, null, 2) + "\n", "utf8")
console.log("Update feed bundle: " + output)
