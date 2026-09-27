import { ipcMain } from "electron"

import { IPC_CHANNELS } from "../../shared/channels.cjs"
import {
  deleteCredential,
  getCredentialPreview,
  getCredentialStatus,
  saveCredential,
} from "../services/credential-service.cjs"
import {
  authorizedMainWindow,
  type MainWindowResolver,
} from "./ipc-auth.cjs"

function providerValue(value: unknown): string {
  if (typeof value !== "string" || !value.trim()) {
    throw new Error("Credential provider must be a non-empty string.")
  }
  return value
}

function apiKeyValue(value: unknown): string {
  if (typeof value !== "string") {
    throw new Error("API Key must be a string.")
  }
  return value
}

export function registerCredentialIpc(
  resolveMainWindow: MainWindowResolver,
): void {
  ipcMain.removeHandler(IPC_CHANNELS.credentialsStatus)
  ipcMain.handle(IPC_CHANNELS.credentialsStatus, (event, provider: unknown) => {
    authorizedMainWindow(event, resolveMainWindow)
    return getCredentialStatus(providerValue(provider))
  })

  ipcMain.removeHandler(IPC_CHANNELS.credentialsPreview)
  ipcMain.handle(IPC_CHANNELS.credentialsPreview, (event, provider: unknown) => {
    authorizedMainWindow(event, resolveMainWindow)
    return getCredentialPreview(providerValue(provider))
  })

  ipcMain.removeHandler(IPC_CHANNELS.credentialsSave)
  ipcMain.handle(
    IPC_CHANNELS.credentialsSave,
    async (event, provider: unknown, apiKey: unknown) => {
      authorizedMainWindow(event, resolveMainWindow)
      await saveCredential(providerValue(provider), apiKeyValue(apiKey))
    },
  )

  ipcMain.removeHandler(IPC_CHANNELS.credentialsDelete)
  ipcMain.handle(IPC_CHANNELS.credentialsDelete, async (event, provider: unknown) => {
    authorizedMainWindow(event, resolveMainWindow)
    await deleteCredential(providerValue(provider))
  })
}
