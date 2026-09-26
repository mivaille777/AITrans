import { cleanup, fireEvent, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import SandboxDebugStudio from "./SandboxDebugStudio"

afterEach(() => {
  cleanup()
})

describe("SandboxDebugStudio", () => {
  it("renders the studio shell and all five tabs", () => {
    render(<SandboxDebugStudio />)

    expect(screen.getByText("Sandbox Debug Studio")).toBeTruthy()
    expect(screen.getByText("Runtime status unavailable")).toBeTruthy()

    for (const label of ["Trace", "Filesystem", "Resources", "Policy", "Runs"]) {
      const tab = screen.getByRole("tab", { name: label })
      expect((tab as HTMLButtonElement).disabled).toBe(false)
    }
  })

  it("starts on Trace and switches between tab panels", () => {
    render(<SandboxDebugStudio />)

    expect(screen.getByRole("tab", { name: "Trace" }).getAttribute("aria-selected")).toBe("true")
    expect(screen.getByText("Run a Python sandbox trace")).toBeTruthy()

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
