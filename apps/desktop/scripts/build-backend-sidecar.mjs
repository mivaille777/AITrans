import { spawn } from "node:child_process"
import { cp, mkdir, readFile, readdir, rm, stat, writeFile } from "node:fs/promises"
import path from "node:path"
import process from "node:process"
import { fileURLToPath } from "node:url"

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(scriptDir, "..")
const repoRoot = path.resolve(desktopRoot, "../..")
const buildRoot = path.join(repoRoot, "build")
const pyinstallerDist = path.join(buildRoot, "pyinstaller")
const pyinstallerWork = path.join(buildRoot, "pyinstaller-work")
const sourceSidecar = path.join(pyinstallerDist, "AITransBackend")
const sidecarExe = path.join(sourceSidecar, "AITransBackend.exe")
const stagedBackendRoot = path.join(buildRoot, "electron-resources", "backend")
const stagedSidecar = path.join(stagedBackendRoot, "AITransBackend")
const specPath = path.join(repoRoot, "aitrans_backend.spec")
const versionPath = path.join(repoRoot, "VERSION")
const python = process.env.AITRANS_PYTHON_EXECUTABLE?.trim() || "python"

if (process.platform !== "win32") {
  throw new Error("Stage 10 backend packaging currently targets Windows only.")
}

function run(command, args, options = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(command, args, {
      cwd: repoRoot,
      stdio: "inherit",
      windowsHide: false,
      ...options,
    })
    child.once("error", reject)
    child.once("exit", (code) => {
      if (code === 0) resolve()
      else reject(new Error(`${command} exited with code ${code ?? "unknown"}.`))
    })
  })
}

async function assertBuildEnvironment() {
  const probe = [
    "import PyInstaller",
    "import qdrant_client",
    "import sentence_transformers",
    "import transformers",
    "print('AITrans sidecar build dependencies available')",
  ].join("; ")
  try {
    await run(python, ["-c", probe])
  } catch (error) {
    throw new Error(
      'Missing Python packaging dependencies. Run: python -m pip install -e ".[build]" -r aitranslator-rag-requirements.txt',
      { cause: error },
    )
  }
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

const appVersion = (await readFile(versionPath, "utf8")).trim()
if (!appVersion) throw new Error("VERSION must not be empty.")

await assertBuildEnvironment()
await rm(pyinstallerDist, { recursive: true, force: true })
await rm(pyinstallerWork, { recursive: true, force: true })
await rm(stagedBackendRoot, { recursive: true, force: true })
await mkdir(pyinstallerDist, { recursive: true })
await mkdir(pyinstallerWork, { recursive: true })

console.log("Building AITrans Python backend sidecar with PyInstaller...")
await run(python, [
  "-m", "PyInstaller", "--noconfirm", "--clean",
  "--distpath", pyinstallerDist,
  "--workpath", pyinstallerWork,
  specPath,
])

const executable = await stat(sidecarExe).catch(() => null)
if (!executable?.isFile()) throw new Error(`PyInstaller did not produce ${sidecarExe}.`)

await run(python, [
  path.join(scriptDir, "archive-sidecar-licenses.py"),
  sourceSidecar,
])

console.log("Running frozen backend runtime smoke test...")
await run(sidecarExe, ["--runtime-smoke-test"], { cwd: sourceSidecar })

const forbidden = await findForbiddenModelArtifact(sourceSidecar)
if (forbidden) throw new Error(`Model weight artifact must not be bundled into the sidecar: ${forbidden}`)

await mkdir(stagedBackendRoot, { recursive: true })
await cp(sourceSidecar, stagedSidecar, { recursive: true })
await writeFile(
  path.join(stagedBackendRoot, "sidecar-manifest.json"),
  JSON.stringify({
    schema_version: 1,
    executable: "AITransBackend/AITransBackend.exe",
    version: appVersion,
    models: "external-user-data",
    models_root: "%LOCALAPPDATA%/AITrans/models",
  }, null, 2) + "\n",
  "utf8",
)
console.log(`Staged Electron backend resource: ${stagedSidecar}`)
