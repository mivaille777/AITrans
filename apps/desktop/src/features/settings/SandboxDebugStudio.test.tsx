import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react"
import { afterEach, describe, expect, it, vi } from "vitest"

vi.mock("../../api/sandbox-debug", () => ({
  getSandboxRuntimeHealth: vi.fn().mockResolvedValue({
    available: true,
    runtime: "docker",
    image: "aitrans-sandbox:latest",
    daemon_ready: true,
    os_type: "linux",
    detail: "",
  }),
}))

vi.mock("./SandboxDebugTrace", () => ({
  default: () => <div>Sandbox trace content</div>,
}))

import SandboxDebugStudio from "./SandboxDebugStudio"

afterEach(() => {
  cleanup()
  vi.clearAllMocks()
})

describe("SandboxDebugStudio", () => {
  it("renders the studio shell and all five tabs", async () => {
    render(<SandboxDebugStudio />)

    expect(screen.getByText("Sandbox Debug Studio")).toBeTruthy()
    await waitFor(() => expect(screen.getByText("Docker · Ready")).toBeTruthy())

    for (const label of ["Trace", "Filesystem", "Resources", "Policy", "Runs"]) {
      const tab = screen.getByRole("tab", { name: label })
      expect((tab as HTMLButtonElement).disabled).toBe(false)
    }
  })

  it("starts on Trace and switches between tab panels", () => {
    render(<SandboxDebugStudio />)

    expect(screen.getByRole("tab", { name: "Trace" }).getAttribute("aria-selected")).toBe("true")
    expect(screen.getByText("Sandbox trace content")).toBeTruthy()

    fireEvent.click(screen.getByRole("tab", { name: "Filesystem" }))
    expect(screen.getByRole("tab", { name: "Filesystem" }).getAttribute("aria-selected")).toBe("true")
    expect(screen.getByText("No filesystem activity recorded")).toBeTruthy()

    fireEvent.click(screen.getByRole("tab", { name: "Resources" }))
    expect(screen.getByText("No resource samples recorded")).toBeTruthy()

    fireEvent.click(screen.getByRole("tab", { name: "Policy" }))
    expect(screen.getByText("No effective policy recorded")).toBeTruthy()

    fireEvent.click(screen.getByRole("tab", { name: "Runs" }))
    expect(screen.getByText("No sandbox runs recorded")).toBeTruthy()
  })

  it("moves the active underline with the selected tab", () => {
    render(<SandboxDebugStudio />)

    const traceTab = screen.getByRole("tab", { name: "Trace" })
    const policyTab = screen.getByRole("tab", { name: "Policy" })

    expect(traceTab.querySelector("span")?.className).toContain("scale-x-100")
    expect(policyTab.querySelector("span")?.className).toContain("scale-x-0")

    fireEvent.click(policyTab)

    expect(traceTab.querySelector("span")?.className).toContain("scale-x-0")
    expect(policyTab.querySelector("span")?.className).toContain("scale-x-100")
  })
})
