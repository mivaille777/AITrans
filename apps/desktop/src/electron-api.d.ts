import type { ElectronDesktopApi } from "./desktop/electron/electron-api"

declare global {
  interface Window {
    aiTransDesktop?: ElectronDesktopApi
  }
}

export {}
