import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { BookOpen, Bot, Check, ChevronDown, ChevronRight, FileText, LoaderCircle, MessageCircle, PanelRightClose, Send, Share2, Square } from "lucide-react"
import { Link, useLocation, useSearchParams } from "react-router-dom"

import {
  dismissCompanionHandoff,
  getCompanionHandoff,
} from "../../api/companion"
import { getAvailableLlmModels, getLlmSettings, updateLlmSettings } from "../../api/llm-settings"
import { saveResearchNote } from "../../api/quick-actions"
import { exportConversationMarkdown } from "../../api/conversations"
import { downloadMarkdown } from "../../shared/files/markdown-export"
import { WorkspaceFilesPanel } from "./components/WorkspaceFilesPanel"
import type { ResearchNoteSaveRequest } from "../../api/types"
import { queryKeys, queryPolling } from "../../shared/query/query-keys"
import { Badge } from "../../shared/ui/Badge"
import { Button } from "../../shared/ui/Button"
import { buttonClassName } from "../../shared/ui/button-styles"
import { EmptyState } from "../../shared/ui/EmptyState"
import { AnswerMarkdown } from "../evidence/AnswerMarkdown"
import { ExecutionResultCard } from "../../shared/components/ExecutionResultCard"
import { conversationArtifactUrl, wantsPlotExecution } from "../../api/execution-results"
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
import { ChatSessionControls } from "./components/ChatSessionControls"
import { useChatConfiguration } from "./hooks/useChatConfiguration"
import { AgentRunInspector } from "./components/AgentRunInspector"
import { ChatConversationHeader } from "./components/ChatConversationHeader"
import { KnowledgeRetrievalControl } from "./components/KnowledgeRetrievalControl"
import { useCompanionConversationRuntime } from "./useCompanionConversationRuntime"
import "./ChatWorkspace.css"

const workspaceToolLabels: Record<string, string> = {
  list_workspace_files: "浏览文件", search_workspace_text: "搜索文件内容", read_workspace_text: "读取文本",
  create_workspace_file: "新建文件", edit_workspace_file: "编辑文件", write_workspace_file: "重写文件",
  create_workspace_directory: "新建文件夹", undo_workspace_change: "撤销文件变更",
}

function companionGenerationPhaseLabel(phase?: CompanionGenerationPhase, message?: CompanionRuntimeMessage): string {
  const outline = message?.knowledgeRecovery?.reading_coverage
  if (phase === "reading_document" && outline?.basis === "stage_headers") {
    return outline.total_chunks ? `正在核对阶段目录… ${outline.processed_chunks}/${outline.total_chunks}` : "正在核对阶段目录…"
  }
  const coverage = message?.knowledgeRecovery?.full_read
  if (phase === "reading_document" && coverage?.total_chunks) {
    return `正在阅读全文… ${coverage.processed_chunks}/${coverage.total_chunks}`
  }
  switch (phase) {
    case "routing":
      return "Routing…"
    case "retrieving":
      return "Searching knowledge…"
    case "recovering":
      return "正在恢复资料读取…"
    case "reading_document":
      return "正在阅读全文…"
    case "verifying":
      return "Verifying sources…"
    case "generating":
      if (message?.knowledgeRecovery?.reading_task?.answer_kind === "overview") return "正在整理文档概览…"
      if (message?.knowledgeRecovery?.reading_task?.answer_kind === "stages") return "正在整理阶段划分…"
      return "Generating…"
    default:
      return "Generating…"
  }
}

function companionKnowledgeBehaviorLabel(message: CompanionRuntimeMessage): string | null {
  const recovery = message.knowledgeRecovery
  if (recovery?.outcome === "partial") return "全文读取未完成"
  if (recovery?.outcome === "blocked") return "暂时无法核验"
  if (recovery?.outcome === "fallback") {
    if (recovery.reading_coverage?.basis === "stage_headers") return "阶段回答未通过核验"
    if (recovery.full_read?.complete) {
      if (recovery.reason === "answer_incomplete") return "正文已读完，回答不完整"
      return recovery.reason === "full_read_synthesis_failed"
        ? "正文已读完，摘要生成失败" : "正文已读完，摘要未通过核验"
    }
    return "已使用证据兜底"
  }
  const ragDocuments = recovery?.rag_reading?.documents
  if (ragDocuments?.length) {
    const expectedStages = ragDocuments.reduce((sum, d) => sum + d.expected_stages.length, 0)
    const readStages = ragDocuments.reduce((sum, d) => sum + d.read_stages.length, 0)
    const stageLabel = expectedStages ? ` · 阶段 ${readStages}/${expectedStages}` : ""
    if (recovery?.reading_coverage?.complete) return `阶段目录已核验${stageLabel}`
    if (recovery?.full_read?.complete) {
      const total = ragDocuments.reduce((sum, d) => sum + d.inventory_chunks, 0)
      const read = ragDocuments.reduce((sum, d) => sum + d.read_chunks, 0)
      const labels = new Set([...message.content.matchAll(/\[(\d+)\]/g)].map(match => match[1]))
      return `正文 ${read}/${total}${stageLabel} · 引用 ${labels.size} 个片段`
    }
  }
  if (recovery?.reading_coverage?.basis === "stage_headers" && recovery.reading_coverage.complete) return "阶段目录已核验"
  if (recovery?.full_read?.complete) return "索引正文已完整读取"
  const decision = message.knowledgeDecision
  const retrieved = message.knowledgeRetrieved
    ?? Boolean(message.knowledgeEnabled && (message.evidence?.length ?? 0) > 0)
  if (retrieved) {
    const documentCount = message.knowledgeDocumentCount ?? new Set(
      (message.evidence ?? []).map((item) => item.source_id).filter(Boolean),
    ).size
    const chunkCount = message.knowledgeChunkCount ?? message.evidence?.length ?? 0
    if (documentCount > 0 || chunkCount > 0) {
      return `Knowledge · ${documentCount} document${documentCount === 1 ? "" : "s"} · 已读取 ${chunkCount} 个片段`
    }
    return "Knowledge · searched · no evidence"
  }
  if (!decision) return null
  if (decision.reason_code === "catalog_request") {
    return "Knowledge · directory"
  }
  if (decision.reason_code === "current_context_sufficient") {
    return "Knowledge · skipped / Current context sufficient"
  }
  if (decision.reason_code === "explicit_never") {
    return "Knowledge · skipped / Never search"
  }
  return "Knowledge · skipped"
}

export default function CompanionWorkspaceV2() {
  const queryClient = useQueryClient()
  const location = useLocation()
  const [searchParams, setSearchParams] = useSearchParams()
  const [editingMessageId, setEditingMessageId] = useState("")
  const [editingText, setEditingText] = useState("")
  const [branchingMessageId, setBranchingMessageId] = useState("")
  const [modelPickerOpen, setModelPickerOpen] = useState(false)
  const [contextPanelOpen, setContextPanelOpen] = useState(() =>
    typeof window.matchMedia !== "function" || window.matchMedia("(min-width: 1100px)").matches,
  )
  const handoffIdRef = useRef("")
  const usingHandoffRef = useRef(false)
  const modelPickerRef = useRef<HTMLDivElement>(null)
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
    clientSurface: "main",
    onConversationAccepted: setConversationRoute,
  })
  const markdownExportMutation = useMutation({
    mutationFn: async (messageId?: string) => {
      const document = await exportConversationMarkdown(runtime.conversationId, messageId)
      downloadMarkdown(document)
    },
  })
  const chatConfig = useChatConfiguration(runtime.sessionId)
  const restorePendingPlan = runtime.restorePendingPlan
  const currentAgentRunId = runtime.agentRunId
  const openingChatConversation = runtime.openingConversation
  useEffect(() => {
    const runId = chatConfig.configuration.data?.pending_run_id
    if (runId && currentAgentRunId !== runId && !openingChatConversation) {
      void restorePendingPlan(runId).catch(() => undefined)
    }
  }, [chatConfig.configuration.data?.pending_run_id, currentAgentRunId, openingChatConversation, restorePendingPlan])
  useEffect(() => {
    if (runtime.agentPhase === "completed" || runtime.agentPhase === "confirmation_required" || runtime.agentPhase === "cancelled") {
      void queryClient.invalidateQueries({queryKey:["chat-configuration",runtime.sessionId]})
    }
  }, [runtime.agentPhase, runtime.sessionId, queryClient])
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
    if (!canSend) return
    runtime.sendMessage(undefined, undefined, {
      transport: chatConfig.configuration.data?.execution_mode || runtime.selectedTools.length > 0 ? "agent" : "companion",
      chatConfiguration: Boolean(chatConfig.configuration.data?.execution_mode) || wantsPlotExecution(runtime.draft),
      enabledTools: runtime.selectedTools,
      agentContextMode: isKnowledgeContext ? "knowledge" : runtime.contextMode === "reading" ? "reading" : "general",
    })
  }

  const isKnowledgeContext = runtime.contextMode === "reading"
    && runtime.context.source_kind.startsWith("knowledge_")
  const sendBlockedReason = chatConfig.configuration.isPending || chatConfig.mutation.isPending
    ? "正在更新会话配置…"
    : chatConfig.configuration.isError
      ? "会话配置加载失败，请重试。"
      : chatConfig.configuration.data?.pending_run_id || runtime.pendingPlan
        ? "请先确认执行或取消当前计划。"
        : runtime.openingConversation
    ? "正在加载会话…"
    : runtime.recoveryState !== "idle"
      ? runtime.recoveryDetail || "会话连接需要恢复，请重试。"
      : runtime.conversationBusyElsewhere
        ? "此会话正在另一个窗口中生成回复，请等待完成。"
        : runtime.contextUpdating
          ? "正在更新上下文…"
          : branchingMessageId
            ? "正在重新发送消息…"
            : !runtime.chatAvailable
              ? runtime.chatStatusLoaded
                ? runtime.chatStatusDetail || "AI Chat 暂不可用，请检查模型配置或重试。"
                : "正在检查 AI Chat 连接…"
              : runtime.contextMode === "reading" && !runtime.context.source_text.trim()
                ? "请先附加阅读内容，或切换到 General。"
                : ""
  const canSend = runtime.activeRequestId === null
    && !sendBlockedReason
    && Boolean(runtime.draft.trim())
  const contextTitle = runtime.contextMode === "general"
    ? "General Chat"
    : runtime.context.resource_title || runtime.context.section_heading || "Reading context"
  const canAttachSaved = Boolean(runtime.context.source_text)
  const branchBusy = Boolean(branchingMessageId) || runtime.activeRequestId !== null || Boolean(runtime.pendingPlan) || Boolean(chatConfig.configuration.data?.pending_run_id)
  const activeModel = llmSettingsQuery.data?.model
    || [...runtime.messages]
      .reverse()
      .find((message) => message.model)?.model
    || (llmSettingsQuery.isPending ? "模型加载中…" : "选择模型")
  const modelSwitchError = modelSwitchMutation.error instanceof Error
    ? modelSwitchMutation.error.message
    : ""
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
    <section className={`${companionLayoutClassNames.shell}${contextPanelOpen ? "" : " is-context-closed"}`} aria-label="Chat workspace">
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

      <aside id="chat-context-panel" className={companionLayoutClassNames.contextPanel} hidden={!contextPanelOpen} aria-label="Chat context and run details">
        <button type="button" className="ait-chat-context-close" onClick={() => setContextPanelOpen(false)} aria-label="Close context panel">
          <PanelRightClose size={18} />
        </button>
        <WorkspaceFilesPanel sessionId={runtime.sessionId} workspaceId={chatConfig.configuration.data?.filesystem_workspace_id || ""}
          readOnly={chatConfig.configuration.data?.filesystem_access === "read_only"}
          busy={runtime.activeRequestId !== null || Boolean(chatConfig.configuration.data?.pending_run_id)}
          refreshKey={`${runtime.agentRunId}:${runtime.agentPhase}:${runtime.agentEvents.filter(event => event.event_type === "tool_result").length}`} />
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
          policy={runtime.knowledgeAccessPolicy}
          enabled={runtime.knowledgeEnabled}
          selectedDocumentIds={runtime.knowledgeDocumentIds}
          scopeLabel={runtime.knowledgeDocumentIds.length > 0
            ? `${runtime.knowledgeDocumentIds.length} selected documents`
            : isKnowledgeContext ? "Current document" : "All documents"}
          disabled={runtime.activeRequestId !== null || runtime.openingConversation}
          onPolicyChange={runtime.setKnowledgeAccessPolicy}
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
        <ChatConversationHeader
          title={contextTitle === "General Chat" ? "New conversation" : contextTitle}
          contextLabel={runtime.contextMode === "reading" ? "Reading context" : "Local workspace"}
          statusLabel={runtime.activeRequestId !== null ? "Generating…" : runtime.openingConversation ? "Loading conversation…" : "Ready to chat"}
          contextPanelOpen={contextPanelOpen}
          newChatDisabled={runtime.activeRequestId !== null || runtime.openingConversation}
          onToggleContext={() => setContextPanelOpen((open) => !open)}
          onNewChat={startNewGeneralConversation}
          onExportMarkdown={runtime.conversationId && runtime.messages.some((message) => message.status === "complete" && message.content) && !markdownExportMutation.isPending ? () => markdownExportMutation.mutate(undefined) : undefined}
          onViewContext={() => {
            runtime.setInspectorView("context")
            setContextPanelOpen(true)
          }}
          onViewRun={runtime.agentRunId || runtime.agentEvents.length > 0 ? () => {
            runtime.setInspectorView("run")
            setContextPanelOpen(true)
          } : undefined}
        />

        <div
          ref={messageScrollerRef}
          className={companionLayoutClassNames.messageScroller}
          onScroll={handleMessageScroll}
        >
          {runtime.messages.length === 0 && (
            <EmptyState
              className="ait-chat-empty-state"
              icon={<MessageCircle size={24} />}
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

          <div className="ait-chat-messages">
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
                      <span className="ait-chat-avatar" aria-label="AITrans assistant"><Bot size={23} strokeWidth={2} /></span>
                      {(message.executionResults ?? []).map(result => <ExecutionResultCard key={result.sandbox_id} result={result}
                        artifactUrl={(fileId, inline) => conversationArtifactUrl(runtime.conversationId, message.serverMessageId || message.id, result.sandbox_id, fileId, inline)} />)}
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
                          {companionGenerationPhaseLabel(message.generationPhase, message)}
                        </div>
                      ) : (
                        <p className="text-slate-400">
                          {message.status === "cancelled" ? "Generation stopped." : message.status === "error" ? "本次未能生成有效回答，请重试。" : "No response content."}
                        </p>
                      )}
                      <div className="ait-chat-message-meta">
                        {message.status === "complete" && message.content && runtime.conversationId && message.serverMessageId && (
                          <button type="button" className="ait-chat-message-action disabled:opacity-40" disabled={markdownExportMutation.isPending} onClick={() => markdownExportMutation.mutate(message.serverMessageId)}>
                            导出 Markdown
                          </button>
                        )}
                        {message.status === "streaming" && (
                          <Badge className="ait-chat-message-badge" tone="info">
                            {companionGenerationPhaseLabel(message.generationPhase, message)}
                          </Badge>
                        )}
                        {message.status === "cancelled" && <Badge className="ait-chat-message-badge" tone="warning">Stopped</Badge>}
                        {message.status === "error" && <Badge className="ait-chat-message-badge" tone="danger">Failed</Badge>}
                        {message.status === "complete" && message.provider && (
                          <Badge className="ait-chat-message-badge" tone="success">
                            {message.provider}{message.model ? ` · ${message.model}` : ""}
                          </Badge>
                        )}
                        {message.status === "complete" && companionKnowledgeBehaviorLabel(message) && (
                          <Badge
                            className="ait-chat-message-badge"
                            tone={message.knowledgeRetrieved ? "info" : "warning"}
                          >
                            {companionKnowledgeBehaviorLabel(message)}
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
          {runtime.pendingPlan && (
            <div className="ait-chat-unavailable-message" role="status">
              <span>计划已生成：{runtime.pendingPlan.multi_step_plan?.goal}。确认后执行。</span>
              <div className="w-full">
                {runtime.pendingPlan.multi_step_plan?.steps.map(step => <div key={step.step_id} className="my-2 text-xs">
                  <strong>{workspaceToolLabels[step.tool_name] || step.tool_name} · {String(step.arguments.relative_path || "")}</strong>
                  {step.file_preview?.relative_path && <><p>{step.file_preview.size_before} → {step.file_preview.size_after} 字节</p>
                    <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-all">{step.file_preview.diff || (step.file_preview.operation === "mkdir" ? "创建文件夹" : "变更为上方显示的文件状态。")}</pre>
                    {step.file_preview.diff_truncated && <p>差异过长，仅显示部分内容。</p>}</>}
                </div>)}
              </div>
              <Button size="sm" disabled={runtime.activeRequestId !== null} onClick={() => runtime.confirmAgentPlan("approve")}>确认执行</Button>
              <Button size="sm" disabled={runtime.activeRequestId !== null} onClick={() => runtime.confirmAgentPlan("reject")}>取消计划</Button>
            </div>
          )}
          {chatConfig.mutation.error && <p role="alert" className="ait-chat-model-menu-message is-error">{chatConfig.mutation.error instanceof Error ? chatConfig.mutation.error.message : "操作失败，请重试。"}</p>}
          {markdownExportMutation.error && <p role="alert" className="ait-chat-model-menu-message is-error">{markdownExportMutation.error instanceof Error ? markdownExportMutation.error.message : "Markdown 导出失败，请重试。"}</p>}
          {runtime.agentPhase === "confirmation_required" && !runtime.pendingPlan && (
            <div className="ait-chat-unavailable-message" role="status">
              <span>A tool is waiting for your confirmation.</span>
              <Button size="sm" onClick={() => {
                runtime.setInspectorView("run")
                setContextPanelOpen(true)
              }}>Review tool action</Button>
            </div>
          )}
          {runtime.activeRequestId === null && sendBlockedReason && (
            <div className="ait-chat-unavailable-message" role="status" id="chat-send-status">
              <span>{sendBlockedReason}</span>
              {chatConfig.configuration.data?.pending_run_id && !runtime.pendingPlan ? <Button size="sm" onClick={() => void restorePendingPlan(chatConfig.configuration.data!.pending_run_id)}>恢复待确认计划</Button> : chatConfig.configuration.isError ? <Button size="sm" onClick={() => void chatConfig.configuration.refetch()}>重试</Button> : !runtime.openingConversation && runtime.recoveryState === "offline" ? (
                <Button size="sm" onClick={() => void runtime.retryRecovery()}>重试连接</Button>
              ) : !runtime.chatAvailable && runtime.chatStatusLoaded && runtime.recoveryState === "idle" ? (
                <Button size="sm" onClick={() => void queryClient.invalidateQueries({ queryKey: queryKeys.companion.chatStatus })}>重试连接</Button>
              ) : null}
            </div>
          )}
          <div className="ait-chat-composer-controls">
            <div className="ait-chat-model-picker" ref={modelPickerRef}>
              <button
                type="button"
                className="ait-chat-composer-control ait-chat-composer-model-button"
                aria-haspopup="listbox"
                aria-expanded={modelPickerOpen}
                disabled={branchBusy || modelSwitchMutation.isPending}
                onClick={() => setModelPickerOpen((open) => !open)}
              >
                <Bot size={18} />
                <span className="ait-chat-composer-model-label">{activeModel}</span>
                <ChevronDown size={14} />
              </button>
              {modelPickerOpen && (
                <div className="ait-chat-model-menu" role="listbox" aria-label="Available models">
                  <div className="ait-chat-model-menu-heading">
                    <span>选择模型</span>
                    {modelCatalogQuery.isFetching && <LoaderCircle size={13} className="ait-chat-model-menu-spinner" />}
                  </div>
                  {modelCatalogQuery.isPending ? (
                    <p className="ait-chat-model-menu-message">正在加载可用模型…</p>
                  ) : modelCatalogQuery.isError ? (
                    <p className="ait-chat-model-menu-message is-error">模型列表加载失败，请重试。</p>
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
            <ChatSessionControls config={chatConfig} disabled={runtime.activeRequestId !== null || runtime.openingConversation || runtime.conversationBusyElsewhere} selectedTools={runtime.selectedTools} onToolsChange={runtime.setSelectedTools} hasReadingContext={Boolean(runtime.context.source_text.trim()) || Boolean(chatConfig.configuration.data?.attachments.length)} knowledgePolicy={runtime.knowledgeAccessPolicy} onKnowledgePolicyChange={runtime.setKnowledgeAccessPolicy}/>
          </div>
          <div className="ait-chat-composer-row">
            <label className="ait-chat-composer-field">
              <textarea
                className="ait-chat-composer-input"
                aria-label="Message"
                placeholder={runtime.activeRequestId === null
                  ? runtime.contextMode === "general" ? "Ask anything…" : "Ask about the current context…"
                  : "当前回复仍在生成，可先编辑下一条消息…"}
                value={runtime.draft}
                disabled={runtime.openingConversation}
                onChange={(event) => runtime.setDraft(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing && event.keyCode !== 229) {
                    event.preventDefault()
                    if (canSend) event.currentTarget.form?.requestSubmit()
                  }
                }}
              />
            </label>
            {runtime.activeRequestId !== null ? (
              <Button className="ait-chat-send-button" type="button" variant="danger" size="md" onClick={runtime.cancelStream}>
                <Square size={16} />
                Stop
              </Button>
            ) : (
              <Button
                className="ait-chat-send-button"
                type="submit"
                variant="primary"
                size="md"
                disabled={!canSend}
                title={sendBlockedReason || (!runtime.draft.trim() ? "请输入消息" : "发送消息")}
                aria-describedby={sendBlockedReason ? "chat-send-status" : undefined}
              >
                <Send size={19} />
                Send
              </Button>
            )}
          </div>
          <p className="ait-chat-composer-helper">
            Enter 发送 · Shift+Enter 换行 · {chatConfig.configuration.data?.execution_mode === "plan_execute" ? "Plan–Execute：确认计划后执行" : "常规（ReAct）"}
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
