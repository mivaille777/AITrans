import { PhysicalSize } from "@tauri-apps/api/dpi"
import { invoke } from "@tauri-apps/api/core"
import { emitTo, listen } from "@tauri-apps/api/event"
import { getCurrentWindow } from "@tauri-apps/api/window"

import type { OverlayVisualTheme } from "./overlay-preferences"

const OVERLAY_VISUAL_THEME_CHANGED_EVENT = "aitrans-overlay-visual-theme-changed"

function hasTauriRuntime(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window
}

export function applyOverlayThemeToDocument(theme: OverlayVisualTheme): void {
  if (typeof document === "undefined") return
  document.documentElement.dataset.aitOverlayTheme = theme
}

async function enforceOverlayBorderlessNativeFrame(): Promise<void> {
  await invoke("enforce_overlay_borderless")
}

async function refreshOverlayTransparentComposition(): Promise<void> {
  const currentWindow = getCurrentWindow()
  const size = await currentWindow.outerSize()
  if (size.width < 1 || size.height < 1) return

  /*
   * Tauri/tao issue #14764 leaves a cached Win32/WebView2 caption surface under
   * transparent undecorated windows. The upstream report also notes that a real
   * resize clears that ghost layer. Pulse the physical height by one pixel and
   * immediately restore it; this emits WM_SIZE without leaving the overlay at a
   * different user-visible size and forces WebView2 to recompute the full client
   * surface after the HWND caption styles have been stripped.
   */
  await currentWindow.setSize(new PhysicalSize(size.width, size.height + 1))
  await currentWindow.setSize(new PhysicalSize(size.width, size.height))
}

async function recoverOverlayTransparentSurface(): Promise<void> {
  await enforceOverlayBorderlessNativeFrame()
  await refreshOverlayTransparentComposition()
  await enforceOverlayBorderlessNativeFrame()
}

export async function startOverlayWindowDrag(): Promise<void> {
  if (!hasTauriRuntime()) return

  await enforceOverlayBorderlessNativeFrame()
  await getCurrentWindow().startDragging()

  // Drag/focus transitions are the main trigger for the transparent-window
  // ghost caption. Refresh the WebView2 composition after the native drag ends.
  await recoverOverlayTransparentSurface()
}

export async function applyOverlayNativeVisualTheme(
  theme: OverlayVisualTheme,
): Promise<void> {
  if (!hasTauriRuntime()) return

  await enforceOverlayBorderlessNativeFrame()

  /*
   * Keep the native system backdrop disabled for both DOM themes. The light
   * Liquid Glass appearance is owned by the translucent DOM material; enabling
   * the Windows transient backdrop here can rebuild the non-client caption
   * surface that is visible only through the light transparent host.
   */
  const nativeTheme = "dark"
  await invoke("set_overlay_visual_theme", { theme: nativeTheme })

  // DWM updates can rebuild the cached non-client surface. A one-pixel resize
  // pulse is the upstream-observed operation that actually clears that ghost
  // composition, whereas setDecorations(false) alone does not.
  await recoverOverlayTransparentSurface()

  // localStorage remains the persisted source of truth, but a Tauri event makes
  // cross-window theme changes deterministic instead of relying on WebView2's
  // storage-event timing between the main window and the overlay document.
  await emitTo("overlay", OVERLAY_VISUAL_THEME_CHANGED_EVENT, { theme })
}

export async function subscribeOverlayVisualThemeEvents(
  callback: (theme: OverlayVisualTheme) => void,
): Promise<() => void> {
  if (!hasTauriRuntime()) return () => undefined

  return listen<{ theme?: string }>(OVERLAY_VISUAL_THEME_CHANGED_EVENT, (event) => {
    const theme = event.payload?.theme
    if (theme === "light" || theme === "dark") callback(theme)
  })
}
