import { useCallback, useEffect, useRef, useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"

import {
  getCompanionChatOwnership,
  getCompanionChatStatus,
  type CompanionClientSurface,
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
import type {
  ChatContextMode,
  CompanionChatStreamEvent,
  ConversationContextUpdate,
  ConversationDetail,
} from "../../api/types"
import { desktop } from "../../desktop"
import type { CompanionConversationChangeSignal } from "../../desktop/adapter"
import { queryKeys, queryPolling } from "../../shared/query/query-keys"
import {
  buildCompanionChatRequest,
  companionContextSnapshot,
  createCompanionScope,
  EMPTY_COMPANION_CONTEXT,
  restoreCompanionMessages,
  type CompanionContextSnapshot,
  type CompanionRuntimeMessage,
} from "./companion-runtime"
import { projectPersistedContext } from "./context-persistence-policy"
import type { CompanionRecoveryState } from "./companion-recovery"
import { companionExternalChangeDecision } from "./companion-sync"

type StreamEventContext = {
  scopeId: string
  requestId: number
  localUserId: string
  localAssistantId: string
}

type ApplyConversationOptions = {
  preserveDraft?: boolean
}

const OWNERSHIP_REJECTION_CODES = new Set([
  "conversation_busy",
  "duplicate_request",
  "duplicate_active_request",
])

export interface CompanionRuntimeResetOptions {
  context?: CompanionContextSnapshot | null
  contextMode?: ChatContextMode
  draft?: string
  sessionId?: string
  scopeId?: string
  knowledgeEnabled?: boolean
  knowledgeDocumentIds?: string[]
}

export interface UseCompanionConversationRuntimeOptions {
  initialContext?: CompanionContextSnapshot | null
  initialContextMode?: ChatContextMode
  initialDraft?: string
  initialSessionId?: string
  initialScopeId?: string
  clientSurface?: CompanionClientSurface
  onConversationAccepted?: (conversationId: string) => void
}

export interface CompanionConversationRuntime {
  messages: CompanionRuntimeMessage[]
  draft: string
  setDraft: (value: string) => void
  errorMessage: string
  clearError: () => void
  activeRequestId: number | null
  conversationId: string
  context: CompanionContextSnapshot
  contextMode: ChatContextMode
  chatAvailable: boolean
  chatStatusDetail: string
  chatStatusLoaded: boolean
  openingConversation: boolean
  contextUpdating: boolean
  knowledgeEnabled: boolean
  setKnowledgeEnabled: (enabled: boolean) => void
  knowledgeDocumentIds: string[]
  setKnowledgeDocumentIds: (documentIds: string[]) => void
  conversationBusyElsewhere: boolean
  ownerSurface: CompanionClientSurface
  recoveryState: CompanionRecoveryState
  recoveryDetail: string
  reset: (options?: CompanionRuntimeResetOptions) => void
  openConversation: (conversationId: string) => Promise<ConversationDetail | null>
  sendMessage: (message?: string, baseMessages?: CompanionRuntimeMessage[]) => boolean
  cancelStream: () => void
  closeActiveStream: () => void
  retryRecovery: () => Promise<boolean>
  attachReadingContext: (context: CompanionContextSnapshot) => Promise<void>
  attachSavedContext: () => Promise<void>
  detachReadingContext: () => Promise<void>
  rewriteFromUser: (
    userMessage: CompanionRuntimeMessage,
    replacementText: string,
  ) => Promise<boolean>
}

function normalizedDocumentIds(values: string[] | undefined): string[] {
  return [...new Set((values ?? []).map((value) => value.trim()).filter(Boolean))].slice(0, 100)
}

export function useCompanionConversationRuntime(
  options: UseCompanionConversationRuntimeOptions = {},
): CompanionConversationRuntime {
  const queryClient = useQueryClient()
  const [messages, setMessages] = useState<CompanionRuntimeMessage[]>([])
  const [draft, setDraft] = useState(options.initialDraft ?? "")
  const [errorMessage, setErrorMessage] = useState("")
  const [activeRequestId, setActiveRequestId] = useState<number | null>(null)
  const [conversationId, setConversationId] = useState("")
  const [context, setContext] = useState<CompanionContextSnapshot>(
    options.initialContext ?? EMPTY_COMPANION_CONTEXT,
  )
  const [contextMode, setContextMode] = useState<ChatContextMode>(
    options.initialContextMode ?? "general",
  )
  const [openingConversation, setOpeningConversation] = useState(false)
  const [contextUpdating, setContextUpdating] = useState(false)
  const [knowledgeEnabled, setKnowledgeEnabled] = useState(false)
  const [knowledgeDocumentIds, setKnowledgeDocumentIds] = useState<string[]>([])
  const [recoveryState, setRecoveryState] = useState<CompanionRecoveryState>("idle")
  const [recoveryDetail, setRecoveryDetail] = useState("")
  const [clientSurface] = useState<CompanionClientSurface>(options.clientSurface ?? "unknown")
  const [clientId] = useState(() => createCompanionScope(`client-${clientSurface}`))

  const contextRef = useRef(context)
  const contextModeRef = useRef(contextMode)
  const conversationIdRef = useRef("")
  const sessionIdRef = useRef(
    options.initialSessionId ?? createCompanionScope("session"),
  )
  const scopeRef = useRef(
    options.initialScopeId ?? createCompanionScope("companion"),
  )
  const requestCounterRef = useRef(0)
  const activeRequestRef = useRef<number | null>(null)
  const streamHandleRef = useRef<CompanionChatStreamHandle | null>(null)
  const openingConversationRef = useRef(false)
  const pendingExternalChangeRef = useRef<CompanionConversationChangeSignal | null>(null)
  const lastRecoveryConversationRef = useRef("")
  const lastFailedDraftRef = useRef("")
  const onConversationAcceptedRef = useRef(options.onConversationAccepted)

  useEffect(() => {
    onConversationAcceptedRef.current = options.onConversationAccepted
  }, [options.onConversationAccepted])

  const chatStatusQuery = useQuery({
    queryKey: queryKeys.companion.chatStatus,
    queryFn: getCompanionChatStatus,
    refetchInterval: queryPolling.companionChatStatus,
    retry: 0,
  })

  const ownershipQuery = useQuery({
    queryKey: queryKeys.companion.ownership(conversationId),
    queryFn: () => getCompanionChatOwnership(conversationId),
    enabled: Boolean(conversationId),
    refetchInterval: queryPolling.companionOwnership,
    retry: 0,
  })
  const ownerSurface = ownershipQuery.data?.owner_surface ?? "unknown"
  const conversationBusyElsewhere = Boolean(
    conversationId &&
      ownershipQuery.data?.busy &&
      ownershipQuery.data.owner_id !== clientId,
  )

  const clearRecovery = useCallback(() => {
    setRecoveryState("idle")
    setRecoveryDetail("")
  }, [])

  const applyConversationId = useCallback((next: string) => {
    conversationIdRef.current = next
    if (next) lastRecoveryConversationRef.current = next
    setConversationId(next)
  }, [])

  const applyContext = useCallback((next: CompanionContextSnapshot) => {
    contextRef.current = next
    setContext(next)
  }, [])

  const applyContextMode = useCallback((next: ChatContextMode) => {
    contextModeRef.current = next
    setContextMode(next)
  }, [])

  const closeActiveStream = useCallback(() => {
    streamHandleRef.current?.cancel()
    streamHandleRef.current?.close()
    streamHandleRef.current = null
    activeRequestRef.current = null
    setActiveRequestId(null)
  }, [])

  useEffect(
    () => () => {
      streamHandleRef.current?.close()
    },
    [],
  )

  const reset = useCallback((next: CompanionRuntimeResetOptions = {}) => {
    closeActiveStream()
    pendingExternalChangeRef.current = null
    lastRecoveryConversationRef.current = ""
    lastFailedDraftRef.current = ""
    clearRecovery()
    applyConversationId("")
    applyContext(next.context ?? EMPTY_COMPANION_CONTEXT)
    applyContextMode(next.contextMode ?? "general")
    sessionIdRef.current = next.sessionId ?? createCompanionScope("session")
    scopeRef.current = next.scopeId ?? createCompanionScope("companion")
    setMessages([])
    setDraft(next.draft ?? "")
    setErrorMessage("")
    const nextKnowledgeDocumentIds = normalizedDocumentIds(next.knowledgeDocumentIds)
    setKnowledgeDocumentIds(nextKnowledgeDocumentIds)
    setKnowledgeEnabled(Boolean(next.knowledgeEnabled && nextKnowledgeDocumentIds.length > 0))
  }, [
    applyContext,
    applyContextMode,
    applyConversationId,
    clearRecovery,
    closeActiveStream,
  ])

  const applyConversation = useCallback((
    conversation: ConversationDetail,
    options: ApplyConversationOptions = {},
  ) => {
    applyConversationId(conversation.conversation_id)
    applyContext(companionContextSnapshot(conversation))
    applyContextMode(conversation.context_mode)
    sessionIdRef.current = conversation.session_id
    scopeRef.current = `stored:${conversation.conversation_id}`
    setMessages(restoreCompanionMessages(conversation.messages))
    if (!options.preserveDraft) setDraft("")
    lastFailedDraftRef.current = ""
    clearRecovery()
    queryClient.setQueryData(
      queryKeys.conversations.detail(conversation.conversation_id),
      conversation,
    )
  }, [applyContext, applyContextMode, applyConversationId, clearRecovery, queryClient])

  const refreshConversationFromExternalChange = useCallback(async (
    nextConversationId: string,
  ) => {
    const normalized = nextConversationId.trim()
    if (
      !normalized ||
      conversationIdRef.current !== normalized ||
      activeRequestRef.current !== null ||
      openingConversationRef.current
    ) {
      return
    }

    try {
      const conversation = await getConversation(normalized)
      if (
        conversationIdRef.current !== normalized ||
        activeRequestRef.current !== null ||
        openingConversationRef.current
      ) {
        return
      }
      applyConversation(conversation, { preserveDraft: true })
      void queryClient.invalidateQueries({ queryKey: ["conversations"] })
    } catch {
      // Explicit recovery paths surface failures. Background peer sync remains best-effort.
    }
  }, [applyConversation, queryClient])

  const applyExternalConversationDeletion = useCallback((nextConversationId: string) => {
    const normalized = nextConversationId.trim()
    if (!normalized || conversationIdRef.current !== normalized) return

    pendingExternalChangeRef.current = null
    closeActiveStream()
    applyConversationId("")
    setMessages([])
    setDraft("")
    setRecoveryState("offline")
    setRecoveryDetail("The conversation was deleted in another window.")
    setErrorMessage("This conversation was deleted in another window.")
    void queryClient.invalidateQueries({ queryKey: ["conversations"] })
  }, [applyConversationId, closeActiveStream, queryClient])

  useEffect(() => {
    let disposed = false
    let unlisten: () => void = () => undefined

    void desktop.overlay.onCompanionConversationChanged((signal) => {
      if (disposed) return
      const decision = companionExternalChangeDecision(
        signal,
        conversationIdRef.current,
        activeRequestRef.current !== null || openingConversationRef.current,
      )

      if (decision === "ignore") return
      if (decision === "delete") {
        applyExternalConversationDeletion(signal.conversationId)
        return
      }
      if (decision === "queue") {
        pendingExternalChangeRef.current = signal
        return
      }

      void refreshConversationFromExternalChange(signal.conversationId)
    }).then((stopListening) => {
      if (disposed) {
        stopListening()
        return
      }
      unlisten = stopListening
    })

    return () => {
      disposed = true
      unlisten()
    }
  }, [applyExternalConversationDeletion, refreshConversationFromExternalChange])

  useEffect(() => {
    if (activeRequestId !== null || openingConversation || !conversationId) return
    const pending = pendingExternalChangeRef.current
    if (!pending) return

    const decision = companionExternalChangeDecision(pending, conversationId, false)
    pendingExternalChangeRef.current = null
    if (decision === "delete") {
      applyExternalConversationDeletion(pending.conversationId)
    } else if (decision === "refresh") {
      void refreshConversationFromExternalChange(pending.conversationId)
    }
  }, [
    activeRequestId,
    applyExternalConversationDeletion,
    conversationId,
    openingConversation,
    refreshConversationFromExternalChange,
  ])

  const notifyConversationUpdated = useCallback((nextConversationId: string) => {
    const normalized = nextConversationId.trim()
    if (!normalized) return
    void desktop.overlay.notifyCompanionConversationChanged({
      conversationId: normalized,
      kind: "updated",
    }).catch(() => {
      // Persisted storage remains the source of truth when the peer window is unavailable.
    })
  }, [])

  const openConversation = useCallback(async (nextConversationId: string) => {
    if (!nextConversationId || openingConversationRef.current) return null
    if (conversationIdRef.current === nextConversationId && messages.length > 0) {
      return queryClient.getQueryData<ConversationDetail>(
        queryKeys.conversations.detail(nextConversationId),
      ) ?? null
    }

    closeActiveStream()
    openingConversationRef.current = true
    setOpeningConversation(true)
    setRecoveryState("recovering")
    setRecoveryDetail("Restoring persisted conversation…")
    setErrorMessage("")
    try {
      const conversation = await queryClient.fetchQuery({
        queryKey: queryKeys.conversations.detail(nextConversationId),
        queryFn: () => getConversation(nextConversationId),
        staleTime: 0,
      })
      applyConversation(conversation)
      return conversation
    } catch (error) {
      const detail = error instanceof Error ? error.message : "Unable to open conversation."
      setRecoveryState("offline")
      setRecoveryDetail(detail)
      setErrorMessage(detail)
      return null
    } finally {
      openingConversationRef.current = false
      setOpeningConversation(false)
    }
  }, [applyConversation, closeActiveStream, messages.length, queryClient])

  const recoverConversation = useCallback(async (
    nextConversationId: string,
    expectedScope: string,
  ): Promise<boolean> => {
    if (!nextConversationId || scopeRef.current !== expectedScope) return false
    lastRecoveryConversationRef.current = nextConversationId
    setRecoveryState("recovering")
    setRecoveryDetail("Recovering persisted conversation…")
    try {
      const recovered = await getConversation(nextConversationId)
      if (scopeRef.current !== expectedScope) return false
      applyConversation(recovered)
      void queryClient.invalidateQueries({ queryKey: ["conversations"] })
      return true
    } catch (error) {
      if (scopeRef.current !== expectedScope) return false
      const detail = error instanceof Error ? error.message : "Unable to recover conversation."
      setRecoveryState("offline")
      setRecoveryDetail(detail)
      setErrorMessage(detail)
      return false
    }
  }, [applyConversation, queryClient])

  const retryRecovery = useCallback(async (): Promise<boolean> => {
    const persistedConversationId = conversationIdRef.current || lastRecoveryConversationRef.current
    if (persistedConversationId) {
      return recoverConversation(persistedConversationId, scopeRef.current)
    }

    setRecoveryState("recovering")
    setRecoveryDetail("Reconnecting to AI Chat…")
    const result = await chatStatusQuery.refetch()
    if (result.data?.available) {
      clearRecovery()
      setErrorMessage("")
      return true
    }
    setRecoveryState("offline")
    setRecoveryDetail(result.data?.detail || "AI Chat backend is unavailable.")
    return false
  }, [chatStatusQuery, clearRecovery, recoverConversation])

  const finishRequest = useCallback((requestId: number, nextConversationId = "") => {
    if (activeRequestRef.current !== requestId) return
    activeRequestRef.current = null
    streamHandleRef.current = null
    setActiveRequestId(null)
    void queryClient.invalidateQueries({ queryKey: ["conversations"] })
    const ownershipConversationId = nextConversationId || conversationIdRef.current
    if (ownershipConversationId) {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.companion.ownership(ownershipConversationId),
      })
    }
  }, [queryClient])

  const handleStreamEvent = useCallback((
    event: CompanionChatStreamEvent,
    streamContext: StreamEventContext,
  ) => {
    const { scopeId, requestId, localUserId, localAssistantId } = streamContext
    if (scopeRef.current !== scopeId) return
    if (activeRequestRef.current !== requestId || event.request_id !== requestId) return

    if (event.type === "accepted") {
      const isNewConversation = conversationIdRef.current !== event.conversation_id
      applyConversationId(event.conversation_id)
      clearRecovery()
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
      if (isNewConversation) {
        onConversationAcceptedRef.current?.(event.conversation_id)
      }
      void queryClient.invalidateQueries({ queryKey: ["conversations"] })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.companion.ownership(event.conversation_id),
      })
      return
    }

    if (event.type === "delta") {
      setMessages((current) =>
        current.map((message) =>
          message.id === localAssistantId
            ? {
                ...message,
                content: event.accumulated_text,
                serverMessageId: event.message_id,
                status: "streaming",
              }
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
                knowledgeEnabled: event.knowledge_enabled,
                knowledgeFallbackReason: event.knowledge_fallback_reason,
                evidence: event.evidence,
                citations: event.citations,
                status: "complete",
              }
            : message,
        ),
      )
      lastFailedDraftRef.current = ""
      clearRecovery()
      finishRequest(requestId, event.conversation_id)
      notifyConversationUpdated(event.conversation_id)
      return
    }

    if (event.type === "cancelled") {
      setMessages((current) =>
        current.map((message) =>
          message.id === localAssistantId
            ? {
                ...message,
                serverMessageId: event.message_id,
                status: "cancelled",
                errorCode: "user_cancelled",
              }
            : message,
        ),
      )
      clearRecovery()
      finishRequest(requestId, event.conversation_id)
      notifyConversationUpdated(event.conversation_id)
      return
    }

    if (OWNERSHIP_REJECTION_CODES.has(event.code)) {
      setMessages((current) =>
        current.filter((message) => message.id !== localUserId && message.id !== localAssistantId),
      )
      setDraft(lastFailedDraftRef.current)
      clearRecovery()
      setErrorMessage(event.message || "This conversation is already replying in another window.")
      finishRequest(requestId, event.conversation_id)
      return
    }

    setMessages((current) =>
      current.map((message) =>
        message.id === localAssistantId
          ? {
              ...message,
              serverMessageId: event.message_id,
              status: "error",
              errorCode: event.code,
            }
          : message,
      ),
    )
    setErrorMessage(event.message || "AI Chat streaming failed.")
    finishRequest(requestId, event.conversation_id)
    notifyConversationUpdated(event.conversation_id)
  }, [applyConversationId, clearRecovery, finishRequest, notifyConversationUpdated, queryClient])

  const sendMessage = useCallback((
    message = draft,
    baseMessages = messages,
  ) => {
    if (activeRequestRef.current !== null) return false
    if (conversationBusyElsewhere) {
      const surface = ownerSurface === "unknown" ? "another window" : ownerSurface
      setErrorMessage(`This conversation is already replying in ${surface}.`)
      return false
    }

    const normalized = message.trim()
    if (!normalized) return false

    const currentContext = contextRef.current
    if (contextModeRef.current === "reading" && !currentContext.source_text.trim()) {
      setErrorMessage("Reading-grounded Chat requires an attached selection.")
      return false
    }

    const requestId = requestCounterRef.current + 1
    requestCounterRef.current = requestId
    activeRequestRef.current = requestId
    lastFailedDraftRef.current = normalized
    clearRecovery()
    setActiveRequestId(requestId)
    setErrorMessage("")
    setDraft("")

    const localUserId = `user-local-${requestId}`
    const localAssistantId = `assistant-local-${requestId}`
    setMessages([
      ...baseMessages,
      {
        id: localUserId,
        role: "user",
        content: normalized,
        status: "complete",
      },
      {
        id: localAssistantId,
        role: "assistant",
        content: "",
        status: "streaming",
        knowledgeEnabled,
      },
    ])

    if (!sessionIdRef.current) {
      sessionIdRef.current = createCompanionScope("session")
    }
    if (!scopeRef.current) {
      scopeRef.current = createCompanionScope("companion")
    }

    const scopeId = scopeRef.current
    const payload = buildCompanionChatRequest({
      conversationId: conversationIdRef.current,
      sessionId: sessionIdRef.current,
      clientId,
      clientSurface,
      userMessage: normalized,
      contextMode: contextModeRef.current,
      context: currentContext,
      messages: baseMessages,
      requestId,
      knowledgeEnabled,
      knowledgeDocumentIds,
    })

    streamHandleRef.current = streamCompanionChat(payload, {
      onEvent: (event) =>
        handleStreamEvent(event, {
          scopeId,
          requestId,
          localUserId,
          localAssistantId,
        }),
      onTransportError: (error) => {
        if (scopeRef.current !== scopeId || activeRequestRef.current !== requestId) return
        setMessages((current) =>
          current.map((runtimeMessage) =>
            runtimeMessage.id === localAssistantId
              ? { ...runtimeMessage, status: "error", errorCode: "transport" }
              : runtimeMessage,
          ),
        )
        const persistedConversationId = conversationIdRef.current
        setRecoveryState(persistedConversationId ? "recovering" : "offline")
        setRecoveryDetail(
          persistedConversationId
            ? "Recovering persisted stream state…"
            : "The stream disconnected before a conversation was persisted. Your draft was restored.",
        )
        setErrorMessage(
          persistedConversationId
            ? `${error.message} Recovering persisted stream state…`
            : error.message,
        )
        finishRequest(requestId, persistedConversationId)
        if (persistedConversationId) {
          window.setTimeout(
            () => void recoverConversation(persistedConversationId, scopeId),
            250,
          )
        } else {
          setDraft(lastFailedDraftRef.current)
        }
      },
    })
    return true
  }, [
    clearRecovery,
    clientId,
    clientSurface,
    conversationBusyElsewhere,
    draft,
    finishRequest,
    handleStreamEvent,
    knowledgeDocumentIds,
    knowledgeEnabled,
    messages,
    ownerSurface,
    recoverConversation,
  ])

  const persistContextUpdate = useCallback(async (
    payload: ConversationContextUpdate,
    preferredContext?: CompanionContextSnapshot,
  ) => {
    const currentConversationId = conversationIdRef.current
    if (!currentConversationId || conversationBusyElsewhere) return null
    const updated = await updateConversationContext(currentConversationId, payload)
    const projected = projectPersistedContext(updated, preferredContext)
    applyContext(projected.context)
    applyContextMode(projected.contextMode)
    queryClient.setQueryData(
      queryKeys.conversations.detail(updated.conversation_id),
      updated,
    )
    void queryClient.invalidateQueries({ queryKey: ["conversations"] })
    return updated
  }, [applyContext, applyContextMode, conversationBusyElsewhere, queryClient])

  const attachReadingContext = useCallback(async (
    nextContext: CompanionContextSnapshot,
  ) => {
    if (activeRequestRef.current !== null || contextUpdating || conversationBusyElsewhere) return
    setContextUpdating(true)
    setErrorMessage("")
    try {
      if (conversationIdRef.current) {
        await persistContextUpdate({
          context_mode: "reading",
          source_text: nextContext.source_text,
          translated_text: nextContext.translated_text,
          source_language: nextContext.source_language,
          target_language: nextContext.target_language,
          resource_url: nextContext.resource_url,
          resource_title: nextContext.resource_title,
          application: nextContext.application,
          section_heading: nextContext.section_heading,
          context_before: nextContext.context_before,
          context_after: nextContext.context_after,
          source_kind: nextContext.source_kind,
        }, nextContext)
      } else {
        applyContext(nextContext)
        applyContextMode("reading")
      }
    } catch (error) {
      setErrorMessage(
        error instanceof Error ? error.message : "Unable to attach reading context.",
      )
    } finally {
      setContextUpdating(false)
    }
  }, [
    applyContext,
    applyContextMode,
    contextUpdating,
    conversationBusyElsewhere,
    persistContextUpdate,
  ])

  const attachSavedContext = useCallback(async () => {
    if (!contextRef.current.source_text.trim()) return
    await attachReadingContext(contextRef.current)
  }, [attachReadingContext])

  const detachReadingContext = useCallback(async () => {
    if (activeRequestRef.current !== null || contextUpdating || conversationBusyElsewhere) return
    setContextUpdating(true)
    setErrorMessage("")
    try {
      if (conversationIdRef.current) {
        await persistContextUpdate({ context_mode: "general" }, contextRef.current)
      } else {
        applyContextMode("general")
      }
    } catch (error) {
      setErrorMessage(
        error instanceof Error ? error.message : "Unable to detach reading context.",
      )
    } finally {
      setContextUpdating(false)
    }
  }, [applyContextMode, contextUpdating, conversationBusyElsewhere, persistContextUpdate])

  const rewriteFromUser = useCallback(async (
    userMessage: CompanionRuntimeMessage,
    replacementText: string,
  ) => {
    const currentConversationId = conversationIdRef.current
    const userMessageId = userMessage.serverMessageId || userMessage.id
    if (
      !currentConversationId ||
      !userMessageId ||
      userMessageId.startsWith("user-local-") ||
      activeRequestRef.current !== null ||
      conversationBusyElsewhere
    ) {
      return false
    }

    const normalized = replacementText.trim()
    if (!normalized) return false

    closeActiveStream()
    setErrorMessage("")
    try {
      const rewound = await rewindConversation(currentConversationId, userMessageId)
      applyConversation(rewound)
      const baseMessages = restoreCompanionMessages(rewound.messages)
      return sendMessage(normalized, baseMessages)
    } catch (error) {
      setErrorMessage(
        error instanceof Error ? error.message : "Unable to rewrite conversation branch.",
      )
      return false
    }
  }, [
    applyConversation,
    closeActiveStream,
    conversationBusyElsewhere,
    sendMessage,
  ])

  return {
    messages,
    draft,
    setDraft,
    errorMessage,
    clearError: () => setErrorMessage(""),
    activeRequestId,
    conversationId,
    context,
    contextMode,
    chatAvailable: chatStatusQuery.data?.available ?? false,
    chatStatusDetail: chatStatusQuery.data?.detail ?? "",
    chatStatusLoaded: chatStatusQuery.isSuccess,
    openingConversation,
    contextUpdating,
    knowledgeEnabled,
    setKnowledgeEnabled,
    knowledgeDocumentIds,
    setKnowledgeDocumentIds,
    conversationBusyElsewhere,
    ownerSurface,
    recoveryState,
    recoveryDetail,
    reset,
    openConversation,
    sendMessage,
    cancelStream: () => streamHandleRef.current?.cancel(),
    closeActiveStream,
    retryRecovery,
    attachReadingContext,
    attachSavedContext,
    detachReadingContext,
    rewriteFromUser,
  }
}
