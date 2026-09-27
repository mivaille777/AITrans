import {
  ipcMain,
  type BrowserWindow,
  type IpcMainInvokeEvent,
} from "electron"

import { IPC_CHANNELS } from "../../shared/channels.cjs"

type MainWindowResolver = () => BrowserWindow | null

function authorizedMainWindow(
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

export function registerMainWindowIpc(
  resolveMainWindow: MainWindowResolver,
): void {
  const register = (
    channel: string,
    handler: (window: BrowserWindow) => unknown | Promise<unknown>,
  ) => {
    ipcMain.removeHandler(channel)
    ipcMain.handle(channel, (event) =>
      handler(authorizedMainWindow(event, resolveMainWindow)),
    )
  }

  register(IPC_CHANNELS.windowShow, (window) => {
    window.show()
  })

  register(IPC_CHANNELS.windowHide, (window) => {
    window.hide()
  })

  register(IPC_CHANNELS.windowFocus, (window) => {
    window.show()
    window.focus()
  })

  register(IPC_CHANNELS.windowMinimize, (window) => {
    window.minimize()
  })

  register(IPC_CHANNELS.windowToggleMaximize, (window) => {
    if (window.isMaximized()) {
      window.unmaximize()
      return false
    }
    window.maximize()
    return true
  })

  register(IPC_CHANNELS.windowIsMaximized, (window) =>
    window.isMaximized(),
  )

  register(IPC_CHANNELS.windowClose, (window) => {
    window.close()
  })
}
