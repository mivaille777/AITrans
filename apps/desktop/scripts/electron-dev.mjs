import { spawn } from "node:child_process"
import path from "node:path"
import process from "node:process"
import { setTimeout as delay } from "node:timers/promises"

const rendererUrl = "http://127.0.0.1:5173"
const npmCommand = process.platform === "win32" ? "npm.cmd" : "npm"
const electronCommand = path.join(
  process.cwd(),
  "node_modules",
  ".bin",
  process.platform === "win32" ? "electron.cmd" : "electron",
)

function spawnProcess(command, args, options = {}) {
  return spawn(command, args, {
    cwd: process.cwd(),
    stdio: "inherit",
    ...options,
  })
}

async function run(command, args) {
  const child = spawnProcess(command, args)
  return new Promise((resolve, reject) => {
    child.once("error", reject)
    child.once("exit", (code) => {
      if (code === 0) resolve()
      else reject(new Error(`${command} exited with code ${code ?? "unknown"}.`))
    })
  })
}

async function waitForRenderer(vite) {
  for (let attempt = 0; attempt < 120; attempt += 1) {
    if (vite.exitCode !== null) {
      throw new Error("Vite exited before the Electron renderer became ready.")
    }
    try {
      const response = await fetch(rendererUrl)
      if (response.ok) return
    } catch {
      // Development server is still starting.
    }
    await delay(100)
  }
  throw new Error("Vite did not become ready.")
}

await run(npmCommand, ["run", "electron:compile"])

const vite = spawnProcess(npmCommand, ["run", "dev"])
let electron = null

function stop() {
  if (electron && electron.exitCode === null) electron.kill()
  if (vite.exitCode === null) vite.kill()
}

process.once("SIGINT", stop)
process.once("SIGTERM", stop)

try {
  await waitForRenderer(vite)

  electron = spawnProcess(electronCommand, ["."], {
    env: {
      ...process.env,
      AITRANS_RENDERER_URL: rendererUrl,
    },
  })

  await new Promise((resolve, reject) => {
    electron.once("error", reject)
    electron.once("exit", (code) => {
      process.exitCode = code ?? 0
      resolve()
    })
  })
} finally {
  stop()
}
