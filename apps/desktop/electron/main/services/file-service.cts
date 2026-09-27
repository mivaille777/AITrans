import {
  dialog,
  shell,
  type BrowserWindow,
} from "electron"
import { realpath, stat } from "node:fs/promises"
import path from "node:path"
import { fileURLToPath } from "node:url"

const KNOWLEDGE_EXTENSIONS = ["pdf", "docx", "txt", "md", "html", "htm"]

async function canonicalPath(candidate: string): Promise<string> {
  if (!path.isAbsolute(candidate)) {
    throw new Error("Local path must be absolute.")
  }
  return realpath(candidate)
}

export async function pickKnowledgeDocument(
  owner: BrowserWindow,
): Promise<string | null> {
  const result = await dialog.showOpenDialog(owner, {
    title: "Add document to Knowledge Library",
    properties: ["openFile"],
    filters: [
      {
        name: "Knowledge documents",
        extensions: KNOWLEDGE_EXTENSIONS,
      },
    ],
  })

  if (result.canceled || result.filePaths.length === 0) return null

  const selected = await canonicalPath(result.filePaths[0])
  const info = await stat(selected)
  if (!info.isFile()) {
    throw new Error("Selected knowledge resource is not a file.")
  }
  return selected
}

export async function pickAgentWorkspace(
  owner: BrowserWindow,
): Promise<string | null> {
  const result = await dialog.showOpenDialog(owner, {
    title: "Choose Agent Workspace",
    properties: ["openDirectory"],
  })

  if (result.canceled || result.filePaths.length === 0) return null

  const selected = await canonicalPath(result.filePaths[0])
  const info = await stat(selected)
  if (!info.isDirectory()) {
    throw new Error("Selected Agent workspace is not a directory.")
  }
  return selected
}

export async function openEvidenceSource(resourceUrl: string): Promise<void> {
  let parsed: URL
  try {
    parsed = new URL(resourceUrl)
  } catch {
    throw new Error("Evidence source URI is invalid.")
  }

  if (parsed.protocol !== "file:") {
    throw new Error("Only verified local file evidence can be opened.")
  }

  let candidate: string
  try {
    candidate = fileURLToPath(parsed)
  } catch {
    throw new Error("Evidence source URI is not a local file path.")
  }

  const selected = await canonicalPath(candidate)
  const info = await stat(selected)
  if (!info.isFile()) {
    throw new Error("Evidence source is not a file.")
  }

  const error = await shell.openPath(selected)
  if (error) {
    throw new Error(`Unable to open evidence source: ${error}`)
  }
}
