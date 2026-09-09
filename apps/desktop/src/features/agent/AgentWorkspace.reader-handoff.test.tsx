// @vitest-environment jsdom

import { render, waitFor } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { describe, expect, it, vi } from "vitest"

import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import { AgentWorkspace } from "./AgentWorkspace"

const runtimeMocks = vi.hoisted(() => ({
  submitPrompt: vi.fn(),
}))

vi.mock("./hooks/useAgentRuntime", async () => {
  const React = await import("react")
  return {
    useAgentRuntime: () => {
      const [prompt, setPrompt] = React.useState("")
      return {
        prompt,
        setPrompt,
        sourceText: "Selected paper passage",
        context: {
          resource_title: "Paper",
          section_heading: "Method",
          source_kind: "knowledge_document",
        },
        viewState: {
          phase: "idle",
          uiMode: "default",
          activities: [],
          runId: "",
          traceId: "",
          totalDurationMs: 0,
          confirmationTool: "",
          errorMessage: "",
          outputText: "",
          provider: "",
          model: "",
          evidence: [],
          citations: [],
        },
        traceEvents: [],
        decision: null,
        pending: false,
        cancelRequested: false,
        observabilityRefresh: 0,
        submitPrompt: runtimeMocks.submitPrompt,
        confirmWriteTool: vi.fn(),
        cancelRun: vi.fn(),
      }
    },
  }
})

vi.mock("../companion/components/AgentHeader", () => ({ AgentHeader: () => null }))
vi.mock("../companion/components/AgentInputComposer", () => ({ AgentInputComposer: () => null }))
vi.mock("../companion/components/AgentMessage", () => ({ AgentMessage: () => null }))
vi.mock("../companion/components/AgentObservabilityPanel", () => ({ AgentObservabilityPanel: () => null }))
vi.mock("../companion/components/ContextCard", () => ({ ContextCard: () => null }))
vi.mock("./components/AgentDecisionPanel", () => ({ AgentDecisionPanel: () => null }))
vi.mock("./components/AgentTimeline", () => ({ AgentTimeline: () => null }))
vi.mock("./components/MultiAgentTracePanel", () => ({ MultiAgentTracePanel: () => null }))

describe("AgentWorkspace reader handoff", () => {
  it("loads and automatically submits a question handed off by the paper reader", async () => {
    runtimeMocks.submitPrompt.mockClear()

    render(
      <MemoryRouter
        initialEntries={[
          {
            pathname: "/agent",
            state: {
              agentDraftPrompt: "Explain this passage in context.",
              autoSubmitAgentPrompt: true,
            },
          },
        ]}
      >
        <AgentWorkspace workspace={{} as TranslationWorkspaceController} />
      </MemoryRouter>,
    )

    await waitFor(() => expect(runtimeMocks.submitPrompt).toHaveBeenCalledTimes(1))
  })
})
