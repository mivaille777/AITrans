import { readFile, readdir } from "node:fs/promises"
import path from "node:path"
import process from "node:process"
import { fileURLToPath } from "node:url"

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(scriptDir, "..")
const repoRoot = path.resolve(desktopRoot, "../..")

const excludedDirectories = new Set([
  ".git", ".venv", "node_modules", "dist", "dist-electron", "out", "build",
  "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
])

const excludedPrefixes = [
  path.join(repoRoot, "docs", "archive", "legacy"),
  path.join(repoRoot, "docs", "electron-migration"),
]

const textExtensions = new Set([
  ".ts", ".tsx", ".cts", ".mts", ".js", ".mjs", ".cjs", ".json", ".py",
  ".toml", ".yml", ".yaml", ".ps1", ".md", ".css", ".html", ".txt",
])

function fail(message) {
  throw new Error("Release readiness failed: " + message)
}

async function text(file) {
  return readFile(file, "utf8")
}

function isExcluded(file) {
  return excludedPrefixes.some((prefix) => file === prefix || file.startsWith(prefix + path.sep))
}

async function collectFiles(directory, output = []) {
  if (isExcluded(directory)) return output
  const entries = await readdir(directory, { withFileTypes: true })
  for (const entry of entries) {
    if (excludedDirectories.has(entry.name)) continue
    const absolute = path.join(directory, entry.name)
    if (isExcluded(absolute)) continue
    if (entry.isDirectory()) {
      await collectFiles(absolute, output)
    } else if (textExtensions.has(path.extname(entry.name).toLowerCase())) {
      output.push(absolute)
    }
  }
  return output
}

const canonicalVersion = (await text(path.join(repoRoot, "VERSION"))).trim()
if (!/^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/.test(canonicalVersion)) {
  fail("VERSION is not a valid release version: " + canonicalVersion)
}

const packageJson = JSON.parse(await text(path.join(desktopRoot, "package.json")))
if (packageJson.version !== canonicalVersion) {
  fail(`package.json version ${packageJson.version} != VERSION ${canonicalVersion}`)
}
if (packageJson.productName !== "AITrans") fail("package.json productName must be AITrans")
if (packageJson.main !== "dist-electron/main/index.cjs") fail("Electron main entry is unexpected")
if (packageJson.config?.forge !== "./forge.config.cjs") fail("Forge config is not explicitly wired")

const packageLock = JSON.parse(await text(path.join(desktopRoot, "package-lock.json")))
if (packageLock.version !== canonicalVersion) fail("package-lock root version does not match VERSION")
if (packageLock.packages?.[""]?.version !== canonicalVersion) fail("package-lock package version does not match VERSION")

const pyproject = await text(path.join(repoRoot, "pyproject.toml"))
const pythonVersion = pyproject.match(/^version\s*=\s*"([^"]+)"/m)?.[1]
if (pythonVersion !== canonicalVersion) {
  fail(`pyproject.toml version ${pythonVersion ?? "missing"} != VERSION ${canonicalVersion}`)
}

const backendMain = await text(path.join(repoRoot, "backend", "main.py"))
if (!backendMain.includes("version=get_app_version()")) fail("FastAPI version must use get_app_version()")
if (/version\s*=\s*"\d+\.\d+\.\d+"/.test(backendMain)) fail("FastAPI contains a hard-coded version")

const spec = await text(path.join(repoRoot, "aitrans_backend.spec"))
if (!spec.includes('project_root / "VERSION"')) fail("PyInstaller does not bundle VERSION")

const builder = await text(path.join(desktopRoot, "scripts", "build-backend-sidecar.mjs"))
if (!builder.includes("version: appVersion")) fail("Sidecar manifest does not include app version")

const forge = await text(path.join(desktopRoot, "forge.config.cjs"))
for (const expected of ["@electron-forge/maker-squirrel", "extraResource", "win32metadata"]) {
  if (!forge.includes(expected)) fail("Forge configuration is missing " + expected)
}

const activeFiles = await collectFiles(repoRoot)
const legacyHits = []
for (const file of activeFiles) {
  const source = await text(file)
  if (/tauri/i.test(source)) legacyHits.push(path.relative(repoRoot, file))
}
if (legacyHits.length) {
  fail("legacy runtime references remain in active files: " + legacyHits.slice(0, 20).join(", "))
}

console.log("AITrans release readiness static gate passed.")
console.log("Version: " + canonicalVersion)
console.log("Active text files scanned: " + activeFiles.length)
