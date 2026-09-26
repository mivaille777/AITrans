// @vitest-environment jsdom

import { act, renderHook, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import {
  createFilesystemWorkspace,
  getFilesystemWorkspace,
} from "../../../api/filesystem-workspaces"
import { desktop } from "../../../desktop"
import { useFilesystemWorkspace } from "./useFilesystemWorkspace"

vi.mock("../../../api/filesystem-workspaces", () => ({
  createFilesystemWorkspace: vi.fn(),
  getFilesystemWorkspace: vi.fn(),
}))

vi.mock("../../../desktop", () => ({
  desktop: {
    files: {
      pickAgentWorkspace: vi.fn(),
    },
  },
}))

const workspace = {
  workspace_id: "fsw-123",
  display_name: "AITrans",
  readable: true,
  writable: false,
  status: "active" as const,
  created_at: "",
  last_used_at: "",
}

afterEach(() => {
  window.localStorage.clear()
  vi.clearAllMocks()
})

describe("useFilesystemWorkspace", () => {
  it("does not load workspace authority while the feature is disabled", () => {
    window.localStorage.setItem("aitrans.agent.filesystemWorkspaceId", "fsw-123")

    const { result } = renderHook(() => useFilesystemWorkspace(false))

    expect(result.current.workspace).toBeNull()
    expect(result.current.loading).toBe(false)
    expect(result.current.choosing).toBe(false)
    expect(result.current.error).toBe("")
    expect(getFilesystemWorkspace).not.toHaveBeenCalled()
  })

  it("rehydrates the active workspace when the feature is enabled", async () => {
    window.localStorage.setItem("aitrans.agent.filesystemWorkspaceId", "fsw-123")
    vi.mocked(getFilesystemWorkspace).mockResolvedValue(workspace)

    const { result } = renderHook(() => useFilesystemWorkspace(true))

    expect(result.current.loading).toBe(true)
    await waitFor(() => expect(result.current.workspace?.workspace_id).toBe("fsw-123"))
    expect(result.current.loading).toBe(false)
  })

  it("persists only the backend workspace id after choosing a host folder", async () => {
    vi.mocked(desktop.files.pickAgentWorkspace).mockResolvedValue("D:\\Private\\AITrans")
    vi.mocked(createFilesystemWorkspace).mockResolvedValue(workspace)

    const { result } = renderHook(() => useFilesystemWorkspace(true))

    await act(async () => {
      await result.current.chooseWorkspace()
    })

    expect(createFilesystemWorkspace).toHaveBeenCalledWith("D:\\Private\\AITrans")
    expect(window.localStorage.getItem("aitrans.agent.filesystemWorkspaceId")).toBe("fsw-123")
    expect(JSON.stringify({ ...window.localStorage })).not.toContain("D:\\Private\\AITrans")
  })

  it("removes stale ids when backend authority rejects the saved workspace", async () => {
    window.localStorage.setItem("aitrans.agent.filesystemWorkspaceId", "fsw-stale")
    vi.mocked(getFilesystemWorkspace).mockRejectedValue(new Error("not found"))

    const { result } = renderHook(() => useFilesystemWorkspace(true))

    await waitFor(() => expect(result.current.loading).toBe(false))
    expect(result.current.workspace).toBeNull()
    expect(window.localStorage.getItem("aitrans.agent.filesystemWorkspaceId")).toBeNull()
  })
})
