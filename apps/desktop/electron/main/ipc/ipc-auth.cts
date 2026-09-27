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
