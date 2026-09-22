// @vitest-environment jsdom

import { render, screen } from "@testing-library/react"
import { describe, expect, it } from "vitest"

import { AgentKnowledgeStateCard } from "./AgentKnowledgeStateCard"

describe("AgentKnowledgeStateCard", () => {
  it("keeps Agent knowledge policy separate from the Chat control", () => {
    render(
      <AgentKnowledgeStateCard
        events={[]}
        pending={false}
        contextMode="reading"
        contextTitle="Control Paper"
        contextSection="Measurement"
        documentCount={1}
      />,
    )

    expect(screen.getByText("Knowledge policy")).toBeTruthy()
    expect(screen.getByText("Auto")).toBeTruthy()
    expect(screen.getByText("Current document · Measurement")).toBeTruthy()
  })

  it("shows the live evaluating state while a run is pending", () => {
    render(
      <AgentKnowledgeStateCard
        events={[]}
        pending
        contextMode="reading"
        contextSection="Measurement"
      />,
    )

    expect(screen.getByText("Evaluating…")).toBeTruthy()
  })
})
