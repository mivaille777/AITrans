import type {
  BrowserWindow,
  IpcMainInvokeEvent,
} from "electron"

export type MainWindowResolver = () => BrowserWindow | null

export function authorizedMainWindow(
  event: IpcMainInvokeEvent,
  resolveMainWindow: MainWindowResolver,
): BrowserWindow {
  const mainWindow = resolveMainWindow()
  if (!mainWindow || mainWindow.isDestroyed()) {
    throw new Error("AITrans main window is unavailable.")
  }

  if (event.sender !== mainWindow.webContents) {
    throw new Error("Unauthorized desktop IPC sender.")
  }

  return mainWindow
}


export function authorizedDesktopWindow(
  event: IpcMainInvokeEvent,
  resolveMainWindow: MainWindowResolver,
  resolveOverlayWindow: MainWindowResolver,
): BrowserWindow {
  const candidates = [resolveMainWindow(), resolveOverlayWindow()]
    .filter((window): window is BrowserWindow => Boolean(window && !window.isDestroyed()))

  const matched = candidates.find((window) => event.sender === window.webContents)
  if (!matched) {
    throw new Error("Unauthorized desktop IPC sender.")
  }
  return matched
}

export function desktopWindowKind(
  event: IpcMainInvokeEvent,
  resolveMainWindow: MainWindowResolver,
  resolveOverlayWindow: MainWindowResolver,
): "main" | "overlay" {
  const mainWindow = resolveMainWindow()
  if (mainWindow && !mainWindow.isDestroyed() && event.sender === mainWindow.webContents) {
    return "main"
  }

  const overlayWindow = resolveOverlayWindow()
  if (overlayWindow && !overlayWindow.isDestroyed() && event.sender === overlayWindow.webContents) {
    return "overlay"
  }

  throw new Error("Unauthorized desktop IPC sender.")
}
