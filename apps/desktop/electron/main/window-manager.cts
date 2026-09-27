import { BrowserWindow } from "electron"

import { APP_ORIGIN } from "./app-protocol.cjs"
import path from "node:path"

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

export async function createMainWindow(): Promise<BrowserWindow> {
  const preload = path.join(__dirname, "../preload/index.cjs")
  const developmentUrl = rendererDevelopmentUrl()

  const window = new BrowserWindow({
    title: "AITranslator WebReBuild",
    width: 1320,
    height: 720,
    minWidth: 960,
    minHeight: 600,
    center: true,
    resizable: true,
    frame: false,
    transparent: true,
    backgroundColor: "#00000000",
    hasShadow: false,
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

  window.once("ready-to-show", () => {
    if (!window.isDestroyed()) window.show()
  })

  if (developmentUrl) {
    await window.loadURL(developmentUrl)
  } else {
    await window.loadURL(APP_ORIGIN + "/index.html")
  }

  return window
}
