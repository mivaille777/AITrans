import { readFile, readdir, stat } from "node:fs/promises"
import path from "node:path"
import { fileURLToPath } from "node:url"

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(scriptDir, "..")
const repoRoot = path.resolve(desktopRoot, "../..")

const excludedDirectories = new Set([
  ".git", ".venv", "node_modules", "dist", "dist-electron", "out", "build",
  "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
])
const textExtensions = new Set([
  ".ts", ".tsx", ".cts", ".mts", ".js", ".mjs", ".cjs", ".json", ".py",
  ".toml", ".yml", ".yaml", ".ps1", ".css", ".html", ".txt",
])

function fail(message) { throw new Error("Release readiness failed: " + message) }
async function text(file) { return readFile(file, "utf8") }
function isContractOrTest(file) {
  const name = path.basename(file)
  return /(?:\.test\.|-contract\.)/i.test(name) || name === "release-readiness.mjs"
}

async function collectTarget(target, output = []) {
  const info = await stat(target).catch(() => null)
  if (!info) return output
  if (info.isFile()) {
    if (textExtensions.has(path.extname(target).toLowerCase()) && !isContractOrTest(target)) output.push(target)
    return output
  }
  const entries = await readdir(target, { withFileTypes: true })
  for (const entry of entries) {
    if (excludedDirectories.has(entry.name)) continue
    const absolute = path.join(target, entry.name)
    if (entry.isDirectory()) await collectTarget(absolute, output)
    else if (textExtensions.has(path.extname(entry.name).toLowerCase()) && !isContractOrTest(absolute)) output.push(absolute)
  }
  return output
}

const canonicalVersion = (await text(path.join(repoRoot, "VERSION"))).trim()
if (!/^\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?$/.test(canonicalVersion)) {
  fail("VERSION is not a valid release version: " + canonicalVersion)
}

const packageJson = JSON.parse(await text(path.join(desktopRoot, "package.json")))
if (packageJson.version !== canonicalVersion) fail(`package.json version ${packageJson.version} != VERSION ${canonicalVersion}`)
if (packageJson.productName !== "AITrans") fail("package.json productName must be AITrans")
if (packageJson.main !== "dist-electron/main/index.cjs") fail("Electron main entry is unexpected")
if (packageJson.config?.forge !== "./forge.config.cjs") fail("Forge config is not explicitly wired")

const packageLock = JSON.parse(await text(path.join(desktopRoot, "package-lock.json")))
if (packageLock.version !== canonicalVersion) fail("package-lock root version does not match VERSION")
if (packageLock.packages?.[""]?.version !== canonicalVersion) fail("package-lock package version does not match VERSION")

const pyproject = await text(path.join(repoRoot, "pyproject.toml"))
const pythonVersion = pyproject.match(/^version\s*=\s*"([^"]+)"/m)?.[1]
if (pythonVersion !== canonicalVersion) fail(`pyproject.toml version ${pythonVersion ?? "missing"} != VERSION ${canonicalVersion}`)

const backendMain = await text(path.join(repoRoot, "backend", "main.py"))
if (!backendMain.includes("version=get_app_version()")) fail("FastAPI version must use get_app_version()")
if (/version\s*=\s*"\d+\.\d+\.\d+"/.test(backendMain)) fail("FastAPI contains a hard-coded version")

const spec = await text(path.join(repoRoot, "aitrans_backend.spec"))
if (!spec.includes('project_root / "VERSION"')) fail("PyInstaller does not bundle VERSION")

const builder = await text(path.join(desktopRoot, "scripts", "build-backend-sidecar.mjs"))
if (!builder.includes("version: appVersion")) fail("Sidecar manifest does not include app version")

const forge = await text(path.join(desktopRoot, "forge.config.cjs"))
for (const expected of ["@electron-forge/maker-squirrel", "extraResource", "win32metadata", "appVersion: releaseVersion", "buildVersion: releaseVersion", "AITRANS_WINDOWS_CERTIFICATE_FILE", "windowsSign"]) {
  if (!forge.includes(expected)) fail("Forge configuration is missing " + expected)
}

const activeRoots = [
  path.join(repoRoot, ".github", "workflows"),
  path.join(repoRoot, "backend"),
  path.join(repoRoot, "scripts"),
  path.join(repoRoot, "start.ps1"),
  path.join(repoRoot, "start-electron.ps1"),
  path.join(repoRoot, "start-electronrebuild.ps1"),
  path.join(repoRoot, "pyproject.toml"),
  path.join(repoRoot, "aitrans_backend.spec"),
  path.join(desktopRoot, "electron"),
  path.join(desktopRoot, "src"),
  path.join(desktopRoot, "scripts"),
  path.join(desktopRoot, "package.json"),
  path.join(desktopRoot, "forge.config.cjs"),
  path.join(desktopRoot, "vite.config.ts"),
]

const activeFiles = []
for (const target of activeRoots) await collectTarget(target, activeFiles)
const legacyHits = []
for (const file of new Set(activeFiles)) {
  if (/tauri/i.test(await text(file))) legacyHits.push(path.relative(repoRoot, file))
}
if (legacyHits.length) fail("legacy runtime references remain in active files: " + legacyHits.slice(0, 20).join(", "))

console.log("AITrans release readiness static gate passed.")
console.log("Version: " + canonicalVersion)
console.log("Active runtime/config files scanned: " + new Set(activeFiles).size)
