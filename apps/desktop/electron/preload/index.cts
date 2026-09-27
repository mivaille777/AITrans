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
    show: async () => undefined,
    hide: async () => undefined,
    focus: async () => undefined,
    place: async () => null,
    resize: async () => undefined,
    getPosition: async () => null,
    setAlwaysOnTop: async () => undefined,
    setClickThrough: async () => undefined,
    startDragging: async () => undefined,
    setVisualTheme: async () => undefined,
    onVisualThemeChanged: async () => () => undefined,
    onMoved: async () => () => undefined,
    notifyStateChanged: async () => undefined,
    onStateChanged: async () => () => undefined,
    notifyCompanionNavigation: async () => undefined,
    onCompanionNavigation: async () => () => undefined,
    notifyCompanionConversationChanged: async () => undefined,
    onCompanionConversationChanged: async () => () => undefined,
  },
}

contextBridge.exposeInMainWorld("aiTransDesktop", api)
