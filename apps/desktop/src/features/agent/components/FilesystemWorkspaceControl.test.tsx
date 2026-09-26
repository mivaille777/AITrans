// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

import { FilesystemWorkspaceControl } from "./FilesystemWorkspaceControl"

afterEach(() => {
  cleanup()
})

const workspace = {
  workspace_id: "fsw-123",
  display_name: "AITrans",
  readable: true,
  writable: false,
  status: "active" as const,
  created_at: "",
  last_used_at: "",
}

describe("FilesystemWorkspaceControl", () => {
  it("shows the unselected state", () => {
    render(
      <FilesystemWorkspaceControl
        workspace={null}
        loading={false}
        choosing={false}
        error=""
        disabled={false}
        onChoose={vi.fn()}
        onClear={vi.fn()}
      />,
    )

    expect(screen.getByText("No filesystem workspace")).toBeTruthy()
    expect(screen.getByText("Agent cannot access local files until you explicitly choose a folder.")).toBeTruthy()
  })

  it("shows permission boundaries for the active workspace", () => {
    render(
      <FilesystemWorkspaceControl
        workspace={workspace}
        loading={false}
        choosing={false}
        error=""
        disabled={false}
        onChoose={vi.fn()}
        onClear={vi.fn()}
      />,
    )

    expect(screen.getByText("AITrans")).toBeTruthy()
    expect(screen.getByText("Agent file access is limited to this folder.")).toBeTruthy()
    expect(screen.getByText("Outside folder")).toBeTruthy()
    expect(screen.getByText("Confirmation required")).toBeTruthy()
  })

  it("disables workspace mutation while the Agent is running", () => {
    render(
      <FilesystemWorkspaceControl
        workspace={workspace}
        loading={false}
        choosing={false}
        error=""
        disabled
        onChoose={vi.fn()}
        onClear={vi.fn()}
      />,
    )

    expect((screen.getByRole("button", { name: "Change" }) as HTMLButtonElement).disabled).toBe(true)
    expect((screen.getByRole("button", { name: "Clear filesystem workspace" }) as HTMLButtonElement).disabled).toBe(true)
  })

  it("invokes clear explicitly", () => {
    const onClear = vi.fn()
    render(
      <FilesystemWorkspaceControl
        workspace={workspace}
        loading={false}
        choosing={false}
        error=""
        disabled={false}
        onChoose={vi.fn()}
        onClear={onClear}
      />,
    )

    fireEvent.click(screen.getByRole("button", { name: "Clear filesystem workspace" }))
    expect(onClear).toHaveBeenCalledTimes(1)
  })
})
