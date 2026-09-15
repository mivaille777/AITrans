import type { DesktopAdapter } from "../adapter"

let browserWindowMaximized = false

export const browserDesktopAdapter: DesktopAdapter = {
  runtime: "browser",
  files: {
    async pickKnowledgeDocument() {
      const path = window.prompt("Enter an absolute path to a local knowledge document:")
      return path?.trim() || null
    },
    async openEvidenceSource() {
      throw new Error("Opening local evidence files requires the desktop app.")
    },
  },
  window: {
    async show() {
      // Browser development mode has no native desktop window lifecycle.
    },
    async hide() {
      // Browser development mode has no native desktop window lifecycle.
    },
    async focus() {
      window.focus()
    },
    async minimize() {
      // Browser development mode cannot minimize the host browser window.
    },
    async toggleMaximize() {
      browserWindowMaximized = !browserWindowMaximized
      return browserWindowMaximized
    },
    async isMaximized() {
      return browserWindowMaximized
    },
    async close() {
      // Browser development mode cannot close the host browser window.
    },
  },
  overlay: {
    async show() {
      // Browser development mode has no native overlay window.
    },
    async hide() {
      // Browser development mode has no native overlay window.
    },
    async focus() {
      window.focus()
    },
    async place() {
      return null
    },
    async resize() {
      // Browser development mode cannot resize a native overlay window.
    },
    async getPosition() {
      return null
    },
    async setAlwaysOnTop() {
      // No-op outside a desktop runtime.
    },
    async setClickThrough() {
      // No-op outside a desktop runtime.
    },
    async onMoved() {
      return () => undefined
    },
    async notifyStateChanged() {
      // Polling remains the browser-development fallback.
    },
    async onStateChanged() {
      return () => undefined
    },
    async notifyCompanionNavigation() {
      // The backend handoff remains the browser-development fallback.
    },
    async onCompanionNavigation() {
      return () => undefined
    },
    async notifyCompanionConversationChanged() {
      // Browser development mode relies on normal query/refetch behavior.
    },
    async onCompanionConversationChanged() {
      return () => undefined
    },
  },
}
