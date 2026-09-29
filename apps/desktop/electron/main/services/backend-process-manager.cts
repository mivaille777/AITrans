import { app } from "electron"
import {
  spawn,
  spawnSync,
  type ChildProcessByStdio,
} from "node:child_process"
import path from "node:path"
import type { Readable } from "node:stream"
import { setTimeout as delay } from "node:timers/promises"

export type BackendRuntimeState =
  | "stopped"
  | "starting"
  | "ready"
  | "external"
  | "failed"

export interface BackendRuntimeStatus {
  state: BackendRuntimeState
  owned: boolean
  pid: number | null
  restartAttempts: number
}

const DEFAULT_HEALTH_URL = "http://127.0.0.1:8766/health"
const READY_ATTEMPTS = 120
const READY_DELAY_MS = 250
const MAX_DIAGNOSTIC_BYTES = 16 * 1024

function backendHealthUrl(): string {
  return process.env.AITRANS_BACKEND_HEALTH_URL?.trim() || DEFAULT_HEALTH_URL
}

async function backendIsHealthy(): Promise<boolean> {
  try {
    const response = await fetch(backendHealthUrl(), {
      signal: AbortSignal.timeout(1000),
      headers: { Accept: "application/json" },
    })
    if (!response.ok) return false
    const payload = await response.json() as {
      status?: unknown
      service?: unknown
    }
    return payload.status === "ok" && payload.service === "aitrans-backend"
  } catch {
    return false
  }
}

function packagedBackendExecutable(): string {
  const configured = process.env.AITRANS_BACKEND_EXECUTABLE?.trim()
  if (configured) return configured

  return path.join(
    process.resourcesPath,
    "backend",
    "AITransBackend",
    "AITransBackend.exe",
  )
}

function developmentBackendLaunch(): {
  command: string
  args: string[]
  cwd: string
} {
  return {
    command: process.env.AITRANS_PYTHON_EXECUTABLE?.trim() || "python",
    args: ["-m", "backend"],
    cwd: process.env.AITRANS_REPO_ROOT?.trim() ||
      path.resolve(app.getAppPath(), "../.."),
  }
}

export class BackendProcessManager {
  private child: ChildProcessByStdio<null, Readable, Readable> | null = null
  private owned = false
  private stopping = false
  private state: BackendRuntimeState = "stopped"
  private restartAttempts = 0
  private diagnosticTail = ""

  status(): BackendRuntimeStatus {
    return {
      state: this.state,
      owned: this.owned,
      pid: this.child?.pid ?? null,
      restartAttempts: this.restartAttempts,
    }
  }

  diagnostics(): string {
    return this.diagnosticTail
  }

  async start(): Promise<void> {
    if (this.state === "ready" || this.state === "external") return

    if (await backendIsHealthy()) {
      this.state = "external"
      this.owned = false
      return
    }

    this.stopping = false
    this.state = "starting"
    this.spawnOwnedBackend()
    await this.waitUntilReady()
  }

  stopNow(): void {
    this.stopping = true
    this.state = "stopped"

    const child = this.child
    this.child = null
    if (!child || !this.owned || child.pid == null) {
      this.owned = false
      return
    }

    this.owned = false

    if (process.platform === "win32") {
      spawnSync(
        "taskkill.exe",
        ["/PID", String(child.pid), "/T", "/F"],
        {
          windowsHide: true,
          stdio: "ignore",
        },
      )
      return
    }

    child.kill("SIGTERM")
  }

  private spawnOwnedBackend(): void {
    if (this.child && this.child.exitCode === null) return

    const launch = app.isPackaged
      ? {
          command: packagedBackendExecutable(),
          args: [] as string[],
          cwd: path.dirname(packagedBackendExecutable()),
        }
      : developmentBackendLaunch()

    const child = spawn(launch.command, launch.args, {
      cwd: launch.cwd,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
      env: {
        ...process.env,
        PYTHONUNBUFFERED: "1",
        ...(app.isPackaged
          ? { AITRANS_SANDBOX_BUILD_CONTEXT: path.join(process.resourcesPath, "sandbox", "python") }
          : {}),
      },
    })

    this.child = child
    this.owned = true

    const appendDiagnostic = (chunk: Buffer) => {
      this.diagnosticTail += chunk.toString("utf8")
      if (Buffer.byteLength(this.diagnosticTail, "utf8") > MAX_DIAGNOSTIC_BYTES) {
        this.diagnosticTail = this.diagnosticTail.slice(-MAX_DIAGNOSTIC_BYTES)
      }
    }

    child.stdout.on("data", appendDiagnostic)
    child.stderr.on("data", appendDiagnostic)

    child.once("error", () => {
      if (this.child === child) {
        this.child = null
        this.owned = false
        this.state = "failed"
      }
    })

    child.once("exit", () => {
      if (this.child !== child) return

      this.child = null
      this.owned = false

      if (this.stopping) {
        this.state = "stopped"
        return
      }

      this.state = "failed"
      if (this.restartAttempts < 1) {
        this.restartAttempts += 1
        void delay(500).then(() => this.start()).catch(() => {
          this.state = "failed"
        })
      }
    })
  }

  private async waitUntilReady(): Promise<void> {
    for (let attempt = 0; attempt < READY_ATTEMPTS; attempt += 1) {
      if (await backendIsHealthy()) {
        this.state = this.owned ? "ready" : "external"
        return
      }

      if (this.state === "failed" && !this.child) {
        break
      }

      await delay(READY_DELAY_MS)
    }

    if (this.state !== "ready" && this.state !== "external") {
      this.state = "failed"
      throw new Error("AITrans backend did not become ready.")
    }
  }
}
