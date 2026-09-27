/** @vitest-environment jsdom */

import { beforeEach, describe, expect, it, vi } from "vitest"

const mocks = vi.hoisted(() => ({
  startDragging: vi.fn(),
  setVisualTheme: vi.fn(),
  onVisualThemeChanged: vi.fn(),
}))

vi.mock("./index", () => ({
  desktop: {
    overlay: {
      startDragging: mocks.startDragging,
      setVisualTheme: mocks.setVisualTheme,
      onVisualThemeChanged: mocks.onVisualThemeChanged,
    },
  },
}))

import {
  applyOverlayNativeVisualTheme,
  applyOverlayThemeToDocument,
  startOverlayWindowDrag,
  subscribeOverlayVisualThemeEvents,
} from "./overlay-native-theme"

describe("overlay native visual theme bridge", () => {
  beforeEach(() => {
    mocks.startDragging.mockReset()
    mocks.setVisualTheme.mockReset()
    mocks.onVisualThemeChanged.mockReset()
    mocks.startDragging.mockResolvedValue(undefined)
    mocks.setVisualTheme.mockResolvedValue(undefined)
    mocks.onVisualThemeChanged.mockResolvedValue(() => undefined)
    delete document.documentElement.dataset.aitOverlayTheme
  })

  it("updates the overlay document theme without a native runtime", () => {
    applyOverlayThemeToDocument("light")
    expect(document.documentElement.dataset.aitOverlayTheme).toBe("light")
  })

  it("delegates light native theme updates through the desktop adapter", async () => {
    await applyOverlayNativeVisualTheme("light")
    expect(mocks.setVisualTheme).toHaveBeenCalledWith("light")
  })

  it("delegates dark native theme updates through the desktop adapter", async () => {
    await applyOverlayNativeVisualTheme("dark")
    expect(mocks.setVisualTheme).toHaveBeenCalledWith("dark")
  })

  it("delegates overlay dragging through the desktop adapter", async () => {
    await startOverlayWindowDrag()
    expect(mocks.startDragging).toHaveBeenCalledTimes(1)
  })

  it("delegates visual-theme subscriptions through the desktop adapter", async () => {
    const unsubscribe = vi.fn()
    const callback = vi.fn()
    mocks.onVisualThemeChanged.mockImplementation(async (nextCallback) => {
      nextCallback("light")
      return unsubscribe
    })

    const result = await subscribeOverlayVisualThemeEvents(callback)

    expect(callback).toHaveBeenCalledWith("light")
    expect(result).toBe(unsubscribe)
  })
})
