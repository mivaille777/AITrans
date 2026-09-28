import { spawnSync } from "node:child_process"
import path from "node:path"

import { app, type BrowserWindow } from "electron"

import { registerAppSchemePrivileges, installAppProtocol } from "./app-protocol.cjs"
import { registerCredentialIpc } from "./ipc/credential-ipc.cjs"
import { registerFileIpc } from "./ipc/file-ipc.cjs"
import { registerMainWindowIpc } from "./ipc/window-ipc.cjs"
import { registerOverlayIpc } from "./ipc/overlay-ipc.cjs"
import { OverlayManager } from "./overlay-manager.cjs"
import { BackendProcessManager } from "./services/backend-process-manager.cjs"
import { UpdateManager } from "./services/update-manager.cjs"
import { createMainWindow } from "./window-manager.cjs"

const ELECTRON_RUNTIME_SMOKE_ARGUMENT = "--electron-runtime-smoke-test"

const SQUIRREL_INSTALL_ARGUMENTS = new Set([
  "--squirrel-install",
  "--squirrel-updated",
])
const SQUIRREL_UNINSTALL_ARGUMENT = "--squirrel-uninstall"
const SQUIRREL_OBSOLETE_ARGUMENT = "--squirrel-obsolete"

function squirrelLifecycleArgument(): string | null {
  if (process.platform !== "win32") return null
  return process.argv.find((argument) =>
    SQUIRREL_INSTALL_ARGUMENTS.has(argument) ||
    argument === SQUIRREL_UNINSTALL_ARGUMENT ||
    argument === SQUIRREL_OBSOLETE_ARGUMENT
  ) ?? null
}

function runSquirrelShortcutCommand(action: "--createShortcut" | "--removeShortcut"): void {
  const updateExecutable = path.resolve(path.dirname(process.execPath), "..", "Update.exe")
  const executableName = path.basename(process.execPath)
  const result = spawnSync(updateExecutable, [action, executableName], {
    windowsHide: true,
    stdio: "ignore",
    timeout: 10000,
  })
  if (result.error) {
    console.error(`Squirrel shortcut lifecycle failed for ${action}.`, result.error)
  } else if (result.status !== 0) {
    console.error(`Squirrel shortcut lifecycle returned status ${result.status} for ${action}.`)
  }
}

function handleSquirrelLifecycle(argument: string): void {
  if (SQUIRREL_INSTALL_ARGUMENTS.has(argument)) {
    runSquirrelShortcutCommand("--createShortcut")
  } else if (argument === SQUIRREL_UNINSTALL_ARGUMENT) {
    runSquirrelShortcutCommand("--removeShortcut")
  }
  app.quit()
}

async function runPackagedRuntimeSmoke(): Promise<void> {
  const backendManager = new BackendProcessManager()
  const updateManager = new UpdateManager(() => backendManager.stopNow())
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
      updateManager.start()

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
    updateManager.stop()
    backendManager.stopNow()
  })

  app.on("window-all-closed", () => {
    if (process.platform !== "darwin") {
      app.quit()
    }
  })
}

const squirrelArgument = squirrelLifecycleArgument()

if (squirrelArgument) {
  handleSquirrelLifecycle(squirrelArgument)
} else if (process.argv.includes(ELECTRON_RUNTIME_SMOKE_ARGUMENT)) {
  void app.whenReady().then(runPackagedRuntimeSmoke)
} else {
  startApplication()
}
