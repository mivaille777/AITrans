import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BookOpen, Check, ChevronDown, ChevronRight, FileText, LoaderCircle, MoreHorizontal, Paperclip, Share2 } from "lucide-react"
import { Link, useLocation, useSearchParams } from "react-router-dom"

import {
  dismissCompanionHandoff,
  getCompanionHandoff,
} from "../../api/companion"
import { getAvailableLlmModels, getLlmSettings, updateLlmSettings } from "../../api/llm-settings"
import { saveResearchNote } from "../../api/quick-actions"
import type { ResearchNoteSaveRequest } from "../../api/types"
import { queryKeys, queryPolling } from "../../shared/query/query-keys"
import { Badge } from "../../shared/ui/Badge"
import { Button } from "../../shared/ui/Button"
import { buttonClassName } from "../../shared/ui/button-styles"
import { EmptyState } from "../../shared/ui/EmptyState"
import { AnswerMarkdown } from "../evidence/AnswerMarkdown"
import { CitedAnswer } from "../evidence/CitedAnswer"
import {
  companionContextSnapshot,
  companionHandoffRuntimeSeed,
  createCompanionScope,
  EMPTY_COMPANION_CONTEXT,
  previousCompanionUserMessage,
  type CompanionContextSnapshot,
  type CompanionGenerationPhase,
  type CompanionRuntimeMessage,
} from "./companion-runtime"
import { companionLayoutClassNames } from "./companion-layout"
import ConversationHistoryPanel from "./ConversationHistoryPanel"
import { AgentToolsControl } from "./components/AgentToolsControl"
import { AgentRunInspector } from "./components/AgentRunInspector"
import { KnowledgeRetrievalControl } from "./components/KnowledgeRetrievalControl"
import { useCompanionConversationRuntime } from "./useCompanionConversationRuntime"

function companionGenerationPhaseLabel(phase?: CompanionGenerationPhase): string {
  switch (phase) {
    case "routing":
      return "Routing…"
    case "retrieving":
      return "Searching knowledge…"
    case "verifying":
      return "Verifying sources…"
    case "generating":
      return "Generating…"
    default:
      return "Generating…"
  }
}

export default function CompanionWorkspaceV2() {
  const queryClient = useQueryClient()
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const [editingMessageId, setEditingMessageId] = useState("")
  const [editingText, setEditingText] = useState("")
  const [branchingMessageId, setBranchingMessageId] = useState("")
  const [modelPickerOpen, setModelPickerOpen] = useState(false)
  const [contextPickerOpen, setContextPickerOpen] = useState(false)
  const handoffIdRef = useRef("")
  const usingHandoffRef = useRef(false)
  const modelPickerRef = useRef<HTMLDivElement>(null)
  const contextPickerRef = useRef<HTMLDivElement>(null)
  const messageScrollerRef = useRef<HTMLDivElement>(null)
  const messageNearBottomRef = useRef(true)

  const routedConversationId = searchParams.get("conversation") ?? ""

  const setConversationRoute = useCallback((conversationId: string) => {
    if (location.pathname !== "/chat") return
    const next = new URLSearchParams(searchParams)
    if (conversationId) next.set("conversation", conversationId)
    else next.delete("conversation")
    setSearchParams(next, { replace: true })
  }, [location.pathname, searchParams, setSearchParams])

  const runtime = useCompanionConversationRuntime({
    onConversationAccepted: setConversationRoute,
  })
  const runtimeConversationId = runtime.conversationId
  const openRuntimeConversation = runtime.openConversation
  const resetRuntime = runtime.reset

  const llmSettingsQuery = useQuery({
    queryKey: queryKeys.llm.settings,
    queryFn: getLlmSettings,
    staleTime: 30_000,
    retry: 0,
  })
  const modelCatalogQuery = useQuery({
    queryKey: queryKeys.llm.models(
      llmSettingsQuery.data?.provider ?? "deepseek",
      llmSettingsQuery.data?.base_url ?? "",
    ),
    queryFn: getAvailableLlmModels,
    enabled: modelPickerOpen && llmSettingsQuery.isSuccess,
    staleTime: 60_000,
    retry: 0,
  })
  const modelSwitchMutation = useMutation({
    mutationFn: async (model: string) => {
      const settings = llmSettingsQuery.data
      if (!settings) throw new Error("LLM settings are not ready yet.")
      return updateLlmSettings({
        provider: settings.provider,
        model,
        base_url: settings.base_url,
      })
    },
    onSuccess: (nextSettings) => {
      queryClient.setQueryData(queryKeys.llm.settings, nextSettings)
      void queryClient.invalidateQueries({ queryKey: queryKeys.llm.status })
      void queryClient.invalidateQueries({ queryKey: queryKeys.companion.chatStatus })
      setModelPickerOpen(false)
    },
  })

  useEffect(() => {
    if (!modelPickerOpen) return undefined

    const closeOnPointerDown = (event: PointerEvent) => {
      if (!modelPickerRef.current?.contains(event.target as Node)) {
        setModelPickerOpen(false)
      }
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setModelPickerOpen(false)
    }
    document.addEventListener("pointerdown", closeOnPointerDown)
    document.addEventListener("keydown", closeOnEscape)
    return () => {
      document.removeEventListener("pointerdown", closeOnPointerDown)
      document.removeEventListener("keydown", closeOnEscape)
    }
  }, [modelPickerOpen])

  useEffect(() => {
    if (!contextPickerOpen) return undefined
    const closeOnPointerDown = (event: PointerEvent) => {
      if (!contextPickerRef.current?.contains(event.target as Node)) {
        setContextPickerOpen(false)
      }
    }
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") setContextPickerOpen(false)
    }
    document.addEventListener("pointerdown", closeOnPointerDown)
    document.addEventListener("keydown", closeOnEscape)
    return () => {
      document.removeEventListener("pointerdown", closeOnPointerDown)
      document.removeEventListener("keydown", closeOnEscape)
    }
  }, [contextPickerOpen])

  const handoffQuery = useQuery({
    queryKey: queryKeys.companion.handoff,
    queryFn: getCompanionHandoff,
    refetchInterval: queryPolling.companionHandoff,
    staleTime: 0,
  })
  const handoff = handoffQuery.data?.handoff ?? null
  const readingHandoff = handoff && !(handoff.conversation_id ?? "").trim()
    ? handoff
    : null

  useEffect(() => {
    if (!routedConversationId || runtimeConversationId === routedConversationId) return
    queueMicrotask(() => void openRuntimeConversation(routedConversationId))
  }, [openRuntimeConversation, routedConversationId, runtimeConversationId])

  useEffect(() => {
    const activeHandoff = handoff
    if (!activeHandoff) {
      handoffIdRef.current = ""
      return
    }

    const nextId = activeHandoff.handoff_id
    if ((activeHandoff.conversation_id ?? "").trim()) {
      handoffIdRef.current = nextId
      return
    }
    if (routedConversationId) {
      handoffIdRef.current = nextId
      return
    }
    if (nextId === handoffIdRef.current && usingHandoffRef.current) return

    handoffIdRef.current = nextId
    usingHandoffRef.current = true
    const runtimeSeed = companionHandoffRuntimeSeed(activeHandoff)
    queueMicrotask(() => {
      resetRuntime(runtimeSeed)
      setEditingMessageId("")
      setEditingText("")
      setConversationRoute("")
    })
  }, [handoff, resetRuntime, routedConversationId, setConversationRoute])

  const dismissMutation = useMutation({
    mutationFn: (handoffId: string) => dismissCompanionHandoff(handoffId),
    onMutate: runtime.closeActiveStream,
    onSuccess: () => {
      usingHandoffRef.current = false
      runtime.reset({
        context: EMPTY_COMPANION_CONTEXT,
        contextMode: "general",
      })
      setConversationRoute("")
      void handoffQuery.refetch()
    },
  })

  const saveNoteMutation = useMutation({
    mutationFn: (payload: ResearchNoteSaveRequest) => saveResearchNote(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["research", "notes"] })
    },
  })

  function selectCurrentReading() {
    if (!readingHandoff) return
    usingHandoffRef.current = true
    runtime.reset(companionHandoffRuntimeSeed(readingHandoff))
    setConversationRoute("")
  }

  function startNewGeneralConversation() {
    usingHandoffRef.current = false
    runtime.reset({
      context: runtime.context,
      contextMode: "general",
      sessionId: createCompanionScope("session"),
      scopeId: createCompanionScope("draft-general"),
    })
    setConversationRoute("")
    setEditingMessageId("")
    setEditingText("")
  }

  function handleDeletedActive() {
    if (readingHandoff) {
      selectCurrentReading()
      return
    }
    startNewGeneralConversation()
  }

  async function attachCurrentReading() {
    if (!readingHandoff) return
    usingHandoffRef.current = true
    await runtime.attachReadingContext(companionContextSnapshot(readingHandoff))
  }

  async function rewriteFromUser(
    message: CompanionRuntimeMessage,
    replacementText: string,
  ) {
    const messageId = message.serverMessageId || message.id
    if (!messageId || branchingMessageId || runtime.activeRequestId !== null) return
    setBranchingMessageId(messageId)
    try {
      const started = await runtime.rewriteFromUser(message, replacementText)
      if (started) {
        setEditingMessageId("")
        setEditingText("")
      }
    } finally {
      setBranchingMessageId("")
    }
  }

  function commitEditMessage(message: CompanionRuntimeMessage) {
    const edited = editingText.trim()
    if (!edited || edited === message.content) {
      setEditingMessageId("")
      setEditingText("")
      return
    }
    void rewriteFromUser(message, edited)
  }

  function saveLinkedNote() {
    if (
      !runtime.conversationId ||
      runtime.contextMode !== "reading" ||
      !runtime.context.source_text ||
      runtime.context.source_kind.startsWith("knowledge_")
    ) {
      return
    }

    const lastAssistant = [...runtime.messages]
      .reverse()
      .find((message) => message.role === "assistant" && message.status === "complete")

    saveNoteMutation.mutate({
      source_text: runtime.context.source_text,
      translated_text: runtime.context.translated_text,
      source_language: runtime.context.source_language,
      target_language: runtime.context.target_language,
      resource_url: runtime.context.resource_url,
      resource_title: runtime.context.resource_title,
      section_heading: runtime.context.section_heading,
      context_before: runtime.context.context_before,
      context_after: runtime.context.context_after,
      source_kind: runtime.context.source_kind,
      ai_content: lastAssistant?.content || runtime.context.ai_content || "",
      ai_action: lastAssistant ? "conversation_answer" : runtime.context.ai_action || "",
      conversation_id: runtime.conversationId,
    })
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    runtime.sendMessage(undefined, undefined, {
      transport: runtime.selectedTools.length > 0 ? "agent" : "companion",
      enabledTools: runtime.selectedTools,
      agentContextMode: isKnowledgeContext ? "knowledge" : runtime.contextMode === "reading" ? "reading" : "general",
    })
  }

  const isKnowledgeContext = runtime.contextMode === "reading"
    && runtime.context.source_kind.startsWith("knowledge_")
  const contextTitle = runtime.contextMode === "general"
    ? "General Chat"
    : runtime.context.resource_title || runtime.context.section_heading || "Reading context"
  const canAttachSaved = Boolean(runtime.context.source_text)
  const branchBusy = Boolean(branchingMessageId) || runtime.activeRequestId !== null
  const activeModel = llmSettingsQuery.data?.model
    || [...runtime.messages]
      .reverse()
      .find((message) => message.model)?.model
    || "Llama 3.1 8B (Local)"
  const modelSwitchError = modelSwitchMutation.error instanceof Error
    ? modelSwitchMutation.error.message
    : ""
  const contextControlLabel = runtime.selectedTools.length > 0
    ? isKnowledgeContext ? "Knowledge" : "Research"
    : runtime.contextMode === "reading" ? isKnowledgeContext ? "Knowledge" : "Reading" : "General"
  const latestAssistant = [...runtime.messages]
    .reverse()
    .find((message) => message.role === "assistant")
  const showAgentInspector = runtime.inspectorView === "run"
    && (runtime.agentRunId || runtime.agentEvents.length > 0 || runtime.agentPhase !== "idle")

  function selectModel(model: string) {
    if (!model.trim() || modelSwitchMutation.isPending || model === activeModel) return
    modelSwitchMutation.mutate(model)
  }

  function scrollMessagesToBottom() {
    const element = messageScrollerRef.current
    if (!element) return
    element.scrollTop = element.scrollHeight
  }

  function handleMessageScroll() {
    const element = messageScrollerRef.current
    if (!element) return
    messageNearBottomRef.current = element.scrollHeight - element.scrollTop - element.clientHeight < 72
  }

  useEffect(() => {
    if (messageNearBottomRef.current) {
      requestAnimationFrame(scrollMessagesToBottom)
    }
  }, [runtime.messages])

  const showingHandoff = Boolean(
    readingHandoff &&
      !runtime.conversationId &&
      runtime.contextMode === "reading" &&
      runtime.context.source_text === readingHandoff.source_text,
  )

  return (
    <section className={companionLayoutClassNames.shell}>
      <ConversationHistoryPanel
        activeConversationId={runtime.conversationId}
        hasCurrentReading={Boolean(readingHandoff)}
        onOpen={(conversationId) => {
          usingHandoffRef.current = false
          setConversationRoute(conversationId)
          void runtime.openConversation(conversationId)
        }}
        onUseCurrentReading={selectCurrentReading}
        onNewGeneralConversation={startNewGeneralConversation}
        onDeletedActive={handleDeletedActive}
      />

      <aside className={companionLayoutClassNames.contextPanel}>
        {showAgentInspector ? (
          <AgentRunInspector
            context={runtime.context}
            phase={runtime.agentPhase}
            runId={runtime.agentRunId}
            traceId={runtime.agentTraceId}
            events={runtime.agentEvents}
            snapshot={runtime.agentSnapshot}
            selectedTools={runtime.selectedTools}
            confirmationTool={runtime.agentConfirmationTool}
            evidence={latestAssistant?.evidence ?? []}
            citations={latestAssistant?.citations ?? []}
            knowledgeDocumentIds={runtime.knowledgeDocumentIds}
            onViewContext={() => runtime.setInspectorView("context")}
            onConfirmWrite={() => runtime.confirmAgentWrite()}
          />
        ) : (
          <>
        <div className="ait-chat-context-header">
          <div className="ait-chat-context-heading">
            <span className="ait-chat-context-icon"><BookOpen size={19} /></span>
            <div className="min-w-0">
              <p className="ait-chat-section-eyebrow">
                {runtime.contextMode === "reading" ? "Reading context" : "Chat context"}
              </p>
              <h2 className="ait-chat-context-title">
                {contextTitle}
              </h2>
              <p className="ait-chat-context-count">
                {runtime.contextMode === "reading" ? "Current evidence" : "No sources attached"}
              </p>
            </div>
          </div>
          <ChevronRight size={18} className="ait-chat-context-chevron" aria-hidden="true" />
        </div>

        <div className="ait-chat-context-tabs">
          <span
            aria-hidden="true"
            className={`ait-chat-context-tab-indicator ${
              runtime.contextMode === "reading" ? "translate-x-full" : "translate-x-0"
            }`}
          />
          <button
            type="button"
            disabled={runtime.contextUpdating || runtime.activeRequestId !== null}
            className={`ait-chat-context-tab ${
              runtime.contextMode === "general" ? "text-slate-900" : "text-slate-500"
            }`}
            onClick={() => void runtime.detachReadingContext()}
          >
            General
          </button>
          <button
            type="button"
            disabled={
              runtime.contextUpdating ||
              runtime.activeRequestId !== null ||
              (!canAttachSaved && !readingHandoff)
            }
            className={`ait-chat-context-tab disabled:opacity-40 ${
              runtime.contextMode === "reading" ? "text-slate-900" : "text-slate-500"
            }`}
            onClick={() => void (
              canAttachSaved
                ? runtime.attachSavedContext()
                : attachCurrentReading()
            )}
          >
            {isKnowledgeContext ? "Knowledge" : "Reading"}
          </button>
        </div>

        <section className="ait-chat-reading-context-section">
          <div className="ait-chat-inspector-section-heading">
            <div className="ait-chat-inspector-section-title">
              <FileText size={18} />
              <div>
                <h3>Reading context</h3>
                <p>{runtime.context.source_text ? "1 source in context" : "No sources in context"}</p>
              </div>
            </div>
            <ChevronRight size={17} />
          </div>
          {runtime.context.source_text ? (
            <div className="ait-chat-source-item">
              <span className="ait-chat-source-icon"><FileText size={17} /></span>
              <span className="ait-chat-source-copy">
                <strong>{contextTitle}</strong>
                <small>{isKnowledgeContext ? "Knowledge source" : "Current selection"}</small>
              </span>
              <ChevronRight size={16} />
            </div>
          ) : (
            <p className="ait-chat-inspector-empty">Attach a reading selection to see its source here.</p>
          )}
        </section>

        <div key={runtime.contextMode} className="ait-context-panel-enter">
          {runtime.contextMode === "general" ? (
            <div className="ait-chat-context-empty">
              <p className="ait-chat-context-empty-title">No reading context attached.</p>
              <p className="ait-chat-context-empty-copy">
                Conversation history remains available. Attach the latest reading evidence whenever you need grounded analysis.
              </p>
              {readingHandoff && (
                <Button
                  className="mt-3"
                  size="xs"
                  disabled={runtime.contextUpdating}
                  onClick={() => void attachCurrentReading()}
                >
                  Attach current reading
                </Button>
              )}
            </div>
          ) : runtime.context.source_text ? (
            <>
              <ContextPreview context={runtime.context} />
              {readingHandoff && (
                <Button
                  className="mt-3"
                  size="xs"
                  disabled={runtime.contextUpdating}
                  onClick={() => void attachCurrentReading()}
                >
                  Replace with current reading
                </Button>
              )}
              {runtime.context.ai_content && (
                <div className="ait-chat-insight-card">
                  <div className="flex items-center gap-2">
                    <span className="ait-chat-neutral-badge">{isKnowledgeContext ? "Knowledge Insight" : "Quick Action"}</span>
                    {runtime.context.ai_action && (
                      <span className="ait-chat-context-action-label">
                        {runtime.context.ai_action}
                      </span>
                    )}
                  </div>
                  <p className="ait-chat-insight-copy">
                    {runtime.context.ai_content}
                  </p>
                </div>
              )}
              {runtime.conversationId && (
                isKnowledgeContext ? (
                  <div className="ait-chat-context-note">
                    This context already lives in canonical Knowledge. Continue the conversation here; use Agent Workspace when you want to save another linked Insight.
                  </div>
                ) : (
                  <div className="ait-chat-save-note">
                    <Button
                      size="xs"
                      disabled={saveNoteMutation.isPending}
                      onClick={saveLinkedNote}
                    >
                      {saveNoteMutation.isPending ? "Saving…" : "Save linked note"}
                    </Button>
                    {saveNoteMutation.isSuccess && (
                      <p className="ait-chat-success-note">
                        Research Note linked to this conversation.
                      </p>
                    )}
                  </div>
                )
              )}
            </>
          ) : (
            <p className="ait-chat-context-helper">
              Attach the current reading selection to use grounded chat.
            </p>
          )}

          {showingHandoff && readingHandoff && (
            <Button
              className="mt-4"
              size="xs"
              disabled={dismissMutation.isPending}
              onClick={() => dismissMutation.mutate(readingHandoff.handoff_id)}
            >
              Clear handoff
            </Button>
          )}
        </div>

        <KnowledgeRetrievalControl
          enabled={runtime.knowledgeEnabled}
          selectedDocumentIds={runtime.knowledgeDocumentIds}
          disabled={runtime.activeRequestId !== null || runtime.openingConversation}
          onEnabledChange={runtime.setKnowledgeEnabled}
          onScopeChange={runtime.setKnowledgeDocumentIds}
        />

        <section className="ait-chat-related-section">
          <div className="ait-chat-inspector-section-heading">
            <div className="ait-chat-inspector-section-title">
              <Share2 size={18} />
              <div>
                <h3>Related</h3>
                <p>Continue the research workflow</p>
              </div>
            </div>
          </div>
          <div className="ait-chat-related-links">
            <Link to="/research">Find similar papers</Link>
            <Link to="/research">Summarize this collection</Link>
            <Link to="/research">Extract key claims</Link>
            <Link to="/knowledge">Map the debate</Link>
          </div>
        </section>
          </>
        )}
      </aside>

      <div className={companionLayoutClassNames.chatColumn}>
        <header className={companionLayoutClassNames.conversationHeader}>
          <div className="ait-chat-conversation-heading">
            <h1 className="ait-chat-conversation-name">
              {contextTitle === "General Chat" ? "New conversation" : contextTitle}
            </h1>
            <p className="ait-chat-conversation-meta-line">
              {runtime.contextMode === "reading" ? "Reading context" : "Local workspace"}
              <span aria-hidden="true">·</span>
              {runtime.contextMode === "reading" ? "Today" : "Ready to chat"}
            </p>
          </div>
          <button type="button" className="ait-chat-conversation-menu" aria-label="Conversation actions">
            <MoreHorizontal size={19} />
          </button>
        </header>

        <div
          ref={messageScrollerRef}
          className={companionLayoutClassNames.messageScroller}
          onScroll={handleMessageScroll}
        >
          {runtime.messages.length === 0 && (
            <EmptyState
              title={runtime.contextMode === "general"
                ? "Start a General Chat"
                : isKnowledgeContext ? "Continue from this Knowledge card" : "Ask about this reading context"}
              description={runtime.contextMode === "general"
                ? "This conversation has no active reading evidence."
                : isKnowledgeContext
                  ? "The canonical card and its bounded source-paper context are supplied as grounded evidence."
                  : "The selected passage and bounded nearby context are supplied as reference evidence."}
              actions={!runtime.context.source_text && runtime.contextMode === "reading" ? (
                <>
                  <Link to="/reading" className={buttonClassName()}>Reading Context</Link>
                  <Link to="/research" className={buttonClassName({ variant: "primary" })}>
                    Research Notes
                  </Link>
                </>
              ) : undefined}
            />
          )}

          <div className="mt-4 space-y-3">
            {runtime.messages.map((message, index) => {
              const userBefore = message.role === "assistant"
                ? previousCompanionUserMessage(runtime.messages, index)
                : null
              const userServerId = message.role === "user"
                ? message.serverMessageId || message.id
                : ""
              const editing = message.role === "user" && editingMessageId === message.id

              return (
                <div
                  key={message.id}
                  className={`ait-chat-message-enter ait-chat-message ${message.role === "user" ? "is-user" : "is-assistant"}`}
                >
                  {message.role === "assistant" ? (
                    <>
                      {message.content ? (
                        <div className="ait-chat-answer max-w-none">
                          {(message.citations?.length ?? 0) > 0 ? (
                            <CitedAnswer
                              content={message.content}
                              evidence={message.evidence ?? []}
                              citations={message.citations ?? []}
                            />
                          ) : (
                            <AnswerMarkdown content={message.content} />
                          )}
                        </div>
                      ) : message.status === "streaming" ? (
                        <div className="flex items-center gap-2 text-slate-400">
                          <span className="h-3 w-3 animate-spin rounded-full border border-slate-300 border-t-slate-700" />
                          {companionGenerationPhaseLabel(message.generationPhase)}
                        </div>
                      ) : (
                        <p className="text-slate-400">
                          {message.status === "cancelled" ? "Generation stopped." : "No response content."}
                        </p>
                      )}
                      <div className="ait-chat-message-meta">
                        {message.status === "streaming" && (
                          <Badge className="ait-chat-message-badge" tone="info">
                            {companionGenerationPhaseLabel(message.generationPhase)}
                          </Badge>
                        )}
                        {message.status === "cancelled" && <Badge className="ait-chat-message-badge" tone="warning">Stopped</Badge>}
                        {message.status === "error" && <Badge className="ait-chat-message-badge" tone="danger">Failed</Badge>}
                        {message.status === "complete" && message.provider && (
                          <Badge className="ait-chat-message-badge" tone="success">
                            {message.provider}{message.model ? ` · ${message.model}` : ""}
                          </Badge>
                        )}
                        {message.status === "complete" && message.knowledgeEnabled && (
                          <Badge className="ait-chat-message-badge" tone={(message.evidence?.length ?? 0) > 0 ? "info" : "warning"}>
                            {(message.evidence?.length ?? 0) > 0
                              ? `Knowledge · ${message.evidence?.length} sources`
                              : "General answer · No knowledge sources"}
                          </Badge>
                        )}
                        {userBefore && message.status !== "streaming" && (
                          <button
                            type="button"
                            disabled={branchBusy}
                            className="ait-chat-message-action disabled:opacity-40"
                            onClick={() => void rewriteFromUser(userBefore, userBefore.content)}
                          >
                            {message.status === "complete" ? "Regenerate" : "Retry"}
                          </button>
                        )}
                      </div>
                    </>
                  ) : editing ? (
                    <div>
                      <textarea
                        autoFocus
                        className="min-h-24 w-full resize-y rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm leading-6 text-white outline-none focus:border-slate-500"
                        value={editingText}
                        onChange={(event) => setEditingText(event.target.value)}
                      />
                      <div className="mt-2 flex justify-end gap-2">
                        <button
                          type="button"
                          className="text-[10px] text-slate-400 hover:text-white"
                          onClick={() => {
                            setEditingMessageId("")
                            setEditingText("")
                          }}
                        >
                          Cancel
                        </button>
                        <button
                          type="button"
                          className="rounded bg-white px-2 py-1 text-[10px] font-medium text-slate-900 disabled:opacity-40"
                          disabled={!editingText.trim() || branchBusy}
                          onClick={() => commitEditMessage(message)}
                        >
                          Resend
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <p className="whitespace-pre-wrap">{message.content}</p>
                      {userServerId && !userServerId.startsWith("user-local-") && (
                        <div className="ait-chat-user-action-row">
                          <button
                            type="button"
                            disabled={branchBusy}
                            className="ait-chat-message-action is-user-action disabled:opacity-40"
                            onClick={() => {
                              setEditingMessageId(message.id)
                              setEditingText(message.content)
                            }}
                          >
                            Edit & resend
                          </button>
                        </div>
                      )}
                    </>
                  )}
                </div>
              )
            })}

            {runtime.errorMessage && (
              <p className="ait-chat-error-message">
                {runtime.errorMessage}
              </p>
            )}
          </div>
        </div>

        <form
          className={companionLayoutClassNames.composer}
          onSubmit={handleSubmit}
        >
          {!runtime.chatAvailable && runtime.chatStatusLoaded && (
            <p className="ait-chat-unavailable-message">
              AI Chat 未配置：{runtime.chatStatusDetail}
            </p>
          )}
          <div className="ait-chat-composer-controls">
            <div className="ait-chat-context-picker" ref={contextPickerRef}>
              <button
                type="button"
                className="ait-chat-composer-control ait-chat-context-picker-button"
                aria-haspopup="menu"
                aria-expanded={contextPickerOpen}
                disabled={runtime.activeRequestId !== null || runtime.contextUpdating}
                onClick={() => setContextPickerOpen((open) => !open)}
              >
                <span>{contextControlLabel}</span>
                <ChevronDown size={14} />
              </button>
              {contextPickerOpen && (
                <div className="ait-chat-context-picker-menu" role="menu" aria-label="Chat context">
                  <button
                    type="button"
                    role="menuitem"
                    className={`ait-chat-context-picker-option ${runtime.contextMode === "general" ? "is-active" : ""}`}
                    onClick={() => {
                      void runtime.detachReadingContext()
                      runtime.setSelectedTools([])
                      setContextPickerOpen(false)
                    }}
                  >
                    <span><strong>General</strong><small>Chat without a reading selection.</small></span>
                    {runtime.contextMode === "general" && <Check size={14} />}
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    disabled={!canAttachSaved && !readingHandoff}
                    className={`ait-chat-context-picker-option ${runtime.contextMode === "reading" ? "is-active" : ""}`}
                    onClick={() => {
                      if (canAttachSaved) void runtime.attachSavedContext()
                      else void attachCurrentReading()
                      setContextPickerOpen(false)
                    }}
                  >
                    <span><strong>{isKnowledgeContext ? "Knowledge" : "Reading"}</strong><small>Ground the next message in current context.</small></span>
                    {runtime.contextMode === "reading" && <Check size={14} />}
                  </button>
                </div>
              )}
            </div>
            <div className="ait-chat-model-picker" ref={modelPickerRef}>
              <button
                type="button"
                className="ait-chat-composer-control ait-chat-composer-model-button"
                aria-haspopup="listbox"
                aria-expanded={modelPickerOpen}
                disabled={runtime.activeRequestId !== null || modelSwitchMutation.isPending}
                onClick={() => setModelPickerOpen((open) => !open)}
              >
                <span className="ait-chat-composer-model-label">{activeModel}</span>
                <ChevronDown size={14} />
              </button>
              {modelPickerOpen && (
                <div className="ait-chat-model-menu" role="listbox" aria-label="Available models">
                  <div className="ait-chat-model-menu-heading">
                    <span>Available models</span>
                    {modelCatalogQuery.isFetching && <LoaderCircle size={13} className="ait-chat-model-menu-spinner" />}
                  </div>
                  {modelCatalogQuery.isPending ? (
                    <p className="ait-chat-model-menu-message">Checking the current API key…</p>
                  ) : modelCatalogQuery.isError ? (
                    <p className="ait-chat-model-menu-message is-error">Unable to load models. Try again.</p>
                  ) : !modelCatalogQuery.data?.available ? (
                    <p className="ait-chat-model-menu-message is-error">
                      {modelCatalogQuery.data?.detail || "No models are available for this API key."}
                    </p>
                  ) : (
                    <div className="ait-chat-model-options">
                      {modelCatalogQuery.data.models.map((model) => (
                        <button
                          key={model.id}
                          type="button"
                          role="option"
                          aria-selected={model.id === activeModel}
                          className="ait-chat-model-option"
                          disabled={modelSwitchMutation.isPending}
                          onClick={() => selectModel(model.id)}
                        >
                          <span>{model.id}</span>
                          {model.id === activeModel && <Check size={15} />}
                        </button>
                      ))}
                    </div>
                  )}
                  {modelSwitchError && <p className="ait-chat-model-menu-message is-error">{modelSwitchError}</p>}
                </div>
              )}
            </div>
            <button
              type="button"
              className={`ait-chat-composer-knowledge ait-chat-composer-knowledge-button ${runtime.knowledgeEnabled ? "is-on" : ""}`}
              role="switch"
              aria-checked={runtime.knowledgeEnabled}
              disabled={runtime.activeRequestId !== null || runtime.openingConversation}
              onClick={() => runtime.setKnowledgeEnabled(!runtime.knowledgeEnabled)}
            >
              <span className="ait-chat-composer-knowledge-dot" />
              Knowledge {runtime.knowledgeEnabled ? "on" : "off"}
            </button>
            <AgentToolsControl
              selectedTools={runtime.selectedTools}
              disabled={runtime.activeRequestId !== null || runtime.openingConversation}
              hasReadingContext={Boolean(runtime.context.source_text.trim())}
              onChange={runtime.setSelectedTools}
            />
          </div>
          <div className="ait-chat-composer-row">
            <label className="ait-chat-composer-field">
              <Paperclip size={19} className="ait-chat-composer-attach" />
              <textarea
                className="ait-chat-composer-input"
                placeholder={runtime.activeRequestId === null
                  ? runtime.contextMode === "general" ? "Ask anything, or type '/' for commands…" : "Ask a question, or type '/' for commands…"
                  : "当前回复仍在生成，可先编辑下一条消息…"}
                value={runtime.draft}
                disabled={runtime.openingConversation}
                onChange={(event) => runtime.setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault()
                    event.currentTarget.form?.requestSubmit()
                  }
                }}
              />
            </label>
            {runtime.activeRequestId !== null ? (
              <Button className="ait-chat-send-button" type="button" variant="danger" size="md" onClick={runtime.cancelStream}>
                Stop
              </Button>
            ) : (
              <Button
                className="ait-chat-send-button"
                type="submit"
                variant="primary"
                size="md"
                disabled={
                  !runtime.chatAvailable ||
                  !runtime.draft.trim() ||
                  runtime.openingConversation ||
                  Boolean(branchingMessageId)
                }
              >
                Send
              </Button>
            )}
          </div>
          <p className="ait-chat-composer-helper">
            Enter to send · Shift+Enter for a new line · {runtime.contextMode === "reading" ? isKnowledgeContext ? "Knowledge context" : "Reading context" : "General"}{runtime.knowledgeEnabled ? " · Knowledge on" : ""}
          </p>
        </form>
      </div>
    </section>
  )
}

function ContextPreview({ context }: { context: CompanionContextSnapshot }) {
  const knowledgeContext = context.source_kind.startsWith("knowledge_")
  return (
    <div className="ait-chat-context-preview">
      <div className="ait-chat-context-card">
        <p className="ait-chat-card-eyebrow">
          {knowledgeContext ? "Knowledge card" : "Selection"}
        </p>
        <p className="ait-chat-context-card-copy">
          {context.source_text}
        </p>
      </div>
      {context.translated_text && (
        <div className="ait-chat-context-card">
          <p className="ait-chat-card-eyebrow">
            Translation
          </p>
          <p className="ait-chat-context-card-copy is-muted">
            {context.translated_text}
          </p>
        </div>
      )}
    </div>
  )
}
