/** @vitest-environment jsdom */

import { beforeEach, describe, expect, it } from "vitest"

import {
  DEFAULT_OVERLAY_PREFERENCES,
  readOverlayPreferences,
  updateOverlayPreferences,
} from "./overlay-preferences"

const STORAGE_KEY = "aitrans.overlay.preferences.v3"
const PREVIOUS_STORAGE_KEY = "aitrans.overlay.preferences.v2"

describe("overlay appearance preferences", () => {
  beforeEach(() => {
    window.localStorage.clear()
  })

  it("uses the light Liquid Glass theme by default", () => {
    expect(DEFAULT_OVERLAY_PREFERENCES.theme).toBe("light")
    expect(readOverlayPreferences().theme).toBe("light")
  })

  it("persists an explicit dark theme selection", () => {
    const preferences = updateOverlayPreferences({ theme: "dark" })

    expect(preferences.theme).toBe("dark")
    expect(readOverlayPreferences().theme).toBe("dark")
  })

  it("migrates v2 preferences to the new light-theme default", () => {
    window.localStorage.setItem(
      PREVIOUS_STORAGE_KEY,
      JSON.stringify({
        positionMode: "custom_fixed_position",
        alwaysOnTop: false,
        locked: true,
        clickThrough: true,
        smartAutoDismiss: false,
        customPosition: { x: 120, y: 240 },
      }),
    )

    const migrated = readOverlayPreferences()

    expect(migrated).toMatchObject({
      theme: "light",
      positionMode: "custom_fixed_position",
      alwaysOnTop: false,
      locked: true,
      clickThrough: true,
      smartAutoDismiss: false,
      customPosition: { x: 120, y: 240 },
    })
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}").theme).toBe("light")
  })
})
