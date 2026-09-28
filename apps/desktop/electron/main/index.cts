import { app, type BrowserWindow } from "electron"

import { registerAppSchemePrivileges, installAppProtocol } from "./app-protocol.cjs"
import { registerCredentialIpc } from "./ipc/credential-ipc.cjs"
import { registerFileIpc } from "./ipc/file-ipc.cjs"
import { registerMainWindowIpc } from "./ipc/window-ipc.cjs"
import { registerOverlayIpc } from "./ipc/overlay-ipc.cjs"
import { OverlayManager } from "./overlay-manager.cjs"
import { BackendProcessManager } from "./services/backend-process-manager.cjs"
import { createMainWindow } from "./window-manager.cjs"

const ELECTRON_RUNTIME_SMOKE_ARGUMENT = "--electron-runtime-smoke-test"

const SQUIRREL_LIFECYCLE_ARGUMENTS = new Set([
  "--squirrel-install",
  "--squirrel-updated",
  "--squirrel-uninstall",
  "--squirrel-obsolete",
])

function isSquirrelLifecycleLaunch(): boolean {
  return process.platform === "win32" &&
    process.argv.some((argument) => SQUIRREL_LIFECYCLE_ARGUMENTS.has(argument))
}

async function runPackagedRuntimeSmoke(): Promise<void> {
  const backendManager = new BackendProcessManager()
  try {
    await backendManager.start()
    const status = backendManager.status()
    if (status.state !== "ready") {
      throw new Error("Packaged Electron backend did not reach owned ready state.")
    }
    console.log("AITrans packaged Electron runtime smoke test passed.")
    backendManager.stopNow()
    app.exit(0)
  } catch (error: unknown) {
    backendManager.stopNow()
    console.error("AITrans packaged Electron runtime smoke test failed.", error)
    app.exit(1)
  }
}

function startApplication(): void {
  registerAppSchemePrivileges()

  if (process.platform === "win32") {
    app.setAppUserModelId("com.squirrel.AITrans.AITrans")
  }

  let mainWindow: BrowserWindow | null = null
  const overlayManager = new OverlayManager()
  const backendManager = new BackendProcessManager()

  async function ensureMainWindow(): Promise<BrowserWindow> {
    if (mainWindow && !mainWindow.isDestroyed()) {
      return mainWindow
    }

    mainWindow = await createMainWindow()
    mainWindow.on("closed", () => {
      mainWindow = null
      void overlayManager.destroy()
    })
    return mainWindow
  }

  registerMainWindowIpc(() => mainWindow)
  registerFileIpc(() => mainWindow)
  registerCredentialIpc(() => mainWindow)
  registerOverlayIpc(
    () => mainWindow,
    () => overlayManager.getWindow(),
    overlayManager,
  )

  void app.whenReady()
    .then(async () => {
      await installAppProtocol()

      void backendManager.start().catch((error: unknown) => {
        const message = error instanceof Error ? error.message : "Unknown backend startup error."
        console.error("AITrans backend startup failed:", message)
      })

      await ensureMainWindow()
      await overlayManager.ensureWindow()

      app.on("activate", () => {
        void Promise.all([
          ensureMainWindow(),
          overlayManager.ensureWindow(),
        ]).then(([window]) => {
          window.show()
          window.focus()
        })
      })
    })
    .catch((error: unknown) => {
      console.error("AITrans Electron startup failed.", error)
      app.exit(1)
    })

  app.on("before-quit", () => {
    backendManager.stopNow()
  })

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") {
      app.quit()
    }
  })
}

if (isSquirrelLifecycleLaunch()) {
  app.quit()
} else if (process.argv.includes(ELECTRON_RUNTIME_SMOKE_ARGUMENT)) {
  void app.whenReady().then(runPackagedRuntimeSmoke)
} else {
  startApplication()
}
