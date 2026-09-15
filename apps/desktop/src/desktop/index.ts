import type { DesktopAdapter } from "./adapter"
import { browserDesktopAdapter } from "./browser/browser-adapter"
import { tauriDesktopAdapter } from "./tauri/tauri-adapter"

function resolveDesktopAdapter(): DesktopAdapter {
  if (typeof window !== "undefined" && "__TAURI_INTERNALS__" in window) {
    return tauriDesktopAdapter
  }

  return browserDesktopAdapter
}

export const desktop = resolveDesktopAdapter()
export type {
  DesktopAdapter,
  DesktopFilesAdapter,
  DesktopPoint,
  DesktopRuntime,
  DesktopSize,
  DesktopWindowAdapter,
  OverlayPositionMode,
  OverlayWindowAdapter,
  WindowAdapter,
} from "./adapter"
