import { BrowserWindow, screen } from "electron"

import { APP_ORIGIN } from "./app-protocol.cjs"
import path from "node:path"
import { setTimeout as delay } from "node:timers/promises"

export interface OverlayPoint {
  x: number
  y: number
}

export interface OverlaySize {
  width: number
  height: number
}

export interface OverlayPlacementContext {
  cursor: OverlayPoint
  windowSize: OverlaySize
  workArea: OverlayPoint & OverlaySize
  visible: boolean
}

const DEVELOPMENT_RENDERER_URL_ENV = "AITRANS_RENDERER_URL"

function rendererDevelopmentUrl(): string | null {
  const value = process.env[DEVELOPMENT_RENDERER_URL_ENV]?.trim()
  return value || null
}

function isAllowedNavigation(targetUrl: string, developmentUrl: string | null): boolean {
  if (developmentUrl) {
    try {
      return new URL(targetUrl).origin === new URL(developmentUrl).origin
    } catch {
      return false
    }
  }
  return targetUrl.startsWith(APP_ORIGIN + "/")
}

function clamp(value: number, minimum: number, maximum: number): number {
  return Math.max(minimum, Math.min(value, Math.max(minimum, maximum)))
}

export class OverlayManager {
  private window: BrowserWindow | null = null
  private moveGeneration = 0
  private resizeGeneration = 0
  private ignoreMovesUntil = 0
  private readonly movedListeners = new Set<(position: OverlayPoint) => void>()

  getWindow(): BrowserWindow | null {
    if (!this.window || this.window.isDestroyed()) return null
    return this.window
  }

  async ensureWindow(): Promise<BrowserWindow> {
    const existing = this.getWindow()
    if (existing) return existing

    const preload = path.join(__dirname, "../preload/index.cjs")
    const developmentUrl = rendererDevelopmentUrl()

    const window = new BrowserWindow({
      title: "",
      width: 420,
      height: 190,
      minWidth: 320,
      minHeight: 184,
      resizable: false,
      frame: false,
      transparent: true,
      backgroundColor: "#00000000",
      hasShadow: false,
      alwaysOnTop: true,
      skipTaskbar: true,
      show: false,
      autoHideMenuBar: true,
      webPreferences: {
        preload,
        nodeIntegration: false,
        contextIsolation: true,
        sandbox: true,
        webSecurity: true,
      },
    })

    window.webContents.setWindowOpenHandler(() => ({ action: "deny" }))
    window.webContents.on("will-navigate", (event, url) => {
      if (!isAllowedNavigation(url, developmentUrl)) {
        event.preventDefault()
      }
    })

    window.on("move", () => {
      if (Date.now() < this.ignoreMovesUntil) return
      const [x, y] = window.getPosition()
      for (const listener of this.movedListeners) {
        listener({ x, y })
      }
    })

    window.on("closed", () => {
      if (this.window === window) this.window = null
    })

    if (developmentUrl) {
      const base = developmentUrl.endsWith("/") ? developmentUrl : developmentUrl + "/"
      await window.loadURL(new URL("overlay.html", base).toString())
    } else {
      await window.loadURL(APP_ORIGIN + "/overlay.html")
    }

    this.window = window
    return window
  }

  async destroy(): Promise<void> {
    this.moveGeneration += 1
    this.resizeGeneration += 1
    const window = this.getWindow()
    this.window = null
    if (window) window.destroy()
  }

  async show(): Promise<void> {
    const window = await this.ensureWindow()
    window.showInactive()
  }

  async hide(): Promise<void> {
    this.moveGeneration += 1
    this.resizeGeneration += 1
    this.getWindow()?.hide()
  }

  async focus(): Promise<void> {
    const window = await this.ensureWindow()
    window.show()
    window.focus()
  }

  async placementContext(reference?: OverlayPoint | null): Promise<OverlayPlacementContext> {
    const window = await this.ensureWindow()
    const cursor = screen.getCursorScreenPoint()
    const display = screen.getDisplayNearestPoint(reference ?? cursor)
    const [width, height] = window.getSize()
    const area = display.workArea

    return {
      cursor,
      windowSize: { width, height },
      workArea: {
        x: area.x,
        y: area.y,
        width: area.width,
        height: area.height,
      },
      visible: window.isVisible(),
    }
  }

  async setPosition(position: OverlayPoint, animate: boolean): Promise<void> {
    const window = await this.ensureWindow()
    const [startX, startY] = window.getPosition()
    const targetX = Math.round(position.x)
    const targetY = Math.round(position.y)
    const deltaX = targetX - startX
    const deltaY = targetY - startY
    const distance = Math.hypot(deltaX, deltaY)
    const generation = ++this.moveGeneration

    this.ignoreMovesUntil = Date.now() + (animate ? 180 : 120)

    if (!animate || distance > 720) {
      window.setPosition(targetX, targetY, false)
      return
    }

    const steps = 10
    for (let step = 1; step <= steps; step += 1) {
      if (generation !== this.moveGeneration || window.isDestroyed()) return
      const t = step / steps
      const eased = 1 - Math.pow(1 - t, 3)
      window.setPosition(
        Math.round(startX + deltaX * eased),
        Math.round(startY + deltaY * eased),
        false,
      )
      if (step < steps) await delay(8)
    }
  }

  async resize(target: OverlaySize): Promise<void> {
    const window = await this.ensureWindow()
    const generation = ++this.resizeGeneration
    const [startWidth, startHeight] = window.getSize()
    const deltaWidth = Math.round(target.width) - startWidth
    const deltaHeight = Math.round(target.height) - startHeight

    if (Math.abs(deltaWidth) < 1 && Math.abs(deltaHeight) < 1) {
      this.keepInsideWorkArea(window)
      return
    }

    const steps = 8
    for (let step = 1; step <= steps; step += 1) {
      if (generation !== this.resizeGeneration || window.isDestroyed()) return
      const t = step / steps
      const eased = 1 - Math.pow(1 - t, 4)
      window.setSize(
        Math.max(1, Math.round(startWidth + deltaWidth * eased)),
        Math.max(1, Math.round(startHeight + deltaHeight * eased)),
        false,
      )
      if (step < steps) await delay(18)
    }

    if (generation === this.resizeGeneration) {
      this.keepInsideWorkArea(window)
    }
  }

  getPosition(): OverlayPoint | null {
    const window = this.getWindow()
    if (!window) return null
    const [x, y] = window.getPosition()
    return { x, y }
  }

  async setAlwaysOnTop(enabled: boolean): Promise<void> {
    const window = await this.ensureWindow()
    window.setAlwaysOnTop(enabled)
  }

  async setClickThrough(enabled: boolean): Promise<void> {
    const window = await this.ensureWindow()
    if (enabled) {
      window.setIgnoreMouseEvents(true, { forward: true })
    } else {
      window.setIgnoreMouseEvents(false)
    }
  }

  send(channel: string, payload: unknown): void {
    const window = this.getWindow()
    if (!window || window.webContents.isDestroyed()) return
    window.webContents.send(channel, payload)
  }

  onMoved(listener: (position: OverlayPoint) => void): () => void {
    this.movedListeners.add(listener)
    return () => this.movedListeners.delete(listener)
  }

  private keepInsideWorkArea(window: BrowserWindow): void {
    const bounds = window.getBounds()
    const display = screen.getDisplayNearestPoint({ x: bounds.x, y: bounds.y })
    const area = display.workArea
    const maximumX = Math.max(area.x, area.x + area.width - bounds.width)
    const maximumY = Math.max(area.y, area.y + area.height - bounds.height)
    const nextX = Math.round(clamp(bounds.x, area.x, maximumX))
    const nextY = Math.round(clamp(bounds.y, area.y, maximumY))

    if (nextX !== bounds.x || nextY !== bounds.y) {
      this.ignoreMovesUntil = Date.now() + 120
      window.setPosition(nextX, nextY, false)
    }
  }
}
