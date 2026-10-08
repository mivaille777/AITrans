import type { DesktopAdapter } from "../adapter"
import { computeOverlayPosition } from "../overlay-positioning"
import type { ElectronDesktopApi } from "./electron-api"

const OVERLAY_INTERACTIVE_DATASET_KEY = "aitOverlayInteractive"

function overlayRequiresPointerInteraction(): boolean {
  return document.documentElement.dataset[OVERLAY_INTERACTIVE_DATASET_KEY] === "true"
}

function bridge(): ElectronDesktopApi {
  const api = window.aiTransDesktop
  if (!api) {
    throw new Error("Electron desktop bridge is unavailable.")
  }
  return api
}

export const electronDesktopAdapter: DesktopAdapter = {
  runtime: "electron",
  credentials: {
    isAvailable() {
      return typeof window !== "undefined" && Boolean(window.aiTransDesktop)
    },
    getStatus(provider) {
      return bridge().credentials.getStatus(provider)
    },
    getPreview(provider) {
      return bridge().credentials.getPreview(provider)
    },
    save(provider, apiKey) {
      return bridge().credentials.save(provider, apiKey)
    },
    delete(provider) {
      return bridge().credentials.delete(provider)
    },
  },
  files: {
    pickKnowledgeDocument() {
      return bridge().files.pickKnowledgeDocument()
    },
    pickAgentWorkspace() {
      return bridge().files.pickAgentWorkspace()
    },
    openEvidenceSource(resourceUrl) {
      return bridge().files.openEvidenceSource(resourceUrl)
    },
    async revealWorkspaceLocation(resourceUrl) {
      const reveal = bridge().files.revealWorkspaceLocation
      if (!reveal) throw new Error("请重启桌面程序以使用文件定位。")
      await reveal(resourceUrl)
    },
  },
  window: {
    show() {
      return bridge().window.show()
    },
    hide() {
      return bridge().window.hide()
    },
    focus() {
      return bridge().window.focus()
    },
    minimize() {
      return bridge().window.minimize()
    },
    toggleMaximize() {
      return bridge().window.toggleMaximize()
    },
    isMaximized() {
      return bridge().window.isMaximized()
    },
    close() {
      return bridge().window.close()
    },
    getCloseBehavior() {
      return bridge().window.getCloseBehavior()
    },
    setCloseBehavior(behavior) {
      return bridge().window.setCloseBehavior(behavior)
    },
  },
  overlay: {
    show() {
      return bridge().overlay.show()
    },
    hide() {
      return bridge().overlay.hide()
    },
    focus() {
      return bridge().overlay.focus()
    },
    async place(mode, customPosition) {
      const reference =
        mode === "custom_fixed_position" && customPosition
          ? customPosition
          : null
      const context = await bridge().overlay.getPlacementContext(reference)
      const position = computeOverlayPosition({
        mode,
        cursor: context.cursor,
        windowSize: context.windowSize,
        workArea: context.workArea,
        customPosition,
      })
      await bridge().overlay.setPosition(
        position,
        mode === "mouse_follow" && context.visible,
      )
      return position
    },
    resize(size) {
      return bridge().overlay.resize(size)
    },
    getPosition() {
      return bridge().overlay.getPosition()
    },
    setAlwaysOnTop(enabled) {
      return bridge().overlay.setAlwaysOnTop(enabled)
    },
    setClickThrough(enabled) {
      const effectiveClickThrough =
        enabled && !overlayRequiresPointerInteraction()
      return bridge().overlay.setClickThrough(effectiveClickThrough)
    },
    async startDragging() {
      // Electron uses CSS app-region dragging for frameless windows.
    },
    setVisualTheme(theme) {
      return bridge().overlay.setVisualTheme(theme)
    },
    onVisualThemeChanged(callback) {
      return bridge().overlay.onVisualThemeChanged(callback)
    },
    onMoved(callback) {
      return bridge().overlay.onMoved(callback)
    },
    notifyStateChanged(contextId) {
      return bridge().overlay.notifyStateChanged(contextId)
    },
    onStateChanged(callback) {
      return bridge().overlay.onStateChanged(callback)
    },
    notifyCompanionNavigation(signal) {
      return bridge().overlay.notifyCompanionNavigation(signal)
    },
    onCompanionNavigation(callback) {
      return bridge().overlay.onCompanionNavigation(callback)
    },
    notifyCompanionConversationChanged(signal) {
      return bridge().overlay.notifyCompanionConversationChanged(signal)
    },
    onCompanionConversationChanged(callback) {
      return bridge().overlay.onCompanionConversationChanged(callback)
    },
  },
}
