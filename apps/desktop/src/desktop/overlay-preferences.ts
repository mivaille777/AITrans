import type { DesktopPoint, OverlayPositionMode } from "./adapter"

export type OverlayVisualTheme = "light" | "dark"

const STORAGE_KEY = "aitrans.overlay.preferences.v3"
const PREVIOUS_STORAGE_KEY = "aitrans.overlay.preferences.v2"
const LEGACY_STORAGE_KEY = "aitrans.overlay.preferences.v1"
const CHANGE_EVENT = "aitrans-overlay-preferences-changed"

export interface OverlayPreferences {
  positionMode: OverlayPositionMode
  alwaysOnTop: boolean
  locked: boolean
  clickThrough: boolean
  smartAutoDismiss: boolean
  customPosition: DesktopPoint | null
  theme: OverlayVisualTheme
}

export const DEFAULT_OVERLAY_PREFERENCES: OverlayPreferences = {
  positionMode: "mouse_follow",
  alwaysOnTop: true,
  locked: false,
  clickThrough: false,
  smartAutoDismiss: true,
  customPosition: null,
  theme: "light",
}

function isPositionMode(value: unknown): value is OverlayPositionMode {
  return [
    "mouse_follow",
    "desktop_lyrics_bottom",
    "desktop_lyrics_center",
    "desktop_lyrics_top",
    "custom_fixed_position",
  ].includes(String(value))
}

function isOverlayTheme(value: unknown): value is OverlayVisualTheme {
  return value === "light" || value === "dark"
}

function isDesktopPoint(value: unknown): value is DesktopPoint {
  if (!value || typeof value !== "object") return false
  const candidate = value as Partial<DesktopPoint>
  return (
    typeof candidate.x === "number" &&
    Number.isFinite(candidate.x) &&
    typeof candidate.y === "number" &&
    Number.isFinite(candidate.y)
  )
}

function normalizePreferences(
  parsed: Partial<OverlayPreferences>,
  { resetClickThrough = false }: { resetClickThrough?: boolean } = {},
): OverlayPreferences {
  return {
    positionMode: isPositionMode(parsed.positionMode)
      ? parsed.positionMode
      : DEFAULT_OVERLAY_PREFERENCES.positionMode,
    alwaysOnTop:
      typeof parsed.alwaysOnTop === "boolean"
        ? parsed.alwaysOnTop
        : DEFAULT_OVERLAY_PREFERENCES.alwaysOnTop,
    locked:
      typeof parsed.locked === "boolean"
        ? parsed.locked
        : DEFAULT_OVERLAY_PREFERENCES.locked,
    clickThrough: resetClickThrough
      ? false
      : typeof parsed.clickThrough === "boolean"
        ? parsed.clickThrough
        : DEFAULT_OVERLAY_PREFERENCES.clickThrough,
    smartAutoDismiss:
      typeof parsed.smartAutoDismiss === "boolean"
        ? parsed.smartAutoDismiss
        : DEFAULT_OVERLAY_PREFERENCES.smartAutoDismiss,
    customPosition: isDesktopPoint(parsed.customPosition)
      ? parsed.customPosition
      : null,
    theme: isOverlayTheme(parsed.theme)
      ? parsed.theme
      : DEFAULT_OVERLAY_PREFERENCES.theme,
  }
}

function persistMigratedPreferences(preferences: OverlayPreferences): OverlayPreferences {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences))
  return preferences
}

export function readOverlayPreferences(): OverlayPreferences {
  if (typeof window === "undefined") return DEFAULT_OVERLAY_PREFERENCES

  try {
    const raw = window.localStorage.getItem(STORAGE_KEY)
    if (raw) {
      return normalizePreferences(JSON.parse(raw) as Partial<OverlayPreferences>)
    }

    const previousRaw = window.localStorage.getItem(PREVIOUS_STORAGE_KEY)
    if (previousRaw) {
      return persistMigratedPreferences(
        normalizePreferences(JSON.parse(previousRaw) as Partial<OverlayPreferences>),
      )
    }

    const legacyRaw = window.localStorage.getItem(LEGACY_STORAGE_KEY)
    if (!legacyRaw) return DEFAULT_OVERLAY_PREFERENCES

    // v1 could persist click-through=true indefinitely, leaving the native overlay
    // impossible to click after an upgrade. Preserve placement preferences but make
    // pointer interaction safe again; users can explicitly re-enable click-through.
    return persistMigratedPreferences(
      normalizePreferences(
        JSON.parse(legacyRaw) as Partial<OverlayPreferences>,
        { resetClickThrough: true },
      ),
    )
  } catch {
    return DEFAULT_OVERLAY_PREFERENCES
  }
}

export function writeOverlayPreferences(preferences: OverlayPreferences): OverlayPreferences {
  if (typeof window !== "undefined") {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(preferences))
    window.dispatchEvent(new CustomEvent(CHANGE_EVENT, { detail: preferences }))
  }
  return preferences
}

export function updateOverlayPreferences(
  patch: Partial<OverlayPreferences>,
): OverlayPreferences {
  return writeOverlayPreferences({
    ...readOverlayPreferences(),
    ...patch,
  })
}

export function subscribeOverlayPreferences(
  callback: (preferences: OverlayPreferences) => void,
): () => void {
  if (typeof window === "undefined") return () => undefined

  const handleStorage = (event: StorageEvent) => {
    if (
      event.key === STORAGE_KEY ||
      event.key === PREVIOUS_STORAGE_KEY ||
      event.key === LEGACY_STORAGE_KEY
    ) {
      callback(readOverlayPreferences())
    }
  }
  const handleLocalChange = () => callback(readOverlayPreferences())

  window.addEventListener("storage", handleStorage)
  window.addEventListener(CHANGE_EVENT, handleLocalChange)
  return () => {
    window.removeEventListener("storage", handleStorage)
    window.removeEventListener(CHANGE_EVENT, handleLocalChange)
  }
}
