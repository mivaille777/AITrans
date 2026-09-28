import { spawn, spawnSync } from "node:child_process"
import net from "node:net"
import path from "node:path"
import process from "node:process"
import { setTimeout as delay } from "node:timers/promises"

const rendererHost = "127.0.0.1"
const rendererPort = 5173
const rendererUrl = `http://${rendererHost}:${rendererPort}`
const backendHost = "127.0.0.1"
const backendPort = 8766
const backendHealthUrl = `http://${backendHost}:${backendPort}/health`

const npmCliPath = process.env.npm_execpath
const npmCommand = process.platform === "win32" ? process.execPath : "npm"
const electronCommand = process.platform === "win32"
  ? process.execPath
  : path.join(process.cwd(), "node_modules", ".bin", "electron")
const electronArgs = process.platform === "win32"
  ? [path.join(process.cwd(), "node_modules", "electron", "cli.js"), "."]
  : ["."]

function npmArgs(args) {
  if (process.platform !== "win32") return args
  if (!npmCliPath) {
    throw new Error("Windows Electron development must be started through npm run.")
  }
  return [npmCliPath, ...args]
}

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

function portIsOpen(host, port, timeoutMs = 500) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host, port })
    let settled = false

    const finish = (value) => {
      if (settled) return
      settled = true
      socket.destroy()
      resolve(value)
    }

    socket.setTimeout(timeoutMs)
    socket.once("connect", () => finish(true))
    socket.once("timeout", () => finish(false))
    socket.once("error", () => finish(false))
  })
}

async function aiTransBackendIsHealthy() {
  try {
    const response = await fetch(backendHealthUrl, {
      signal: AbortSignal.timeout(1000),
      headers: { Accept: "application/json" },
    })
    if (!response.ok) return false

    const payload = await response.json()
    return payload?.status === "ok" && payload?.service === "aitrans-backend"
  } catch {
    return false
  }
}

async function preflightPorts() {
  if (await portIsOpen(rendererHost, rendererPort)) {
    throw new Error(
      `Renderer port ${rendererPort} is already in use. Stop the existing Vite/Electron development process before running electron:dev.`,
    )
  }

  if (await portIsOpen(backendHost, backendPort)) {
    if (!(await aiTransBackendIsHealthy())) {
      throw new Error(
        `Backend port ${backendPort} is occupied by a non-AITrans service. Free the port before starting Electron.`,
      )
    }
    console.log(
      `AITrans backend already healthy on ${backendHealthUrl}; Electron will reuse it as an external backend.`,
    )
  }
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
  throw new Error("Vite did not become ready on http://127.0.0.1:5173.")
}

function waitForExit(child, name) {
  return new Promise((resolve, reject) => {
    child.once("error", reject)
    child.once("exit", (code, signal) => {
      resolve({ name, code: code ?? 0, signal })
    })
  })
}

function stopProcessTree(child) {
  if (!child?.pid || child.exitCode !== null || child.signalCode !== null) return

  if (process.platform === "win32") {
    spawnSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], {
      stdio: "ignore",
      windowsHide: true,
    })
  } else {
    child.kill("SIGTERM")
  }
}

let vite = null
let electron = null
let stopping = false

function stop() {
  if (stopping) return
  stopping = true
  stopProcessTree(electron)
  stopProcessTree(vite)
}

process.once("SIGINT", stop)
process.once("SIGTERM", stop)

try {
  await preflightPorts()
  await run(npmCommand, npmArgs(["run", "electron:compile"]))

  vite = spawnProcess(npmCommand, npmArgs(["run", "dev"]))
  await waitForRenderer(vite)

  electron = spawnProcess(electronCommand, electronArgs, {
    env: {
      ...process.env,
      AITRANS_RENDERER_URL: rendererUrl,
    },
  })

  const result = await Promise.race([
    waitForExit(electron, "electron"),
    waitForExit(vite, "vite"),
  ])

  if (result.name === "vite") {
    throw new Error(
      `Vite exited while Electron was running (code=${result.code}, signal=${result.signal ?? "none"}).`,
    )
  }

  process.exitCode = result.code
} finally {
  stop()
}
