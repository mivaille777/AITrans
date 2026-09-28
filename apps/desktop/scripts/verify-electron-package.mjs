import { spawn } from "node:child_process"
import { readFile, readdir, stat } from "node:fs/promises"
import path from "node:path"
import process from "node:process"
import { fileURLToPath } from "node:url"

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(scriptDir, "..")
const outRoot = path.join(desktopRoot, "out")
const requireInstaller = process.argv.includes("--require-installer")

async function existsFile(file) {
  const info = await stat(file).catch(() => null)
  return Boolean(info?.isFile())
}

async function findPackagedApp() {
  const entries = await readdir(outRoot, { withFileTypes: true })
  const candidates = entries
    .filter((entry) => entry.isDirectory() && /-win32-x64$/i.test(entry.name))
    .map((entry) => path.join(outRoot, entry.name))
  for (const directory of candidates) {
    if (await existsFile(path.join(directory, "AITrans.exe"))) return directory
  }
  throw new Error("Unable to find packaged AITrans win32-x64 directory under apps/desktop/out.")
}

function run(command, args, cwd, env = process.env) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd,
      stdio: "inherit",
      windowsHide: false,
      env,
    })
    child.once("error", reject)
    child.once("exit", (code) => {
      if (code === 0) resolve()
      else reject(new Error(`${command} exited with code ${code ?? "unknown"}.`))
    })
  })
}

async function findForbiddenModelArtifact(root) {
  const forbiddenExact = new Set([
    "model.safetensors",
    "pytorch_model.bin",
    "pytorch_model.bin.index.json",
    "model.safetensors.index.json",
  ])
  async function walk(directory) {
    const entries = await readdir(directory, { withFileTypes: true })
    for (const entry of entries) {
      const absolute = path.join(directory, entry.name)
      if (entry.isDirectory()) {
        const nested = await walk(absolute)
        if (nested) return nested
      } else {
        const lower = entry.name.toLowerCase()
        if (forbiddenExact.has(lower) || lower.endsWith(".gguf")) return absolute
      }
    }
    return null
  }
  return walk(root)
}

const packageDir = await findPackagedApp()
const resources = path.join(packageDir, "resources")
const sidecarDir = path.join(resources, "backend", "AITransBackend")
const updateConfigPath = path.join(resources, "update-config.json")
const required = [
  path.join(packageDir, "AITrans.exe"),
  path.join(resources, "app.asar"),
  path.join(resources, "app.asar.unpacked", "dist", "index.html"),
  path.join(sidecarDir, "AITransBackend.exe"),
  path.join(resources, "backend", "sidecar-manifest.json"),
  updateConfigPath,
]
for (const file of required) {
  if (!(await existsFile(file))) throw new Error(`Packaged artifact is missing: ${file}`)
}

const updateConfig = JSON.parse(await readFile(updateConfigPath, "utf8"))
if (updateConfig.schema_version !== 1) {
  throw new Error("Packaged update config schema_version must be 1.")
}
if (!["stable", "beta"].includes(updateConfig.channel)) {
  throw new Error("Packaged update config channel is invalid.")
}
if (updateConfig.enabled && !/^https:\/\//i.test(String(updateConfig.base_url ?? ""))) {
  throw new Error("Enabled packaged update config must use an HTTPS base_url.")
}

const forbidden = await findForbiddenModelArtifact(path.join(resources, "backend"))
if (forbidden) throw new Error(`Packaged backend contains a forbidden model artifact: ${forbidden}`)

console.log("Running packaged sidecar smoke test...")
await run(path.join(sidecarDir, "AITransBackend.exe"), ["--runtime-smoke-test"], sidecarDir)

console.log("Running packaged Electron -> backend lifecycle smoke test...")
await run(
  path.join(packageDir, "AITrans.exe"),
  ["--electron-runtime-smoke-test"],
  packageDir,
  {
    ...process.env,
    AITRANS_API_PORT: "18766",
    AITRANS_BACKEND_HEALTH_URL: "http://127.0.0.1:18766/health",
  },
)

if (requireInstaller) {
  const makerRoot = path.join(outRoot, "make", "squirrel.windows", "x64")
  const artifacts = await readdir(makerRoot)
  const setup = artifacts.find((name) => /Setup\.exe$/i.test(name))
  const nupkg = artifacts.find((name) => /-full\.nupkg$/i.test(name))
  if (!setup || !nupkg || !artifacts.includes("RELEASES")) {
    throw new Error("Squirrel.Windows output must contain Setup.exe, a full .nupkg, and RELEASES.")
  }
  console.log(`Squirrel installer verified: ${path.join(makerRoot, setup)}`)
}
console.log(`Electron package verified: ${packageDir}`)
