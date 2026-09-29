import type { DesktopAdapter } from "./adapter"
import { browserDesktopAdapter } from "./browser/browser-adapter"
import { electronDesktopAdapter } from "./electron/electron-adapter"

function resolveDesktopAdapter(): DesktopAdapter {
  if (typeof window !== "undefined" && window.aiTransDesktop) {
    return electronDesktopAdapter
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
  WindowCloseBehavior,
  WindowAdapter,
} from "./adapter"
