// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { afterEach, describe, expect, it, vi } from "vitest"

import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import { AgentWorkspace } from "./AgentWorkspace"

const runtimeMocks = vi.hoisted(() => ({
  phase: "idle" as string,
  useAgentRuntime: vi.fn(),
  useFilesystemWorkspace: vi.fn(),
}))

vi.mock("./hooks/useFilesystemWorkspace", () => ({
  useFilesystemWorkspace: runtimeMocks.useFilesystemWorkspace,
}))

vi.mock("./hooks/useAgentRuntime", () => ({
  useAgentRuntime: runtimeMocks.useAgentRuntime,
}))

vi.mock("../companion/components/AgentHeader", () => ({ AgentHeader: () => null }))
vi.mock("../companion/components/AgentInputComposer", () => ({ AgentInputComposer: () => null }))
vi.mock("../companion/components/AgentMessage", () => ({ AgentMessage: () => null }))
vi.mock("../companion/components/AgentObservabilityPanel", () => ({ AgentObservabilityPanel: () => null }))
vi.mock("../companion/components/ContextCard", () => ({ ContextCard: () => null }))
vi.mock("./components/AgentContextObservabilityCard", () => ({ AgentContextObservabilityCard: () => null }))
vi.mock("./components/AgentDecisionPanel", () => ({ AgentDecisionPanel: () => null }))
vi.mock("./components/AgentKnowledgeStateCard", () => ({ AgentKnowledgeStateCard: () => null }))
vi.mock("./components/AgentTimeline", () => ({ AgentTimeline: () => null }))
vi.mock("./components/TaskExecutionPanel", () => ({ TaskExecutionPanel: () => null }))
vi.mock("./components/ResearchArtifactPanel", () => ({ ResearchArtifactPanel: () => null }))
vi.mock("./components/FilesystemWorkspaceControl", () => ({
  FilesystemWorkspaceControl: ({
    workspace,
    disabled,
  }: {
    workspace: { workspace_id: string } | null
    disabled: boolean
  }) => (
    <div data-testid="filesystem-workspace-control">
      FSW: {workspace?.workspace_id ?? "none"} · disabled: {String(disabled)}
    </div>
  ),
}))

function workspace(sandboxEnabled: boolean): TranslationWorkspaceController {
  return {
    backendState: "connected",
    backendService: "aitrans-backend",
    sandboxEnabled,
    providerName: "stub",
    translationProvider: "google_web",
    providerSwitching: false,
    browserStatus: undefined,
    browserStatusChecking: false,
    browserSelection: null,
    browserPage: null,
    readingSelection: null,
    academicReadingContext: null,
    activeResearchWorkspaceId: "",
    researchRetrievalScope: {
      knowledgeDocumentIds: [],
      researchSourceIds: [],
    },
    sourceText: "",
    sourceLanguage: "auto",
    targetLanguage: "zh-CN",
    translation: null,
    translationError: "",
    followBrowserSelection: true,
    autoTranslateSelection: false,
    autoTranslating: false,
    manualTranslating: false,
    updateSourceText: vi.fn(),
    setSourceLanguage: vi.fn(),
    setTargetLanguage: vi.fn(),
    setTranslationProvider: vi.fn(),
    setFollowBrowserSelection: vi.fn(),
    setAutoTranslateSelection: vi.fn(),
    translateManual: vi.fn(),
    swapLanguages: vi.fn(),
    clear: vi.fn(),
    useLatestSelection: vi.fn(),
    useAcademicReadingContext: vi.fn(),
    setActiveResearchWorkspaceId: vi.fn(),
    setResearchRetrievalScope: vi.fn(),
  }
}

function runtime() {
  return {
    prompt: "",
    setPrompt: vi.fn(),
    sourceText: "",
    context: {
      resource_url: "",
      resource_title: "",
      section_heading: "",
      context_before: "",
      context_after: "",
      source_kind: "desktop",
    },
    contextMode: "general",
    viewState: {
      phase: runtimeMocks.phase,
      uiMode: "assistant",
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
    temporary: false,
    workflowAction: "",
    setWorkflowAction: vi.fn(),
    runSnapshot: null,
    durableRun: null,
    setTemporaryMode: vi.fn(),
    submitPrompt: vi.fn(),
    confirmWriteTool: vi.fn(),
    cancelRun: vi.fn(),
    pauseRun: vi.fn(),
    resumeRun: vi.fn(),
    retryRun: vi.fn(),
    retryTask: vi.fn(),
  }
}

function activeFilesystemWorkspace() {
  return {
    workspace: {
      workspace_id: "fsw-123",
      display_name: "AITrans",
      readable: true,
      writable: false,
      status: "active" as const,
      created_at: "",
      last_used_at: "",
    },
    loading: false,
    choosing: false,
    error: "",
    chooseWorkspace: vi.fn(),
    clearWorkspace: vi.fn(),
  }
}

afterEach(() => {
  cleanup()
  runtimeMocks.phase = "idle"
  runtimeMocks.useAgentRuntime.mockReset()
  runtimeMocks.useFilesystemWorkspace.mockReset()
})

describe("AgentWorkspace filesystem workspace integration", () => {
  it("attaches the active filesystem workspace to the Agent runtime", () => {
    runtimeMocks.useFilesystemWorkspace.mockReturnValue(activeFilesystemWorkspace())
    runtimeMocks.useAgentRuntime.mockReturnValue(runtime())

    render(
      <MemoryRouter>
        <AgentWorkspace workspace={workspace(true)} />
      </MemoryRouter>,
    )

    expect(runtimeMocks.useFilesystemWorkspace).toHaveBeenCalledWith(true)
    expect(runtimeMocks.useAgentRuntime).toHaveBeenCalled()
    const call = runtimeMocks.useAgentRuntime.mock.calls[0]
    expect(call?.[2]).toBe("fsw-123")
    expect(call?.[3]).toBe(true)
    expect(screen.getByTestId("filesystem-workspace-control").textContent).toContain("FSW: fsw-123")
    expect(screen.getByTestId("filesystem-workspace-control").textContent).toContain("disabled: false")
  })

  it("locks workspace mutation while the Agent is running", () => {
    runtimeMocks.phase = "running"
    runtimeMocks.useFilesystemWorkspace.mockReturnValue(activeFilesystemWorkspace())
    runtimeMocks.useAgentRuntime.mockReturnValue(runtime())

    render(
      <MemoryRouter>
        <AgentWorkspace workspace={workspace(true)} />
      </MemoryRouter>,
    )

    expect(screen.getByTestId("filesystem-workspace-control").textContent).toContain("disabled: true")
  })

  it("removes filesystem scope when the Sandbox feature is disabled", () => {
    runtimeMocks.useFilesystemWorkspace.mockReturnValue(activeFilesystemWorkspace())
    runtimeMocks.useAgentRuntime.mockReturnValue(runtime())

    render(
      <MemoryRouter>
        <AgentWorkspace workspace={workspace(false)} />
      </MemoryRouter>,
    )

    expect(runtimeMocks.useFilesystemWorkspace).toHaveBeenCalledWith(false)
    const call = runtimeMocks.useAgentRuntime.mock.calls[0]
    expect(call?.[2]).toBe("")
    expect(call?.[3]).toBe(true)
    expect(screen.queryByTestId("filesystem-workspace-control")).toBeNull()
  })
})
