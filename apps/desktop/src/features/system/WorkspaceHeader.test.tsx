// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react"
import { afterEach, describe, expect, it } from "vitest"

import type { LlmRuntimeStatus } from "../../api/llm-settings"
import WorkspaceHeader from "./WorkspaceHeader"

afterEach(cleanup)

function renderStatus(state: LlmRuntimeStatus["state"]) {
  render(
    <WorkspaceHeader
      title="AI Chat"
      description="Test"
      llmStatus={{
        state,
        provider: "deepseek",
        model: "deepseek-v4-flash",
        detail: state === "unavailable" ? "Unable to connect." : "",
        active_requests: state === "calling" ? 1 : 0,
      }}
    />,
  )
}

describe("WorkspaceHeader LLM status", () => {
  it.each([
    ["available", "bg-emerald-500"],
    ["calling", "bg-amber-400"],
    ["unavailable", "bg-red-500"],
  ] as const)("renders the %s indicator", (state, expectedClass) => {
    renderStatus(state)
    expect(screen.getByTestId("llm-status-dot").className).toContain(expectedClass)
    expect(screen.getAllByTestId("llm-status-dot")).toHaveLength(1)
  })

  it("flashes only while an LLM request is active", () => {
    renderStatus("calling")
    expect(screen.getByTestId("llm-status-dot").className).toContain("animate-pulse")
  })
})
