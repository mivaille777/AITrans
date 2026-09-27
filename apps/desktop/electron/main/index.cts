import { app, type BrowserWindow } from "electron"

import { registerMainWindowIpc } from "./ipc/window-ipc.cjs"
import { createMainWindow } from "./window-manager.cjs"

let mainWindow: BrowserWindow | null = null

async function ensureMainWindow(): Promise<BrowserWindow> {
  if (mainWindow && !mainWindow.isDestroyed()) {
    return mainWindow
  }

  mainWindow = await createMainWindow()
  mainWindow.on("closed", () => {
    mainWindow = null
  })
  return mainWindow
}

registerMainWindowIpc(() => mainWindow)

void app.whenReady()
  .then(async () => {
    await ensureMainWindow()

    app.on("activate", () => {
      void ensureMainWindow().then((window) => {
        window.show()
        window.focus()
      })
    })
  })
  .catch((error: unknown) => {
    console.error("AITrans Electron startup failed.", error)
    app.exit(1)
  })

app.on("window-all-closed", () => {
  if (process.platform !== "darwin") {
    app.quit()
  }
})
