// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { MemoryRouter, useLocation } from "react-router-dom"
import { afterEach, describe, expect, it } from "vitest"

import { ResearchWorkflowActions } from "./ResearchWorkflowActions"

function LocationProbe() {
  const location = useLocation()
  return <output aria-label="location">{JSON.stringify({ pathname: location.pathname, state: location.state })}</output>
}

afterEach(cleanup)

describe("ResearchWorkflowActions", () => {
  it("sends an explicit workflow action instead of relying on the button label", async () => {
    render(<MemoryRouter><ResearchWorkflowActions available={["compare_papers"]} /><LocationProbe /></MemoryRouter>)
    await userEvent.click(screen.getByRole("button", { name: /比较论文/ }))
    const location = JSON.parse(screen.getByLabelText("location").textContent || "{}")
    expect(location.pathname).toBe("/agent")
    expect(location.state.agentWorkflowAction).toBe("compare_papers")
    expect(location.state.autoSubmitAgentPrompt).toBe(true)
  })
})
