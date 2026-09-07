import { useEffect, useRef } from "react"
import { useLocation } from "react-router-dom"

import type { TranslationWorkspaceController } from "../translation/useTranslationWorkspace"
import { AgentHeader } from "../companion/components/AgentHeader"
import { AgentInputComposer } from "../companion/components/AgentInputComposer"
import { AgentMessage } from "../companion/components/AgentMessage"
import { AgentObservabilityPanel } from "../companion/components/AgentObservabilityPanel"
import { ContextCard } from "../companion/components/ContextCard"
import { agentWorkspaceAreas } from "./agent-workspace-layout"
import { AgentDecisionPanel } from "./components/AgentDecisionPanel"
import { AgentTimeline } from "./components/AgentTimeline"
import { useAgentRuntime } from "./hooks/useAgentRuntime"

interface AgentNavigationState {
  agentDraftPrompt?: string
  autoSubmitAgentPrompt?: boolean
}

export function AgentWorkspace({ workspace }: { workspace: TranslationWorkspaceController }) {
  const location = useLocation()
  const navigationState = (location.state ?? null) as AgentNavigationState | null
  const draftPrompt = navigationState?.agentDraftPrompt?.trim() ?? ""
  const autoSubmitDraft = Boolean(navigationState?.autoSubmitAgentPrompt)
  const runtime = useAgentRuntime(workspace)
  const appliedDraftRef = useRef("")
  const submittedDraftRef = useRef("")

  useEffect(() => {
    if (!draftPrompt || appliedDraftRef.current === draftPrompt) return
    appliedDraftRef.current = draftPrompt
    runtime.setPrompt(draftPrompt)
  }, [draftPrompt, runtime.setPrompt])

  useEffect(() => {
    if (!autoSubmitDraft || !draftPrompt || !runtime.sourceText) return
    if (runtime.prompt !== draftPrompt || runtime.pending) return
    if (submittedDraftRef.current === draftPrompt) return
    submittedDraftRef.current = draftPrompt
    runtime.submitPrompt()
  }, [
    autoSubmitDraft,
    draftPrompt,
    runtime.pending,
    runtime.prompt,
    runtime.sourceText,
    runtime.submitPrompt,
  ])

  return (
    <section aria-label="Agent Workspace" className="space-y-4 pb-2">
      <div className="ait-surface overflow-hidden p-5 sm:p-6">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
          <div className="max-w-2xl">
            <p className="text-[10px] font-semibold uppercase tracking-[0.2em] text-slate-400">
              Stage 9 · Agent-first workspace
            </p>
            <h2 className="mt-2 text-xl font-semibold tracking-tight text-slate-950">
              One workspace for context, tools, and execution
            </h2>
            <p className="mt-2 text-sm leading-6 text-slate-500">
              Translation, reading, and research capabilities are presented as Agent resources instead of separate hidden execution paths.
            </p>
          </div>
          <p className="max-w-md text-xs leading-5 text-slate-400">
            Stage 9.4 separates Agent decisions from final answers so approval, retries, fallbacks, cancellation, and failures remain explicit.
          </p>
        </div>

        <div className="mt-5 grid gap-2 sm:grid-cols-2 xl:grid-cols-4" aria-label="Agent workspace areas">
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

      <div className="grid gap-4 xl:grid-cols-[minmax(0,0.82fr)_minmax(0,1.18fr)]">
        <ContextCard
          text={runtime.sourceText}
          title={runtime.context.resource_title}
          section={runtime.context.section_heading}
          sourceKind={runtime.context.source_kind}
        />
        <AgentTimeline
          activities={runtime.viewState.activities}
          running={runtime.viewState.phase === "running" || runtime.viewState.phase === "cancelling"}
          runId={runtime.viewState.runId}
          traceId={runtime.viewState.traceId}
          totalDurationMs={runtime.viewState.totalDurationMs}
        />
      </div>

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

      <AgentObservabilityPanel
        refreshToken={runtime.observabilityRefresh}
        currentRunId={runtime.viewState.runId}
      />

      <div className="sticky bottom-0 z-20 rounded-[18px] border border-slate-200/80 bg-white/95 p-3 shadow-[0_-12px_34px_rgba(15,23,42,0.08)] backdrop-blur-xl">
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