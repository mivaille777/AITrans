import { useCallback, useEffect, useState } from "react"

import {
  createFilesystemWorkspace,
  getFilesystemWorkspace,
  type FilesystemWorkspace,
} from "../../../api/filesystem-workspaces"
import { desktop } from "../../../desktop"

const ACTIVE_WORKSPACE_KEY = "aitrans.agent.filesystemWorkspaceId"

function readActiveWorkspaceId(): string {
  if (typeof window === "undefined") return ""
  return window.localStorage.getItem(ACTIVE_WORKSPACE_KEY)?.trim() ?? ""
}

function persistActiveWorkspaceId(workspaceId: string): void {
  if (typeof window === "undefined") return
  if (workspaceId) window.localStorage.setItem(ACTIVE_WORKSPACE_KEY, workspaceId)
  else window.localStorage.removeItem(ACTIVE_WORKSPACE_KEY)
}

export function useFilesystemWorkspace(enabled = true) {
  const [workspace, setWorkspace] = useState<FilesystemWorkspace | null>(null)
  const [loading, setLoading] = useState(() => enabled && Boolean(readActiveWorkspaceId()))
  const [choosing, setChoosing] = useState(false)
  const [error, setError] = useState("")

  useEffect(() => {
    if (!enabled) return
    const workspaceId = readActiveWorkspaceId()
    if (!workspaceId) return

    let disposed = false
    void getFilesystemWorkspace(workspaceId)
      .then((next) => {
        if (disposed) return
        if (next.status !== "active") {
          persistActiveWorkspaceId("")
          setWorkspace(null)
          return
        }
        setWorkspace(next)
      })
      .catch(() => {
        if (disposed) return
        persistActiveWorkspaceId("")
        setWorkspace(null)
      })
      .finally(() => {
        if (!disposed) setLoading(false)
      })

    return () => {
      disposed = true
    }
  }, [enabled])

  const chooseWorkspace = useCallback(async () => {
    if (!enabled || choosing) return
    setChoosing(true)
    setError("")
    try {
      const path = await desktop.files.pickAgentWorkspace()
      if (!path) return
      const next = await createFilesystemWorkspace(path)
      if (next.status !== "active") {
        throw new Error("Selected workspace is not available.")
      }
      persistActiveWorkspaceId(next.workspace_id)
      setWorkspace(next)
    } catch (chooseError) {
      setError(
        chooseError instanceof Error
          ? chooseError.message
          : "Unable to register the filesystem workspace.",
      )
    } finally {
      setChoosing(false)
    }
  }, [choosing, enabled])

  const clearWorkspace = useCallback(() => {
    persistActiveWorkspaceId("")
    setWorkspace(null)
    setError("")
  }, [])

  return {
    workspace: enabled ? workspace : null,
    loading: enabled ? loading : false,
    choosing,
    error,
    chooseWorkspace,
    clearWorkspace,
  }
}
