import type { DesktopAdapter } from "./adapter"
import { browserDesktopAdapter } from "./browser/browser-adapter"
import { electronDesktopAdapter } from "./electron/electron-adapter"
import { tauriDesktopAdapter } from "./tauri/tauri-adapter"

function resolveDesktopAdapter(): DesktopAdapter {
  if (typeof window !== "undefined" && window.aiTransDesktop) {
    return electronDesktopAdapter
  }

  if (typeof window !== "undefined" && "__TAURI_INTERNALS__" in window) {
    return tauriDesktopAdapter
  }

  return browserDesktopAdapter
}

export const desktop = resolveDesktopAdapter()
export type {
  DesktopAdapter,
  DesktopCredentialAdapter,
  DesktopCredentialPreview,
  DesktopCredentialStatus,
  DesktopFilesAdapter,
  DesktopOverlayTheme,
  DesktopPoint,
  DesktopRuntime,
  DesktopSize,
  DesktopWindowAdapter,
  OverlayPositionMode,
  OverlayWindowAdapter,
  WindowAdapter,
} from "./adapter"
