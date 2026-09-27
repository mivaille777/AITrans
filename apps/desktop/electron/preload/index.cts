import { contextBridge, ipcRenderer } from "electron"

import { IPC_CHANNELS } from "../shared/channels.cjs"

function unavailable(capability: string): never {
  throw new Error(`${capability} is not available in the Stage 2 Electron shell yet.`)
}

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
    pickKnowledgeDocument: async () => null,
    pickAgentWorkspace: async () => null,
    openEvidenceSource: async () => unavailable("Evidence source opening"),
  },
  credentials: {
    getStatus: async () => ({ configured: false }),
    getPreview: async () => ({ configured: false, masked: "" }),
    save: async () => unavailable("Credential storage"),
    delete: async () => unavailable("Credential storage"),
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
