import { desktop } from "./index"
import type { OverlayVisualTheme } from "./overlay-preferences"

export function applyOverlayThemeToDocument(theme: OverlayVisualTheme): void {
  if (typeof document === "undefined") return
  document.documentElement.dataset.aitOverlayTheme = theme
}

export async function startOverlayWindowDrag(): Promise<void> {
  await desktop.overlay.startDragging()
}

export async function applyOverlayNativeVisualTheme(
  theme: OverlayVisualTheme,
): Promise<void> {
  await desktop.overlay.setVisualTheme(theme)
}

export async function subscribeOverlayVisualThemeEvents(
  callback: (theme: OverlayVisualTheme) => void,
): Promise<() => void> {
  return desktop.overlay.onVisualThemeChanged(callback)
}
