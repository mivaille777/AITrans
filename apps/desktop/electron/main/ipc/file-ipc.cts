import { ipcMain } from "electron"

import { IPC_CHANNELS } from "../../shared/channels.cjs"
import {
  openEvidenceSource,
  revealWorkspaceLocation,
  pickAgentWorkspace,
  pickKnowledgeDocument,
} from "../services/file-service.cjs"
import {
  authorizedMainWindow,
  type MainWindowResolver,
} from "./ipc-auth.cjs"

const MAX_RESOURCE_URL_LENGTH = 32_768

function validatedResourceUrl(value: unknown): string {
  if (typeof value !== "string") {
    throw new Error("Evidence source URI must be a string.")
  }

  const normalized = value.trim()
  if (!normalized || normalized.length > MAX_RESOURCE_URL_LENGTH) {
    throw new Error("Evidence source URI is invalid.")
  }

  return normalized
}

export function registerFileIpc(
  resolveMainWindow: MainWindowResolver,
): void {
  ipcMain.removeHandler(IPC_CHANNELS.filesRevealWorkspaceLocation)
  ipcMain.handle(IPC_CHANNELS.filesRevealWorkspaceLocation, async (event, resourceUrl: unknown) => {
    authorizedMainWindow(event, resolveMainWindow)
    await revealWorkspaceLocation(validatedResourceUrl(resourceUrl))
  })
  ipcMain.removeHandler(IPC_CHANNELS.filesPickKnowledgeDocument)
  ipcMain.handle(IPC_CHANNELS.filesPickKnowledgeDocument, (event) =>
    pickKnowledgeDocument(authorizedMainWindow(event, resolveMainWindow)),
  )

  ipcMain.removeHandler(IPC_CHANNELS.filesPickAgentWorkspace)
  ipcMain.handle(IPC_CHANNELS.filesPickAgentWorkspace, (event) =>
    pickAgentWorkspace(authorizedMainWindow(event, resolveMainWindow)),
  )

  ipcMain.removeHandler(IPC_CHANNELS.filesOpenEvidenceSource)
  ipcMain.handle(
    IPC_CHANNELS.filesOpenEvidenceSource,
    async (event, resourceUrl: unknown) => {
      authorizedMainWindow(event, resolveMainWindow)
      await openEvidenceSource(validatedResourceUrl(resourceUrl))
    },
  )
}
