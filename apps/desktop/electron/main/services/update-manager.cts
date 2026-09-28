import { existsSync, readFileSync } from "node:fs"
import path from "node:path"

import { app, autoUpdater } from "electron"

type UpdateChannel = "stable" | "beta"
type UpdateState =
  | "disabled"
  | "idle"
  | "checking"
  | "available"
  | "downloaded"
  | "error"

interface UpdateConfig {
  schema_version: number
  enabled: boolean
  channel: UpdateChannel
  base_url: string
  check_interval_minutes: number
}

const DEFAULT_CONFIG: UpdateConfig = {
  schema_version: 1,
  enabled: false,
  channel: "stable",
  base_url: "",
  check_interval_minutes: 360,
}

function installedUpdateExecutable(): string {
  return path.resolve(path.dirname(process.execPath), "..", "Update.exe")
}

function normalizeConfig(input: Partial<UpdateConfig>): UpdateConfig {
  const channel: UpdateChannel = input.channel === "beta" ? "beta" : "stable"
  const baseUrl = String(input.base_url ?? "").trim().replace(/\/+$/, "")
  const interval = Number(input.check_interval_minutes)
  return {
    schema_version: 1,
    enabled: input.enabled === true,
    channel,
    base_url: baseUrl,
    check_interval_minutes:
      Number.isFinite(interval) && interval >= 30 ? Math.floor(interval) : 360,
  }
}

function loadUpdateConfig(): UpdateConfig {
  const configuredPath =
    process.env.AITRANS_UPDATE_CONFIG_PATH?.trim() ||
    path.join(process.resourcesPath, "update-config.json")

  try {
    const payload = JSON.parse(readFileSync(configuredPath, "utf8")) as Partial<UpdateConfig>
    const config = normalizeConfig(payload)

    const environmentChannel = process.env.AITRANS_RELEASE_CHANNEL?.trim().toLowerCase()
    if (environmentChannel === "stable" || environmentChannel === "beta") {
      config.channel = environmentChannel
    }
    const environmentBaseUrl = process.env.AITRANS_UPDATE_BASE_URL?.trim()
    if (environmentBaseUrl) config.base_url = environmentBaseUrl.replace(/\/+$/, "")
    if (process.env.AITRANS_ENABLE_AUTO_UPDATE?.trim() === "1") config.enabled = true

    return config
  } catch {
    return { ...DEFAULT_CONFIG }
  }
}

function feedUrl(config: UpdateConfig): string {
  return [
    config.base_url.replace(/\/+$/, ""),
    config.channel,
    "win32",
    "x64",
  ].join("/")
}

export class UpdateManager {
  private state: UpdateState = "disabled"
  private firstCheckTimer: NodeJS.Timeout | null = null
  private intervalTimer: NodeJS.Timeout | null = null
  private started = false

  constructor(private readonly beforeInstall: () => void = () => undefined) {}

  start(): void {
    if (this.started) return
    this.started = true

    if (process.platform !== "win32" || !app.isPackaged) {
      this.state = "disabled"
      return
    }
    if (!existsSync(installedUpdateExecutable())) {
      this.state = "disabled"
      console.info("AITrans auto update disabled: app is not Squirrel-installed.")
      return
    }

    const config = loadUpdateConfig()
    if (!config.enabled || !config.base_url) {
      this.state = "disabled"
      console.info("AITrans auto update disabled by packaged configuration.")
      return
    }
    if (!/^https:\/\//i.test(config.base_url)) {
      this.state = "error"
      console.error("AITrans auto update requires an HTTPS base URL.")
      return
    }

    const url = feedUrl(config)
    this.registerEvents()
    autoUpdater.setFeedURL({ url })
    this.state = "idle"
    console.info(`AITrans auto update enabled: channel=${config.channel}, feed=${url}`)

    const firstRun = process.argv.includes("--squirrel-firstrun")
    const firstDelayMs = firstRun ? 15_000 : 5_000
    this.firstCheckTimer = setTimeout(() => this.check(), firstDelayMs)

    const intervalMs = config.check_interval_minutes * 60_000
    this.intervalTimer = setInterval(() => this.check(), intervalMs)
  }

  stop(): void {
    if (this.firstCheckTimer) clearTimeout(this.firstCheckTimer)
    if (this.intervalTimer) clearInterval(this.intervalTimer)
    this.firstCheckTimer = null
    this.intervalTimer = null
  }

  private check(): void {
    if (this.state === "checking") return
    try {
      this.state = "checking"
      autoUpdater.checkForUpdates()
    } catch (error: unknown) {
      this.state = "error"
      console.error("AITrans update check failed.", error)
    }
  }

  private registerEvents(): void {
    autoUpdater.on("checking-for-update", () => {
      this.state = "checking"
    })
    autoUpdater.on("update-available", () => {
      this.state = "available"
      console.info("AITrans update available; Squirrel download started.")
    })
    autoUpdater.on("update-not-available", () => {
      this.state = "idle"
    })
    autoUpdater.on("update-downloaded", (_event, _notes, releaseName) => {
      this.state = "downloaded"
      console.info(`AITrans update downloaded: ${releaseName || "new version"}. It will apply on restart.`)
    })
    autoUpdater.on("error", (error) => {
      this.state = "error"
      console.error("AITrans auto updater error.", error)
    })
    autoUpdater.on("before-quit-for-update", () => {
      this.beforeInstall()
    })
  }
}

export {
  feedUrl,
  installedUpdateExecutable,
  loadUpdateConfig,
  normalizeConfig,
}
