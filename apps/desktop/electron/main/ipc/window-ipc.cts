import {
  ipcMain,
  type BrowserWindow,
} from "electron"

import { IPC_CHANNELS } from "../../shared/channels.cjs"
import {
  authorizedMainWindow,
  type MainWindowResolver,
} from "./ipc-auth.cjs"
import {
  getWindowCloseBehavior,
  isWindowCloseBehavior,
  setWindowCloseBehavior,
} from "../services/window-preferences.cjs"

export function registerMainWindowIpc(
  resolveMainWindow: MainWindowResolver,
): void {
  const register = (
    channel: string,
    handler: (window: BrowserWindow, ...args: unknown[]) => unknown | Promise<unknown>,
  ) => {
    ipcMain.removeHandler(channel)
    ipcMain.handle(channel, (event, ...args) =>
      handler(authorizedMainWindow(event, resolveMainWindow), ...args),
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

  register(IPC_CHANNELS.windowGetCloseBehavior, () => getWindowCloseBehavior())

  register(IPC_CHANNELS.windowSetCloseBehavior, (_window, behavior) => {
    if (!isWindowCloseBehavior(behavior)) {
      throw new TypeError("Window close behavior is invalid.")
    }
    setWindowCloseBehavior(behavior)
  })
}
