import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import ReactMarkdown from "react-markdown"
import { Link, useSearchParams } from "react-router-dom"

import {
  dismissCompanionHandoff,
  getCompanionChatStatus,
  getCompanionHandoff,
} from "../../api/companion"
import {
  streamCompanionChat,
  type CompanionChatStreamHandle,
} from "../../api/companion-stream"
import {
  getConversation,
  rewindConversation,
  updateConversationContext,
} from "../../api/conversations"
import { saveResearchNote } from "../../api/quick-actions"
import type {
  ChatContextMode,
  CompanionChatMessage,
  CompanionChatRequest,
  CompanionChatStreamEvent,
  CompanionHandoff,
  ConversationContextUpdate,
  ConversationDetail,
  ConversationMessage,
  ResearchNoteSaveRequest,
} from "../../api/types"
import { queryKeys, queryPolling } from "../../shared/query/query-keys"
import { Badge } from "../../shared/ui/Badge"
import { Button } from "../../shared/ui/Button"
import { buttonClassName } from "../../shared/ui/button-styles"
import { EmptyState } from "../../shared/ui/EmptyState"
import ConversationHistoryPanel from "./ConversationHistoryPanel"

type MessageStatus = "complete" | "streaming" | "cancelled" | "error"
type ContextOrigin = "none" | "handoff" | "stored" | "draft"

interface WorkspaceMessage extends CompanionChatMessage {
  id: string
  status: MessageStatus
  provider?: string
  model?: string
  serverMessageId?: string
  errorCode?: string
}

interface StreamEventContext {
  scopeId: string
  requestId: number
  localUserId: string
  localAssistantId: string
}

interface ChatContextSnapshot {
  source_text: string
  translated_text: string
  source_language: string
  target_language: string
  resource_url: string
  resource_title: string
  section_heading: string
  context_before: string
  context_after: string
  source_kind: string
  ai_content?: string
  ai_action?: string
}

const EMPTY_CONTEXT: ChatContextSnapshot = {
  source_text: "",
  translated_text: "",
  source_language: "auto",
  target_language: "zh-CN",
  resource_url: "",
  resource_title: "",
  section_heading: "",
  context_before: "",
  context_after: "",
  source_kind: "",
}

function snapshotFromContext(context: CompanionHandoff | ConversationDetail): ChatContextSnapshot {
  return {
    source_text: context.source_text,
    translated_text: context.translated_text,
    source_language: context.source_language,
    target_language: context.target_language,
    resource_url: context.resource_url,
    resource_title: context.resource_title,
    section_heading: context.section_heading,
    context_before: context.context_before,
    context_after: context.context_after,
    source_kind: context.source_kind,
    ...("ai_content" in context ? { ai_content: context.ai_content, ai_action: context.ai_action } : {}),
  }
}

function historyFrom(messages: WorkspaceMessage[]): CompanionChatMessage[] {
  return messages
    .filter((message) => message.status === "complete" && message.content.trim())
    .slice(-16)
    .map(({ role, content }) => ({ role, content }))
}

function restoredMessages(messages: ConversationMessage[]): WorkspaceMessage[] {
  return messages.map((message) => ({
    id: message.message_id,
    role: message.role,
    content: message.content,
    status: message.status,
    provider: message.provider,
    model: message.model,
    serverMessageId: message.message_id,
    errorCode: message.error_code,
  }))
}

function previousUserMessage(messages: WorkspaceMessage[], assistantIndex: number): WorkspaceMessage | null {
  for (let index = assistantIndex - 1; index >= 0; index -= 1) {
    if (messages[index]?.role === "user") return messages[index]
  }
  return null
}

function uniqueScope(prefix: string): string {
  return `${prefix}:${Date.now()}:${Math.random().toString(36).slice(2, 10)}`
}

export default function CompanionWorkspace() {
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [messages, setMessages] = useState<WorkspaceMessage[]>([])
  const [draft, setDraft] = useState("")
  const [errorMessage, setErrorMessage] = useState("")
  const [activeRequestId, setActiveRequestId] = useState<number | null>(null)
  const [activeConversationId, setActiveConversationId] = useState("")
  const [restoredConversation, setRestoredConversation] = useState<ConversationDetail | null>(null)
  const [draftContext, setDraftContext] = useState<ChatContextSnapshot | null>(null)
  const [chatContextMode, setChatContextMode] = useState<ChatContextMode>("general")
  const [openingConversation, setOpeningConversation] = useState(false)
  const [branchingMessageId, setBranchingMessageId] = useState("")
  const [contextUpdating, setContextUpdating] = useState(false)
  const [editingMessageId, setEditingMessageId] = useState("")
  const [editingText, setEditingText] = useState("")
  const handoffIdRef = useRef("")
  const contextOriginRef = useRef<ContextOrigin>("none")
  const contextModeRef = useRef<ChatContextMode>("general")
  const scopeRef = useRef("")
  const sessionIdRef = useRef("")
  const requestCounterRef = useRef(0)
  const activeRequestRef = useRef<number | null>(null)
  const conversationIdRef = useRef("")
  const openingConversationRef = useRef(false)
  const streamHandleRef = useRef<CompanionChatStreamHandle | null>(null)

  const handoffQuery = useQuery({
    queryKey: queryKeys.companion.handoff,
    queryFn: getCompanionHandoff,
    refetchInterval: queryPolling.companionHandoff,
    staleTime: 0,
  })

  const chatStatusQuery = useQuery({
    queryKey: queryKeys.companion.chatStatus,
    queryFn: getCompanionChatStatus,
    refetchInterval: queryPolling.companionChatStatus,
    retry: 0,
  })

  const handoff = handoffQuery.data?.handoff ?? null
  const chatAvailable = chatStatusQuery.data?.available ?? false
  const restoredSnapshot = restoredConversation ? snapshotFromContext(restoredConversation) : null
  const handoffSnapshot = handoff ? snapshotFromContext(handoff) : null
  const activeContext = draftContext ?? restoredSnapshot ?? handoffSnapshot
  const routedConversationId = searchParams.get("conversation") ?? ""

  const setConversationRoute = useCallback((conversationId: string) => {
    const next = new URLSearchParams(searchParams)
    if (conversationId) next.set("conversation", conversationId)
    else next.delete("conversation")
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])

  const applyConversationId = useCallback((conversationId: string) => {
    conversationIdRef.current = conversationId
    setActiveConversationId(conversationId)
  }, [])

  const applyContextMode = useCallback((mode: ChatContextMode) => {
    contextModeRef.current = mode
    setChatContextMode(mode)
  }, [])

  const closeActiveStream = useCallback(() => {
    streamHandleRef.current?.cancel()
    streamHandleRef.current?.close()
    streamHandleRef.current = null
    activeRequestRef.current = null
    setActiveRequestId(null)
  }, [])

  const resetToHandoff = useCallback((nextHandoff: CompanionHandoff) => {
    closeActiveStream()
    contextOriginRef.current = "handoff"
    scopeRef.current = `handoff:${nextHandoff.handoff_id}`
    sessionIdRef.current = `companion-${nextHandoff.handoff_id}`
    setDraftContext(snapshotFromContext(nextHandoff))
    setRestoredConversation(null)
    applyContextMode("reading")
    applyConversationId("")
    setMessages([])
    setDraft(nextHandoff.suggested_prompt ?? "")
    setErrorMessage("")
    setEditingMessageId("")
    setEditingText("")
    setConversationRoute("")
  }, [applyContextMode, applyConversationId, closeActiveStream, setConversationRoute])

  const openConversation = useCallback(async (conversationId: string, updateRoute = true) => {
    if (!conversationId || openingConversationRef.current) return
    if (conversationIdRef.current === conversationId && messages.length > 0) {
      if (updateRoute) setConversationRoute(conversationId)
      return
    }

    closeActiveStream()
    openingConversationRef.current = true
    setOpeningConversation(true)
    setErrorMessage("")
    try {
      const conversation = await queryClient.fetchQuery({
        queryKey: queryKeys.conversations.detail(conversationId),
        queryFn: () => getConversation(conversationId),
        staleTime: 0,
      })
      contextOriginRef.current = "stored"
      scopeRef.current = `stored:${conversation.conversation_id}`
      sessionIdRef.current = conversation.session_id
      setDraftContext(null)
      setRestoredConversation(conversation)
      applyContextMode(conversation.context_mode)
      applyConversationId(conversation.conversation_id)
      setMessages(restoredMessages(conversation.messages))
      setDraft("")
      setEditingMessageId("")
      setEditingText("")
      if (updateRoute) setConversationRoute(conversation.conversation_id)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Unable to open conversation.")
    } finally {
      openingConversationRef.current = false
      setOpeningConversation(false)
    }
  }, [applyContextMode, applyConversationId, closeActiveStream, messages.length, queryClient, setConversationRoute])

  useEffect(() => {
    const nextId = handoff?.handoff_id ?? ""
    if (!nextId) {
      if (contextOriginRef.current === "handoff") {
        queueMicrotask(() => {
          contextOriginRef.current = "none"
          scopeRef.current = ""
          sessionIdRef.current = ""
          setDraftContext(null)
          setRestoredConversation(null)
          applyContextMode("general")
          applyConversationId("")
          setMessages([])
          setDraft("")
          setErrorMessage("")
        })
      }
      handoffIdRef.current = ""
      return
    }

    if (routedConversationId) {
      handoffIdRef.current = nextId
      return
    }

    const shouldConsume = nextId !== handoffIdRef.current || contextOriginRef.current === "stored"
    if (!shouldConsume || !handoff) return
    handoffIdRef.current = nextId
    queueMicrotask(() => resetToHandoff(handoff))
  }, [applyContextMode, applyConversationId, handoff, resetToHandoff, routedConversationId])

  useEffect(() => {
    if (!routedConversationId) return
    if (conversationIdRef.current === routedConversationId) return
    queueMicrotask(() => void openConversation(routedConversationId, false))
  }, [openConversation, routedConversationId])

  useEffect(
    () => () => {
      streamHandleRef.current?.close()
    },
    [],
  )

  const dismissMutation = useMutation({
    mutationFn: (handoffId: string) => dismissCompanionHandoff(handoffId),
    onMutate: closeActiveStream,
    onSuccess: () => {
      contextOriginRef.current = "none"
      scopeRef.current = ""
      sessionIdRef.current = ""
      setDraftContext(EMPTY_CONTEXT)
      setRestoredConversation(null)
      applyContextMode("general")
      applyConversationId("")
      setMessages([])
      setDraft("")
      setErrorMessage("")
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

  const recoverConversation = useCallback(async (conversationId: string, expectedScope: string) => {
    if (!conversationId || scopeRef.current !== expectedScope) return
    try {
      const conversation = await getConversation(conversationId)
      if (scopeRef.current !== expectedScope) return
      setMessages(restoredMessages(conversation.messages))
      setRestoredConversation(conversation)
      setDraftContext(null)
      applyContextMode(conversation.context_mode)
      queryClient.setQueryData(queryKeys.conversations.detail(conversationId), conversation)
      void queryClient.invalidateQueries({ queryKey: ["conversations"] })
    } catch {
      // Keep the transport error already shown to the user.
    }
  }, [applyContextMode, queryClient])

  function useCurrentReading() {
    if (!handoff) return
    resetToHandoff(handoff)
  }

  function startNewGeneralConversation() {
    closeActiveStream()
    contextOriginRef.current = "draft"
    scopeRef.current = uniqueScope("draft-general")
    sessionIdRef.current = uniqueScope("session")
    setDraftContext(activeContext ?? EMPTY_CONTEXT)
    setRestoredConversation(null)
    applyContextMode("general")
    applyConversationId("")
    setMessages([])
    setDraft("")
    setErrorMessage("")
    setEditingMessageId("")
    setEditingText("")
    setConversationRoute("")
  }

  function handleDeletedActive() {
    if (handoff) {
      resetToHandoff(handoff)
      return
    }
    contextOriginRef.current = "draft"
    scopeRef.current = uniqueScope("draft-general")
    sessionIdRef.current = uniqueScope("session")
    setDraftContext(EMPTY_CONTEXT)
    setRestoredConversation(null)
    applyContextMode("general")
    applyConversationId("")
    setMessages([])
    setDraft("")
    setErrorMessage("")
    setConversationRoute("")
  }

  async function persistContextUpdate(payload: ConversationContextUpdate) {
    const conversationId = conversationIdRef.current
    if (!conversationId) return null
    const updated = await updateConversationContext(conversationId, payload)
    setRestoredConversation(updated)
    setDraftContext(null)
    contextOriginRef.current = "stored"
    scopeRef.current = `stored:${updated.conversation_id}`
    sessionIdRef.current = updated.session_id
    applyContextMode(updated.context_mode)
    queryClient.setQueryData(queryKeys.conversations.detail(conversationId), updated)
    void queryClient.invalidateQueries({ queryKey: ["conversations"] })
    return updated
  }

  async function detachContext() {
    if (activeRequestRef.current !== null || contextUpdating) return
    setContextUpdating(true)
    setErrorMessage("")
    try {
      if (conversationIdRef.current) {
        await persistContextUpdate({ context_mode: "general" })
      } else {
        applyContextMode("general")
        if (!draftContext) setDraftContext(activeContext ?? EMPTY_CONTEXT)
        if (contextOriginRef.current === "handoff") contextOriginRef.current = "draft"
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Unable to detach reading context.")
    } finally {
      setContextUpdating(false)
    }
  }

  async function attachSavedContext() {
    if (!activeContext?.source_text || activeRequestRef.current !== null || contextUpdating) return
    setContextUpdating(true)
    setErrorMessage("")
    try {
      if (conversationIdRef.current) {
        await persistContextUpdate({ context_mode: "reading" })
      } else {
        applyContextMode("reading")
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Unable to attach saved reading context.")
    } finally {
      setContextUpdating(false)
    }
  }

  async function attachCurrentReading() {
    if (!handoff || activeRequestRef.current !== null || contextUpdating) return
    const current = snapshotFromContext(handoff)
    setContextUpdating(true)
    setErrorMessage("")
    try {
      if (conversationIdRef.current) {
        await persistContextUpdate({
          context_mode: "reading",
          source_text: current.source_text,
          translated_text: current.translated_text,
          source_language: current.source_language,
          target_language: current.target_language,
          resource_url: current.resource_url,
          resource_title: current.resource_title,
          section_heading: current.section_heading,
          context_before: current.context_before,
          context_after: current.context_after,
          source_kind: current.source_kind,
        })
      } else {
        setDraftContext(current)
        applyContextMode("reading")
        if (contextOriginRef.current === "none") contextOriginRef.current = "draft"
      }
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Unable to attach current reading context.")
    } finally {
      setContextUpdating(false)
    }
  }

  function finishRequest(requestId: number) {
    if (activeRequestRef.current !== requestId) return
    activeRequestRef.current = null
    streamHandleRef.current = null
    setActiveRequestId(null)
    void queryClient.invalidateQueries({ queryKey: ["conversations"] })
  }

  function handleStreamEvent(event: CompanionChatStreamEvent, context: StreamEventContext) {
    const { scopeId, requestId, localUserId, localAssistantId } = context
    if (scopeRef.current !== scopeId) return
    if (activeRequestRef.current !== requestId || event.request_id !== requestId) return

    if (event.type === "accepted") {
      applyConversationId(event.conversation_id)
      setConversationRoute(event.conversation_id)
      setMessages((current) =>
        current.map((message) => {
          if (message.id === localUserId && event.user_message_id) {
            return { ...message, serverMessageId: event.user_message_id }
          }
          if (message.id === localAssistantId) {
            return { ...message, serverMessageId: event.message_id }
          }
          return message
        }),
      )
      void queryClient.invalidateQueries({ queryKey: ["conversations"] })
      return
    }

    if (event.type === "delta") {
      setMessages((current) =>
        current.map((message) =>
          message.id === localAssistantId
            ? { ...message, content: event.accumulated_text, serverMessageId: event.message_id, status: "streaming" }
            : message,
        ),
      )
      return
    }

    if (event.type === "done") {
      setMessages((current) =>
        current.map((message) =>
          message.id === localAssistantId
            ? {
                ...message,
                content: event.output_text,
                serverMessageId: event.message_id,
                provider: event.provider,
                model: event.model,
                status: "complete",
              }
            : message,
        ),
      )
      finishRequest(requestId)
      return
    }

    if (event.type === "cancelled") {
      setMessages((current) =>
        current.map((message) =>
          message.id === localAssistantId
            ? { ...message, serverMessageId: event.message_id, status: "cancelled", errorCode: "user_cancelled" }
            : message,
        ),
      )
      finishRequest(requestId)
      return
    }

    setMessages((current) =>
      current.map((message) =>
        message.id === localAssistantId
          ? { ...message, serverMessageId: event.message_id, status: "error", errorCode: event.code }
          : message,
      ),
    )
    setErrorMessage(event.message || "AI Chat streaming failed.")
    finishRequest(requestId)
  }

  function startExchange(userMessage: string, baseMessages: WorkspaceMessage[] = messages) {
    const context = activeContext ?? EMPTY_CONTEXT
    if (activeRequestRef.current !== null) return
    if (contextModeRef.current === "reading" && !context.source_text.trim()) {
      setErrorMessage("Reading-grounded Chat requires an attached selection.")
      return
    }
    const normalized = userMessage.trim()
    if (!normalized) return

    const requestId = requestCounterRef.current + 1
    requestCounterRef.current = requestId
    activeRequestRef.current = requestId
    setActiveRequestId(requestId)
    setErrorMessage("")
    setDraft("")

    const localUserId = `user-local-${requestId}`
    const localAssistantId = `assistant-local-${requestId}`
    const history = historyFrom(baseMessages)
    setMessages([
      ...baseMessages,
      { id: localUserId, role: "user", content: normalized, status: "complete" },
      { id: localAssistantId, role: "assistant", content: "", status: "streaming" },
    ])

    const payload: CompanionChatRequest = {
      conversation_id: conversationIdRef.current,
      session_id: sessionIdRef.current || uniqueScope("session"),
      user_message: normalized,
      context_mode: contextModeRef.current,
      source_text: context.source_text,
      translated_text: context.translated_text,
      source_language: context.source_language,
      target_language: context.target_language,
      resource_url: context.resource_url,
      resource_title: context.resource_title,
      section_heading: context.section_heading,
      context_before: context.context_before,
      context_after: context.context_after,
      source_kind: context.source_kind,
      history,
      request_id: requestId,
      knowledge_enabled: false,
      knowledge_document_ids: [],
    }

    const scopeId = scopeRef.current || uniqueScope("draft-general")
    if (!scopeRef.current) scopeRef.current = scopeId
    streamHandleRef.current = streamCompanionChat(payload, {
      onEvent: (streamEvent) =>
        handleStreamEvent(streamEvent, { scopeId, requestId, localUserId, localAssistantId }),
      onTransportError: (error) => {
        if (scopeRef.current !== scopeId || activeRequestRef.current !== requestId) return
        setMessages((current) =>
          current.map((message) =>
            message.id === localAssistantId
              ? { ...message, status: "error", errorCode: "transport" }
              : message,
          ),
        )
        setErrorMessage(`${error.message} Recovering persisted stream state…`)
        const conversationId = conversationIdRef.current
        finishRequest(requestId)
        if (conversationId) {
          window.setTimeout(() => void recoverConversation(conversationId, scopeId), 250)
        }
      },
    })
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    startExchange(draft)
  }

  function cancelStream() {
    streamHandleRef.current?.cancel()
  }

  async function rewriteFromUser(userMessage: WorkspaceMessage, replacementText: string) {
    const conversationId = conversationIdRef.current
    const userMessageId = userMessage.serverMessageId || userMessage.id
    if (!conversationId || !userMessageId || userMessageId.startsWith("user-local-")) return
    if (activeRequestRef.current !== null) return

    closeActiveStream()
    setBranchingMessageId(userMessageId)
    setErrorMessage("")
    try {
      const rewound = await rewindConversation(conversationId, userMessageId)
      const baseMessages = restoredMessages(rewound.messages)
      setRestoredConversation(rewound)
      setDraftContext(null)
      setMessages(baseMessages)
      queryClient.setQueryData(queryKeys.conversations.detail(conversationId), rewound)
      void queryClient.invalidateQueries({ queryKey: ["conversations"] })
      setEditingMessageId("")
      setEditingText("")
      startExchange(replacementText, baseMessages)
    } catch (error) {
      setErrorMessage(error instanceof Error ? error.message : "Unable to rewrite conversation branch.")
    } finally {
      setBranchingMessageId("")
    }
  }

  function beginEditMessage(message: WorkspaceMessage) {
    setEditingMessageId(message.id)
    setEditingText(message.content)
  }

  function cancelEditMessage() {
    setEditingMessageId("")
    setEditingText("")
  }

  function commitEditMessage(message: WorkspaceMessage) {
    const edited = editingText.trim()
    if (!edited || edited === message.content) {
      cancelEditMessage()
      return
    }
    void rewriteFromUser(message, edited)
  }

  function saveLinkedNote() {
    const conversationId = conversationIdRef.current
    if (!activeContext || !conversationId || chatContextMode !== "reading" || !activeContext.source_text) return
    const lastAssistant = [...messages]
      .reverse()
      .find((message) => message.role === "assistant" && message.status === "complete")
    saveNoteMutation.mutate({
      source_text: activeContext.source_text,
      translated_text: activeContext.translated_text,
      source_language: activeContext.source_language,
      target_language: activeContext.target_language,
      resource_url: activeContext.resource_url,
      resource_title: activeContext.resource_title,
      section_heading: activeContext.section_heading,
      context_before: activeContext.context_before,
      context_after: activeContext.context_after,
      source_kind: activeContext.source_kind,
      ai_content: lastAssistant?.content || activeContext.ai_content || "",
      ai_action: lastAssistant ? "conversation_answer" : activeContext.ai_action || "",
      conversation_id: conversationId,
    })
  }

  const contextTitle = chatContextMode === "general"
    ? "General Chat"
    : activeContext?.resource_title || activeContext?.section_heading || "Reading context"
  const canAttachSaved = Boolean(activeContext?.source_text)
  const branchBusy = Boolean(branchingMessageId) || activeRequestId !== null
  const showingHandoff = Boolean(
    handoff &&
      !activeConversationId &&
      chatContextMode === "reading" &&
      draftContext?.source_text === handoff.source_text,
  )

  return (
    <section className="ait-chat-shell ait-surface grid min-h-[680px] overflow-hidden xl:grid-cols-[270px_340px_minmax(0,1fr)]">
      <ConversationHistoryPanel
        activeConversationId={activeConversationId}
        hasCurrentReading={Boolean(handoff)}
        onOpen={(conversationId) => void openConversation(conversationId)}
        onUseCurrentReading={useCurrentReading}
        onNewGeneralConversation={startNewGeneralConversation}
        onDeletedActive={handleDeletedActive}
      />

      <aside className="border-b border-slate-200/70 bg-slate-50/60 p-5 xl:border-b-0 xl:border-r">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">Chat context</p>
            <h2 className="mt-2 truncate text-sm font-semibold text-slate-900">{contextTitle}</h2>
          </div>
          <Badge tone={chatContextMode === "reading" ? "info" : "neutral"}>
            {chatContextMode === "reading" ? "Reading-grounded" : "General"}
          </Badge>
        </div>

        <div className="relative mt-4 grid grid-cols-2 overflow-hidden rounded-[14px] bg-slate-200/70 p-1">
          <span
            aria-hidden="true"
            className={`ait-segment-indicator absolute inset-y-1 left-1 w-[calc(50%-4px)] rounded-[11px] bg-white shadow-sm ${
              chatContextMode === "reading" ? "translate-x-full" : "translate-x-0"
            }`}
          />
          <button
            type="button"
            disabled={contextUpdating || activeRequestId !== null}
            className={`relative z-10 rounded-[11px] px-2 py-2 text-xs font-medium transition-colors ${
              chatContextMode === "general" ? "text-slate-900" : "text-slate-500"
            }`}
            onClick={() => void detachContext()}
          >
            General
          </button>
          <button
            type="button"
            disabled={contextUpdating || activeRequestId !== null || (!canAttachSaved && !handoff)}
            className={`relative z-10 rounded-[11px] px-2 py-2 text-xs font-medium transition-colors disabled:opacity-40 ${
              chatContextMode === "reading" ? "text-slate-900" : "text-slate-500"
            }`}
            onClick={() => void (canAttachSaved ? attachSavedContext() : attachCurrentReading())}
          >
            Reading
          </button>
        </div>

        <div key={chatContextMode} className="ait-context-panel-enter">
          {chatContextMode === "general" ? (
            <div className="mt-4 rounded-[16px] border border-slate-200/70 bg-white/85 p-3.5">
              <p className="text-xs font-medium text-slate-700">No reading context attached.</p>
              <p className="mt-1 text-xs leading-5 text-slate-500">
                The assistant receives conversation history and your new message. Reading evidence can be attached again at any time.
              </p>
              {handoff && (
                <Button className="mt-3" size="xs" onClick={() => void attachCurrentReading()} disabled={contextUpdating}>
                  Attach current reading
                </Button>
              )}
            </div>
          ) : activeContext ? (
            <>
              <ContextPreview context={activeContext} />
              {handoff && (
                <Button className="mt-3" size="xs" onClick={() => void attachCurrentReading()} disabled={contextUpdating}>
                  Replace with current reading
                </Button>
              )}
              {activeContext.ai_content && (
                <div className="mt-3 rounded-[16px] border border-cyan-100 bg-cyan-50/70 p-3.5">
                  <div className="flex items-center gap-2">
                    <Badge tone="info">Quick Action</Badge>
                    {activeContext.ai_action && <span className="text-[10px] text-cyan-700/70">{activeContext.ai_action}</span>}
                  </div>
                  <p className="mt-2 line-clamp-8 whitespace-pre-wrap text-xs leading-5 text-slate-700">{activeContext.ai_content}</p>
                </div>
              )}
              {activeContext.resource_url && (
                <p className="mt-4 break-all font-mono text-[10px] leading-4 text-slate-400">{activeContext.resource_url}</p>
              )}
              {activeConversationId && (
                <div className="mt-4">
                  <Button size="xs" disabled={saveNoteMutation.isPending} onClick={saveLinkedNote}>
                    {saveNoteMutation.isPending ? "Saving…" : "Save linked note"}
                  </Button>
                  {saveNoteMutation.isSuccess && <p className="mt-2 text-[10px] text-emerald-600">Research Note linked to this conversation.</p>}
                </div>
              )}
            </>
          ) : (
            <p className="mt-4 text-xs leading-5 text-slate-500">Attach the current reading selection to use grounded chat.</p>
          )}

          {showingHandoff && handoff && (
            <Button className="mt-4" size="xs" disabled={dismissMutation.isPending} onClick={() => dismissMutation.mutate(handoff.handoff_id)}>
              Clear handoff
            </Button>
          )}
        </div>
      </aside>

      <div className="flex min-h-0 flex-col bg-white/95">
        <div className="min-h-0 flex-1 overflow-y-auto p-5 lg:p-6">
          {messages.length === 0 && (
            <EmptyState
              title={chatContextMode === "general" ? "Start a General Chat" : "Ask about this reading context"}
              description={chatContextMode === "general"
                ? "This conversation has no reading context attached. You can attach reading evidence at any time."
                : "The selected passage and bounded nearby context will be supplied as reference evidence."}
              actions={!activeContext && chatContextMode === "reading" ? (
                <>
                  <Link to="/reading" className={buttonClassName()}>Reading Context</Link>
                  <Link to="/research" className={buttonClassName({ variant: "primary" })}>Research Notes</Link>
                </>
              ) : undefined}
            />
          )}

          <div className="mt-4 space-y-3">
            {messages.map((message, index) => {
              const userBefore = message.role === "assistant" ? previousUserMessage(messages, index) : null
              const userServerId = message.role === "user" ? message.serverMessageId || message.id : ""
              const editing = message.role === "user" && editingMessageId === message.id
              return (
                <div
                  key={message.id}
                  className={`ait-chat-message-enter ${message.role === "user"
                    ? "ml-auto max-w-[78%] rounded-[20px] bg-slate-950 px-4 py-3 text-sm leading-6 text-white shadow-sm"
                    : "max-w-[88%] rounded-[20px] border border-slate-100 bg-slate-50/85 px-4 py-3 text-sm leading-6 text-slate-700"}`}
                >
                  {message.role === "assistant" ? (
                    <>
                      {message.content ? (
                        <div className="max-w-none"><ReactMarkdown>{message.content}</ReactMarkdown></div>
                      ) : message.status === "streaming" ? (
                        <div className="flex items-center gap-2 text-slate-400">
                          <span className="h-3 w-3 animate-spin rounded-full border border-slate-300 border-t-slate-700" />
                          Waiting for the first token…
                        </div>
                      ) : (
                        <p className="text-slate-400">{message.status === "cancelled" ? "Generation stopped." : "No response content."}</p>
                      )}
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        {message.status === "streaming" && <Badge tone="info">Streaming</Badge>}
                        {message.status === "cancelled" && <Badge tone="warning">Stopped</Badge>}
                        {message.status === "error" && <Badge tone="danger">Failed</Badge>}
                        {message.status === "complete" && message.provider && <Badge tone="success">{message.provider}{message.model ? ` · ${message.model}` : ""}</Badge>}
                        {message.errorCode && message.status !== "complete" && <span className="text-[10px] text-slate-400">{message.errorCode}</span>}
                        {userBefore && (userBefore.serverMessageId || !userBefore.id.startsWith("user-local-")) && message.status !== "streaming" && (
                          <button
                            type="button"
                            disabled={branchBusy}
                            className="text-[10px] font-medium text-slate-400 hover:text-slate-700 disabled:opacity-40"
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
                        <button type="button" className="text-[10px] text-slate-400 hover:text-white" onClick={cancelEditMessage}>Cancel</button>
                        <button type="button" className="rounded bg-white px-2 py-1 text-[10px] font-medium text-slate-900 disabled:opacity-40" disabled={!editingText.trim() || branchBusy} onClick={() => commitEditMessage(message)}>Resend</button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <p className="whitespace-pre-wrap">{message.content}</p>
                      {userServerId && !userServerId.startsWith("user-local-") && (
                        <div className="mt-2 text-right">
                          <button type="button" disabled={branchBusy} className="text-[10px] text-slate-400 hover:text-white disabled:opacity-40" onClick={() => beginEditMessage(message)}>Edit & resend</button>
                        </div>
                      )}
                    </>
                  )}
                </div>
              )
            })}

            {errorMessage && <p className="rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700">{errorMessage}</p>}
          </div>
        </div>

        <form className="border-t border-slate-100/80 bg-white/90 p-4 backdrop-blur-xl" onSubmit={handleSubmit}>
          {!chatAvailable && chatStatusQuery.isSuccess && (
            <p className="mb-2 rounded-lg bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-700">AI Chat 未配置：{chatStatusQuery.data.detail}</p>
          )}
          <div className="flex items-end gap-2">
            <textarea
              className="max-h-36 min-h-12 flex-1 resize-none rounded-[16px] border border-slate-200/80 bg-slate-50/85 px-3.5 py-2.5 text-sm leading-6 outline-none transition focus:border-slate-400 focus:bg-white disabled:cursor-not-allowed disabled:opacity-60"
              placeholder={activeRequestId === null
                ? chatContextMode === "general" ? "Ask anything…" : "继续问这段内容…"
                : "当前回复仍在生成，可先编辑下一条消息…"}
              value={draft}
              disabled={openingConversation}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault()
                  event.currentTarget.form?.requestSubmit()
                }
              }}
            />
            {activeRequestId !== null ? (
              <Button type="button" variant="danger" size="md" onClick={cancelStream}>停止</Button>
            ) : (
              <Button type="submit" variant="primary" size="md" disabled={!chatAvailable || !draft.trim() || openingConversation || Boolean(branchingMessageId)}>
                发送
              </Button>
            )}
          </div>
          <p className="mt-2 text-[10px] text-slate-400">
            Enter 发送 · Shift+Enter 换行 · {chatContextMode === "reading" ? "Reading-grounded" : "General"} · WebSocket Streaming · SQLite branches
          </p>
        </form>
      </div>
    </section>
  )
}

function ContextPreview({ context }: { context: ChatContextSnapshot }) {
  return (
    <div className="mt-4 space-y-3">
      <div className="rounded-[16px] border border-slate-200/70 bg-white/85 p-3.5">
        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">Selection</p>
        <p className="mt-2 line-clamp-8 text-xs leading-5 text-slate-700">{context.source_text}</p>
      </div>
      {context.translated_text && (
        <div className="rounded-[16px] border border-slate-200/70 bg-white/85 p-3.5">
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">Translation</p>
          <p className="mt-2 line-clamp-7 text-xs leading-5 text-slate-600">{context.translated_text}</p>
        </div>
      )}
    </div>
  )
}
