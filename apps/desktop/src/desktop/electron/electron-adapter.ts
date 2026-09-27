import type { DesktopAdapter } from "../adapter"
import type { ElectronDesktopApi } from "./electron-api"

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
    place(mode, customPosition) {
      return bridge().overlay.place(mode, customPosition)
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
      return bridge().overlay.setClickThrough(enabled)
    },
    startDragging() {
      return bridge().overlay.startDragging()
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
