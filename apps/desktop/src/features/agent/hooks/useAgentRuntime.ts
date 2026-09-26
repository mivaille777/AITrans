import { useEffect, useId, useMemo, useRef, useState } from "react"

import type {
  AgentKnowledgeContext,
  AgentRunSnapshot,
  AgentRunRequest,
  AgentRunResponse,
  AgentRunTraceResponse,
  AgentTraceEvent,
  AgentWorkflowAction,
} from "../../../api/agent"
import { getAgentRunSnapshot } from "../../../api/agent"
import {
  cancelAgentRuntimeRun,
  confirmAgentRuntimeRun,
  createAgentRuntimeRun,
  getAgentRuntimeEvents,
  getAgentRuntimeResult,
  getAgentRuntimeRun,
  pauseAgentRuntimeRun,
  resumeAgentRuntimeRun,
  retryAgentRuntimeRun,
  streamAgentRuntimeRun,
  type DurableAgentRunRecord,
  type DurableAgentRuntimeStreamHandle,
} from "../../../api/agent-runtime"
import {
  streamAgentRun,
  type AgentStreamHandle,
} from "../../../api/agent-stream"
import { attachResearchProjectMember } from "../../../api/research"
import type { ReadingContextFields } from "../../../api/types"
import type { TranslationWorkspaceController } from "../../translation/useTranslationWorkspace"
import { deriveAgentDecision } from "../decision/agent-decision"
import {
  buildAgentResumeRequest,
  clearPendingAgentRun,
  readPendingAgentRun,
  rememberPendingAgentRun,
} from "../runtime/agent-checkpoint-recovery"
import type { AgentContextMode } from "../runtime/agent-context-mode"
import {
  inferAgentContextMode,
  resolveAgentContext,
} from "../runtime/agent-context-resolver"
import { buildAgentRunRequest } from "../runtime/agent-run-request"
import { mergeAgentEvents } from "../runtime/agent-event-replay"
import { defaultKnowledgeAccessPolicy } from "../runtime/knowledge-access-policy"
import { deriveAgentWorkspaceState } from "../state/agent-workspace-state"

export function useAgentRuntime(
  workspace: TranslationWorkspaceController,
  knowledgeContext: AgentKnowledgeContext | null = null,
  filesystemWorkspaceId = "",
  filesystemWorkspaceHydrated = true,
) {
  const [prompt, setPrompt] = useState("")
  const [trace, setTrace] = useState<AgentRunTraceResponse | null>(null)
  const [liveEvents, setLiveEvents] = useState<AgentTraceEvent[]>([])
  const [pending, setPending] = useState(false)
  const [cancelRequested, setCancelRequested] = useState(false)
  const [cancelledMessage, setCancelledMessage] = useState("")
  const [errorMessage, setErrorMessage] = useState("")
  const [fallbackReason, setFallbackReason] = useState("")
  const [temporary, setTemporary] = useState(false)
  const [workflowAction, setWorkflowAction] = useState<AgentWorkflowAction>("")
  const [runSnapshot, setRunSnapshot] = useState<AgentRunSnapshot | null>(null)
  const [durableRun, setDurableRun] = useState<DurableAgentRunRecord | null>(null)
  const [observabilityRefresh, setObservabilityRefresh] = useState(0)
  const reactInstanceId = useId()
  const sessionId = `agent-workspace-${reactInstanceId.replace(/[^a-zA-Z0-9_-]/g, "")}`
  const conversationId = useRef("")
  const conversationMode = useRef<AgentContextMode | null>(null)
  const requestId = useRef(0)
  const lastPayload = useRef<AgentRunRequest | null>(null)
  const streamHandle = useRef<AgentStreamHandle | null>(null)
  const durableStreamHandle = useRef<DurableAgentRuntimeStreamHandle | null>(null)
  const activeRunId = useRef("")
  const recoveryAttempted = useRef(false)
  const initialTargetLanguage = useRef(workspace.targetLanguage)
  const transportRecoveryCount = useRef(0)
  const activeWorkspaceId = useRef(workspace.activeResearchWorkspaceId)
  const activeFilesystemWorkspaceId = useRef(filesystemWorkspaceId)
  const filesystemBoundaryInitialized = useRef(false)

  useEffect(() => {
    return () => {
      streamHandle.current?.close()
      streamHandle.current = null
      durableStreamHandle.current?.close()
      durableStreamHandle.current = null
    }
  }, [])

  /* oxlint-disable react-hooks/set-state-in-effect -- changing workspace is a security boundary that clears stale scoped UI state */
  useEffect(() => {
    if (activeWorkspaceId.current === workspace.activeResearchWorkspaceId) return
    activeWorkspaceId.current = workspace.activeResearchWorkspaceId
    streamHandle.current?.cancel()
    streamHandle.current?.close()
    streamHandle.current = null
    durableStreamHandle.current?.close()
    durableStreamHandle.current = null
    clearPendingAgentRun(activeRunId.current)
    activeRunId.current = ""
    conversationId.current = ""
    conversationMode.current = null
    lastPayload.current = null
    setTrace(null)
    setLiveEvents([])
    setRunSnapshot(null)
    setDurableRun(null)
    setPending(false)
    setCancelRequested(false)
    setCancelledMessage("")
    setErrorMessage("")
    setFallbackReason("")
  }, [workspace.activeResearchWorkspaceId])
  /* oxlint-enable react-hooks/set-state-in-effect */

  /* oxlint-disable react-hooks/set-state-in-effect -- filesystem workspace changes are security-boundary changes */
  useEffect(() => {
    if (!filesystemWorkspaceHydrated) return
    if (!filesystemBoundaryInitialized.current) {
      filesystemBoundaryInitialized.current = true
      activeFilesystemWorkspaceId.current = filesystemWorkspaceId
      return
    }
    if (activeFilesystemWorkspaceId.current === filesystemWorkspaceId) return

    activeFilesystemWorkspaceId.current = filesystemWorkspaceId
    streamHandle.current?.cancel()
    streamHandle.current?.close()
    streamHandle.current = null
    durableStreamHandle.current?.close()
    durableStreamHandle.current = null
    clearPendingAgentRun(activeRunId.current)
    activeRunId.current = ""
    conversationId.current = ""
    conversationMode.current = null
    lastPayload.current = null
    setTrace(null)
    setLiveEvents([])
    setRunSnapshot(null)
    setDurableRun(null)
    setPending(false)
    setCancelRequested(false)
    setCancelledMessage("")
    setErrorMessage("")
    setFallbackReason("")
  }, [filesystemWorkspaceHydrated, filesystemWorkspaceId])
  /* oxlint-enable react-hooks/set-state-in-effect */

  const academic = workspace.academicReadingContext
  const reading = workspace.readingSelection
  const ambientSourceText = (academic?.text || reading?.text || workspace.sourceText).trim()
  const ambientContext = useMemo<ReadingContextFields>(
    () => {
      if (academic) {
        return {
          resource_url: academic.resource_url,
          resource_title: academic.resource_title,
          section_heading: academic.section_heading,
          context_before: academic.context_before,
          context_after: academic.context_after,
          source_kind: academic.source_kind,
        }
      }
      return {
        resource_url: reading?.resource_url || workspace.browserPage?.url || "",
        resource_title: reading?.resource_title || workspace.browserPage?.title || "",
        section_heading: reading?.section_heading || workspace.browserPage?.heading || "",
        context_before: reading?.context_before || "",
        context_after: reading?.context_after || "",
        source_kind: reading?.source_kind || (workspace.browserPage ? "browser_dom" : "desktop"),
      }
    },
    [academic, reading, workspace.browserPage],
  )

  const browserContext = useMemo<ReadingContextFields | null>(
    () => workspace.browserPage
      ? {
          resource_url: workspace.browserPage.url || "",
          resource_title: workspace.browserPage.title || "",
          section_heading: workspace.browserPage.heading || "",
          context_before: "",
          context_after: "",
          source_kind: "browser_dom",
        }
      : null,
    [workspace.browserPage],
  )

  const hasKnowledgeScope = workspace.researchRetrievalScope.knowledgeDocumentIds.length > 0
  const hasResearchWorkspace = Boolean(workspace.activeResearchWorkspaceId.trim())
  const previewMode = useMemo(
    () => inferAgentContextMode({
      userMessage: prompt,
      hasReadingContext: Boolean(ambientSourceText),
      hasKnowledgeScope,
      hasResearchWorkspace,
    }),
    [ambientSourceText, hasKnowledgeScope, hasResearchWorkspace, prompt],
  )
  const previewContext = useMemo(
    () => resolveAgentContext({
      mode: previewMode,
      readingText: ambientSourceText,
      readingContext: ambientContext,
      browserContext,
      fallbackText: workspace.sourceText,
    }),
    [ambientContext, ambientSourceText, browserContext, previewMode, workspace.sourceText],
  )

  const viewState = useMemo(
    () => deriveAgentWorkspaceState({
      trace,
      liveEvents,
      pending,
      cancelRequested,
      cancelledMessage,
      errorMessage,
      durableRun,
    }),
    [cancelRequested, cancelledMessage, durableRun, errorMessage, liveEvents, pending, trace],
  )

  const decision = useMemo(
    () => deriveAgentDecision({
      phase: viewState.phase,
      confirmationTool: viewState.confirmationTool,
      errorMessage: viewState.errorMessage,
      fallbackReason,
      activities: viewState.activities,
    }),
    [fallbackReason, viewState],
  )

  const traceEvents = useMemo(
    () => (pending || liveEvents.length > 0 ? liveEvents : trace?.events ?? []),
    [liveEvents, pending, trace],
  )

  function refreshObservability() {
    setObservabilityRefresh((current) => current + 1)
  }

  function rememberConversation(nextConversationId: string) {
    const normalized = nextConversationId.trim()
    if (!normalized) return
    conversationId.current = normalized
    if (lastPayload.current) {
      lastPayload.current = {
        ...lastPayload.current,
        conversation_id: normalized,
      }
    }
  }

  function associateTraceWithWorkspace(nextTrace: AgentRunTraceResponse) {
    const workspaceId = workspace.activeResearchWorkspaceId.trim()
    if (!workspaceId) return

    const operations: Promise<unknown>[] = []
    const nextConversationId = nextTrace.run.conversation_id.trim()
    if (nextConversationId) {
      operations.push(
        attachResearchProjectMember(workspaceId, "conversation", nextConversationId),
      )
    }

    if (nextTrace.run.tool_result?.tool_name === "save_research_note") {
      const noteId = String(nextTrace.run.tool_result.data.note_id ?? "").trim()
      if (noteId) {
        operations.push(attachResearchProjectMember(workspaceId, "note", noteId))
      }
    }

    if (operations.length > 0) {
      void Promise.allSettled(operations)
    }
  }

  function executeLegacyStream(payload: AgentRunRequest, preserveEvents = false) {
    streamHandle.current?.close()
    streamHandle.current = null
    if (!payload.resume_run_id) {
      clearPendingAgentRun()
    }
    setPending(true)
    setCancelRequested(false)
    setCancelledMessage("")
    setErrorMessage("")
    setFallbackReason("")
    if (!preserveEvents) {
      transportRecoveryCount.current = 0
      setLiveEvents([])
      setRunSnapshot(null)
    }
    activeRunId.current = payload.resume_run_id || ""

    streamHandle.current = streamAgentRun(payload, {
      onEvent(event) {
        if (event.type === "accepted") {
          activeRunId.current = event.run_id
          rememberPendingAgentRun(event, Date.now(), Boolean(payload.temporary))
          return
        }

        if (event.type === "activity") {
          setLiveEvents((current) => mergeAgentEvents(current, [event.event], event.run_id))
          return
        }

        if (event.type === "cancel_requested") {
          setCancelRequested(true)
          return
        }

        if (event.type === "cancelled") {
          clearPendingAgentRun(event.run_id || activeRunId.current)
          activeRunId.current = ""
          setCancelledMessage(event.message || "Agent run cancelled.")
          setFallbackReason("")
          setCancelRequested(false)
          setPending(false)
          streamHandle.current = null
          refreshObservability()
          return
        }

        if (event.type === "done") {
          clearPendingAgentRun(event.run_id || activeRunId.current)
          activeRunId.current = ""
          rememberConversation(event.trace.run.conversation_id || "")
          associateTraceWithWorkspace(event.trace)
          setTrace((current) => ({
            ...event.trace,
            events: mergeAgentEvents(
              current?.run_id === event.run_id ? current.events : liveEvents,
              event.trace.events,
              event.run_id,
            ),
          }))
          setLiveEvents((current) => mergeAgentEvents(current, event.trace.events, event.run_id))
          void getAgentRunSnapshot(event.run_id)
            .then((snapshot) => {
              setRunSnapshot(snapshot)
              setLiveEvents((current) => mergeAgentEvents(current, snapshot.events, snapshot.run_id))
            })
            .catch(() => undefined)
          setFallbackReason("")
          setCancelRequested(false)
          setPending(false)
          streamHandle.current = null
          refreshObservability()
          return
        }

        if (event.type === "error") {
          clearPendingAgentRun(event.run_id || activeRunId.current)
          activeRunId.current = ""
          setErrorMessage(event.message || "Agent run failed.")
          setFallbackReason(event.fallback_reason || "")
          setCancelRequested(false)
          setPending(false)
          streamHandle.current = null
          refreshObservability()
        }
      },
      onTransportError(error) {
        const runId = activeRunId.current
        streamHandle.current = null
        if (!runId || payload.temporary || transportRecoveryCount.current >= 2) {
          setErrorMessage(error.message || "Agent stream failed.")
          setFallbackReason("")
          setCancelRequested(false)
          setPending(false)
          return
        }
        transportRecoveryCount.current += 1
        setErrorMessage("Connection interrupted. Recovering the authoritative run state…")
        void getAgentRunSnapshot(runId)
          .then((snapshot) => {
            setRunSnapshot(snapshot)
            setLiveEvents((current) => mergeAgentEvents(current, snapshot.events, runId))
            if (!snapshot.resumable) {
              clearPendingAgentRun(runId)
              activeRunId.current = ""
              setPending(false)
              setErrorMessage(snapshot.status === "completed" ? "" : `Agent run ended with status: ${snapshot.status}.`)
              return
            }
            const resume = buildAgentResumeRequest({
              runId,
              traceId: snapshot.trace_id || payload.trace_id || "",
              sessionId: payload.session_id,
              requestId: payload.request_id ?? 0,
              acceptedAt: Date.now(),
            }, initialTargetLanguage.current)
            lastPayload.current = resume
            setErrorMessage("")
            executeLegacyStream(resume, true)
          })
          .catch(() => {
            setErrorMessage(error.message || "Agent stream failed.")
            setFallbackReason("")
            setCancelRequested(false)
            setPending(false)
          })
      },
    })
  }


  function buildDurableTrace(
    run: DurableAgentRunRecord,
    session: string,
    response: AgentRunResponse,
    events: AgentTraceEvent[],
  ): AgentRunTraceResponse {
    return {
      run_id: run.run_id,
      trace_id: run.trace_id,
      session_id: session,
      ui_mode: "assistant",
      total_duration_ms: events.at(-1)?.elapsed_ms ?? run.budget_used_ms,
      run: response,
      events,
    }
  }

  async function hydrateDurableRun(
    run: DurableAgentRunRecord,
    session: string,
  ): Promise<void> {
    setDurableRun(run)
    const [eventsResult, resultResult, snapshotResult] = await Promise.allSettled([
      getAgentRuntimeEvents(run.run_id),
      getAgentRuntimeResult(run.run_id),
      getAgentRunSnapshot(run.run_id),
    ])
    const events = eventsResult.status === "fulfilled" ? eventsResult.value : []
    if (events.length > 0) setLiveEvents(events)
    if (snapshotResult.status === "fulfilled") setRunSnapshot(snapshotResult.value)

    if (resultResult.status === "fulfilled" && resultResult.value.result) {
      const candidate = resultResult.value.result as Partial<AgentRunResponse>
      if (candidate.run_id && candidate.trace_id && candidate.plan) {
        const response = candidate as AgentRunResponse
        const nextTrace = buildDurableTrace(run, session, response, events)
        setTrace(nextTrace)
        rememberConversation(response.conversation_id || "")
        associateTraceWithWorkspace(nextTrace)
      } else if (run.status === "failed") {
        const payload = resultResult.value.result as Record<string, unknown>
        setErrorMessage(String(payload.message || payload.code || "Agent run failed."))
      }
    }

    if (run.status === "cancelled") {
      setCancelledMessage("Agent run cancelled.")
    }
    if (["waiting", "paused", "completed", "failed", "cancelled"].includes(run.status)) {
      setPending(false)
    }
    if (["completed", "failed", "cancelled"].includes(run.status)) {
      clearPendingAgentRun(run.run_id)
      activeRunId.current = ""
      durableStreamHandle.current?.close()
      durableStreamHandle.current = null
      refreshObservability()
    }
  }

  function followDurableRun(
    run: DurableAgentRunRecord,
    session: string,
    request: number,
    afterSequence = -1,
  ) {
    durableStreamHandle.current?.close()
    activeRunId.current = run.run_id
    setDurableRun(run)
    setPending(["queued", "running", "pause_requested", "recovering"].includes(run.status))
    rememberPendingAgentRun({
      type: "accepted",
      request_id: request,
      session_id: session,
      run_id: run.run_id,
      trace_id: run.trace_id,
    })
    durableStreamHandle.current = streamAgentRuntimeRun(
      run.run_id,
      {
        onEvent(event) {
          if (event.type === "event") {
            setLiveEvents((current) => mergeAgentEvents(current, [event.event], run.run_id))
            return
          }
          if (event.type === "run") {
            setDurableRun(event.run)
            setPending(["queued", "running", "pause_requested", "recovering"].includes(event.run.status))
            if (event.run.status === "waiting" || event.run.status === "paused") {
              void hydrateDurableRun(event.run, session)
            }
            return
          }
          if (event.type === "terminal") {
            void hydrateDurableRun(event.run, session)
            return
          }
          setErrorMessage(event.message)
          setPending(false)
        },
        onTransportError(error) {
          const runId = activeRunId.current
          durableStreamHandle.current = null
          if (!runId || transportRecoveryCount.current >= 2) {
            setErrorMessage(error.message)
            setPending(false)
            return
          }
          transportRecoveryCount.current += 1
          void Promise.all([getAgentRuntimeRun(runId), getAgentRuntimeEvents(runId)])
            .then(([currentRun, events]) => {
              setDurableRun(currentRun)
              setLiveEvents(events)
              const cursor = events.at(-1)?.sequence ?? -1
              followDurableRun(currentRun, session, request, cursor)
            })
            .catch(() => {
              setErrorMessage(error.message)
              setPending(false)
            })
        },
      },
      afterSequence,
    )
  }

  function executeDurable(payload: AgentRunRequest, preserveEvents = false) {
    setPending(true)
    setCancelRequested(false)
    setCancelledMessage("")
    setErrorMessage("")
    setFallbackReason("")
    if (!preserveEvents) {
      transportRecoveryCount.current = 0
      setTrace(null)
      setLiveEvents([])
      setRunSnapshot(null)
      setDurableRun(null)
    }
    void createAgentRuntimeRun(payload, "long_task")
      .then((run) => followDurableRun(
        run,
        payload.session_id,
        payload.request_id ?? 0,
      ))
      .catch((error) => {
        setPending(false)
        setErrorMessage(error instanceof Error ? error.message : "Unable to create durable Agent run.")
      })
  }

  function execute(payload: AgentRunRequest, preserveEvents = false) {
    if (payload.temporary) {
      executeLegacyStream(payload, preserveEvents)
      return
    }
    executeDurable(payload, preserveEvents)
  }

  /* oxlint-disable react-hooks/exhaustive-deps -- checkpoint recovery is one-shot per mounted runtime */
  useEffect(() => {
    if (recoveryAttempted.current) return
    recoveryAttempted.current = true
    const pendingRun = readPendingAgentRun()
    if (!pendingRun) return

    requestId.current = Math.max(requestId.current, pendingRun.requestId)
    const timer = window.setTimeout(() => {
      void getAgentRuntimeRun(pendingRun.runId)
        .then((run) => followDurableRun(
          run,
          pendingRun.sessionId,
          pendingRun.requestId,
          -1,
        ))
        .catch(() => {
          const payload = buildAgentResumeRequest(pendingRun, initialTargetLanguage.current)
          lastPayload.current = payload
          executeLegacyStream(payload)
        })
    }, 0)
    return () => window.clearTimeout(timer)
  }, [])
  /* oxlint-enable react-hooks/exhaustive-deps */

  function submitPrompt() {
    const userMessage = prompt.trim()
    if (!userMessage || pending) return

    const contextMode = inferAgentContextMode({
      userMessage,
      hasReadingContext: Boolean(ambientSourceText),
      hasKnowledgeScope,
      hasResearchWorkspace,
    })
    const resolved = resolveAgentContext({
      mode: contextMode,
      readingText: ambientSourceText,
      readingContext: ambientContext,
      browserContext,
      fallbackText: workspace.sourceText,
    })

    if ((contextMode === "reading" || contextMode === "translation") && !resolved.sourceText) {
      setFallbackReason("")
      setErrorMessage("Capture a reading selection or choose an academic section before running this reading task.")
      return
    }

    // A conversation may continue within one context domain, but crossing from
    // Reading to Knowledge/Research/General starts a fresh durable conversation
    // so stale document grounding cannot leak through history.
    if (conversationMode.current && conversationMode.current !== contextMode) {
      conversationId.current = ""
      lastPayload.current = null
    }
    conversationMode.current = contextMode

    requestId.current += 1
    const readingGrounded = contextMode === "reading" || contextMode === "translation"
    const payload = buildAgentRunRequest({
      context: resolved.context,
      contextMode,
      sessionId,
      traceId: `trace-${sessionId}-${requestId.current}-${Date.now().toString(36)}`,
      requestId: requestId.current,
      userMessage,
      sourceText: resolved.sourceText,
      translatedText: readingGrounded ? workspace.translation?.translated_text || "" : "",
      sourceLanguage: workspace.sourceLanguage,
      targetLanguage: workspace.targetLanguage,
      conversationId: conversationId.current,
      workspaceId: workspace.activeResearchWorkspaceId,
      filesystemWorkspaceId,
      knowledgeDocumentIds: workspace.researchRetrievalScope.knowledgeDocumentIds,
      researchSourceIds: workspace.researchRetrievalScope.researchSourceIds,
      knowledgeContext,
      knowledgeAccessPolicy: defaultKnowledgeAccessPolicy,
      temporary,
      workflowAction,
    })
    lastPayload.current = payload
    execute(payload)
  }

  function confirmWriteTool() {
    const toolName = viewState.confirmationTool
    if (!toolName || pending) return

    if (durableRun?.status === "waiting") {
      setPending(true)
      void confirmAgentRuntimeRun(durableRun.run_id, toolName)
        .then((run) => followDurableRun(run, sessionId, requestId.current))
        .catch((error) => {
          setPending(false)
          setErrorMessage(error instanceof Error ? error.message : "Unable to confirm write action.")
        })
      return
    }

    const previous = lastPayload.current
    if (!previous) return
    requestId.current += 1
    const payload: AgentRunRequest = {
      ...previous,
      conversation_id: conversationId.current || previous.conversation_id,
      confirmed_write_tools: [toolName],
      request_id: requestId.current,
    }
    lastPayload.current = payload
    executeLegacyStream(payload)
  }

  function cancelRun() {
    if (cancelRequested) return
    if (durableRun && !["completed", "failed", "cancelled"].includes(durableRun.status)) {
      setCancelRequested(true)
      void cancelAgentRuntimeRun(durableRun.run_id)
        .then((run) => {
          setDurableRun(run)
          void hydrateDurableRun(run, sessionId)
        })
        .catch((error) => {
          setCancelRequested(false)
          setErrorMessage(error instanceof Error ? error.message : "Unable to cancel Agent run.")
        })
      return
    }
    if (!pending) return
    clearPendingAgentRun(activeRunId.current)
    setCancelRequested(true)
    streamHandle.current?.cancel()
  }

  function pauseRun() {
    if (!durableRun || durableRun.status !== "running") return
    void pauseAgentRuntimeRun(durableRun.run_id)
      .then(setDurableRun)
      .catch((error) => setErrorMessage(error instanceof Error ? error.message : "Unable to pause Agent run."))
  }

  function resumeRun() {
    if (!durableRun || durableRun.status !== "paused") return
    setPending(true)
    void resumeAgentRuntimeRun(durableRun.run_id)
      .then((run) => followDurableRun(
        run,
        sessionId,
        requestId.current,
        liveEvents.at(-1)?.sequence ?? -1,
      ))
      .catch((error) => {
        setPending(false)
        setErrorMessage(error instanceof Error ? error.message : "Unable to resume Agent run.")
      })
  }

  function retryRun() {
    if (!durableRun || durableRun.status !== "failed") return
    setPending(true)
    void retryAgentRuntimeRun(durableRun.run_id)
      .then((run) => {
        setTrace(null)
        setLiveEvents([])
        setRunSnapshot(null)
        followDurableRun(run, sessionId, requestId.current)
      })
      .catch((error) => {
        setPending(false)
        setErrorMessage(error instanceof Error ? error.message : "Unable to retry Agent run.")
      })
  }

  function setTemporaryMode(enabled: boolean) {
    if (pending) return
    setTemporary(enabled)
    conversationId.current = ""
    conversationMode.current = null
    lastPayload.current = null
    clearPendingAgentRun()
  }

  function retryTask(taskId: string) {
    if (durableRun) {
      if (durableRun.status === "failed") retryRun()
      return
    }
    const runId = runSnapshot?.run_id || viewState.runId
    if (!runId || pending || !runSnapshot?.retryable_task_ids.includes(taskId)) return
    requestId.current += 1
    const payload = buildAgentResumeRequest({
      runId,
      traceId: runSnapshot.trace_id || viewState.traceId,
      sessionId,
      requestId: requestId.current,
      acceptedAt: Date.now(),
    }, workspace.targetLanguage, taskId)
    lastPayload.current = payload
    transportRecoveryCount.current = 0
    execute(payload, true)
  }

  return {
    prompt,
    setPrompt,
    sourceText: previewContext.sourceText,
    context: previewContext.context,
    contextMode: previewContext.mode,
    viewState,
    traceEvents,
    decision,
    pending,
    cancelRequested,
    observabilityRefresh,
    temporary,
    workflowAction,
    setWorkflowAction,
    runSnapshot,
    durableRun,
    setTemporaryMode,
    submitPrompt,
    confirmWriteTool,
    cancelRun,
    pauseRun,
    resumeRun,
    retryRun,
    retryTask,
  }
}
