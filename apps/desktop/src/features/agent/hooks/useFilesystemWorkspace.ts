import { useCallback, useEffect, useState } from "react"

import {
  createFilesystemWorkspace,
  getFilesystemWorkspace,
  revokeFilesystemWorkspace,
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

  /* oxlint-disable react-hooks/set-state-in-effect -- feature toggles intentionally reset and rehydrate bounded workspace state */
  useEffect(() => {
    if (!enabled) {
      setLoading(false)
      setChoosing(false)
      setError("")
      return
    }

    const workspaceId = readActiveWorkspaceId()
    if (!workspaceId) {
      setWorkspace(null)
      setLoading(false)
      return
    }

    setLoading(true)
    setError("")
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
  /* oxlint-enable react-hooks/set-state-in-effect */

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
    } catch {
      setError("Filesystem workspace is unavailable.")
    } finally {
      setChoosing(false)
    }
  }, [choosing, enabled])

  const clearWorkspace = useCallback(async () => {
    if (choosing) return
    const workspaceId = workspace?.workspace_id ?? readActiveWorkspaceId()
    if (!workspaceId) {
      persistActiveWorkspaceId("")
      setWorkspace(null)
      setError("")
      return
    }

    setChoosing(true)
    setError("")
    try {
      const result = await revokeFilesystemWorkspace(workspaceId)
      if (!result.revoked) {
        throw new Error("Workspace revocation was not confirmed.")
      }
      persistActiveWorkspaceId("")
      setWorkspace(null)
    } catch {
      setError("Filesystem workspace access could not be revoked.")
    } finally {
      setChoosing(false)
    }
  }, [choosing, workspace?.workspace_id])

  return {
    workspace: enabled ? workspace : null,
    loading: enabled ? loading : false,
    choosing: enabled ? choosing : false,
    error: enabled ? error : "",
    chooseWorkspace,
    clearWorkspace,
  }
}
