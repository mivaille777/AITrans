import { afterEach, describe, expect, it, vi } from "vitest"

import {
  createFilesystemWorkspace,
  getFilesystemWorkspace,
  listFilesystemWorkspaces,
  revokeFilesystemWorkspace,
} from "./filesystem-workspaces"

afterEach(() => {
  vi.unstubAllGlobals()
})

describe("filesystem workspace api", () => {
  it("creates, lists, reads and revokes workspace registrations", async () => {
    const workspace = {
      workspace_id: "fsw-123",
      display_name: "AITrans",
      readable: true,
      writable: false,
      status: "active",
      created_at: "2026-09-26T12:00:00Z",
      last_used_at: "2026-09-26T12:00:00Z",
    }
    const responses = [workspace, [workspace], workspace, { workspace_id: "fsw-123", revoked: true }]
    const fetchMock = vi.fn(async (_input: RequestInfo | URL, _init?: RequestInit) =>
      new Response(JSON.stringify(responses.shift()), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    )
    vi.stubGlobal("fetch", fetchMock)

    await createFilesystemWorkspace("D:\\Project\\AITrans")
    await listFilesystemWorkspaces()
    await getFilesystemWorkspace("fsw-123")
    const revoked = await revokeFilesystemWorkspace("fsw-123")

    expect(revoked.revoked).toBe(true)
    expect(JSON.parse(String((fetchMock.mock.calls[0]?.[1] as RequestInit).body))).toEqual({
      path: "D:\\Project\\AITrans",
    })
    expect((fetchMock.mock.calls[3]?.[1] as RequestInit).method).toBe("DELETE")
  })
})
