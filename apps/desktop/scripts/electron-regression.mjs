import { spawn } from "node:child_process"
import { mkdir, writeFile } from "node:fs/promises"
import path from "node:path"
import process from "node:process"
import { fileURLToPath } from "node:url"

const scriptDir = path.dirname(fileURLToPath(import.meta.url))
const desktopRoot = path.resolve(scriptDir, "..")
const repoRoot = path.resolve(desktopRoot, "../..")
const reportDir = path.join(repoRoot, "test-results")
const reportPath = path.join(reportDir, "electron-regression.json")
const python = process.env.AITRANS_PYTHON_EXECUTABLE?.trim() || "python"
const npmCliPath = process.env.npm_execpath
const npmCommand = process.platform === "win32" ? process.execPath : "npm"

function npmArgs(args) {
  if (process.platform !== "win32") return args
  if (!npmCliPath) {
    throw new Error("Windows Electron regression must be started through npm run.")
  }
  return [npmCliPath, ...args]
}

const steps = [
  { name: "electron-contracts", cwd: desktopRoot, command: npmCommand, args: npmArgs(["run", "electron:check"]) },
  { name: "frontend-regression", cwd: desktopRoot, command: npmCommand, args: npmArgs(["run", "test"]) },
  { name: "frontend-build", cwd: desktopRoot, command: npmCommand, args: npmArgs(["run", "build"]) },
  {
    name: "backend-electron-integration",
    cwd: repoRoot,
    command: python,
    args: [
      "-m", "pytest", "-q",
      "tests/test_backend_health.py",
      "tests/api/test_llm_settings_api.py",
      "tests/api/test_workspace_apply_api.py",
      "tests/api/test_sandbox_approvals_api.py",
      "tests/agent/test_agent_api_runtime.py",
      "tests/agent/test_python_execute_agent_integration.py",
      "tests/rag/test_offline_runtime.py",
      "tests/rag/test_model_manager.py",
      "tests/sandbox/test_filesystem_workspace_service.py",
      "tests/sandbox/test_sandbox_debug_service.py",
    ],
  },
]

function runStep(step) {
  const startedAt = new Date()
  const started = performance.now()
  return new Promise((resolve) => {
    const child = spawn(step.command, step.args, {
      cwd: step.cwd,
      stdio: "inherit",
      windowsHide: false,
      env: process.env,
    })
    child.once("error", (error) => {
      resolve({
        name: step.name, status: "failed", exit_code: null, error: error.message,
        started_at: startedAt.toISOString(),
        duration_ms: Math.round(performance.now() - started),
      })
    })
    child.once("exit", (code, signal) => {
      resolve({
        name: step.name, status: code === 0 ? "passed" : "failed",
        exit_code: code, signal: signal ?? null,
        started_at: startedAt.toISOString(),
        duration_ms: Math.round(performance.now() - started),
      })
    })
  })
}

await mkdir(reportDir, { recursive: true })
const results = []
let failed = false
for (const step of steps) {
  console.log("\n=== Electron regression: " + step.name + " ===")
  const result = await runStep(step)
  results.push(result)
  if (result.status !== "passed") { failed = true; break }
}

const report = {
  schema_version: 1,
  generated_at: new Date().toISOString(),
  platform: process.platform,
  arch: process.arch,
  node: process.version,
  python_command: python,
  status: failed ? "failed" : "passed",
  coverage: {
    electron_contracts: true, frontend: true, backend_health: true, credentials_api: true,
    workspace: true, sandbox: true, agent: true, rag_offline: true,
    packaged_runtime: false, gui_manual_acceptance: false,
  },
  steps: results,
}
await writeFile(reportPath, JSON.stringify(report, null, 2) + "\n", "utf8")
console.log("\nElectron regression report: " + reportPath)
if (failed) process.exitCode = 1
