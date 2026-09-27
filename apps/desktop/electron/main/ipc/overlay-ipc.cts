import {
  ipcMain,
  type BrowserWindow,
  type IpcMainInvokeEvent,
} from "electron"

import { IPC_CHANNELS } from "../../shared/channels.cjs"
import { OverlayManager, type OverlayPoint, type OverlaySize } from "../overlay-manager.cjs"
import {
  authorizedDesktopWindow,
  desktopWindowKind,
  type MainWindowResolver,
} from "./ipc-auth.cjs"

type OverlayWindowResolver = () => BrowserWindow | null

function finiteNumber(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(label + " must be a finite number.")
  }
  return value
}

function pointValue(value: unknown, optional = false): OverlayPoint | null {
  if (value == null && optional) return null
  if (!value || typeof value !== "object") {
    throw new Error("Overlay position must be an object.")
  }
  const candidate = value as Record<string, unknown>
  return {
    x: finiteNumber(candidate.x, "Overlay x"),
    y: finiteNumber(candidate.y, "Overlay y"),
  }
}

function sizeValue(value: unknown): OverlaySize {
  if (!value || typeof value !== "object") {
    throw new Error("Overlay size must be an object.")
  }
  const candidate = value as Record<string, unknown>
  const width = finiteNumber(candidate.width, "Overlay width")
  const height = finiteNumber(candidate.height, "Overlay height")
  if (width < 1 || height < 1 || width > 4096 || height > 4096) {
    throw new Error("Overlay size is outside the supported range.")
  }
  return { width, height }
}

function booleanValue(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(label + " must be a boolean.")
  }
  return value
}

function shortString(value: unknown, label: string, maximum = 512): string {
  if (typeof value !== "string") {
    throw new Error(label + " must be a string.")
  }
  const normalized = value.trim()
  if (normalized.length > maximum) {
    throw new Error(label + " is too long.")
  }
  return normalized
}

export function registerOverlayIpc(
  resolveMainWindow: MainWindowResolver,
  resolveOverlayWindow: OverlayWindowResolver,
  manager: OverlayManager,
): void {
  const authorize = (event: IpcMainInvokeEvent) =>
    authorizedDesktopWindow(event, resolveMainWindow, resolveOverlayWindow)

  const register = (
    channel: string,
    handler: (event: IpcMainInvokeEvent, ...args: unknown[]) => unknown | Promise<unknown>,
  ) => {
    ipcMain.removeHandler(channel)
    ipcMain.handle(channel, (event, ...args) => {
      authorize(event)
      return handler(event, ...args)
    })
  }

  register(IPC_CHANNELS.overlayShow, () => manager.show())
  register(IPC_CHANNELS.overlayHide, () => manager.hide())
  register(IPC_CHANNELS.overlayFocus, () => manager.focus())
  register(IPC_CHANNELS.overlayPlacementContext, (_event, reference) =>
    manager.placementContext(pointValue(reference, true)),
  )
  register(IPC_CHANNELS.overlaySetPosition, (_event, position, animate) =>
    manager.setPosition(
      pointValue(position) as OverlayPoint,
      booleanValue(animate, "Overlay animate"),
    ),
  )
  register(IPC_CHANNELS.overlayResize, (_event, size) =>
    manager.resize(sizeValue(size)),
  )
  register(IPC_CHANNELS.overlayGetPosition, () => manager.getPosition())
  register(IPC_CHANNELS.overlaySetAlwaysOnTop, (_event, enabled) =>
    manager.setAlwaysOnTop(booleanValue(enabled, "Overlay always-on-top")),
  )
  register(IPC_CHANNELS.overlaySetClickThrough, (_event, enabled) =>
    manager.setClickThrough(booleanValue(enabled, "Overlay click-through")),
  )
  register(IPC_CHANNELS.overlaySetVisualTheme, (_event, theme) => {
    const normalized = shortString(theme, "Overlay visual theme", 16)
    if (normalized !== "light" && normalized !== "dark") {
      throw new Error("Unsupported overlay visual theme.")
    }
    manager.send(IPC_CHANNELS.eventOverlayVisualThemeChanged, { theme: normalized })
  })
  register(IPC_CHANNELS.overlayNotifyStateChanged, (_event, contextId) => {
    manager.send(IPC_CHANNELS.eventOverlayStateChanged, {
      contextId: shortString(contextId ?? "", "Overlay context id"),
    })
  })
  register(IPC_CHANNELS.overlayNotifyCompanionNavigation, (_event, signal) => {
    if (!signal || typeof signal !== "object") {
      throw new Error("Companion navigation signal is invalid.")
    }
    const value = signal as Record<string, unknown>
    const payload = {
      conversationId: shortString(value.conversationId, "Conversation id"),
      handoffId: shortString(value.handoffId ?? "", "Handoff id"),
    }
    if (!payload.conversationId) {
      throw new Error("Conversation id is required.")
    }
    const mainWindow = resolveMainWindow()
    if (mainWindow && !mainWindow.webContents.isDestroyed()) {
      mainWindow.webContents.send(IPC_CHANNELS.eventCompanionNavigation, payload)
    }
  })
  register(IPC_CHANNELS.overlayNotifyCompanionConversationChanged, (event, signal) => {
    if (!signal || typeof signal !== "object") {
      throw new Error("Companion conversation signal is invalid.")
    }
    const value = signal as Record<string, unknown>
    const conversationId = shortString(value.conversationId, "Conversation id")
    const kind = value.kind === "deleted" ? "deleted" : "updated"
    if (!conversationId) {
      throw new Error("Conversation id is required.")
    }

    const sender = desktopWindowKind(event, resolveMainWindow, resolveOverlayWindow)
    const target = sender === "main" ? resolveOverlayWindow() : resolveMainWindow()
    if (target && !target.webContents.isDestroyed()) {
      target.webContents.send(IPC_CHANNELS.eventCompanionConversationChanged, {
        conversationId,
        kind,
      })
    }
  })

  manager.onMoved((position) => {
    manager.send(IPC_CHANNELS.eventOverlayMoved, position)
  })
}
