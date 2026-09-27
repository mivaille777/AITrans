/** @vitest-environment jsdom */

import { afterEach, describe, expect, it, vi } from "vitest"

import type { ElectronDesktopApi } from "./electron/electron-api"

function createBridge(): ElectronDesktopApi {
  const noop = async () => undefined
  const unsubscribe = async () => () => undefined

  return {
    window: {
      show: noop,
      hide: noop,
      focus: noop,
      minimize: noop,
      toggleMaximize: async () => false,
      isMaximized: async () => false,
      close: noop,
    },
    files: {
      pickKnowledgeDocument: async () => null,
      pickAgentWorkspace: async () => null,
      openEvidenceSource: noop,
    },
    credentials: {
      getStatus: async () => ({ configured: false }),
      getPreview: async () => ({ configured: false, masked: "" }),
      save: noop,
      delete: noop,
    },
    overlay: {
      show: noop,
      hide: noop,
      focus: noop,
      getPlacementContext: async () => ({
        cursor: { x: 0, y: 0 },
        windowSize: { width: 420, height: 190 },
        workArea: { x: 0, y: 0, width: 1920, height: 1080 },
        visible: false,
      }),
      setPosition: noop,
      resize: noop,
      getPosition: async () => null,
      setAlwaysOnTop: noop,
      setClickThrough: noop,
      startDragging: noop,
      setVisualTheme: noop,
      onVisualThemeChanged: unsubscribe,
      onMoved: unsubscribe,
      notifyStateChanged: noop,
      onStateChanged: unsubscribe,
      notifyCompanionNavigation: noop,
      onCompanionNavigation: unsubscribe,
      notifyCompanionConversationChanged: noop,
      onCompanionConversationChanged: unsubscribe,
    },
  }
}

describe("desktop runtime selection", () => {
  afterEach(() => {
    delete window.aiTransDesktop
    delete (window as unknown as Record<string, unknown>).__TAURI_INTERNALS__
    vi.resetModules()
  })

  it("prefers Electron when the preload bridge is present", async () => {
    window.aiTransDesktop = createBridge()

    const { desktop } = await import("./index")

    expect(desktop.runtime).toBe("electron")
  })

  it("falls back to the browser adapter without a desktop bridge", async () => {
    const { desktop } = await import("./index")

    expect(desktop.runtime).toBe("browser")
  })
})
