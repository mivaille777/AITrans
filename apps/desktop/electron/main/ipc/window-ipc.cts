import {
  ipcMain,
  type BrowserWindow,
} from "electron"

import { IPC_CHANNELS } from "../../shared/channels.cjs"
import {
  authorizedMainWindow,
  type MainWindowResolver,
} from "./ipc-auth.cjs"

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
