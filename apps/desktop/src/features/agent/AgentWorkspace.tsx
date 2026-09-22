import { useEffect, useMemo, useRef, useState } from "react"
import { useLocation, useNavigate } from "react-router-dom"

import { runAgentTrace, type AgentRunRequest, type AgentWorkflowAction } from "../../api/agent"
import { Button } from "../../shared/ui/Button"
import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import { AgentHeader } from "../companion/components/AgentHeader"
import { AgentInputComposer } from "../companion/components/AgentInputComposer"
import { AgentMessage } from "../companion/components/AgentMessage"
import { AgentObservabilityPanel } from "../companion/components/AgentObservabilityPanel"
import { ContextCard } from "../companion/components/ContextCard"
import { agentWorkspaceAreas } from "./agent-workspace-layout"
import { AgentContextObservabilityCard } from "./components/AgentContextObservabilityCard"
import { AgentDecisionPanel } from "./components/AgentDecisionPanel"
import { AgentTimeline } from "./components/AgentTimeline"
import { TaskExecutionPanel } from "./components/TaskExecutionPanel"
import { ResearchArtifactPanel } from "./components/ResearchArtifactPanel"
import { useAgentRuntime } from "./hooks/useAgentRuntime"
import {
  resolveKnowledgeAgentContext,
  type KnowledgeAgentContext,
} from "./runtime/knowledge-agent-context"

interface AgentNavigationState {
  agentDraftPrompt?: string
  autoSubmitAgentPrompt?: boolean
  knowledgeAgentContext?: KnowledgeAgentContext
  agentWorkflowAction?: AgentWorkflowAction
}

export function AgentWorkspace({ workspace }: { workspace: TranslationWorkspaceController }) {
  const location = useLocation()
  const navigate = useNavigate()
  const navigationState = (location.state ?? null) as AgentNavigationState | null
  const draftPrompt = navigationState?.agentDraftPrompt?.trim() ?? ""
  const autoSubmitDraft = Boolean(navigationState?.autoSubmitAgentPrompt)
  const requestedWorkflowAction = navigationState?.agentWorkflowAction ?? ""
  const knowledgeAgentContext = navigationState?.knowledgeAgentContext ?? null
  const resolvedKnowledgeContext = useMemo(
    () => resolveKnowledgeAgentContext(knowledgeAgentContext),
    [knowledgeAgentContext],
  )
  const runtimeWorkspace = useMemo<TranslationWorkspaceController>(() => {
    if (!knowledgeAgentContext || !resolvedKnowledgeContext) return workspace

    const item = knowledgeAgentContext.item
    const documentIds = [
      ...workspace.researchRetrievalScope.knowledgeDocumentIds,
      ...resolvedKnowledgeContext.documentIds,
    ]
    return {
      ...workspace,
      translation: null,
      academicReadingContext: {
        context_id: `knowledge-card-${item.item_id}`,
        document_id: item.resource_document_id ?? item.item_id,
        text: resolvedKnowledgeContext.sourceText,
        resource_url: resolvedKnowledgeContext.context.resource_url,
        resource_title: item.title,
        section_heading: resolvedKnowledgeContext.context.section_heading,
        context_before: "",
        context_after: "",
        source_kind: "knowledge_document",
      },
      researchRetrievalScope: {
        ...workspace.researchRetrievalScope,
        knowledgeDocumentIds: [...new Set(documentIds.filter(Boolean))],
      },
    }
  }, [knowledgeAgentContext, resolvedKnowledgeContext, workspace])
  const runtime = useAgentRuntime(
    runtimeWorkspace,
    resolvedKnowledgeContext?.knowledgeContext ?? null,
  )
  const { pending, prompt, setPrompt, setWorkflowAction, sourceText, submitPrompt } = runtime
  const appliedDraftRef = useRef("")
  const submittedDraftRef = useRef("")
  const lastRuntimeRunRef = useRef("")
  const [savingKnowledge, setSavingKnowledge] = useState(false)
  const [knowledgeSaveError, setKnowledgeSaveError] = useState("")
  const [savedKnowledgeItemId, setSavedKnowledgeItemId] = useState("")

  useEffect(() => {
    if (!draftPrompt || appliedDraftRef.current === draftPrompt) return
    appliedDraftRef.current = draftPrompt
    setPrompt(draftPrompt)
    setWorkflowAction?.(requestedWorkflowAction)
  }, [draftPrompt, requestedWorkflowAction, setPrompt, setWorkflowAction])

  useEffect(() => {
    if (!autoSubmitDraft || !draftPrompt) return
    if (["quick_read", "analyze_visuals"].includes(requestedWorkflowAction) && !sourceText) return
    if (prompt !== draftPrompt || pending) return
    if (submittedDraftRef.current === draftPrompt) return
    submittedDraftRef.current = draftPrompt
    submitPrompt()
  }, [autoSubmitDraft, draftPrompt, pending, prompt, requestedWorkflowAction, sourceText, submitPrompt])

  useEffect(() => {
    const runId = runtime.viewState.runId
    if (!runId || runId === lastRuntimeRunRef.current) return
    lastRuntimeRunRef.current = runId
    setKnowledgeSaveError("")
    setSavedKnowledgeItemId("")
  }, [runtime.viewState.runId])

  async function saveKnowledgeResult() {
    const writeback = knowledgeAgentContext?.writeback
    const resolved = resolvedKnowledgeContext
    const output = runtime.viewState.outputText.trim()
    if (!writeback || !resolved || !output || savingKnowledge) return

    setSavingKnowledge(true)
    setKnowledgeSaveError("")
    try {
      const traceId = `trace-knowledge-writeback-${Date.now().toString(36)}`
      const payload: AgentRunRequest = {
        ...resolved.context,
        session_id: `knowledge-writeback-${runtime.viewState.runId || Date.now().toString(36)}`,
        trace_id: traceId,
        client_id: "knowledge-agent-writeback",
        client_surface: "main",
        context_mode: "reading",
        user_message: "save this agent result to knowledge",
        source_text: resolved.sourceText,
        translated_text: output,
        source_language: workspace.sourceLanguage,
        target_language: workspace.targetLanguage,
        style: "academic",
        conversation_id: "",
        workspace_id: "",
        confirmed_write_tools: ["save_knowledge_card"],
        knowledge_document_ids: resolved.documentIds,
        research_source_ids: [],
        knowledge_context: resolved.knowledgeContext,
        request_id: 1,
      }
      const result = await runAgentTrace(payload)
      const toolResult = result.run.tool_result
      if (result.run.status !== "completed" || toolResult?.tool_name !== "save_knowledge_card") {
        throw new Error("Knowledge write-back did not complete.")
      }
      const itemId = String(toolResult.data.item_id ?? "").trim()
      if (!itemId) throw new Error("Knowledge write-back completed without a card id.")
      setSavedKnowledgeItemId(itemId)
    } catch (error) {
      setKnowledgeSaveError(error instanceof Error ? error.message : "Unable to save this Agent result to Knowledge.")
    } finally {
      setSavingKnowledge(false)
    }
  }

  const runtimeRunning = ["queued", "running", "pausing", "recovering", "cancelling"].includes(runtime.viewState.phase)
  const canOfferKnowledgeWriteback = Boolean(
    knowledgeAgentContext?.writeback
    && runtime.viewState.phase === "completed"
    && runtime.viewState.outputText.trim(),
  )

  return (
    <section aria-label="AI Agent Workspace" className="space-y-4 pb-2">
      <div className="ait-surface overflow-hidden p-5 sm:p-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div className="max-w-2xl">
            <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-400">
              AI Agent Workspace
            </p>
            <h2 className="mt-2 text-xl font-semibold tracking-tight text-slate-950">
              你的 AI Agent 正在理解任务、调用工具并完成工作
            </h2>
            <p className="mt-2 text-sm leading-6 text-slate-500">
              多个专业 Agent 可以协同分析，由主 Agent 统一规划执行流程，并通过状态追踪、工具确认和结果验证完成任务。
            </p>
          </div>
          <p className="max-w-md text-xs leading-5 text-slate-400">
            Agent 会根据任务选择合适能力。涉及关键操作时，会进行确认并保持结果可追踪。
          </p>
        </div>

        <div className="mt-5 grid gap-2 sm:grid-cols-2 xl:grid-cols-4" aria-label="Agent capabilities">
          {agentWorkspaceAreas.map((area, index) => (
            <div
              key={area.id}
              className="rounded-[16px] border border-slate-200/80 bg-white/70 px-4 py-3 shadow-sm"
              data-agent-area={area.id}
            >
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-semibold tabular-nums text-slate-400">
                  {String(index + 1).padStart(2, "0")}
                </span>
                <strong className="text-xs font-semibold text-slate-800">{area.label}</strong>
              </div>
              <p className="mt-2 text-[11px] leading-5 text-slate-500">{area.description}</p>
            </div>
          ))}
        </div>
      </div>

      <AgentHeader phase={runtime.viewState.phase} uiMode={runtime.viewState.uiMode} />

      <AgentContextObservabilityCard
        context={resolvedKnowledgeContext?.knowledgeContext ?? null}
        events={runtime.traceEvents}
      />

      <div className="grid gap-4 xl:grid-cols-[minmax(0,0.82fr)_minmax(0,1.18fr)]">
        <ContextCard
          text={runtime.sourceText}
          title={runtime.context.resource_title}
          section={runtime.context.section_heading}
          sourceKind={runtime.context.source_kind}
        />
        <AgentTimeline
          activities={runtime.viewState.activities}
          running={runtimeRunning}
          runId={runtime.viewState.runId}
          traceId={runtime.viewState.traceId}
          totalDurationMs={runtime.viewState.totalDurationMs}
          runStatus={runtime.durableRun?.status ?? runtime.viewState.phase}
        />
      </div>


      {runtime.durableRun ? (
        <div className="ait-surface flex flex-wrap items-center gap-2 p-3" aria-label="Durable Agent run controls">
          <span className="mr-auto text-[11px] font-medium text-slate-500">
            Runtime · {runtime.durableRun.status}
          </span>
          {runtime.durableRun.status === "running" ? (
            <Button onClick={runtime.pauseRun}>Pause</Button>
          ) : null}
          {runtime.durableRun.status === "paused" ? (
            <Button onClick={runtime.resumeRun}>Resume</Button>
          ) : null}
          {runtime.durableRun.status === "failed" ? (
            <Button onClick={runtime.retryRun}>Retry</Button>
          ) : null}
          {!["completed", "failed", "cancelled"].includes(runtime.durableRun.status) ? (
            <Button onClick={runtime.cancelRun}>Cancel</Button>
          ) : null}
        </div>
      ) : null}

      <TaskExecutionPanel
        events={runtime.traceEvents}
        snapshot={runtime.runSnapshot}
        running={runtimeRunning}
        onRetry={runtime.retryTask}
      />

      <ResearchArtifactPanel snapshot={runtime.runSnapshot} />

      <AgentDecisionPanel
        notice={runtime.decision}
        onConfirm={runtime.confirmWriteTool}
        confirming={runtime.pending}
      />

      <AgentMessage
        content={runtime.viewState.outputText}
        phase={runtime.viewState.phase}
        provider={runtime.viewState.provider}
        model={runtime.viewState.model}
        evidence={runtime.viewState.evidence}
        citations={runtime.viewState.citations}
      />

      {canOfferKnowledgeWriteback ? (
        <div className="ait-surface flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="min-w-0">
            <p className="text-xs font-semibold text-slate-900">
              {savedKnowledgeItemId ? "Result saved to Knowledge" : "Save this Agent result to Knowledge?"}
            </p>
            <p className="mt-1 text-[11px] leading-5 text-slate-500">
              {savedKnowledgeItemId
                ? "The canonical card and its AI-derived relation are now stored in the Knowledge Library."
                : `Nothing is written automatically. Confirm to create a ${knowledgeAgentContext?.writeback?.itemType ?? "note"} linked to ${knowledgeAgentContext?.item.title ?? "the source card"}.`}
            </p>
            {knowledgeSaveError ? (
              <p className="mt-2 text-[11px] text-rose-600" role="alert">{knowledgeSaveError}</p>
            ) : null}
          </div>
          <div className="flex shrink-0 gap-2">
            {savedKnowledgeItemId ? (
              <Button
                onClick={() => navigate(`/knowledge?view=library&item=${encodeURIComponent(savedKnowledgeItemId)}`)}
              >
                Open saved card
              </Button>
            ) : (
              <Button
                variant="primary"
                disabled={savingKnowledge}
                onClick={() => void saveKnowledgeResult()}
              >
                {savingKnowledge ? "Saving…" : "Save to Knowledge"}
              </Button>
            )}
          </div>
        </div>
      ) : null}

      <AgentObservabilityPanel
        refreshToken={runtime.observabilityRefresh}
        currentRunId={runtime.viewState.runId}
      />

      <div className="sticky bottom-0 z-20 rounded-[18px] border border-slate-200/80 bg-white/95 p-3 shadow-[0_-12px_34px_rgba(15,23,42,0.08)] backdrop-blur-xl">
        <label className="mb-2 flex items-center gap-2 px-1 text-[11px] text-slate-500">
          <input
            type="checkbox"
            checked={runtime.temporary}
            disabled={runtime.pending}
            onChange={(event) => runtime.setTemporaryMode(event.target.checked)}
          />
          临时会话：不读取长期记忆，不保存聊天、checkpoint、trace 或恢复记录
        </label>
        <AgentInputComposer
          value={runtime.prompt}
          onChange={runtime.setPrompt}
          onSubmit={runtime.submitPrompt}
          onCancel={runtime.cancelRun}
          disabled={runtime.pending}
          busy={runtime.pending}
          cancelling={runtime.cancelRequested}
        />
      </div>
    </section>
  )
}

export default AgentWorkspace
