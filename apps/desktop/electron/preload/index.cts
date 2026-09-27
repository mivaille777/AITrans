import { contextBridge, ipcRenderer } from "electron"

import { IPC_CHANNELS } from "../shared/channels.cjs"

const api = {
  window: {
    show: () => ipcRenderer.invoke(IPC_CHANNELS.windowShow),
    hide: () => ipcRenderer.invoke(IPC_CHANNELS.windowHide),
    focus: () => ipcRenderer.invoke(IPC_CHANNELS.windowFocus),
    minimize: () => ipcRenderer.invoke(IPC_CHANNELS.windowMinimize),
    toggleMaximize: () =>
      ipcRenderer.invoke(IPC_CHANNELS.windowToggleMaximize) as Promise<boolean>,
    isMaximized: () =>
      ipcRenderer.invoke(IPC_CHANNELS.windowIsMaximized) as Promise<boolean>,
    close: () => ipcRenderer.invoke(IPC_CHANNELS.windowClose),
  },
  files: {
    pickKnowledgeDocument: () =>
      ipcRenderer.invoke(IPC_CHANNELS.filesPickKnowledgeDocument) as Promise<string | null>,
    pickAgentWorkspace: () =>
      ipcRenderer.invoke(IPC_CHANNELS.filesPickAgentWorkspace) as Promise<string | null>,
    openEvidenceSource: (resourceUrl: string) =>
      ipcRenderer.invoke(IPC_CHANNELS.filesOpenEvidenceSource, resourceUrl),
  },
  credentials: {
    getStatus: (provider: string) =>
      ipcRenderer.invoke(IPC_CHANNELS.credentialsStatus, provider) as Promise<{ configured: boolean }>,
    getPreview: (provider: string) =>
      ipcRenderer.invoke(IPC_CHANNELS.credentialsPreview, provider) as Promise<{ configured: boolean; masked: string }>,
    save: (provider: string, apiKey: string) =>
      ipcRenderer.invoke(IPC_CHANNELS.credentialsSave, provider, apiKey),
    delete: (provider: string) =>
      ipcRenderer.invoke(IPC_CHANNELS.credentialsDelete, provider),
  },
  overlay: {
    show: () => ipcRenderer.invoke(IPC_CHANNELS.overlayShow),
    hide: () => ipcRenderer.invoke(IPC_CHANNELS.overlayHide),
    focus: () => ipcRenderer.invoke(IPC_CHANNELS.overlayFocus),
    getPlacementContext: (reference?: { x: number; y: number } | null) =>
      ipcRenderer.invoke(IPC_CHANNELS.overlayPlacementContext, reference),
    setPosition: (position: { x: number; y: number }, animate: boolean) =>
      ipcRenderer.invoke(IPC_CHANNELS.overlaySetPosition, position, animate),
    resize: (size: { width: number; height: number }) =>
      ipcRenderer.invoke(IPC_CHANNELS.overlayResize, size),
    getPosition: () =>
      ipcRenderer.invoke(IPC_CHANNELS.overlayGetPosition),
    setAlwaysOnTop: (enabled: boolean) =>
      ipcRenderer.invoke(IPC_CHANNELS.overlaySetAlwaysOnTop, enabled),
    setClickThrough: (enabled: boolean) =>
      ipcRenderer.invoke(IPC_CHANNELS.overlaySetClickThrough, enabled),
    startDragging: async () => undefined,
    setVisualTheme: (theme: "light" | "dark") =>
      ipcRenderer.invoke(IPC_CHANNELS.overlaySetVisualTheme, theme),
    onVisualThemeChanged: async (callback: (theme: "light" | "dark") => void) => {
      const listener = (_event: Electron.IpcRendererEvent, payload: { theme?: string }) => {
        if (payload?.theme === "light" || payload?.theme === "dark") callback(payload.theme)
      }
      ipcRenderer.on(IPC_CHANNELS.eventOverlayVisualThemeChanged, listener)
      return () => ipcRenderer.removeListener(IPC_CHANNELS.eventOverlayVisualThemeChanged, listener)
    },
    onMoved: async (callback: (position: { x: number; y: number }) => void) => {
      const listener = (_event: Electron.IpcRendererEvent, payload: { x?: number; y?: number }) => {
        if (Number.isFinite(payload?.x) && Number.isFinite(payload?.y)) {
          callback({ x: Number(payload.x), y: Number(payload.y) })
        }
      }
      ipcRenderer.on(IPC_CHANNELS.eventOverlayMoved, listener)
      return () => ipcRenderer.removeListener(IPC_CHANNELS.eventOverlayMoved, listener)
    },
    notifyStateChanged: (contextId = "") =>
      ipcRenderer.invoke(IPC_CHANNELS.overlayNotifyStateChanged, contextId),
    onStateChanged: async (callback: (contextId: string) => void) => {
      const listener = (_event: Electron.IpcRendererEvent, payload: { contextId?: string }) => {
        callback(String(payload?.contextId ?? ""))
      }
      ipcRenderer.on(IPC_CHANNELS.eventOverlayStateChanged, listener)
      return () => ipcRenderer.removeListener(IPC_CHANNELS.eventOverlayStateChanged, listener)
    },
    notifyCompanionNavigation: (signal: { conversationId: string; handoffId: string }) =>
      ipcRenderer.invoke(IPC_CHANNELS.overlayNotifyCompanionNavigation, signal),
    onCompanionNavigation: async (
      callback: (signal: { conversationId: string; handoffId: string }) => void,
    ) => {
      const listener = (
        _event: Electron.IpcRendererEvent,
        payload: { conversationId?: string; handoffId?: string },
      ) => {
        const conversationId = String(payload?.conversationId ?? "").trim()
        if (!conversationId) return
        callback({
          conversationId,
          handoffId: String(payload?.handoffId ?? "").trim(),
        })
      }
      ipcRenderer.on(IPC_CHANNELS.eventCompanionNavigation, listener)
      return () => ipcRenderer.removeListener(IPC_CHANNELS.eventCompanionNavigation, listener)
    },
    notifyCompanionConversationChanged: (
      signal: { conversationId: string; kind: "updated" | "deleted" },
    ) => ipcRenderer.invoke(IPC_CHANNELS.overlayNotifyCompanionConversationChanged, signal),
    onCompanionConversationChanged: async (
      callback: (signal: { conversationId: string; kind: "updated" | "deleted" }) => void,
    ) => {
      const listener = (
        _event: Electron.IpcRendererEvent,
        payload: { conversationId?: string; kind?: string },
      ) => {
        const conversationId = String(payload?.conversationId ?? "").trim()
        if (!conversationId) return
        callback({
          conversationId,
          kind: payload?.kind === "deleted" ? "deleted" : "updated",
        })
      }
      ipcRenderer.on(IPC_CHANNELS.eventCompanionConversationChanged, listener)
      return () => ipcRenderer.removeListener(IPC_CHANNELS.eventCompanionConversationChanged, listener)
    },
  },
}

contextBridge.exposeInMainWorld("aiTransDesktop", api)
