import { useCallback, useEffect, useRef, useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Link, useSearchParams } from "react-router-dom"

import {
  dismissCompanionHandoff,
  getCompanionHandoff,
} from "../../api/companion"
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
  type CompanionRuntimeMessage,
} from "./companion-runtime"
import { companionLayoutClassNames } from "./companion-layout"
import ConversationHistoryPanel from "./ConversationHistoryPanel"
import { KnowledgeRetrievalControl } from "./components/KnowledgeRetrievalControl"
import { useCompanionConversationRuntime } from "./useCompanionConversationRuntime"

export default function CompanionWorkspaceV2() {
  const queryClient = useQueryClient()
  const [searchParams, setSearchParams] = useSearchParams()
  const [editingMessageId, setEditingMessageId] = useState("")
  const [editingText, setEditingText] = useState("")
  const [branchingMessageId, setBranchingMessageId] = useState("")
  const handoffIdRef = useRef("")
  const usingHandoffRef = useRef(false)

  const routedConversationId = searchParams.get("conversation") ?? ""

  const setConversationRoute = useCallback((conversationId: string) => {
    const next = new URLSearchParams(searchParams)
    if (conversationId) next.set("conversation", conversationId)
    else next.delete("conversation")
    setSearchParams(next, { replace: true })
  }, [searchParams, setSearchParams])

  const runtime = useCompanionConversationRuntime({
    onConversationAccepted: setConversationRoute,
  })
  const runtimeConversationId = runtime.conversationId
  const openRuntimeConversation = runtime.openConversation
  const resetRuntime = runtime.reset

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
    runtime.sendMessage()
  }

  const isKnowledgeContext = runtime.contextMode === "reading"
    && runtime.context.source_kind.startsWith("knowledge_")
  const contextTitle = runtime.contextMode === "general"
    ? "General Chat"
    : runtime.context.resource_title || runtime.context.section_heading || "Reading context"
  const canAttachSaved = Boolean(runtime.context.source_text)
  const branchBusy = Boolean(branchingMessageId) || runtime.activeRequestId !== null
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
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-400">
              Chat context
            </p>
            <h2 className="mt-2 truncate text-sm font-semibold text-slate-900">
              {contextTitle}
            </h2>
          </div>
          <Badge tone={runtime.contextMode === "reading" ? "info" : "neutral"}>
            {runtime.contextMode === "reading"
              ? isKnowledgeContext ? "Knowledge-grounded" : "Reading-grounded"
              : "General"}
          </Badge>
        </div>

        <div className="relative mt-4 grid grid-cols-2 overflow-hidden rounded-[14px] bg-slate-200/70 p-1">
          <span
            aria-hidden="true"
            className={`ait-segment-indicator absolute inset-y-1 left-1 w-[calc(50%-4px)] rounded-[11px] bg-white shadow-sm ${
              runtime.contextMode === "reading" ? "translate-x-full" : "translate-x-0"
            }`}
          />
          <button
            type="button"
            disabled={runtime.contextUpdating || runtime.activeRequestId !== null}
            className={`relative z-10 rounded-[11px] px-2 py-2 text-xs font-medium ${
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
            className={`relative z-10 rounded-[11px] px-2 py-2 text-xs font-medium disabled:opacity-40 ${
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

        <div key={runtime.contextMode} className="ait-context-panel-enter">
          {runtime.contextMode === "general" ? (
            <div className="mt-4 rounded-[16px] border border-slate-200/70 bg-white/85 p-3.5">
              <p className="text-xs font-medium text-slate-700">No reading context attached.</p>
              <p className="mt-1 text-xs leading-5 text-slate-500">
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
                <div className="mt-3 rounded-[16px] border border-cyan-100 bg-cyan-50/70 p-3.5">
                  <div className="flex items-center gap-2">
                    <Badge tone="info">{isKnowledgeContext ? "Knowledge Insight" : "Quick Action"}</Badge>
                    {runtime.context.ai_action && (
                      <span className="text-[10px] text-cyan-700/70">
                        {runtime.context.ai_action}
                      </span>
                    )}
                  </div>
                  <p className="mt-2 line-clamp-8 whitespace-pre-wrap text-xs leading-5 text-slate-700">
                    {runtime.context.ai_content}
                  </p>
                </div>
              )}
              {runtime.conversationId && (
                isKnowledgeContext ? (
                  <div className="mt-4 rounded-[13px] border border-slate-200 bg-slate-50 px-3 py-2.5 text-[10px] leading-5 text-slate-500">
                    This context already lives in canonical Knowledge. Continue the conversation here; use Agent Workspace when you want to save another linked Insight.
                  </div>
                ) : (
                  <div className="mt-4">
                    <Button
                      size="xs"
                      disabled={saveNoteMutation.isPending}
                      onClick={saveLinkedNote}
                    >
                      {saveNoteMutation.isPending ? "Saving…" : "Save linked note"}
                    </Button>
                    {saveNoteMutation.isSuccess && (
                      <p className="mt-2 text-[10px] text-emerald-600">
                        Research Note linked to this conversation.
                      </p>
                    )}
                  </div>
                )
              )}
            </>
          ) : (
            <p className="mt-4 text-xs leading-5 text-slate-500">
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
      </aside>

      <div className={companionLayoutClassNames.chatColumn}>
        <div className={companionLayoutClassNames.messageScroller}>
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
                  className={`ait-chat-message-enter ${message.role === "user"
                    ? "ml-auto max-w-[78%] rounded-[20px] bg-slate-950 px-4 py-3 text-sm leading-6 text-white shadow-sm"
                    : "max-w-[88%] rounded-[20px] border border-slate-100 bg-slate-50/85 px-4 py-3 text-sm leading-6 text-slate-700"}`}
                >
                  {message.role === "assistant" ? (
                    <>
                      {message.content ? (
                        <div className="max-w-none">
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
                          Waiting for the first token…
                        </div>
                      ) : (
                        <p className="text-slate-400">
                          {message.status === "cancelled" ? "Generation stopped." : "No response content."}
                        </p>
                      )}
                      <div className="mt-2 flex flex-wrap items-center gap-2">
                        {message.status === "streaming" && <Badge tone="info">Streaming</Badge>}
                        {message.status === "cancelled" && <Badge tone="warning">Stopped</Badge>}
                        {message.status === "error" && <Badge tone="danger">Failed</Badge>}
                        {message.status === "complete" && message.provider && (
                          <Badge tone="success">
                            {message.provider}{message.model ? ` · ${message.model}` : ""}
                          </Badge>
                        )}
                        {message.status === "complete" && message.knowledgeEnabled && (
                          <Badge tone={(message.evidence?.length ?? 0) > 0 ? "info" : "warning"}>
                            {(message.evidence?.length ?? 0) > 0
                              ? `Knowledge · ${message.evidence?.length} sources`
                              : "General answer · No knowledge sources"}
                          </Badge>
                        )}
                        {userBefore && message.status !== "streaming" && (
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
                        <div className="mt-2 text-right">
                          <button
                            type="button"
                            disabled={branchBusy}
                            className="text-[10px] text-slate-400 hover:text-white disabled:opacity-40"
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
              <p className="rounded-xl bg-rose-50 px-4 py-3 text-sm text-rose-700">
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
            <p className="mb-2 rounded-lg bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-700">
              AI Chat 未配置：{runtime.chatStatusDetail}
            </p>
          )}
          <div className="mb-2 flex flex-wrap gap-1.5">
            <Badge tone={runtime.contextMode === "reading" ? "info" : "neutral"}>
              {runtime.contextMode === "reading" ? isKnowledgeContext ? "Knowledge Card" : "Reading" : "General"}
            </Badge>
            {runtime.knowledgeEnabled && (
              <Badge tone="info">
                Knowledge · {runtime.knowledgeDocumentIds.length > 0
                  ? `${runtime.knowledgeDocumentIds.length} selected`
                  : "All"}
              </Badge>
            )}
          </div>
          <div className="flex items-end gap-2">
            <textarea
              className="max-h-36 min-h-12 flex-1 resize-none rounded-[16px] border border-slate-200/80 bg-slate-50/85 px-3.5 py-2.5 text-sm leading-6 outline-none transition focus:border-slate-400 focus:bg-white disabled:cursor-not-allowed disabled:opacity-60"
              placeholder={runtime.activeRequestId === null
                ? runtime.contextMode === "general" ? "Ask anything…" : "继续问这段内容…"
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
            {runtime.activeRequestId !== null ? (
              <Button type="button" variant="danger" size="md" onClick={runtime.cancelStream}>
                停止
              </Button>
            ) : (
              <Button
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
                发送
              </Button>
            )}
          </div>
          <p className="mt-2 text-[10px] text-slate-400">
            Enter 发送 · Shift+Enter 换行 · {runtime.contextMode === "reading" ? isKnowledgeContext ? "Knowledge context" : "Reading context" : "General"}{runtime.knowledgeEnabled ? " · Knowledge ON" : ""} · Shared Companion Runtime
          </p>
        </form>
      </div>
    </section>
  )
}

function ContextPreview({ context }: { context: CompanionContextSnapshot }) {
  const knowledgeContext = context.source_kind.startsWith("knowledge_")
  return (
    <div className="mt-4 space-y-3">
      <div className="rounded-[16px] border border-slate-200/70 bg-white/85 p-3.5">
        <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">
          {knowledgeContext ? "Knowledge card" : "Selection"}
        </p>
        <p className="mt-2 line-clamp-8 text-xs leading-5 text-slate-700">
          {context.source_text}
        </p>
      </div>
      {context.translated_text && (
        <div className="rounded-[16px] border border-slate-200/70 bg-white/85 p-3.5">
          <p className="text-[10px] font-semibold uppercase tracking-[0.14em] text-slate-400">
            Translation
          </p>
          <p className="mt-2 line-clamp-7 text-xs leading-5 text-slate-600">
            {context.translated_text}
          </p>
        </div>
      )}
    </div>
  )
}
